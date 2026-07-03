from __future__ import annotations

from backend.chat_schema import ChatMessage, ChatRequest, ChatResponse
from backend.helpers.llm import MissingAPIKeyError
from backend.helpers.orchestrator import run_turn
from fastapi import HTTPException


def chat(request: ChatRequest) -> ChatResponse:
    """POST /chat — orchestrate tools to answer the conversation's latest turn.

    Architecture (see helpers/ for each stage):
      1. route()            — lenient service classifier, then (only when the
                              selected services' tools exceed a threshold) a
                              recall-biased tool shortlist. helpers/router.py
      2. run_turn() loop    — Responses-API tool-calling loop over the routed
                              subset, with a find_more_tools escape hatch,
                              duplicate/failure breakers, and hard budgets.
                              helpers/orchestrator.py
    Every registry tool invoked (success or error) appears in tool_calls in
    execution order.
    """
    try:
        reply, tool_calls = run_turn(list(request.messages))
    except MissingAPIKeyError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ChatResponse(
        messages=[*request.messages, ChatMessage(role="assistant", content=reply)],
        tool_calls=tool_calls,
    )
