"""
Data Agent — the core intelligence layer.

Handles two paths:
  1. Tool execution: matched tool --> extract params --> invoke tool --> return result
  2. SQL fallback: no tool --> retrieve similar examples --> Opus generates SQL --> validate

This is where Opus 4.6 runs. It's the most expensive call but also
the most critical, wrong SQL here means wrong business decisions.
"""

import json
import re
import hashlib
import anthropic

from core.config import Config
from core.models import Route, Intent, ToolMatch, TraceStep
from core.tool_registry import ToolRegistry
from core.retrieval import RetrievalIndex
from core.sql_validator import SQLValidator


class DataAgent:
    def __init__(
        self,
        client: anthropic.Anthropic,
        config: Config,
        tool_registry: ToolRegistry,
        retrieval_index: RetrievalIndex
    ):
        self.client = client
        self.model_cfg = config.models["data_agent"]
        self.config = config
        self.tools = tool_registry
        self.retrieval = retrieval_index
        self.validator = SQLValidator(config)

    def execute_tool(self, tool: ToolMatch, intent: Intent) -> tuple[dict, list[TraceStep]]:
        """
        Execute a matched tool: extract params --> build invocation --> run.

        In production, the invocation dict would be sent to your tool runtime
        (API endpoint, Lambda, K8s job, etc.). Currently returns the tool's
        SQL template as a demo.
        """
        trace = []
        trace.append(TraceStep(
            "data_agent", "tool_matched",
            f"{tool.name}@{tool.version} (score: {tool.score:.2f})"
        ))

        # Extract parameters from the query using Opus
        params = self._extract_params(intent.raw_query, tool)
        tool.params = params
        trace.append(TraceStep("data_agent", "params_extracted", json.dumps(params)))

        # Build invocation request (matches design doc format)
        invocation = {
            "tool": f"{tool.name}@{tool.version}",
            "inputs": params,
            "context": {"user_id": "u123", "region_whitelist": ["EU", "NA"]}
        }
        trace.append(TraceStep("data_agent", "tool_invoked", json.dumps(invocation, indent=2)))

        # Execute tool
        # TODO: Replace with actual tool runtime call
        sql_fallback = tool.manifest.get("sql_fallback", "")
        result = {
            "status": "ok",
            "route": Route.SEMANTIC_FIRST.value,
            "tool": tool.name,
            "version": tool.version,
            "params": params,
            "sql_template": sql_fallback,
            "evidence": {
                "manifest": f"{tool.name}@{tool.version}",
                "semantic_objects": (
                    tool.manifest.get("semantic_binding", {}).get("metrics", [])
                    + tool.manifest.get("semantic_binding", {}).get("dimensions", [])
                )
            }
        }
        trace.append(TraceStep("data_agent", "tool_executed", "Route: semantic_first"))
        return result, trace

    def generate_sql(self, query: str, intent: Intent) -> tuple[dict, list[TraceStep]]:
        """
        SQL fallback: retrieve similar examples --> build prompt --> call Opus --> validate.

        This is where data pairs are used as few-shot context.
        """
        trace = []
        trace.append(TraceStep(
            "data_agent", "sql_fallback_triggered",
            "No tool match — generating SQL"
        ))

        # Step 1: Retrieve similar examples from training data
        examples = self.retrieval.retrieve(query)
        trace.append(TraceStep(
            "data_agent", "examples_retrieved",
            f"{len(examples)} similar queries found",
            metadata={"examples": [
                {"query": e["text_query"], "sim": e["similarity"]}
                for e in examples[:3]
            ]}
        ))

        # Step 2: Build the Opus prompt (schema + examples + rules)
        system_prompt = self._build_sql_prompt(examples)
        trace.append(TraceStep(
            "data_agent", "prompt_built",
            f"Schema + {len(examples)} examples → Opus"
        ))

        # Step 3: Call Opus API
        try:
            resp = self.client.messages.create(
                model=self.model_cfg["model"],
                max_tokens=self.model_cfg["max_tokens"],
                temperature=self.model_cfg["temperature"],
                system=system_prompt,
                messages=[{"role": "user", "content": f'Write SQL for: "{query}"'}]
            )
            sql = resp.content[0].text.strip()
            sql = sql.replace("```sql", "").replace("```", "").strip()
            input_tokens = resp.usage.input_tokens
            output_tokens = resp.usage.output_tokens
        except Exception as e:
            trace.append(TraceStep("data_agent", "api_error", str(e)))
            return {"status": "error", "error": str(e)}, trace

        trace.append(TraceStep("data_agent", "sql_generated", sql))

        # Step 4: Validate the generated SQL
        validation = self.validator.validate(sql)

        if not validation["valid"]:
            trace.append(TraceStep(
                "data_agent", "validation_failed",
                "; ".join(validation["errors"])
            ))
            return {
                "status": "error",
                "errors": validation["errors"],
                "sql": sql
            }, trace

        if validation["warnings"]:
            trace.append(TraceStep(
                "data_agent", "validation_warnings",
                "; ".join(validation["warnings"])
            ))
            sql = validation["cleaned_sql"]

        trace.append(TraceStep("data_agent", "validation_passed", "Syntax ✓ | Security ✓"))

        # Step 5: Build response with evidence
        fingerprint = hashlib.sha256(sql.encode()).hexdigest()[:16]
        result = {
            "status": "ok",
            "route": Route.SQL_FALLBACK.value,
            "sql": sql,
            "evidence": {
                "route": "sql_fallback",
                "sql_fingerprint": f"sha256:{fingerprint}",
                "examples_used": len(examples),
                "top_example_similarity": examples[0]["similarity"] if examples else 0,
            },
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": round(
                    input_tokens * 15 / 1e6 + output_tokens * 75 / 1e6, 6
                )
            }
        }
        return result, trace

    def _extract_params(self, query: str, tool: ToolMatch) -> dict:
        """Use Opus to extract tool input parameters from the query."""
        inputs_desc = json.dumps(tool.manifest.get("inputs", {}), indent=2)
        prompt = (
            f'Extract parameter values from this query for the tool "{tool.name}".\n\n'
            f"Tool inputs schema:\n{inputs_desc}\n\n"
            f'Query: "{query}"\n\n'
            f"Respond ONLY with a JSON object mapping parameter names to values.\n"
            f"Use defaults from the schema if the query doesn't specify a value."
        )
        try:
            resp = self.client.messages.create(
                model=self.model_cfg["model"],
                max_tokens=256,
                temperature=0,
                messages=[{"role": "user", "content": prompt}]
            )
            raw = resp.content[0].text.strip()
            raw = raw.replace("```json", "").replace("```", "").strip()
            return json.loads(raw)
        except Exception:
            return self._extract_params_fallback(query, tool)

    def _extract_params_fallback(self, query: str, tool: ToolMatch) -> dict:
        """Regex-based parameter extraction when Opus is unavailable."""
        params = {}
        for pname, pdef in tool.manifest.get("inputs", {}).items():
            if isinstance(pdef, dict) and "default" in pdef:
                params[pname] = pdef["default"]
        n_match = re.search(r"top\s+(\d+)", query, re.I)
        if n_match and "n" in tool.manifest.get("inputs", {}):
            params["n"] = int(n_match.group(1))
        return params

    def _build_sql_prompt(self, examples: list[dict]) -> str:
        """Build the system prompt for SQL generation."""
        few_shot = "\n\n".join([
            f"Question: {e['text_query']}\nSQL: {e['sql_command']}"
            for e in examples
        ])
        return (
            "You are an expert SQL generator for an enterprise data warehouse.\n\n"
            f"DATABASE SCHEMA:\n{self.config.schema}\n\n"
            "RULES:\n"
            "1. ONLY use tables and columns defined in the schema above.\n"
            "2. Use explicit JOIN syntax with ON clauses.\n"
            "3. Use meaningful table aliases.\n"
            "4. Add LIMIT unless the query uses aggregation on all rows.\n"
            "5. Use ISO date format for date comparisons.\n"
            "6. If the question is ambiguous, choose the most likely interpretation.\n"
            "7. Return ONLY the SQL query — no explanation, no markdown fences.\n\n"
            f"SIMILAR PAST QUERIES FOR REFERENCE:\n{few_shot}"
        )