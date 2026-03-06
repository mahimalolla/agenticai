"""
Data classes used across all agents.

These are plain data containers.
Every agent reads and writes these structures.
"""

import time
from dataclasses import dataclass, field
from enum import Enum


class Route(str, Enum):
    """The three possible paths a query can take."""
    SEMANTIC_FIRST = "semantic_first"
    SQL_FALLBACK = "sql_fallback"
    ESCALATE = "escalate"


@dataclass
class Intent:
    """
    Structured output from the User Agent.
    Converts raw English into typed fields the rest of the system can use.
    """
    query_type: str = "metric_lookup"       # metric_lookup, trend_analysis, comparison, ranking, anomaly_detection, list_filter
    entities: list = field(default_factory=list)          # ["customers", "margin", "orders"]
    time_period: str = "last_28d"           # last_7d, last_28d, mtd, qtd, ytd, custom
    constraints: list = field(default_factory=list)       # ["status = completed", "region = EU"]
    confidence: float = 0.0                 # 0-1, how clear the query is
    raw_query: str = ""                     # Original user input


@dataclass
class ToolMatch:
    """
    Result of matching a query against the tool registry.
    Contains the matched tool's manifest and extracted parameters.
    """
    name: str = ""                          # e.g., "orders.top_customers"
    version: str = ""                       # e.g., "2.1.0"
    score: float = 0.0                      # Match confidence 0-1
    manifest: dict = field(default_factory=dict)          # Full tool definition from config
    params: dict = field(default_factory=dict)            # Extracted input parameters


@dataclass
class TraceStep:
    """
    Single step in the audit trail.
    Every action by any agent is logged as a TraceStep.
    """
    agent: str                              # "user_agent", "data_agent", "orchestrator"
    action: str                             # "intent_classified", "tool_matched", etc.
    detail: str                             # Human-readable description
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)          # Optional structured data


@dataclass
class AgentResponse:
    """
    Final output of the entire pipeline.
    Contains everything needed for display, audit, and downstream processing.
    """
    status: str = "ok"                      # "ok" or "error"
    route: str = ""                         # Which path was taken
    request_id: str = ""                    # Unique ID for audit
    data: dict = field(default_factory=dict)              # Full result payload
    sql: str = ""                           # Generated SQL (if sql_fallback route)
    evidence: dict = field(default_factory=dict)          # Audit metadata
    trace: list = field(default_factory=list)             # Complete list of TraceSteps
    cost_usd: float = 0.0                  # Total API cost
    elapsed_ms: int = 0                     # Wall-clock time