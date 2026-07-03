"""Developer harness: run /chat turns from the terminal with latency and cost.

Runs the solution in-process (no server needed) and prints, per prompt, the
exact /chat response JSON followed by a stats line (latency, tool calls, LLM
calls, tokens, estimated cost).

Usage (from the repo root):

    ./backend/.venv/bin/python -m backend.helpers.devtools "What conversations do I have in Slack?"

    # several independent scenarios (state is reset between them):
    ./backend/.venv/bin/python -m backend.helpers.devtools \
        "What's on my calendar today?" \
        "Delete the file 'budget_2025.xlsx' from my Drive."

    # chain prompts as consecutive turns of ONE conversation instead:
    ./backend/.venv/bin/python -m backend.helpers.devtools --conversation \
        "Schedule a 30-minute meeting with everyone on the project next week." \
        "The Tool Orchestrator project. Monday next week at 10am works."

    # keep mock state across independent prompts (default resets each time):
    ./backend/.venv/bin/python -m backend.helpers.devtools --no-reset "..." "..."
"""

from __future__ import annotations

import argparse
import json
import sys
import time


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("prompts", nargs="+", help="one or more user prompts")
    parser.add_argument(
        "--conversation",
        action="store_true",
        help="treat prompts as consecutive turns of one conversation",
    )
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="do not reset mock state between independent prompts",
    )
    args = parser.parse_args()

    # Imports deferred so `--help` stays instant.
    from backend.chat_schema import ChatMessage, ChatRequest
    from backend.helpers.llm import usage_snapshot
    from backend.main import reset_all_mock_state
    from backend.solution import chat

    history: list[ChatMessage] = []
    totals = {"seconds": 0.0, "tool_calls": 0, "llm_calls": 0, "cost": 0.0}

    for index, prompt in enumerate(args.prompts, start=1):
        if not args.conversation:
            history = []
            if not args.no_reset:
                reset_all_mock_state()
        history.append(ChatMessage(role="user", content=prompt))

        started = time.perf_counter()
        response = chat(ChatRequest(messages=history))
        elapsed = time.perf_counter() - started
        history = list(response.messages)

        print(json.dumps(response.model_dump(mode="json"), indent=2))
        usage = usage_snapshot()
        cost = usage["estimated_cost_usd"]
        print(
            f"--- [{index}/{len(args.prompts)}] latency {elapsed:.2f}s | "
            f"{len(response.tool_calls)} tool calls | "
            f"{usage['llm_calls']} llm calls | "
            f"{usage['input_tokens']} in / {usage['output_tokens']} out tokens | "
            f"est cost {'$' + format(cost, '.4f') if cost is not None else 'n/a'}",
            file=sys.stderr,
        )
        totals["seconds"] += elapsed
        totals["tool_calls"] += len(response.tool_calls)
        totals["llm_calls"] += usage["llm_calls"]
        totals["cost"] += cost or 0.0

    if len(args.prompts) > 1:
        print(
            f"=== total: {totals['seconds']:.2f}s | {totals['tool_calls']} tool "
            f"calls | {totals['llm_calls']} llm calls | est cost "
            f"${totals['cost']:.4f} across {len(args.prompts)} prompts",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
