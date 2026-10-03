"""Offline tests for remaining Draft V1.1 failure attribution."""
import inspect
from pathlib import Path
import sys
import unittest


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.story_extraction.analyze_m4_04b3d3r_remaining_failures_v1 import (
    MigrationDiagnosticError,
    _duplicate_concrete_proposition_pair_count,
    _event_anchor_defect_count,
    _guard_path,
    analyze,
)


class M404B3D3RAttributionTests(unittest.TestCase):
    def test_analyzer_has_no_gold_or_evaluator_parameter(self):
        self.assertEqual(
            list(inspect.signature(analyze).parameters),
            ["artifact_root", "input_archive", "input_root"],
        )

    def test_gold_and_holdout_paths_fail_closed(self):
        for path in (Path("private") / "DEV2_GOLD", Path("sealed_holdout")):
            with self.subTest(path=path):
                with self.assertRaises(MigrationDiagnosticError):
                    _guard_path(path)

    def test_event_to_named_time_anchor_is_detected_in_input_semantics(self):
        draft = {
            "events": [{"handle": "EVT1", "anchor_handle": "T1"}],
            "anchors": [{"handle": "T1", "anchor_kind": "NAMED_TIME"}],
        }
        self.assertEqual(_event_anchor_defect_count(draft), 1)

    def test_matching_event_time_anchor_is_not_a_defect(self):
        draft = {
            "events": [{"handle": "EVT1", "anchor_handle": "T1"}],
            "anchors": [{
                "handle": "T1", "anchor_kind": "EVENT_TIME", "event_handle": "EVT1"
            }],
        }
        self.assertEqual(_event_anchor_defect_count(draft), 0)

    def test_duplicate_concrete_propositions_are_counted_without_labels(self):
        args = {"entity": {"kind": "ENTITY", "handle": "E1"}}
        draft = {"propositions": [
            {"handle": "P1", "predicate": "Exists", "args": args, "editorial_label": "a"},
            {"handle": "P2", "predicate": "Exists", "args": args, "editorial_label": "b"},
            {"handle": "P3", "placeholder": True},
        ]}
        self.assertEqual(_duplicate_concrete_proposition_pair_count(draft), 1)


if __name__ == "__main__":
    unittest.main()
