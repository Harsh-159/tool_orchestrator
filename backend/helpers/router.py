"""Adaptive two-stage tool routing.

Stage 0 — lenient service classifier over a 7-line catalog.
Stage 1 — only if the selected services' combined tool count exceeds
FULL_EXPOSURE_THRESHOLD, a recall-biased finder shortlists individual tools
from those services' compact catalog. Small unions skip the finder entirely
and expose whole services (100% recall, one less LLM round-trip).

find_more_tools() re-runs the finder over the FULL catalog mid-loop — the
escape hatch for routing misses and for multi-step plans whose later steps
only become knowable after earlier results.
"""

from __future__ import annotations

from typing import Sequence

from backend.chat_schema import ChatMessage

from .env import finder_model_name
from .llm import create_response, extract_json
from .prompts import CLASSIFIER_INSTRUCTIONS, FINDER_INSTRUCTIONS_TEMPLATE
from .registry import SERVICES, compact_catalog, tools_by_service, valid_names

# ≲30 full schemas keeps tool-selection accuracy high; above it we shortlist.
FULL_EXPOSURE_THRESHOLD = 28
FINDER_CAP = 15
ESCAPE_HATCH_CAP = 10

# Deterministic recall floor: whenever the finder shortlists a service's tools,
# these workspace-enumeration primitives ride along regardless of what the LLM
# picked, so unspecified scope ("which repo?") is always resolvable in-loop.
ANCHOR_TOOLS: dict[str, tuple[str, ...]] = {
    "gmail": ("GMAIL_FETCH_EMAILS", "GMAIL_LIST_THREADS"),
    "googlecalendar": ("GOOGLECALENDAR_EVENTS_LIST", "GOOGLECALENDAR_FIND_EVENT"),
    "googledrive": ("GOOGLEDRIVE_FIND_FILE", "GOOGLEDRIVE_FIND_FOLDER"),
    "slack": ("slack_list_conversations", "slack_list_users"),
    "linear": ("linear_list_projects", "linear_list_teams", "linear_list_issues"),
    "github": (
        "github_search_repositories",
        "github_search_pull_requests",
        "github_search_issues",
    ),
    "perplexity": ("perplexity_search",),
}

_CLASSIFIER_SCHEMA = {
    "type": "object",
    "properties": {
        "services": {
            "type": "array",
            "items": {"type": "string", "enum": list(SERVICES)},
        }
    },
    "required": ["services"],
    "additionalProperties": False,
}

# `plan` comes first so the model reasons about the steps before naming tools.
_FINDER_SCHEMA = {
    "type": "object",
    "properties": {
        "plan": {
            "type": "string",
            "description": "One or two sentences: the steps the agent will take.",
        },
        "tools": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["plan", "tools"],
    "additionalProperties": False,
}


def render_conversation(
    messages: Sequence[ChatMessage], *, limit: int = 8, clip: int = 1500
) -> str:
    recent = messages[-limit:]
    return "\n".join(f"{m.role.upper()}: {m.content[:clip]}" for m in recent)


def _classify_services(conversation: str) -> list[str]:
    response = create_response(
        input=[{"role": "user", "content": conversation}],
        instructions=CLASSIFIER_INSTRUCTIONS,
        json_schema=_CLASSIFIER_SCHEMA,
        schema_name="service_selection",
    )
    parsed = extract_json(response.output_text)
    services = parsed.get("services", []) if isinstance(parsed, dict) else []
    return [s for s in dict.fromkeys(services) if s in SERVICES]


def _shortlist(conversation: str, services: Sequence[str], cap: int) -> list[str]:
    instructions = FINDER_INSTRUCTIONS_TEMPLATE.format(
        cap=cap, catalog=compact_catalog(services)
    )
    task = (
        f"Conversation transcript:\n{conversation}\n\n"
        "Select the candidate tools for the newest user request now."
    )
    response = create_response(
        input=[{"role": "user", "content": task}],
        instructions=instructions,
        json_schema=_FINDER_SCHEMA,
        schema_name="tool_selection",
        model=finder_model_name(),
    )
    parsed = extract_json(response.output_text)
    names = parsed.get("tools", []) if isinstance(parsed, dict) else []
    allowed = {
        name for service in services for name in tools_by_service().get(service, ())
    }
    return [name for name in valid_names(names) if name in allowed][:cap]


def _service_union(services: Sequence[str]) -> list[str]:
    return [name for service in services for name in tools_by_service().get(service, ())]


def route(messages: Sequence[ChatMessage]) -> list[str]:
    """Pick the tool names the orchestrator starts the turn with."""
    conversation = render_conversation(messages)
    services = _classify_services(conversation)
    if not services:
        return []
    union = _service_union(services)
    if len(union) <= FULL_EXPOSURE_THRESHOLD:
        return union
    shortlisted = _shortlist(conversation, services, FINDER_CAP)
    # A failed shortlist must not lose tools: fall back to full exposure.
    if not shortlisted:
        return union
    anchors = [name for service in services for name in ANCHOR_TOOLS.get(service, ())]
    return valid_names([*anchors, *shortlisted])


def find_more_tools(
    messages: Sequence[ChatMessage], need: str, exclude: Sequence[str]
) -> list[str]:
    """Escape hatch: recall-biased search over the entire catalog."""
    conversation = render_conversation(messages)
    prompt = (
        f"{conversation}\n\n"
        f"The agent working on this request needs additional tools to: {need}"
    )
    excluded = set(exclude)
    picked = _shortlist(prompt, list(SERVICES), ESCAPE_HATCH_CAP + len(excluded))
    return [name for name in picked if name not in excluded][:ESCAPE_HATCH_CAP]
