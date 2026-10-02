"""Tests for the holdout sealing checks (M4_FRESH_HOLDOUT_V1).

Synthetic data and public records only. No holdout content, model, API or network.
"""
import copy
import re
import sys
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.story_extraction import holdout_seal_v1 as S  # noqa: E402

BENCH = REPO / "benchmarks" / "m4_extraction"
A, B, C, D = "a" * 64, "b" * 64, "c" * 64, "d" * 64


def input_case():
    return {"case_id": "case-1",
            "scope": {"passage_inputs": [{"use": "EVIDENCE_ELIGIBLE", "passage_ref": {"segment_id": "seg-1"}}],
                      "as_of_position": {"stream_id": "s", "key": [1, 1]}, "profile_id": S.PROFILE_ID,
                      "prior_canonical_context": {"kind": "NONE"}},
            "base_source_layer_subset": {"source_documents": [{"id": "d"}], "source_segments": [{"id": "seg-1"}]},
            "passage_texts": [{"segment_id": "seg-1", "text": "synthetic"}]}


def gold_record(**changes):
    record = {"case_id": "case-1", "gold_completeness": "COMPLETE_FOR_PROFILE", "extraction_profile": S.PROFILE_ID,
              "window_size": 2, "line_coverage": [{"segment": 1, "coverage": "x"}, {"segment": 2, "coverage": "y"}],
              "gold_status": list(S.GOLD_STATUS), "categories": ["SIMPLE_EVENT"],
              "required_assertions": ["a1"], "acceptable_assertions": ["a2"]}
    record.update(changes)
    return record


class TestPackageSeparation(unittest.TestCase):
    def test_clean_input_package_passes(self):
        self.assertEqual(S.check_input_package({"cases/case-1.input.json": input_case()}), [])

    def test_gold_fields_in_the_input_package_are_detected_at_any_depth(self):
        for key in ("candidate_records", "required_assertions", "categories", "line_coverage", "literal_variants",
                    "role", "predicate", "expected_metrics", "notes"):
            with self.subTest(key):
                case = input_case()
                case["scope"]["passage_inputs"][0][key] = "x"
                issues = S.check_input_package({"cases/case-1.input.json": case})
                self.assertEqual(len(issues), 1)
                self.assertIn(key, issues[0])

    def test_member_named_after_gold_is_rejected(self):
        self.assertTrue(S.check_input_package({"gold/case-1.json": {}}))

    def test_packages_must_differ_and_share_no_member(self):
        self.assertEqual(S.check_package_separation(["i.json"], ["g.json"], A, B), [])
        self.assertTrue(S.check_package_separation(["i.json"], ["g.json"], A, A))
        self.assertTrue(S.check_package_separation(["x.json"], ["x.json"], A, B))


class TestGoldCompletenessGate(unittest.TestCase):
    def test_complete_cases_pass(self):
        self.assertEqual(S.gold_completeness_gate([gold_record()], 1), [])

    def test_incomplete_or_uncertain_case_blocks(self):
        for state in ("INCOMPLETE", "UNCERTAIN", None):
            with self.subTest(state):
                issues = S.gold_completeness_gate([gold_record(gold_completeness=state)], 1)
                self.assertTrue(any("GOLD_COMPLETENESS_UNRESOLVED" in i for i in issues))

    def test_every_eligible_segment_needs_a_coverage_note(self):
        self.assertTrue(S.gold_completeness_gate([gold_record(line_coverage=[{"segment": 1, "coverage": "x"}])], 1))

    def test_a_dropped_case_blocks(self):
        self.assertTrue(S.gold_completeness_gate([gold_record()], 12))

    def test_profile_status_categories_and_overlap_are_checked(self):
        for changes in ({"extraction_profile": "OTHER"}, {"gold_status": ["CONFIRMED"]}, {"categories": []},
                        {"categories": ["TOO_HARD"]}, {"acceptable_assertions": ["a1"]}):
            with self.subTest(changes):
                self.assertTrue(S.gold_completeness_gate([gold_record(**changes)], 1))

    def test_gold_batch_must_be_an_unreviewed_annotation(self):
        batch = {"process": {"method": "HUMAN_ANNOTATION"},
                 "candidate_records": {"assertions": [{"id": "a1", "review": {"state": "UNREVIEWED"}}]}}
        self.assertEqual(S.gold_batch_labels(batch), [])
        confirmed = copy.deepcopy(batch)
        confirmed["candidate_records"]["assertions"][0]["review"] = {"state": "CONFIRMED", "reviewer_kind": "HUMAN"}
        self.assertTrue(S.gold_batch_labels(confirmed))
        model = copy.deepcopy(batch)
        model["process"]["method"] = "MODEL"
        self.assertTrue(S.gold_batch_labels(model))


class TestBlindnessManifest(unittest.TestCase):
    def test_built_manifest_forbids_gold_and_passes(self):
        manifest = S.build_blindness_manifest(A, B, C, D)
        self.assertEqual(manifest["extractor_access_allowed"], {"input_package": True, "gold_package": False})
        self.assertEqual(manifest["gold_may_be_opened_after"], {"predictions_locked_and_hashed": True})
        self.assertEqual(S.check_blindness_manifest(manifest), [])

    def test_manifest_that_allows_gold_access_fails(self):
        manifest = S.build_blindness_manifest(A, B, C, D)
        manifest["extractor_access_allowed"]["gold_package"] = True
        self.assertTrue(S.check_blindness_manifest(manifest))

    def test_manifest_without_prediction_lock_condition_fails(self):
        manifest = S.build_blindness_manifest(A, B, C, D)
        manifest["gold_may_be_opened_after"] = {"predictions_locked_and_hashed": False}
        self.assertTrue(S.check_blindness_manifest(manifest))

    def test_missing_or_identical_hashes_fail(self):
        self.assertTrue(S.check_blindness_manifest(S.build_blindness_manifest(A, A, C, D)))
        self.assertTrue(S.check_blindness_manifest(S.build_blindness_manifest(A, "", C, D)))

    def test_opening_gold_before_prediction_lock_contaminates(self):
        self.assertEqual(S.holdout_state(True), "CONTAMINATED")
        self.assertEqual(S.holdout_state(False), "CLEAN")


class TestReadinessGate(unittest.TestCase):
    def test_all_conditions_true_seals(self):
        result = S.readiness({name: True for name in S.READINESS_CONDITIONS})
        self.assertEqual(result, {"status": "M4_FRESH_HOLDOUT_V1_SEALED", "failed": []})
        self.assertEqual(len(S.READINESS_CONDITIONS), 10)

    def test_any_false_or_missing_condition_blocks(self):
        for name in S.READINESS_CONDITIONS:
            with self.subTest(name):
                conditions = {n: True for n in S.READINESS_CONDITIONS}
                conditions[name] = False
                self.assertEqual(S.readiness(conditions), {"status": "M4_HOLDOUT_NOT_READY", "failed": [name]})
                del conditions[name]
                self.assertEqual(S.readiness(conditions)["status"], "M4_HOLDOUT_NOT_READY")

    def test_unknown_condition_is_an_error(self):
        with self.assertRaises(ValueError):
            S.readiness({"looks_fine": True})


class TestEvaluationSnapshot(unittest.TestCase):
    def setUp(self):
        self.snapshot = yaml.safe_load((BENCH / "M4_EVALUATION_PROTOCOL_SNAPSHOT_V1.yaml").read_text(encoding="utf-8"))

    def test_scorer_files_match_the_snapshot(self):
        self.assertEqual(self.snapshot["snapshot_id"], S.SNAPSHOT_ID)
        self.assertEqual(S.snapshot_mismatches(self.snapshot), [])

    def test_snapshot_covers_protocol_evaluator_tests_and_profile(self):
        files = set(self.snapshot["files"])
        self.assertEqual(files, set(S.SNAPSHOT_FILES))
        self.assertIn("docs/research/m4/M4_EXTRACTION_EVALUATION_PROTOCOL_V0.md", files)
        self.assertIn("tools/story_extraction/evaluate_extraction_v0.py", files)
        self.assertEqual(self.snapshot["profile"]["id"], "STORY_UNDERSTANDING_CORE_V0")
        self.assertIs(self.snapshot["story_extraction_v0_frozen"], False)

    def test_a_changed_hash_is_reported(self):
        changed = copy.deepcopy(self.snapshot)
        name = "tools/story_extraction/evaluate_extraction_v0.py"
        changed["files"][name] = "0" * 64
        changed["profile"]["definition_sha256"] = "0" * 64
        self.assertEqual(S.snapshot_mismatches(changed), [name, "<profile definition>"])

    def test_hash_ignores_line_ending_style(self):
        self.assertEqual(S.lf_sha256(b"a\r\nb\r\n"), S.lf_sha256(b"a\nb\n"))

    def test_profile_definition_is_one_section(self):
        text = "# T\n\n## 3. Before\nx\n\n## 4. Development Extraction Profile\nbody\n\n## 5. After\ny\n"
        self.assertEqual(S.profile_definition(text), "## 4. Development Extraction Profile\nbody\n\n")


class TestPublicSealRecord(unittest.TestCase):
    def setUp(self):
        self.text = (BENCH / "M4_03_FRESH_HOLDOUT_SEAL_RESULT.yaml").read_text(encoding="utf-8")
        self.record = yaml.safe_load(self.text)

    def test_record_binds_the_public_lock_and_snapshot(self):
        lock = yaml.safe_load((BENCH / "M4_03_HOLDOUT_SELECTION_LOCK_PUBLIC.yaml").read_text(encoding="utf-8"))
        snapshot = yaml.safe_load((BENCH / "M4_EVALUATION_PROTOCOL_SNAPSHOT_V1.yaml").read_text(encoding="utf-8"))
        self.assertEqual(self.record["selection"]["selection_lock_sha256"], lock["private_hashes"]["selection_lock_sha256"])
        self.assertEqual(self.record["selection"]["case_count"], lock["selection"]["selected_cases"])
        self.assertEqual(self.record["evaluation_snapshot"]["snapshot_sha256"], snapshot["snapshot_sha256"])
        self.assertIs(lock["gold_annotation_started_at_this_commit"], False)

    def test_packages_are_separate_and_gold_is_forbidden_to_extractors(self):
        packages = self.record["packages"]
        self.assertNotEqual(packages["input_package"]["sha256"], packages["gold_package"]["sha256"])
        self.assertIs(packages["input_package"]["contains_gold"], False)
        self.assertIs(packages["committed_to_repository"], False)
        self.assertEqual(self.record["blindness"]["extractor_access_allowed"], {"input_package": True, "gold_package": False})

    def test_readiness_gate_in_the_record_is_consistent(self):
        gate = dict(self.record["readiness_gate"])
        result = gate.pop("result")
        self.assertEqual(S.readiness(gate)["status"], result)
        self.assertEqual(self.record["status"], result)

    def test_gold_is_labelled_as_an_unreviewed_agent_draft(self):
        gold = self.record["gold"]
        self.assertEqual(gold["gold_status"], list(S.GOLD_STATUS))
        self.assertEqual(gold["review_state"], "UNREVIEWED")
        self.assertEqual(gold["gold_completeness"], "12/12 COMPLETE_FOR_PROFILE")
        self.assertEqual(set(gold["natural_category_distribution"]), set(S.CATEGORIES))

    def test_nothing_was_run_or_frozen(self):
        self.assertFalse(any(self.record["not_done"].values()))

    def test_public_records_carry_no_private_identifiers_or_source_text(self):
        doc = (REPO / "docs" / "research" / "m4" / "M4_FRESH_HOLDOUT_PROTOCOL_V1.md").read_text(encoding="utf-8")
        for text in (self.text, doc):
            self.assertIsNone(re.search(r"seg-[0-9a-f]{8,}|srcdoc-[0-9a-f]{6,}|M4HOLD_\d+|char_start|byte_start", text))
            self.assertFalse(any(0x3040 <= ord(ch) <= 0x30FF or 0x4E00 <= ord(ch) <= 0x9FFF for ch in text))


if __name__ == "__main__":
    unittest.main()
