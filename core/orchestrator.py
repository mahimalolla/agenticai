"""
Orchestrator, the central router.

Ties all agents together into a single pipeline:
  User Agent (classify) --> Tool Registry (match) --> Data Agent (execute or generate)

Handles routing decisions, access control, trace collection,
and response assembly.
"""

import time
import hashlib
import anthropic
from rich.console import Console

from core.config import Config
from core.models import TraceStep, AgentResponse
from core.retrieval import RetrievalIndex
from core.tool_registry import ToolRegistry
from core.user_agent import UserAgent
from core.data_agent import DataAgent

console = Console()


class Orchestrator:
    def __init__(self, config_path: str = "config.yaml"):
        # Load configuration
        self.config = Config(config_path)

        # Create shared Anthropic client (one connection pool for all agents)
        self.client = anthropic.Anthropic()

        # Initialize components (retrieval index is lazy-loaded)
        self.retrieval = RetrievalIndex(self.config)
        self.tool_registry = ToolRegistry(self.config)
        self.user_agent = UserAgent(self.client, self.config)
        self.data_agent = DataAgent(
            self.client, self.config,
            self.tool_registry, self.retrieval
        )
        self._initialized = False

    def initialize(self):
        """Load embedding model and build FAISS index. Call once at startup."""
        if not self._initialized:
            self.retrieval.load()
            self._initialized = True
            console.log("[bold green]✓ Orchestrator initialized[/]")

    def process(self, query: str, user_context: dict = None) -> AgentResponse:
        """
        Main entry point: process a natural language query through the full pipeline.

        Args:
            query: Natural language question from the user
            user_context: Auth info — user_id, roles, region_whitelist

        Returns:
            AgentResponse with results, SQL, evidence, trace, and cost
        """
        self.initialize()
        start = time.time()
        all_trace = []

        # Generate unique request ID for audit
        request_id = f"req_{hashlib.md5(f'{query}{time.time()}'.encode()).hexdigest()[:12]}"

        # Default user context (in production, comes from your auth system)
        user_context = user_context or {
            "user_id": "u123",
            "roles": ["analyst"],
            "region_whitelist": ["EU", "NA"]
        }

        # ── Phase 1: User Agent — Intent Classification ──────────
        console.log("\n[bold purple]▸ User Agent[/] — classifying intent...")
        intent, user_trace = self.user_agent.classify(query)
        all_trace.extend(user_trace)

        # ── Phase 2: Orchestrator — Routing Decision ─────────────
        all_trace.append(TraceStep(
            "orchestrator", "routing",
            "Strategy: semantic_first → sql_fallback"
        ))

        # ── Phase 3: Data Agent — Tool Match or SQL Fallback ─────
        console.log("[bold red]▸ Data Agent[/] — searching tool registry...")
        tool_match = self.tool_registry.match(query, intent)

        if tool_match:
            # Check access control before executing
            result, data_trace = self._execute_with_acl(
                tool_match, intent, user_context, all_trace, request_id, start
            )
            if isinstance(result, AgentResponse):
                return result  # Access denied — early return
            all_trace.extend(data_trace)
        else:
            # No tool match --> SQL fallback
            console.log("[bold yellow]  ✗ No tool match[/] — falling back to SQL generation")
            result, data_trace = self.data_agent.generate_sql(query, intent)
            all_trace.extend(data_trace)

        # ── Phase 4: Format & Return Response ────────────────────
        all_trace.append(TraceStep(
            "orchestrator", "response_formatted",
            "Assembling final response"
        ))
        elapsed = int((time.time() - start) * 1000)

        return AgentResponse(
            status=result.get("status", "ok"),
            route=result.get("route", "unknown"),
            request_id=request_id,
            data=result,
            sql=result.get("sql", result.get("sql_template", "")),
            evidence=result.get("evidence", {}),
            trace=all_trace,
            cost_usd=result.get("usage", {}).get("cost_usd", 0),
            elapsed_ms=elapsed
        )

    def _execute_with_acl(self, tool_match, intent, user_context, all_trace, request_id, start):
        """
        Execute a tool with access control check.

        Returns either:
          - (result_dict, trace_steps) on success
          - AgentResponse on access denied (early return)
        """
        acl = tool_match.manifest.get("access_control", {})
        allowed_roles = acl.get("roles", [])
        user_roles = user_context.get("roles", [])

        if allowed_roles and not any(r in allowed_roles for r in user_roles):
            all_trace.append(TraceStep(
                "orchestrator", "access_denied",
                f"User roles {user_roles} not in {allowed_roles}"
            ))
            return AgentResponse(
                status="error",
                route="access_denied",
                request_id=request_id,
                data={"error": "Insufficient permissions for this tool"},
                trace=all_trace,
                elapsed_ms=int((time.time() - start) * 1000)
            ), []

        console.log(f"[bold green]  ✓ Tool matched:[/] {tool_match.name}@{tool_match.version}")
        return self.data_agent.execute_tool(tool_match, intent)