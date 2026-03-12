"""
Tool registry for semantic-first routing.

Each tool is a versioned manifest (defined in config.yaml) that represents
a trusted business query. The registry matches user queries against tools
using keyword overlap + semantic binding scores.

If a tool matches, its vetted SQL is used instead of generating from scratch.
This is the core of the "entity as a tool" pattern from the design doc.
"""

from typing import Optional

from core.config import Config
from core.models import Intent, ToolMatch


class ToolRegistry:
    def __init__(self, config: Config):
        self.tools = config.tools
        self.threshold = config.routing.get("tool_match_threshold", 0.15)

    def match(self, query: str, intent: Intent) -> Optional[ToolMatch]:
        """
        Score each registered tool against the query and return the best match.

        Scoring formula: 60% keyword match + 40% semantic binding match.
        Returns None if no tool exceeds the threshold.
        """
        q_lower = query.lower()
        best_match = None
        best_score = 0.0

        for tool in self.tools:
            kws = tool.get("keywords", [])
            metrics = tool.get("semantic_binding", {}).get("metrics", [])
            dims = tool.get("semantic_binding", {}).get("dimensions", [])

            # Keyword match: how many tool keywords appear in the query?
            kw_hits = sum(1 for k in kws if k.lower() in q_lower)
            kw_score = kw_hits / max(len(kws), 1)

            # Semantic binding match: do metrics/dimensions match intent entities?
            entity_str = " ".join(intent.entities).lower()
            met_hits = sum(1 for m in metrics if m in q_lower or m in entity_str)
            dim_hits = sum(1 for d in dims if d in q_lower or d in entity_str)
            sem_score = (met_hits + dim_hits) / max(len(metrics) + len(dims), 1)

            # Combined score 
            score = kw_score * 0.6 + sem_score * 0.4

            if score > best_score:
                best_score = score
                best_match = tool

        # Return match only if above threshold
        if best_match and best_score >= self.threshold:
            return ToolMatch(
                name=best_match["name"],
                version=best_match["version"],
                score=best_score,
                manifest=best_match,
                params={}
            )
        return None

    def get_tool(self, name: str) -> Optional[dict]:
        """Look up a tool by name."""
        for t in self.tools:
            if t["name"] == name:
                return t
        return None