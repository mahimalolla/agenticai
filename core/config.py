"""
Configuration loader.

Reads config.yaml and provides clean accessors for each section.
Single source of truth for models, tools, schema, security, and retrieval settings.
"""

import os
import yaml


class Config:
    def __init__(self, path: str = "config.yaml"):
        with open(path) as f:
            self._cfg = yaml.safe_load(f)

    @property
    def models(self) -> dict:
        """Model assignments for each agent (user_agent, data_agent, orchestrator)."""
        return self._cfg["models"]


    @property
    def tools(self) -> list:
        """List of registered tool manifests."""
        return self._cfg.get("tools", [])

    @property
    def schema(self) -> str:
        """
        Database schema as a string of CREATE TABLE statements.
        Checks for an external .sql file first, falls back to inline config.
        """
        s = self._cfg.get("schema", {})
        if s.get("schema_file") and os.path.exists(s["schema_file"]):
            with open(s["schema_file"]) as f:
                return f.read()
        return s.get("inline", "")

    @property
    def retrieval(self) -> dict:
        """Settings for the embedding model, training data path, top_k, etc."""
        return self._cfg.get("retrieval", {})

    @property
    def security(self) -> dict:
        """SQL validation rules: blocked patterns, LIMIT requirements, max rows."""
        return self._cfg.get("security", {})

    @property
    def routing(self) -> dict:
        """Routing thresholds: tool match threshold, ambiguity threshold, fallback strategy."""
        return self._cfg.get("routing", {})