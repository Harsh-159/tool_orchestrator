"""Unit tests for the solution's routing helpers (no LLM calls)."""

from __future__ import annotations

import os
import unittest
import unittest.mock

from backend.helpers.env import _parse_env_text, finder_model_name, model_name
from backend.helpers.llm import (
    _price_for,
    _record_usage,
    extract_json,
    reset_usage,
    usage_snapshot,
)
from backend.helpers.registry import (
    SERVICES,
    all_tool_names,
    compact_catalog,
    tools_by_service,
    valid_names,
)
from backend.helpers.router import (
    ANCHOR_TOOLS,
    FULL_EXPOSURE_THRESHOLD,
    _service_union,
)


class RegistryViewTests(unittest.TestCase):
    def test_service_grouping_covers_all_191_tools(self) -> None:
        grouped = tools_by_service()
        self.assertEqual(set(grouped), set(SERVICES))
        self.assertEqual(sum(len(names) for names in grouped.values()), 191)
        self.assertEqual(len(all_tool_names()), 191)

    def test_compact_catalog_lists_every_tool_once(self) -> None:
        catalog = compact_catalog()
        for name in all_tool_names():
            self.assertIn(f"- {name} — ", catalog)

    def test_compact_catalog_respects_service_filter(self) -> None:
        catalog = compact_catalog(["slack"])
        self.assertIn("slack_list_conversations", catalog)
        self.assertNotIn("gmail_", catalog)

    def test_valid_names_filters_and_dedupes(self) -> None:
        names = valid_names(
            ["slack_list_users", "not_a_tool", "slack_list_users", None, 3]
        )
        self.assertEqual(names, ["slack_list_users"])

    def test_valid_names_resolves_casing(self) -> None:
        # Smaller models normalize the registry's mixed-case names; resolution
        # must be case-insensitive or action tools get silently dropped.
        names = valid_names(["googlecalendar_CREATE_EVENT", "SLACK_SEND_MESSAGE"])
        self.assertEqual(
            names, ["GOOGLECALENDAR_CREATE_EVENT", "slack_send_message"]
        )


class RoutingShapeTests(unittest.TestCase):
    def test_small_service_unions_skip_the_finder(self) -> None:
        # slack alone and slack+perplexity must qualify for full exposure.
        self.assertLessEqual(
            len(_service_union(["slack", "perplexity"])), FULL_EXPOSURE_THRESHOLD
        )

    def test_github_always_requires_the_finder(self) -> None:
        self.assertGreater(len(_service_union(["github"])), FULL_EXPOSURE_THRESHOLD)

    def test_anchor_tools_are_registered_names(self) -> None:
        for service, names in ANCHOR_TOOLS.items():
            self.assertEqual(valid_names(names), list(names), service)


class ParsingTests(unittest.TestCase):
    def test_env_parser(self) -> None:
        parsed = _parse_env_text(
            "# comment\nOPENAI_API_KEY='sk-test'\nOPENAI_MODEL=gpt-4.1-mini\n\nBAD LINE\n"
        )
        self.assertEqual(
            parsed, {"OPENAI_API_KEY": "sk-test", "OPENAI_MODEL": "gpt-4.1-mini"}
        )

    def test_extract_json_tolerates_prose(self) -> None:
        self.assertEqual(
            extract_json('Sure! {"tools": ["a"]}'), {"tools": ["a"]}
        )
        self.assertIsNone(extract_json("no json here"))


class UsageTrackingTests(unittest.TestCase):
    def test_price_matches_longest_prefix(self) -> None:
        self.assertEqual(_price_for("gpt-4.1-mini"), (0.40, 1.60))
        self.assertEqual(_price_for("gpt-4.1"), (2.00, 8.00))
        self.assertIsNone(_price_for("some-future-model"))

    def test_usage_tally_prices_per_call_model(self) -> None:
        class FakeUsage:
            input_tokens = 1_000_000
            output_tokens = 500_000

        class FakeResponse:
            usage = FakeUsage()

        reset_usage()
        # mixed models must be priced individually:
        _record_usage(FakeResponse(), "gpt-4.1-mini")  # 0.40 + 0.80 = $1.20
        _record_usage(FakeResponse(), "gpt-4.1")  # 2.00 + 4.00 = $6.00
        snapshot = usage_snapshot()
        self.assertEqual(snapshot["llm_calls"], 2)
        self.assertEqual(snapshot["input_tokens"], 2_000_000)
        self.assertAlmostEqual(snapshot["estimated_cost_usd"], 7.20, places=4)
        reset_usage()

    def test_stage_model_selection(self) -> None:
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_FINDER_MODEL", None)
            self.assertEqual(finder_model_name(), "gpt-4.1")
        with unittest.mock.patch.dict(
            os.environ, {"OPENAI_FINDER_MODEL": "gpt-4.1-mini"}
        ):
            self.assertEqual(finder_model_name(), "gpt-4.1-mini")
        self.assertTrue(model_name())


if __name__ == "__main__":
    unittest.main()
