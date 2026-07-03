"""Helper package map for `backend.solution.chat`.

- env.py          — .env loading + model/key config (no dotenv dependency).
- registry.py     — read-only views over backend.main's tool registry:
                    compact catalog, service groupings, name validation.
- llm.py          — OpenAI Responses-API client wrapper + JSON parsing.
- prompts.py      — classifier / finder / orchestrator system prompts.
- router.py       — adaptive two-stage routing + find_more_tools escape hatch.
- orchestrator.py — the tool-calling loop, logging, and stop logic.
- devtools.py     — terminal harness: run turns with latency/token/cost stats
                    (python -m backend.helpers.devtools "prompt").
"""
