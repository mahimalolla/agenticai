"""
Enterprise Data Agent — Multi-Agent Orchestration Engine
Run:  python main.py
REPL: python main.py --interactive
Test: python main.py --eval
"""

import argparse

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from core import Orchestrator
from utils import display_response, run_eval

load_dotenv()
console = Console()


def main():
    parser = argparse.ArgumentParser(description="Enterprise Data Agent")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive REPL mode")
    parser.add_argument("--eval", "-e", action="store_true", help="Run evaluation suite")
    parser.add_argument("--query", "-q", type=str, help="Single query to process")
    parser.add_argument("--config", "-c", type=str, default="config.yaml", help="Config file path")
    args = parser.parse_args()

    # Banner
    console.print(Panel.fit(
        "[bold]Enterprise Data Agent[/]\nMulti-Agent Orchestration with Opus API",
        border_style="blue"
    ))

    # Create orchestrator (agents are initialized, FAISS index is lazy-loaded)
    orchestrator = Orchestrator(args.config)

    # Mode: Evaluation 
    if args.eval:
        console.print("\n[bold]Running evaluation...[/]\n")
        orchestrator.initialize()
        run_eval(orchestrator)

    # Mode: Interactive REPL 
    elif args.interactive:
        console.print("\n[bold green]Interactive mode[/] — type your questions (Ctrl+C to exit)\n")
        orchestrator.initialize()
        while True:
            try:
                query = console.input("[bold purple]You:[/] ")
                if not query.strip():
                    continue
                if query.lower() in ("exit", "quit", "q"):
                    break
                resp = orchestrator.process(query)
                display_response(resp)
                console.print()
            except KeyboardInterrupt:
                console.print("\n[bold]Goodbye![/]")
                break

    # Mode: Single query 
    elif args.query:
        orchestrator.initialize()
        resp = orchestrator.process(args.query)
        display_response(resp)

    # Mode: Default demo
    else:
        orchestrator.initialize()
        demo_queries = [
            "Who are our top 25 customers by margin this month?",
            "Find all orders over $10K placed on weekends with a discount above 15%",
        ]
        for q in demo_queries:
            console.print(f"\n[bold purple]Query:[/] {q}")
            resp = orchestrator.process(q)
            display_response(resp)


if __name__ == "__main__":
    main()