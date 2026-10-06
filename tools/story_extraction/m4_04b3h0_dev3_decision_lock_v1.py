"""Pre-registered DEV3 evaluation decision rule for the locked P3 extractor (M4-04B3H0).

This module is policy data plus one pure function. It reads tracked public files only.
It does not locate or open DEV3 packages, predictions, gold, credentials, transports or
holdout artifacts, and it scores nothing. A future scorer supplies observed facts and
receives the label this record dictates; it cannot pass a threshold, weight or policy.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from tools.story_extraction.m4_04b3f_dev3_p3_protocol_v1 import (
    CASE_IDS,
    COMPILER_SHA256,
    DEV3_GOLD_SHA256,
    DEV3_INPUT_SHA256,
    DRAFT_SCHEMA_SHA256,
    DURABLE_EXECUTOR_SHA256,
    EXTRACTOR_ID,
    PREDICATE_REGISTRY_SHA256,
    PROTOCOL_ID,
    REPO_ROOT,
    RUNTIME_SHA256,
    SNAPSHOT_V2_FILE_SHA256,
    SNAPSHOT_V2_ID,
    SNAPSHOT_V2_SHA256,
    build_protocol,
    canonical_json_bytes,
    normalized_file_sha256,
    sha256_bytes,
    validate_public_bindings,
)


TASK_ID = "M4-04B3H0"
EXPECTED_BASE_COMMIT = "ffc5fbf3513537043aa99ea67133d68b51a143e8"
RECORD_ID = "M4_04B3H0_DEV3_EVALUATION_DECISION_RECORD_V1"
RECORD_SCHEMA_VERSION = "M4_04B3H0_DEV3_EVALUATION_DECISION_RECORD_SCHEMA_V1"
PUBLIC_LOCK_PATH = REPO_ROOT / "benchmarks/m4_extraction/M4_04B3H0_DEV3_EVALUATION_DECISION_LOCK.yaml"

# SHA-256 of canonical_json_bytes(build_decision_record()). Changing any policy below
# changes this value; a changed policy is a new task, never an edit of this record.
DECISION_RECORD_SHA256 = "5826854dfe6828ebea67e0d4c089fbda148fcc89da9efc80f1afb244aa329735"

P3_PROTOCOL_SHA256 = "f9cf1c25a21bb3bfc910b8e218c8dac9f032d67957f8d7cb58397134a0504bae"

LABEL_PROTOCOL_INVALID = "PROTOCOL_INVALID"
LABEL_SAFETY_FAIL = "DEV3_SAFETY_FAIL"
LABEL_SAFE_REVIEW = "DEV3_SAFE_BUT_COMPETENCE_REVIEW_REQUIRED"
LABEL_HOLDOUT_ELIGIBLE = "DEV3_HOLDOUT_ELIGIBLE"
SCORER_ASSIGNABLE_LABELS = (LABEL_PROTOCOL_INVALID, LABEL_SAFETY_FAIL, LABEL_SAFE_REVIEW)

# Public tracked files whose content is fixed by the B3F/B3G locks and Snapshot V2.
# Hash mode: UTF8_LF_NORMALIZED_SHA256.
PROTECTED_EXTRACTOR_STACK = {
    "tools/story_extraction/prompts/story_extraction_draft_p3_v1_1_system.txt":
        "9eb4aa33c4dd20cb62e6014b215e85f063861856c8243385a8ae7d74dcc55670",
    "tools/story_extraction/prompts/story_extraction_draft_p3_v1_1_user.txt":
        "eeda5645bc5e319d1bfeb4c99a4276fd0a070103eb95409c357370b7255e96d1",
    "tools/story_extraction/prompts/story_extraction_draft_p3_v1_1_repair_user.txt":
        "bf0831479337f0212e779ee3e99fc9ad2872c1267fa6c7ac9e2f670a72e8233d",
    "schemas/story_extraction/story_extraction_draft_v1_1.schema.json": DRAFT_SCHEMA_SHA256,
    "tools/story_extraction/draft_compiler_v1_1.py": COMPILER_SHA256,
    "schemas/canonical_story/predicate_registry_v0.yaml": PREDICATE_REGISTRY_SHA256,
    "tools/story_extraction/gemini_resilience_v1_1.py": RUNTIME_SHA256,
    "tools/story_extraction/durable_research_executor_v1.py": DURABLE_EXECUTOR_SHA256,
    "tools/story_extraction/m4_04b3f_dev3_p3_protocol_v1.py":
        "ff50740344b46a904cc32b0ffd6ad71509a466fc518be50da69b8c190712c2c0",
    "tools/story_extraction/run_m4_04b3g_dev3_p3_predictions_v1.py":
        "a07a26240c9d30d96bf455a4f88173a38a3b1538a8de2d32d3f09b7402be5087",
}
PROTECTED_EVALUATION_STACK = {
    "benchmarks/m4_extraction/M4_EVALUATION_PROTOCOL_SNAPSHOT_V2.yaml": SNAPSHOT_V2_FILE_SHA256,
    "docs/research/m4/M4_EXTRACTION_EVALUATION_PROTOCOL_V0.md":
        "c67c9514f6648d314f4e7ccebaa49025b6498f4fdce0710433521ee76a672617",
    "tools/story_extraction/evaluate_extraction_v0.py":
        "f6294985820bea2d4232888e15323c321e7f7ff5bc12ec282ee3e096daa33f96",
    "tools/story_extraction/extraction_contract_guard_v1.py":
        "85c6c7c81df3d0e144ba308a76430503aa9a643596f28e233a08a0e0ba9eebe0",
    "tools/story_extraction/evaluate_extraction_guarded_v1.py":
        "399347558c562d5438c94239ecd9aaea9f21fb79311d2c249cd311a5eed7a15d",
}


class DecisionLockError(RuntimeError):
    """The decision record, a public binding or an observation differs from the lock."""


def _check(check_id: str, observation: str, required: Any, origin: str) -> dict[str, Any]:
    return {"id": check_id, "observation": observation, "required": required, "origin": origin}


def build_decision_record() -> dict[str, Any]:
    case_count = len(CASE_IDS)
    return {
        "record_id": RECORD_ID,
        "record_schema_version": RECORD_SCHEMA_VERSION,
        "task_id": TASK_ID,
        "base_commit": EXPECTED_BASE_COMMIT,
        "locked_before_any_p3_dev3_prediction": True,
        "applies_to": {
            "extractor_id": EXTRACTOR_ID,
            "candidate_count": 1,
            "p3_protocol_id": PROTOCOL_ID,
            "p3_protocol_sha256": P3_PROTOCOL_SHA256,
            "dev3_input_sha256": DEV3_INPUT_SHA256,
            "dev3_gold_sha256": DEV3_GOLD_SHA256,
            "case_count": case_count,
            "case_order": list(CASE_IDS),
        },
        "evaluation": {
            "snapshot_identity": SNAPSHOT_V2_ID,
            "snapshot_identity_sha256": SNAPSHOT_V2_SHA256,
            "snapshot_file_sha256": SNAPSHOT_V2_FILE_SHA256,
            "hash_mode": "UTF8_LF_NORMALIZED_SHA256",
            "evaluator_entrypoint": "tools/story_extraction/evaluate_extraction_guarded_v1.py",
            "case_parameters": "SEALED_GOLD_PACKAGE_CASE_SPEC_UNCHANGED",
            "evaluation_mode_if_sealed_case_spec_is_silent": "REAL_SOURCE",
            "only_permitted_case_spec_addition": "adjudications",
            "gold_status_must_be_stated_with_results": ["AGENT_DRAFT_GOLD", "NOT_HUMAN_CONFIRMED"],
            "l0_definition": "SNAPSHOT_V2_GUARDED_L0_STRUCTURAL_VALIDITY_WITH_SOURCE_EXACT_INGESTION",
            "terminal_structural_failure_case": "L0_FAIL_AND_FULL_CANONICAL_CASE_SUCCESS_FALSE",
        },
        "chronology": {
            "violation_label": LABEL_PROTOCOL_INVALID,
            "violation_consequence": "DEV3_CANNOT_SUPPORT_PROGRESSION_CLAIMS",
            "steps": [
                {"step": "A", **_check(
                    "P3_PREDICTION_EXECUTION_UNDER_LOCKED_PROTOCOL",
                    "p3_predictions_executed_under_locked_protocol", True, "B3F_PROTOCOL_LOCK")},
                {"step": "B", **_check(
                    "ALL_10_CASES_TERMINAL", "terminal_case_count", case_count, "B3F_PROTOCOL_LOCK")},
                {"step": "C", **_check(
                    "PREDICTION_PACKAGE_AND_SHA256_CREATED",
                    "prediction_package_sha256_created", True, "B3F_PROTOCOL_LOCK")},
                {"step": "D", **_check(
                    "PUBLIC_PREDICTION_LOCK_COMMITTED",
                    "public_prediction_lock_committed", True, "B3F_PROTOCOL_LOCK")},
                {"step": "E", **_check(
                    "BRANCH_PUSHED_AND_REMOTE_SHA_VERIFIED",
                    "prediction_lock_pushed_and_remote_sha_verified", True, "B3F_PROTOCOL_LOCK")},
                {"step": "F", **_check(
                    "DEV3_GOLD_OPENED_ONLY_AFTER_STEP_E",
                    "dev3_gold_opened_only_after_remote_verified_prediction_lock", True,
                    "B3F_PROTOCOL_LOCK")},
                {"step": "G", **_check(
                    "ZERO_PROVIDER_OR_MODEL_CALLS_AFTER_GOLD_OPEN",
                    "provider_or_model_calls_after_gold_open", 0, "B3F_PROTOCOL_LOCK")},
            ],
        },
        "safety_gate": {
            "automatic": True,
            "failure_label": LABEL_SAFETY_FAIL,
            "failure_consequence": "NOT_ELIGIBLE_FOR_HOLDOUT_PROGRESSION",
            "any_single_failure_fails_the_gate": True,
            "checks": [
                _check("ALL_FINAL_PREDICTIONS_L0_SOURCE_EXACT_VALID",
                       "l0_valid_final_case_count", case_count, "B2_NORMATIVE_SAFETY_GATE"),
                _check("ZERO_CRITICAL_UNSUPPORTED",
                       "critical_unsupported_count", 0, "B2_NORMATIVE_SAFETY_GATE"),
                _check("ZERO_HIGH_UNSUPPORTED",
                       "high_unsupported_count", 0, "B2_NORMATIVE_SAFETY_GATE"),
                _check("ZERO_UNRATED_UNSUPPORTED",
                       "unrated_unsupported_count", 0, "B3H0_FAIL_CLOSED_CLARIFICATION"),
                _check("ZERO_PENDING_ADJUDICATION",
                       "pending_adjudication_count", 0, "B3H0_FAIL_CLOSED_CLARIFICATION"),
                _check("NO_UNRESOLVED_EVALUATION_OR_PROTOCOL_DEFECT",
                       "unresolved_evaluation_or_protocol_defect_count", 0, "B2_NORMATIVE_SAFETY_GATE"),
                _check("NO_PROTOCOL_VIOLATION",
                       "protocol_violation_count", 0, "B2_NORMATIVE_SAFETY_GATE"),
                _check("NO_PROVIDER_OR_MODEL_CALL_AFTER_GOLD_OPEN",
                       "provider_or_model_calls_after_gold_open", 0, "B2_NORMATIVE_SAFETY_GATE"),
                _check("NO_HOLDOUT_ACCESS",
                       "holdout_accessed", False, "B2_NORMATIVE_SAFETY_GATE"),
                _check("NO_PROTECTED_EXTRACTOR_STACK_CHANGE_AFTER_PREDICTION_LOCK",
                       "protected_extractor_stack_changed_after_prediction_lock", False,
                       "B3H0_TASK_MANDATE"),
                _check("TRANSPORT_EXECUTION_INVARIANTS_PASS",
                       "transport_execution_invariants_pass", True, "B2_NORMATIVE_SAFETY_GATE"),
            ],
            "counts_as_unresolved_evaluation_or_protocol_defect": [
                "EVALUATOR_OR_SNAPSHOT_V2_INTEGRITY_DEFECT",
                "GOLD_BATCH_FAILS_GUARDED_VALIDATION",
                "ALIGNMENT_AMBIGUITY_WITHOUT_RECORDED_RESOLUTION",
                "PREDICTION_OR_GOLD_HASH_MISMATCH",
            ],
            "adjudication": {
                "ontology": "EXISTING_SNAPSHOT_V2_STATES_AND_SEVERITIES_ONLY",
                "provider_or_model_calls": 0,
                "every_adjudication_published_public_safe": True,
                "adjudicator_kind_must_be_disclosed": True,
                "human_adjudication_status_must_be_disclosed": True,
            },
        },
        "decision": {
            "labels": [
                LABEL_PROTOCOL_INVALID,
                LABEL_SAFETY_FAIL,
                LABEL_SAFE_REVIEW,
                LABEL_HOLDOUT_ELIGIBLE,
            ],
            "precedence": [
                {"if": "ANY_CHRONOLOGY_STEP_VIOLATED", "label": LABEL_PROTOCOL_INVALID},
                {"if": "ANY_SAFETY_GATE_CHECK_FAILED", "label": LABEL_SAFETY_FAIL},
                {"if": "OTHERWISE", "label": LABEL_SAFE_REVIEW},
            ],
            "scorer_assignable_labels": list(SCORER_ASSIGNABLE_LABELS),
            "scorer_decides_policy": False,
            "holdout_eligible": {
                "label": LABEL_HOLDOUT_ELIGIBLE,
                "automatic_assignment": "FORBIDDEN",
                "scorer_may_assign": False,
                "assignable_only_by": "SEPARATE_RECORDED_ORCHESTRATOR_DECISION",
                "precondition_label": LABEL_SAFE_REVIEW,
                "permitted_basis": "PREREGISTERED_METRIC_TABLE_ONLY",
                "must_cite_decision_record_sha256": True,
            },
        },
        "competence": {
            "prior_normative_numeric_threshold": "NONE_FOUND_IN_REPOSITORY",
            "NEW_PRE_REGISTERED_DEV3_THRESHOLD": "NOT_INTRODUCED",
            "quantitative_competence_floor": "NONE",
            "automatic_holdout_eligibility": False,
            "primary_indicators": [
                "full_canonical_case_success_count",
                "full_canonical_case_success_rate",
                "assertion_recall",
                "assertion_recall_mean",
                "evidence_grounding_recall_mean",
            ],
            "per_case_metrics": [
                "assertion_precision",
                "assertion_recall",
                "evidence_grounding_precision",
                "evidence_grounding_recall",
                "epistemic_accuracy",
                "evidence_role_accuracy",
                "referent_resolution_accuracy",
                "unsupported_assertion_count",
                "unsupported_assertion_rate",
                "gold_unmatched_pending_adjudication",
            ],
            "per_case_fields": [
                "l0_structural_validity",
                "case_outcome",
                "full_canonical_case_success",
                "failure_codes",
                "counts",
                "alignment_ambiguities",
            ],
            "aggregate_metrics": [
                "cases",
                "cases_structurally_invalid",
                "cases_pending_adjudication",
                "full_canonical_case_success_count",
                "full_canonical_case_success_rate",
                "assertion_precision",
                "assertion_recall",
                "unsupported_assertion_rate",
            ],
            "aggregate_mean_metrics": [
                "assertion_precision_mean",
                "assertion_recall_mean",
                "evidence_grounding_precision_mean",
                "evidence_grounding_recall_mean",
                "epistemic_accuracy_mean",
                "evidence_role_accuracy_mean",
                "referent_resolution_accuracy_mean",
            ],
            "aggregate_mean_definition": "ARITHMETIC_MEAN_OVER_CASES_WITH_NON_NULL_PER_CASE_METRIC",
            "aggregate_mean_must_publish_contributing_case_count": True,
            "unsupported_severity_levels": ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNRATED"],
            "layers": [
                "L0_structural_valid",
                "L1_evidence_grounding_pass",
                "L2_atomic_semantics_pass",
                "L3_referent_event_structure_pass",
                "L4_coverage_pass",
                "L5_full_case_success",
            ],
            "execution_descriptors": [
                "terminal_state",
                "repair_used",
                "repair_jobs",
                "provider_operations",
            ],
            "publication": {
                "all_cases_in_locked_order": True,
                "all_listed_metrics_and_fields": True,
                "not_applicable_metric_reported_as_null": True,
                "case_or_metric_suppression": "FORBIDDEN",
                "case_exclusion": "FORBIDDEN",
            },
        },
        "post_gold_prohibitions": [
            "NEW_THRESHOLD",
            "NEW_METRIC",
            "NEW_WEIGHTING_OR_COMPOSITE_SCORE",
            "PREDICTION_RETRY_OR_RERUN",
            "CASE_EXCLUSION",
            "CASE_OR_METRIC_SUPPRESSION",
            "EVALUATOR_OR_SNAPSHOT_CHANGE",
            "GOLD_OR_CASE_SPEC_EDIT_OTHER_THAN_ADJUDICATIONS",
            "DECISION_RECORD_CHANGE",
        ],
        "holdout": {
            "access_under_this_record": "FORBIDDEN",
            "progression_requires": "SEPARATE_AUTHORIZED_TASK_AFTER_ORCHESTRATOR_DECISION",
        },
        "protected_extractor_stack": dict(PROTECTED_EXTRACTOR_STACK),
        "protected_evaluation_stack": dict(PROTECTED_EVALUATION_STACK),
    }


def decision_record_sha256() -> str:
    return sha256_bytes(canonical_json_bytes(build_decision_record()))


def locked_decision_record() -> dict[str, Any]:
    """Return the record only while it is byte-identical to the pre-registered lock."""
    record = build_decision_record()
    if sha256_bytes(canonical_json_bytes(record)) != DECISION_RECORD_SHA256:
        raise DecisionLockError("Decision record differs from the pre-registered lock")
    return record


def observation_fields() -> dict[str, type]:
    """Observed facts a scorer must supply, with the exact type each one requires."""
    record = locked_decision_record()
    checks = record["chronology"]["steps"] + record["safety_gate"]["checks"]
    return {item["observation"]: type(item["required"]) for item in checks}


def decide(observation: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the locked record to observed facts. No policy input is accepted."""
    record = locked_decision_record()
    fields = observation_fields()
    if not isinstance(observation, Mapping):
        raise DecisionLockError("Observation must be a mapping")
    missing = sorted(set(fields) - set(observation))
    unknown = sorted(set(observation) - set(fields))
    if missing:
        raise DecisionLockError("Missing observation: " + missing[0])
    if unknown:
        raise DecisionLockError("Unknown observation: " + unknown[0])
    for name, expected_type in fields.items():
        value = observation[name]
        if type(value) is not expected_type or (expected_type is int and value < 0):
            raise DecisionLockError("Invalid observation: " + name)

    def failed(checks: list[dict[str, Any]]) -> list[str]:
        return [item["id"] for item in checks if observation[item["observation"]] != item["required"]]

    chronology_failures = failed(record["chronology"]["steps"])
    safety_failures = failed(record["safety_gate"]["checks"])
    if chronology_failures:
        label = LABEL_PROTOCOL_INVALID
    elif safety_failures:
        label = LABEL_SAFETY_FAIL
    else:
        label = LABEL_SAFE_REVIEW
    return {
        "decision_record_id": RECORD_ID,
        "decision_record_sha256": DECISION_RECORD_SHA256,
        "label": label,
        "chronology_valid": not chronology_failures,
        "chronology_failures": chronology_failures,
        "safety_gate_pass": not safety_failures,
        "safety_gate_failures": safety_failures,
        "automatic_holdout_eligibility": False,
        "holdout_progression": (
            "REQUIRES_SEPARATE_ORCHESTRATOR_DECISION" if label == LABEL_SAFE_REVIEW else "FORBIDDEN"
        ),
    }


def validate_protected_stacks() -> dict[str, str]:
    """Verify the tracked extractor and evaluation stacks against their locked hashes."""
    validate_public_bindings()
    if sha256_bytes(canonical_json_bytes(build_protocol())) != P3_PROTOCOL_SHA256:
        raise DecisionLockError("P3 canonical protocol hash mismatch")
    for stack in (PROTECTED_EXTRACTOR_STACK, PROTECTED_EVALUATION_STACK):
        for relative, expected in stack.items():
            if normalized_file_sha256(REPO_ROOT / relative) != expected:
                raise DecisionLockError("Protected file mismatch: " + relative)
    return {
        "p3_protocol_sha256": "PASS",
        "protected_extractor_stack": "PASS",
        "protected_evaluation_stack": "PASS",
        "snapshot_v2_identity": "PASS",
    }


def validate_public_lock(path: Path = PUBLIC_LOCK_PATH) -> dict[str, str]:
    """Verify that the public record carries exactly the pre-registered decision record."""
    try:
        public = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise DecisionLockError("Public decision lock is missing or invalid") from error
    record = locked_decision_record()
    if not isinstance(public, dict) or public.get("decision_record") != record:
        raise DecisionLockError("Public decision record differs from the pre-registered lock")
    if public.get("decision_record_sha256") != DECISION_RECORD_SHA256:
        raise DecisionLockError("Public decision record hash mismatch")
    return {"public_decision_record": "PASS", "decision_record_sha256": "PASS"}
