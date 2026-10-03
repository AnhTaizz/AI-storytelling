"""Synthetic tests for the public-safe, offline B3C-R forensics analyzer."""
from pathlib import Path
import sys
import unittest


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.story_extraction.analyze_m4_04b3cr_structural_failures_v1 import (
    StructuralForensicsError,
    _repair_effect,
    analyze_locked_artifacts,
    draft_change_shape,
    failure_family,
    mention_linkage_shape,
)


class StructuralFailureForensicsTests(unittest.TestCase):
    def test_failure_families_are_explicit(self):
        cases = (
            (None, None, "PASS"),
            ("JSON_PARSE_FAILURE", "BAD_JSON", "JSON"),
            ("DRAFT_SCHEMA_FAILURE", "SCHEMA", "DRAFT_SCHEMA"),
            ("DRAFT_COMPILER_FAILURE", "AMBIGUOUS_QUOTE", "QUOTE"),
            ("DRAFT_COMPILER_FAILURE", "MENTION_EVIDENCE_MISMATCH", "HANDLE"),
            ("DRAFT_COMPILER_FAILURE", "UNKNOWN_PREDICATE", "PREDICATE"),
            (
                "DRAFT_COMPILER_FAILURE",
                "CANONICAL_CONFORMANCE_FAILURE",
                "CANONICAL_COMPILER",
            ),
            ("DRAFT_COMPILER_FAILURE", "UNCLASSIFIED", "OTHER"),
        )
        for category, code, expected in cases:
            with self.subTest(category=category, code=code):
                self.assertEqual(failure_family(category, code), expected)

    def test_linkage_diagnostic_emits_shape_not_quote_text(self):
        secret_mention = "private mention text"
        secret_evidence = "private mention text plus surrounding source"
        draft = {
            "evidence": [
                {
                    "handle": "EV1",
                    "passage_handle": "P1",
                    "quote": secret_evidence,
                    "role": "DIRECT",
                    "occurrence": 1,
                }
            ],
            "mentions": [
                {
                    "handle": "M1",
                    "evidence_handle": "EV1",
                    "passage_handle": "P1",
                    "quote": secret_mention,
                    "role": "DIRECT",
                    "occurrence": 1,
                }
            ],
        }
        result = mention_linkage_shape(draft)
        self.assertEqual(
            result,
            [
                {
                    "mention_handle": "M1",
                    "evidence_handle": "EV1",
                    "mismatch_fields": ["quote"],
                    "quote_relation": "MENTION_QUOTE_STRICTLY_WITHIN_EVIDENCE_QUOTE",
                }
            ],
        )
        self.assertNotIn(secret_mention, repr(result))
        self.assertNotIn(secret_evidence, repr(result))

    def test_draft_change_diagnostic_emits_fields_not_values(self):
        before = {
            "mentions": [
                {"handle": "M1", "quote": "private before", "evidence_handle": "EV1"}
            ]
        }
        after = {
            "mentions": [
                {"handle": "M1", "quote": "private after", "evidence_handle": "EV2"}
            ]
        }
        result = draft_change_shape(before, after)
        self.assertEqual(
            result["changed_collections"]["mentions"]["changed_fields_by_handle"],
            {"M1": ["evidence_handle", "quote"]},
        )
        self.assertNotIn("private before", repr(result))
        self.assertNotIn("private after", repr(result))

    def test_repair_effect_distinguishes_four_outcomes(self):
        first = {"category": "C", "code": "X", "path": "M1"}
        self.assertEqual(_repair_effect(first, first, True), "NO_CHANGE")
        self.assertEqual(
            _repair_effect(first, {"pass": True}, False),
            "FULL_STRUCTURAL_CORRECTION",
        )
        self.assertEqual(
            _repair_effect(first, dict(first), False),
            "CHANGED_DRAFT_BUT_TRIGGER_PERSISTED",
        )
        self.assertEqual(
            _repair_effect(
                first,
                {"category": "C", "code": "X", "path": "M2"},
                False,
            ),
            "INITIAL_TRIGGER_CORRECTED_NEXT_TRIGGER_EXPOSED",
        )

    def test_rejects_input_or_gold_paths_before_reading(self):
        for unsafe in (Path("private") / "input", Path("private") / "dev2_gold"):
            with self.subTest(path=unsafe):
                with self.assertRaises(StructuralForensicsError):
                    analyze_locked_artifacts(unsafe)


if __name__ == "__main__":
    unittest.main()
