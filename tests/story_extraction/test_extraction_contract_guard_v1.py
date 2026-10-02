"""Synthetic regression and V1-to-V2 monotonicity tests; no DEV or holdout data."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixture_builder as fx  # noqa: E402
from test_story_extraction_contract_v0 import (  # noqa: E402
    NEGATIVE_VARIANTS,
    STRUCTURALLY_INVALID_VARIANTS,
    gold,
    prediction,
)
from tools.story_extraction import evaluate_extraction_guarded_v1 as v2_evaluator  # noqa: E402
from tools.story_extraction import evaluate_extraction_v0 as v1_evaluator  # noqa: E402
from tools.story_extraction import extraction_contract_v0 as v1  # noqa: E402
from tools.story_extraction.extraction_contract_guard_v1 import (  # noqa: E402
    GUARD_ID,
    validate_batch_guarded,
)


class TestGuardV1MalformedPassageInputs(unittest.TestCase):
    def setUp(self):
        self.ingestion, self.base, self.batch = prediction("c07_location")

    def mutate(self, operation):
        batch = copy.deepcopy(self.batch)
        ref = batch["scope"]["passage_inputs"][0]["passage_ref"]
        operation(ref)
        return batch

    def assert_structural_failure(self, batch):
        first = validate_batch_guarded(batch, self.base, self.ingestion)
        second = validate_batch_guarded(copy.deepcopy(batch), self.base, self.ingestion)
        self.assertEqual(first, second)
        self.assertFalse(first["pass"])
        self.assertFalse(first["checks"]["scope"]["pass"])
        self.assertTrue(
            any("MALFORMED_PASSAGE_INPUT" in issue for issue in first["checks"]["scope"]["issues"])
        )

    def test_identity(self):
        self.assertEqual(GUARD_ID, "M4_EXTRACTION_VALIDATION_GUARD_V1")

    def test_empty_span(self):
        self.assert_structural_failure(self.mutate(lambda ref: ref.update(span={})))

    def test_missing_char_start(self):
        self.assert_structural_failure(self.mutate(lambda ref: ref["span"].pop("char_start")))

    def test_missing_char_end(self):
        self.assert_structural_failure(self.mutate(lambda ref: ref["span"].pop("char_end_exclusive")))

    def test_span_wrong_scalar_type(self):
        self.assert_structural_failure(self.mutate(lambda ref: ref.update(span="bad")))

    def test_empty_position(self):
        self.assert_structural_failure(self.mutate(lambda ref: ref.update(position={})))

    def test_position_missing_stream_id(self):
        self.assert_structural_failure(self.mutate(lambda ref: ref["position"].pop("stream_id")))

    def test_position_missing_key(self):
        self.assert_structural_failure(self.mutate(lambda ref: ref["position"].pop("key")))

    def test_position_key_invalid(self):
        for value in ([], [True], ["1"], [-1], [1] * 9):
            with self.subTest(value=value):
                self.assert_structural_failure(
                    self.mutate(lambda ref, value=value: ref["position"].update(key=value))
                )

    def test_equal_character_bounds(self):
        self.assert_structural_failure(
            self.mutate(
                lambda ref: ref["span"].update(
                    char_end_exclusive=ref["span"]["char_start"]
                )
            )
        )

    def test_reversed_character_bounds(self):
        self.assert_structural_failure(
            self.mutate(
                lambda ref: ref["span"].update(
                    char_end_exclusive=ref["span"]["char_start"] - 1
                )
            )
        )

    def test_known_v1_crash_becomes_v2_failure(self):
        batch = self.mutate(lambda ref: ref.update(span={"kind": "TEXT_RANGE_V0"}))
        with self.assertRaises(KeyError):
            v1.validate_batch(batch, self.base, self.ingestion)
        self.assert_structural_failure(batch)


class TestGuardV1Impact(unittest.TestCase):
    def test_all_valid_synthetic_contract_results_identical(self):
        for case_id in fx.CASES:
            for build in (gold, prediction):
                ingestion, base, batch = build(case_id)
                with self.subTest(case=case_id, build=build.__name__):
                    self.assertEqual(
                        v1.validate_batch(batch, base, ingestion),
                        validate_batch_guarded(batch, base, ingestion),
                    )

    def test_existing_negative_evaluator_results_identical(self):
        for case_id, variants in NEGATIVE_VARIANTS.items():
            ingestion, base, gold_batch = gold(case_id)
            for variant in variants:
                _, _, predicted = prediction(case_id, variant)
                with self.subTest(case=case_id, variant=variant):
                    self.assertEqual(
                        v1_evaluator.evaluate_case(base, gold_batch, predicted, ingestion=ingestion),
                        v2_evaluator.evaluate_case(base, gold_batch, predicted, ingestion=ingestion),
                    )

    def test_existing_structural_rejections_identical(self):
        for case_id, variant in STRUCTURALLY_INVALID_VARIANTS.items():
            ingestion, base, _ = gold(case_id)
            _, _, predicted = prediction(case_id, variant)
            with self.subTest(case=case_id, variant=variant):
                self.assertEqual(
                    v1_evaluator.evaluate_case(base, gold(case_id)[2], predicted, ingestion=ingestion),
                    v2_evaluator.evaluate_case(base, gold(case_id)[2], predicted, ingestion=ingestion),
                )

    def test_metric_relevant_perfect_results_identical(self):
        for case_id in fx.CASES:
            ingestion, base, gold_batch = gold(case_id)
            _, _, predicted = prediction(case_id)
            with self.subTest(case=case_id):
                self.assertEqual(
                    v1_evaluator.evaluate_case(base, gold_batch, predicted, ingestion=ingestion),
                    v2_evaluator.evaluate_case(base, gold_batch, predicted, ingestion=ingestion),
                )

    def test_v2_evaluator_fails_closed_on_new_malformed_shape(self):
        ingestion, base, gold_batch = gold("c07_location")
        _, _, predicted = prediction("c07_location")
        predicted["scope"]["passage_inputs"][0]["passage_ref"]["span"] = {}
        result = v2_evaluator.evaluate_case(base, gold_batch, predicted, ingestion=ingestion)
        self.assertFalse(result["l0_structural_validity"])
        self.assertIsNone(result["metrics"])
        self.assertEqual(result["failure_codes"], ["CANONICAL_CONFORMANCE_FAILURE"])


if __name__ == "__main__":
    unittest.main()
