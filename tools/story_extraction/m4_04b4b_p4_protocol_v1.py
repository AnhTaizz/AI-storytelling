"""P4 structural tuning protocol: exact runtime binding and request builders (M4-04B4B).

Binds the accepted P4 output contract to one model, one credential slot and the accepted
durable runtime. The model and runtime are those of P3, so a later tuning run isolates
the interface change. The one generation difference is the native response schema, which
is the tracked self-contained model schema and nothing else.

This module builds requests. It makes no provider call, loads no credential and reads no
dataset. It is not bound to DEV3 as a fresh benchmark.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from tools.story_extraction import m4_04b4a_p4_output_contract_v1 as contract
from tools.story_extraction import materialize_draft_v1_1_model_schema_v1 as materializer
from tools.story_extraction.durable_research_executor_v1 import (
    DURABLE_EXECUTOR_VERSION,
    GLOBAL_MAX_PROVIDER_OPERATIONS,
    GLOBAL_ROLLING_WINDOW_SECONDS,
    MAX_EXECUTION_WINDOWS_PER_JOB,
    MAX_PROVIDER_ATTEMPTS_PER_JOB,
    MAX_PROVIDER_ATTEMPTS_PER_WINDOW,
    DurableJobSpec,
)


REPO_ROOT = materializer.REPO_ROOT
TASK_ID = "M4-04B4B"
EXPECTED_BASE_COMMIT = "0b57d63e0f72b645e4a2bb9b41f3b13b0ea36a49"
PROTOCOL_ID = "M4_P4_STRUCTURAL_TUNING_PROTOCOL_V1"
PROTOCOL_SCHEMA_VERSION = "M4_P4_STRUCTURAL_TUNING_PROTOCOL_SCHEMA_V1"
# SHA-256 of canonical_json_bytes(build_protocol()). A changed binding is a new protocol.
PROTOCOL_SHA256 = "e0c74be45bcfd7cdca4111ff6029358e668b68f0a94fa94cf52718614f75279a"

EXTRACTOR_ID = contract.P4_EXTRACTOR_ID
MODEL = "gemini-3.5-flash-lite"
CREDENTIAL_SLOT = "gemini_slot_3"
TEMPERATURE = 0
MAX_OUTPUT_TOKENS = 16384
RESPONSE_MIME_TYPE = "application/json"
CONCURRENCY = 1
SCHEMA_RESPONSE_MODE = "PROVIDER_JSON_MIME_PLUS_NATIVE_RESPONSE_JSON_SCHEMA_V1"
RUNTIME_VERSION = "GEMINI_TRANSPORT_RESILIENCE_V1_1"
WINDOW_COOLDOWN_SECONDS = 60
MAX_STRUCTURAL_REPAIRS_PER_CASE = 1
REPAIR_ELIGIBLE_CATEGORIES = ("JSON_PARSE_FAILURE", "DRAFT_SCHEMA_FAILURE", "DRAFT_COMPILER_FAILURE")
EXECUTOR_PROTOCOL_ID_PREFIX = PROTOCOL_ID + ":"

MODEL_SCHEMA_SHA256 = "5aa2ed6dde3791546ddd5e059648d8dac38df1571a6073b7abc31c89eb257f14"
# Tracked files this protocol depends on. Hash mode: UTF8_LF_NORMALIZED_SHA256.
BOUND_FILES = {
    "schemas/story_extraction/story_extraction_draft_v1_1_model_schema_v1.schema.json": MODEL_SCHEMA_SHA256,
    "schemas/story_extraction/story_extraction_draft_v1_1.schema.json":
        "e0d38b65f0f265dfb1a0ef2be4e85c9b3950550a46f47e8980fbd6a7cab068a3",
    "schemas/story_extraction/story_extraction_draft_v1.schema.json":
        "7993db7bdce15e461a0483ec3e4bf5cf7596b49393fab477d9d25d61bd1f0f15",
    "schemas/canonical_story/predicate_registry_v0.yaml":
        "44f3eafc6982f84bcc74ccb91abe7cd467a453352ee96be147095f27559c5350",
    "tools/story_extraction/draft_compiler_v1_1.py":
        "f962e561a7801ddf48ef248416231673e1567b9eac9d04f2aaba1d1e16eed953",
    "tools/story_extraction/draft_compiler_v1.py":
        "281a2dfb5e99e67cc82b71798c09c93c04ab9682e8385a9cf6dfaf8393d69800",
    "tools/story_extraction/materialize_draft_v1_1_model_schema_v1.py":
        "4eba6f3c9907e9dca53586b8933587de6069ce248043d632e920dc47af1325dc",
    "tools/story_extraction/m4_04b4a_p4_output_contract_v1.py":
        "dba892456fdfd57211e8becedf1cd7296cb2b77c68885df9e5cf828379dcceec",
    "tools/story_extraction/prompts/story_extraction_draft_p4_v1_system.txt":
        "ff6dcfd8b31a6e9d75d6134f6393c19c3d1de582b5f2155986c9df38be20e035",
    "tools/story_extraction/prompts/story_extraction_draft_p4_v1_user.txt":
        "86336a230640f0ee96c41abcd6f15a160b313f3fb1bc6612cdaf0abb27b59b3e",
    "tools/story_extraction/prompts/story_extraction_draft_p4_v1_repair_user.txt":
        "7681338344525f1722a4a2d9351177734404f18945e105a1848bd60f4707b55b",
    "tools/story_extraction/gemini_resilience_v1_1.py":
        "8b84804f5c5b94e1b2ac2507d8b7bc39697b916bbdd889fc1f9040762bfc9213",
    "tools/story_extraction/durable_research_executor_v1.py":
        "cc9bd7a863ff906dea8fcd2f753c552881acd33f97a72b4af4e4e84eb1bfbe66",
    "tools/story_extraction/gemini_transport_v1.py":
        "0828c50bfb0b4b4b0ca6845aa1937af509637bc17c765f8bc1ab451255a307b5",
    "tools/story_extraction/gemini_errors_v1.py":
        "ee5dd06238233dce8a269a474d28c40ee2ed5171f1269fd6b96ed138645927d7",
    "tools/story_extraction/gemini_key_pool_v1.py":
        "77ab9238e322e493ebfdab223098052e74a73d7d0125c6a314b24e096bc690d0",
    "tools/story_extraction/run_m4_04b2_dev_predictions_v1.py":
        "0aaa275fe96bb8bcf0f10e2e0ca7b9e789f643e3d2a154ceeef532c4155a744d",
}

_CASE_ID = re.compile(r"^[A-Z][A-Z0-9_]{0,39}$")


class P4ProtocolError(RuntimeError):
    """The P4 protocol, a bound file or a job specification differs from the exact lock."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def normalized_file_sha256(path: Path) -> str:
    return sha256_text(path.read_text(encoding="utf-8").replace("\r\n", "\n"))


# ---------------------------------------------------------------------------
# Generation config and the single-source schema gate
# ---------------------------------------------------------------------------

def generation_config() -> dict[str, Any]:
    """The exact P4 generation settings, constructed from the accepted output contract."""
    config = contract.generation_config()
    if (
        set(config) != {"temperature", "max_output_tokens", contract.NATIVE_SCHEMA_PARAMETER}
        or config["temperature"] != TEMPERATURE
        or type(config["temperature"]) is not int
        or config["max_output_tokens"] != MAX_OUTPUT_TOKENS
        or config[contract.NATIVE_SCHEMA_PARAMETER] != materializer.load_tracked_model_schema()
    ):
        raise P4ProtocolError("Output contract generation settings differ from the P4 protocol")
    return config


def generation_config_sha256() -> str:
    return sha256_bytes(canonical_json_bytes(generation_config()))


def single_source_schema_gate() -> dict[str, str]:
    """Prove that one schema object is shown to the model and sent to the provider."""
    system = contract.prompt_material()["primary_system"]
    in_prompt = contract.extract_prompt_schema(
        system, contract.SCHEMA_SECTION_MARKER, contract.REGISTRY_SECTION_MARKER
    )
    native = generation_config()[contract.NATIVE_SCHEMA_PARAMETER]
    tracked = materializer.load_tracked_model_schema()
    produced = materializer.materialize_model_schema()
    if not (in_prompt == native == tracked == produced):
        raise P4ProtocolError("Prompt schema, native schema, tracked schema and materializer output differ")
    if materializer.model_schema_sha256() != MODEL_SCHEMA_SHA256:
        raise P4ProtocolError("Model schema hash differs from the P4 protocol")
    if materializer.external_refs(native):
        raise P4ProtocolError("Native response schema has an external reference")
    contract.assert_prompt_coverage(system)
    return {
        "prompt_schema_equals_native_schema": "PASS",
        "native_schema_equals_tracked_file": "PASS",
        "tracked_file_equals_materializer_output": "PASS",
        "model_schema_sha256": "PASS",
        "external_ref_count_zero": "PASS",
        "prompt_structural_coverage": "PASS",
    }


def prompt_hashes() -> dict[str, str]:
    material = contract.prompt_material()
    return {
        "primary_system_sha256": sha256_text(material["primary_system"]),
        "primary_user_template_sha256": sha256_text(material["primary_user_template"]),
        "primary_prompt_pair_sha256": sha256_text(material["primary_system"] + "\0" + material["primary_user_template"]),
        "repair_system_sha256": sha256_text(material["repair_system"]),
        "repair_user_template_sha256": sha256_text(material["repair_user_template"]),
        "repair_prompt_pair_sha256": sha256_text(material["repair_system"] + "\0" + material["repair_user_template"]),
    }


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

def build_protocol() -> dict[str, Any]:
    return {
        "protocol_id": PROTOCOL_ID,
        "protocol_schema_version": PROTOCOL_SCHEMA_VERSION,
        "task_id": TASK_ID,
        "base_commit": EXPECTED_BASE_COMMIT,
        "candidate": {
            "extractor_id": EXTRACTOR_ID,
            "canonical_draft_contract": materializer.CANONICAL_DRAFT_VERSION,
            "model_schema_identity": materializer.MODEL_SCHEMA_IDENTITY,
            "model_schema_sha256": MODEL_SCHEMA_SHA256,
        },
        "generation": {
            "model": MODEL,
            "credential_slot": CREDENTIAL_SLOT,
            "temperature": TEMPERATURE,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "response_mime_type": RESPONSE_MIME_TYPE,
            "native_schema_enabled": True,
            "native_schema_parameter": contract.NATIVE_SCHEMA_PARAMETER,
            "native_schema_sha256": MODEL_SCHEMA_SHA256,
            "generation_config_sha256": generation_config_sha256(),
            "schema_response_mode": SCHEMA_RESPONSE_MODE,
            "concurrency": CONCURRENCY,
            "seed": "NOT_SUPPORTED_NOT_USED",
            "difference_from_p3": "NATIVE_RESPONSE_JSON_SCHEMA_ONLY",
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
            "same_native_schema_and_generation_settings": True,
            "quality_signal": "FORBIDDEN",
            "missing_fact_or_coverage_retry": "FORBIDDEN",
            "gold_signal": "FORBIDDEN",
            "semantic_reinterpretation": "FORBIDDEN",
            "repair_failure_is_terminal": True,
        },
        "request_construction": {
            "primary_job_id_pattern": "M4B4B_P4_{CASE_ID}_PRIMARY",
            "repair_job_id_pattern": "M4B4B_P4_{CASE_ID}_REPAIR_1",
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
            raise P4ProtocolError("Bound file is unavailable: " + relative) from error
        if actual != expected:
            raise P4ProtocolError("Bound file mismatch: " + relative)
    return {"bound_files": "PASS", "bound_file_count": str(len(BOUND_FILES))}


def locked_protocol() -> dict[str, Any]:
    """Return the protocol only while every binding is exactly the locked one."""
    validate_bound_files()
    single_source_schema_gate()
    protocol = build_protocol()
    if sha256_bytes(canonical_json_bytes(protocol)) != PROTOCOL_SHA256:
        raise P4ProtocolError("P4 protocol differs from the locked protocol")
    return protocol


def executor_protocol_id() -> str:
    """Identity stamped into every durable checkpoint of this protocol."""
    return EXECUTOR_PROTOCOL_ID_PREFIX + PROTOCOL_SHA256


# ---------------------------------------------------------------------------
# Request builders and the P4 job-spec checker
# ---------------------------------------------------------------------------

def _validate_case_id(case_id: Any) -> str:
    if not isinstance(case_id, str) or not _CASE_ID.fullmatch(case_id):
        raise P4ProtocolError("Case id is not a valid P4 case identifier")
    return case_id


def build_primary_spec(case_id: str, prepared_input: Mapping[str, Any]) -> DurableJobSpec:
    _validate_case_id(case_id)
    material = contract.prompt_material()
    try:
        user = contract.render_primary_user(case_id, prepared_input)
    except contract.OutputContractError as error:
        raise P4ProtocolError("Primary request cannot be built") from error
    return DurableJobSpec(
        job_id=f"M4B4B_P4_{case_id}_PRIMARY",
        model=MODEL,
        system_prompt=material["primary_system"],
        user_prompt=user,
        generation_config=generation_config(),
        schema_response_mode=SCHEMA_RESPONSE_MODE,
        credential_slot=CREDENTIAL_SLOT,
        research_task_id=PROTOCOL_ID,
    )


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
        raise P4ProtocolError("Repair requires a structural diagnostic V2 with an eligible category")
    material = contract.prompt_material()
    try:
        user = contract.render_repair_user(case_id, prepared_input, primary_response, diagnostic)
    except contract.OutputContractError as error:
        raise P4ProtocolError("Repair request cannot be built") from error
    return DurableJobSpec(
        job_id=f"M4B4B_P4_{case_id}_REPAIR_1",
        model=MODEL,
        system_prompt=material["repair_system"],
        user_prompt=user,
        generation_config=generation_config(),
        schema_response_mode=SCHEMA_RESPONSE_MODE,
        credential_slot=CREDENTIAL_SLOT,
        research_task_id=PROTOCOL_ID,
    )


def assert_locked_job_spec(spec: DurableJobSpec) -> None:
    """The P4 job-spec checker. Every field of a request must be exactly the locked one."""
    material = contract.prompt_material()
    match = re.fullmatch(r"M4B4B_P4_([A-Z][A-Z0-9_]{0,39}?)_(PRIMARY|REPAIR_1)", spec.job_id)
    if match is None:
        raise P4ProtocolError("Job id is not a P4 primary or single-repair job")
    expected_system = material["primary_system"] if match.group(2) == "PRIMARY" else material["repair_system"]
    config = dict(spec.generation_config)
    if contract.NATIVE_SCHEMA_PARAMETER not in config:
        raise P4ProtocolError("Native response schema is mandatory for P4")
    if config != generation_config() or type(config.get("temperature")) is not int:
        raise P4ProtocolError("Generation settings or native response schema differ from P4")
    if spec.system_prompt != expected_system:
        raise P4ProtocolError("System prompt differs from the locked P4 prompt")
    if (
        spec.model != MODEL
        or spec.credential_slot != CREDENTIAL_SLOT
        or spec.schema_response_mode != SCHEMA_RESPONSE_MODE
        or spec.research_task_id != PROTOCOL_ID
    ):
        raise P4ProtocolError("Model, credential or response mode differs from P4")
