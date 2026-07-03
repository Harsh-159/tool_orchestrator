"""Read-only views over the tool registry defined in backend.main.

backend.main imports backend.solution at module load, so importing
backend.main at the top of this module would be circular. Every accessor
imports it lazily instead — by the time any of these run, main is loaded.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Any, Iterable

# One-line capability summary per service, shown to the service classifier.
SERVICES: dict[str, str] = {
    "gmail": "Email: search, read, send, reply, draft, label, archive messages and threads, contacts.",
    "googlecalendar": "Calendar: find/create/update/delete events, check free-busy availability, schedule meetings, attendees.",
    "googledrive": "Files & documents: search, list, read, create, upload, move, rename, delete files and folders; permissions, sharing, comments.",
    "slack": "Team chat: list channels and users, read conversation history and threads, search messages, send messages.",
    "linear": "Issue/project tracking: teams, projects, issues, statuses, assignees, comments, labels, cycles.",
    "github": "Code hosting: repos, branches, commits, files, pull requests, reviews, issues, actions/CI, releases, tags, security alerts.",
    "perplexity": "Web search: answer questions using current public internet information.",
}


def _main():
    import backend.main as main

    return main


def all_tool_names() -> list[str]:
    return _main().list_available_tools()


def get_spec(name: str):
    return _main().get_tool_spec(name)


# Appended to tool descriptions at schema-render time to correct model priors
# that the mock semantics do not honor (verified against the mock sources).
_GITHUB_SEARCH_NOTE = (
    "NOTE: 'query' matches plain substrings in title/body only. GitHub search "
    "operators (is:open, state:, label:, repo:) are NOT supported — pass "
    "query=null to get everything, then filter the results yourself."
)
_DESCRIPTION_NOTES: dict[str, str] = {
    "github_search_pull_requests": _GITHUB_SEARCH_NOTE,
    "github_search_issues": _GITHUB_SEARCH_NOTE,
    "github_search_repositories": _GITHUB_SEARCH_NOTE,
    "github_search_code": _GITHUB_SEARCH_NOTE,
    "github_list_pull_requests": (
        "NOTE: requires owner and repo. To look across all repositories, use "
        "github_search_pull_requests with query=null instead."
    ),
    "github_list_issues": (
        "NOTE: requires owner and repo. To look across all repositories, use "
        "github_search_issues with query=null instead."
    ),
}


def openai_tool_schemas(names: list[str]) -> list[dict[str, Any]]:
    if not names:
        return []
    entries = _main().get_openai_tools(names)
    for entry in entries:
        note = _DESCRIPTION_NOTES.get(entry.get("name", ""))
        if note:
            entry["description"] = f"{entry['description']}\n\n{note}"
    return entries


@lru_cache(maxsize=1)
def tools_by_service() -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = {service: [] for service in SERVICES}
    for name, spec in _main().get_all_tool_specs().items():
        grouped.setdefault(spec.service, []).append(name)
    return {service: tuple(sorted(names)) for service, names in grouped.items()}


@lru_cache(maxsize=1)
def _descriptions() -> dict[str, str]:
    lines: dict[str, str] = {}
    for name, spec in _main().get_all_tool_specs().items():
        description = " ".join(spec.description.split())
        required = [
            field_name
            for field_name, field in spec.args_model.model_fields.items()
            if field.is_required()
        ]
        suffix = f" (requires: {', '.join(required)})" if required else ""
        lines[name] = f"{description}{suffix}"
    return lines


def catalog_line(name: str) -> str:
    return f"{name} — {_descriptions().get(name, '')}"


def compact_catalog(services: Iterable[str] | None = None) -> str:
    """Low-resolution catalog: one line per tool, grouped under service headers."""
    selected = list(services) if services else list(SERVICES)
    sections: list[str] = []
    for service in selected:
        names = tools_by_service().get(service, ())
        if not names:
            continue
        lines = [f"## {service} — {SERVICES.get(service, '')}"]
        lines.extend(f"- {catalog_line(name)}" for name in names)
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


@lru_cache(maxsize=1)
def _canonical_by_lower() -> dict[str, str]:
    return {name.lower(): name for name in all_tool_names()}


def valid_names(names: Iterable[Any]) -> list[str]:
    """Resolve to registered tool names, deduplicated, order preserved.

    Resolution is case-insensitive: the registry mixes UPPER_SNAKE and
    lower_snake names, and smaller models normalize casing when repeating
    them — an exact match would silently drop valid picks.
    """
    lookup = _canonical_by_lower()
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        if not isinstance(name, str):
            continue
        canonical = lookup.get(name.strip().lower())
        if canonical and canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
    return result


def mock_now() -> datetime:
    """The fixtures' frozen clock; relative dates must resolve against this."""
    from backend.googlecalendar_mock.state import BASE_NOW

    return BASE_NOW
