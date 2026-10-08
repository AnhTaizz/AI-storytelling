"""P4 structural tuning protocol V2: provider projection as the native schema (M4-04B4BR).

Protocol V1 sent the full model schema as the native response schema and the provider
rejected the request. V2 changes one thing: the native response schema is the
deterministic provider projection of the full model schema.

    prompt schema  == full model schema
    native schema  == provider_projection(full model schema)

The model-facing contract is unchanged, so the extractor identity is unchanged. The
prompt still carries every validator rule and the unchanged local validator stays
authoritative. Only the provider's output-shaping constraint is weaker.

Protocol V1 is historical and is not edited. This module builds requests. It makes no
provider call, loads no credential and reads no dataset.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from tools.story_extraction import m4_04b4a_p4_output_contract_v1 as contract
from tools.story_extraction import m4_04b4b_p4_protocol_v1 as protocol_v1
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
TASK_ID = "M4-04B4BR"
EXPECTED_BASE_COMMIT = "057c0dc9edd97a5b5650c3ba6207ecee6741d2cc"
PROTOCOL_ID = "M4_P4_STRUCTURAL_TUNING_PROTOCOL_V2"
PROTOCOL_SCHEMA_VERSION = "M4_P4_STRUCTURAL_TUNING_PROTOCOL_SCHEMA_V2"
SUPERSEDES_PROTOCOL_ID = protocol_v1.PROTOCOL_ID
SUPERSEDES_PROTOCOL_SHA256 = "e0c74be45bcfd7cdca4111ff6029358e668b68f0a94fa94cf52718614f75279a"
# SHA-256 of canonical_json_bytes(build_protocol()). A changed binding is a new protocol.
PROTOCOL_SHA256 = "24b2af927e07078da3a06fe329aa5378cdde92675e76e92e2c03d9ad82726025"

EXTRACTOR_ID = contract.P4_EXTRACTOR_ID
MODEL = "gemini-3.5-flash-lite"
CREDENTIAL_SLOT = "gemini_slot_3"
TEMPERATURE = 0
MAX_OUTPUT_TOKENS = 16384
RESPONSE_MIME_TYPE = "application/json"
CONCURRENCY = 1
SCHEMA_RESPONSE_MODE = "PROVIDER_JSON_MIME_PLUS_NATIVE_PROVIDER_PROJECTION_SCHEMA_V2"
RUNTIME_VERSION = "GEMINI_TRANSPORT_RESILIENCE_V1_1"
WINDOW_COOLDOWN_SECONDS = 60
MAX_STRUCTURAL_REPAIRS_PER_CASE = 1
REPAIR_ELIGIBLE_CATEGORIES = ("JSON_PARSE_FAILURE", "DRAFT_SCHEMA_FAILURE", "DRAFT_COMPILER_FAILURE")
EXECUTOR_PROTOCOL_ID_PREFIX = PROTOCOL_ID + ":"

FULL_MODEL_SCHEMA_SHA256 = "5aa2ed6dde3791546ddd5e059648d8dac38df1571a6073b7abc31c89eb257f14"
PROVIDER_PROJECTION_SHA256 = "89506defa4089b1449f7c80bbcf782d94065802ceae71aa86e1598a5a17ab9bd"
# Everything protocol V1 bound, plus V1 itself and the projection. UTF8_LF_NORMALIZED_SHA256.
BOUND_FILES = {
    **protocol_v1.BOUND_FILES,
    "tools/story_extraction/m4_04b4b_p4_protocol_v1.py":
        "513824f4c9c6f5208c73dd5d54c388f0d2577858570c8177551f6e0fda540a4b",
    "tools/story_extraction/project_draft_v1_1_model_schema_to_gemini_v1.py":
        "3fcfd71c9129ecac6de7e1d5341911073dad5326a74ed60741733c1808d6a5c5",
    "schemas/story_extraction/story_extraction_draft_v1_1_gemini_response_schema_v1.schema.json":
        PROVIDER_PROJECTION_SHA256,
    "benchmarks/m4_extraction/M4_04B4BR_PROVIDER_SCHEMA_PROJECTION_MANIFEST.json":
        "bf475e6c0c557ec8e5f6a40af94e1875f420d073fa29963f82c3741286793760",
}

_CASE_ID = re.compile(r"^[A-Z][A-Z0-9_]{0,39}$")
_JOB_ID = re.compile(r"M4B4BR_P4V2_([A-Z][A-Z0-9_]{0,39}?)_(PRIMARY|REPAIR_1)")


class P4ProtocolV2Error(RuntimeError):
    """Protocol V2, a bound file or a job specification differs from the exact lock."""


# ---------------------------------------------------------------------------
# Generation config and the schema lineage gate
# ---------------------------------------------------------------------------

def native_response_schema() -> dict[str, Any]:
    """The exact provider projection. Never the full model schema."""
    try:
        schema = projection.load_tracked_projection()
    except projection.ProjectionError as error:
        raise P4ProtocolV2Error("Provider projection is unavailable or not the locked projection") from error
    if sha256_text(projection.projection_text(schema)) != PROVIDER_PROJECTION_SHA256:
        raise P4ProtocolV2Error("Provider projection hash differs from protocol V2")
    return schema


def generation_config() -> dict[str, Any]:
    """Protocol V1 generation settings with the native schema replaced by the projection."""
    base = contract.generation_config()
    if (
        set(base) != {"temperature", "max_output_tokens", contract.NATIVE_SCHEMA_PARAMETER}
        or base["temperature"] != TEMPERATURE
        or type(base["temperature"]) is not int
        or base["max_output_tokens"] != MAX_OUTPUT_TOKENS
    ):
        raise P4ProtocolV2Error("Output contract generation settings differ from protocol V2")
    return {
        "temperature": base["temperature"],
        "max_output_tokens": base["max_output_tokens"],
        contract.NATIVE_SCHEMA_PARAMETER: native_response_schema(),
    }


def generation_config_sha256() -> str:
    return sha256_bytes(canonical_json_bytes(generation_config()))


def schema_lineage_gate() -> dict[str, str]:
    """Prompt schema is the full model schema; native schema is its projection and nothing else."""
    system = contract.prompt_material()["primary_system"]
    in_prompt = contract.extract_prompt_schema(
        system, contract.SCHEMA_SECTION_MARKER, contract.REGISTRY_SECTION_MARKER
    )
    full = materializer.load_tracked_model_schema()
    native = generation_config()[contract.NATIVE_SCHEMA_PARAMETER]
    if not (in_prompt == full == materializer.materialize_model_schema()):
        raise P4ProtocolV2Error("Prompt schema is not the full model schema")
    if materializer.model_schema_sha256() != FULL_MODEL_SCHEMA_SHA256:
        raise P4ProtocolV2Error("Full model schema hash differs from protocol V2")
    if native == full or native == in_prompt:
        raise P4ProtocolV2Error("Native schema must be the provider projection, not the full model schema")
    if native != projection.project(full)[0]:
        raise P4ProtocolV2Error("Native schema is not the projection of the full model schema")
    try:
        projection.lineage_gate()
    except (projection.ProjectionError, materializer.ModelSchemaError) as error:
        raise P4ProtocolV2Error("Provider projection lineage gate failed") from error
    if materializer.external_refs(native):
        raise P4ProtocolV2Error("Native response schema has an external reference")
    contract.assert_prompt_coverage(system)
    return {
        "prompt_schema_equals_full_model_schema": "PASS",
        "full_model_schema_equals_materializer_output": "PASS",
        "full_model_schema_sha256": "PASS",
        "native_schema_equals_tracked_provider_projection": "PASS",
        "native_schema_equals_projection_of_full_model_schema": "PASS",
        "native_schema_differs_from_full_model_schema": "PASS",
        "provider_projection_sha256": "PASS",
        "provider_projection_is_relaxation_by_construction": "PASS",
        "external_ref_count_zero": "PASS",
        "prompt_structural_coverage": "PASS",
    }


def prompt_hashes() -> dict[str, str]:
    """Identical to protocol V1: the prompts are unchanged."""
    return protocol_v1.prompt_hashes()


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

def build_protocol() -> dict[str, Any]:
    return {
        "protocol_id": PROTOCOL_ID,
        "protocol_schema_version": PROTOCOL_SCHEMA_VERSION,
        "task_id": TASK_ID,
        "base_commit": EXPECTED_BASE_COMMIT,
        "supersedes": {
            "protocol_id": SUPERSEDES_PROTOCOL_ID,
            "protocol_sha256": SUPERSEDES_PROTOCOL_SHA256,
            "reason": "PROVIDER_REJECTED_FULL_MODEL_SCHEMA_AS_NATIVE_RESPONSE_SCHEMA",
            "change": "PROVIDER_OUTPUT_SHAPING_CONSTRAINT_ONLY",
        },
        "candidate": {
            "extractor_id": EXTRACTOR_ID,
            "extractor_identity_changed": False,
            "canonical_draft_contract": materializer.CANONICAL_DRAFT_VERSION,
            "model_schema_identity": materializer.MODEL_SCHEMA_IDENTITY,
            "model_schema_sha256": FULL_MODEL_SCHEMA_SHA256,
        },
        "schema_roles": {
            "prompt_schema": materializer.MODEL_SCHEMA_IDENTITY,
            "prompt_schema_sha256": FULL_MODEL_SCHEMA_SHA256,
            "native_schema": projection.PROJECTION_IDENTITY,
            "native_schema_sha256": PROVIDER_PROJECTION_SHA256,
            "native_schema_derivation": projection.PROJECTION_TOOL_ID,
            "native_schema_is_weaker_than_prompt_schema": True,
            "authoritative_validator": "UNCHANGED_LOCAL_DRAFT_V1_1_VALIDATOR",
            "native_schema_role": "OUTPUT_SHAPING_AID_ONLY",
        },
        "generation": {
            "model": MODEL,
            "credential_slot": CREDENTIAL_SLOT,
            "temperature": TEMPERATURE,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "response_mime_type": RESPONSE_MIME_TYPE,
            "native_schema_enabled": True,
            "native_schema_parameter": contract.NATIVE_SCHEMA_PARAMETER,
            "native_schema_sha256": PROVIDER_PROJECTION_SHA256,
            "generation_config_sha256": generation_config_sha256(),
            "schema_response_mode": SCHEMA_RESPONSE_MODE,
            "concurrency": CONCURRENCY,
            "seed": "NOT_SUPPORTED_NOT_USED",
            "difference_from_protocol_v1": "NATIVE_RESPONSE_JSON_SCHEMA_IS_THE_PROVIDER_PROJECTION",
        },
        "prompt_hashes": prompt_hashes(),
        "bound_files": dict(BOUND_FILES),
        "bound_file_hash_mode": "UTF8_LF_NORMALIZED_SHA256",
        "compilation": {
            "validator": "tools.story_extraction.draft_compiler_v1_1.validate_draft_v1_1",
            "compiler": "tools.story_extraction.draft_compiler_v1_1.compile_story_extraction_draft_v1_1",
            "new_canonical_compiler": False,
            "semantic_translation_layer": False,
        },
        "durable_execution": {
            "runtime": RUNTIME_VERSION,
            "durable_executor": DURABLE_EXECUTOR_VERSION,
            "transport": "GeminiDevWindowTransport",
            "pacer": "PersistentRollingOperationPacer",
            "maximum_windows_per_job": MAX_EXECUTION_WINDOWS_PER_JOB,
            "maximum_provider_attempts_per_window": MAX_PROVIDER_ATTEMPTS_PER_WINDOW,
            "maximum_provider_attempts_per_job": MAX_PROVIDER_ATTEMPTS_PER_JOB,
            "global_pacing_max_operations": GLOBAL_MAX_PROVIDER_OPERATIONS,
            "global_pacing_rolling_window_seconds": GLOBAL_ROLLING_WINDOW_SECONDS,
            "window_cooldown_seconds": WINDOW_COOLDOWN_SECONDS,
            "first_success": "IMMUTABLE_LOCK",
            "output_aware_transport_retry": "FORBIDDEN",
            "model_switch": "FORBIDDEN",
            "credential_switch": "FORBIDDEN",
        },
        "repair_policy": {
            "diagnostic": contract.REPAIR_DIAGNOSTIC_ID,
            "maximum_per_case": MAX_STRUCTURAL_REPAIRS_PER_CASE,
            "eligible_primary_failure_categories": list(REPAIR_ELIGIBLE_CATEGORIES),
            "eligible_only_after_successful_primary_response": True,
            "repair_receives": ["PREPARED_INPUT", "PRIMARY_RESPONSE", "STRUCTURAL_DIAGNOSTIC_V2"],
            "diagnostic_is_computed_from": "FULL_MODEL_SCHEMA_AND_COMPILER_NOT_THE_PROVIDER_PROJECTION",
            "same_native_schema_and_generation_settings": True,
            "quality_signal": "FORBIDDEN",
            "missing_fact_or_coverage_retry": "FORBIDDEN",
            "gold_signal": "FORBIDDEN",
            "semantic_reinterpretation": "FORBIDDEN",
            "repair_failure_is_terminal": True,
        },
        "request_construction": {
            "primary_job_id_pattern": "M4B4BR_P4V2_{CASE_ID}_PRIMARY",
            "repair_job_id_pattern": "M4B4BR_P4V2_{CASE_ID}_REPAIR_1",
            "input": "HOST_PREPARED_DRAFT_V1_1_INPUT_ONLY",
        },
        "data": {
            "bound_to_a_fresh_benchmark": False,
            "DEV3_status": "TUNING_DATA_AFTER_P3_FAILURE",
            "DEV3_gold": "FORBIDDEN",
            "holdout": "FORBIDDEN",
        },
    }


def protocol_sha256() -> str:
    return sha256_bytes(canonical_json_bytes(build_protocol()))


def validate_bound_files() -> dict[str, str]:
    for relative, expected in BOUND_FILES.items():
        try:
            actual = normalized_file_sha256(REPO_ROOT / relative)
        except (OSError, UnicodeError) as error:
            raise P4ProtocolV2Error("Bound file is unavailable: " + relative) from error
        if actual != expected:
            raise P4ProtocolV2Error("Bound file mismatch: " + relative)
    return {"bound_files": "PASS", "bound_file_count": str(len(BOUND_FILES))}


def locked_protocol() -> dict[str, Any]:
    """Return the protocol only while every binding is exactly the locked one."""
    validate_bound_files()
    if protocol_v1.protocol_sha256() != SUPERSEDES_PROTOCOL_SHA256:
        raise P4ProtocolV2Error("Historical protocol V1 changed")
    schema_lineage_gate()
    protocol = build_protocol()
    if sha256_bytes(canonical_json_bytes(protocol)) != PROTOCOL_SHA256:
        raise P4ProtocolV2Error("P4 protocol differs from the locked protocol V2")
    return protocol


def executor_protocol_id() -> str:
    """Identity stamped into every durable checkpoint of this protocol."""
    return EXECUTOR_PROTOCOL_ID_PREFIX + PROTOCOL_SHA256


# ---------------------------------------------------------------------------
# Request builders and the V2 job-spec checker
# ---------------------------------------------------------------------------

def _validate_case_id(case_id: Any) -> str:
    if not isinstance(case_id, str) or not _CASE_ID.fullmatch(case_id):
        raise P4ProtocolV2Error("Case id is not a valid P4 case identifier")
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
    _validate_case_id(case_id)
    try:
        user = contract.render_primary_user(case_id, prepared_input)
    except contract.OutputContractError as error:
        raise P4ProtocolV2Error("Primary request cannot be built") from error
    return _spec(f"M4B4BR_P4V2_{case_id}_PRIMARY", contract.prompt_material()["primary_system"], user)


def build_repair_spec(
    case_id: str,
    prepared_input: Mapping[str, Any],
    primary_response: str,
    diagnostic: Mapping[str, Any],
) -> DurableJobSpec:
    _validate_case_id(case_id)
    if (
        not isinstance(diagnostic, Mapping)
        or diagnostic.get("diagnostic") != contract.REPAIR_DIAGNOSTIC_ID
        or diagnostic.get("category") not in REPAIR_ELIGIBLE_CATEGORIES
        or not diagnostic.get("findings")
    ):
        raise P4ProtocolV2Error("Repair requires a structural diagnostic V2 with an eligible category")
    try:
        user = contract.render_repair_user(case_id, prepared_input, primary_response, diagnostic)
    except contract.OutputContractError as error:
        raise P4ProtocolV2Error("Repair request cannot be built") from error
    return _spec(f"M4B4BR_P4V2_{case_id}_REPAIR_1", contract.prompt_material()["repair_system"], user)


def assert_locked_job_spec(spec: DurableJobSpec) -> None:
    """The V2 job-spec checker. The native schema must be the exact provider projection."""
    material = contract.prompt_material()
    match = _JOB_ID.fullmatch(spec.job_id)
    if match is None:
        raise P4ProtocolV2Error("Job id is not a protocol V2 primary or single-repair job")
    expected_system = material["primary_system"] if match.group(2) == "PRIMARY" else material["repair_system"]
    config = dict(spec.generation_config)
    if contract.NATIVE_SCHEMA_PARAMETER not in config:
        raise P4ProtocolV2Error("Native response schema is mandatory for protocol V2")
    native = config[contract.NATIVE_SCHEMA_PARAMETER]
    if native == materializer.load_tracked_model_schema():
        raise P4ProtocolV2Error("The full model schema must not be used as the native response schema")
    if not isinstance(native, dict) or sha256_text(projection.projection_text(native)) != PROVIDER_PROJECTION_SHA256:
        raise P4ProtocolV2Error("Native response schema is not the exact provider projection")
    if config != generation_config() or type(config.get("temperature")) is not int:
        raise P4ProtocolV2Error("Generation settings differ from protocol V2")
    if spec.system_prompt != expected_system:
        raise P4ProtocolV2Error("System prompt differs from the locked P4 prompt")
    if (
        spec.model != MODEL
        or spec.credential_slot != CREDENTIAL_SLOT
        or spec.schema_response_mode != SCHEMA_RESPONSE_MODE
        or spec.research_task_id != PROTOCOL_ID
    ):
        raise P4ProtocolV2Error("Model, credential or response mode differs from protocol V2")
