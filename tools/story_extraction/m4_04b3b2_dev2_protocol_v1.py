"""Exact offline lock for the M4-04B3B2 P2 DEV2 draft extractor.

This module materializes prompts and request identities and validates a canonical
private protocol.  It never opens DEV2, loads credentials, constructs a transport,
or performs provider work.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import yaml

from tools.story_extraction.durable_research_executor_v1 import DurableJobSpec


REPO_ROOT = Path(__file__).resolve().parents[2]
TASK_ID = "M4-04B3B2-LOCK-DRAFT-EXTRACTOR-AND-DEV2-BENCHMARK-PROTOCOL"
EXPECTED_BASE_COMMIT = "eb8fd511b878bb3ac899c88bfd8d05d3532ac139"
PROTOCOL_ID = "M4_04B3B2_DEV2_BENCHMARK_PROTOCOL_V1"
PROTOCOL_SCHEMA_VERSION = "M4_04B3B2_DEV2_BENCHMARK_PROTOCOL_SCHEMA_V1"
EXTRACTOR_ID = "P2_STORY_EXTRACTION_DRAFT_V1_GEMINI_3_5_FLASH_LITE_V1"

DEV2_INPUT_SHA256 = "e63937252e69820ff6f4b097537f860524ea9937e1e0bbd7187f2ae52cd812d5"
DEV2_GOLD_SHA256 = "77b9655b92b09c5b2c0d0ce749432ae12da342bbf07d62a01b16b37b1fce9939"
CASE_IDS = tuple(f"DEV2_{index:02d}" for index in range(1, 11))

MODEL = "gemini-3.5-flash-lite"
CREDENTIAL_SLOT = "gemini_slot_3"
CREDENTIAL_TOPOLOGY = "UNKNOWN"
TEMPERATURE = 0
MAX_OUTPUT_TOKENS = 16384
CONCURRENCY = 1
SCHEMA_RESPONSE_MODE = "PROVIDER_JSON_MIME_STORY_EXTRACTION_DRAFT_V1"

DURABLE_PROFILE_ID = "M4_DURABLE_RESEARCH_EXECUTION_PROFILE_V1"
DURABLE_PROFILE_SHA256 = "c6c789f0f06d3fdabc2333c29b389252de853ffef0add536d4f06fb6b94e143e"
RUNTIME_VERSION = "GEMINI_TRANSPORT_RESILIENCE_V1_1"
RUNTIME_SHA256 = "8b84804f5c5b94e1b2ac2507d8b7bc39697b916bbdd889fc1f9040762bfc9213"
DURABLE_EXECUTOR_VERSION = "DURABLE_RESEARCH_EXECUTOR_V1"
DURABLE_EXECUTOR_SHA256 = "cc9bd7a863ff906dea8fcd2f753c552881acd33f97a72b4af4e4e84eb1bfbe66"
MAX_WINDOWS_PER_JOB = 3
MAX_PROVIDER_ATTEMPTS_PER_WINDOW = 3
MAX_PROVIDER_ATTEMPTS_PER_JOB = 9
GLOBAL_MAX_PROVIDER_OPERATIONS = 6
GLOBAL_ROLLING_WINDOW_SECONDS = 60
WINDOW_COOLDOWN_SECONDS = 60

DRAFT_VERSION = "STORY_EXTRACTION_DRAFT_V1"
DRAFT_SCHEMA_PATH = REPO_ROOT / "schemas/story_extraction/story_extraction_draft_v1.schema.json"
DRAFT_SCHEMA_SHA256 = "498edf8dba8d45b80380a180d1383787f5c0e4ecea5060254883cc27c7d83e80"
COMPILER_PATH = REPO_ROOT / "tools/story_extraction/draft_compiler_v1.py"
COMPILER_SHA256 = "bcd15328cefafe86dd8e686fb35a155b2cb2c261b20017486ed106e85371d836"
PREDICATE_REGISTRY_PATH = REPO_ROOT / "schemas/canonical_story/predicate_registry_v0.yaml"
PREDICATE_REGISTRY_SHA256 = "44f3eafc6982f84bcc74ccb91abe7cd467a453352ee96be147095f27559c5350"
SNAPSHOT_V2_PATH = REPO_ROOT / "benchmarks/m4_extraction/M4_EVALUATION_PROTOCOL_SNAPSHOT_V2.yaml"
SNAPSHOT_V2_ID = "M4_EVALUATION_PROTOCOL_SNAPSHOT_V2"
SNAPSHOT_V2_SHA256 = "8dddbd0b9f3ea51af593c1fab0631b088b6f4e6b8c16833a1f11b8448088eee9"
SNAPSHOT_V2_FILE_SHA256 = "eef2db2ff2ba61f22a96d3a52ab64e07c6c9e9dbc9e9741e061f2893ba6283a8"

PROMPT_ROOT = REPO_ROOT / "tools/story_extraction/prompts"
SYSTEM_PREAMBLE_PATH = PROMPT_ROOT / "story_extraction_draft_p2_system_v1.txt"
USER_TEMPLATE_PATH = PROMPT_ROOT / "story_extraction_draft_p2_user_v1.txt"
REPAIR_USER_TEMPLATE_PATH = PROMPT_ROOT / "story_extraction_draft_p2_repair_user_v1.txt"
REPAIR_SYSTEM_SUFFIX = """

STRUCTURAL REPAIR MODE
Repair only the sanitized deterministic failure supplied by the host. Preserve semantic
choices from the primary response. Do not fill coverage gaps, optimize quality, consult
gold, or introduce a new interpretation. This is the only repair allowed for the case.
""".strip()

REPAIR_ELIGIBLE_CATEGORIES = (
    "JSON_PARSE_FAILURE",
    "DRAFT_SCHEMA_FAILURE",
    "DRAFT_COMPILER_FAILURE",
)
MAX_STRUCTURAL_REPAIRS_PER_CASE = 1


class Dev2ProtocolError(RuntimeError):
    """The protocol or its public bindings differ from the exact lock."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _normalized_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").rstrip()


def prompt_material() -> dict[str, str]:
    """Build exact P2 prompts only from tracked public files."""
    preamble = _normalized_text(SYSTEM_PREAMBLE_PATH)
    draft_schema = _normalized_text(DRAFT_SCHEMA_PATH)
    registry = _normalized_text(PREDICATE_REGISTRY_PATH)
    system = (
        preamble
        + "\n\nEXACT STORY_EXTRACTION_DRAFT_V1 JSON SCHEMA:\n"
        + draft_schema
        + "\n\nEXACT PREDICATE REGISTRY:\n"
        + registry
    )
    return {
        "primary_system": system,
        "primary_user_template": _normalized_text(USER_TEMPLATE_PATH) + "\n",
        "repair_system": system + "\n\n" + REPAIR_SYSTEM_SUFFIX,
        "repair_user_template": _normalized_text(REPAIR_USER_TEMPLATE_PATH) + "\n",
    }


def prompt_hashes() -> dict[str, str]:
    material = prompt_material()
    return {
        "primary_system_sha256": sha256_text(material["primary_system"]),
        "primary_user_template_sha256": sha256_text(material["primary_user_template"]),
        "primary_prompt_pair_sha256": sha256_text(
            material["primary_system"] + "\0" + material["primary_user_template"]
        ),
        "repair_system_sha256": sha256_text(material["repair_system"]),
        "repair_user_template_sha256": sha256_text(material["repair_user_template"]),
        "repair_prompt_pair_sha256": sha256_text(
            material["repair_system"] + "\0" + material["repair_user_template"]
        ),
    }


def _render(template: str, replacements: Mapping[str, str]) -> str:
    rendered = template
    for key, value in replacements.items():
        marker = "{" + key + "}"
        if marker not in rendered:
            raise Dev2ProtocolError("Prompt template marker missing: " + marker)
        rendered = rendered.replace(marker, value)
    if any(marker in rendered for marker in ("{CASE_ID}", "{PREPARED_INPUT_JSON}",
                                               "{PRIMARY_RESPONSE}", "{FAILURE_JSON}")):
        raise Dev2ProtocolError("Prompt template has unresolved markers")
    return rendered


def primary_user_prompt(case_id: str, prepared_input: Mapping[str, Any]) -> str:
    if case_id not in CASE_IDS:
        raise Dev2ProtocolError("Unknown DEV2 case id")
    if prepared_input.get("draft_version") != DRAFT_VERSION:
        raise Dev2ProtocolError("Prepared input is not Draft V1")
    template = prompt_material()["primary_user_template"]
    return _render(template, {
        "CASE_ID": case_id,
        "PREPARED_INPUT_JSON": canonical_json_bytes(prepared_input).decode("utf-8").rstrip(),
    })


def build_primary_spec(case_id: str, prepared_input: Mapping[str, Any]) -> DurableJobSpec:
    material = prompt_material()
    return DurableJobSpec(
        job_id=f"M4B3B2_P2_{case_id}_PRIMARY",
        model=MODEL,
        system_prompt=material["primary_system"],
        user_prompt=primary_user_prompt(case_id, prepared_input),
        generation_config={"temperature": TEMPERATURE, "max_output_tokens": MAX_OUTPUT_TOKENS},
        schema_response_mode=SCHEMA_RESPONSE_MODE,
        credential_slot=CREDENTIAL_SLOT,
        research_task_id=TASK_ID,
    )


def build_repair_spec(case_id: str, prepared_input: Mapping[str, Any], primary_response: str,
                      failure: Mapping[str, Any]) -> DurableJobSpec:
    category = failure.get("category")
    if category not in REPAIR_ELIGIBLE_CATEGORIES:
        raise Dev2ProtocolError("Repair category is not eligible")
    if any(key in failure for key in ("gold", "score", "quality", "missing_assertions")):
        raise Dev2ProtocolError("Repair failure payload contains a forbidden quality/gold signal")
    if not isinstance(primary_response, str) or not primary_response:
        raise Dev2ProtocolError("Repair requires one successful primary response")
    if case_id not in CASE_IDS or prepared_input.get("draft_version") != DRAFT_VERSION:
        raise Dev2ProtocolError("Invalid repair case/input identity")
    material = prompt_material()
    user = _render(material["repair_user_template"], {
        "CASE_ID": case_id,
        "PREPARED_INPUT_JSON": canonical_json_bytes(prepared_input).decode("utf-8").rstrip(),
        "PRIMARY_RESPONSE": primary_response,
        "FAILURE_JSON": canonical_json_bytes(dict(failure)).decode("utf-8").rstrip(),
    })
    return DurableJobSpec(
        job_id=f"M4B3B2_P2_{case_id}_REPAIR_1",
        model=MODEL,
        system_prompt=material["repair_system"],
        user_prompt=user,
        generation_config={"temperature": TEMPERATURE, "max_output_tokens": MAX_OUTPUT_TOKENS},
        schema_response_mode=SCHEMA_RESPONSE_MODE,
        credential_slot=CREDENTIAL_SLOT,
        research_task_id=TASK_ID,
    )


def build_protocol(base_commit: str = EXPECTED_BASE_COMMIT) -> dict[str, Any]:
    """Return the sole accepted canonical private protocol content."""
    return {
        "access_policy": {
            "dev1": "TUNING_DATA_ALLOWED",
            "dev2_gold": "FORBIDDEN_UNTIL_PREDICTION_LOCK_COMMITTED_AND_PUSHED",
            "dev2_input_during_protocol_lock": "FORBIDDEN",
            "holdout_gold": "FORBIDDEN",
            "holdout_input": "FORBIDDEN",
            "provider_calls_during_protocol_lock": 0,
        },
        "base_commit": base_commit,
        "case_count": len(CASE_IDS),
        "case_execution_order": list(CASE_IDS),
        "case_ids": list(CASE_IDS),
        "compiler_binding": {
            "compiler_entrypoint": "tools.story_extraction.draft_compiler_v1.compile_story_extraction_draft_v1",
            "compiler_sha256": COMPILER_SHA256,
            "draft_schema_sha256": DRAFT_SCHEMA_SHA256,
            "draft_version": DRAFT_VERSION,
            "predicate_registry_sha256": PREDICATE_REGISTRY_SHA256,
        },
        "dev2_gold_sha256": DEV2_GOLD_SHA256,
        "dev2_input_sha256": DEV2_INPUT_SHA256,
        "durable_execution": {
            "durable_executor": DURABLE_EXECUTOR_VERSION,
            "durable_executor_sha256": DURABLE_EXECUTOR_SHA256,
            "first_success": "IMMUTABLE_LOCK",
            "global_pacing_max_operations": GLOBAL_MAX_PROVIDER_OPERATIONS,
            "global_pacing_rolling_window_seconds": GLOBAL_ROLLING_WINDOW_SECONDS,
            "maximum_provider_attempts_per_job": MAX_PROVIDER_ATTEMPTS_PER_JOB,
            "maximum_provider_attempts_per_window": MAX_PROVIDER_ATTEMPTS_PER_WINDOW,
            "maximum_windows_per_job": MAX_WINDOWS_PER_JOB,
            "output_aware_transport_retry": "FORBIDDEN",
            "profile_id": DURABLE_PROFILE_ID,
            "profile_sha256": DURABLE_PROFILE_SHA256,
            "restart_persistent_pacing": True,
            "runtime": RUNTIME_VERSION,
            "runtime_sha256": RUNTIME_SHA256,
            "transport_only_deferral": True,
            "window_cooldown_seconds": WINDOW_COOLDOWN_SECONDS,
        },
        "evaluation_snapshot": {
            "file_sha256": SNAPSHOT_V2_FILE_SHA256,
            "identity": SNAPSHOT_V2_ID,
            "sha256": SNAPSHOT_V2_SHA256,
        },
        "extractor_id": EXTRACTOR_ID,
        "generation": {
            "concurrency": CONCURRENCY,
            "credential_slot": CREDENTIAL_SLOT,
            "credential_topology": CREDENTIAL_TOPOLOGY,
            "json_mode": True,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "model": MODEL,
            "response_mime_type": "application/json",
            "schema_response_mode": SCHEMA_RESPONSE_MODE,
            "seed": "NOT_SUPPORTED_NOT_USED",
            "temperature": TEMPERATURE,
        },
        "output_contract": {
            "allowed_root": DRAFT_VERSION,
            "canonical_batch_from_model": "FORBIDDEN",
            "compiler_is_only_canonicalization_path": True,
            "model_output_only": DRAFT_VERSION,
        },
        "prediction_lock": {
            "dev2_gold_may_open_only_after": "RAW_DRAFTS_AND_COMPILED_BATCHES_HASHED_COMMITTED_AND_PUSHED",
            "lock_before_gold": True,
            "manifest_case_count": len(CASE_IDS),
            "model_or_repair_calls_after_gold_open": 0,
            "raw_primary_and_repair_hashes_required": True,
            "terminal_compiled_or_structural_failure_hash_required": True,
        },
        "prompt_hashes": prompt_hashes(),
        "protocol_id": PROTOCOL_ID,
        "protocol_schema_version": PROTOCOL_SCHEMA_VERSION,
        "repair_policy": {
            "eligible_only_after_successful_primary_response": True,
            "eligible_primary_failure_categories": list(REPAIR_ELIGIBLE_CATEGORIES),
            "gold_signal": "FORBIDDEN",
            "job_id_pattern": "M4B3B2_P2_{CASE_ID}_REPAIR_1",
            "maximum_per_case": MAX_STRUCTURAL_REPAIRS_PER_CASE,
            "missing_fact_or_coverage_retry": "FORBIDDEN",
            "quality_signal": "FORBIDDEN",
            "repair_failure_is_terminal": True,
            "semantic_reinterpretation": "FORBIDDEN",
        },
        "request_construction": {
            "case_specific_primary_fingerprint_locked_at_prediction_time": True,
            "input": "HOST_PREPARED_DRAFT_INPUT_ONLY",
            "job_id_pattern": "M4B3B2_P2_{CASE_ID}_PRIMARY",
            "passage_handles": "P1_P2_ORDERED",
            "primary_jobs": len(CASE_IDS),
            "prompt_material_is_public_tracked_only": True,
        },
        "stop_rules": {
            "alternate_model_or_credential": "FORBIDDEN",
            "batch_rerun": "FORBIDDEN",
            "holdout_access": "FORBIDDEN",
            "maximum_semantic_jobs": len(CASE_IDS) * 2,
            "protocol_change_after_lock": "NEW_TASK_REQUIRED",
        },
        "task_id": TASK_ID,
    }


def _first_difference(expected: Any, actual: Any, path: str = "protocol") -> str:
    if type(expected) is not type(actual):
        return path
    if isinstance(expected, dict):
        if set(expected) != set(actual):
            return path
        for key in expected:
            difference = _first_difference(expected[key], actual[key], f"{path}.{key}")
            if difference:
                return difference
        return ""
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return path
        for index, (left, right) in enumerate(zip(expected, actual)):
            difference = _first_difference(left, right, f"{path}[{index}]")
            if difference:
                return difference
        return ""
    return "" if expected == actual else path


def validate_public_bindings() -> dict[str, str]:
    checks = {}
    for name, path, expected in (
        ("draft_schema", DRAFT_SCHEMA_PATH, DRAFT_SCHEMA_SHA256),
        ("compiler", COMPILER_PATH, COMPILER_SHA256),
        ("predicate_registry", PREDICATE_REGISTRY_PATH, PREDICATE_REGISTRY_SHA256),
        ("runtime", REPO_ROOT / "tools/story_extraction/gemini_resilience_v1_1.py", RUNTIME_SHA256),
        ("durable_executor", REPO_ROOT / "tools/story_extraction/durable_research_executor_v1.py",
         DURABLE_EXECUTOR_SHA256),
    ):
        if file_sha256(path) != expected:
            raise Dev2ProtocolError("Public binding mismatch: " + name)
        checks[name] = "PASS"
    snapshot = yaml.safe_load(SNAPSHOT_V2_PATH.read_text(encoding="utf-8"))
    if (
        file_sha256(SNAPSHOT_V2_PATH) != SNAPSHOT_V2_FILE_SHA256
        or snapshot.get("snapshot_id") != SNAPSHOT_V2_ID
        or snapshot.get("snapshot_sha256") != SNAPSHOT_V2_SHA256
    ):
        raise Dev2ProtocolError("Snapshot V2 identity mismatch")
    checks["snapshot_v2"] = "PASS"
    return checks


def validate_protocol(value: Any, expected_base_commit: str = EXPECTED_BASE_COMMIT) -> dict[str, str]:
    validate_public_bindings()
    if not isinstance(value, dict):
        raise Dev2ProtocolError("Protocol root must be an object")
    expected = build_protocol(expected_base_commit)
    difference = _first_difference(expected, value)
    if difference:
        raise Dev2ProtocolError("Protocol semantic mismatch: " + difference)
    return {
        "parse": "PASS",
        "schema": "PASS",
        "semantic_consistency": "PASS",
        "prompt_hashes": "PASS",
        "case_list_and_order": "PASS",
        "dev2_hash_bindings": "PASS",
        "execution_profile_binding": "PASS",
        "draft_compiler_binding": "PASS",
        "snapshot_v2_binding": "PASS",
        "repair_policy": "PASS",
        "prediction_lock_before_gold": "PASS",
        "holdout_prohibition": "PASS",
    }


@dataclass(frozen=True)
class ValidatedProtocol:
    path: Path
    value: Mapping[str, Any]
    sha256: str
    locked_bytes: bytes
    checks: Mapping[str, str]

    def assert_unchanged(self) -> None:
        try:
            current = self.path.read_bytes()
        except OSError as error:
            raise Dev2ProtocolError("Locked protocol is unavailable") from error
        if current != self.locked_bytes or sha256_bytes(current) != self.sha256:
            raise Dev2ProtocolError("Locked protocol mutated")


def write_protocol(path: Path, base_commit: str = EXPECTED_BASE_COMMIT) -> tuple[dict[str, Any], str]:
    protocol = build_protocol(base_commit)
    validate_protocol(protocol, base_commit)
    payload = canonical_json_bytes(protocol)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return protocol, sha256_bytes(payload)


def validate_protocol_file(path: Path, expected_sha256: str,
                           expected_base_commit: str = EXPECTED_BASE_COMMIT) -> ValidatedProtocol:
    try:
        locked = path.read_bytes()
        value = json.loads(locked.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise Dev2ProtocolError("Canonical protocol is missing or invalid JSON") from error
    actual = sha256_bytes(locked)
    if actual != expected_sha256:
        raise Dev2ProtocolError("Canonical protocol hash mismatch")
    checks = validate_protocol(value, expected_base_commit)
    return ValidatedProtocol(path, deepcopy(value), actual, locked, checks)
