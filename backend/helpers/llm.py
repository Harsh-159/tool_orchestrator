"""OpenAI Responses API access.

main.py's get_openai_tools() emits Responses-API strict function entries
(flat name/parameters/strict), so the Responses API is the intended surface.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from openai import BadRequestError, OpenAI

from .env import model_name, openai_api_key


class MissingAPIKeyError(RuntimeError):
    pass


# USD per 1M input/output tokens; matched by longest model-name prefix.
_PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
}

_usage = {
    "llm_calls": 0,
    "input_tokens": 0,
    "output_tokens": 0,
    "estimated_cost_usd": 0.0,
}


def reset_usage() -> None:
    _usage.update(
        llm_calls=0, input_tokens=0, output_tokens=0, estimated_cost_usd=0.0
    )


def usage_snapshot() -> dict[str, Any]:
    snapshot: dict[str, Any] = dict(_usage)
    snapshot["estimated_cost_usd"] = round(snapshot["estimated_cost_usd"], 6)
    return snapshot


def _price_for(model: str) -> tuple[float, float] | None:
    for prefix in sorted(_PRICES_PER_MTOK, key=len, reverse=True):
        if model.startswith(prefix):
            return _PRICES_PER_MTOK[prefix]
    return None


def _record_usage(response: Any, model: str) -> None:
    """Tally tokens and cost, priced by the model that made the call —
    stages use different models, so a single-model estimate would lie."""
    usage = getattr(response, "usage", None)
    _usage["llm_calls"] += 1
    if usage is None:
        return
    input_tokens = getattr(usage, "input_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", 0) or 0
    _usage["input_tokens"] += input_tokens
    _usage["output_tokens"] += output_tokens
    price = _price_for(model)
    if price:
        _usage["estimated_cost_usd"] += (
            input_tokens / 1e6 * price[0] + output_tokens / 1e6 * price[1]
        )


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    key = openai_api_key()
    if not key:
        raise MissingAPIKeyError(
            "OPENAI_API_KEY is not set. Copy .env.example to .env and fill in your key."
        )
    return OpenAI(api_key=key, timeout=90.0, max_retries=2)


def create_response(
    *,
    input: list[Any],
    instructions: str,
    tools: list[dict[str, Any]] | None = None,
    json_schema: dict[str, Any] | None = None,
    schema_name: str = "output",
    model: str | None = None,
) -> Any:
    kwargs: dict[str, Any] = {
        "model": model or model_name(),
        "input": input,
        "instructions": instructions,
        "temperature": 0,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["parallel_tool_calls"] = True
    if json_schema is not None:
        kwargs["text"] = {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "strict": True,
                "schema": json_schema,
            }
        }
    try:
        response = _client().responses.create(**kwargs)
    except BadRequestError as exc:
        # Defensive: some models reject sampling params; retry without.
        if "temperature" in str(exc) and "temperature" in kwargs:
            kwargs.pop("temperature")
            response = _client().responses.create(**kwargs)
        else:
            raise
    _record_usage(response, kwargs["model"])
    return response


def extract_json(text: str) -> Any:
    """Parse a JSON object/array out of model text, tolerating stray prose."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    match = re.search(r"\{.*\}|\[.*\]", text or "", flags=re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None
