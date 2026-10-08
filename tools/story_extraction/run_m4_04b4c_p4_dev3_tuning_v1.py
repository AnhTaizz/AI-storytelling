"""DEV3 execution adapter for P4 structural tuning under protocol V2 (M4-04B4C).

Composes accepted components. It changes no extraction semantics. DEV3 is tuning data for
P4, not fresh validation. Only the hash-verified DEV3 input archive is ever opened; the
gold package is rejected by hash before anything reads it. No evaluator is imported and
nothing is scored.

Input layer: the verified DEV3 layout loader supplies the input-only mechanics (archive
identity, the fixed 51-member inventory, frozen M3 ingestion and exact reproduction of the
prepared Draft V1.1 input). Each case is then rebound to P4 provenance, so nothing compiled
here carries a P3 run identity.

Execution: protocol V2 request builders and job-spec checker, the unchanged full Draft
V1.1 validator and compiler, structural diagnostic V2, the accepted durable executor,
persistent pacer and Gemini transport. One primary per case and at most one structural
repair. A hard, restart-persistent cap limits real provider operations for the whole run.

The experiment is fixed by a tracked experiment lock that must equal what this module
rebuilds from the code on disk. The run is single-shot: existing execution state is never
resumed automatically.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import fields, replace
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Callable, Mapping, Optional, Sequence

from jsonschema import Draft202012Validator
import yaml

from tools.story_extraction import m4_04b4a_p4_output_contract_v1 as contract
from tools.story_extraction import m4_04b4br_p4_protocol_v2 as protocol
from tools.story_extraction import materialize_draft_v1_1_model_schema_v1 as materializer
from tools.story_extraction import project_draft_v1_1_model_schema_to_gemini_v1 as projection
from tools.story_extraction import run_m4_04b3h_dev3_p3_live_v1_1 as dev3_layout
from tools.story_extraction.draft_compiler_v1_1 import prepare_story_extraction_draft_v1_1
from tools.story_extraction.durable_research_executor_v1 import (
    DURABLE_EXECUTOR_VERSION,
    MAX_EXECUTION_WINDOWS_PER_JOB,
    MAX_PROVIDER_ATTEMPTS_PER_JOB,
    MAX_PROVIDER_ATTEMPTS_PER_WINDOW,
    CheckpointIntegrityError,
    DurableJobSpec,
    DurableResearchExecutor,
    JobState,
    PersistentRollingOperationPacer,
)
from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError, load_runtime_config
from tools.story_extraction.run_m4_04b2_dev_predictions_v1 import GeminiDevWindowTransport, _write_bytes_atomic
from tools.story_extraction.run_m4_04b3g_dev3_p3_predictions_v1 import CaseInput
from tools.story_extraction.run_m4_04b4b_p4_structural_v1 import BudgetedPacer, compile_raw_response


TASK_ID = "M4-04B4C"
RUNNER_ID = "M4_04B4C_P4_DEV3_TUNING_ADAPTER_V1"
ADAPTER_PATH = "tools/story_extraction/run_m4_04b4c_p4_dev3_tuning_v1.py"
REPO_ROOT = protocol.REPO_ROOT
EXPECTED_BASE_COMMIT = "3ac509af4cb99a04ab4de806541bc4019f23bdca"
LIVE_AUTHORIZATION_TOKEN = "M4-04B4C"

EXPERIMENT_ID = "M4_04B4C_P4_DEV3_STRUCTURAL_TUNING_EXPERIMENT_V1"
EXPERIMENT_SCHEMA_VERSION = "M4_04B4C_EXPERIMENT_LOCK_SCHEMA_V1"
EXPERIMENT_LOCK_PATH = REPO_ROOT / "benchmarks/m4_extraction/M4_04B4C_P4_DEV3_TUNING_EXPERIMENT_LOCK.yaml"
PREDICTION_LOCK_PATH = REPO_ROOT / "benchmarks/m4_extraction/M4_04B4C_P4_DEV3_TUNING_PREDICTION_LOCK.yaml"
RESULT_RECORD_PATH = REPO_ROOT / "benchmarks/m4_extraction/M4_04B4C_P4_DEV3_TUNING_RESULT.yaml"
DEFAULT_PRIVATE_ROOT = REPO_ROOT / ".local/m4_04b4c_p4_dev3_tuning"

PROCESS_ID = "M4_04B4C_P4"
RUN_ID_PREFIX = "P4_"
PROVENANCE_FIELDS = ("process_id", "run_id")
RETAINED_PROCESS_VERSION = "v1.1"

DEV3_INPUT_ARCHIVE_NAME = "M4_04B3_DEV3_INPUT_V1.zip"
DEV3_INPUT_SHA256 = "47ae7c743065f8ff001f4db6a398df2edf1db094383b1fe2d0c3a05ab40c55c7"
DEV3_GOLD_SHA256 = "b5b2258d46608015ff60de2c660fba521029ff4716c7c1cc3b3735c55dfd34a9"
CASE_IDS = tuple(f"DEV3_{number:02d}" for number in range(1, 11))
DEV3_STATUS_FOR_P4 = "TUNING_DATA_AFTER_P3_FAILURE"
P3_PREDICTION_SET_SHA256 = "06d555f53f6c113e3db7ab7eea55501a4b442e7e8daec3047bcc7cb3b55f38fd"
P3_STRUCTURAL_VALID = 0

MAX_REAL_PROVIDER_OPERATIONS = 30
OPERATION_BUDGET_ID = "M4_04B4C_OPERATION_BUDGET_V1"
PREDICTION_SET_ID = "M4_04B4C_P4_DEV3_PREDICTION_SET_V1"
TUNING_RESULT_ID = "M4_04B4C_P4_DEV3_TUNING_RESULT_V1"
PREDICTION_MANIFEST_ID = "M4_04B4C_P4_DEV3_PREDICTION_MANIFEST_V1"
INCOMPLETE_RECORD_ID = "M4_04B4C_P4_DEV3_TUNING_INCOMPLETE_V1"
PRIVATE_DIRECTORIES = (
    "checkpoints", "input", "raw_primary", "raw_repair", "drafts", "compiled", "failures", "case_results",
    "telemetry",
)
FOREIGN_PRIVATE_ROOTS = ("m4_04b3h_dev3_predictions", "m4_04b4b_p4_synthetic_smoke", "m4_04b4br_p4_projection_smoke")
TERMINAL_STATUSES = ("STRUCTURAL_VALID", "STRUCTURAL_FAILURE", "TRANSPORT_FAILURE")
EMPTY_PRIMARY_NOT_REPAIRABLE = "EMPTY_PRIMARY_RESPONSE_REPAIR_REQUEST_NOT_CONSTRUCTIBLE_UNDER_PROTOCOL_V2"

STATUS_COMPLETE = "M4_04B4C_P4_DEV3_TUNING_COMPLETE"
STATUS_PRELIVE_LOCK_FAILED = "M4_04B4C_PRELIVE_LOCK_FAILED"
STATUS_PREFLIGHT_FAILED = "M4_04B4C_DEV3_PREFLIGHT_FAILED"
STATUS_INTERRUPTED = "M4_04B4C_INTERRUPTED_REQUIRES_CHECKPOINT_REVIEW"
STATUS_BUDGET_EXHAUSTED = "M4_04B4C_BUDGET_EXHAUSTED"
STATUS_FAIL_CLOSED = "M4_04B4C_RUN_STOPPED_FAIL_CLOSED"
STATUS_PROTOCOL_VIOLATION = "M4_04B4C_PROTOCOL_VIOLATION"
STATUS_OFFLINE_INCOMPLETE = "M4_04B4C_OFFLINE_IMPLEMENTATION_INCOMPLETE"
STATUS_PRELIVE_READY = "M4_04B4C_PRELIVE_READY_LIVE_NOT_STARTED"
NEXT_IF_STABLE = "ORCHESTRATOR REVIEW FOR FRESH DEV4 DESIGN AND SEALING"
NEXT_IF_POOR = "ORCHESTRATOR REVIEW FOR OFFLINE P4 STRUCTURAL FORENSICS"
STABLE_MINIMUM_STRUCTURAL_VALID = 8

# Files on the execution path that protocol V2 does not already bind. UTF8_LF_NORMALIZED_SHA256.
EXECUTION_PATH_FILES = (
    ADAPTER_PATH,
    "tools/story_extraction/m4_04b4br_p4_protocol_v2.py",
    "tools/story_extraction/run_m4_04b4b_p4_structural_v1.py",
    "tools/story_extraction/run_m4_04b3h_dev3_p3_live_v1_1.py",
    "tools/story_extraction/run_m4_04b3g_dev3_p3_predictions_v1.py",
    "tools/story_extraction/m4_04b3f_dev3_p3_protocol_v1.py",
    "tools/story_extraction/m4_04b3h0_dev3_decision_lock_v1.py",
    "tools/story_extraction/dev3_seal_v1.py",
    "tools/story_ingestion/light_novel_adapter_v0.py",
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
canonical_json_bytes = protocol.canonical_json_bytes
sha256_bytes = protocol.sha256_bytes


class P4Dev3Error(RuntimeError):
    """A fail-closed adapter, input, lock or integrity error with no private text."""


class PreflightFailure(P4Dev3Error):
    """A gate before provider construction failed."""


class PriorExecutionState(P4Dev3Error):
    """Execution state already exists. It is never resumed automatically."""


class BudgetExhausted(P4Dev3Error):
    """The hard operation budget stopped the run before another provider operation."""

    def __init__(self, case_id: str, phase: str) -> None:
        self.case_id = case_id
        self.phase = phase
        super().__init__("Real provider operation budget is exhausted")


def _json_normalized(value: Any) -> Any:
    return json.loads(json.dumps(value))


# ---------------------------------------------------------------------------
# DEV3 input with P4 provenance
# ---------------------------------------------------------------------------

def p4_run_id(case_id: str) -> str:
    return RUN_ID_PREFIX + case_id


def rebind_to_p4(case: CaseInput) -> CaseInput:
    """The same verified input with a P4 process and run identity. Nothing else may differ."""
    source = case.compiler_context
    if source.process_version != RETAINED_PROCESS_VERSION:
        raise P4Dev3Error("Source context has an unexpected process version")
    context = replace(source, process_id=PROCESS_ID, run_id=p4_run_id(case.case_id))
    for field in fields(context):
        if field.name not in PROVENANCE_FIELDS and getattr(context, field.name) is not getattr(source, field.name):
            raise P4Dev3Error("Rebinding changed a source input field")
    try:
        reproduced = prepare_story_extraction_draft_v1_1(context)
    except Exception as error:
        raise P4Dev3Error("Prepared Draft V1.1 input cannot be reproduced under P4 provenance") from error
    if reproduced != case.prepared_input:
        raise P4Dev3Error("Prepared Draft V1.1 input does not reproduce exactly under P4 provenance")
    if any("P3" in str(getattr(context, name)) for name in PROVENANCE_FIELDS):
        raise P4Dev3Error("P3 provenance reached a P4 compiler context")
    return CaseInput(case.case_id, case.prepared_input, context)


def load_p4_case_inputs(
    input_archive: Path,
    input_root: Path,
    *,
    expected_input_sha256: str = DEV3_INPUT_SHA256,
) -> list[CaseInput]:
    """The ten DEV3 cases from the hash-verified input archive only, with P4 provenance."""
    if (
        (dev3_layout.DEV3_INPUT_SHA256, dev3_layout.DEV3_GOLD_SHA256, tuple(dev3_layout.CASE_IDS))
        != (DEV3_INPUT_SHA256, DEV3_GOLD_SHA256, CASE_IDS)
    ):
        raise P4Dev3Error("Verified DEV3 layout loader is bound to a different dataset identity")
    if expected_input_sha256 == DEV3_GOLD_SHA256:
        raise P4Dev3Error("DEV3 gold package is forbidden")
    try:
        cases = dev3_layout.load_case_inputs(input_archive, input_root, expected_input_sha256=expected_input_sha256)
    except dev3_layout.LiveExecutionError as error:
        raise P4Dev3Error("DEV3 input failed the verified layout loader: " + str(error)) from error
    if [case.case_id for case in cases] != list(CASE_IDS):
        raise P4Dev3Error("DEV3 case identity or order mismatch")
    return [rebind_to_p4(case) for case in cases]


# ---------------------------------------------------------------------------
# Experiment lock
# ---------------------------------------------------------------------------

STOP_RESUME_POLICY = {
    "single_shot": True,
    "automatic_resume": "FORBIDDEN",
    "existing_execution_state_at_start": STATUS_INTERRUPTED,
    "process_killed_machine_sleep_or_ambiguous_in_flight_window": STATUS_INTERRUPTED,
    "integrity_or_execution_guard_failure": STATUS_FAIL_CLOSED,
    "operation_budget_exhausted": STATUS_BUDGET_EXHAUSTED,
    "on_any_stop": "PRESERVE_ALL_CHECKPOINTS_AND_RAW_SUCCESSES_AND_REPORT",
    "manual_retry": "NOT_AUTHORIZED",
    "rerun_of_a_terminal_case": "FORBIDDEN",
    "provider_calls_after_prediction_lock": "FORBIDDEN",
}
REPAIR_POLICY = {
    "maximum_per_case": protocol.MAX_STRUCTURAL_REPAIRS_PER_CASE,
    "diagnostic": contract.REPAIR_DIAGNOSTIC_ID,
    "eligible_only_after_a_successful_primary_response_with": list(protocol.REPAIR_ELIGIBLE_CATEGORIES),
    "repair_receives": ["SAME_PREPARED_INPUT", "IMMUTABLE_PRIMARY_RESPONSE", "COMPLETE_STRUCTURAL_DIAGNOSTIC_V2"],
    "repair_after_valid_primary": "FORBIDDEN",
    "repair_after_transport_terminal_primary": "FORBIDDEN",
    "second_repair": "FORBIDDEN",
    "quality_coverage_or_missing_fact_retry": "FORBIDDEN",
    "gold_or_semantic_feedback": "FORBIDDEN",
    "repair_compilation_failure": "STRUCTURAL_FAILURE",
    "empty_primary_response": EMPTY_PRIMARY_NOT_REPAIRABLE,
    "empty_primary_response_terminal_status": "STRUCTURAL_FAILURE",
}
TRANSPORT_POLICY = {
    "retry_policy": "UNCHANGED_ACCEPTED_DURABLE_RUNTIME",
    "maximum_windows_per_job": MAX_EXECUTION_WINDOWS_PER_JOB,
    "maximum_provider_attempts_per_window": MAX_PROVIDER_ATTEMPTS_PER_WINDOW,
    "maximum_provider_attempts_per_job": MAX_PROVIDER_ATTEMPTS_PER_JOB,
    "job_without_successful_response": "TRANSPORT_FAILURE",
    "transport_failure_converted_to_structural_failure": False,
    "repair_job_without_successful_response": "TRANSPORT_FAILURE",
    "model_credential_or_setting_switch": "FORBIDDEN",
}
OPERATION_BUDGET_POLICY = {
    "identity": OPERATION_BUDGET_ID,
    "maximum_real_provider_operations": MAX_REAL_PROVIDER_OPERATIONS,
    "scope": "ENTIRE_B4C_RUN",
    "origin": "NEWLY_AUTHORIZED_FOR_B4C_NOT_A_PROTOCOL_V2_VALUE",
    "mechanism": "PERSISTENT_FAIL_CLOSED_RESERVATION_CAP_AROUND_THE_ACCEPTED_PACER",
    "counted_unit": "ONE_PACING_RESERVATION_IMMEDIATELY_BEFORE_EACH_PROVIDER_CALL",
    "restart_persistent": True,
    "expected_successful_first_response_jobs_at_most": 2 * len(CASE_IDS),
    "authorizes_quality_aware_retries": False,
    "on_exhaustion": [
        "STOP_BEFORE_THE_NEXT_PROVIDER_OPERATION", "PRESERVE_CHECKPOINTS_AND_RAW_SUCCESSES",
        "REPORT_COMPLETED_AND_UNCOMPLETED_CASES_SEPARATELY", "NO_FABRICATED_TERMINAL_OUTCOME",
        "NO_BUDGET_INCREASE", "NO_RERUN",
    ],
}
PRIVATE_ARTIFACT_CONTRACT = {
    "root": ".local/m4_04b4c_p4_dev3_tuning",
    "tracked": False,
    "isolated_from": list(FOREIGN_PRIVATE_ROOTS),
    "write_once": True,
    "checkpoints": "checkpoints/jobs/{JOB_ID}.json",
    "global_pacing_state": "checkpoints/global_pacing.json",
    "operation_budget_state": "checkpoints/operation_budget.json",
    "verified_input_extraction": "input/",
    "raw_primary_responses": "raw_primary/{CASE_ID}.txt",
    "raw_repair_responses": "raw_repair/{CASE_ID}.txt",
    "parsed_drafts": "drafts/{CASE_ID}_{PHASE}.json",
    "compiled_canonical_batches": "compiled/{CASE_ID}.json",
    "structural_failure_records": "failures/{CASE_ID}.json and failures/{CASE_ID}_{PHASE}_diagnostic.json",
    "case_results": "case_results/{CASE_ID}.json",
    "transport_telemetry": "telemetry/{JOB_ID}.json",
    "prediction_manifest": PREDICTION_MANIFEST_ID + ".json",
    "experiment_result": TUNING_RESULT_ID + ".json",
    "incomplete_run_record": INCOMPLETE_RECORD_ID + ".json",
}
PREDICTION_IDENTITY_FIELDS = (
    "case_id", "protocol_sha256", "experiment_lock_sha256", "primary_request_fingerprint",
    "primary_response_sha256", "repair_used", "repair_request_fingerprint", "repair_response_sha256",
    "terminal_status", "terminal_draft_sha256", "compiled_batch_sha256", "terminal_failure_sha256",
    "durable_job_success_identities",
)
ATTEMPT_METRIC_FIELDS = (
    "requests", "provider_success", "valid_json", "provider_projection_valid", "full_draft_v1_1_schema_valid",
    "compiler_reached", "compiler_success", "structural_failure_categories",
)
PUBLIC_CASE_FIELDS = PREDICTION_IDENTITY_FIELDS + (
    "run_id", "terminal_phase", "terminal_failure_category", "primary_draft_sha256", "repair_draft_sha256",
    "repair_skipped_reason", "durable_jobs", "durable_provider_operations",
)
PUBLIC_RESULT_FIELDS = (
    "task", "status", "artifact", "experiment", "identities", "prediction_set_sha256", "public_prediction_lock",
    "structural_metrics", "comparison_with_p3", "transport_and_accounting", "integrity", "regression",
    "limitations", "claims", "recommended_next_action", "boundaries",
)
LIMITATIONS = (
    "This is a tuning experiment on DEV3, which P3 had already failed on. It is not a fresh blind validation.",
    "Structural validity means a response parsed, satisfied the full Draft V1.1 contract and compiled. "
    "It says nothing about whether the extracted content is correct or complete.",
    "DEV3 gold was not opened and nothing was scored against it. Semantic recall, semantic precision, grounding "
    "accuracy, epistemic correctness and extraction quality are not established.",
    "The comparison with P3 is descriptive. P4 differs from P3 in the self-contained prompt schema, the "
    "provider-native schema projection and structural repair diagnostic V2, so no single cause is isolated.",
    "Each request was sent once to one model at temperature 0. Run-to-run variation was not measured.",
    "Ten cases from one source family. The result does not generalize beyond them.",
    "Fresh validation of P4 needs a later DEV4 that P4 has not been tuned on.",
)
PUBLIC_LOCK_FIELDS = (
    "task", "status", "artifact", "experiment", "identities", "dev3", "extractor", "provenance", "execution",
    "operation_accounting", "pacing", "cases", "prediction_set", "predictions_locked",
    "all_cases_terminal_before_lock", "DEV3_gold_opened", "holdout_opened", "semantic_scoring_performed",
)


def recommended_next_action(structural_valid: int) -> str:
    """Fixed before the run. A recommendation for Orchestrator review, not a gate."""
    return NEXT_IF_STABLE if structural_valid >= STABLE_MINIMUM_STRUCTURAL_VALID else NEXT_IF_POOR


def execution_path_hashes() -> dict[str, str]:
    try:
        return {path: protocol.normalized_file_sha256(REPO_ROOT / path) for path in EXECUTION_PATH_FILES}
    except (OSError, UnicodeError) as error:
        raise P4Dev3Error("An execution-path file is unavailable") from error


def build_experiment_lock() -> dict[str, Any]:
    """Everything that fixes the experiment, rebuilt from the code and files on disk."""
    locked = protocol.locked_protocol()
    bound = dict(protocol.BOUND_FILES)
    return _json_normalized({
        "experiment_id": EXPERIMENT_ID,
        "experiment_schema_version": EXPERIMENT_SCHEMA_VERSION,
        "task_id": TASK_ID,
        "base_commit": EXPECTED_BASE_COMMIT,
        "classification": "TUNING_EXPERIMENT_NOT_FRESH_BLIND_VALIDATION",
        "p4": {
            "extractor_id": protocol.EXTRACTOR_ID,
            "protocol_id": protocol.PROTOCOL_ID,
            "protocol_sha256": protocol.PROTOCOL_SHA256,
            "full_model_schema_identity": materializer.MODEL_SCHEMA_IDENTITY,
            "full_model_schema_sha256": protocol.FULL_MODEL_SCHEMA_SHA256,
            "provider_projection_identity": projection.PROJECTION_IDENTITY,
            "provider_projection_sha256": protocol.PROVIDER_PROJECTION_SHA256,
            "prompt_schema_role": "FULL_MODEL_SCHEMA",
            "native_schema_role": "DETERMINISTIC_PROVIDER_PROJECTION_OF_FULL_MODEL_SCHEMA",
            "acceptance_criterion": "UNCHANGED_FULL_LOCAL_DRAFT_V1_1_VALIDATOR_AND_COMPILER_V1_1",
            "provider_projection_as_acceptance_criterion": False,
            "prompt_hashes": protocol.prompt_hashes(),
            "generation_config_sha256": protocol.generation_config_sha256(),
            "repair_diagnostic": contract.REPAIR_DIAGNOSTIC_ID,
            "canonical_draft_contract": materializer.CANONICAL_DRAFT_VERSION,
            "validator": locked["compilation"]["validator"],
            "compiler": locked["compilation"]["compiler"],
            "canonical_draft_v1_1_schema_sha256": bound["schemas/story_extraction/story_extraction_draft_v1_1.schema.json"],
            "canonical_draft_v1_schema_sha256": bound["schemas/story_extraction/story_extraction_draft_v1.schema.json"],
            "compiler_v1_1_sha256": bound["tools/story_extraction/draft_compiler_v1_1.py"],
            "compiler_v1_sha256": bound["tools/story_extraction/draft_compiler_v1.py"],
            "predicate_registry_sha256": bound["schemas/canonical_story/predicate_registry_v0.yaml"],
        },
        "generation": {
            "model": protocol.MODEL,
            "credential_slot": protocol.CREDENTIAL_SLOT,
            "temperature": protocol.TEMPERATURE,
            "max_output_tokens": protocol.MAX_OUTPUT_TOKENS,
            "response_mime_type": protocol.RESPONSE_MIME_TYPE,
            "concurrency": protocol.CONCURRENCY,
            "schema_response_mode": protocol.SCHEMA_RESPONSE_MODE,
            "model_switch": "FORBIDDEN",
            "credential_switch": "FORBIDDEN",
        },
        "runtime": {
            "runtime": protocol.RUNTIME_VERSION,
            "durable_executor": DURABLE_EXECUTOR_VERSION,
            "transport": "GeminiDevWindowTransport",
            "pacer": "PersistentRollingOperationPacer",
            "global_pacing_max_operations": protocol.GLOBAL_MAX_PROVIDER_OPERATIONS,
            "global_pacing_rolling_window_seconds": protocol.GLOBAL_ROLLING_WINDOW_SECONDS,
            "window_cooldown_seconds": protocol.WINDOW_COOLDOWN_SECONDS,
            "first_success": "IMMUTABLE_LOCK",
            "sdk": {"google-genai": importlib.metadata.version("google-genai")},
            "execution_environment": dev3_layout.ENVIRONMENT_METHOD,
        },
        "dev3": {
            "status_for_p4": DEV3_STATUS_FOR_P4,
            "input_archive": DEV3_INPUT_ARCHIVE_NAME,
            "input_sha256": DEV3_INPUT_SHA256,
            "forbidden_gold_sha256": DEV3_GOLD_SHA256,
            "case_order": list(CASE_IDS),
            "layout_loader": "tools.story_extraction.run_m4_04b3h_dev3_p3_live_v1_1.load_case_inputs",
            "gold": "FORBIDDEN",
            "holdout": "FORBIDDEN",
            "semantic_scoring": "FORBIDDEN",
            "may_later_be_presented_as_fresh_validation_for_p4": False,
        },
        "p4_provenance": {
            "process_id": PROCESS_ID,
            "process_version": RETAINED_PROCESS_VERSION,
            "process_version_rule": "RETAINED_UNCHANGED_FROM_THE_VERIFIED_INPUT_CONTEXT",
            "run_id_pattern": RUN_ID_PREFIX + "{CASE_ID}",
            "host_owned_fields_that_differ_from_the_p3_input_context": list(PROVENANCE_FIELDS),
            "every_other_context_field": "IDENTICAL_OBJECT",
            "prepared_input": "MUST_REPRODUCE_EXACTLY_UNDER_P4_IDENTITY",
            "p3_identity_in_p4_output": "FORBIDDEN",
        },
        "request_construction": {
            "primary": "tools.story_extraction.m4_04b4br_p4_protocol_v2.build_primary_spec",
            "repair": "tools.story_extraction.m4_04b4br_p4_protocol_v2.build_repair_spec",
            "checker": "tools.story_extraction.m4_04b4br_p4_protocol_v2.assert_locked_job_spec",
            "primary_job_id_pattern": "M4B4BR_P4V2_{CASE_ID}_PRIMARY",
            "repair_job_id_pattern": "M4B4BR_P4V2_{CASE_ID}_REPAIR_1",
            "p3_request_builder": "NOT_USED",
            "protocol_v1": "NOT_USED",
        },
        "repair_policy": REPAIR_POLICY,
        "transport_policy": TRANSPORT_POLICY,
        "operation_budget": OPERATION_BUDGET_POLICY,
        "stop_resume_policy": STOP_RESUME_POLICY,
        "live_authorization_token_required": True,
        "private_artifact_contract": PRIVATE_ARTIFACT_CONTRACT,
        "prediction_set": {
            "identity": PREDICTION_SET_ID,
            "per_case_identity_fields": list(PREDICTION_IDENTITY_FIELDS),
            "hash": "SHA256_OF_CANONICAL_JSON_OF_THE_ORDERED_CASE_IDENTITIES_WITH_EXPERIMENT_AND_PROTOCOL_HASHES",
            "canonical_json": "UTF8_SORTED_KEYS_TWO_SPACE_INDENT_TRAILING_NEWLINE",
        },
        "structural_metrics": {
            "primary_outcomes": list(ATTEMPT_METRIC_FIELDS),
            "repair_outcomes": ["repairs_eligible", "repairs_skipped_empty_primary_response"] + list(ATTEMPT_METRIC_FIELDS),
            "terminal_outcomes": list(TERMINAL_STATUSES) + [
                "case_completion_count", "terminal_structural_valid_rate", "terminal_structural_valid_percent",
            ],
            "runtime_metrics": [
                "durable_jobs", "successful_first_response_jobs", "structural_repair_jobs",
                "real_provider_operations", "pacing_reservations", "durable_recorded_provider_operations",
                "transport_retry_attempts", "transport_terminal_jobs", "pacing_invariant", "pacing_wait_count",
                "max_rolling_reservations_observed", "tokens_where_reported", "latency_seconds",
                "operation_budget_utilization",
            ],
            "values": "OBSERVED_ONLY",
        },
        "public_result_record": {
            "path": "benchmarks/m4_extraction/M4_04B4C_P4_DEV3_TUNING_RESULT.yaml",
            "top_level_fields": list(PUBLIC_RESULT_FIELDS),
            "limitations": list(LIMITATIONS),
            "semantic_quality_claim": False,
        },
        "public_prediction_lock": {
            "path": "benchmarks/m4_extraction/M4_04B4C_P4_DEV3_TUNING_PREDICTION_LOCK.yaml",
            "top_level_fields": list(PUBLIC_LOCK_FIELDS),
            "per_case_fields": list(PUBLIC_CASE_FIELDS),
            "content": "IDENTITIES_HASHES_COUNTS_AND_MECHANICAL_STATES_ONLY",
            "forbidden": ["SOURCE_TEXT", "QUOTES", "PREDICTIONS", "MODEL_GENERATED_FIELD_VALUES", "CREDENTIALS",
                          "GOLD_CONTENT"],
        },
        "decision_rules": {
            "permitted_terminal_statuses": list(TERMINAL_STATUSES),
            "success_requires": "ALL_TEN_CASES_TERMINAL_UNDER_THIS_LOCK",
            "success_requires_ten_structural_valid": False,
            "statuses": {
                "all_ten_cases_terminal": STATUS_COMPLETE,
                "prelive_lock_failure": STATUS_PRELIVE_LOCK_FAILED,
                "dev3_preflight_failure": STATUS_PREFLIGHT_FAILED,
                "ambiguous_interruption": STATUS_INTERRUPTED,
                "operation_budget_exhausted": STATUS_BUDGET_EXHAUSTED,
                "integrity_or_execution_guard_failure": STATUS_FAIL_CLOSED,
                "protocol_violation": STATUS_PROTOCOL_VIOLATION,
                "offline_implementation_incomplete": STATUS_OFFLINE_INCOMPLETE,
                "prelive_ready_live_not_started": STATUS_PRELIVE_READY,
            },
            "comparison_with_p3": {
                "label": "TUNING_COMPARISON_NOT_BLIND_VALIDATION",
                "p3_prediction_set_sha256": P3_PREDICTION_SET_SHA256,
                "p3_structural_valid": P3_STRUCTURAL_VALID,
                "cause_attributed_solely_to_schema_packaging": False,
                "p4_also_differs_in": ["PROVIDER_NATIVE_PROJECTION", "STRUCTURAL_REPAIR_DIAGNOSTIC_V2"],
            },
            "claims_forbidden": ["SEMANTIC_RECALL", "SEMANTIC_PRECISION", "GROUNDING_ACCURACY",
                                 "EPISTEMIC_CORRECTNESS", "EXTRACTION_QUALITY"],
            "recommended_next_action": {
                "binding": "RECOMMENDATION_FOR_ORCHESTRATOR_REVIEW_ONLY",
                "threshold_origin": "SET_BY_THE_EXECUTOR_BEFORE_THE_RUN_NOT_SPECIFIED_BY_THE_ORCHESTRATOR",
                "stable_if_structural_valid_at_least": STABLE_MINIMUM_STRUCTURAL_VALID,
                "if_stable": NEXT_IF_STABLE,
                "otherwise": NEXT_IF_POOR,
            },
        },
        "code": {
            "hash_mode": "UTF8_LF_NORMALIZED_SHA256",
            "runner_id": RUNNER_ID,
            "execution_path_files": execution_path_hashes(),
            "protocol_v2_bound_files": bound,
        },
    })


def experiment_lock_sha256(lock: Optional[Mapping[str, Any]] = None) -> str:
    return sha256_bytes(canonical_json_bytes(build_experiment_lock() if lock is None else lock))


def experiment_lock_document() -> dict[str, Any]:
    lock = build_experiment_lock()
    return {"experiment_lock_sha256": experiment_lock_sha256(lock), "lock": lock}


def write_experiment_lock(path: Path = EXPERIMENT_LOCK_PATH) -> str:
    document = experiment_lock_document()
    text = yaml.safe_dump(document, sort_keys=False, default_flow_style=False, width=120, allow_unicode=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return document["experiment_lock_sha256"]


def locked_experiment(expected_sha256: Optional[str] = None, path: Path = EXPERIMENT_LOCK_PATH) -> tuple[dict[str, Any], str]:
    """The tracked lock, only while it equals what the code on disk rebuilds."""
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise P4Dev3Error("Experiment lock is unavailable") from error
    try:
        rebuilt = build_experiment_lock()
    except (protocol.P4ProtocolV2Error, protocol.protocol_v1.P4ProtocolError, contract.OutputContractError,
            projection.ProjectionError, materializer.ModelSchemaError) as error:
        raise P4Dev3Error("Protocol V2 or a bound file changed") from error
    digest = experiment_lock_sha256(rebuilt)
    if (
        not isinstance(document, dict)
        or set(document) != {"experiment_lock_sha256", "lock"}
        or document["lock"] != rebuilt
        or document["experiment_lock_sha256"] != digest
    ):
        raise P4Dev3Error("Experiment lock differs from the code and files on disk")
    if expected_sha256 is not None and expected_sha256 != digest:
        raise P4Dev3Error("Experiment lock is not the expected lock")
    return rebuilt, digest


def executor_protocol_id(lock_sha256: str) -> str:
    """Identity stamped into every durable checkpoint of this experiment."""
    return f"{protocol.executor_protocol_id()}:{EXPERIMENT_ID}:{lock_sha256}"


# ---------------------------------------------------------------------------
# Operation budget and durable runtime
# ---------------------------------------------------------------------------

class PersistentOperationBudget:
    """A hard, restart-persistent cap on real provider operations around the accepted pacer.

    The transport reserves one pacing slot immediately before each provider call. The
    consumed count is the pacer's persisted reservation total, so it survives restarts, and
    a refused reservation is a provider call that never starts. The budget identity is
    written once beside the pacing state; a different identity fails closed.
    """

    def __init__(self, pacer: PersistentRollingOperationPacer, identity_path: Path, *, lock_sha256: str,
                 maximum: int = MAX_REAL_PROVIDER_OPERATIONS) -> None:
        if type(maximum) is not int or not 1 <= maximum <= MAX_REAL_PROVIDER_OPERATIONS:
            raise P4Dev3Error("Operation budget cannot exceed the authorized maximum")
        identity = {
            "artifact": OPERATION_BUDGET_ID,
            "experiment_lock_sha256": lock_sha256,
            "maximum_real_provider_operations": maximum,
            "pacing_checkpoint": pacer.checkpoint_path.name,
        }
        data = canonical_json_bytes(identity)
        if identity_path.exists():
            if identity_path.read_bytes() != data:
                raise CheckpointIntegrityError("Operation budget identity changed across restart")
        else:
            _write_bytes_atomic(identity_path, data)
        self._pacer = pacer
        self._budgeted = BudgetedPacer(pacer, maximum)
        self.maximum = maximum
        self.identity = identity

    def acquire(self) -> float:
        return self._budgeted.acquire()

    @property
    def refusals(self) -> int:
        return self._budgeted.refusals

    def consumed(self) -> int:
        return int(self._pacer.snapshot()["reservation_count"])

    def remaining(self) -> int:
        return self.maximum - self.consumed()

    def snapshot(self) -> dict[str, Any]:
        consumed = self.consumed()
        return {
            **self.identity,
            "consumed": consumed,
            "remaining": self.maximum - consumed,
            "refusals": self.refusals,
            "within_budget": consumed <= self.maximum,
        }


def build_durable_stack(
    checkpoint_root: Path, lock_sha256: str, *, forbidden_secrets: tuple[str, ...] = (),
    maximum_operations: int = MAX_REAL_PROVIDER_OPERATIONS,
) -> tuple[PersistentRollingOperationPacer, PersistentOperationBudget, DurableResearchExecutor]:
    """The accepted pacer and executor with the locked limits, plus the experiment budget."""
    checkpoint_root.mkdir(parents=True, exist_ok=True)
    pacer = PersistentRollingOperationPacer(
        checkpoint_root / "global_pacing.json",
        max_operations=protocol.GLOBAL_MAX_PROVIDER_OPERATIONS,
        window_seconds=protocol.GLOBAL_ROLLING_WINDOW_SECONDS,
    )
    budget = PersistentOperationBudget(
        pacer, checkpoint_root / "operation_budget.json", lock_sha256=lock_sha256, maximum=maximum_operations
    )
    executor = DurableResearchExecutor(
        checkpoint_root / "jobs",
        protocol_id=executor_protocol_id(lock_sha256),
        window_cooldown_seconds=protocol.WINDOW_COOLDOWN_SECONDS,
        forbidden_secrets=forbidden_secrets,
    )
    return pacer, budget, executor


def select_locked_credential(config: Any) -> Any:
    """Return the single credential of the locked slot. No other slot can be selected."""
    selected = [item for item in config.credentials if item.slot_id == protocol.CREDENTIAL_SLOT]
    if len(selected) != 1:
        raise P4Dev3Error("Locked credential slot is unavailable or ambiguous")
    return selected[0]


def build_guard(input_archive: Path, expected_input_sha256: str, lock_sha256: str) -> Callable[[], None]:
    """Re-verify the experiment lock, protocol V2 and the input identity before every operation."""

    def guard() -> None:
        try:
            locked_experiment(lock_sha256)
            dev3_layout.verify_archive_identity(input_archive, expected_input_sha256)
        except (P4Dev3Error, dev3_layout.LiveExecutionError, OSError, RuntimeError) as error:
            raise CheckpointIntegrityError("Experiment lock, protocol V2, bound file or input changed") from error

    return guard


# ---------------------------------------------------------------------------
# Private artifacts
# ---------------------------------------------------------------------------

def private_layout(private_root: Path) -> dict[str, Path]:
    """Create the private artifact layout. It must be ignored storage that nothing else uses."""
    root = private_root.resolve()
    repository = REPO_ROOT.resolve()
    if root == repository or (repository in root.parents and root.relative_to(repository).parts[0] != ".local"):
        raise P4Dev3Error("Private artifacts must live under ignored local storage")
    lowered = [part.lower() for part in root.parts]
    if any(name in lowered for name in FOREIGN_PRIVATE_ROOTS):
        raise P4Dev3Error("Private storage of another experiment is not reused")
    if any(marker in part for part in lowered[-2:] for marker in ("gold", "holdout")):
        raise P4Dev3Error("A gold or holdout location is not accepted")
    layout = {name: root / name for name in PRIVATE_DIRECTORIES}
    for path in layout.values():
        path.mkdir(parents=True, exist_ok=True)
    layout["root"] = root
    return layout


def _write_once(path: Path, data: bytes) -> str:
    """Write an immutable private artifact. An existing different artifact is an error."""
    if path.exists():
        if path.read_bytes() != data:
            raise P4Dev3Error("Immutable private artifact differs: " + path.name)
    else:
        _write_bytes_atomic(path, data)
    return sha256_bytes(data)


def existing_execution_state(layout: Mapping[str, Path]) -> list[str]:
    """Names of directories that already hold execution state. The input extraction is not state."""
    found = [name for name in PRIVATE_DIRECTORIES
             if name != "input" and any(path.is_file() for path in layout[name].rglob("*"))]
    found += [name for name in (TUNING_RESULT_ID, PREDICTION_MANIFEST_ID, INCOMPLETE_RECORD_ID)
              if (layout["root"] / f"{name}.json").exists()]
    return found


# ---------------------------------------------------------------------------
# Case execution
# ---------------------------------------------------------------------------

def _first_success(provider: Any, budget: PersistentOperationBudget, spec: DurableJobSpec, case_id: str, phase: str):
    """One durable job. Stops before the next provider operation when the budget is spent."""
    protocol.assert_locked_job_spec(spec)
    if budget.remaining() <= 0:
        raise BudgetExhausted(case_id, phase)
    try:
        return provider.first_success(spec)
    except CheckpointIntegrityError:
        # A refused reservation reaches here as the transport's accounting error.
        if budget.refusals:
            raise BudgetExhausted(case_id, phase) from None
        raise


def _attempt_record(phase: str, entry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "phase": phase,
        "job_id": entry["job_id"],
        "request_fingerprint": entry["request_fingerprint"],
        "provider_success": entry["raw_response"] is not None,
        "transport_terminal_reason": None,
        "raw_response_sha256": entry["raw_response_sha256"],
        "json_parse": None,
        "provider_projection_valid": None,
        "full_schema_valid": None,
        "compiler_reached": False,
        "compiler_success": None,
        "structural_failure_category": None,
        "structural_finding_count": None,
        "draft_sha256": None,
        "diagnostic_sha256": None,
        "telemetry": entry["telemetry"],
    }


def _evaluate_response(
    layout: Mapping[str, Path], case: CaseInput, phase: str, entry: Mapping[str, Any],
    projection_validator: Draft202012Validator,
) -> tuple[dict[str, Any], Any, dict[str, Any]]:
    """Persist one locked response and judge it with the unchanged full validator and compiler."""
    raw = entry["raw_response"]
    directory = layout["raw_primary"] if phase == "primary" else layout["raw_repair"]
    if _write_once(directory / f"{case.case_id}.txt", raw.encode("utf-8")) != entry["raw_response_sha256"]:
        raise P4Dev3Error("Raw response identity mismatch")
    draft, batch, validation = compile_raw_response(raw, case)
    category = validation["category"]
    parsed = category != "JSON_PARSE_FAILURE"
    record = _attempt_record(phase, entry)
    record.update({
        "json_parse": parsed,
        # Measured only. The projection never decides acceptance.
        "provider_projection_valid": projection_validator.is_valid(draft) if parsed else None,
        "full_schema_valid": (category != "DRAFT_SCHEMA_FAILURE") if parsed else None,
        "compiler_reached": category in (None, "DRAFT_COMPILER_FAILURE"),
        "compiler_success": validation["pass"] if category in (None, "DRAFT_COMPILER_FAILURE") else None,
        "structural_failure_category": category,
        "structural_finding_count": 0 if validation["diagnostic"] is None else validation["diagnostic"]["finding_count"],
    })
    if draft is not None:
        record["draft_sha256"] = _write_once(
            layout["drafts"] / f"{case.case_id}_{phase}.json", canonical_json_bytes(draft)
        )
    if validation["diagnostic"] is not None:
        record["diagnostic_sha256"] = _write_once(
            layout["failures"] / f"{case.case_id}_{phase}_diagnostic.json", canonical_json_bytes(validation["diagnostic"])
        )
    return record, batch, validation


def execute_case(
    case: CaseInput,
    provider: Any,
    budget: PersistentOperationBudget,
    layout: Mapping[str, Path],
    projection_validator: Draft202012Validator,
) -> dict[str, Any]:
    """One primary and, after a structural failure of a successful response, at most one repair."""
    if case.compiler_context.run_id != p4_run_id(case.case_id) or case.compiler_context.process_id != PROCESS_ID:
        raise P4Dev3Error("Case does not carry P4 provenance")
    if (layout["case_results"] / f"{case.case_id}.json").exists():
        raise P4Dev3Error("A terminal case is never executed again")
    mark = len(provider.journal)
    attempts: list[dict[str, Any]] = []
    batch = validation = None
    transport_phase = transport_reason = repair_skipped = None

    primary_spec = protocol.build_primary_spec(case.case_id, case.prepared_input)
    try:
        _first_success(provider, budget, primary_spec, case.case_id, "primary")
    except dev3_layout.TransportTerminalFailure as failure:
        transport_phase, transport_reason = "PRIMARY", failure.category
        attempts.append({**_attempt_record("primary", provider.journal[-1]), "transport_terminal_reason": failure.category})
    else:
        record, batch, validation = _evaluate_response(layout, case, "primary", provider.journal[-1], projection_validator)
        attempts.append(record)
        if not validation["pass"]:
            if validation["category"] not in protocol.REPAIR_ELIGIBLE_CATEGORIES:
                raise P4Dev3Error("Semantic or quality retry is forbidden")
            primary_raw = provider.journal[-1]["raw_response"]
            if primary_raw == "":
                repair_skipped = EMPTY_PRIMARY_NOT_REPAIRABLE
            else:
                repair_spec = protocol.build_repair_spec(
                    case.case_id, case.prepared_input, primary_raw, validation["diagnostic"]
                )
                try:
                    _first_success(provider, budget, repair_spec, case.case_id, "repair_1")
                except dev3_layout.TransportTerminalFailure as failure:
                    transport_phase, transport_reason = "REPAIR", failure.category
                    attempts.append({**_attempt_record("repair_1", provider.journal[-1]),
                                     "transport_terminal_reason": failure.category})
                    batch = None
                else:
                    record, batch, validation = _evaluate_response(
                        layout, case, "repair_1", provider.journal[-1], projection_validator
                    )
                    attempts.append(record)

    calls = provider.journal[mark:]
    expected_jobs = [f"M4B4BR_P4V2_{case.case_id}_PRIMARY", f"M4B4BR_P4V2_{case.case_id}_REPAIR_1"]
    if (
        not 1 <= len(calls) <= 1 + protocol.MAX_STRUCTURAL_REPAIRS_PER_CASE
        or len(calls) != len(attempts)
        or [item["job_id"] for item in calls] != expected_jobs[: len(calls)]
    ):
        raise P4Dev3Error("Case job sequence differs from the locked protocol")
    for item in calls:
        _write_once(layout["telemetry"] / f"{item['job_id']}.json", canonical_json_bytes(item["telemetry"]))

    if transport_phase is not None:
        terminal_status, category = "TRANSPORT_FAILURE", "TRANSPORT_FAILURE"
        failure_record = {"case_id": case.case_id, "terminal_status": terminal_status, "phase": transport_phase,
                          "transport_terminal_reason": transport_reason}
    elif validation["pass"]:
        terminal_status, category, failure_record = "STRUCTURAL_VALID", None, None
    else:
        terminal_status, category = "STRUCTURAL_FAILURE", validation["category"]
        failure_record = {"case_id": case.case_id, "terminal_status": terminal_status,
                          "phase": attempts[-1]["phase"].upper(), "category": category,
                          "diagnostic": validation["diagnostic"], "repair_skipped_reason": repair_skipped}
    compiled_sha256 = failure_sha256 = None
    if terminal_status == "STRUCTURAL_VALID":
        compiled_sha256 = _write_once(layout["compiled"] / f"{case.case_id}.json", canonical_json_bytes(batch))
    else:
        failure_sha256 = _write_once(layout["failures"] / f"{case.case_id}.json", canonical_json_bytes(failure_record))
    successful = [item for item in attempts if item["provider_success"]]
    repair = attempts[1] if len(attempts) > 1 else None
    result = {
        "case_id": case.case_id,
        "run_id": case.compiler_context.run_id,
        "primary": attempts[0],
        "repair_used": repair is not None,
        "repair": repair,
        "repair_skipped_reason": repair_skipped,
        "terminal_status": terminal_status,
        "terminal_phase": (transport_phase or attempts[-1]["phase"].upper()),
        "terminal_failure_category": category,
        "terminal_draft_sha256": successful[-1]["draft_sha256"] if successful and transport_phase is None else None,
        "compiled_batch_sha256": compiled_sha256,
        "terminal_failure_sha256": failure_sha256,
        "durable_jobs": len(calls),
        "durable_provider_operations": sum(int(item["telemetry"]["total_provider_operations"]) for item in calls),
    }
    _write_once(layout["case_results"] / f"{case.case_id}.json", canonical_json_bytes(result))
    return result


# ---------------------------------------------------------------------------
# Prediction set, metrics and result
# ---------------------------------------------------------------------------

def case_identity(item: Mapping[str, Any], lock_sha256: str) -> dict[str, Any]:
    repair = item["repair"]
    identity = {
        "case_id": item["case_id"],
        "protocol_sha256": protocol.PROTOCOL_SHA256,
        "experiment_lock_sha256": lock_sha256,
        "primary_request_fingerprint": item["primary"]["request_fingerprint"],
        "primary_response_sha256": item["primary"]["raw_response_sha256"],
        "repair_used": item["repair_used"],
        "repair_request_fingerprint": None if repair is None else repair["request_fingerprint"],
        "repair_response_sha256": None if repair is None else repair["raw_response_sha256"],
        "terminal_status": item["terminal_status"],
        "terminal_draft_sha256": item["terminal_draft_sha256"],
        "compiled_batch_sha256": item["compiled_batch_sha256"],
        "terminal_failure_sha256": item["terminal_failure_sha256"],
        "durable_job_success_identities": [
            {"job_id": attempt["job_id"], "response_sha256": attempt["raw_response_sha256"]}
            for attempt in (item["primary"], repair) if attempt is not None and attempt["provider_success"]
        ],
    }
    validate_case_identity(identity)
    return identity


def validate_case_identity(identity: Mapping[str, Any]) -> None:
    if tuple(identity) != PREDICTION_IDENTITY_FIELDS:
        raise P4Dev3Error("Prediction identity fields differ from the locked fields")
    for name, value in identity.items():
        if name.endswith(("sha256", "fingerprint")) and value is not None and not _HEX64.fullmatch(str(value)):
            raise P4Dev3Error("Prediction identity is not a SHA-256 value: " + name)
    successes = identity["durable_job_success_identities"]
    if (
        type(identity["repair_used"]) is not bool
        or identity["terminal_status"] not in TERMINAL_STATUSES
        or identity["case_id"] not in CASE_IDS
        or not isinstance(successes, list)
        or len(successes) > 1 + protocol.MAX_STRUCTURAL_REPAIRS_PER_CASE
        or any(set(entry) != {"job_id", "response_sha256"} or not _HEX64.fullmatch(str(entry["response_sha256"]))
               for entry in successes)
        or (identity["terminal_status"] == "STRUCTURAL_VALID") != (identity["compiled_batch_sha256"] is not None)
        or (identity["compiled_batch_sha256"] is None) == (identity["terminal_failure_sha256"] is None)
        or (not identity["repair_used"] and identity["repair_request_fingerprint"] is not None)
        or (identity["repair_used"] and identity["repair_request_fingerprint"] is None)
    ):
        raise P4Dev3Error("Prediction identity is invalid")


def prediction_set_sha256(
    identities: Sequence[Mapping[str, Any]], lock_sha256: str, input_sha256: str = DEV3_INPUT_SHA256
) -> str:
    """Deterministic identity of the terminal prediction set. Every bound identity changes it."""
    if [item["case_id"] for item in identities] != list(CASE_IDS):
        raise P4Dev3Error("Prediction set must contain every case once in the locked order")
    for identity in identities:
        validate_case_identity(identity)
        if (identity["experiment_lock_sha256"], identity["protocol_sha256"]) != (lock_sha256, protocol.PROTOCOL_SHA256):
            raise P4Dev3Error("Prediction identity is bound to another lock or protocol")
    return sha256_bytes(canonical_json_bytes({
        "artifact": PREDICTION_SET_ID,
        "experiment_lock_sha256": lock_sha256,
        "protocol_sha256": protocol.PROTOCOL_SHA256,
        "dev3_input_sha256": input_sha256,
        "case_order": list(CASE_IDS),
        "cases": [dict(identity) for identity in identities],
    }))


def _attempt_metrics(attempts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    categories = Counter(item["structural_failure_category"] for item in attempts if item["structural_failure_category"])
    return {
        "requests": len(attempts),
        "provider_success": sum(item["provider_success"] for item in attempts),
        "valid_json": sum(item["json_parse"] is True for item in attempts),
        "provider_projection_valid": sum(item["provider_projection_valid"] is True for item in attempts),
        "full_draft_v1_1_schema_valid": sum(item["full_schema_valid"] is True for item in attempts),
        "compiler_reached": sum(item["compiler_reached"] is True for item in attempts),
        "compiler_success": sum(item["compiler_success"] is True for item in attempts),
        "structural_failure_categories": dict(sorted(categories.items())),
    }


def structural_metrics(results: Sequence[Mapping[str, Any]], operations: Mapping[str, Any]) -> dict[str, Any]:
    """Observed counts only. Structural conformance, never extraction quality."""
    primary = [item["primary"] for item in results]
    repair = [item["repair"] for item in results if item["repair"] is not None]
    jobs = primary + repair
    terminal = {status: sum(item["terminal_status"] == status for item in results) for status in TERMINAL_STATUSES}
    usage: Counter = Counter()
    for job in jobs:
        for key, value in (job["telemetry"].get("usage") or {}).items():
            if type(value) is int:
                usage[key] += value
    latency = [float(job["telemetry"]["provider_latency_seconds"]) for job in jobs
               if isinstance(job["telemetry"].get("provider_latency_seconds"), (int, float))]
    recorded = sum(int(job["telemetry"]["total_provider_operations"]) for job in jobs)
    reservations = int(operations["pacing_reservations"])
    return {
        "primary_outcomes": _attempt_metrics(primary),
        "repair_outcomes": {
            "repairs_eligible": sum(
                item["provider_success"] and item["structural_failure_category"] in protocol.REPAIR_ELIGIBLE_CATEGORIES
                for item in primary
            ),
            "repairs_skipped_empty_primary_response": sum(item["repair_skipped_reason"] is not None for item in results),
            **_attempt_metrics(repair),
        },
        "terminal_outcomes": {
            **terminal,
            "case_completion_count": len(results),
            "terminal_structural_valid_rate": f"{terminal['STRUCTURAL_VALID']}/{len(results)}",
            "terminal_structural_valid_percent": round(100.0 * terminal["STRUCTURAL_VALID"] / len(results), 1)
            if results else None,
        },
        "runtime_metrics": {
            "durable_jobs": len(jobs),
            "successful_first_response_jobs": sum(job["provider_success"] for job in jobs),
            "structural_repair_jobs": len(repair),
            "real_provider_operations": int(operations["real_provider_operations"]),
            "pacing_reservations": reservations,
            "durable_recorded_provider_operations": recorded,
            "transport_retry_attempts": max(0, reservations - len(jobs)),
            "transport_terminal_jobs": sum(not job["provider_success"] for job in jobs),
            "pacing_invariant": operations["pacing_invariant"],
            "pacing_wait_count": operations["wait_count"],
            "max_rolling_reservations_observed": operations["max_rolling_reservations_observed"],
            "tokens_where_reported": dict(sorted(usage.items())),
            "latency_seconds": {
                "jobs_measured": len(latency),
                "total": round(sum(latency), 3),
                "maximum": round(max(latency), 3) if latency else None,
            },
            "operation_budget_utilization": f"{reservations}/{operations['operation_budget']}",
        },
    }


def operation_accounting(pacer: PersistentRollingOperationPacer, budget: PersistentOperationBudget, real: bool) -> dict[str, Any]:
    pacing = pacer.snapshot()
    reservations = int(pacing["reservation_count"])
    return {
        "operation_budget": budget.maximum,
        "pacing_reservations": reservations,
        "real_provider_operations": reservations if real else 0,
        "budget_refusals": budget.refusals,
        "within_budget": reservations <= budget.maximum,
        "max_provider_operations_per_window": pacing["max_provider_operations"],
        "rolling_window_seconds": pacing["rolling_window_seconds"],
        "wait_count": pacing["wait_count"],
        "max_rolling_reservations_observed": pacing["max_rolling_reservations_observed"],
        "restart_persistent": pacing["restart_persistent"],
        "pacing_invariant": pacing["invariant"],
    }


def build_tuning_result(
    results: Sequence[Mapping[str, Any]],
    *,
    lock_sha256: str,
    input_sha256: str,
    operations: Mapping[str, Any],
    environment: Optional[Mapping[str, Any]],
    transport: str,
) -> dict[str, Any]:
    if [item["case_id"] for item in results] != list(CASE_IDS):
        raise P4Dev3Error("A tuning result needs every case terminal in the locked order")
    identities = [case_identity(item, lock_sha256) for item in results]
    metrics = structural_metrics(results, operations)
    valid = metrics["terminal_outcomes"]["STRUCTURAL_VALID"]
    return {
        "artifact": TUNING_RESULT_ID,
        "status": STATUS_COMPLETE,
        "task_id": TASK_ID,
        "runner_id": RUNNER_ID,
        "experiment_id": EXPERIMENT_ID,
        "experiment_lock_sha256": lock_sha256,
        "protocol_id": protocol.PROTOCOL_ID,
        "protocol_sha256": protocol.PROTOCOL_SHA256,
        "full_model_schema_sha256": protocol.FULL_MODEL_SCHEMA_SHA256,
        "provider_projection_sha256": protocol.PROVIDER_PROJECTION_SHA256,
        "adapter_sha256": protocol.normalized_file_sha256(REPO_ROOT / ADAPTER_PATH),
        "source_commit": None if environment is None else environment["source_commit"],
        "execution_environment": None if environment is None else environment["method"],
        "transport": transport,
        "dev3_input_sha256": input_sha256,
        "dev3_status_for_p4": DEV3_STATUS_FOR_P4,
        "extractor_id": protocol.EXTRACTOR_ID,
        "model": protocol.MODEL,
        "credential_slot": protocol.CREDENTIAL_SLOT,
        "process_id": PROCESS_ID,
        "process_version": RETAINED_PROCESS_VERSION,
        "case_order": list(CASE_IDS),
        "terminal_case_count": len(results),
        "metrics": metrics,
        "operations": dict(operations),
        "prediction_set_sha256": prediction_set_sha256(identities, lock_sha256, input_sha256),
        "prediction_identities": identities,
        "predictions": [dict(item) for item in results],
        "comparison_with_p3": {
            "label": "TUNING_COMPARISON_NOT_BLIND_VALIDATION",
            "p3_structural_valid": f"{P3_STRUCTURAL_VALID}/{len(CASE_IDS)}",
            "p4_structural_valid": f"{valid}/{len(CASE_IDS)}",
        },
        "recommended_next_action": recommended_next_action(valid),
        "dev3_gold_opened": False,
        "holdout_opened": False,
        "semantic_scoring_performed": False,
    }


# ---------------------------------------------------------------------------
# Public prediction lock
# ---------------------------------------------------------------------------

def build_public_prediction_lock(result: Mapping[str, Any]) -> dict[str, Any]:
    """Metadata-only public summary: identities, hashes, counts and mechanical states."""
    lock_sha256 = result["experiment_lock_sha256"]
    identities = [case_identity(item, lock_sha256) for item in result["predictions"]]
    if (
        result.get("artifact") != TUNING_RESULT_ID
        or identities != result.get("prediction_identities")
        or prediction_set_sha256(identities, lock_sha256, result["dev3_input_sha256"])
        != result.get("prediction_set_sha256")
        or result.get("terminal_case_count") != len(CASE_IDS)
        or result.get("dev3_gold_opened") is not False
        or result.get("holdout_opened") is not False
        or result.get("semantic_scoring_performed") is not False
    ):
        raise P4Dev3Error("Tuning result is not a complete terminal run")
    cases = []
    for item, identity in zip(result["predictions"], identities):
        cases.append({
            **identity,
            "run_id": item["run_id"],
            "terminal_phase": item["terminal_phase"],
            "terminal_failure_category": item["terminal_failure_category"],
            "primary_draft_sha256": item["primary"]["draft_sha256"],
            "repair_draft_sha256": None if item["repair"] is None else item["repair"]["draft_sha256"],
            "repair_skipped_reason": item["repair_skipped_reason"],
            "durable_jobs": item["durable_jobs"],
            "durable_provider_operations": item["durable_provider_operations"],
        })
    metrics, operations = result["metrics"], result["operations"]
    lock = {
        "task": TASK_ID,
        "status": STATUS_COMPLETE,
        "artifact": "M4_04B4C_P4_DEV3_TUNING_PREDICTION_LOCK_V1",
        "experiment": {
            "identity": EXPERIMENT_ID,
            "experiment_lock_sha256": lock_sha256,
            "classification": "TUNING_EXPERIMENT_NOT_FRESH_BLIND_VALIDATION",
            "prelive_commit": result["source_commit"],
            "runner_id": result["runner_id"],
            "adapter_sha256": result["adapter_sha256"],
        },
        "identities": {
            "protocol_id": result["protocol_id"],
            "protocol_sha256": result["protocol_sha256"],
            "full_model_schema_sha256": result["full_model_schema_sha256"],
            "provider_projection_sha256": result["provider_projection_sha256"],
        },
        "dev3": {
            "input_sha256": result["dev3_input_sha256"],
            "status_for_p4": result["dev3_status_for_p4"],
            "case_order": list(result["case_order"]),
        },
        "extractor": {
            "identity": result["extractor_id"],
            "model": result["model"],
            "credential_slot": result["credential_slot"],
        },
        "provenance": {
            "process_id": result["process_id"],
            "process_version": result["process_version"],
            "run_id_pattern": RUN_ID_PREFIX + "CASE_ID",
        },
        "execution": {
            "terminal_case_count": result["terminal_case_count"],
            "structural_valid_count": metrics["terminal_outcomes"]["STRUCTURAL_VALID"],
            "structural_failure_count": metrics["terminal_outcomes"]["STRUCTURAL_FAILURE"],
            "transport_failure_count": metrics["terminal_outcomes"]["TRANSPORT_FAILURE"],
            "repairs_used": metrics["repair_outcomes"]["requests"],
            "interpretation": "STRUCTURAL_CONFORMANCE_ONLY_NOT_EXTRACTION_QUALITY",
        },
        "operation_accounting": {
            "durable_jobs": metrics["runtime_metrics"]["durable_jobs"],
            "successful_first_response_jobs": metrics["runtime_metrics"]["successful_first_response_jobs"],
            "structural_repair_jobs": metrics["runtime_metrics"]["structural_repair_jobs"],
            "real_provider_operations": operations["real_provider_operations"],
            "pacing_reservations": operations["pacing_reservations"],
            "durable_recorded_provider_operations": metrics["runtime_metrics"]["durable_recorded_provider_operations"],
            "transport_retry_attempts": metrics["runtime_metrics"]["transport_retry_attempts"],
            "operation_budget": operations["operation_budget"],
            "budget_refusals": operations["budget_refusals"],
            "within_budget": operations["within_budget"],
        },
        "pacing": {
            "max_provider_operations_per_window": operations["max_provider_operations_per_window"],
            "rolling_window_seconds": operations["rolling_window_seconds"],
            "wait_count": operations["wait_count"],
            "max_rolling_reservations_observed": operations["max_rolling_reservations_observed"],
            "restart_persistent": operations["restart_persistent"],
            "invariant": operations["pacing_invariant"],
        },
        "cases": cases,
        "prediction_set": {
            "identity": PREDICTION_SET_ID,
            "prediction_set_sha256": result["prediction_set_sha256"],
        },
        "predictions_locked": True,
        "all_cases_terminal_before_lock": True,
        "DEV3_gold_opened": False,
        "holdout_opened": False,
        "semantic_scoring_performed": False,
    }
    validate_public_prediction_lock(lock, input_sha256=result["dev3_input_sha256"])
    return lock


def validate_public_prediction_lock(lock: Any, *, input_sha256: str = DEV3_INPUT_SHA256) -> str:
    """Schema, allowlist and safety check of a public prediction lock. Returns its set hash."""
    if not isinstance(lock, Mapping) or tuple(lock) != PUBLIC_LOCK_FIELDS:
        raise P4Dev3Error("Public prediction lock fields differ from the allowlist")
    try:
        dev3_layout._assert_public_safe(lock)
    except dev3_layout.LiveExecutionError as error:
        raise P4Dev3Error("Public prediction lock has a value that is not public-safe") from error
    cases = lock["cases"]
    if (
        not isinstance(cases, list)
        or any(not isinstance(case, Mapping) or tuple(case) != PUBLIC_CASE_FIELDS for case in cases)
        or lock["dev3"]["case_order"] != list(CASE_IDS)
        or lock["dev3"]["input_sha256"] != input_sha256
        or lock["DEV3_gold_opened"] is not False
        or lock["holdout_opened"] is not False
        or lock["semantic_scoring_performed"] is not False
        or lock["predictions_locked"] is not True
        or lock["status"] != STATUS_COMPLETE
        or lock["identities"]["protocol_sha256"] != protocol.PROTOCOL_SHA256
    ):
        raise P4Dev3Error("Public prediction lock is not a complete, sealed-gold terminal lock")
    lock_sha256 = lock["experiment"]["experiment_lock_sha256"]
    identities = [{name: case[name] for name in PREDICTION_IDENTITY_FIELDS} for case in cases]
    digest = prediction_set_sha256(identities, lock_sha256, input_sha256)
    counts = Counter(case["terminal_status"] for case in cases)
    execution, accounting = lock["execution"], lock["operation_accounting"]
    if (
        digest != lock["prediction_set"]["prediction_set_sha256"]
        or [case["run_id"] for case in cases] != [p4_run_id(case_id) for case_id in CASE_IDS]
        or execution["terminal_case_count"] != len(CASE_IDS)
        or (execution["structural_valid_count"], execution["structural_failure_count"],
            execution["transport_failure_count"]) != tuple(counts[status] for status in TERMINAL_STATUSES)
        or execution["repairs_used"] != sum(case["repair_used"] for case in cases)
        or accounting["operation_budget"] != MAX_REAL_PROVIDER_OPERATIONS
        or not 0 <= accounting["pacing_reservations"] <= MAX_REAL_PROVIDER_OPERATIONS
        or accounting["within_budget"] is not True
        or lock["pacing"]["invariant"] != "PASS"
    ):
        raise P4Dev3Error("Public prediction lock is internally inconsistent")
    return digest


def write_public_prediction_lock(lock: Mapping[str, Any], path: Path = PREDICTION_LOCK_PATH) -> str:
    validate_public_prediction_lock(lock, input_sha256=lock["dev3"]["input_sha256"])
    data = yaml.safe_dump(dict(lock), sort_keys=False, default_flow_style=False, width=120).encode("utf-8")
    _write_bytes_atomic(path, data)
    return sha256_bytes(data)


def build_public_result_record(
    result: Mapping[str, Any],
    verification: Mapping[str, Any],
    regression: Mapping[str, Any],
    prediction_lock_file_sha256: str,
) -> dict[str, Any]:
    """The public experiment result: counts, hashes, fixed labels and fixed limitation text only."""
    if (
        verification.get("status") != "POST_RUN_INTEGRITY_PASS"
        or not all(value is True for value in verification["checks"].values())
        or verification["prediction_set_sha256"] != result["prediction_set_sha256"]
        or not _HEX64.fullmatch(str(prediction_lock_file_sha256))
    ):
        raise P4Dev3Error("A public result needs a passed post-run integrity check")
    suites = regression.get("full_offline_suites")
    focused = regression.get("focused_tests")
    if (
        set(regression) != {"focused_tests", "full_offline_suites"}
        or not isinstance(suites, Mapping) or not isinstance(focused, Mapping)
        or set(focused) != {"count", "result"} or type(focused["count"]) is not int or focused["result"] != "PASS"
        or set(suites) != set(dev3_layout.REQUIRED_SUITES) | {"total", "result"} or suites["result"] != "PASS"
        or any(type(suites[name]) is not int for name in dev3_layout.REQUIRED_SUITES)
        or suites["total"] != sum(suites[name] for name in dev3_layout.REQUIRED_SUITES)
    ):
        raise P4Dev3Error("Regression summary is not a complete passing summary")
    metrics, operations = result["metrics"], result["operations"]
    valid = metrics["terminal_outcomes"]["STRUCTURAL_VALID"]
    record = {
        "task": TASK_ID,
        "status": STATUS_COMPLETE,
        "artifact": "M4_04B4C_P4_DEV3_TUNING_PUBLIC_RESULT_V1",
        "experiment": {
            "identity": EXPERIMENT_ID,
            "experiment_lock_sha256": result["experiment_lock_sha256"],
            "classification": "TUNING_EXPERIMENT_NOT_FRESH_BLIND_VALIDATION",
            "prelive_commit": result["source_commit"],
            "base_commit": EXPECTED_BASE_COMMIT,
            "runner_id": result["runner_id"],
            "adapter_sha256": result["adapter_sha256"],
            "execution_environment": result["execution_environment"],
            "transport": result["transport"],
        },
        "identities": {
            "extractor_id": result["extractor_id"],
            "protocol_id": result["protocol_id"],
            "protocol_sha256": result["protocol_sha256"],
            "full_model_schema_sha256": result["full_model_schema_sha256"],
            "provider_projection_sha256": result["provider_projection_sha256"],
            "dev3_input_sha256": result["dev3_input_sha256"],
            "dev3_status_for_p4": result["dev3_status_for_p4"],
            "model": result["model"],
            "credential_slot": result["credential_slot"],
            "process_id": result["process_id"],
            "process_version": result["process_version"],
        },
        "prediction_set_sha256": result["prediction_set_sha256"],
        "public_prediction_lock": {
            "path": PREDICTION_LOCK_PATH.relative_to(REPO_ROOT).as_posix(),
            "file_sha256": prediction_lock_file_sha256,
        },
        "structural_metrics": _json_normalized(metrics),
        "comparison_with_p3": {
            "label": "TUNING_COMPARISON_NOT_BLIND_VALIDATION",
            "p3_prediction_set_sha256": P3_PREDICTION_SET_SHA256,
            "p3_structural_valid": f"{P3_STRUCTURAL_VALID}/{len(CASE_IDS)}",
            "p4_structural_valid": f"{valid}/{len(CASE_IDS)}",
            "cause_attributed_solely_to_schema_packaging": False,
            "p4_also_differs_in": ["PROVIDER_NATIVE_PROJECTION", "STRUCTURAL_REPAIR_DIAGNOSTIC_V2"],
        },
        "transport_and_accounting": _json_normalized(operations),
        "integrity": {
            "status": verification["status"],
            "checks": dict(verification["checks"]),
            "provider_operations_after_the_run": 0,
        },
        "regression": _json_normalized(regression),
        "limitations": list(LIMITATIONS),
        "claims": {
            "semantic_quality_claim": False,
            "not_established": ["SEMANTIC_RECALL", "SEMANTIC_PRECISION", "GROUNDING_ACCURACY",
                                "EPISTEMIC_CORRECTNESS", "EXTRACTION_QUALITY"],
        },
        "recommended_next_action": {
            "action": recommended_next_action(valid),
            "binding": "RECOMMENDATION_FOR_ORCHESTRATOR_REVIEW_ONLY",
            "rule": f"STRUCTURAL_VALID_AT_LEAST_{STABLE_MINIMUM_STRUCTURAL_VALID}_OF_{len(CASE_IDS)}",
            "rule_fixed_before_the_run": True,
        },
        "boundaries": {
            "DEV3_gold_opened": False,
            "holdout_opened": False,
            "semantic_scoring_performed": False,
            "DEV4_created": False,
            "P3_predictions_modified": False,
            "provider_calls_after_prediction_lock": 0,
        },
    }
    if tuple(record) != PUBLIC_RESULT_FIELDS:
        raise P4Dev3Error("Public result fields differ from the locked fields")
    return record


def write_public_result_record(record: Mapping[str, Any], path: Path = RESULT_RECORD_PATH) -> str:
    if tuple(record) != PUBLIC_RESULT_FIELDS:
        raise P4Dev3Error("Public result fields differ from the locked fields")
    data = yaml.safe_dump(dict(record), sort_keys=False, default_flow_style=False, width=120).encode("utf-8")
    _write_bytes_atomic(path, data)
    return sha256_bytes(data)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def _tracked(paths: Sequence[str]) -> bool:
    try:
        subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files", "--error-unmatch", *paths],
                       capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


def preflight(
    *,
    input_archive: Path,
    private_root: Path = DEFAULT_PRIVATE_ROOT,
    expected_input_sha256: str = DEV3_INPUT_SHA256,
    expected_lock_sha256: Optional[str] = None,
    check_environment: bool = True,
) -> dict[str, Any]:
    """Every gate before provider construction, in order. No provider, credential or checkpoint."""
    try:
        _, lock_sha256 = locked_experiment(expected_lock_sha256)
        environment = None
        if check_environment:
            environment = dev3_layout.verify_execution_environment()
            lock_path = EXPERIMENT_LOCK_PATH.relative_to(REPO_ROOT).as_posix()
            if not _tracked([ADAPTER_PATH, lock_path]):
                raise PreflightFailure("Adapter and experiment lock must be committed before DEV3 input is opened")
        dev3_layout.verify_archive_identity(input_archive, expected_input_sha256)
        layout = private_layout(private_root)
        cases = load_p4_case_inputs(input_archive, layout["input"], expected_input_sha256=expected_input_sha256)
        for case in cases:
            protocol.assert_locked_job_spec(protocol.build_primary_spec(case.case_id, case.prepared_input))
        guard = build_guard(input_archive, expected_input_sha256, lock_sha256)
        guard()
    except PreflightFailure:
        raise
    except (P4Dev3Error, dev3_layout.LiveExecutionError, protocol.P4ProtocolV2Error, CheckpointIntegrityError) as error:
        raise PreflightFailure("Preflight failed: " + str(error)) from error
    return {"environment": environment, "layout": layout, "cases": cases, "guard": guard, "lock_sha256": lock_sha256}


def preflight_report(checked: Mapping[str, Any]) -> dict[str, Any]:
    cases = checked["cases"]
    return {
        "status": "PREFLIGHT_PASS",
        "experiment_lock_sha256": checked["lock_sha256"],
        "protocol_sha256": protocol.PROTOCOL_SHA256,
        "environment": None if checked["environment"] is None else checked["environment"]["method"],
        "source_commit": None if checked["environment"] is None else checked["environment"]["source_commit"],
        "dev3_input_sha256_verified": True,
        "cases": len(cases),
        "case_order_exact": [case.case_id for case in cases] == list(CASE_IDS),
        "m3_ingestion_and_report_binding": len(cases),
        "p4_compiler_contexts": sum(case.compiler_context.process_id == PROCESS_ID for case in cases),
        "p4_run_identities": sum(case.compiler_context.run_id == p4_run_id(case.case_id) for case in cases),
        "prepared_inputs_reproduced": len(cases),
        "p3_provenance_in_p4_contexts": sum(
            "P3" in case.compiler_context.run_id or "P3" in case.compiler_context.process_id for case in cases
        ),
        "primary_requests_pass_protocol_v2_checker": len(cases),
        "existing_execution_state": existing_execution_state(checked["layout"]),
        "provider_operations": 0,
        "credential_loaded": False,
    }


def run(
    *,
    input_archive: Path,
    private_root: Path = DEFAULT_PRIVATE_ROOT,
    expected_input_sha256: str = DEV3_INPUT_SHA256,
    expected_lock_sha256: Optional[str] = None,
    transport_factory: Optional[Callable[[PersistentOperationBudget, Callable[[], None]], Any]] = None,
    maximum_operations: int = MAX_REAL_PROVIDER_OPERATIONS,
) -> dict[str, Any]:
    """The tuning run. Without an injected transport this is the real, single-shot execution."""
    real = transport_factory is None
    if real != (expected_input_sha256 == DEV3_INPUT_SHA256):
        raise P4Dev3Error("Only the accepted transport may run the DEV3 input, and it may run nothing else")
    if real and expected_lock_sha256 is None:
        raise P4Dev3Error("A live run must name the committed experiment lock it executes")
    if real and private_root.resolve() != DEFAULT_PRIVATE_ROOT.resolve():
        raise P4Dev3Error("A live run uses the one private root of this experiment")
    checked = preflight(
        input_archive=input_archive, private_root=private_root, expected_input_sha256=expected_input_sha256,
        expected_lock_sha256=expected_lock_sha256, check_environment=real,
    )
    layout, cases, guard, lock_sha256 = checked["layout"], checked["cases"], checked["guard"], checked["lock_sha256"]
    if existing_execution_state(layout):
        raise PriorExecutionState("Execution state already exists and is not resumed")
    secrets: tuple[str, ...] = ()
    credential = None
    if real:
        try:
            config = load_runtime_config()
        except GeminiConfigError as error:
            raise P4Dev3Error("Runtime credential configuration is invalid") from error
        credential = select_locked_credential(config)
        secrets = tuple(item._api_key for item in config.credentials)
    pacer, budget, executor = build_durable_stack(
        layout["checkpoints"], lock_sha256, forbidden_secrets=secrets, maximum_operations=maximum_operations
    )
    if budget.consumed() != 0:
        raise PriorExecutionState("The operation budget is already in use")
    transport = GeminiDevWindowTransport(credential, budget, guard) if real else transport_factory(budget, guard)
    provider = dev3_layout.DurableFirstSuccessProvider(executor, transport, guard, counts_real_provider_operations=real)
    projection_validator = Draft202012Validator(protocol.native_response_schema())
    label = "ACCEPTED_GEMINI_DEV_WINDOW_TRANSPORT" if real else "INJECTED_MOCK"

    results: list[dict[str, Any]] = []
    try:
        for case in cases:
            guard()
            item = execute_case(case, provider, budget, layout, projection_validator)
            results.append(item)
            print(json.dumps({"case_id": item["case_id"], "repair_used": item["repair_used"],
                              "terminal_status": item["terminal_status"]}, sort_keys=True), flush=True)
    except BudgetExhausted as stop:
        done = [item["case_id"] for item in results]
        record = {
            "artifact": INCOMPLETE_RECORD_ID,
            "status": STATUS_BUDGET_EXHAUSTED,
            "experiment_lock_sha256": lock_sha256,
            "stopped_at_case": stop.case_id,
            "stopped_at_phase": stop.phase,
            "completed_cases": done,
            "uncompleted_cases": [case_id for case_id in CASE_IDS if case_id not in done],
            "terminal_statuses_of_completed_cases": {item["case_id"]: item["terminal_status"] for item in results},
            "operations": operation_accounting(pacer, budget, real),
            "prediction_lock_created": False,
            "terminal_outcomes_fabricated": False,
        }
        _write_bytes_atomic(layout["root"] / f"{INCOMPLETE_RECORD_ID}.json", canonical_json_bytes(record))
        return record
    guard()
    result = build_tuning_result(
        results, lock_sha256=lock_sha256, input_sha256=expected_input_sha256,
        operations=operation_accounting(pacer, budget, real), environment=checked["environment"], transport=label,
    )
    if not result["operations"]["within_budget"] or result["operations"]["pacing_invariant"] != "PASS":
        raise P4Dev3Error("Operation budget or pacing invariant violated")
    _write_bytes_atomic(layout["root"] / f"{TUNING_RESULT_ID}.json", canonical_json_bytes(result))
    _write_bytes_atomic(layout["root"] / f"{PREDICTION_MANIFEST_ID}.json", canonical_json_bytes({
        "artifact": PREDICTION_MANIFEST_ID,
        "experiment_lock_sha256": lock_sha256,
        "protocol_sha256": protocol.PROTOCOL_SHA256,
        "dev3_input_sha256": expected_input_sha256,
        "case_order": list(CASE_IDS),
        "entries": result["prediction_identities"],
        "prediction_set_sha256": result["prediction_set_sha256"],
        "predictions_locked": True,
    }))
    return result


def verify_run(
    *,
    input_archive: Path,
    private_root: Path = DEFAULT_PRIVATE_ROOT,
    expected_input_sha256: str = DEV3_INPUT_SHA256,
    expected_lock_sha256: Optional[str] = None,
) -> dict[str, Any]:
    """Offline integrity check of a finished run. It makes no provider call and changes nothing."""
    try:
        return _verify_run(input_archive, private_root, expected_input_sha256, expected_lock_sha256)
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, CheckpointIntegrityError,
            protocol.P4ProtocolV2Error) as error:
        raise P4Dev3Error("Post-run integrity check failed: an artifact is missing, unreadable or inconsistent") from error


def _verify_run(
    input_archive: Path, private_root: Path, expected_input_sha256: str, expected_lock_sha256: Optional[str]
) -> dict[str, Any]:
    _, lock_sha256 = locked_experiment(expected_lock_sha256)
    layout = private_layout(private_root)
    try:
        result = json.loads((layout["root"] / f"{TUNING_RESULT_ID}.json").read_text(encoding="utf-8"))
        manifest = json.loads((layout["root"] / f"{PREDICTION_MANIFEST_ID}.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise P4Dev3Error("A complete private tuning result is unavailable") from error
    cases = load_p4_case_inputs(input_archive, layout["input"], expected_input_sha256=expected_input_sha256)
    pacer, budget, executor = build_durable_stack(layout["checkpoints"], lock_sha256)
    projection_validator = Draft202012Validator(protocol.native_response_schema())
    predictions = result["predictions"]
    checks: dict[str, bool] = {
        "result_bound_to_this_lock_and_protocol": (result["experiment_lock_sha256"], result["protocol_sha256"])
        == (lock_sha256, protocol.PROTOCOL_SHA256),
        "adapter_unchanged_since_the_run": result["adapter_sha256"] == protocol.normalized_file_sha256(REPO_ROOT / ADAPTER_PATH),
        "all_ten_cases_terminal_exactly_once": [item["case_id"] for item in predictions] == list(CASE_IDS)
        and sorted(path.name for path in layout["case_results"].iterdir()) == sorted(f"{c}.json" for c in CASE_IDS),
    }
    expected_jobs: list[str] = []
    request_ok = raw_ok = draft_ok = terminal_ok = lock_ok = identity_ok = case_file_ok = True
    for case, item in zip(cases, predictions):
        stored = json.loads((layout["case_results"] / f"{case.case_id}.json").read_text(encoding="utf-8"))
        case_file_ok &= stored == item
        primary_spec = protocol.build_primary_spec(case.case_id, case.prepared_input)
        specs = {"primary": primary_spec}
        attempts = [item["primary"]] + ([item["repair"]] if item["repair"] is not None else [])
        batch = validation = None
        for attempt in attempts:
            phase = attempt["phase"]
            if phase == "repair_1":
                raw_primary = (layout["raw_primary"] / f"{case.case_id}.txt").read_bytes().decode("utf-8")
                diagnostic = json.loads(
                    (layout["failures"] / f"{case.case_id}_primary_diagnostic.json").read_text(encoding="utf-8")
                )
                specs[phase] = protocol.build_repair_spec(case.case_id, case.prepared_input, raw_primary, diagnostic)
            spec = specs[phase]
            protocol.assert_locked_job_spec(spec)
            expected_jobs.append(spec.job_id)
            record = executor.load_job(spec)
            request_ok &= attempt["request_fingerprint"] == spec.request_fingerprint == record["request_fingerprint"]
            identity_ok &= (record["model_requested"], record["credential_slot"]) == (protocol.MODEL, protocol.CREDENTIAL_SLOT)
            identity_ok &= all(
                (step.get("model"), step.get("slot_id")) == (protocol.MODEL, protocol.CREDENTIAL_SLOT)
                for window in record["windows"] for step in window["attempt_history"]
            )
            if attempt["provider_success"]:
                directory = layout["raw_primary"] if phase == "primary" else layout["raw_repair"]
                raw = (directory / f"{case.case_id}.txt").read_bytes()
                lock_ok &= record["state"] == JobState.SUCCEEDED_LOCKED.value
                raw_ok &= (sha256_bytes(raw) == attempt["raw_response_sha256"]
                           == record["first_success"]["response_sha256"]
                           and record["first_success"]["raw_response"].encode("utf-8") == raw)
                draft, batch, validation = compile_raw_response(raw.decode("utf-8"), case)
                draft_ok &= (None if draft is None else sha256_bytes(canonical_json_bytes(draft))) == attempt["draft_sha256"]
                draft_ok &= validation["category"] == attempt["structural_failure_category"]
                draft_ok &= attempt["provider_projection_valid"] == (
                    projection_validator.is_valid(draft) if validation["category"] != "JSON_PARSE_FAILURE" else None
                )
            else:
                lock_ok &= record["state"] == JobState.TERMINAL_FAILED.value and item["terminal_status"] == "TRANSPORT_FAILURE"
        if item["terminal_status"] == "STRUCTURAL_VALID":
            compiled = (layout["compiled"] / f"{case.case_id}.json").read_bytes()
            terminal_ok &= (sha256_bytes(compiled) == item["compiled_batch_sha256"]
                            and validation is not None and validation["pass"]
                            and canonical_json_bytes(batch) == compiled)
            text = compiled.decode("utf-8")
            terminal_ok &= p4_run_id(case.case_id) in text and ("P3_" + case.case_id) not in text
        else:
            failure = (layout["failures"] / f"{case.case_id}.json").read_bytes()
            terminal_ok &= sha256_bytes(failure) == item["terminal_failure_sha256"]
            terminal_ok &= not (layout["compiled"] / f"{case.case_id}.json").exists()
        terminal_ok &= len(attempts) <= 1 + protocol.MAX_STRUCTURAL_REPAIRS_PER_CASE
        terminal_ok &= not (len(attempts) == 2 and item["primary"]["compiler_success"] is True)
    job_files = sorted(path.name for path in (layout["checkpoints"] / "jobs").glob("*.json"))
    identities = [case_identity(item, lock_sha256) for item in predictions]
    operations = operation_accounting(pacer, budget, result["transport"] == "ACCEPTED_GEMINI_DEV_WINDOW_TRANSPORT")
    checks.update({
        "case_result_files_match_the_result": case_file_ok,
        "request_fingerprints_rebuild_from_input": request_ok,
        "raw_response_hashes_match_files_and_checkpoints": raw_ok,
        "parsed_draft_hashes_and_categories_recompute": draft_ok,
        "compiled_and_failure_record_hashes": terminal_ok,
        "immutable_success_locks": lock_ok,
        "no_model_or_credential_switch": identity_ok,
        "durable_jobs_are_exactly_the_expected_jobs": job_files == sorted(f"{name}.json" for name in expected_jobs),
        "maximum_one_repair_per_case_and_no_other_retry": all(
            name.endswith(("_PRIMARY.json", "_REPAIR_1.json")) for name in job_files
        ) and len(job_files) <= 2 * len(CASE_IDS),
        "provider_operations_within_budget": operations["pacing_reservations"] <= MAX_REAL_PROVIDER_OPERATIONS
        and operations["pacing_reservations"] == result["operations"]["pacing_reservations"],
        "pacing_invariant": operations["pacing_invariant"] == "PASS",
        "prediction_set_rebuilds_deterministically": identities == result["prediction_identities"] == manifest["entries"]
        and prediction_set_sha256(identities, lock_sha256, expected_input_sha256)
        == result["prediction_set_sha256"] == manifest["prediction_set_sha256"],
        "metrics_rebuild_from_case_results": structural_metrics(predictions, result["operations"]) == result["metrics"],
        "public_prediction_lock_rebuilds": validate_public_prediction_lock(
            build_public_prediction_lock(result), input_sha256=expected_input_sha256
        ) == result["prediction_set_sha256"],
        "result_is_for_this_input": result["dev3_input_sha256"] == expected_input_sha256,
        "gold_and_holdout_flags_false": result["dev3_gold_opened"] is False and result["holdout_opened"] is False
        and result["semantic_scoring_performed"] is False,
    })
    if PREDICTION_LOCK_PATH.exists():
        published = yaml.safe_load(PREDICTION_LOCK_PATH.read_text(encoding="utf-8"))
        checks["published_prediction_lock_matches_private_result"] = published == _json_normalized(
            build_public_prediction_lock(result)
        )
    if not all(checks.values()):
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise P4Dev3Error("Post-run integrity check failed: " + ", ".join(failed))
    return {"status": "POST_RUN_INTEGRITY_PASS", "checks": checks, "prediction_set_sha256": result["prediction_set_sha256"],
            "experiment_lock_sha256": lock_sha256, "provider_operations_during_verification": 0}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True,
                        choices=("write-lock", "verify-lock", "preflight", "run", "verify-run", "publish"))
    parser.add_argument("--input-archive", type=Path)
    parser.add_argument("--private-root", type=Path, default=DEFAULT_PRIVATE_ROOT)
    parser.add_argument("--expected-experiment-lock-sha256")
    parser.add_argument("--authorize-live-provider-operations", default="")
    parser.add_argument("--regression-json", type=Path)
    args = parser.parse_args(argv)
    stage = STATUS_PRELIVE_LOCK_FAILED
    try:
        if args.mode == "write-lock":
            print(json.dumps({"experiment_lock_sha256": write_experiment_lock(), "provider_operations": 0}, sort_keys=True))
            return 0
        if args.mode == "verify-lock":
            _, digest = locked_experiment(args.expected_experiment_lock_sha256)
            print(json.dumps({"experiment_lock_sha256": digest, "protocol_sha256": protocol.PROTOCOL_SHA256,
                              "provider_operations": 0, "status": "EXPERIMENT_LOCK_VERIFIED"}, sort_keys=True))
            return 0
        if args.input_archive is None:
            raise P4Dev3Error("This mode needs the DEV3 input archive")
        common = {"input_archive": args.input_archive, "private_root": args.private_root,
                  "expected_lock_sha256": args.expected_experiment_lock_sha256}
        if args.mode == "preflight":
            stage = STATUS_PREFLIGHT_FAILED
            print(json.dumps(preflight_report(preflight(**common)), sort_keys=True))
            return 0
        if args.mode == "run":
            stage = STATUS_FAIL_CLOSED
            if args.authorize_live_provider_operations != LIVE_AUTHORIZATION_TOKEN:
                raise P4Dev3Error("Run mode requires the explicit live authorization token")
            result = run(**common)
            public = {"status": result["status"], "experiment_lock_sha256": result["experiment_lock_sha256"]}
            if result["status"] == STATUS_COMPLETE:
                public.update({"prediction_set_sha256": result["prediction_set_sha256"],
                               "terminal": result["metrics"]["terminal_outcomes"],
                               "provider_operations": result["operations"]["pacing_reservations"]})
            else:
                public.update({"completed_cases": result["completed_cases"],
                               "uncompleted_cases": result["uncompleted_cases"],
                               "provider_operations": result["operations"]["pacing_reservations"]})
            print(json.dumps(public, sort_keys=True), flush=True)
            return 0 if result["status"] == STATUS_COMPLETE else 5
        stage = STATUS_FAIL_CLOSED
        report = verify_run(**common)
        if args.mode == "publish":
            if args.regression_json is None:
                raise P4Dev3Error("Publishing needs the regression summary")
            regression = json.loads(args.regression_json.read_text(encoding="utf-8"))
            layout = private_layout(args.private_root)
            result = json.loads((layout["root"] / f"{TUNING_RESULT_ID}.json").read_text(encoding="utf-8"))
            lock_file_sha256 = write_public_prediction_lock(build_public_prediction_lock(result))
            record = build_public_result_record(result, report, regression, lock_file_sha256)
            report = {
                "status": "PUBLIC_RECORDS_WRITTEN",
                "prediction_set_sha256": result["prediction_set_sha256"],
                "public_prediction_lock_file_sha256": lock_file_sha256,
                "public_result_file_sha256": write_public_result_record(record),
                "provider_operations": 0,
            }
        print(json.dumps(report, sort_keys=True))
        return 0
    except PreflightFailure as error:
        print(f"{STATUS_PREFLIGHT_FAILED}: {error}", flush=True)
        return 3
    except PriorExecutionState:
        print(STATUS_INTERRUPTED, flush=True)
        return 4
    except (P4Dev3Error, CheckpointIntegrityError, RuntimeError) as error:
        print(f"{stage}: {type(error).__name__}", flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
