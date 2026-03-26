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
    "user_agent":   "purple",
    "data_agent":   "red",
    "orchestrator": "green",
    "sql_fallback": "blue",
}

# Maximum rows to render in the terminal — avoids flooding the screen
# for queries that return hundreds of rows.
_MAX_DISPLAY_ROWS = 25


def display_response(resp: AgentResponse):
    """Pretty-print an AgentResponse to the terminal."""

    # ── Agent Trace ───────────────────────────────────────────────
    console.print("\n[bold]═══ Agent Trace ═══[/]")
    for step in resp.trace:
        color = AGENT_STYLES.get(step.agent, "white")
        detail = step.detail[:120]
        console.print(f"  [{color}]■ {step.agent}[/{color}] → {step.action}: {detail}")

    # ── Result Summary ────────────────────────────────────────────
    route_color = "green" if resp.route == "semantic_first" else "blue"
    console.print(f"\n[bold]═══ Result ═══[/]")
    console.print(f"  Route:      [{route_color}]{resp.route}[/{route_color}]")
    console.print(f"  Request ID: {resp.request_id}")
    console.print(f"  Elapsed:    {resp.elapsed_ms}ms")

    # ── SQL ───────────────────────────────────────────────────────
    if resp.sql:
        formatted = sqlparse.format(resp.sql, reindent=True, keyword_case="upper")
        console.print(Panel(formatted, title="SQL", border_style="blue"))

    # ── Query Results ─────────────────────────────────────────────
    if resp.rows:
        _render_rows(resp.rows)
    elif resp.status == "ok":
        console.print("\n  [dim]No rows returned.[/]")

    # ── Evidence ──────────────────────────────────────────────────
    if resp.evidence:
        console.print(f"\n  Evidence:   {json.dumps(resp.evidence, indent=2)}")

    # ── Cost ──────────────────────────────────────────────────────
    if resp.cost_usd > 0:
        console.print(f"  API Cost:   ${resp.cost_usd:.6f}")


def _render_rows(rows: list[dict]):
    """
    Render query result rows as a Rich table.

    Caps display at _MAX_DISPLAY_ROWS and shows a truncation notice
    when the full result set is larger. Column order follows the key
    order of the first row, which matches SELECT column order.
    """
    total = len(rows)
    display = rows[:_MAX_DISPLAY_ROWS]
    columns = list(display[0].keys())

    title = (
        f"Results — {total} row{'s' if total != 1 else ''}"
        if total <= _MAX_DISPLAY_ROWS
        else f"Results — showing {_MAX_DISPLAY_ROWS} of {total} rows"
    )

    table = Table(title=title, border_style="green", show_lines=False)
    for col in columns:
        table.add_column(col, overflow="fold")

    for row in display:
        table.add_row(*[_fmt(row[col]) for col in columns])

    console.print()
    console.print(table)

    if total > _MAX_DISPLAY_ROWS:
        console.print(
            f"  [dim]… {total - _MAX_DISPLAY_ROWS} more rows not shown[/]"
        )


def _fmt(value) -> str:
    """Format a single cell value for display."""
    if value is None:
        return "[dim]—[/]"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def run_eval(orchestrator: Orchestrator, n: int = 20):
    """
    Run evaluation on a set of test queries.

    Tests both routing accuracy (did it pick the right path?)
    and collects cost/latency metrics.
    """
    test_queries = [
        # Should match tools (semantic_first)
        ("Who are our top 10 customers by margin?",           "semantic_first"),
        ("Show revenue by region for last quarter",            "semantic_first"),
        ("Which product categories are selling best?",         "semantic_first"),
        ("What's the order trend over the past 12 weeks?",    "semantic_first"),
        ("Find customers at risk of churning",                 "semantic_first"),

        # Should NOT match tools (sql_fallback)
        ("List all orders above $5000 with more than 3 items placed in January", "sql_fallback"),
        ("What's the average discount by product category for completed orders?", "sql_fallback"),
        ("Show me customers in NA who ordered electronics last month",            "sql_fallback"),
        ("Which regions had declining revenue month-over-month?",                 "sql_fallback"),
        ("Find products that were never ordered",                                 "sql_fallback"),
    ]

    # Build results table
    table = Table(title="Evaluation Results")
    table.add_column("Query",    style="white", max_width=50)
    table.add_column("Expected", style="cyan")
    table.add_column("Actual",   style="green")
    table.add_column("Rows",     justify="right")
    table.add_column("Match",    style="bold")
    table.add_column("Time",     justify="right")
    table.add_column("Cost",     justify="right")

    correct     = 0
    total_cost  = 0.0
    total_time  = 0
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
            str(len(resp.rows)),
            match,
            f"{resp.elapsed_ms}ms",
            f"${resp.cost_usd:.5f}",
        )

    # Display results
    console.print(table)
    count = len(queries_to_run)
    console.print(f"\n[bold]Routing Accuracy:[/] {correct}/{count} ({correct / count * 100:.0f}%)")
    console.print(f"[bold]Total Cost:[/]      ${total_cost:.5f}")
    console.print(f"[bold]Avg Latency:[/]     {total_time // count}ms")