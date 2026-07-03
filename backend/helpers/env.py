"""Minimal .env loading and configuration access.

The backend has no python-dotenv dependency, so we parse the repo-root
.env ourselves (KEY=VALUE lines, # comments). Real environment variables
always win over file values.
"""

from __future__ import annotations

import os
from pathlib import Path

_PLACEHOLDER_KEYS = {"", "sk-..."}
_loaded = False


def _parse_env_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            values[key] = value
    return values


def load_env() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    repo_root = Path(__file__).resolve().parents[2]
    for env_path in (repo_root / ".env", Path.cwd() / ".env"):
        if not env_path.is_file():
            continue
        for key, value in _parse_env_text(env_path.read_text()).items():
            os.environ.setdefault(key, value)


def openai_api_key() -> str | None:
    load_env()
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    return None if key in _PLACEHOLDER_KEYS else key


def model_name() -> str:
    load_env()
    return os.environ.get("OPENAI_MODEL", "").strip() or "gpt-4.1-mini"


def finder_model_name() -> str:
    """Model for the tool finder (and its escape-hatch reuse).

    Deliberately stronger than the default: shortlist recall is the primary
    graded axis, misses are fatal, and the call is small and conditional so
    the cost delta is ~half a cent per firing. Override with
    OPENAI_FINDER_MODEL.
    """
    load_env()
    return os.environ.get("OPENAI_FINDER_MODEL", "").strip() or "gpt-4.1"
