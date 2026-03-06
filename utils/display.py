"""
Rich terminal display helpers and evaluation runner.

Separated from core logic because display is a presentation concern —
you might swap this out for a web UI, API response formatter, etc.
"""

import json
import sqlparse
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from core.models import AgentResponse
from core.orchestrator import Orchestrator

console = Console()

# Agent name --> terminal color mapping
AGENT_STYLES = {
    "user_agent": "purple",
    "data_agent": "red",
    "orchestrator": "green",
    "sql_fallback": "blue",
}


def display_response(resp: AgentResponse):
    """Pretty-print an AgentResponse to the terminal."""

    # Trace
    console.print("\n[bold]═══ Agent Trace ═══[/]")
    for step in resp.trace:
        color = AGENT_STYLES.get(step.agent, "white")
        detail = step.detail[:120]
        console.print(f"  [{color}]■ {step.agent}[/{color}] → {step.action}: {detail}")

    # Result summary 
    route_color = "green" if resp.route == "semantic_first" else "blue"
    console.print(f"\n[bold]═══ Result ═══[/]")
    console.print(f"  Route:      [{route_color}]{resp.route}[/{route_color}]")
    console.print(f"  Request ID: {resp.request_id}")
    console.print(f"  Elapsed:    {resp.elapsed_ms}ms")

    # SQL (if present)
    if resp.sql:
        formatted = sqlparse.format(resp.sql, reindent=True, keyword_case="upper")
        console.print(Panel(formatted, title="Generated SQL", border_style="blue"))

    # Evidence
    if resp.evidence:
        console.print(f"  Evidence:   {json.dumps(resp.evidence, indent=2)}")

    # Cost
    if resp.cost_usd > 0:
        console.print(f"  API Cost:   ${resp.cost_usd:.6f}")


def run_eval(orchestrator: Orchestrator, n: int = 20):
    """
    Run evaluation on a set of test queries.

    Tests both routing accuracy (did it pick the right path?)
    and collects cost/latency metrics.
    """
    test_queries = [
        # Should match tools (semantic_first)
        ("Who are our top 10 customers by margin?", "semantic_first"),
        ("Show revenue by region for last quarter", "semantic_first"),
        ("Which product categories are selling best?", "semantic_first"),
        ("What's the order trend over the past 12 weeks?", "semantic_first"),
        ("Find customers at risk of churning", "semantic_first"),

        # Should NOT match tools (sql_fallback)
        ("List all orders above $5000 with more than 3 items placed in January", "sql_fallback"),
        ("What's the average discount by product category for completed orders?", "sql_fallback"),
        ("Show me customers in NA who ordered electronics last month", "sql_fallback"),
        ("Which regions had declining revenue month-over-month?", "sql_fallback"),
        ("Find products that were never ordered", "sql_fallback"),
    ]

    # Build results table
    table = Table(title="Evaluation Results")
    table.add_column("Query", style="white", max_width=50)
    table.add_column("Expected", style="cyan")
    table.add_column("Actual", style="green")
    table.add_column("Match", style="bold")
    table.add_column("Time", justify="right")
    table.add_column("Cost", justify="right")

    correct = 0
    total_cost = 0.0
    total_time = 0
    queries_to_run = test_queries[:n]

    for query, expected_route in queries_to_run:
        resp = orchestrator.process(query)

        match = "✓" if resp.route == expected_route else "✗"
        if resp.route == expected_route:
            correct += 1
        total_cost += resp.cost_usd
        total_time += resp.elapsed_ms

        table.add_row(
            query[:50],
            expected_route,
            resp.route,
            match,
            f"{resp.elapsed_ms}ms",
            f"${resp.cost_usd:.5f}"
        )

    # Display results
    console.print(table)
    count = len(queries_to_run)
    console.print(f"\n[bold]Routing Accuracy:[/] {correct}/{count} ({correct / count * 100:.0f}%)")
    console.print(f"[bold]Total Cost:[/] ${total_cost:.5f}")
    console.print(f"[bold]Avg Latency:[/] {total_time // count}ms")