"""Offline tests for the M4-04B4CR compiler forensics analyzer.

Unit fixtures are synthetic: a mocked M4-04B4C run over synthetic archives in the recorded
DEV3 layout. No DEV3 package, credential, provider or gold is touched. One class checks
the published forensic record, which holds structural aggregates only.
"""
import ast
import copy
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

import yaml

from tests.story_extraction import test_run_m4_04b4c_p4_dev3_tuning_v1 as b4c_tests
from tools.story_extraction import analyze_m4_04b4cr_p4_dev3_compiler_forensics_v1 as forensics
from tools.story_extraction import draft_compiler_v1 as compiler_v1
from tools.story_extraction import m4_04b4a_p4_output_contract_v1 as contract
from tools.story_extraction import m4_04b4br_p4_protocol_v2 as protocol
from tools.story_extraction import run_m4_04b4c_p4_dev3_tuning_v1 as b4c


SEMANTIC = "ZZ_MODEL_WRITTEN_VALUE_ZZ"
PINNED = {
    "tools/story_extraction/run_m4_04b4c_p4_dev3_tuning_v1.py":
        "6265931dbd58912746ab5af9fe5e5a878bb6e69f7a2d67233eb0713edcbe47ac",
    "tools/story_extraction/draft_compiler_v1_1.py":
        "f962e561a7801ddf48ef248416231673e1567b9eac9d04f2aaba1d1e16eed953",
    "tools/story_extraction/draft_compiler_v1.py":
        "281a2dfb5e99e67cc82b71798c09c93c04ab9682e8385a9cf6dfaf8393d69800",
    "schemas/canonical_story/predicate_registry_v0.yaml":
        "44f3eafc6982f84bcc74ccb91abe7cd467a453352ee96be147095f27559c5350",
    "benchmarks/m4_extraction/M4_04B4C_P4_DEV3_TUNING_PREDICTION_LOCK.yaml":
        "4574994a093b18c7923d1524d0175c1c7e9931451643d297f9daa74954fb5683",
    "benchmarks/m4_extraction/M4_04B4C_P4_DEV3_TUNING_RESULT.yaml":
        "78d0af5741a5c3485deffba18f54d6f578f479419e4b78f33d48dca200a7b512",
}
B4C_PREDICTION_SET = "ee67ff92c72f01b98d2bd7ac892fa3fb13d437074511bc5b4bf946aa7ee66538"
B4C_EXPERIMENT_LOCK = "4e407e0c644cfd359f1c4114c6bf98902d7cb453457277345631aea4b73fc840"


def ambiguous(case_id, handles=None, occurrence=None):
    """A valid synthetic draft whose mention quotes repeat in their passage. Occurrence given or omitted."""
    draft = b4c_tests.valid_draft(case_id)
    for mention in draft["mentions"]:
        if handles is not None and mention["handle"] not in handles:
            continue
        mention["quote"] = "e"
        mention["surface_form"] = "e"
        mention.pop("occurrence", None)
        if occurrence is not None:
            mention["occurrence"] = occurrence
    return draft


def with_duplicate_proposition(draft):
    clone = copy.deepcopy(draft["propositions"][-1])
    clone["handle"] = f"PROP{len(draft['propositions']) + 1}"
    draft["propositions"].append(clone)
    return draft


def with_disallowed_entity_kind(case_id):
    draft = b4c_tests.valid_draft(case_id)
    next(entity for entity in draft["entities"] if entity["kind"] == "LOCATION")["kind"] = "OBJECT"
    return draft


def with_missing_argument(case_id):
    draft = b4c_tests.valid_draft(case_id)
    proposition = draft["propositions"][-1]
    proposition["args"].pop(sorted(proposition["args"])[-1])
    return draft


def raw(draft, **kwargs):
    return json.dumps(draft, ensure_ascii=False, **kwargs)


class SyntheticRun:
    """One mocked B4C run with every kind of compiler failure and repair effect."""

    def __init__(self):
        self.holder = unittest.TestCase()
        self.workspace = b4c_tests.Workspace(self.holder)
        job, fix, ok = b4c_tests.primary_job, b4c_tests.repair_job, b4c_tests.success
        same_quote = raw(ambiguous("DEV3_01"))
        same_kind = raw(with_disallowed_entity_kind("DEV3_05"))
        arity = with_missing_argument("DEV3_06")
        self.script = {
            job("DEV3_01"): ok(same_quote), fix("DEV3_01"): ok(same_quote),
            job("DEV3_02"): ok(raw(ambiguous("DEV3_02"))), fix("DEV3_02"): ok(raw(ambiguous("DEV3_02", occurrence=1))),
            job("DEV3_04"): ok(raw(ambiguous("DEV3_04"))),
            fix("DEV3_04"): ok(raw(with_duplicate_proposition(ambiguous("DEV3_04", occurrence=2)))),
            job("DEV3_05"): ok(same_kind), fix("DEV3_05"): ok(same_kind),
            job("DEV3_06"): ok(raw(arity)), fix("DEV3_06"): ok(raw(arity, indent=1)),
            job("DEV3_08"): ok(raw(with_duplicate_proposition(b4c_tests.valid_draft("DEV3_08")))),
            fix("DEV3_08"): ok(b4c_tests.valid_raw("DEV3_08")),
        }
        self.result = self.workspace.run(self.script)
        b4c.write_public_prediction_lock(b4c.build_public_prediction_lock(self.result), self.workspace.published_lock)
        self.forensic_root = self.workspace.root / "forensics"

    def analyze(self, **kwargs):
        return forensics.analyze(
            private_root=self.workspace.private, input_archive=self.workspace.archive,
            forensic_root=kwargs.pop("forensic_root", self.forensic_root),
            expected_input_sha256=self.workspace.sha256, prediction_lock_path=self.workspace.published_lock, **kwargs)

    def close(self):
        self.holder.doCleanups()


class LockedResultReproductionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.run_ = SyntheticRun()
        cls.outcome = cls.run_.analyze()
        cls.record = cls.outcome["record"]
        cls.private = cls.outcome["private"]

    @classmethod
    def tearDownClass(cls):
        cls.run_.close()

    def test_prediction_set_is_rebuilt_from_the_artifact_files(self):
        reproduction = self.record["reproduction"]
        self.assertEqual(self.run_.result["prediction_set_sha256"],
                         reproduction["prediction_set_sha256_rebuilt_from_artifact_files"])
        self.assertEqual(self.run_.result["prediction_set_sha256"], self.record["accepted_B4C"]["prediction_set_sha256"])
        self.assertTrue(reproduction["prediction_set_matches_private_result_manifest_and_public_lock"])
        self.assertTrue(reproduction["b4c_integrity_checks_all_pass"])
        self.assertEqual(0, reproduction["provider_operations_during_forensics"])
        self.assertEqual(
            {"raw_responses": 16, "parsed_drafts": 16, "compiled_batches": 6, "terminal_failure_records": 4,
             "diagnostics": 10, "case_results": 10, "durable_checkpoints": 16},
            reproduction["artifact_counts"],
        )

    def test_every_attempt_replays_to_its_locked_outcome(self):
        matrix = self.private["attempt_matrix"]
        self.assertEqual(16, len(matrix))
        self.assertEqual({"PRIMARY": 10, "REPAIR_1": 6},
                         {phase: sum(row["phase"] == phase for row in matrix) for phase in ("PRIMARY", "REPAIR_1")})
        totals = self.record["attempt_metrics"]["totals"]
        self.assertEqual((16, 16, 16, 16, 6, 10), (totals["attempts"], totals["json_valid"], totals["full_schema_valid"],
                                                   totals["compiler_reached"], totals["compiler_success"],
                                                   totals["compiler_failure"]))
        self.assertEqual({"AMBIGUOUS_QUOTE": 4, "CANONICAL_CONFORMANCE_FAILURE": 6}, totals["first_blocker_codes"])
        self.assertEqual((6, 4, 0), (totals["final_structural_valid_cases"], totals["final_structural_failure_cases"],
                                     totals["final_transport_failure_cases"]))
        self.assertEqual((4, 2), (self.record["attempt_metrics"]["primary"]["compiler_success"],
                                  self.record["attempt_metrics"]["repair"]["compiler_success"]))
        self.assertTrue(self.record["reproduction"]["compiler_results_reproduced"])
        self.assertEqual(6, self.record["reproduction"]["compiled_batches_reproduced_byte_for_byte"])
        required = {"case_id", "phase", "request_fingerprint", "raw_response_sha256", "draft_sha256", "json_valid",
                    "projection_valid", "full_schema_valid", "compiler_reached", "compiler_success", "blocker_phase",
                    "blocker_code", "blocker_path", "repair_used", "repair_identical_to_primary", "terminal_status"}
        for row in matrix:
            self.assertLessEqual(required, set(row))
            self.assertFalse(any(key.startswith("_") for key in row))
        text = json.dumps(matrix)
        for forbidden in ("Mira", "captain", "lantern", '"quote"', "surface_form"):
            self.assertNotIn(forbidden, text)

    def test_quote_errors_and_canonical_errors_are_separated(self):
        by_key = {(row["case_id"], row["phase"]): row for row in self.private["attempt_matrix"]}
        self.assertEqual(("QUOTE", "AMBIGUOUS_QUOTE", "mentions/M1"),
                         tuple(by_key[("DEV3_01", "PRIMARY")][k] for k in ("blocker_phase", "blocker_code", "blocker_path")))
        self.assertEqual(2, by_key[("DEV3_02", "PRIMARY")]["blocker_count"])
        self.assertEqual(("CANONICAL_COMPILER", "CANONICAL_CONFORMANCE_FAILURE", "canonical"),
                         tuple(by_key[("DEV3_05", "PRIMARY")][k] for k in ("blocker_phase", "blocker_code", "blocker_path")))
        quote = self.record["quote_forensics"]
        self.assertEqual((5, 4), (quote["quote_blockers"], quote["attempts_with_a_quote_blocker"]))
        self.assertEqual({"AMBIGUOUS_QUOTE:QUOTE_REPEATED_OCCURRENCE_MISSING": 5}, quote["blockers_by_code_and_class"])
        self.assertEqual(6, self.record["canonical_conformance_forensics"]["attempts_with_canonical_conformance_failure"])

    def test_ambiguous_quote_facts_are_mechanical(self):
        ambiguous_quote = self.record["quote_forensics"]["ambiguous_quote"]
        self.assertEqual(
            (5, {"PRIMARY": 4, "REPAIR_1": 1}, {"mentions": 5}, 5, 5, 5, 5, 0),
            (ambiguous_quote["blockers"], ambiguous_quote["by_phase"], ambiguous_quote["by_record_kind"],
             ambiguous_quote["quote_exists_in_designated_passage"], ambiguous_quote["occurrence_omitted"],
             ambiguous_quote["passage_evidence_eligible"], ambiguous_quote["caused_by_repeated_exact_text"],
             ambiguous_quote["repetition_only_through_overlapping_matches"]),
        )
        self.assertEqual({"1": 5}, ambiguous_quote["quote_length_buckets_in_code_points"])
        effect = self.record["quote_forensics"]["effect_of_repair_on_primary_quote_blockers"]
        self.assertEqual((4, 4, 0, 3, 3, 1), (effect["primary_quote_blockers_in_repaired_cases"],
                                              effect["record_still_present"], effect["quote_text_changed"],
                                              effect["occurrence_added"], effect["ambiguity_cleared"],
                                              effect["ambiguity_unchanged"]))
        self.assertEqual(3, self.record["quote_forensics"]["repeated_quote_locators_that_did_carry_an_occurrence"])

    def test_canonical_failures_are_attributed_to_check_section_and_rule(self):
        canonical = self.record["canonical_conformance_forensics"]
        self.assertEqual({"canonical": 6}, canonical["failed_checks"])
        self.assertEqual({"predicate_integrity": 6}, canonical["issues_by_section"])
        self.assertEqual({"ARGUMENT_ENTITY_KIND_NOT_ALLOWED": 2, "DUPLICATE_CONCRETE_PROPOSITION_CONTENT": 2,
                          "PREDICATE_ARGUMENT_SET_MISMATCH": 2}, canonical["issues_by_rule_class"])
        self.assertEqual((0, 0, 6), (canonical["unclassified_issues"], canonical["validator_exceptions"],
                                     canonical["attempts_with_zero_precompile_structural_blockers"]))
        kinds = canonical["rule_classes"]["ARGUMENT_ENTITY_KIND_NOT_ALLOWED"]
        self.assertEqual((2, 1, 1, 2, 0), (kinds["affected_attempts"], kinds["primary_attempts"], kinds["repair_attempts"],
                                           kinds["violation_present_in_model_draft"],
                                           kinds["violation_absent_from_model_draft"]))
        duplicate = canonical["rule_classes"]["DUPLICATE_CONCRETE_PROPOSITION_CONTENT"]
        self.assertEqual((2, 2), (duplicate["affected_attempts"], duplicate["violation_present_in_model_draft"]))
        self.assertEqual(2, canonical["rule_classes"]["PREDICATE_ARGUMENT_SET_MISMATCH"]["violation_not_mechanically_checked"])
        self.assertEqual("READ_ONLY_RECORDER_AROUND_THE_VALIDATOR_CALL_INSIDE_THE_UNCHANGED_COMPILER",
                         canonical["instrumentation"])

    def test_repair_effects_and_identical_responses(self):
        repairs = self.record["repair_effectiveness"]
        self.assertEqual(
            {"BLOCKER_UNCHANGED": 1, "IDENTICAL_RESPONSE": 2, "PRIMARY_BLOCKER_CLEARED_BUT_NEW_BLOCKER": 1,
             "REPAIR_STRUCTURALLY_VALID": 2}, repairs["effects"])
        self.assertEqual((6, 2, 4, 2, 3, 3, 6), (
            repairs["repair_attempts"], repairs["identical_repair_responses"], repairs["distinct_repair_responses"],
            repairs["repair_compiler_successes"], repairs["primary_blocker_cleared"],
            repairs["primary_blocker_not_cleared"], repairs["request_fingerprints_differ_from_primary"]))
        by_case = {entry["case_id"]: entry for entry in self.private["repair_comparisons"]}
        self.assertEqual(
            {"DEV3_01": "IDENTICAL_RESPONSE", "DEV3_02": "REPAIR_STRUCTURALLY_VALID",
             "DEV3_04": "PRIMARY_BLOCKER_CLEARED_BUT_NEW_BLOCKER", "DEV3_05": "IDENTICAL_RESPONSE",
             "DEV3_06": "BLOCKER_UNCHANGED", "DEV3_08": "REPAIR_STRUCTURALLY_VALID"},
            {case_id: entry["effect"] for case_id, entry in by_case.items()})
        self.assertTrue(by_case["DEV3_01"]["response_sha256_equal"])
        self.assertFalse(by_case["DEV3_06"]["response_sha256_equal"])
        self.assertTrue(all(entry["request_fingerprints_differ"] for entry in by_case.values()))
        matrix = {(row["case_id"], row["phase"]): row for row in self.private["attempt_matrix"]}
        self.assertIs(True, matrix[("DEV3_01", "REPAIR_1")]["repair_identical_to_primary"])
        self.assertIs(False, matrix[("DEV3_06", "REPAIR_1")]["repair_identical_to_primary"])
        self.assertIsNone(matrix[("DEV3_01", "PRIMARY")]["repair_identical_to_primary"])

    def test_repair_diagnostic_v2_audit(self):
        audit = self.record["repair_diagnostic_audit"]
        self.assertEqual("M4_P4_STRUCTURAL_REPAIR_DIAGNOSTIC_V2", audit["diagnostic_identity"])
        self.assertEqual((6, 6, 6, 6), (audit["repairs_audited"], audit["primary_error_category_correct"],
                                        audit["blocker_phase_and_code_preserved"],
                                        audit["diagnostic_equals_sanitized_compiler_blockers"]))
        self.assertEqual(["code", "path", "phase"], audit["finding_fields"])
        self.assertEqual((6, 3, 3, 0, 1, 7, 6), (
            audit["record_handle_masked_in_path"], audit["path_fully_masked"], audit["canonical_failures_sent_to_repair"],
            audit["canonical_failures_naming_the_failed_check"], audit["repairs_where_blockers_were_collapsed"],
            audit["raw_compiler_blockers_total"], audit["findings_sent_total"]))
        self.assertEqual(
            {"CORRECT_DIAGNOSTIC_BUT_MODEL_DID_NOT_REPAIR": 1, "DIAGNOSTIC_TOO_GENERIC_FOR_STRUCTURAL_REPAIR": 2,
             "NOT_APPLICABLE_PRIMARY_BLOCKER_WAS_CLEARED": 3}, audit["probable_mechanisms"])
        stored = json.loads((self.run_.workspace.private / "failures" / "DEV3_02_primary_diagnostic.json").read_text("utf-8"))
        self.assertEqual([{"phase": "QUOTE", "code": "AMBIGUOUS_QUOTE", "path": "mentions/<UNRECOGNIZED_KEY>"}],
                         stored["findings"])

    def test_counterfactuals_are_isolated_diagnostics(self):
        counter = self.record["counterfactuals"]
        self.assertEqual(("NON_PREDICTION_DIAGNOSTIC_ONLY", False, False, False),
                         (counter["label"], counter["counted_as_predictions"], counter["written_to_the_prediction_root"],
                          counter["an_occurrence_was_chosen_as_correct"]))
        occurrence = counter["quote_occurrence"]
        self.assertEqual((4, 4, 4, 4, 0, 0), (
            occurrence["failed_attempts_examined"], occurrence["attempts_enumerated"],
            occurrence["attempts_where_every_choice_clears_the_quote_blocker"],
            occurrence["attempts_that_compile_under_every_choice"], occurrence["attempts_where_another_blocker_follows"],
            occurrence["attempts_where_the_outcome_depends_on_the_choice"]))
        self.assertEqual({"COMPILES": 4}, occurrence["outcome_codes_after_the_edit"])
        self.assertGreater(occurrence["occurrence_combinations_tried"], 4)
        self.assertEqual((2, {"COMPILES": 2}), (counter["canonical"]["duplicate_proposition_edits_tried"],
                                                counter["canonical"]["outcomes"]))
        self.assertEqual({"ARGUMENT_ENTITY_KIND_NOT_ALLOWED": 2, "PREDICATE_ARGUMENT_SET_MISMATCH": 2},
                         counter["canonical"]["skipped_because_the_edit_needs_a_semantic_choice"])
        self.assertEqual("NON_PREDICTION_DIAGNOSTIC_ONLY", self.private["counterfactuals"]["label"])
        for entry in self.private["counterfactuals"]["quote"] + self.private["counterfactuals"]["canonical"]:
            self.assertEqual("NON_PREDICTION_DIAGNOSTIC_ONLY", entry["label"])
        self.assertEqual(6, self.record["attempt_metrics"]["totals"]["final_structural_valid_cases"])

    def test_prediction_root_is_unchanged_and_forensics_live_elsewhere(self):
        before = forensics.prediction_root_fingerprint(self.run_.workspace.private)
        self.run_.analyze()
        self.assertEqual(before, forensics.prediction_root_fingerprint(self.run_.workspace.private))
        names = sorted(path.name for path in self.run_.forensic_root.iterdir())
        self.assertEqual(["attempt_matrix.json", "canonical_conformance.json", "counterfactuals.json",
                          "quote_forensics.json", "repair_comparisons.json", "reproduction_report.json"], names)
        for path in self.run_.forensic_root.iterdir():
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("FORENSIC_DIAGNOSTIC_NOT_A_PREDICTION", payload["kind"])
        for bad in (self.run_.workspace.private, self.run_.workspace.private / "forensics",
                    self.run_.workspace.root, forensics.REPO_ROOT, forensics.REPO_ROOT / "benchmarks" / "x",
                    self.run_.workspace.root.parent / "gold_forensics"):
            with self.subTest(root=bad.name), self.assertRaises(forensics.ForensicsError):
                self.run_.analyze(forensic_root=bad)

    def test_root_cause_attribution_is_conditional_on_the_evidence(self):
        attribution = {entry["mechanism"]: entry for entry in self.record["root_cause_attribution"]}
        quote = attribution["AMBIGUOUS_QUOTE:QUOTE_REPEATED_OCCURRENCE_MISSING"]
        self.assertEqual((4, 3, 1, ["A_MODEL_STRUCTURAL_CONFORMANCE"], "HIGH"),
                         (quote["affected_attempts"], quote["primary_attempts"], quote["repair_attempts"],
                          quote["attribution"], quote["confidence"]))
        duplicate = attribution["CANONICAL_CONFORMANCE_FAILURE:DUPLICATE_CONCRETE_PROPOSITION_CONTENT"]
        self.assertEqual(["B_MODEL_FACING_INTERFACE_GAP"], duplicate["attribution"])
        self.assertIs(False, duplicate["structural_evidence"]["compiler_generated_the_invalid_structure"])
        unchecked = attribution["CANONICAL_CONFORMANCE_FAILURE:PREDICATE_ARGUMENT_SET_MISMATCH"]
        self.assertEqual((["G_INSUFFICIENT_EVIDENCE"], "LOW"), (unchecked["attribution"], unchecked["confidence"]))
        for entry in attribution.values():
            self.assertIn(entry["confidence"], ("HIGH", "MEDIUM", "LOW"))
            self.assertLessEqual({"supporting", "contrary", "uncertainty", "structural_evidence"}, set(entry))
        self.assertFalse(self.record["alternative_explanations"]["D_DETERMINISTIC_COMPILER_DEFECT"]["supported"])
        self.assertIs(False, self.record["decision"]["implementation_authorized"])
        self.assertEqual(
            ["P4.1 VERSIONED REPAIR DIAGNOSTIC REDESIGN", "P4.1 VERSIONED QUOTE-LOCATOR / COMPILER-INTERFACE REDESIGN",
             "CANONICAL CONTRACT CLARIFICATION"], self.record["decision"]["next_research_candidate"])

    def test_public_record_is_allowlisted_and_carries_no_private_value(self):
        forensics.validate_public_record(self.record)
        self.assertEqual(forensics.PUBLIC_SECTIONS, tuple(self.record))
        text = yaml.safe_dump(json.loads(json.dumps(self.record)), allow_unicode=True)
        for forbidden in ("Mira", "captain", "lantern", "courtyard", "mentions/M", "PROP1", "PROP2", "EV1", "E_NEW",
                          "draftv1-", "OccursAt",
                          "Possesses", "RefersTo", "char_start", "C:\\", ".local/m4_04b4c"):
            self.assertNotIn(forbidden, text, forbidden)
        boundaries = self.record["boundaries"]
        self.assertEqual((0, 0, False, False, False, False, False),
                         (boundaries["provider_calls"], boundaries["model_calls"], boundaries["predictions_rerun"],
                          boundaries["DEV3_gold_opened"], boundaries["holdout_opened"], boundaries["semantic_scoring"],
                          boundaries["redesign_implemented"]))
        mutations = {
            "narrative_value": lambda r: r["quote_forensics"].__setitem__("matcher", "Mira opened the gate."),
            "model_value": lambda r: r["limitations"].append("the model wrote " + SEMANTIC + " here"),
            "extra_section": lambda r: r.__setitem__("predictions", []),
            "gold_opened": lambda r: r["boundaries"].__setitem__("DEV3_gold_opened", True),
            "provider_call": lambda r: r["boundaries"].__setitem__("provider_calls", 1),
            "scoring": lambda r: r["boundaries"].__setitem__("semantic_scoring", True),
            "object_value": lambda r: r["decision"].__setitem__("extra", object()),
        }
        for label, change in mutations.items():
            mutated = copy.deepcopy(json.loads(json.dumps(self.record)))
            change(mutated)
            with self.subTest(mutation=label), self.assertRaises(forensics.ForensicsError):
                forensics.validate_public_record(mutated)

    def test_public_record_validates_in_a_fresh_process(self):
        """Publishable sentences must be registered at import, not as a side effect of an analysis."""
        path = self.run_.workspace.root / "record.yaml"
        path.write_text(yaml.safe_dump(json.loads(json.dumps(self.record)), sort_keys=False, allow_unicode=True),
                        encoding="utf-8")
        code = ("import sys, yaml\n"
                "from tools.story_extraction import analyze_m4_04b4cr_p4_dev3_compiler_forensics_v1 as f\n"
                "f.validate_public_record(yaml.safe_load(open(sys.argv[1], encoding='utf-8')))\n")
        environment = {**os.environ, "PYTHONPATH": str(forensics.REPO_ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
        completed = subprocess.run([sys.executable, "-c", code, str(path)], cwd=forensics.REPO_ROOT, env=environment,
                                   capture_output=True, text=True)
        self.assertEqual(0, completed.returncode, completed.stderr[-400:])
        tree = ast.parse(Path(forensics.__file__).read_text(encoding="utf-8"))
        inside = [node.lineno for function in ast.walk(tree)
                  if isinstance(function, ast.FunctionDef) and function.name != "_p"
                  for node in ast.walk(function)
                  if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_p"]
        self.assertEqual([], inside)

    def test_integrity_and_reproduction_defects_stop_the_analysis(self):
        private = self.run_.workspace.private
        target = private / "raw_primary" / "DEV3_03.txt"
        original = target.read_bytes()
        try:
            target.write_bytes(original + b" ")
            with self.assertRaises(forensics.IntegrityDefect):
                self.run_.analyze()
        finally:
            target.write_bytes(original)
        other_lock = copy.deepcopy(yaml.safe_load(self.run_.workspace.published_lock.read_text(encoding="utf-8")))
        other_lock["operation_accounting"]["transport_retry_attempts"] += 1
        path = self.run_.workspace.root / "other_lock.yaml"
        path.write_text(yaml.safe_dump(other_lock, sort_keys=False), encoding="utf-8")
        with self.assertRaises(forensics.IntegrityDefect):
            forensics.analyze(private_root=private, input_archive=self.run_.workspace.archive,
                              forensic_root=self.run_.forensic_root, expected_input_sha256=self.run_.workspace.sha256,
                              prediction_lock_path=path)
        with mock.patch.object(forensics, "compile_with_recorder",
                               return_value=(None, [{"phase": "QUOTE", "code": "QUOTE_NOT_FOUND", "path": "x"}], [])):
            with self.assertRaises(forensics.ReproductionDefect):
                self.run_.analyze()
        with mock.patch.object(contract, "compiler_findings", return_value=[]):
            with self.assertRaises(forensics.ReproductionDefect):
                self.run_.analyze()
        self.run_.analyze()

    def test_no_provider_credential_or_gold_is_touched(self):
        with mock.patch.object(b4c, "load_runtime_config", side_effect=AssertionError("credentials")) as credentials, \
                mock.patch.object(b4c, "GeminiDevWindowTransport", side_effect=AssertionError("transport")) as transport, \
                mock.patch("tools.story_extraction.run_m4_04b2_dev_predictions_v1.official_client_factory",
                           side_effect=AssertionError("client")) as client:
            self.run_.analyze()
        for patched in (credentials, transport, client):
            patched.assert_not_called()
        for name in ("dev3_gold.zip", "holdout_input.zip"):
            with self.subTest(archive=name), self.assertRaises(forensics.ForensicsError):
                forensics.analyze(private_root=self.run_.workspace.private,
                                  input_archive=self.run_.workspace.root / name,
                                  forensic_root=self.run_.forensic_root, expected_input_sha256=self.run_.workspace.sha256,
                                  prediction_lock_path=self.run_.workspace.published_lock)
        with self.assertRaises(forensics.IntegrityDefect):
            forensics.analyze(private_root=self.run_.workspace.private, input_archive=self.run_.workspace.archive,
                              forensic_root=self.run_.forensic_root, expected_input_sha256=b4c.DEV3_GOLD_SHA256,
                              prediction_lock_path=self.run_.workspace.published_lock)


class QuoteMatcherTests(unittest.TestCase):
    PASSAGES = {
        "P1": ({"use": "EVIDENCE_ELIGIBLE"}, "aaa bob bob. Cafe\u0301 caf\u00e9"),
        "P2": ({"use": "CONTEXT_ONLY"}, "bob"),
    }

    def classify(self, **record):
        return forensics.classify_locator({"passage_handle": "P1", **record}, self.PASSAGES)

    def test_exact_occurrence_counting_semantics(self):
        self.assertEqual(2, forensics.occurrence_count("aaa", "aa"))
        self.assertEqual(1, "aaa".count("aa"))
        self.assertEqual(2, forensics.occurrence_count("bob bob", "bob"))
        self.assertEqual(0, forensics.occurrence_count("Bob", "bob"))
        self.assertEqual(0, forensics.occurrence_count("caf\u00e9", "cafe\u0301"))
        self.assertEqual(1, forensics.occurrence_count("a  b", "a  b"))
        self.assertEqual(0, forensics.occurrence_count("a  b", "a b"))
        self.assertEqual(compiler_v1._occurrences("aaaa", "aa"), [0, 1, 2])
        self.assertEqual(3, forensics.occurrence_count("aaaa", "aa"))

    def test_locator_classes(self):
        expected = {
            "QUOTE_REPEATED_OCCURRENCE_MISSING": self.classify(quote="bob"),
            "QUOTE_REPEATED_OCCURRENCE_PRESENT": self.classify(quote="bob", occurrence=2),
            "QUOTE_UNIQUE_OCCURRENCE_OMITTED": self.classify(quote="Cafe\u0301"),
            "QUOTE_UNIQUE_OCCURRENCE_PRESENT": self.classify(quote="caf\u00e9", occurrence=1),
            "QUOTE_NOT_FOUND": self.classify(quote="Bob"),
            "QUOTE_LOCATOR_INVALID": self.classify(quote="bob", occurrence=3),
        }
        for label, facts in expected.items():
            self.assertEqual(label, facts["class"], label)
        self.assertEqual("AMBIGUOUS_QUOTE", expected["QUOTE_REPEATED_OCCURRENCE_MISSING"]["reason"])
        self.assertEqual("OCCURRENCE_OUT_OF_RANGE", expected["QUOTE_LOCATOR_INVALID"]["reason"])
        self.assertEqual(("QUOTE_LOCATOR_INVALID", "UNKNOWN_PASSAGE_HANDLE"),
                         tuple(forensics.classify_locator({"passage_handle": "P9", "quote": "bob"}, self.PASSAGES)[k]
                               for k in ("class", "reason")))
        context_only = forensics.classify_locator({"passage_handle": "P2", "quote": "bob"}, self.PASSAGES)
        self.assertEqual(("OTHER_QUOTE_BINDING_FAILURE", "CONTEXT_ONLY_EVIDENCE"),
                         (context_only["class"], context_only["reason"]))
        overlapping = self.classify(quote="aa")
        self.assertEqual(("QUOTE_REPEATED_OCCURRENCE_MISSING", True, 2),
                         (overlapping["class"], overlapping["overlapping_only"], overlapping["exact_occurrences"]))
        self.assertFalse(self.classify(quote="bob")["overlapping_only"])
        self.assertEqual(["1", "2_TO_3", "4_TO_9", "10_OR_MORE", "UNKNOWN"],
                         [forensics._length_bucket(n) for n in (1, 3, 9, 10, None)])
        self.assertEqual(["1", "2", "3_OR_MORE"], [forensics._count_bucket(n) for n in (1, 2, 7)])


class CanonicalIssueClassificationTests(unittest.TestCase):
    def test_every_validator_template_maps_to_a_rule_class_without_keeping_text(self):
        prefix = "draftv1-0123456789abcdef01234567-"
        cases = {
            ("canonical", f"predicate_integrity: duplicate concrete proposition content: {prefix}PROP1 and {prefix}PROP2 "
                          f"are the same {SEMANTIC} proposition; reuse one proposition id"):
                ("predicate_integrity", "DUPLICATE_CONCRETE_PROPOSITION_CONTENT", "OTHER_CANONICAL_CONSTRAINT"),
            ("canonical", f"predicate_integrity: proposition {prefix}PROP1 {SEMANTIC}.x entity kind OBJECT not in ['LOCATION']"):
                ("predicate_integrity", "ARGUMENT_ENTITY_KIND_NOT_ALLOWED", "OTHER_CANONICAL_CONSTRAINT"),
            ("canonical", f"predicate_integrity: proposition {prefix}PROP1 arity mismatch for {SEMANTIC}: got [], expected []"):
                ("predicate_integrity", "PREDICATE_ARGUMENT_SET_MISMATCH", "OTHER_CANONICAL_CONSTRAINT"),
            ("canonical", f"predicate_integrity: proposition {prefix}PROP1 uses unregistered predicate {SEMANTIC}"):
                ("predicate_integrity", "UNREGISTERED_PREDICATE", "OTHER_CANONICAL_CONSTRAINT"),
            ("canonical", f"derivation_integrity: assertion {prefix}A1 derivation {prefix}A1-der-1 rule X cannot conclude Y"):
                ("derivation_integrity", "RULE_CANNOT_CONCLUDE_PREDICATE", "SUPPORT_RELATION"),
            ("canonical", f"derivation_integrity: assertion {prefix}A1 derivation {prefix}A1-der-1 rule X cannot conclude attitude Y"):
                ("derivation_integrity", "RULE_CANNOT_CONCLUDE_ATTITUDE", "SUPPORT_RELATION"),
            ("canonical", f"support_path_integrity: assertion {prefix}A1 has no support path (needs a SUFFICIENT evidence set)"):
                ("support_path_integrity", "NO_SUPPORT_PATH", "SUPPORT_RELATION"),
            ("canonical", f"reference_integrity: assertion {prefix}A1 references unknown proposition {SEMANTIC}"):
                ("reference_integrity", "UNKNOWN_REFERENCE", "CROSS_RECORD_REFERENCE"),
            ("canonical", f"temporal_bound_integrity: assertion {prefix}A1 has validity but predicate {SEMANTIC} is not stative"):
                ("temporal_bound_integrity", "VALIDITY_ON_NON_STATIVE_PREDICATE", "TEMPORAL_CONSTRAINT"),
            ("canonical", f"epistemic_integrity: assertion {prefix}A1 is EXPLICIT without a complete direct evidence path"):
                ("epistemic_integrity", "EXPLICIT_WITHOUT_DIRECT_EVIDENCE_PATH", "OTHER_CANONICAL_CONSTRAINT"),
            ("canonical", f"STRUCTURAL: assertions/0/polarity: '{SEMANTIC}' is not one of ['AFFIRMED']"):
                ("STRUCTURAL", "CANONICAL_RECORD_SCHEMA_VIOLATION", "CANONICAL_RECORD_SCHEMA"),
            ("canonical", f"predicate_integrity: something new about {SEMANTIC}"):
                ("predicate_integrity", "UNCLASSIFIED_ISSUE", "OTHER_CANONICAL_CONSTRAINT"),
            ("canonical", f"{SEMANTIC}: free text"):
                ("UNCLASSIFIED_SECTION", "UNCLASSIFIED_ISSUE", "OTHER_CANONICAL_CONSTRAINT"),
            ("evidence", f"SPAN_MISMATCH: evidence ref {prefix}EV1 does not match the exact source span"):
                ("evidence", "SPAN_MISMATCH", "EVIDENCE_PROVENANCE"),
            ("ids", f"ID_COLLISION: id {prefix}EV1 is used twice in the batch"):
                ("ids", "ID_COLLISION", "EXTRACTION_ENVELOPE"),
            ("scope", "MALFORMED_PASSAGE_INPUT: scope.passage_inputs[0].passage_ref must be an object"):
                ("scope", "MALFORMED_PASSAGE_INPUT", "GUARDED_BATCH_CONFORMANCE"),
            ("review_provenance", f"{SEMANTIC} lower case text: x"):
                ("review_provenance", "UNCLASSIFIED_ISSUE", "EVIDENCE_PROVENANCE"),
        }
        for (check, issue), (section, rule, category) in cases.items():
            entry = forensics.classify_issue(check, issue)
            with self.subTest(rule=rule, section=section):
                self.assertEqual((check, section, rule, category),
                                 (entry["check"], entry["section"], entry["rule_class"], entry["category"]))
                self.assertNotIn(SEMANTIC, json.dumps(entry))
                self.assertNotIn("draftv1-", json.dumps(entry))
        self.assertEqual(["PROP1", "PROP2"], forensics._handles_in(f"{prefix}PROP1 and {prefix}PROP2 are"))
        self.assertEqual(["A1", "A1"], forensics._handles_in(f"assertion {prefix}A1 derivation {prefix}A1-der-1 rule"))

    def test_recorder_returns_the_real_report_and_does_not_change_the_verdict(self):
        run = SyntheticRun()
        self.addCleanup(run.close)
        cases = b4c.load_p4_case_inputs(run.workspace.archive, run.workspace.private / "input",
                                        expected_input_sha256=run.workspace.sha256)
        case = cases[4]
        broken = with_disallowed_entity_kind("DEV3_05")
        real = compiler_v1.validate_batch_guarded
        batch, blockers, reports = forensics.compile_with_recorder(broken, case.compiler_context)
        self.assertIs(real, compiler_v1.validate_batch_guarded)
        self.assertIsNone(batch)
        self.assertEqual([{"phase": "CANONICAL_COMPILER", "code": "CANONICAL_CONFORMANCE_FAILURE", "path": "canonical"}],
                         blockers)
        self.assertEqual(1, len(reports))
        self.assertFalse(reports[0]["pass"])
        self.assertEqual(["canonical"], [name for name, check in reports[0]["checks"].items() if not check["pass"]])
        good, no_blockers, good_reports = forensics.compile_with_recorder(b4c_tests.valid_draft("DEV3_05"),
                                                                           case.compiler_context)
        self.assertIsNotNone(good)
        self.assertEqual(([], True), (no_blockers, good_reports[0]["pass"]))
        registry = forensics.load_registry()
        issue = reports[0]["checks"]["canonical"]["issues"][0]
        self.assertIs(True, forensics.draft_carries_violation("ARGUMENT_ENTITY_KIND_NOT_ALLOWED", issue, broken, registry))
        self.assertIs(False, forensics.draft_carries_violation(
            "ARGUMENT_ENTITY_KIND_NOT_ALLOWED", issue, b4c_tests.valid_draft("DEV3_05"), registry))
        self.assertIsNone(forensics.draft_carries_violation("UNCLASSIFIED_ISSUE", issue, broken, registry))


class ContractAuditAndFrozenStackTests(unittest.TestCase):
    def test_contract_audit_reads_the_accepted_prompt_schema_and_registry(self):
        audit = forensics.contract_audit()
        facts = audit["facts"]
        self.assertTrue(facts["prompt_states_occurrence_is_mandatory_for_a_repeated_quote"])
        self.assertTrue(facts["schema_makes_occurrence_optional"])
        self.assertFalse(facts["schema_can_express_quote_uniqueness"])
        self.assertFalse(facts["prompt_states_how_overlapping_matches_are_counted"])
        self.assertTrue(facts["prompt_contains_the_registry_entity_kind_constraints"])
        self.assertFalse(facts["prompt_prose_explains_entity_kind_constraints"])
        self.assertTrue(facts["prompt_contains_the_derivation_rule_conclusion_predicates"])
        self.assertFalse(facts["prompt_states_propositions_with_identical_content_must_be_one"])
        classes = {rule["requirement"]: rule["classification"] for rule in audit["rules"]}
        self.assertEqual("EXPLICIT_AND_CORRECT", classes["OCCURRENCE_REQUIRED_WHEN_THE_EXACT_QUOTE_REPEATS"])
        self.assertEqual("ABSENT", classes["OVERLAPPING_MATCHES_COUNT_AS_OCCURRENCES"])
        self.assertEqual("IMPLICIT_ONLY", classes["ARGUMENT_ENTITY_KIND_ALLOWED_BY_REGISTRY"])
        self.assertEqual("IMPLICIT_ONLY", classes["DERIVATION_RULE_MAY_CONCLUDE_THE_ASSERTED_PREDICATE"])
        self.assertEqual("ABSENT", classes["PROPOSITIONS_WITH_IDENTICAL_CONTENT_MUST_BE_ONE_RECORD"])
        self.assertEqual("AMBIGUOUS", classes["REPAIR_INSTRUCTIONS_FOR_COMPILER_FINDINGS"])
        allowed = {"EXPLICIT_AND_CORRECT", "IMPLICIT_ONLY", "ABSENT", "AMBIGUOUS", "PROMPT_COMPILER_CONFLICT",
                   "NOT_APPLICABLE"}
        self.assertLessEqual(set(classes.values()), allowed)
        for rule in audit["rules"]:
            self.assertIn(rule["note"], forensics.PROSE)

    def test_frozen_components_and_b4c_records_are_unchanged(self):
        from tools.story_extraction import m4_04b3h0_dev3_decision_lock_v1 as decision_lock

        self.assertEqual({"PASS"}, set(decision_lock.validate_protected_stacks().values()))
        for relative, expected in PINNED.items():
            with self.subTest(path=relative):
                self.assertEqual(expected, protocol.normalized_file_sha256(forensics.REPO_ROOT / relative))
        _, lock_sha256 = b4c.locked_experiment()
        self.assertEqual(B4C_EXPERIMENT_LOCK, lock_sha256)
        self.assertEqual("24b2af927e07078da3a06fe329aa5378cdde92675e76e92e2c03d9ad82726025", protocol.protocol_sha256())
        published = yaml.safe_load(b4c.PREDICTION_LOCK_PATH.read_text(encoding="utf-8"))
        self.assertEqual(B4C_PREDICTION_SET, b4c.validate_public_prediction_lock(published))

    def test_analyzer_has_no_provider_gold_or_evaluator_path_and_changes_no_frozen_code(self):
        source = Path(forensics.__file__).read_text(encoding="utf-8")
        for forbidden in ("load_runtime_config", "GeminiDevWindowTransport", "official_client_factory", "genai",
                          "evaluate_case", "import google", "DurableFirstSuccessProvider", "b4c.run(",
                          "build_durable_stack(", ".acquire("):
            self.assertNotIn(forbidden, source, forbidden)
        for function in (forensics.analyze, forensics.verify_locked_result, forensics.replay_attempts, forensics.main):
            names = set(inspect.signature(function).parameters)
            self.assertFalse(any("gold" in name.lower() or "score" in name.lower() or "evaluat" in name.lower()
                                 for name in names))
        self.assertEqual("NON_PREDICTION_DIAGNOSTIC_ONLY", forensics.NON_PREDICTION_LABEL)
        self.assertNotEqual(b4c.DEFAULT_PRIVATE_ROOT, forensics.DEFAULT_FORENSIC_ROOT)
        self.assertEqual(".local", forensics.DEFAULT_FORENSIC_ROOT.relative_to(forensics.REPO_ROOT).parts[0])
        for option in ("--gold", "--gold-archive", "--evaluate", "--authorize-live-provider-operations"):
            with self.subTest(option=option), self.assertRaises(SystemExit), \
                    mock.patch("sys.stderr"):
                forensics.main(["--mode", "analyze", "--input-archive", "x.zip", option, "x"])


class PublishedForensicRecordTests(unittest.TestCase):
    """The published record of the real forensic pass: structural aggregates only."""

    def setUp(self):
        if not forensics.PUBLIC_RECORD_PATH.exists():
            self.skipTest("The M4-04B4CR record has not been published")
        self.text = forensics.PUBLIC_RECORD_PATH.read_text(encoding="utf-8")
        self.record = yaml.safe_load(self.text)

    def test_record_is_allowlisted_and_bound_to_the_accepted_b4c_result(self):
        forensics.validate_public_record(self.record)
        self.assertEqual(("M4-04B4CR", "M4_04B4CR_COMPILER_FORENSICS_COMPLETE",
                          "30436aca8d19fff16b61c3385a169568df575008"),
                         (self.record["task"], self.record["status"], self.record["base_commit"]))
        accepted = self.record["accepted_B4C"]
        self.assertEqual(("M4_04B4C_P4_DEV3_TUNING_COMPLETE", B4C_EXPERIMENT_LOCK, B4C_PREDICTION_SET,
                          "24b2af927e07078da3a06fe329aa5378cdde92675e76e92e2c03d9ad82726025"),
                         (accepted["status"], accepted["experiment_lock_sha256"], accepted["prediction_set_sha256"],
                          accepted["protocol_sha256"]))
        self.assertEqual("TUNING_COMPARISON_NOT_BLIND_VALIDATION", accepted["comparison_with_p3"]["label"])
        self.assertEqual(protocol.normalized_file_sha256(Path(forensics.__file__)), self.record["analyzer"]["sha256"])

    def test_reference_observations_were_reproduced_not_injected(self):
        totals = self.record["attempt_metrics"]["totals"]
        self.assertEqual((16, 16, 16, 5, 11, 5, 5, 6, 4, 1),
                         (totals["attempts"], totals["json_valid"], totals["full_schema_valid"],
                          totals["compiler_success"], totals["compiler_failure"],
                          totals["final_structural_valid_cases"], totals["final_structural_failure_cases"],
                          totals["repair_attempts"], totals["identical_repair_responses"],
                          totals["repair_compiler_successes"]))
        self.assertEqual({"AMBIGUOUS_QUOTE": 6, "CANONICAL_CONFORMANCE_FAILURE": 5}, totals["first_blocker_codes"])
        self.assertEqual((4, 1), (self.record["attempt_metrics"]["primary"]["compiler_success"],
                                  self.record["attempt_metrics"]["repair"]["compiler_success"]))
        reproduction = self.record["reproduction"]
        self.assertEqual({"raw_responses": 16, "parsed_drafts": 16, "compiled_batches": 5,
                          "terminal_failure_records": 5, "diagnostics": 11, "case_results": 10,
                          "durable_checkpoints": 16}, reproduction["artifact_counts"])
        self.assertEqual(B4C_PREDICTION_SET, reproduction["prediction_set_sha256_rebuilt_from_artifact_files"])
        self.assertTrue(reproduction["compiler_results_reproduced"])
        self.assertEqual(0, reproduction["provider_operations_during_forensics"])
        source = Path(forensics.__file__).read_text(encoding="utf-8")
        self.assertNotIn(B4C_PREDICTION_SET, source)

    def test_boundaries_decision_and_public_safety(self):
        boundaries = self.record["boundaries"]
        self.assertEqual((0, 0), (boundaries["provider_calls"], boundaries["model_calls"]))
        for name in ("predictions_rerun", "DEV3_gold_opened", "holdout_opened", "semantic_scoring",
                     "frozen_stack_modified", "redesign_implemented", "new_acceptance_threshold_introduced"):
            self.assertIs(False, boundaries[name], name)
        decision = self.record["decision"]
        self.assertIs(False, decision["implementation_authorized"])
        self.assertIs(False, decision["semantic_quality_claim"])
        self.assertTrue(decision["next_research_candidate"])
        self.assertNotRegex(self.text, r"AIza[0-9A-Za-z_\-]{10,}")
        for forbidden in ("GEMINI_API_KEY", "draftv1-", "char_start", "E_NEW_", "PROP1", "C:\\"):
            self.assertNotIn(forbidden, self.text)

    def test_project_state_records_the_forensic_outcome(self):
        state = (forensics.REPO_ROOT / "docs/PROJECT_STATE.md").read_text(encoding="utf-8")
        self.assertIn(f"Status: {self.record['status']}", state)
        for candidate in self.record["decision"]["next_research_candidate"]:
            self.assertIn(candidate, state)


if __name__ == "__main__":
    unittest.main()
