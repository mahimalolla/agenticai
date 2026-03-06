"""
User Agent — Intent Classification.

Takes raw natural language and produces a structured Intent object.
Uses Claude Sonnet for fast, cost-effective NLU.

This is the first agent in the pipeline. Its output drives
tool matching and SQL generation downstream.
"""

import json
import anthropic

from core.config import Config
from core.models import Intent, TraceStep


class UserAgent:
    def __init__(self, client: anthropic.Anthropic, config: Config):
        self.client = client
        self.model_cfg = config.models["user_agent"]

    def classify(self, query: str) -> tuple[Intent, list[TraceStep]]:
        """
        Classify a natural language query into a structured Intent.

        Returns:
            (Intent, trace_steps) — the parsed intent + audit trail
        """
        trace = []
        trace.append(TraceStep("user_agent", "received_query", query))

        prompt = self._build_prompt(query)

        try:
            # Call Sonnet for classification
            resp = self.client.messages.create(
                model=self.model_cfg["model"],
                max_tokens=self.model_cfg["max_tokens"],
                temperature=self.model_cfg["temperature"],
                messages=[{"role": "user", "content": prompt}]
            )

            # Parse JSON response
            raw = resp.content[0].text.strip()
            raw = raw.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(raw)

            # Map to Intent dataclass
            intent = Intent(
                query_type=parsed.get("query_type", "metric_lookup"),
                entities=parsed.get("entities", []),
                time_period=parsed.get("time_period", "last_28d"),
                constraints=parsed.get("constraints", []),
                confidence=parsed.get("confidence", 0.5),
                raw_query=query
            )

            trace.append(TraceStep(
                "user_agent", "intent_classified",
                f"type={intent.query_type} | entities={intent.entities} | confidence={intent.confidence}",
                metadata=parsed
            ))
            return intent, trace

        except Exception as e:
            # Graceful degradation: return low-confidence default
            trace.append(TraceStep("user_agent", "classification_error", str(e)))
            return Intent(raw_query=query, confidence=0.3), trace

    def _build_prompt(self, query: str) -> str:
        """Build the classification prompt for Sonnet."""
        return f"""Classify this data query and extract structured information.
Respond ONLY with a JSON object (no markdown, no backticks) with these keys:
- query_type: one of [metric_lookup, trend_analysis, comparison, ranking, anomaly_detection, list_filter]
- entities: array of business objects mentioned (e.g., ["customers", "orders", "margin"])
- time_period: detected time period or "last_28d" if none mentioned
- constraints: array of filter conditions mentioned (e.g., ["status = completed", "region = EU"])
- confidence: float 0-1 indicating how clear the query is

Query: "{query}"
"""