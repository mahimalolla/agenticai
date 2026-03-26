"""
Data Agent — the core intelligence layer.

Handles two paths:
  1. Tool execution: matched tool --> extract params --> resolve period --> execute SQL --> return rows
  2. SQL fallback: no tool --> retrieve similar examples --> Opus generates SQL --> validate --> execute --> return rows

This is where Opus 4.6 runs. It's the most expensive call but also
the most critical, wrong SQL here means wrong business decisions.
"""

import json
import re
import hashlib
import anthropic
from datetime import datetime, timedelta, date

from core.config import Config
from core.models import Route, Intent, ToolMatch, TraceStep
from core.tool_registry import ToolRegistry
from core.retrieval import RetrievalIndex
from core.sql_validator import SQLValidator
from core.db import DatabaseManager


class DataAgent:
    def __init__(
        self,
        client: anthropic.Anthropic,
        config: Config,
        tool_registry: ToolRegistry,
        retrieval_index: RetrievalIndex,
        db: DatabaseManager,
    ):
        self.client = client
        self.model_cfg = config.models["data_agent"]
        self.config = config
        self.tools = tool_registry
        self.retrieval = retrieval_index
        self.validator = SQLValidator(config)
        self.db = db

    def execute_tool(self, tool: ToolMatch, intent: Intent) -> tuple[dict, list[TraceStep]]:
        """
        Execute a matched tool: extract params --> resolve period --> execute SQL --> return rows.
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

        # Resolve period label (e.g. "last_28d") into period_start / period_end
        # that the sql_fallback template expects as :period_start and :period_end
        resolved = self._resolve_params(params)
        trace.append(TraceStep(
            "data_agent", "params_resolved",
            json.dumps({k: str(v) for k, v in resolved.items()})
        ))

        # Build invocation record for audit trail
        invocation = {
            "tool": f"{tool.name}@{tool.version}",
            "inputs": params,
            "context": {"user_id": "u123", "region_whitelist": ["EU", "NA"]}
        }
        trace.append(TraceStep("data_agent", "tool_invoked", json.dumps(invocation, indent=2)))

        # Execute the tool's vetted SQL template against the database
        sql = tool.manifest.get("sql_fallback", "")
        try:
            rows = self.db.execute(sql, resolved)
            trace.append(TraceStep(
                "data_agent", "tool_executed",
                f"Route: semantic_first | {len(rows)} rows returned"
            ))
        except Exception as e:
            trace.append(TraceStep("data_agent", "execution_error", str(e)))
            return {"status": "error", "error": str(e)}, trace

        result = {
            "status": "ok",
            "route": Route.SEMANTIC_FIRST.value,
            "tool": tool.name,
            "version": tool.version,
            "params": params,
            "sql_template": sql,
            "rows": rows,
            "evidence": {
                "manifest": f"{tool.name}@{tool.version}",
                "semantic_objects": (
                    tool.manifest.get("semantic_binding", {}).get("metrics", [])
                    + tool.manifest.get("semantic_binding", {}).get("dimensions", [])
                )
            }
        }
        return result, trace

    def generate_sql(self, query: str, intent: Intent) -> tuple[dict, list[TraceStep]]:
        """
        SQL fallback: retrieve similar examples --> build prompt --> call Opus --> validate --> execute.
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

        # Step 5: Execute the validated SQL
        # Opus generates self-contained SQL (hardcoded dates, no :param placeholders),
        # so params is empty here. The execute() call is still the single execution path.
        try:
            rows = self.db.execute(sql)
            trace.append(TraceStep(
                "data_agent", "sql_executed",
                f"{len(rows)} rows returned"
            ))
        except Exception as e:
            trace.append(TraceStep("data_agent", "execution_error", str(e)))
            return {"status": "error", "error": str(e), "sql": sql}, trace

        # Step 6: Build response with evidence
        fingerprint = hashlib.sha256(sql.encode()).hexdigest()[:16]
        result = {
            "status": "ok",
            "route": Route.SQL_FALLBACK.value,
            "sql": sql,
            "rows": rows,
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

    def _resolve_params(self, params: dict) -> dict:
        """
        Expand tool input params into the form the sql_fallback template expects.

        Tool manifests declare inputs like period="last_28d" and n=25, but the
        sql_fallback SQL uses :period_start, :period_end, :n, :granularity, etc.
        This method bridges that gap so db.execute() receives the right keys.

        Period labels → (period_start, period_end) datetime boundaries:
          last_7d   → today-7d  → today
          last_28d  → today-28d → today
          mtd       → first of this month → today
          qtd       → first of this quarter → today
          ytd       → Jan 1 this year → today
          custom    → Opus supplies period_start + period_end as ISO date strings;
                      parsed here into datetimes. Falls back to last_28d if either
                      boundary is missing or unparseable.

        All other params (n, granularity, threshold_days, top_n, etc.)
        are passed through as-is.
        """
        resolved = dict(params)   # copy so we don't mutate the original
        today = date.today()
        period = params.get("period")

        if period == "custom":
            # Opus should have provided period_start and period_end as ISO strings.
            # Parse them into datetimes. If either is missing or malformed, fall
            # back to last_28d so the query still executes rather than crashing.
            try:
                period_start = date.fromisoformat(str(params["period_start"]))
                period_end   = date.fromisoformat(str(params["period_end"]))
            except (KeyError, ValueError):
                period_start = today - timedelta(days=28)
                period_end   = today

            resolved["period_start"] = datetime.combine(period_start, datetime.min.time())
            resolved["period_end"]   = datetime.combine(period_end,   datetime.max.time())
            # Remove all three — sql_fallback uses :period_start/:period_end only
            resolved.pop("period",       None)
            resolved.pop("period_start", None)
            resolved.pop("period_end",   None)

        elif period:
            if period == "last_7d":
                period_start = today - timedelta(days=7)
            elif period == "last_28d":
                period_start = today - timedelta(days=28)
            elif period == "mtd":
                period_start = today.replace(day=1)
            elif period == "qtd":
                quarter_start_month = ((today.month - 1) // 3) * 3 + 1
                period_start = today.replace(month=quarter_start_month, day=1)
            elif period == "ytd":
                period_start = today.replace(month=1, day=1)
            else:
                period_start = today - timedelta(days=28)   # safe fallback

            resolved["period_start"] = datetime.combine(period_start, datetime.min.time())
            resolved["period_end"]   = datetime.combine(today,        datetime.max.time())
            del resolved["period"]   # remove the label; sql_fallback doesn't use :period

        return resolved

    def _extract_params(self, query: str, tool: ToolMatch) -> dict:
        """Use Opus to extract tool input parameters from the query."""
        inputs_desc = json.dumps(tool.manifest.get("inputs", {}), indent=2)
        prompt = (
            f'Extract parameter values from this query for the tool "{tool.name}".\n\n'
            f"Tool inputs schema:\n{inputs_desc}\n\n"
            f'Query: "{query}"\n\n'
            f"Respond ONLY with a JSON object mapping parameter names to values.\n"
            f"Use defaults from the schema if the query doesn't specify a value.\n\n"
            f"IMPORTANT: If the query specifies an explicit date range (e.g. 'between Jan 1 and Feb 15',\n"
            f"'from March to April', 'since last Tuesday'), set period to 'custom' and also include\n"
            f"period_start and period_end as ISO 8601 date strings (YYYY-MM-DD).\n"
            f"Today's date is {date.today().isoformat()}."
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
        """
        Regex-based parameter extraction when Opus is unavailable.

        Handles the custom period case by looking for ISO dates (YYYY-MM-DD)
        in the query. If two are found, sets period=custom with both boundaries.
        If one is found, treats it as period_start with today as period_end.
        """
        params = {}
        for pname, pdef in tool.manifest.get("inputs", {}).items():
            if isinstance(pdef, dict) and "default" in pdef:
                params[pname] = pdef["default"]

        # Top-N extraction
        n_match = re.search(r"top\s+(\d+)", query, re.I)
        if n_match and "n" in tool.manifest.get("inputs", {}):
            params["n"] = int(n_match.group(1))

        # Custom date range extraction — looks for YYYY-MM-DD patterns
        if "period" in tool.manifest.get("inputs", {}):
            dates = re.findall(r"\b(\d{4}-\d{2}-\d{2})\b", query)
            if len(dates) >= 2:
                params["period"]       = "custom"
                params["period_start"] = dates[0]
                params["period_end"]   = dates[1]
            elif len(dates) == 1:
                params["period"]       = "custom"
                params["period_start"] = dates[0]
                params["period_end"]   = date.today().isoformat()

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