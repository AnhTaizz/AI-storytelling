"""Synthetic ownership diagnostics; frozen evaluator semantics remain untouched."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.story_extraction.analyze_m4_04b3a_v1 import classify_issue, frozen_integrity


class ForensicsTests(unittest.TestCase):
    def test_exact_span_is_machine_owned(self):
        self.assertEqual(classify_issue("SPAN_MISMATCH: synthetic"),
                         ("passage_span_source_exact", "MACHINE_OWNED"))

    def test_review_is_machine_owned(self):
        self.assertEqual(classify_issue("SELF_CERTIFICATION: synthetic"),
                         ("provenance_review", "MACHINE_OWNED"))

    def test_dangling_handle_is_machine_owned(self):
        self.assertEqual(classify_issue("DANGLING_REFERENCE: synthetic"),
                         ("id_reference", "MACHINE_OWNED"))

    def test_duplicate_concrete_content_is_mechanical(self):
        self.assertEqual(classify_issue("predicate_integrity: duplicate concrete proposition content"),
                         ("predicate_argument", "MACHINE_OWNED"))

    def test_predicate_choice_is_model_owned(self):
        self.assertEqual(classify_issue("predicate_integrity: unregistered predicate"),
                         ("predicate_argument", "SEMANTIC_MODEL_OWNED"))

    def test_evidence_role_is_model_owned(self):
        self.assertEqual(classify_issue("WRONG_EVIDENCE_ROLE"),
                         ("evidence", "SEMANTIC_MODEL_OWNED"))

    def test_entity_resolution_is_model_owned(self):
        self.assertEqual(classify_issue("WRONG_ENTITY_RESOLUTION"),
                         ("entity_event", "SEMANTIC_MODEL_OWNED"))

    def test_coverage_is_model_owned(self):
        self.assertEqual(classify_issue("MISSED_REQUIRED_ASSERTION"),
                         ("semantic_coverage", "SEMANTIC_MODEL_OWNED"))

    def test_unsupported_is_model_owned(self):
        self.assertEqual(classify_issue("UNSUPPORTED_ASSERTION"),
                         ("unsupported", "SEMANTIC_MODEL_OWNED"))

    def test_m1_m2_m3_and_snapshot_bindings_are_byte_exact(self):
        self.assertEqual(frozen_integrity()["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
