"""End-to-end scenario tests for POST /chat with real LLM calls.

These exercise the full pipeline (routing -> orchestration -> tool execution
-> state mutation) in-process via TestClient; no separate server is needed.
They are OFF by default because they call the OpenAI API (cost, latency,
nondeterminism). Run them explicitly with:

    RUN_LIVE_TESTS=1 ./backend/.venv/bin/python -m unittest backend.tests.test_live_scenarios -v

Coverage map (the axes the case study grades):
  single-service lookup ..... test_single_service_lookup
  cross-service sequential .. test_cross_service_pipeline_mutates_slack
  parallel independent reads  test_parallel_independent_lookups
  ambiguity -> ask, no act .. test_ambiguous_request_asks_without_mutating
  multi-turn state .......... test_clarification_answer_completes_the_task
  error path / honesty ...... test_missing_file_is_reported_not_fabricated
  clear mutation executes ... test_unambiguous_mutation_executes
  large-catalog routing ..... test_github_query_answers_without_asking_scope
  frozen mock clock ......... test_relative_dates_use_mock_today
  no-tool turns ............. test_smalltalk_makes_no_tool_calls
  web search service ........ test_web_search_routes_to_perplexity
"""

from __future__ import annotations

import json
import os
import unittest

from backend.helpers.env import openai_api_key
from backend.main import app
from fastapi.testclient import TestClient

LIVE = os.environ.get("RUN_LIVE_TESTS") == "1" and bool(openai_api_key())


@unittest.skipUnless(
    LIVE, "live LLM tests: set RUN_LIVE_TESTS=1 (and OPENAI_API_KEY) to run"
)
class LiveChatScenarioTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.client = TestClient(app)
        self.client.post("/reset")

    # -- helpers ---------------------------------------------------------

    def chat(self, *user_turns: str) -> dict:
        """Send user turns one at a time, feeding back the full history."""
        messages: list[dict] = []
        response: dict = {}
        for turn in user_turns:
            messages.append({"role": "user", "content": turn})
            http = self.client.post("/chat", json={"messages": messages})
            self.assertEqual(http.status_code, 200, http.text)
            response = http.json()
            messages = response["messages"]
        return response

    def called(self, response: dict) -> list[str]:
        return [c["name"] for c in response["tool_calls"]]

    def reply(self, response: dict) -> str:
        last = response["messages"][-1]
        self.assertEqual(last["role"], "assistant")
        return last["content"]

    def state(self, service: str) -> str:
        return json.dumps(self.client.get("/state").json()[service]).lower()

    def count_marker(self, service: str, marker: str) -> int:
        return self.state(service).count(marker.lower())

    # -- scenarios -------------------------------------------------------

    def test_single_service_lookup(self) -> None:
        response = self.chat("What conversations do I have in Slack?")
        self.assertIn("slack_list_conversations", self.called(response))
        self.assertLessEqual(len(response["tool_calls"]), 2, "over-calling")
        self.assertIn("engineering", self.reply(response).lower())

    def test_cross_service_pipeline_mutates_slack(self) -> None:
        before = self.count_marker("slack", '"ts":')
        response = self.chat(
            "Find the most recent email about the Q1 revenue review and post "
            "a summary of it to the leadership Slack channel."
        )
        names = self.called(response)
        self.assertIn("slack_send_message", names)
        self.assertTrue(
            any(n.startswith("GMAIL_") for n in names), f"no gmail call in {names}"
        )
        self.assertGreater(
            self.count_marker("slack", '"ts":'), before, "no message added to slack"
        )

    def test_parallel_independent_lookups(self) -> None:
        response = self.chat(
            "List my Slack channels and also list the files in my Drive."
        )
        names = self.called(response)
        self.assertIn("slack_list_conversations", names)
        self.assertTrue(
            any(n.startswith("GOOGLEDRIVE_") for n in names),
            f"no drive call in {names}",
        )
        text = self.reply(response).lower()
        self.assertIn("engineering", text)
        self.assertIn("revenue model", text)

    def test_ambiguous_request_asks_without_mutating(self) -> None:
        events_before = self.count_marker("googlecalendar", '"kind": "calendar#event"')
        response = self.chat(
            "Schedule a 30-minute meeting with everyone on the project next week."
        )
        self.assertIn("?", self.reply(response), "should ask which project")
        self.assertNotIn("GOOGLECALENDAR_CREATE_EVENT", self.called(response))
        self.assertEqual(
            self.count_marker("googlecalendar", '"kind": "calendar#event"'),
            events_before,
            "must not create events while ambiguous",
        )

    def test_clarification_answer_completes_the_task(self) -> None:
        events_before = self.count_marker("googlecalendar", '"kind": "calendar#event"')
        response = self.chat(
            "Schedule a 30-minute meeting with everyone on the project next week.",
            "The Tool Orchestrator project. Monday next week at 10am works.",
        )
        self.assertIn("GOOGLECALENDAR_CREATE_EVENT", self.called(response))
        self.assertGreater(
            self.count_marker("googlecalendar", '"kind": "calendar#event"'),
            events_before,
            "clarified request should create the event",
        )

    def test_missing_file_is_reported_not_fabricated(self) -> None:
        files_before = self.count_marker("googledrive", '"name":')
        response = self.chat("Delete the file 'budget_2025.xlsx' from my Drive.")
        deletions = [
            c
            for c in response["tool_calls"]
            if "DELETE" in c["name"].upper() and c["error"] is None
        ]
        self.assertEqual(deletions, [], "nothing should be successfully deleted")
        self.assertEqual(
            self.count_marker("googledrive", '"name":'), files_before,
            "drive state must be unchanged",
        )
        self.assertNotIn("has been deleted", self.reply(response).lower())

    def test_unambiguous_mutation_executes(self) -> None:
        self.assertNotIn("harden the tool router", self.state("linear"))
        response = self.chat(
            "Create a Linear issue titled 'Harden the tool router' in the "
            "Engineering team, description 'Follow-ups from live testing'."
        )
        ok_creates = [
            c
            for c in response["tool_calls"]
            if c["name"] == "linear_create_issue" and c["error"] is None
        ]
        self.assertEqual(len(ok_creates), 1, self.called(response))
        self.assertIn("harden the tool router", self.state("linear"))

    def test_github_query_answers_without_asking_scope(self) -> None:
        response = self.chat("What open pull requests are there right now?")
        names = self.called(response)
        self.assertTrue(
            any("pull_request" in n for n in names), f"no PR tool in {names}"
        )
        text = self.reply(response).lower()
        self.assertNotIn("which repo", text)
        self.assertNotIn("specify the repository", text)
        self.assertIn("prototype", text, "should surface the fixture PRs")

    def test_relative_dates_use_mock_today(self) -> None:
        # The mock world is frozen at Wed 2026-04-08; "today" must resolve there.
        response = self.chat("What's on my calendar today?")
        self.assertTrue(
            any(n.startswith("GOOGLECALENDAR_") for n in self.called(response))
        )
        self.assertIn("revenue board prep", self.reply(response).lower())

    def test_smalltalk_makes_no_tool_calls(self) -> None:
        response = self.chat("hi")
        self.assertEqual(response["tool_calls"], [])
        self.assertTrue(self.reply(response))

    def test_web_search_routes_to_perplexity(self) -> None:
        response = self.chat(
            "Search the web: what is the latest stable version of FastAPI?"
        )
        self.assertIn("perplexity_search", self.called(response))


if __name__ == "__main__":
    unittest.main()
