"""Offline tests for Gemini provider qualification orchestration."""

from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.story_extraction.discover_gemini_qualification_candidates_v1 import (  # noqa: E402
    select_candidates,
)
from tools.story_extraction.run_gemini_provider_qualification_v1 import (  # noqa: E402
    OUTPUT_TOKEN_CAP,
    PROMPT_TEMPLATE_SHA256,
    STAGE_SPECS,
    _reported_model_compatible,
)


def model(name, *, actions=("generateContent",), deprecated=False):
    return SimpleNamespace(
        name=f"models/{name}",
        display_name=name,
        version=name,
        input_token_limit=1000,
        output_token_limit=100,
        supported_actions=list(actions),
        deprecated=deprecated,
    )


class TestCandidateSelection(unittest.TestCase):
    def test_fixed_roles_choose_latest_previous_and_lite(self):
        candidates, _ = select_candidates(
            [
                model("gemini-3.7-flash"),
                model("gemini-3.8-flash"),
                model("gemini-3.8-flash-lite"),
                model("gemini-2.5-flash"),
            ]
        )
        self.assertEqual(
            [item["model_id"] for item in candidates],
            ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.8-flash-lite"],
        )

    def test_preview_experimental_deprecated_and_non_text_are_excluded(self):
        candidates, eligible = select_candidates(
            [
                model("gemini-4.0-flash-preview"),
                model("gemini-3.9-flash-exp"),
                model("gemini-3.8-flash", deprecated=True),
                model("gemini-embedding-001", actions=("embedContent",)),
                model("gemini-3.7-flash"),
            ]
        )
        self.assertEqual([item["model_id"] for item in candidates], ["gemini-3.7-flash"])
        self.assertEqual([item["model_id"] for item in eligible], ["gemini-3.7-flash"])

    def test_duplicate_revisions_do_not_replace_previous_generation(self):
        candidates, _ = select_candidates(
            [
                model("gemini-3.8-flash"),
                model("gemini-3.8-flash-001"),
                model("gemini-3.7-flash"),
            ]
        )
        self.assertEqual(
            [item["model_id"] for item in candidates],
            ["gemini-3.8-flash", "gemini-3.7-flash"],
        )


class TestQualificationContract(unittest.TestCase):
    def test_stage_request_and_concurrency_budgets_are_fixed(self):
        self.assertEqual(STAGE_SPECS["stage_a"], {"requests": 3, "concurrency": 1})
        self.assertEqual(STAGE_SPECS["profile_s"], {"requests": 12, "concurrency": 1})
        self.assertEqual(STAGE_SPECS["profile_c2"], {"requests": 12, "concurrency": 2})

    def test_prompt_hash_is_stable_and_output_cap_is_bounded(self):
        self.assertEqual(
            PROMPT_TEMPLATE_SHA256,
            "caa453f25225089a1a4d3b50d851a607eb7bb8abaf25daa582028ed7a292d4f1",
        )
        self.assertLessEqual(OUTPUT_TOKEN_CAP, 128)

    def test_provider_reported_revision_is_not_a_silent_switch(self):
        self.assertTrue(
            _reported_model_compatible("gemini-3.8-flash", "gemini-3.8-flash-001")
        )
        self.assertFalse(
            _reported_model_compatible("gemini-3.8-flash", "gemini-3.7-flash")
        )


if __name__ == "__main__":
    unittest.main()
