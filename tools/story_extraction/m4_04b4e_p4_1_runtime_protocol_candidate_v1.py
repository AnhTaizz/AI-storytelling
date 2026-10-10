"""P4.1 runtime protocol candidate V1 (M4-04B4E). A proposal, not a live authorization.

Binds the accepted P4.1 candidate V1.1 and structural diagnostic V3.1 to the accepted
runtime shape of P4 protocol V2: the same proposed model, credential slot, generation
settings, native provider projection, durable executor, pacing, first-success lock and
single structural repair. What differs from protocol V2 is the model-facing contract
(P4.1 prompts) and the repair path (diagnostic V3.1, an explicit repair-actionability
rule, a repair request that is rebuilt and compared before it is rendered).

    prompt schema  == full model schema
    native schema  == provider_projection(full model schema)

Nothing here is authorized to run against a provider. The model and credential slot are
proposed future bindings: this module resolves no credential, imports no transport and
calls nothing. The live operation budget and the open decisions listed in
OPEN_DECISIONS must be settled by the Orchestrator before this protocol can be locked
for a live run; assert_ready_for_live_lock() fails until then.

The superseded M4-04B4D candidate V1, diagnostic V3 and diagnostic V2 are rejected
wherever a request or a binding is checked. Protocol V2 and every historical record are
unchanged.
"""
from __future__ import annotations

import json
import re
from typing import Any, Mapping, Optional

from tools.story_extraction import m4_04b4a_p4_output_contract_v1 as p4_contract
from tools.story_extraction import m4_04b4br_p4_protocol_v2 as protocol_v2
from tools.story_extraction import m4_04b4d_f1_p4_1_compiler_aware_contract_v1_1 as candidate
from tools.story_extraction import m4_04b4d_f1_structural_diagnostic_v3_1 as diagnostic_v3_1
from tools.story_extraction import m4_04b4e_p4_1_retention_metrics_v1 as retention
from tools.story_extraction import materialize_draft_v1_1_model_schema_v1 as materializer
from tools.story_extraction import project_draft_v1_1_model_schema_to_gemini_v1 as projection
from tools.story_extraction.durable_research_executor_v1 import (
    DURABLE_EXECUTOR_VERSION,
    GLOBAL_MAX_PROVIDER_OPERATIONS,
    GLOBAL_ROLLING_WINDOW_SECONDS,
    MAX_EXECUTION_WINDOWS_PER_JOB,
    MAX_PROVIDER_ATTEMPTS_PER_JOB,
    MAX_PROVIDER_ATTEMPTS_PER_WINDOW,
    DurableJobSpec,
)
from tools.story_extraction.m4_04b4b_p4_protocol_v1 import (
    canonical_json_bytes,
    normalized_file_sha256,
    sha256_bytes,
    sha256_text,
)


REPO_ROOT = materializer.REPO_ROOT
TASK_ID = "M4-04B4E"
EXPECTED_BASE_COMMIT = "2d46358cdadd69dec50a3202cf3aad8c30878c96"
PROTOCOL_ID = "M4_P4_1_RUNTIME_PROTOCOL_CANDIDATE_V1"
PROTOCOL_SCHEMA_VERSION = "M4_P4_1_RUNTIME_PROTOCOL_CANDIDATE_SCHEMA_V1"
PROTOCOL_STANDING = "PROPOSED_EXPERIMENTAL_PROTOCOL_NOT_A_LIVE_AUTHORIZATION"
PROTOCOL_PATH = "tools/story_extraction/m4_04b4e_p4_1_runtime_protocol_candidate_v1.py"
# SHA-256 of canonical_json_bytes(build_protocol()). A changed binding is a new protocol candidate.
PROTOCOL_SHA256 = "5917a012663963d1d9e15f3be00c38a9ea1306d4fe8ad1e01134a99dc3618ff7"

# The accepted identities. Nothing else may be the active implementation.
ACTIVE_CANDIDATE_ID = "P4_1_STORY_EXTRACTION_DRAFT_V1_1_COMPILER_AWARE_V1_1"
ACTIVE_CANDIDATE_SHA256 = "5a102aa782f876dcbfc94d71fef238de0e712288ed4428a27df6984edfe23019"
ACTIVE_DIAGNOSTIC_ID = "M4_P4_1_STRUCTURAL_REPAIR_DIAGNOSTIC_V3_1"
ACTIVE_DIAGNOSTIC_TOOL_SHA256 = "6cd81cb029baa48998cb2f4da9c75a17be6c984965584b8cedb52c721ae3ee33"
FULL_MODEL_SCHEMA_SHA256 = "5aa2ed6dde3791546ddd5e059648d8dac38df1571a6073b7abc31c89eb257f14"
PROVIDER_PROJECTION_SHA256 = "89506defa4089b1449f7c80bbcf782d94065802ceae71aa86e1598a5a17ab9bd"
HISTORICAL_PROTOCOL_V2_SHA256 = "24b2af927e07078da3a06fe329aa5378cdde92675e76e92e2c03d9ad82726025"
P4_PREDICTION_SET_SHA256 = "ee67ff92c72f01b98d2bd7ac892fa3fb13d437074511bc5b4bf946aa7ee66538"
SUPERSEDED_CANDIDATE_IDS = ("P4_1_STORY_EXTRACTION_DRAFT_V1_1_COMPILER_AWARE_V1",)
SUPERSEDED_DIAGNOSTIC_IDS = ("M4_P4_1_STRUCTURAL_REPAIR_DIAGNOSTIC_V3", "M4_P4_STRUCTURAL_REPAIR_DIAGNOSTIC_V2")

# Proposed future live bindings, kept equal to protocol V2 for continuity. Not an authorization.
MODEL = "gemini-3.5-flash-lite"
CREDENTIAL_SLOT = "gemini_slot_3"
TEMPERATURE = 0
MAX_OUTPUT_TOKENS = 16384
RESPONSE_MIME_TYPE = "application/json"
CONCURRENCY = 1
SCHEMA_RESPONSE_MODE = protocol_v2.SCHEMA_RESPONSE_MODE
RUNTIME_VERSION = protocol_v2.RUNTIME_VERSION
WINDOW_COOLDOWN_SECONDS = 60
MAX_STRUCTURAL_REPAIRS_PER_CASE = 1
REPAIR_ELIGIBLE_CATEGORIES = ("JSON_PARSE_FAILURE", "DRAFT_SCHEMA_FAILURE", "DRAFT_COMPILER_FAILURE")
TERMINAL_STATUSES = ("STRUCTURAL_VALID", "STRUCTURAL_FAILURE", "TRANSPORT_FAILURE")
LIVE_OPERATION_BUDGET = "REQUIRES_ORCHESTRATOR_AUTHORIZATION"
EXECUTOR_PROTOCOL_ID_PREFIX = PROTOCOL_ID + ":"
PRIMARY_JOB_ID = "M4B4E_P41_{CASE_ID}_PRIMARY"
REPAIR_JOB_ID = "M4B4E_P41_{CASE_ID}_REPAIR_1"

# Repair actionability: what a rejected response's diagnostic allows the runtime to do.
ACTION_ACCEPTED = "ACCEPTED_NO_REPAIR"
ACTION_ACTIONABLE = "ACTIONABLE"
ACTION_PARTIAL = "PARTIALLY_DESCRIBED"
ACTION_HOST_SIDE = "NOT_ACTIONABLE_HOST_SIDE_FAILURE"
ACTION_INVALID = "NOT_ACTIONABLE_INVALID_OR_UNSAFE_DIAGNOSTIC"
ACTION_EMPTY_PRIMARY = "NOT_ACTIONABLE_EMPTY_PRIMARY_RESPONSE"
ACTIONABILITY_CLASSES = (
    ACTION_ACCEPTED, ACTION_ACTIONABLE, ACTION_PARTIAL, ACTION_HOST_SIDE, ACTION_INVALID, ACTION_EMPTY_PRIMARY,
)
REASON_UNLOCATED = "A_FINDING_ABOUT_ONE_RECORD_HAS_NO_VERIFIED_LOCATOR"
REASON_UNATTRIBUTED = "A_FINDING_HAS_NO_RECOGNIZED_RULE"
DECISION_REPAIR = "REPAIR"
DECISION_NO_REPAIR = "NO_REPAIR"
# The one class whose handling is not decided here. A caller must state the policy on every call.
PARTIAL_POLICY_REFUSE = "REFUSE_REPAIR"
PARTIAL_POLICY_ALLOW = "ALLOW_REPAIR"
PARTIAL_POLICIES = (PARTIAL_POLICY_REFUSE, PARTIAL_POLICY_ALLOW)
PARTIAL_POLICY_STANDING = "UNRESOLVED_REQUIRES_ORCHESTRATOR_DECISION"
# Statements of diagnostic V3.1 that may be false while a repair is still actionable: they say what the
# compiler has not looked at yet, not that a finding is unsafe or cannot be acted on.
DOWNSTREAM_STATEMENTS = (
    "compiler_structural_rules_checked", "canonical_validation_reached", "downstream_canonical_issues_enumerated",
)
OPEN_DECISIONS = (
    "LIVE_OPERATION_BUDGET",
    "REPAIR_POLICY_FOR_A_PARTIALLY_DESCRIBED_DIAGNOSTIC",
    "CONFIRMATION_OF_THE_PROPOSED_MODEL_CREDENTIAL_SLOT_AND_GENERATION_SETTINGS",
    "DATASET_AND_CASE_LIST_FOR_ANY_LIVE_RUN",
    "PRIVATE_ROOT_AND_RESULT_ARTIFACT_CONTRACT_FOR_ANY_LIVE_RUN",
    "LIVE_TRANSPORT_BINDING_AND_EXECUTION_ENVIRONMENT",
)

# The P4.1 files this candidate depends on, added to everything protocol V2 bound. UTF8_LF_NORMALIZED_SHA256.
P4_1_BOUND_FILES = {
    "tools/story_extraction/m4_04b4br_p4_protocol_v2.py":
        "7410fbc6778eb8d4fe6c64794f645553c380da667f3f774522c6461ab508a001",
    "tools/story_extraction/m4_04b4d_f1_p4_1_compiler_aware_contract_v1_1.py":
        "dc8d4a6d48e4d5eded2c237533fa92d4a55620fb9e7a9c12bf0b8786b7659731",
    "tools/story_extraction/m4_04b4d_f1_structural_diagnostic_v3_1.py": ACTIVE_DIAGNOSTIC_TOOL_SHA256,
    "tools/story_extraction/m4_04b4d_p4_1_compiler_aware_contract_v1.py":
        "daefe500545bdd03c7a07ffe364495304c4c85980ba583336b7d8dc9197e093b",
    "tools/story_extraction/m4_04b4d_structural_diagnostic_v3.py":
        "962ad21da3448d73efc6fabcbe443a41b838a0cf180ec6047a4b5f58320e4adc",
    "tools/story_extraction/prompts/story_extraction_draft_p4_1_v1_system.txt":
        "598aae325585dddae4588ca6f23551fe53ca91043bc9722e7fdafbc6afbbfea8",
    "tools/story_extraction/prompts/story_extraction_draft_p4_1_v1_user.txt":
        "4a642008e3b4be809ab71cf9a107a35260950066bb48ee90ca9e2d64ed76c01a",
    "tools/story_extraction/prompts/story_extraction_draft_p4_1_v1_1_repair_user.txt":
        "2680d93120d4b26b107ca61f4fd557c72f1790bb54807bb01153c73c366cebf2",
    "tools/story_extraction/prompts/story_extraction_draft_p4_1_v1_repair_user.txt":
        "ba1d2035852a0fca8f4d889ca8f26cadb2410373fbe6e5208b40d800a9e30ab6",
    retention.METRICS_PATH: "f6eb7a07a9bc0b09a446d5c812554e7bc430cccb96063d30c151f4e58c6e1827",
}
BOUND_FILES = {**protocol_v2.BOUND_FILES, **P4_1_BOUND_FILES}

_CASE_ID = re.compile(r"^[A-Z][A-Z0-9_]{0,39}$")
_JOB_ID = re.compile(r"M4B4E_P41_([A-Z][A-Z0-9_]{0,39}?)_(PRIMARY|REPAIR_1)")
_ANY_REPAIR_JOB = re.compile(r"M4B4E_P41_[A-Z][A-Z0-9_]{0,39}?_REPAIR_[0-9]+")


class P41RuntimeProtocolError(RuntimeError):
    """The protocol candidate, a binding or a job specification differs from what is proposed. Fail closed."""


# ---------------------------------------------------------------------------
# Identities, generation settings and the schema lineage gate
# ---------------------------------------------------------------------------

def assert_active_identities(candidate_id: Any, candidate_sha256: Any, diagnostic_id: Any,
                             diagnostic_tool_sha256: Any) -> None:
    """Only candidate V1.1 and diagnostic V3.1 may be active. Superseded identities are named in the error."""
    if candidate_id in SUPERSEDED_CANDIDATE_IDS or candidate_sha256 == candidate.SUPERSEDED_CANDIDATE_SHA256:
        raise P41RuntimeProtocolError("The superseded M4-04B4D candidate V1 cannot be the active candidate")
    if diagnostic_id in SUPERSEDED_DIAGNOSTIC_IDS:
        raise P41RuntimeProtocolError("A superseded structural diagnostic cannot be the active diagnostic")
    if (candidate_id, candidate_sha256) != (ACTIVE_CANDIDATE_ID, ACTIVE_CANDIDATE_SHA256):
        raise P41RuntimeProtocolError("The active candidate is not the accepted P4.1 candidate V1.1")
    if (diagnostic_id, diagnostic_tool_sha256) != (ACTIVE_DIAGNOSTIC_ID, ACTIVE_DIAGNOSTIC_TOOL_SHA256):
        raise P41RuntimeProtocolError("The active diagnostic is not the accepted structural diagnostic V3.1")


def native_response_schema() -> dict[str, Any]:
    """The exact accepted provider projection. Never the full model schema."""
    try:
        return protocol_v2.native_response_schema()
    except protocol_v2.P4ProtocolV2Error as error:
        raise P41RuntimeProtocolError("Provider projection is unavailable or not the accepted projection") from error


def generation_config() -> dict[str, Any]:
    """The proposed generation settings: those of protocol V2, with the projection as native schema."""
    try:
        config = protocol_v2.generation_config()
    except protocol_v2.P4ProtocolV2Error as error:
        raise P41RuntimeProtocolError("Generation settings differ from the accepted settings") from error
    if (
        set(config) != {"temperature", "max_output_tokens", p4_contract.NATIVE_SCHEMA_PARAMETER}
        or type(config["temperature"]) is not int or config["temperature"] != TEMPERATURE
        or config["max_output_tokens"] != MAX_OUTPUT_TOKENS
        or sha256_text(projection.projection_text(config[p4_contract.NATIVE_SCHEMA_PARAMETER])) != PROVIDER_PROJECTION_SHA256
    ):
        raise P41RuntimeProtocolError("Generation settings differ from the proposed settings")
    return config


def generation_config_sha256() -> str:
    return sha256_bytes(canonical_json_bytes(generation_config()))


def prompt_hashes() -> dict[str, str]:
    try:
        return candidate.prompt_hashes()
    except candidate.P41ContractV11Error as error:
        raise P41RuntimeProtocolError("P4.1 V1.1 prompts are unavailable") from error


def _prompt_material() -> dict[str, str]:
    try:
        return candidate.prompt_material()
    except candidate.P41ContractV11Error as error:
        raise P41RuntimeProtocolError("P4.1 V1.1 prompts are unavailable") from error


def schema_lineage_gate() -> dict[str, str]:
    """The prompt carries the full model schema; the native schema is its projection and nothing else."""
    material = _prompt_material()
    full = materializer.load_tracked_model_schema()
    native = generation_config()[p4_contract.NATIVE_SCHEMA_PARAMETER]
    for role in ("primary_system", "repair_system"):
        in_prompt = p4_contract.extract_prompt_schema(
            material[role], p4_contract.SCHEMA_SECTION_MARKER, p4_contract.REGISTRY_SECTION_MARKER)
        if not (in_prompt == full == materializer.materialize_model_schema()):
            raise P41RuntimeProtocolError("A system prompt does not carry the full model schema")
        if native == in_prompt:
            raise P41RuntimeProtocolError("Native schema must be the provider projection, not the full model schema")
    if materializer.model_schema_sha256() != FULL_MODEL_SCHEMA_SHA256:
        raise P41RuntimeProtocolError("Full model schema differs from the accepted schema")
    if native == full or native != projection.project(full)[0]:
        raise P41RuntimeProtocolError("Native schema is not the projection of the full model schema")
    try:
        projection.lineage_gate()
    except (projection.ProjectionError, materializer.ModelSchemaError) as error:
        raise P41RuntimeProtocolError("Provider projection lineage gate failed") from error
    if materializer.external_refs(native):
        raise P41RuntimeProtocolError("Native response schema has an external reference")
    return {
        "primary_prompt_schema_equals_full_model_schema": "PASS",
        "repair_prompt_schema_equals_full_model_schema": "PASS",
        "full_model_schema_sha256": "PASS",
        "native_schema_equals_projection_of_full_model_schema": "PASS",
        "native_schema_differs_from_full_model_schema": "PASS",
        "provider_projection_sha256": "PASS",
        "external_ref_count_zero": "PASS",
    }


# ---------------------------------------------------------------------------
# Protocol candidate
# ---------------------------------------------------------------------------

def build_protocol() -> dict[str, Any]:
    return {
        "protocol_id": PROTOCOL_ID,
        "protocol_schema_version": PROTOCOL_SCHEMA_VERSION,
        "task_id": TASK_ID,
        "base_commit": EXPECTED_BASE_COMMIT,
        "standing": PROTOCOL_STANDING,
        "authorization": {
            "live_provider_operations": "NOT_AUTHORIZED",
            "credential_resolution": "NOT_AUTHORIZED",
            "live_operation_budget": LIVE_OPERATION_BUDGET,
            "open_decisions": list(OPEN_DECISIONS),
        },
        "continuity": {
            "runtime_shape_of": protocol_v2.PROTOCOL_ID,
            "historical_protocol_v2_sha256": HISTORICAL_PROTOCOL_V2_SHA256,
            "historical_protocol_v2_modified": False,
            "p4_prediction_set_sha256": P4_PREDICTION_SET_SHA256,
            "differences_from_protocol_v2": [
                "MODEL_FACING_CONTRACT_IS_P4_1_CANDIDATE_V1_1",
                "REPAIR_DIAGNOSTIC_IS_V3_1",
                "REPAIR_REQUEST_IS_REBUILT_AND_COMPARED_BEFORE_RENDERING",
                "EXPLICIT_REPAIR_ACTIONABILITY_RULE",
                "RETENTION_AND_EMPTY_OUTPUT_METRICS_ARE_PART_OF_THE_RESULT",
            ],
        },
        "candidate": {
            "candidate_id": ACTIVE_CANDIDATE_ID,
            "candidate_sha256": ACTIVE_CANDIDATE_SHA256,
            "superseded_candidates_rejected": list(SUPERSEDED_CANDIDATE_IDS),
            "canonical_draft_contract": materializer.CANONICAL_DRAFT_VERSION,
            "model_schema_identity": materializer.MODEL_SCHEMA_IDENTITY,
            "model_schema_sha256": FULL_MODEL_SCHEMA_SHA256,
        },
        "diagnostic": {
            "diagnostic_id": ACTIVE_DIAGNOSTIC_ID,
            "diagnostic_format": diagnostic_v3_1.DIAGNOSTIC_FORMAT,
            "diagnostic_tool_sha256": ACTIVE_DIAGNOSTIC_TOOL_SHA256,
            "superseded_diagnostics_rejected": list(SUPERSEDED_DIAGNOSTIC_IDS),
        },
        "schema_roles": {
            "prompt_schema": materializer.MODEL_SCHEMA_IDENTITY,
            "prompt_schema_sha256": FULL_MODEL_SCHEMA_SHA256,
            "native_schema": projection.PROJECTION_IDENTITY,
            "native_schema_sha256": PROVIDER_PROJECTION_SHA256,
            "native_schema_role": "OUTPUT_SHAPING_AID_ONLY",
            "authoritative_validator": "UNCHANGED_LOCAL_DRAFT_V1_1_VALIDATOR",
        },
        "proposed_generation": {
            "binding": "PROPOSED_FUTURE_LIVE_BINDING_NOT_AN_AUTHORIZATION",
            "model": MODEL,
            "credential_slot": CREDENTIAL_SLOT,
            "temperature": TEMPERATURE,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "response_mime_type": RESPONSE_MIME_TYPE,
            "native_schema_enabled": True,
            "native_schema_parameter": p4_contract.NATIVE_SCHEMA_PARAMETER,
            "native_schema_sha256": PROVIDER_PROJECTION_SHA256,
            "generation_config_sha256": generation_config_sha256(),
            "generation_config_equals_protocol_v2": True,
            "schema_response_mode": SCHEMA_RESPONSE_MODE,
            "concurrency": CONCURRENCY,
            "seed": "NOT_SUPPORTED_NOT_USED",
        },
        "prompt_hashes": prompt_hashes(),
        "bound_files": dict(BOUND_FILES),
        "bound_file_hash_mode": "UTF8_LF_NORMALIZED_SHA256",
        "compilation": {
            "validator": "tools.story_extraction.draft_compiler_v1_1.validate_draft_v1_1",
            "compiler": "tools.story_extraction.draft_compiler_v1_1.compile_story_extraction_draft_v1_1",
            "acceptance_authority": "UNCHANGED_COMPILER_AND_CANONICAL_VALIDATOR",
            "diagnostic_overrides_the_compiler": False,
            "host_edits_the_draft": False,
            "automatic_occurrence_selection": "FORBIDDEN",
        },
        "proposed_durable_execution": {
            "runtime": RUNTIME_VERSION,
            "durable_executor": DURABLE_EXECUTOR_VERSION,
            "transport": "NOT_BOUND_REQUIRES_ORCHESTRATOR_AUTHORIZATION",
            "pacer": "PersistentRollingOperationPacer",
            "maximum_windows_per_job": MAX_EXECUTION_WINDOWS_PER_JOB,
            "maximum_provider_attempts_per_window": MAX_PROVIDER_ATTEMPTS_PER_WINDOW,
            "maximum_provider_attempts_per_job": MAX_PROVIDER_ATTEMPTS_PER_JOB,
            "global_pacing_max_operations": GLOBAL_MAX_PROVIDER_OPERATIONS,
            "global_pacing_rolling_window_seconds": GLOBAL_ROLLING_WINDOW_SECONDS,
            "window_cooldown_seconds": WINDOW_COOLDOWN_SECONDS,
            "model_switch": "FORBIDDEN",
            "credential_switch": "FORBIDDEN",
        },
        "exactly_once": {
            "first_success": "IMMUTABLE_LOCK",
            "raw_response": "WRITE_ONCE_IDENTIFIED_BY_SHA256",
            "request_identity": "REQUEST_FINGERPRINT_BOUND_INTO_THE_CHECKPOINT",
            "retry_of_a_successful_response": "FORBIDDEN",
            "output_aware_transport_retry": "FORBIDDEN",
            "retry_of_a_terminal_case": "FORBIDDEN",
            "in_flight_checkpoint_on_restart": "FAIL_CLOSED_MANUAL_REVIEW",
            "existing_state_on_a_new_run": "REFUSED",
            "checkpoint_reset_to_evade_limits": "FORBIDDEN",
            "operation_accounting": "PERSISTED_RESERVATION_COUNT_OF_THE_PACER",
        },
        "repair_policy": {
            "diagnostic": ACTIVE_DIAGNOSTIC_ID,
            "maximum_per_case": MAX_STRUCTURAL_REPAIRS_PER_CASE,
            "eligible_primary_failure_categories": list(REPAIR_ELIGIBLE_CATEGORIES),
            "eligible_only_after_successful_primary_response": True,
            "repair_receives": ["SAME_PREPARED_INPUT", "UNCHANGED_PRIMARY_RESPONSE", "STRUCTURAL_DIAGNOSTIC_V3_1"],
            "diagnostic_rebuilt_and_compared_before_rendering": True,
            "same_native_schema_and_generation_settings": True,
            "actionability_classes": list(ACTIONABILITY_CLASSES),
            "actionability_decisions": {
                ACTION_ACCEPTED: DECISION_NO_REPAIR,
                ACTION_ACTIONABLE: DECISION_REPAIR,
                ACTION_PARTIAL: PARTIAL_POLICY_STANDING,
                ACTION_HOST_SIDE: DECISION_NO_REPAIR,
                ACTION_INVALID: DECISION_NO_REPAIR,
                ACTION_EMPTY_PRIMARY: DECISION_NO_REPAIR,
            },
            "statements_that_may_be_false_for_an_actionable_diagnostic": list(DOWNSTREAM_STATEMENTS),
            "partially_described_reasons": [REASON_UNLOCATED, REASON_UNATTRIBUTED],
            "quality_signal": "FORBIDDEN",
            "missing_fact_or_coverage_retry": "FORBIDDEN",
            "gold_signal": "FORBIDDEN",
            "semantic_reinterpretation": "FORBIDDEN",
            "repair_failure_is_terminal": True,
        },
        "request_construction": {
            "primary_job_id_pattern": PRIMARY_JOB_ID,
            "repair_job_id_pattern": REPAIR_JOB_ID,
            "input": "HOST_PREPARED_DRAFT_V1_1_INPUT_ONLY",
        },
        "result": {
            "terminal_statuses": list(TERMINAL_STATUSES),
            "retention_metrics": retention.definition(),
            "required_live_reporting": list(candidate.REQUIRED_LIVE_REPORTING),
            "acceptance_threshold": "NONE_DEFINED",
        },
        "data": {
            "bound_to_a_dataset": False,
            "DEV3_status": "TUNING_DATA_AFTER_P3_FAILURE",
            "DEV3_gold": "FORBIDDEN",
            "holdout": "FORBIDDEN",
        },
    }


def protocol_sha256() -> str:
    return sha256_bytes(canonical_json_bytes(build_protocol()))


def validate_bound_files() -> dict[str, str]:
    """Every file the protocol depends on is exactly the bound one. Cheap enough to run before each operation."""
    for relative, expected in BOUND_FILES.items():
        try:
            actual = normalized_file_sha256(REPO_ROOT / relative)
        except (OSError, UnicodeError) as error:
            raise P41RuntimeProtocolError("Bound file is unavailable: " + relative) from error
        if actual != expected:
            raise P41RuntimeProtocolError("Bound file mismatch: " + relative)
    return {"bound_files": "PASS", "bound_file_count": str(len(BOUND_FILES))}


def locked_protocol() -> dict[str, Any]:
    """Return the protocol candidate only while every binding is exactly the proposed one."""
    validate_bound_files()
    # The candidate gate re-locks historical protocol V2 on the way: it fails if V2 or anything V2 binds changed.
    try:
        candidate.assert_candidate_ready()
    except candidate.P41ContractV11Error as error:
        raise P41RuntimeProtocolError("P4.1 candidate V1.1 or historical protocol V2 does not pass its gates") from error
    if protocol_v2.PROTOCOL_SHA256 != HISTORICAL_PROTOCOL_V2_SHA256:
        raise P41RuntimeProtocolError("Historical protocol V2 changed")
    assert_active_identities(
        candidate.CANDIDATE_ID, candidate.candidate_sha256(), diagnostic_v3_1.DIAGNOSTIC_ID,
        normalized_file_sha256(REPO_ROOT / diagnostic_v3_1.DIAGNOSTIC_PATH))
    schema_lineage_gate()
    protocol = build_protocol()
    if sha256_bytes(canonical_json_bytes(protocol)) != PROTOCOL_SHA256:
        raise P41RuntimeProtocolError("Runtime protocol differs from the pinned protocol candidate")
    return protocol


def executor_protocol_id() -> str:
    """Identity stamped into every durable checkpoint of this protocol candidate."""
    return EXECUTOR_PROTOCOL_ID_PREFIX + PROTOCOL_SHA256


def assert_ready_for_live_lock() -> None:
    """A live lock is not possible while a decision is open. This task leaves all of them open."""
    if OPEN_DECISIONS:
        raise P41RuntimeProtocolError(
            "The protocol candidate cannot be locked for a live run: open decisions " + ", ".join(OPEN_DECISIONS))


# ---------------------------------------------------------------------------
# Repair actionability
# ---------------------------------------------------------------------------

def classify_repair_actionability(diagnostic: Any, primary_response: Any) -> dict[str, Any]:
    """What a diagnostic V3.1 of a primary response allows. Conservative and explicit.

    `complete: false` alone refuses nothing: for a rejected draft it is always false. The
    statements in DOWNSTREAM_STATEMENTS say what the compiler has not looked at yet; a
    diagnostic that is incomplete only in those is still actionable. A finding that is
    about one record and names none, or that names no recognized rule, makes the
    diagnostic partially described; whether such a diagnostic is repaired is not decided
    here.
    """
    def result(name: str, reasons: Optional[list[str]] = None, downstream: Optional[list[str]] = None) -> dict[str, Any]:
        return {"class": name, "reasons": list(reasons or []),
                "incomplete_downstream_statements": list(downstream or [])}

    try:
        well_formed = (
            isinstance(diagnostic, Mapping)
            # Field sets, not field order: a diagnostic read back from its canonical JSON has sorted keys.
            and set(diagnostic) == set(diagnostic_v3_1.ENVELOPE_FIELDS)
            and diagnostic["diagnostic"] == ACTIVE_DIAGNOSTIC_ID
            and diagnostic["format"] == diagnostic_v3_1.DIAGNOSTIC_FORMAT
            and set(diagnostic["completeness"]) == set(diagnostic_v3_1.COMPLETENESS_FIELDS)
            and diagnostic["completeness"]["observed_blockers_preserved"] is True
            and diagnostic["finding_count"] == len(diagnostic["findings"])
        )
    except (KeyError, TypeError):
        well_formed = False
    if not well_formed:
        return result(ACTION_INVALID)
    if diagnostic["compiler_verdict"]["compiled"]:
        return result(ACTION_ACCEPTED)
    if diagnostic["category"] not in REPAIR_ELIGIBLE_CATEGORIES or not diagnostic["findings"]:
        return result(ACTION_INVALID)
    if not isinstance(primary_response, str) or primary_response == "":
        return result(ACTION_EMPTY_PRIMARY)
    completeness = diagnostic["completeness"]
    downstream = [name for name in DOWNSTREAM_STATEMENTS if not completeness[name]]
    if any(not finding["repairable_by_model"] for finding in diagnostic["findings"]):
        return result(ACTION_HOST_SIDE, downstream=downstream)
    reasons = []
    if not completeness["observed_blockers_located"]:
        reasons.append(REASON_UNLOCATED)
    if not completeness["observed_blockers_attributed"]:
        reasons.append(REASON_UNATTRIBUTED)
    return result(ACTION_PARTIAL if reasons else ACTION_ACTIONABLE, reasons, downstream)


def repair_decision(actionability: Mapping[str, Any], *, partially_described_policy: str) -> str:
    """REPAIR or NO_REPAIR. The policy for a partially described diagnostic must be stated by the caller."""
    if partially_described_policy not in PARTIAL_POLICIES:
        raise P41RuntimeProtocolError("The policy for a partially described diagnostic must be stated explicitly")
    name = actionability.get("class") if isinstance(actionability, Mapping) else None
    if name not in ACTIONABILITY_CLASSES:
        raise P41RuntimeProtocolError("Repair actionability class is not a protocol value")
    if name == ACTION_ACTIONABLE:
        return DECISION_REPAIR
    if name == ACTION_PARTIAL and partially_described_policy == PARTIAL_POLICY_ALLOW:
        return DECISION_REPAIR
    return DECISION_NO_REPAIR


# ---------------------------------------------------------------------------
# Request builders
# ---------------------------------------------------------------------------

def _validate_case_id(case_id: Any) -> str:
    if not isinstance(case_id, str) or not _CASE_ID.fullmatch(case_id):
        raise P41RuntimeProtocolError("Case id is not a valid case identifier")
    return case_id


def _spec(job_id: str, system: str, user: str) -> DurableJobSpec:
    return DurableJobSpec(
        job_id=job_id,
        model=MODEL,
        system_prompt=system,
        user_prompt=user,
        generation_config=generation_config(),
        schema_response_mode=SCHEMA_RESPONSE_MODE,
        credential_slot=CREDENTIAL_SLOT,
        research_task_id=PROTOCOL_ID,
    )


def build_primary_spec(case_id: str, prepared_input: Mapping[str, Any]) -> DurableJobSpec:
    """The primary request: the P4.1 primary system prompt and the rendered user prompt."""
    _validate_case_id(case_id)
    try:
        user = candidate.render_primary_user(case_id, prepared_input)
    except candidate.P41ContractV11Error as error:
        raise P41RuntimeProtocolError("Primary request cannot be built") from error
    return _spec(PRIMARY_JOB_ID.format(CASE_ID=case_id), _prompt_material()["primary_system"], user)


def build_repair_spec(case_id: str, prepared_input: Mapping[str, Any], primary_response: str,
                      diagnostic: Mapping[str, Any], compiler_context: Any, *,
                      partially_described_policy: str) -> DurableJobSpec:
    """The single structural repair request.

    Refused unless the actionability rule decides REPAIR. The V1.1 repair contract rebuilds
    diagnostic V3.1 from the response and the context and compares it with the one given,
    so a diagnostic that was edited, or belongs to another response, is never rendered.
    """
    _validate_case_id(case_id)
    actionability = classify_repair_actionability(diagnostic, primary_response)
    if repair_decision(actionability, partially_described_policy=partially_described_policy) != DECISION_REPAIR:
        raise P41RuntimeProtocolError("Repair is not permitted for this diagnostic: " + actionability["class"])
    try:
        user = candidate.render_repair_user(case_id, prepared_input, primary_response, diagnostic, compiler_context)
    except candidate.P41ContractV11Error as error:
        raise P41RuntimeProtocolError("Repair request cannot be built") from error
    return _spec(REPAIR_JOB_ID.format(CASE_ID=case_id), _prompt_material()["repair_system"], user)


# ---------------------------------------------------------------------------
# Protocol checker
# ---------------------------------------------------------------------------

def _embedded_diagnostic(user_prompt: str) -> Any:
    """The diagnostic JSON a repair request carries. It is the last section of the V1.1 repair template."""
    template = _prompt_material()["repair_user_template"]
    before, after = template.split("{STRUCTURAL_DIAGNOSTIC_JSON}")
    marker = before.rsplit("\n\n", 1)[1]
    if not user_prompt.endswith(after) or marker not in user_prompt:
        raise P41RuntimeProtocolError("Repair request does not carry a structural diagnostic V3.1 section")
    body = user_prompt[: len(user_prompt) - len(after)]
    try:
        return json.loads(body[body.rindex(marker) + len(marker):])
    except ValueError as error:
        raise P41RuntimeProtocolError("Repair request diagnostic section is not one JSON value") from error


def assert_job_spec(spec: Any) -> None:
    """The protocol checker for one request. Every field must be exactly the proposed one."""
    if not isinstance(spec, DurableJobSpec):
        raise P41RuntimeProtocolError("A request must be a durable job specification")
    match = _JOB_ID.fullmatch(spec.job_id)
    if match is None:
        if _ANY_REPAIR_JOB.fullmatch(spec.job_id):
            raise P41RuntimeProtocolError("At most one structural repair is permitted per case")
        raise P41RuntimeProtocolError("Job id is not a P4.1 primary or single-repair job")
    case_id, phase = match.groups()
    if spec.research_task_id != PROTOCOL_ID:
        raise P41RuntimeProtocolError("The request belongs to another protocol")
    if spec.credential_slot != CREDENTIAL_SLOT:
        raise P41RuntimeProtocolError("Unexpected credential slot")
    if spec.model != MODEL or spec.schema_response_mode != SCHEMA_RESPONSE_MODE:
        raise P41RuntimeProtocolError("Model or response mode differs from the proposed settings")

    config = dict(spec.generation_config)
    if p4_contract.NATIVE_SCHEMA_PARAMETER not in config:
        raise P41RuntimeProtocolError("The native response schema is missing")
    native = config[p4_contract.NATIVE_SCHEMA_PARAMETER]
    if native == materializer.load_tracked_model_schema():
        raise P41RuntimeProtocolError("The full model schema must not be used as the native response schema")
    if not isinstance(native, dict) or sha256_text(projection.projection_text(native)) != PROVIDER_PROJECTION_SHA256:
        raise P41RuntimeProtocolError("Native response schema is not the exact accepted provider projection")
    if config != generation_config() or type(config.get("temperature")) is not int:
        raise P41RuntimeProtocolError("Generation settings differ from the proposed settings")

    material = _prompt_material()
    superseded = candidate.contract_v1.prompt_material()
    historical = p4_contract.prompt_material()
    expected_system = material["primary_system"] if phase == "PRIMARY" else material["repair_system"]
    if spec.system_prompt in (historical["primary_system"], historical["repair_system"]):
        raise P41RuntimeProtocolError("The request carries a P4 prompt, not the P4.1 prompt")
    if phase == "REPAIR_1" and spec.system_prompt == superseded["repair_system"]:
        raise P41RuntimeProtocolError("The request carries the repair prompt of the superseded candidate V1")
    if spec.system_prompt != expected_system:
        raise P41RuntimeProtocolError("System prompt differs from the P4.1 V1.1 prompt")
    in_prompt = p4_contract.extract_prompt_schema(
        spec.system_prompt, p4_contract.SCHEMA_SECTION_MARKER, p4_contract.REGISTRY_SECTION_MARKER)
    if in_prompt != materializer.load_tracked_model_schema():
        raise P41RuntimeProtocolError("The system prompt does not carry the complete model schema")

    if phase == "PRIMARY":
        if not spec.user_prompt.startswith(f"CASE {case_id}\n"):
            raise P41RuntimeProtocolError("Primary request does not belong to its case")
        return
    if not spec.user_prompt.startswith(f"STRUCTURAL REPAIR FOR {case_id}\n"):
        raise P41RuntimeProtocolError("Repair request does not belong to its case")
    if "STRUCTURAL_DIAGNOSTIC_V3_JSON:" in spec.user_prompt and "STRUCTURAL_DIAGNOSTIC_V3_1_JSON:" not in spec.user_prompt:
        raise P41RuntimeProtocolError("The request carries the superseded structural diagnostic V3")
    diagnostic = _embedded_diagnostic(spec.user_prompt)
    identity = diagnostic.get("diagnostic") if isinstance(diagnostic, dict) else None
    if identity in SUPERSEDED_DIAGNOSTIC_IDS:
        raise P41RuntimeProtocolError("The request carries a superseded structural diagnostic")
    if (
        not isinstance(diagnostic, dict)
        or set(diagnostic) != set(diagnostic_v3_1.ENVELOPE_FIELDS)
        or identity != ACTIVE_DIAGNOSTIC_ID
        or diagnostic["format"] != diagnostic_v3_1.DIAGNOSTIC_FORMAT
        or diagnostic["category"] not in REPAIR_ELIGIBLE_CATEGORIES
        or not diagnostic["findings"]
    ):
        raise P41RuntimeProtocolError("Repair request does not carry a structural diagnostic V3.1 of a rejected response")


def assert_request_identity(spec: Any, case_id: str, prepared_input: Mapping[str, Any], *,
                            primary_response: Optional[str] = None, diagnostic: Optional[Mapping[str, Any]] = None,
                            compiler_context: Any = None, partially_described_policy: Optional[str] = None) -> str:
    """The request is exactly the one the builders produce for these inputs. Returns its fingerprint."""
    assert_job_spec(spec)
    if primary_response is None:
        expected = build_primary_spec(case_id, prepared_input)
    else:
        expected = build_repair_spec(case_id, prepared_input, primary_response, diagnostic, compiler_context,
                                     partially_described_policy=partially_described_policy)
    if (spec.job_id, spec.request_fingerprint) != (expected.job_id, expected.request_fingerprint):
        raise P41RuntimeProtocolError("Request identity differs from the request the protocol builds")
    return expected.request_fingerprint


def main(argv: Optional[list[str]] = None) -> int:
    del argv
    try:
        locked_protocol()
    except P41RuntimeProtocolError as error:
        print(f"P4_1_RUNTIME_PROTOCOL_CANDIDATE_NOT_READY: {error}")
        return 2
    print(json.dumps({"protocol_id": PROTOCOL_ID, "protocol_sha256": PROTOCOL_SHA256, "standing": PROTOCOL_STANDING,
                      "provider_operations": 0, "status": "P4_1_RUNTIME_PROTOCOL_CANDIDATE_OFFLINE_GATES_PASS"},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
