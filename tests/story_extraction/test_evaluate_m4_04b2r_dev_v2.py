"""Offline tests for resumed DEV reporting and lexicographic selection."""

from __future__ import annotations

import copy
import unittest

from tools.story_extraction.evaluate_m4_04b2r_dev_v2 import (
    PENDING,
    _selection,
    _structural_failure_result,
    _summary,
    _transport_summary,
)


def candidate_summary(*, critical=0, high=0, full=0, grounding=0.0, recall=0.0, epistemic=0.0):
    split = {
        "full_canonical_case_success_count": full,
        "evidence_grounding_recall_mean": grounding,
        "assertion_recall": recall,
    }
    return {
        "all": {
            "unsupported_severity": {"CRITICAL": critical, "HIGH": high},
            "epistemic_accuracy_mean": epistemic,
        },
        "COMPLETE_FOR_PROFILE": split,
    }


def transport(*, repairs=0, operations=0, output=0, input_=0, latency=0.0):
    return {
        "repair_jobs": repairs,
        "provider_operations": operations,
        "output_tokens": output,
        "input_tokens": input_,
        "provider_latency_seconds": latency,
    }


class TestM404B2REvaluationReporting(unittest.TestCase):
    def test_structural_failure_is_terminal_l0_failure(self):
        value = _structural_failure_result(
            {"primary_validation": {"errors": ["bad passage"]}}, "UNCERTAIN"
        )
        self.assertFalse(value["l0_structural_validity"])
        self.assertIsNone(value["metrics"])
        self.assertEqual(value["failure_codes"], ["CANONICAL_CONFORMANCE_FAILURE"])

    def test_pending_state_uses_frozen_ontology(self):
        result = {
            "l0_structural_validity": True,
            "full_canonical_case_success": None,
            "case_outcome": "PENDING_ADJUDICATION",
            "failure_codes": [],
            "failures": [],
            "unmatched_predictions": [{"state": PENDING}],
            "metrics": None,
        }
        self.assertEqual(_summary([result])["pending_adjudications"], 1)

    def test_selection_obeys_critical_before_every_later_metric(self):
        summaries = {
            "P0": candidate_summary(critical=1, full=99, grounding=1, recall=1, epistemic=1),
            "P1": candidate_summary(critical=0),
        }
        value = _selection(summaries, {"P0": transport(), "P1": transport()})
        self.assertEqual(value["leader"], "P1")
        self.assertEqual(value["deciding_criterion"], "FEWER_CRITICAL_UNSUPPORTED")

    def test_defined_zero_metric_beats_missing_metric(self):
        summaries = {
            "P0": candidate_summary(grounding=None, recall=None, epistemic=None),
            "P1": candidate_summary(grounding=0.0, recall=0.0, epistemic=None),
        }
        value = _selection(summaries, {"P0": transport(), "P1": transport()})
        self.assertEqual(value["leader"], "P1")
        self.assertEqual(value["deciding_criterion"], "HIGHER_COMPLETE_GROUNDING_RECALL")

    def test_repairs_decide_after_quality_ties(self):
        summaries = {"P0": candidate_summary(), "P1": candidate_summary()}
        value = _selection(
            summaries,
            {"P0": transport(repairs=4), "P1": transport(repairs=3)},
        )
        self.assertEqual(value["leader"], "P1")
        self.assertEqual(value["deciding_criterion"], "FEWER_STRUCTURAL_REPAIR_JOBS")

    def test_exact_tie_selects_p0(self):
        summaries = {"P0": candidate_summary(), "P1": candidate_summary()}
        value = _selection(summaries, {"P0": transport(), "P1": transport()})
        self.assertEqual(value["leader"], "P0")
        self.assertEqual(value["deciding_criterion"], "P0_IF_EXACT_TIE")

    def test_transport_summary_includes_primary_and_repair(self):
        job = {
            "total_provider_operations": 1,
            "windows_used": 1,
            "usage": {"prompt_token_count": 10, "candidates_token_count": 2, "total_token_count": 12},
            "provider_latency_seconds": 1.5,
        }
        predictions = [
            {
                "candidate": "P0",
                "primary_transport": copy.deepcopy(job),
                "repair_used": True,
                "repair_transport": copy.deepcopy(job),
                "repair_validation": {"pass": True},
            }
        ]
        value = _transport_summary(predictions, "P0")
        self.assertEqual(value["provider_operations"], 2)
        self.assertEqual(value["total_tokens"], 24)
        self.assertEqual(value["repair_structural_successes"], 1)


if __name__ == "__main__":
    unittest.main()
