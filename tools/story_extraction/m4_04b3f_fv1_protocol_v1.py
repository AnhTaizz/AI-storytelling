"""Exact offline lock for M4-04B3F: the P3 Draft V1.1 extractor on Fresh Validation V1.

This module materializes prompts and request identities and validates a canonical private
protocol. It never opens the FV1 input or gold packages (it only hashes the input package
and the blindness manifest when asked to check them), loads no credential, constructs no
transport, and performs no provider work. The blind run (M4-04B3G) builds its requests with
`build_primary_spec` / `build_repair_spec` against this lock.

    python -m tools.story_extraction.m4_04b3f_fv1_protocol_v1 --protocol P --validation V \
        --prompt-directory D [--fv1-directory .local/story_extraction/M4_04B3E_FRESH_VALIDATION_V1]
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from tools.story_extraction.durable_research_executor_v1 import DurableJobSpec


REPO_ROOT = Path(__file__).resolve().parents[2]
TASK_ID = "M4-04B3F-LOCK-DRAFT-V1-1-EXTRACTOR-AND-FV1-BLIND-PROTOCOL"
EXPECTED_BASE_COMMIT = "c9b24c72be953d58d386decd075d8f47f1328dba"
PROTOCOL_ID = "M4_04B3F_FV1_DRAFT_V1_1_PROTOCOL_V1"
PROTOCOL_SCHEMA_VERSION = "M4_04B3F_FV1_DRAFT_V1_1_PROTOCOL_SCHEMA_V1"
EXTRACTOR_ID = "P3_STORY_EXTRACTION_DRAFT_V1_1_GEMINI_3_5_FLASH_LITE_V1"
AUTHORIZATION = ("project owner delegation, 2026-11-15: \"Những gì tôi cần tôi duyệt thì bạn làm hộ tôi "
                 "luôn nhé\" (decisions taken by the agent on that delegation)")

FV1_SET_ID = "M4_04B3E_FRESH_VALIDATION_V1"
FV1_INPUT_NAME = "M4_04B3E_FRESH_VALIDATION_V1_INPUT.zip"
FV1_INPUT_SHA256 = "724041283cde55ccbce27844c9297cf66eed857c96cf18989dc97997fef55729"
FV1_GOLD_NAME = "M4_04B3E_FRESH_VALIDATION_V1_GOLD.zip"
FV1_GOLD_SHA256 = "732a3555717c6d3426e6e379e43061cd1fd6d11df8798ec859f37248202ddc73"
FV1_MANIFEST_NAME = "M4_04B3E_FRESH_VALIDATION_V1_BLINDNESS_MANIFEST.json"
FV1_MANIFEST_SHA256 = "cdb8c0dcc62d12e776b0061201f3ec984289007f6e11450266474cfe52a75ea8"
FV1_SEAL_RECORD = REPO_ROOT / "benchmarks/m4_extraction/M4_04B3E_FRESH_VALIDATION_V1_SEAL_RESULT.yaml"
CASE_IDS = tuple(f"FV1_{index:02d}" for index in range(1, 11))

MODEL = "gemini-3.5-flash-lite"
# The B3B2 slot (gemini_slot_3) is not configured in the current environment. B3G must
# qualify this slot with one M4-04B1K smoke call before any FV1 call, or stop.
CREDENTIAL_SLOT = "gemini_slot_33"
CREDENTIAL_TOPOLOGY = "UNKNOWN"
CREDENTIAL_QUALIFICATION = "ONE_M4_04B1K_SMOKE_CALL_AT_B3G_START_BEFORE_ANY_FV1_CALL_ELSE_STOP"
TEMPERATURE = 0
MAX_OUTPUT_TOKENS = 16384
CONCURRENCY = 1
SCHEMA_RESPONSE_MODE = "PROVIDER_JSON_MIME_STORY_EXTRACTION_DRAFT_V1_1"

DURABLE_PROFILE_ID = "M4_DURABLE_RESEARCH_EXECUTION_PROFILE_V1"
DURABLE_PROFILE_SHA256 = "c6c789f0f06d3fdabc2333c29b389252de853ffef0add536d4f06fb6b94e143e"
RUNTIME_VERSION = "GEMINI_TRANSPORT_RESILIENCE_V1_1"
RUNTIME_PATH = REPO_ROOT / "tools/story_extraction/gemini_resilience_v1_1.py"
RUNTIME_SHA256 = "8b84804f5c5b94e1b2ac2507d8b7bc39697b916bbdd889fc1f9040762bfc9213"
DURABLE_EXECUTOR_VERSION = "DURABLE_RESEARCH_EXECUTOR_V1"
DURABLE_EXECUTOR_PATH = REPO_ROOT / "tools/story_extraction/durable_research_executor_v1.py"
DURABLE_EXECUTOR_SHA256 = "cc9bd7a863ff906dea8fcd2f753c552881acd33f97a72b4af4e4e84eb1bfbe66"
MAX_WINDOWS_PER_JOB = 3
MAX_PROVIDER_ATTEMPTS_PER_WINDOW = 3
MAX_PROVIDER_ATTEMPTS_PER_JOB = 9
GLOBAL_MAX_PROVIDER_OPERATIONS = 6
GLOBAL_ROLLING_WINDOW_SECONDS = 60
WINDOW_COOLDOWN_SECONDS = 60

DRAFT_VERSION = "STORY_EXTRACTION_DRAFT_V1_1"
DRAFT_SCHEMA_PATH = REPO_ROOT / "schemas/story_extraction/story_extraction_draft_v1_1.schema.json"
DRAFT_SCHEMA_SHA256 = "6b5267319e2b6be42734254ad8efdb8fe6ab6843c5ba945ae4e8b524f11f78c0"
V1_SCHEMA_PATH = REPO_ROOT / "schemas/story_extraction/story_extraction_draft_v1.schema.json"
V1_SCHEMA_SHA256 = "498edf8dba8d45b80380a180d1383787f5c0e4ecea5060254883cc27c7d83e80"
COMPILER_PATH = REPO_ROOT / "tools/story_extraction/draft_compiler_v1_1.py"
COMPILER_SHA256 = "c41730be4e661914faaf00dbf77b77f2dc46924543ee577de1e362b325e04166"
V1_COMPILER_PATH = REPO_ROOT / "tools/story_extraction/draft_compiler_v1.py"
V1_COMPILER_SHA256 = "bcd15328cefafe86dd8e686fb35a155b2cb2c261b20017486ed106e85371d836"
PREDICATE_REGISTRY_PATH = REPO_ROOT / "schemas/canonical_story/predicate_registry_v0.yaml"
PREDICATE_REGISTRY_SHA256 = "44f3eafc6982f84bcc74ccb91abe7cd467a453352ee96be147095f27559c5350"
SNAPSHOT_V2_PATH = REPO_ROOT / "benchmarks/m4_extraction/M4_EVALUATION_PROTOCOL_SNAPSHOT_V2.yaml"
SNAPSHOT_V2_ID = "M4_EVALUATION_PROTOCOL_SNAPSHOT_V2"
SNAPSHOT_V2_SHA256 = "8dddbd0b9f3ea51af593c1fab0631b088b6f4e6b8c16833a1f11b8448088eee9"
SNAPSHOT_V2_FILE_SHA256 = "eef2db2ff2ba61f22a96d3a52ab64e07c6c9e9dbc9e9741e061f2893ba6283a8"

PROMPT_ROOT = REPO_ROOT / "tools/story_extraction/prompts"
SYSTEM_PREAMBLE_PATH = PROMPT_ROOT / "story_extraction_draft_p3_system_v1_1.txt"
USER_TEMPLATE_PATH = PROMPT_ROOT / "story_extraction_draft_p3_user_v1_1.txt"
REPAIR_USER_TEMPLATE_PATH = PROMPT_ROOT / "story_extraction_draft_p3_repair_user_v1_1.txt"
REPAIR_SYSTEM_SUFFIX = """

STRUCTURAL REPAIR MODE
Repair only the sanitized deterministic blockers supplied by the host. Preserve semantic
choices from the primary response. Do not fill coverage gaps, optimize quality, consult
gold, or introduce a new interpretation. This is the only repair allowed for the case.
""".strip()

REPAIR_ELIGIBLE_CATEGORIES = (
    "JSON_PARSE_FAILURE",
    "DRAFT_SCHEMA_FAILURE",
    "DRAFT_COMPILER_FAILURE",
)
MAX_STRUCTURAL_REPAIRS_PER_CASE = 1
BLOCKER_KEYS = ("code", "path", "phase")


class Fv1ProtocolError(RuntimeError):
    """The protocol, a request or a bound artifact differs from the exact lock."""


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
    """Build exact P3 prompts only from tracked public files.

    The V1.1 schema reuses every non-Mention definition of the V1 schema by `$ref`, so the
    V1 schema is appended as the referenced document; otherwise the model would see
    references it cannot resolve."""
    preamble = _normalized_text(SYSTEM_PREAMBLE_PATH)
    system = (
        preamble
        + "\n\nEXACT STORY_EXTRACTION_DRAFT_V1_1 JSON SCHEMA:\n"
        + _normalized_text(DRAFT_SCHEMA_PATH)
        + "\n\nREFERENCED STORY_EXTRACTION_DRAFT_V1 JSON SCHEMA (definitions used by $ref above):\n"
        + _normalized_text(V1_SCHEMA_PATH)
        + "\n\nEXACT PREDICATE REGISTRY:\n"
        + _normalized_text(PREDICATE_REGISTRY_PATH)
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
            material["primary_system"] + "\0" + material["primary_user_template"]),
        "repair_system_sha256": sha256_text(material["repair_system"]),
        "repair_user_template_sha256": sha256_text(material["repair_user_template"]),
        "repair_prompt_pair_sha256": sha256_text(
            material["repair_system"] + "\0" + material["repair_user_template"]),
    }


def prompt_source_hashes() -> dict[str, str]:
    return {path.name: file_sha256(path) for path in (SYSTEM_PREAMBLE_PATH, USER_TEMPLATE_PATH,
                                                     REPAIR_USER_TEMPLATE_PATH)}


def _render(template: str, replacements: Mapping[str, str]) -> str:
    rendered = template
    for key, value in replacements.items():
        marker = "{" + key + "}"
        if marker not in rendered:
            raise Fv1ProtocolError("Prompt template marker missing: " + marker)
        rendered = rendered.replace(marker, value)
    if any(marker in rendered for marker in ("{CASE_ID}", "{PREPARED_INPUT_JSON}",
                                             "{PRIMARY_RESPONSE}", "{FAILURE_JSON}")):
        raise Fv1ProtocolError("Prompt template has unresolved markers")
    return rendered


def _check_case(case_id: str, prepared_input: Mapping[str, Any]) -> str:
    if case_id not in CASE_IDS:
        raise Fv1ProtocolError("Unknown FV1 case id")
    if prepared_input.get("draft_version") != DRAFT_VERSION:
        raise Fv1ProtocolError("Prepared input is not Draft V1.1")
    for handle, record in (prepared_input.get("existing_context") or {}).items():
        if isinstance(record, Mapping) and "evidence_handle" in record:
            raise Fv1ProtocolError("Prepared input carries a mention evidence_handle: " + handle)
    return canonical_json_bytes(dict(prepared_input)).decode("utf-8").rstrip()


def primary_user_prompt(case_id: str, prepared_input: Mapping[str, Any]) -> str:
    rendered_input = _check_case(case_id, prepared_input)
    return _render(prompt_material()["primary_user_template"],
                   {"CASE_ID": case_id, "PREPARED_INPUT_JSON": rendered_input})


def _spec(job_id: str, system: str, user: str) -> DurableJobSpec:
    return DurableJobSpec(
        job_id=job_id, model=MODEL, system_prompt=system, user_prompt=user,
        generation_config={"temperature": TEMPERATURE, "max_output_tokens": MAX_OUTPUT_TOKENS},
        schema_response_mode=SCHEMA_RESPONSE_MODE, credential_slot=CREDENTIAL_SLOT,
        research_task_id=TASK_ID,
    )


def build_primary_spec(case_id: str, prepared_input: Mapping[str, Any]) -> DurableJobSpec:
    return _spec(f"M4B3F_P3_{case_id}_PRIMARY", prompt_material()["primary_system"],
                 primary_user_prompt(case_id, prepared_input))


def sanitized_failure(category: str, blockers: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    """The only repair payload: the category and every blocker as phase, code and path."""
    if category not in REPAIR_ELIGIBLE_CATEGORIES:
        raise Fv1ProtocolError("Repair category is not eligible")
    cleaned = []
    for blocker in blockers:
        if set(blocker) != set(BLOCKER_KEYS) or not all(isinstance(blocker[k], str) for k in BLOCKER_KEYS):
            raise Fv1ProtocolError("A blocker must hold exactly phase, code and path strings")
        cleaned.append({key: blocker[key] for key in BLOCKER_KEYS})
    if not cleaned:
        raise Fv1ProtocolError("A repair needs at least one structural blocker")
    return {"blockers": sorted(cleaned, key=lambda b: (b["phase"], b["code"], b["path"])), "category": category}


def build_repair_spec(case_id: str, prepared_input: Mapping[str, Any], primary_response: str,
                      failure: Mapping[str, Any]) -> DurableJobSpec:
    if set(failure) != {"blockers", "category"}:
        raise Fv1ProtocolError("Repair failure payload must hold only category and blockers")
    payload = sanitized_failure(failure["category"], failure["blockers"])
    if not isinstance(primary_response, str) or not primary_response:
        raise Fv1ProtocolError("Repair requires one successful primary response")
    rendered_input = _check_case(case_id, prepared_input)
    material = prompt_material()
    user = _render(material["repair_user_template"], {
        "CASE_ID": case_id,
        "PREPARED_INPUT_JSON": rendered_input,
        "PRIMARY_RESPONSE": primary_response,
        "FAILURE_JSON": canonical_json_bytes(payload).decode("utf-8").rstrip(),
    })
    return _spec(f"M4B3F_P3_{case_id}_REPAIR_1", material["repair_system"], user)


def build_protocol(base_commit: str = EXPECTED_BASE_COMMIT) -> dict[str, Any]:
    """Return the sole accepted canonical private protocol content."""
    return {
        "access_policy": {
            "dev1": "TUNING_DATA_ALLOWED",
            "dev2": "TUNING_DATA_AFTER_INTERFACE_REDESIGN",
            "fv1_gold": "FORBIDDEN_UNTIL_PREDICTION_LOCK_COMMITTED_AND_PUSHED",
            "fv1_input_during_protocol_lock": "HASH_ONLY_NOT_OPENED",
            "fv1_input_during_blind_run": "PREPARED_DRAFT_INPUT_MEMBERS_ONLY",
            "holdout_gold": "FORBIDDEN",
            "holdout_input": "FORBIDDEN",
            "prompt_tuning_material": "DEV1_DEV2_ONLY_NEVER_FV1_TEXT",
            "provider_calls_during_protocol_lock": 0,
        },
        "authorization": AUTHORIZATION,
        "base_commit": base_commit,
        "case_count": len(CASE_IDS),
        "case_execution_order": list(CASE_IDS),
        "case_ids": list(CASE_IDS),
        "compiler_binding": {
            "compiler_entrypoint": "tools.story_extraction.draft_compiler_v1_1.compile_story_extraction_draft_v1_1",
            "compiler_sha256": COMPILER_SHA256,
            "delegated_v1_compiler_sha256": V1_COMPILER_SHA256,
            "draft_schema_sha256": DRAFT_SCHEMA_SHA256,
            "draft_version": DRAFT_VERSION,
            "predicate_registry_sha256": PREDICATE_REGISTRY_SHA256,
            "referenced_v1_schema_sha256": V1_SCHEMA_SHA256,
        },
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
        "fv1_bindings": {
            "blindness_manifest_sha256": FV1_MANIFEST_SHA256,
            "gold_sha256": FV1_GOLD_SHA256,
            "input_sha256": FV1_INPUT_SHA256,
            "set_id": FV1_SET_ID,
        },
        "generation": {
            "concurrency": CONCURRENCY,
            "credential_qualification": CREDENTIAL_QUALIFICATION,
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
            "mention_evidence_handle_from_model": "FORBIDDEN",
            "model_output_only": DRAFT_VERSION,
        },
        "prediction_lock": {
            "fv1_gold_may_open_only_after": "RAW_DRAFTS_AND_COMPILED_BATCHES_HASHED_COMMITTED_AND_PUSHED",
            "lock_before_gold": True,
            "manifest_case_count": len(CASE_IDS),
            "model_or_repair_calls_after_gold_open": 0,
            "raw_primary_and_repair_hashes_required": True,
            "terminal_compiled_or_structural_failure_hash_required": True,
        },
        "prompt_hashes": prompt_hashes(),
        "prompt_source_sha256": prompt_source_hashes(),
        "protocol_id": PROTOCOL_ID,
        "protocol_schema_version": PROTOCOL_SCHEMA_VERSION,
        "repair_policy": {
            "eligible_only_after_successful_primary_response": True,
            "eligible_primary_failure_categories": list(REPAIR_ELIGIBLE_CATEGORIES),
            "feedback": "ALL_V1_1_STRUCTURAL_BLOCKERS_AS_PHASE_CODE_PATH_WITHOUT_SOURCE_TEXT",
            "gold_signal": "FORBIDDEN",
            "job_id_pattern": "M4B3F_P3_{CASE_ID}_REPAIR_1",
            "maximum_per_case": MAX_STRUCTURAL_REPAIRS_PER_CASE,
            "missing_fact_or_coverage_retry": "FORBIDDEN",
            "quality_signal": "FORBIDDEN",
            "repair_failure_is_terminal": True,
            "semantic_reinterpretation": "FORBIDDEN",
        },
        "request_construction": {
            "case_specific_primary_fingerprint_locked_at_prediction_time": True,
            "input": "HOST_PREPARED_DRAFT_V1_1_INPUT_ONLY",
            "job_id_pattern": "M4B3F_P3_{CASE_ID}_PRIMARY",
            "passage_handles": "P1_P2_ORDERED",
            "primary_jobs": len(CASE_IDS),
            "prompt_material_is_public_tracked_only": True,
        },
        "stop_rules": {
            "alternate_model_or_credential": "FORBIDDEN",
            "batch_rerun": "FORBIDDEN",
            "credential_qualification_failure": "STOP_NEW_TASK_REQUIRED",
            "holdout_access": "FORBIDDEN",
            "maximum_credential_qualification_calls": 1,
            "maximum_semantic_jobs": len(CASE_IDS) * 2,
            "protocol_change_after_lock": "NEW_TASK_REQUIRED",
            "second_model_arm": "NOT_LOCKED_NEW_TASK_REQUIRED",
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
        ("draft_schema_v1_1", DRAFT_SCHEMA_PATH, DRAFT_SCHEMA_SHA256),
        ("draft_schema_v1", V1_SCHEMA_PATH, V1_SCHEMA_SHA256),
        ("compiler_v1_1", COMPILER_PATH, COMPILER_SHA256),
        ("compiler_v1", V1_COMPILER_PATH, V1_COMPILER_SHA256),
        ("predicate_registry", PREDICATE_REGISTRY_PATH, PREDICATE_REGISTRY_SHA256),
        ("runtime", RUNTIME_PATH, RUNTIME_SHA256),
        ("durable_executor", DURABLE_EXECUTOR_PATH, DURABLE_EXECUTOR_SHA256),
    ):
        if file_sha256(path) != expected:
            raise Fv1ProtocolError("Public binding mismatch: " + name)
        checks[name] = "PASS"
    snapshot = yaml.safe_load(SNAPSHOT_V2_PATH.read_text(encoding="utf-8"))
    if (file_sha256(SNAPSHOT_V2_PATH) != SNAPSHOT_V2_FILE_SHA256
            or snapshot.get("snapshot_id") != SNAPSHOT_V2_ID
            or snapshot.get("snapshot_sha256") != SNAPSHOT_V2_SHA256):
        raise Fv1ProtocolError("Snapshot V2 identity mismatch")
    checks["snapshot_v2"] = "PASS"
    seal = yaml.safe_load(FV1_SEAL_RECORD.read_text(encoding="utf-8"))["private_packages"]
    if ((seal["input"]["sha256"], seal["gold"]["sha256"], seal["blindness_manifest"]["sha256"])
            != (FV1_INPUT_SHA256, FV1_GOLD_SHA256, FV1_MANIFEST_SHA256) or seal["input"]["contains_gold"]):
        raise Fv1ProtocolError("FV1 seal record does not match the bound hashes")
    checks["fv1_seal_record"] = "PASS"
    return checks


def verify_fv1_packages(directory: Path) -> dict[str, str]:
    """Hash the FV1 input package and blindness manifest (never opened, never the gold)."""
    checks = {}
    for name, expected in ((FV1_INPUT_NAME, FV1_INPUT_SHA256), (FV1_MANIFEST_NAME, FV1_MANIFEST_SHA256)):
        path = Path(directory) / name
        if not path.is_file():
            raise Fv1ProtocolError("FV1 artifact is missing: " + name)
        if file_sha256(path) != expected:
            raise Fv1ProtocolError("FV1 artifact hash mismatch: " + name)
        checks[name] = "PASS"
    return checks


def validate_protocol(value: Any, expected_base_commit: str = EXPECTED_BASE_COMMIT) -> dict[str, str]:
    validate_public_bindings()
    if not isinstance(value, dict):
        raise Fv1ProtocolError("Protocol root must be an object")
    difference = _first_difference(build_protocol(expected_base_commit), value)
    if difference:
        raise Fv1ProtocolError("Protocol semantic mismatch: " + difference)
    return {
        "parse": "PASS", "semantic_consistency": "PASS", "prompt_hashes": "PASS",
        "case_list_and_order": "PASS", "fv1_hash_bindings": "PASS", "execution_profile_binding": "PASS",
        "draft_compiler_binding": "PASS", "snapshot_v2_binding": "PASS", "repair_policy": "PASS",
        "prediction_lock_before_gold": "PASS", "holdout_prohibition": "PASS",
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
            raise Fv1ProtocolError("Locked protocol is unavailable") from error
        if current != self.locked_bytes or sha256_bytes(current) != self.sha256:
            raise Fv1ProtocolError("Locked protocol mutated")


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
        raise Fv1ProtocolError("Canonical protocol is missing or invalid JSON") from error
    actual = sha256_bytes(locked)
    if actual != expected_sha256:
        raise Fv1ProtocolError("Canonical protocol hash mismatch")
    checks = validate_protocol(value, expected_base_commit)
    return ValidatedProtocol(path, deepcopy(value), actual, locked, checks)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--validation", required=True, type=Path)
    parser.add_argument("--prompt-directory", required=True, type=Path)
    parser.add_argument("--fv1-directory", type=Path, default=None,
                        help="directory holding the sealed FV1 input package and blindness manifest (hashed only)")
    args = parser.parse_args(argv)

    _, protocol_sha = write_protocol(args.protocol)
    validated = validate_protocol_file(args.protocol, protocol_sha)
    args.prompt_directory.mkdir(parents=True, exist_ok=True)
    for name, text in prompt_material().items():
        (args.prompt_directory / f"{name}.txt").write_text(text, encoding="utf-8", newline="\n")
    validation = {
        "artifact": "M4_04B3F_FV1_PROTOCOL_VALIDATION_V1",
        "base_commit": EXPECTED_BASE_COMMIT,
        "protocol_sha256": protocol_sha,
        **dict(validated.checks),
        "public_bindings": validate_public_bindings(),
        "fv1_packages": verify_fv1_packages(args.fv1_directory) if args.fv1_directory else "NOT_CHECKED",
        "prompt_material_hashes": prompt_hashes(),
        "provider_calls": 0,
        "fv1_input_opened": False,
        "fv1_gold_opened": False,
        "holdout_accessed": False,
    }
    args.validation.parent.mkdir(parents=True, exist_ok=True)
    args.validation.write_bytes(canonical_json_bytes(validation))
    print(json.dumps({"protocol_sha256": protocol_sha, "status": "PASS"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
