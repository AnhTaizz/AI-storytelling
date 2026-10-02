"""Preregistered M4-04B2 development benchmark protocol and access controls."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Optional
import uuid
import zipfile


REPO_ROOT = Path(__file__).resolve().parents[2]
TASK_ID = "M4-04B2-DEVELOPMENT-EXTRACTION-BENCHMARK-AND-EXTRACTOR-LOCK"
EXPECTED_BASE_COMMIT = "aeb26d363694c337bb2b30170629be0d94ed090c"
PROTOCOL_ID = "M4_04B2_DEV_BENCHMARK_PROTOCOL_V1"
PROTOCOL_SCHEMA_VERSION = "M4_04B2_DEV_BENCHMARK_PROTOCOL_SCHEMA_V1"
DEV_PACKAGE_SHA256 = "a991921d0ca0afb5643948346acc407a84e17206bd6d0692c362d86de47da809"
EVALUATOR_SNAPSHOT_ID = "M4_EVALUATION_PROTOCOL_SNAPSHOT_V1"
EVALUATOR_SNAPSHOT_SHA256 = "a9ac816fe8e20d6ed0d2a4e078c37a89a63dc10660b11d9c754b8038d71c29a6"
DURABLE_PROFILE_ID = "M4_DURABLE_RESEARCH_EXECUTION_PROFILE_V1"
DURABLE_PROFILE_SHA256 = "c6c789f0f06d3fdabc2333c29b389252de853ffef0add536d4f06fb6b94e143e"
RUNTIME_VERSION = "GEMINI_TRANSPORT_RESILIENCE_V1_1"
DURABLE_EXECUTOR_VERSION = "DURABLE_RESEARCH_EXECUTOR_V1"
MODEL = "gemini-3.5-flash-lite"
CREDENTIAL_SLOT = "gemini_slot_3"
CREDENTIAL_TOPOLOGY = "UNKNOWN"
CANDIDATES = ("P0", "P1")
CASE_IDS = tuple(f"M4DEV_{index:02d}" for index in range(1, 15))
TEMPERATURE = 0
MAX_OUTPUT_TOKENS = 16384
CONCURRENCY = 1
MAX_WINDOWS_PER_JOB = 3
MAX_PROVIDER_ATTEMPTS_PER_WINDOW = 3
MAX_PROVIDER_ATTEMPTS_PER_JOB = 9
MAX_STRUCTURAL_REPAIRS_PER_CASE_CANDIDATE = 1
MAX_PRIMARY_JOBS = len(CANDIDATES) * len(CASE_IDS)
MAX_SEMANTIC_JOBS = MAX_PRIMARY_JOBS * 2
MAX_PROVIDER_ATTEMPTS = MAX_SEMANTIC_JOBS * MAX_PROVIDER_ATTEMPTS_PER_JOB
GLOBAL_MAX_PROVIDER_OPERATIONS = 6
GLOBAL_ROLLING_WINDOW_SECONDS = 60
WINDOW_COOLDOWN_SECONDS = 60
SCHEMA_RESPONSE_MODE = "PROVIDER_JSON_MIME_STRUCTURAL_REPAIR_SEPARATE_JOB"
INPUT_MEMBERS = (
    "M4_02_DEV_CALIBRATION/base_canonical_document.json",
    "M4_02_DEV_CALIBRATION/development_cases.jsonl",
    "M4_02_DEV_CALIBRATION/source_passage_refs.jsonl",
)
FORBIDDEN_CASE_FIELDS = frozenset(
    {
        "acceptable_assertions",
        "annotation_notes",
        "conversion_stats",
        "gold_batch",
        "gold_completeness",
        "gold_status",
        "open_question_tags",
        "required_assertions",
    }
)
ALLOWED_CASE_FIELDS = (
    "case_id",
    "case_objective",
    "category",
    "secondary_categories",
    "extraction_profile",
    "out_of_scope_fact_classes",
    "as_of_position",
    "base_canonical_identity",
    "evidence_eligible_passages",
    "context_only_passages",
    "source_basis",
)


class DevBenchmarkProtocolError(RuntimeError):
    """The preregistration, access boundary, or immutable protocol failed closed."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_normalized(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _load_synthetic_fixture() -> tuple[dict[str, Any], dict[str, Any]]:
    fixture_path = REPO_ROOT / "tests/story_extraction/fixture_builder.py"
    spec = importlib.util.spec_from_file_location("_m4_b2_fixture_builder", fixture_path)
    if spec is None or spec.loader is None:
        raise DevBenchmarkProtocolError("Synthetic fixture builder cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _, base, batch = module.build(
        "c05_event_occurred",
        "gold",
        prefix="fewshot",
        method="AUTOMATED_EXTRACTION",
    )
    envelope = {key: value for key, value in batch.items() if key != "candidate_records"}
    example_input = {
        "base_document": base,
        "required_envelope": envelope,
        "synthetic_case_id": "c05_event_occurred",
    }
    return example_input, batch


USER_TEMPLATE = """DEVELOPMENT CASE {CASE_ID}

Use only the JSON payload below. Copy required_envelope exactly and add candidate_records.
Do not extract from context-only passages. Prior canonical records constrain identity but
are not evidence. Use opaque candidate ids prefixed with {ID_PREFIX}.

INPUT_PAYLOAD_JSON:
{INPUT_PAYLOAD_JSON}

Return exactly one STORY_EXTRACTION_BATCH/v0 JSON object and no surrounding text.
"""

REPAIR_USER_TEMPLATE = """STRUCTURAL REPAIR JOB FOR {CASE_ID} / {CANDIDATE}

This is a new semantic job, not a retry. Correct only deterministic JSON/schema/canonical
conformance errors. Preserve the extraction meaning. Do not add facts because they seem
missing and do not use any quality or gold signal.

ORIGINAL_INPUT_PAYLOAD_JSON:
{INPUT_PAYLOAD_JSON}

ORIGINAL_SUCCESSFUL_RESPONSE:
{ORIGINAL_RESPONSE}

DETERMINISTIC_VALIDATOR_ERRORS_JSON:
{VALIDATOR_ERRORS_JSON}

Return exactly one corrected STORY_EXTRACTION_BATCH/v0 JSON object and no surrounding text.
"""


def prompt_material() -> dict[str, str]:
    """Materialize exact P0/P1 prompts only from public contract/synthetic material."""
    base = _read_normalized(
        REPO_ROOT / "tools/story_extraction/prompts/story_extraction_base_v1.txt"
    ).rstrip()
    batch_schema = _read_normalized(
        REPO_ROOT / "schemas/story_extraction/story_extraction_batch_v0.schema.json"
    ).rstrip()
    canonical_schema = _read_normalized(
        REPO_ROOT / "schemas/canonical_story/canonical_story_v0.schema.json"
    ).rstrip()
    predicate_registry = _read_normalized(
        REPO_ROOT / "schemas/canonical_story/predicate_registry_v0.yaml"
    ).rstrip()
    contract_reference = (
        "\n\nEXACT BATCH ENVELOPE SCHEMA:\n"
        + batch_schema
        + "\n\nEXACT CANONICAL RECORD SCHEMA:\n"
        + canonical_schema
        + "\n\nEXACT PREDICATE REGISTRY:\n"
        + predicate_registry
    )
    p0_system = base + contract_reference
    example_input, example_output = _load_synthetic_fixture()
    fewshot = (
        "FIXED SYNTHETIC M4-01 EXAMPLE. It is invented and is not development data.\n"
        "SYNTHETIC_INPUT_JSON:\n"
        + canonical_json_bytes(example_input).decode("utf-8")
        + "SYNTHETIC_OUTPUT_JSON:\n"
        + canonical_json_bytes(example_output).decode("utf-8")
        + "END_FIXED_SYNTHETIC_EXAMPLE"
    )
    p1_system = p0_system + "\n\n" + fewshot
    repair_system = (
        p0_system
        + "\n\nSTRUCTURAL REPAIR MODE: You are correcting only the listed deterministic "
        "conformance errors in one already-successful response. Never use quality judgment."
    )
    return {
        "p0_system": p0_system,
        "p0_user_template": USER_TEMPLATE,
        "p1_system": p1_system,
        "p1_user_template": USER_TEMPLATE,
        "p1_fewshot": fewshot,
        "repair_system": repair_system,
        "repair_user_template": REPAIR_USER_TEMPLATE,
    }


def prompt_hashes() -> dict[str, str]:
    values = prompt_material()
    return {
        "p0_system_sha256": sha256_text(values["p0_system"]),
        "p0_user_template_sha256": sha256_text(values["p0_user_template"]),
        "p0_prompt_sha256": sha256_text(
            values["p0_system"] + "\0" + values["p0_user_template"]
        ),
        "p1_system_sha256": sha256_text(values["p1_system"]),
        "p1_user_template_sha256": sha256_text(values["p1_user_template"]),
        "p1_fewshot_sha256": sha256_text(values["p1_fewshot"]),
        "p1_prompt_sha256": sha256_text(
            values["p1_system"] + "\0" + values["p1_user_template"]
        ),
        "repair_system_sha256": sha256_text(values["repair_system"]),
        "repair_template_sha256": sha256_text(values["repair_user_template"]),
    }


def build_protocol(base_commit: str = EXPECTED_BASE_COMMIT) -> dict[str, Any]:
    return {
        "base_commit": base_commit,
        "candidate_execution_order": list(CANDIDATES),
        "candidate_selection_rule": [
            "FEWER_CRITICAL_UNSUPPORTED",
            "FEWER_HIGH_UNSUPPORTED",
            "HIGHER_COMPLETE_FULL_CANONICAL_CASE_SUCCESS",
            "HIGHER_COMPLETE_GROUNDING_RECALL",
            "HIGHER_COMPLETE_ASSERTION_RECALL",
            "HIGHER_EPISTEMIC_ACCURACY",
            "FEWER_STRUCTURAL_REPAIR_JOBS",
            "FEWER_PROVIDER_ATTEMPTS",
            "FEWER_OUTPUT_TOKENS",
            "FEWER_INPUT_TOKENS",
            "LOWER_PROVIDER_LATENCY_SECONDS",
            "P0_IF_EXACT_TIE",
        ],
        "case_execution_order": list(CASE_IDS),
        "case_ids": list(CASE_IDS),
        "candidate_count": len(CANDIDATES),
        "case_count": len(CASE_IDS),
        "concurrency": CONCURRENCY,
        "credential_slot": CREDENTIAL_SLOT,
        "credential_topology": CREDENTIAL_TOPOLOGY,
        "dev_package_sha256": DEV_PACKAGE_SHA256,
        "durable_execution_profile": {
            "durable_executor": DURABLE_EXECUTOR_VERSION,
            "identity": DURABLE_PROFILE_ID,
            "profile_sha256": DURABLE_PROFILE_SHA256,
            "runtime": RUNTIME_VERSION,
        },
        "evaluation_metrics": [
            "STRUCTURAL_VALID_CASE_COUNT",
            "REPAIR_COUNT",
            "REPAIR_SUCCESS_COUNT",
            "ASSERTION_PRECISION",
            "ASSERTION_RECALL",
            "GROUNDING_PRECISION",
            "GROUNDING_RECALL",
            "EPISTEMIC_ACCURACY",
            "EVIDENCE_ROLE_ACCURACY",
            "REFERENT_RESOLUTION_ACCURACY",
            "UNSUPPORTED_ASSERTION_RATE",
            "FULL_CANONICAL_CASE_SUCCESS",
            "L0_L5_BREAKDOWN",
            "TOKEN_USAGE",
            "PROVIDER_ATTEMPTS",
            "LATENCY",
        ],
        "evaluator_snapshot": {
            "identity": EVALUATOR_SNAPSHOT_ID,
            "sha256": EVALUATOR_SNAPSHOT_SHA256,
            "evaluator": "evaluate_extraction_v0/0.2.0",
        },
        "extractor_lock_fields": [
            "extractor_id",
            "model",
            "provider_reported_model_version_rule",
            "credential_execution_policy",
            "candidate_identity",
            "prompt_hashes",
            "generation_settings",
            "provider_response_mode",
            "primary_request_construction",
            "repair_template_sha256",
            "maximum_structural_repairs",
            "repair_eligibility",
            "contract_and_schema_identities",
            "evaluator_snapshot_identity",
            "durable_profile_sha256",
            "protocol_sha256",
            "prediction_set_hashes",
            "development_result_sha256",
        ],
        "generation_settings": {
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "provider_json_mode": True,
            "seed": "NOT_SUPPORTED_NOT_USED",
            "temperature": TEMPERATURE,
        },
        "global_pacing": {
            "maximum_provider_operations": GLOBAL_MAX_PROVIDER_OPERATIONS,
            "restart_persistent": True,
            "rolling_window_seconds": GLOBAL_ROLLING_WINDOW_SECONDS,
        },
        "gold_opening_barrier": {
            "dev_gold": "FORBIDDEN_UNTIL_PUBLIC_PREDICTION_LOCK_PUSHED",
            "no_provider_calls_after_dev_gold_open": True,
        },
        "holdout_prohibition": {
            "holdout_gold": "FORBIDDEN",
            "holdout_input": "FORBIDDEN",
            "holdout_predictions": "NOT_RUN",
        },
        "maximum_provider_attempts": MAX_PROVIDER_ATTEMPTS,
        "maximum_provider_attempts_per_job": MAX_PROVIDER_ATTEMPTS_PER_JOB,
        "maximum_provider_attempts_per_window": MAX_PROVIDER_ATTEMPTS_PER_WINDOW,
        "maximum_semantic_jobs": MAX_SEMANTIC_JOBS,
        "maximum_windows_per_job": MAX_WINDOWS_PER_JOB,
        "model": MODEL,
        "prediction_lock_process": {
            "manifest_entries": MAX_PRIMARY_JOBS,
            "public_lock_commit_before_dev_gold": True,
            "raw_and_final_hashes_required": True,
        },
        "primary_job_construction": {
            "candidate_job_count": len(CASE_IDS),
            "case_fields": list(ALLOWED_CASE_FIELDS),
            "envelope_copied_exactly": True,
            "forbidden_case_fields": sorted(FORBIDDEN_CASE_FIELDS),
            "job_id_pattern": "M4B2_{CANDIDATE}_{CASE_ID}_PRIMARY",
            "request_payload": "SAFE_CASE_FIELDS_PLUS_EXACT_PASSAGE_REFS_PLUS_BASE_SUBSET",
            "schema_response_mode": SCHEMA_RESPONSE_MODE,
        },
        "prompt_hashes": prompt_hashes(),
        "protocol_id": PROTOCOL_ID,
        "protocol_schema_version": PROTOCOL_SCHEMA_VERSION,
        "repair_eligibility": [
            "JSON_PARSE_FAILURE",
            "STORY_EXTRACTION_BATCH_SCHEMA_FAILURE",
            "CANONICAL_RECORD_STRUCTURAL_FAILURE",
            "PREDICATE_VALUE_STRUCTURAL_INCOMPATIBILITY",
            "OTHER_MACHINE_DETECTABLE_CONTRACT_FAILURE",
        ],
        "repair_job_construction": {
            "job_id_pattern": "M4B2_{CANDIDATE}_{CASE_ID}_REPAIR_1",
            "maximum_per_case_candidate": MAX_STRUCTURAL_REPAIRS_PER_CASE_CANDIDATE,
            "quality_signal": "FORBIDDEN",
            "receives": [
                "ORIGINAL_INPUT",
                "ORIGINAL_SUCCESSFUL_RESPONSE",
                "DETERMINISTIC_VALIDATOR_ERRORS",
                "ORIGINAL_EXTRACTION_INSTRUCTIONS",
                "REQUIRED_OUTPUT_SCHEMA",
            ],
        },
        "safety_gate": [
            "ALL_SELECTED_FINAL_PREDICTIONS_L0_CONFORMANT",
            "ZERO_CRITICAL_UNSUPPORTED",
            "ZERO_HIGH_UNSUPPORTED",
            "NO_UNRESOLVED_EVALUATOR_INTEGRITY_DEFECT",
            "NO_PROTOCOL_VIOLATION",
            "NO_DEV_PREDICTION_AFTER_GOLD_ACCESS",
            "NO_HOLDOUT_ACCESS",
            "TRANSPORT_EXECUTION_INVARIANTS_PASS",
        ],
        "task_id": TASK_ID,
        "transport_deferred_policy": {
            "first_success": "IMMUTABLE_LOCK",
            "output_aware_transport_retry": "FORBIDDEN",
            "transport_only": True,
            "window_cooldown_seconds": WINDOW_COOLDOWN_SECONDS,
        },
        "uncertain_case_adjudication_policy": {
            "model_calls_after_gold_open": "FORBIDDEN",
            "unmatched_default": "GOLD_UNMATCHED_PENDING_ADJUDICATION",
            "use_existing_ontology_only": True,
        },
    }


PROTOCOL_REQUIRED_FIELDS = tuple(sorted(build_protocol().keys()))


def validate_protocol(
    value: Any, *, expected_base_commit: str = EXPECTED_BASE_COMMIT
) -> dict[str, str]:
    if not isinstance(value, dict):
        raise DevBenchmarkProtocolError("Protocol root must be an object")
    expected = build_protocol(expected_base_commit)
    missing = sorted(set(expected) - set(value))
    unknown = sorted(set(value) - set(expected))
    if missing:
        raise DevBenchmarkProtocolError("Missing protocol field: " + missing[0])
    if unknown:
        raise DevBenchmarkProtocolError("Unknown protocol field: " + unknown[0])
    if value != expected:
        for key in expected:
            if value.get(key) != expected[key]:
                raise DevBenchmarkProtocolError("Protocol semantic mismatch: " + key)
        raise DevBenchmarkProtocolError("Protocol semantic mismatch")
    return {
        "parse": "PASS",
        "schema": "PASS",
        "semantic_consistency": "PASS",
        "prompt_hashes": "PASS",
        "case_list": "PASS",
        "execution_profile_binding": "PASS",
        "evaluator_snapshot_binding": "PASS",
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
            raise DevBenchmarkProtocolError("Protocol became unreadable") from error
        if current != self.locked_bytes:
            raise DevBenchmarkProtocolError("Protocol bytes changed after lock")


def validate_protocol_file(
    path: Path,
    *,
    expected_sha256: Optional[str] = None,
    expected_base_commit: str = EXPECTED_BASE_COMMIT,
) -> ValidatedProtocol:
    if not path.is_file():
        raise DevBenchmarkProtocolError("Protocol file does not exist")
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DevBenchmarkProtocolError("Protocol is not valid UTF-8 JSON") from error
    checks = validate_protocol(value, expected_base_commit=expected_base_commit)
    digest = sha256_bytes(raw)
    if expected_sha256 is not None and digest != expected_sha256.lower():
        raise DevBenchmarkProtocolError("Protocol SHA does not match public lock")
    return ValidatedProtocol(path, value, digest, raw, checks)


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(canonical_json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_protocol(path: Path) -> ValidatedProtocol:
    _write_json_atomic(path, build_protocol())
    return validate_protocol_file(path)


def write_validation_result(
    path: Path,
    validated: ValidatedProtocol,
    *,
    forbidden_secrets: Iterable[str] = (),
) -> dict[str, Any]:
    secrets = tuple(item for item in forbidden_secrets if item)
    if any(item.encode("utf-8") in validated.locked_bytes for item in secrets):
        raise DevBenchmarkProtocolError("Protocol contains configured secret material")
    validated.assert_unchanged()
    result = {
        "artifact": "M4_04B2_DEV_BENCHMARK_PROTOCOL_VALIDATION_V1",
        "protocol_id": PROTOCOL_ID,
        "protocol_sha256": validated.sha256,
        **validated.checks,
        "secret_scan": "PASS",
    }
    _write_json_atomic(path, result)
    return result


def safe_case_projection(case: Mapping[str, Any]) -> dict[str, Any]:
    if set(case) & FORBIDDEN_CASE_FIELDS and not set(case) >= {"case_id"}:
        raise DevBenchmarkProtocolError("Development case is malformed")
    projected = {key: case[key] for key in ALLOWED_CASE_FIELDS if key in case}
    if projected.get("case_id") not in CASE_IDS:
        raise DevBenchmarkProtocolError("Unexpected development case id")
    serialized = json.dumps(projected, ensure_ascii=False).lower()
    if any(token in serialized for token in ('"gold_batch"', '"required_assertions"')):
        raise DevBenchmarkProtocolError("Gold-bearing field crossed the input projection")
    return projected


def extract_input_members_only(
    package_path: Path,
    destination: Path,
) -> dict[str, Any]:
    """Copy only the three preregistered DEV input members after Commit A."""
    if file_sha256(package_path) != DEV_PACKAGE_SHA256:
        raise DevBenchmarkProtocolError("Development package identity mismatch")
    destination.mkdir(parents=True, exist_ok=True)
    extracted: dict[str, str] = {}
    with zipfile.ZipFile(package_path) as archive:
        names = set(archive.namelist())
        for member in INPUT_MEMBERS:
            pure = PurePosixPath(member)
            if member not in names or pure.is_absolute() or ".." in pure.parts:
                raise DevBenchmarkProtocolError("Required safe input member is unavailable")
            data = archive.read(member)
            target = destination / pure.name
            if target.exists() and target.read_bytes() != data:
                raise DevBenchmarkProtocolError("Existing input-only copy differs")
            if not target.exists():
                temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
                temporary.write_bytes(data)
                os.replace(temporary, target)
            extracted[pure.name] = sha256_bytes(data)
    return {
        "artifact": "M4_04B2_DEV_INPUT_EXTRACTION_RESULT_V1",
        "dev_package_sha256": DEV_PACKAGE_SHA256,
        "dev_gold_opened": False,
        "extracted_members": extracted,
        "holdout_opened": False,
    }
