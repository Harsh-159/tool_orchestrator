"""The orchestration loop: LLM ↔ tool execution with logging and stop logic.

Stops:
- natural   — the model replies with text and no tool calls;
- hard      — MAX_ITERATIONS / MAX_TOOL_CALLS reached → one final wrap-up call
              with tools disabled, instructed to be honest about gaps;
- breakers  — duplicate calls are served from cache instead of re-executed,
              and a tool that failed MAX_FAILURES_PER_TOOL times is refused.

Every registry-tool invocation (success or error) is appended to the
ToolCallLog list in execution order — that log is the graded artifact.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

from backend.chat_schema import ChatMessage, ToolCallLog

from .llm import create_response, reset_usage, usage_snapshot
from .prompts import WRAP_UP_INSTRUCTION, orchestrator_instructions
from .registry import all_tool_names, catalog_line, get_spec, openai_tool_schemas
from .router import find_more_tools, route

logger = logging.getLogger("solution.orchestrator")
# Observability: one summary line per turn on the server console. Configured
# here because we may not edit main.py; uvicorn does not set up root logging.
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

MAX_ITERATIONS = 8
MAX_TOOL_CALLS = 24
MAX_RESULT_CHARS = 6000
MAX_FAILURES_PER_TOOL = 2

FIND_MORE_TOOLS_SCHEMA = {
    "type": "function",
    "name": "find_more_tools",
    "description": (
        "Search the full tool catalog (191 tools across gmail, googlecalendar, "
        "googledrive, slack, linear, github, perplexity) for additional tools. "
        "Use this whenever none of your currently available tools fit the next "
        "step. Newly found tools become available to you immediately."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "need": {
                "type": "string",
                "description": (
                    "What you need to accomplish, e.g. 'create a Linear issue' "
                    "or 'delete a file from Drive'."
                ),
            }
        },
        "required": ["need"],
        "additionalProperties": False,
    },
    "strict": True,
}


@dataclass
class _TurnState:
    messages: list[ChatMessage]
    active_tools: list[str]
    logs: list[ToolCallLog] = field(default_factory=list)
    cached_outputs: dict[tuple[str, str], str] = field(default_factory=dict)
    failures: dict[str, int] = field(default_factory=dict)


def run_turn(messages: list[ChatMessage]) -> tuple[str, list[ToolCallLog]]:
    """Route, then loop model ↔ tools until a final reply. Never raises for
    anything past routing — mid-loop failures produce an honest reply plus
    the logs collected so far."""
    started = time.perf_counter()
    reset_usage()
    state = _TurnState(messages=messages, active_tools=route(messages))
    routed = len(state.active_tools)
    try:
        reply = _loop(state, [_to_input_item(m) for m in messages])
    except Exception:
        logger.exception("orchestration loop failed")
        reply = (
            "I hit an internal error while working on this and could not finish. "
            "Any tool calls I completed are logged; please retry or rephrase."
        )
    usage = usage_snapshot()
    cost = usage["estimated_cost_usd"]
    logger.info(
        "turn done: %.2fs | %d tools routed | %d tool calls (%d errored) | "
        "%d llm calls | %d in / %d out tokens | est $%s",
        time.perf_counter() - started,
        routed,
        len(state.logs),
        sum(1 for log in state.logs if log.error),
        usage["llm_calls"],
        usage["input_tokens"],
        usage["output_tokens"],
        f"{cost:.4f}" if cost is not None else "n/a",
    )
    return reply, state.logs


def _loop(state: _TurnState, input_items: list[Any]) -> str:
    instructions = orchestrator_instructions()
    for _ in range(MAX_ITERATIONS):
        tools = openai_tool_schemas(state.active_tools) + [FIND_MORE_TOOLS_SCHEMA]
        response = create_response(
            input=input_items, instructions=instructions, tools=tools
        )
        input_items += response.output
        calls = [
            item
            for item in response.output
            if getattr(item, "type", None) == "function_call"
        ]
        if not calls:
            return response.output_text or "Done."
        for call in calls:
            output = _handle_call(call, state)
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": output,
                }
            )
        if len(state.logs) >= MAX_TOOL_CALLS:
            break
    return _wrap_up(input_items, instructions)


def _wrap_up(input_items: list[Any], instructions: str) -> str:
    input_items.append({"role": "system", "content": WRAP_UP_INSTRUCTION})
    response = create_response(input=input_items, instructions=instructions)
    return response.output_text or "I could not complete the task within budget."


def _handle_call(call: Any, state: _TurnState) -> str:
    name = call.name
    try:
        args = json.loads(call.arguments or "{}")
    except json.JSONDecodeError:
        return "ERROR: tool arguments were not valid JSON. Re-issue the call."
    if not isinstance(args, dict):
        args = {}
    # Strict mode makes every property required; null marks unused optionals.
    args = {key: value for key, value in args.items() if value is not None}

    if name == "find_more_tools":
        return _handle_find_more(args, state)
    if name not in set(all_tool_names()):
        return f"ERROR: unknown tool '{name}'. Use find_more_tools to locate the right one."

    cache_key = (name, json.dumps(args, sort_keys=True, default=str))
    if cache_key in state.cached_outputs:
        return (
            "NOTE: you already made this exact call; cached result below. "
            "Do not repeat calls.\n" + state.cached_outputs[cache_key]
        )
    if state.failures.get(name, 0) >= MAX_FAILURES_PER_TOOL:
        return (
            f"ERROR: {name} already failed {MAX_FAILURES_PER_TOOL} times. Do not "
            "retry it — use a different approach or report the failure honestly."
        )

    output = _execute(name, args, state)
    state.cached_outputs[cache_key] = output
    return output


def _execute(name: str, args: dict[str, Any], state: _TurnState) -> str:
    try:
        envelope = get_spec(name).invoke(**args)
        payload = envelope.model_dump(mode="json").get("result")
        state.logs.append(ToolCallLog(name=name, arguments=args, result=payload))
        return _serialize(payload)
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        state.logs.append(
            ToolCallLog(name=name, arguments=args, result=None, error=message)
        )
        state.failures[name] = state.failures.get(name, 0) + 1
        return (
            f"ERROR calling {name}: {message}\n"
            "If an argument was wrong, fix it and retry once. If the resource "
            "does not exist, tell the user honestly instead of inventing a result."
        )


def _handle_find_more(args: dict[str, Any], state: _TurnState) -> str:
    need = str(args.get("need", "")).strip() or "the next step of the request"
    added = find_more_tools(state.messages, need, exclude=state.active_tools)
    if not added:
        return (
            "No additional matching tools exist in the catalog. Work with your "
            "current tools, or tell the user what cannot be done."
        )
    state.active_tools.extend(added)
    return "Added tools (now available to call):\n" + "\n".join(
        f"- {catalog_line(name)}" for name in added
    )


def _serialize(payload: Any) -> str:
    text = json.dumps(payload, default=str)
    if len(text) > MAX_RESULT_CHARS:
        text = (
            text[:MAX_RESULT_CHARS]
            + f'... [truncated {len(text) - MAX_RESULT_CHARS} chars; refine your '
            "query if you need what was cut]"
        )
    return text


def _to_input_item(message: ChatMessage) -> dict[str, str]:
    if message.role in ("user", "assistant", "system"):
        return {"role": message.role, "content": message.content}
    # 'tool' role from a prior turn has no Responses-API equivalent without
    # its call context; surface it as quoted context instead.
    return {"role": "user", "content": f"[tool output from earlier turn]\n{message.content}"}
