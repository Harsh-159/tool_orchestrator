"""Batch prompt runner: edit PROMPTS below, then run the file.

    ./backend/.venv/bin/python -m backend.helpers.run_prompts

Each entry in PROMPTS runs as an independent scenario against the in-process
solution (mock state is reset before each, using the provided
reset_all_mock_state). An entry can be:
  - a string  -> one user turn;
  - a list of strings -> consecutive turns of ONE conversation (each turn
    feeds the full history back, like the evaluator does).

Per scenario it prints the /chat response JSON plus latency / tool calls /
LLM calls / token / estimated-cost stats, and a totals line at the end.
"""

from __future__ import annotations

import json
import time

# ---------------------------------------------------------------------------
# EDIT ME: the prompts you want to run.
# ---------------------------------------------------------------------------
PROMPTS: list[str | list[str]] = [
    "Find emails about the Q3 budget"
    "What conversations do I have in Slack?",
    "Find the most recent email about the Q1 revenue review and post a summary to the leadership Slack channel.",
    "Delete the file 'budget_2025.xlsx' from my Drive.",
    [
        "Schedule a 30-minute meeting with everyone on the project next week.",
        "The Tool Orchestrator project. Monday next week at 10am works.",
    ],
]


def run() -> None:
    from backend.chat_schema import ChatMessage, ChatRequest
    from backend.helpers.llm import usage_snapshot
    from backend.main import reset_all_mock_state
    from backend.solution import chat

    totals = {"seconds": 0.0, "tool_calls": 0, "llm_calls": 0, "cost": 0.0}

    for index, entry in enumerate(PROMPTS, start=1):
        turns = [entry] if isinstance(entry, str) else list(entry)
        reset_all_mock_state()
        history: list[ChatMessage] = []

        print(f"\n{'=' * 70}\nSCENARIO {index}/{len(PROMPTS)}: {turns[0][:80]}")
        for turn in turns:
            history.append(ChatMessage(role="user", content=turn))
            started = time.perf_counter()
            response = chat(ChatRequest(messages=history))
            elapsed = time.perf_counter() - started
            history = list(response.messages)

            print(json.dumps(response.model_dump(mode="json"), indent=2))
            usage = usage_snapshot()
            cost = usage["estimated_cost_usd"] or 0.0
            print(
                f"--- latency {elapsed:.2f}s | {len(response.tool_calls)} tool "
                f"calls | {usage['llm_calls']} llm calls | "
                f"{usage['input_tokens']} in / {usage['output_tokens']} out "
                f"tokens | est cost ${cost:.4f}"
            )
            totals["seconds"] += elapsed
            totals["tool_calls"] += len(response.tool_calls)
            totals["llm_calls"] += usage["llm_calls"]
            totals["cost"] += cost

    print(
        f"\nTOTAL: {totals['seconds']:.2f}s | {totals['tool_calls']} tool calls "
        f"| {totals['llm_calls']} llm calls | est cost ${totals['cost']:.4f} "
        f"across {len(PROMPTS)} scenarios"
    )


if __name__ == "__main__":
    run()
