import ast
import inspect
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import yaml

from tools.story_extraction import m4_04b3h0_dev3_decision_lock_v1 as lock
from tools.story_extraction.m4_04b2_dev_protocol_v1 import build_protocol as build_b2_protocol
from tools.story_extraction.m4_04b3f_dev3_p3_protocol_v1 import REPO_ROOT, normalized_file_sha256


PINNED_DECISION_RECORD_SHA256 = "5826854dfe6828ebea67e0d4c089fbda148fcc89da9efc80f1afb244aa329735"
MODULE_PATH = REPO_ROOT / "tools/story_extraction/m4_04b3h0_dev3_decision_lock_v1.py"
PUBLIC_DIR = REPO_ROOT / "benchmarks/m4_extraction"

# The established B2 safety gate, mapped onto the DEV3 check that preserves it.
B2_GATE_TO_DEV3_CHECK = {
    "ALL_SELECTED_FINAL_PREDICTIONS_L0_CONFORMANT": "ALL_FINAL_PREDICTIONS_L0_SOURCE_EXACT_VALID",
    "ZERO_CRITICAL_UNSUPPORTED": "ZERO_CRITICAL_UNSUPPORTED",
    "ZERO_HIGH_UNSUPPORTED": "ZERO_HIGH_UNSUPPORTED",
    "NO_UNRESOLVED_EVALUATOR_INTEGRITY_DEFECT": "NO_UNRESOLVED_EVALUATION_OR_PROTOCOL_DEFECT",
    "NO_PROTOCOL_VIOLATION": "NO_PROTOCOL_VIOLATION",
    "NO_DEV_PREDICTION_AFTER_GOLD_ACCESS": "NO_PROVIDER_OR_MODEL_CALL_AFTER_GOLD_OPEN",
    "NO_HOLDOUT_ACCESS": "NO_HOLDOUT_ACCESS",
    "TRANSPORT_EXECUTION_INVARIANTS_PASS": "TRANSPORT_EXECUTION_INVARIANTS_PASS",
}


def clean_observation():
    """Observed facts of a run that violates nothing. Synthetic; no DEV3 content."""
    return {
        "p3_predictions_executed_under_locked_protocol": True,
        "terminal_case_count": 10,
        "prediction_package_sha256_created": True,
        "public_prediction_lock_committed": True,
        "prediction_lock_pushed_and_remote_sha_verified": True,
        "dev3_gold_opened_only_after_remote_verified_prediction_lock": True,
        "provider_or_model_calls_after_gold_open": 0,
        "l0_valid_final_case_count": 10,
        "critical_unsupported_count": 0,
        "high_unsupported_count": 0,
        "unrated_unsupported_count": 0,
        "pending_adjudication_count": 0,
        "unresolved_evaluation_or_protocol_defect_count": 0,
        "protocol_violation_count": 0,
        "holdout_accessed": False,
        "protected_extractor_stack_changed_after_prediction_lock": False,
        "transport_execution_invariants_pass": True,
    }


def violate(value):
    if isinstance(value, bool):
        return not value
    return value + 1 if value == 0 else value - 1


class M404B3H0Dev3DecisionLockTests(unittest.TestCase):
    def setUp(self):
        self.record = lock.locked_decision_record()
        self.safety = {item["id"]: item for item in self.record["safety_gate"]["checks"]}
        self.steps = self.record["chronology"]["steps"]

    def test_binds_dev3_hashes_protocol_and_case_order(self):
        applies = self.record["applies_to"]
        self.assertEqual(
            "47ae7c743065f8ff001f4db6a398df2edf1db094383b1fe2d0c3a05ab40c55c7",
            applies["dev3_input_sha256"],
        )
        self.assertEqual(
            "b5b2258d46608015ff60de2c660fba521029ff4716c7c1cc3b3735c55dfd34a9",
            applies["dev3_gold_sha256"],
        )
        self.assertEqual(
            "f9cf1c25a21bb3bfc910b8e218c8dac9f032d67957f8d7cb58397134a0504bae",
            applies["p3_protocol_sha256"],
        )
        self.assertEqual([f"DEV3_{index:02d}" for index in range(1, 11)], applies["case_order"])
        self.assertEqual(10, applies["case_count"])
        self.assertEqual(1, applies["candidate_count"])

    def test_binds_snapshot_v2_identity(self):
        evaluation = self.record["evaluation"]
        self.assertEqual("M4_EVALUATION_PROTOCOL_SNAPSHOT_V2", evaluation["snapshot_identity"])
        self.assertEqual(
            "8dddbd0b9f3ea51af593c1fab0631b088b6f4e6b8c16833a1f11b8448088eee9",
            evaluation["snapshot_identity_sha256"],
        )
        snapshot = yaml.safe_load(
            (PUBLIC_DIR / "M4_EVALUATION_PROTOCOL_SNAPSHOT_V2.yaml").read_text(encoding="utf-8")
        )
        self.assertEqual(snapshot["snapshot_id"], evaluation["snapshot_identity"])
        self.assertEqual(snapshot["snapshot_sha256"], evaluation["snapshot_identity_sha256"])
        self.assertEqual(snapshot["evaluator_entrypoint"], evaluation["evaluator_entrypoint"])

    def test_protected_stacks_match_tracked_files_and_prior_public_locks(self):
        self.assertTrue(all(value == "PASS" for value in lock.validate_protected_stacks().values()))
        b3f = yaml.safe_load((PUBLIC_DIR / "M4_04B3F_DEV3_P3_PROTOCOL_LOCK.yaml").read_text(encoding="utf-8"))
        b3g = yaml.safe_load(
            (PUBLIC_DIR / "M4_04B3G_P3_RUNNER_OFFLINE_READINESS.yaml").read_text(encoding="utf-8")
        )
        stack = self.record["protected_extractor_stack"]
        self.assertEqual(b3f["private_canonical_protocol"]["sha256"], lock.P3_PROTOCOL_SHA256)
        for source in b3f["prompt_sources"].values():
            if isinstance(source, dict):
                self.assertEqual(source["sha256"], stack[source["path"]])
        self.assertEqual(b3g["artifacts"]["runner"]["sha256"], stack[b3g["artifacts"]["runner"]["path"]])
        self.assertEqual(b3g["locked_bindings"]["protocol_sha256"], lock.P3_PROTOCOL_SHA256)

    def test_decision_categories_and_precedence_are_fixed(self):
        decision = self.record["decision"]
        self.assertEqual(
            [
                "PROTOCOL_INVALID",
                "DEV3_SAFETY_FAIL",
                "DEV3_SAFE_BUT_COMPETENCE_REVIEW_REQUIRED",
                "DEV3_HOLDOUT_ELIGIBLE",
            ],
            decision["labels"],
        )
        self.assertEqual(
            ["PROTOCOL_INVALID", "DEV3_SAFETY_FAIL", "DEV3_SAFE_BUT_COMPETENCE_REVIEW_REQUIRED"],
            [rule["label"] for rule in decision["precedence"]],
        )
        self.assertNotIn("DEV3_HOLDOUT_ELIGIBLE", decision["scorer_assignable_labels"])
        self.assertFalse(decision["scorer_decides_policy"])
        self.assertEqual("FORBIDDEN", decision["holdout_eligible"]["automatic_assignment"])
        self.assertFalse(decision["holdout_eligible"]["scorer_may_assign"])

    def test_safety_gate_requires_l0_and_zero_critical_and_high(self):
        self.assertTrue(self.record["safety_gate"]["automatic"])
        self.assertTrue(self.record["safety_gate"]["any_single_failure_fails_the_gate"])
        l0 = self.safety["ALL_FINAL_PREDICTIONS_L0_SOURCE_EXACT_VALID"]
        self.assertEqual(("l0_valid_final_case_count", 10), (l0["observation"], l0["required"]))
        for check_id, observation in (
            ("ZERO_CRITICAL_UNSUPPORTED", "critical_unsupported_count"),
            ("ZERO_HIGH_UNSUPPORTED", "high_unsupported_count"),
            ("ZERO_UNRATED_UNSUPPORTED", "unrated_unsupported_count"),
        ):
            self.assertEqual(observation, self.safety[check_id]["observation"])
            self.assertEqual(0, self.safety[check_id]["required"])
            self.assertIs(int, type(self.safety[check_id]["required"]))

    def test_safety_gate_preserves_every_established_b2_check(self):
        b2_gate = build_b2_protocol()["safety_gate"]
        self.assertEqual(sorted(B2_GATE_TO_DEV3_CHECK), sorted(b2_gate))
        for b2_check in b2_gate:
            self.assertIn(B2_GATE_TO_DEV3_CHECK[b2_check], self.safety)
        for mandated in (
            "NO_PROTECTED_EXTRACTOR_STACK_CHANGE_AFTER_PREDICTION_LOCK",
            "NO_HOLDOUT_ACCESS",
            "NO_PROVIDER_OR_MODEL_CALL_AFTER_GOLD_OPEN",
            "NO_PROTOCOL_VIOLATION",
            "NO_UNRESOLVED_EVALUATION_OR_PROTOCOL_DEFECT",
        ):
            self.assertIn(mandated, self.safety)

    def test_every_single_safety_violation_is_a_hard_failure(self):
        chronology_fields = {step["observation"] for step in self.steps}
        for check in self.record["safety_gate"]["checks"]:
            observation = clean_observation()
            observation[check["observation"]] = violate(check["required"])
            result = lock.decide(observation)
            self.assertIn(check["id"], result["safety_gate_failures"])
            self.assertFalse(result["safety_gate_pass"])
            self.assertEqual("FORBIDDEN", result["holdout_progression"])
            expected = "PROTOCOL_INVALID" if check["observation"] in chronology_fields else "DEV3_SAFETY_FAIL"
            self.assertEqual(expected, result["label"])

    def test_chronology_locks_prediction_before_gold(self):
        self.assertEqual(list("ABCDEFG"), [step["step"] for step in self.steps])
        ids = [step["id"] for step in self.steps]
        self.assertLess(ids.index("ALL_10_CASES_TERMINAL"), ids.index("PREDICTION_PACKAGE_AND_SHA256_CREATED"))
        self.assertLess(ids.index("PUBLIC_PREDICTION_LOCK_COMMITTED"), ids.index("BRANCH_PUSHED_AND_REMOTE_SHA_VERIFIED"))
        self.assertLess(
            ids.index("BRANCH_PUSHED_AND_REMOTE_SHA_VERIFIED"), ids.index("DEV3_GOLD_OPENED_ONLY_AFTER_STEP_E")
        )
        self.assertEqual("PROTOCOL_INVALID", self.record["chronology"]["violation_label"])
        self.assertEqual(
            "DEV3_CANNOT_SUPPORT_PROGRESSION_CLAIMS", self.record["chronology"]["violation_consequence"]
        )
        for step in self.steps:
            observation = clean_observation()
            observation[step["observation"]] = violate(step["required"])
            result = lock.decide(observation)
            self.assertEqual("PROTOCOL_INVALID", result["label"])
            self.assertIn(step["id"], result["chronology_failures"])
            self.assertEqual("FORBIDDEN", result["holdout_progression"])

    def test_zero_provider_or_model_calls_after_gold_open(self):
        final_step = self.steps[-1]
        self.assertEqual("ZERO_PROVIDER_OR_MODEL_CALLS_AFTER_GOLD_OPEN", final_step["id"])
        self.assertEqual(0, final_step["required"])
        self.assertEqual(0, self.safety["NO_PROVIDER_OR_MODEL_CALL_AFTER_GOLD_OPEN"]["required"])
        self.assertEqual(0, self.record["safety_gate"]["adjudication"]["provider_or_model_calls"])
        observation = clean_observation()
        observation["provider_or_model_calls_after_gold_open"] = 1
        self.assertEqual("PROTOCOL_INVALID", lock.decide(observation)["label"])

    def test_protocol_invalid_takes_precedence_over_safety_fail(self):
        observation = clean_observation()
        observation["public_prediction_lock_committed"] = False
        observation["critical_unsupported_count"] = 3
        result = lock.decide(observation)
        self.assertEqual("PROTOCOL_INVALID", result["label"])
        self.assertEqual(["ZERO_CRITICAL_UNSUPPORTED"], result["safety_gate_failures"])

    def test_no_holdout_access(self):
        self.assertFalse(self.safety["NO_HOLDOUT_ACCESS"]["required"])
        self.assertEqual("FORBIDDEN", self.record["holdout"]["access_under_this_record"])
        observation = clean_observation()
        observation["holdout_accessed"] = True
        self.assertEqual("DEV3_SAFETY_FAIL", lock.decide(observation)["label"])

    def test_safe_run_requires_review_and_is_never_automatically_holdout_eligible(self):
        result = lock.decide(clean_observation())
        self.assertEqual("DEV3_SAFE_BUT_COMPETENCE_REVIEW_REQUIRED", result["label"])
        self.assertEqual("REQUIRES_SEPARATE_ORCHESTRATOR_DECISION", result["holdout_progression"])
        self.assertFalse(result["automatic_holdout_eligibility"])
        self.assertEqual(PINNED_DECISION_RECORD_SHA256, result["decision_record_sha256"])
        source = inspect.getsource(lock.decide)
        self.assertNotIn("LABEL_HOLDOUT_ELIGIBLE", source)
        self.assertNotIn("DEV3_HOLDOUT_ELIGIBLE", source)

    def test_no_competence_threshold_is_introduced(self):
        competence = self.record["competence"]
        self.assertEqual("NONE_FOUND_IN_REPOSITORY", competence["prior_normative_numeric_threshold"])
        self.assertEqual("NOT_INTRODUCED", competence["NEW_PRE_REGISTERED_DEV3_THRESHOLD"])
        self.assertEqual("NONE", competence["quantitative_competence_floor"])
        self.assertFalse(competence["automatic_holdout_eligibility"])

        def numbers(value):
            if isinstance(value, dict):
                return [n for item in value.values() for n in numbers(item)]
            if isinstance(value, list):
                return [n for item in value for n in numbers(item)]
            return [value] if isinstance(value, (int, float)) and not isinstance(value, bool) else []

        self.assertEqual([], numbers(competence))
        for prohibited in ("NEW_THRESHOLD", "NEW_METRIC", "NEW_WEIGHTING_OR_COMPOSITE_SCORE",
                           "PREDICTION_RETRY_OR_RERUN", "CASE_OR_METRIC_SUPPRESSION"):
            self.assertIn(prohibited, self.record["post_gold_prohibitions"])
        self.assertEqual("FORBIDDEN", competence["publication"]["case_or_metric_suppression"])

    def test_metric_names_are_the_existing_repository_names(self):
        competence = self.record["competence"]
        frozen = (REPO_ROOT / "tools/story_extraction/evaluate_extraction_v0.py").read_text(encoding="utf-8")
        summary = (REPO_ROOT / "tools/story_extraction/evaluate_m4_04b2r_dev_v2.py").read_text(encoding="utf-8")
        for name in competence["per_case_metrics"] + competence["aggregate_metrics"] + competence["per_case_fields"]:
            self.assertIn(f'"{name}"', frozen)
        for name in competence["aggregate_mean_metrics"] + competence["layers"]:
            self.assertIn(f'"{name}"', summary)
        for severity in competence["unsupported_severity_levels"]:
            self.assertIn(f'"{severity}"', summary)
        for primary in competence["primary_indicators"]:
            self.assertIn(primary, competence["aggregate_metrics"] + competence["aggregate_mean_metrics"])
        for required in ("full_canonical_case_success_count", "assertion_recall", "evidence_grounding_recall_mean"):
            self.assertIn(required, competence["primary_indicators"])

    def test_scorer_cannot_supply_or_alter_policy(self):
        self.assertEqual(["observation"], list(inspect.signature(lock.decide).parameters))
        for extra in ("threshold", "minimum_assertion_recall", "policy", "weights"):
            observation = clean_observation()
            observation[extra] = 0
            with self.assertRaisesRegex(lock.DecisionLockError, "Unknown observation"):
                lock.decide(observation)
        observation = clean_observation()
        del observation["high_unsupported_count"]
        with self.assertRaisesRegex(lock.DecisionLockError, "Missing observation"):
            lock.decide(observation)
        for name, value in (("high_unsupported_count", False), ("holdout_accessed", 0),
                            ("critical_unsupported_count", -1), ("l0_valid_final_case_count", 10.0)):
            observation = clean_observation()
            observation[name] = value
            with self.assertRaisesRegex(lock.DecisionLockError, "Invalid observation"):
                lock.decide(observation)
        returned = lock.locked_decision_record()
        returned["safety_gate"]["checks"].clear()
        failing = clean_observation()
        failing["high_unsupported_count"] = 1
        self.assertEqual("DEV3_SAFETY_FAIL", lock.decide(failing)["label"])

    def test_any_policy_change_breaks_the_pinned_record(self):
        self.assertEqual(PINNED_DECISION_RECORD_SHA256, lock.DECISION_RECORD_SHA256)
        self.assertEqual(PINNED_DECISION_RECORD_SHA256, lock.decision_record_sha256())
        weakened = dict(lock.PROTECTED_EXTRACTOR_STACK)
        weakened.popitem()
        for target, value in (
            ("LABEL_SAFE_REVIEW", "DEV3_HOLDOUT_ELIGIBLE"),
            ("SCORER_ASSIGNABLE_LABELS", ("DEV3_HOLDOUT_ELIGIBLE",)),
            ("DEV3_GOLD_SHA256", "0" * 64),
            ("PROTECTED_EXTRACTOR_STACK", weakened),
        ):
            with mock.patch.object(lock, target, value):
                with self.assertRaises(lock.DecisionLockError):
                    lock.locked_decision_record()
                with self.assertRaises(lock.DecisionLockError):
                    lock.decide(clean_observation())

    def test_public_record_carries_exactly_the_pinned_decision_record(self):
        self.assertTrue(all(value == "PASS" for value in lock.validate_public_lock().values()))
        public = yaml.safe_load(lock.PUBLIC_LOCK_PATH.read_text(encoding="utf-8"))
        self.assertEqual(PINNED_DECISION_RECORD_SHA256, public["decision_record_sha256"])
        self.assertEqual(self.record, public["decision_record"])
        self.assertEqual("M4_04B3H0_DEV3_EVALUATION_DECISION_LOCKED", public["status"])
        self.assertEqual(normalized_file_sha256(MODULE_PATH), public["tooling"]["decision_record"]["sha256"])
        self.assertEqual(normalized_file_sha256(Path(__file__)), public["tooling"]["focused_tests"]["sha256"])
        public["decision_record"]["safety_gate"]["checks"].pop()
        with tempfile.TemporaryDirectory() as directory:
            mutated = Path(directory) / "lock.yaml"
            mutated.write_text(yaml.safe_dump(public, sort_keys=False), encoding="utf-8")
            with self.assertRaises(lock.DecisionLockError):
                lock.validate_public_lock(mutated)

    def test_public_record_boundaries(self):
        boundaries = yaml.safe_load(lock.PUBLIC_LOCK_PATH.read_text(encoding="utf-8"))["boundaries"]
        self.assertEqual(0, boundaries["provider_or_API_calls"])
        for name in ("DEV3_input_opened", "DEV3_gold_opened", "holdout_accessed", "prediction_started",
                     "scoring_or_evaluator_run"):
            self.assertIs(False, boundaries[name])

    def test_no_dev3_package_content_or_evaluator_is_required(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        imported = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module)
        self.assertEqual(
            {"__future__", "pathlib", "typing", "yaml", "tools.story_extraction.m4_04b3f_dev3_p3_protocol_v1"},
            imported,
        )
        for forbidden in ("zipfile", "ZipFile", ".zip", ".local", "evaluate_case", "api_key"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
