"""Canonical preregistration and fail-closed validation for M4-04B1D2."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional
import uuid

from tools.story_extraction.durable_research_executor_v1 import (
    DEFER_ELIGIBLE_CATEGORIES,
    DURABLE_EXECUTOR_VERSION,
    GLOBAL_MAX_PROVIDER_OPERATIONS,
    GLOBAL_ROLLING_WINDOW_SECONDS,
    MAX_EXECUTION_WINDOWS_PER_JOB,
    MAX_PROVIDER_ATTEMPTS_PER_JOB,
    MAX_PROVIDER_ATTEMPTS_PER_WINDOW,
    NON_DEFER_CATEGORIES,
    DurableJobSpec,
)


PROTOCOL_ID = "M4_04B1D2_DURABLE_CONFIRMATION_PROTOCOL_V1"
PROTOCOL_SCHEMA_VERSION = "M4_04B1D2_CONFIRMATION_PROTOCOL_SCHEMA_V1"
TASK_ID = "M4-04B1D2-DURABLE-EXECUTION-PROTOCOL-REPAIR-AND-CONFIRMATION"
EXPECTED_BASE_COMMIT = "ab1ce127378387d8afc05c3f36efd45a4fb7d215"
RUNTIME_VERSION = "GEMINI_TRANSPORT_RESILIENCE_V1_1"
LOCKED_CREDENTIAL_SLOT = "gemini_slot_3"
LOCKED_CREDENTIAL_TOPOLOGY = "UNKNOWN"
LOCKED_MODEL = "gemini-3.5-flash-lite"
JOB_COUNT = 12
CONCURRENCY = 1
OUTPUT_TOKEN_CAP = 128
WINDOW_COOLDOWN_SECONDS = 60
SYSTEM_PROMPT = "Return only the requested valid JSON object and no additional text."
USER_PROMPT_TEMPLATE = 'Return exactly: {"status":"ok","durable_sequence":<SEQUENCE>}'
SCHEMA_RESPONSE_MODE = "PROVIDER_JSON_MIME_NO_OUTPUT_AWARE_RETRY"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


class ConfirmationProtocolError(RuntimeError):
    """The confirmation protocol is absent, invalid, inconsistent, or mutated."""


def build_confirmation_specs() -> list[DurableJobSpec]:
    """Build the exact preregistered synthetic workload."""
    safe_model = LOCKED_MODEL.replace(".", "_").replace("-", "_")
    return [
        DurableJobSpec(
            job_id=f"M4B1D2_{safe_model}_{index:02d}",
            model=LOCKED_MODEL,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=USER_PROMPT_TEMPLATE.replace("<SEQUENCE>", str(index)),
            generation_config={
                "temperature": 0,
                "max_output_tokens": OUTPUT_TOKEN_CAP,
            },
            schema_response_mode=SCHEMA_RESPONSE_MODE,
            credential_slot=LOCKED_CREDENTIAL_SLOT,
            research_task_id=TASK_ID,
        )
        for index in range(1, JOB_COUNT + 1)
    ]


def build_confirmation_protocol(
    base_commit: str = EXPECTED_BASE_COMMIT,
) -> dict[str, Any]:
    """Return the sole accepted semantic content for the confirmation protocol."""
    specs = build_confirmation_specs()
    return {
        "base_commit": base_commit,
        "concurrency": CONCURRENCY,
        "cooldown_policy": {
            "minimum_seconds": WINDOW_COOLDOWN_SECONDS,
            "retry_after_wins_if_longer": True,
        },
        "credential_slot": LOCKED_CREDENTIAL_SLOT,
        "credential_topology": LOCKED_CREDENTIAL_TOPOLOGY,
        "defer_eligible_categories": sorted(DEFER_ELIGIBLE_CATEGORIES),
        "durable_executor_version": DURABLE_EXECUTOR_VERSION,
        "first_success_lock_policy": {
            "mode": "IMMUTABLE_LOCK",
            "provider_calls_after_success": 0,
        },
        "generation_config": {
            "max_output_tokens": OUTPUT_TOKEN_CAP,
            "temperature": 0,
        },
        "global_pacing": {
            "max_provider_operations": GLOBAL_MAX_PROVIDER_OPERATIONS,
            "persistence": "RESTART_SAFE",
            "rolling_window_seconds": int(GLOBAL_ROLLING_WINDOW_SECONDS),
        },
        "holdout_access_policy": {
            "development_extraction_data": "FORBIDDEN",
            "holdout_gold": "FORBIDDEN",
            "holdout_input": "FORBIDDEN",
            "synthetic_only": True,
        },
        "job_count": JOB_COUNT,
        "max_provider_attempts_per_job": MAX_PROVIDER_ATTEMPTS_PER_JOB,
        "max_provider_attempts_per_window": MAX_PROVIDER_ATTEMPTS_PER_WINDOW,
        "max_windows_per_job": MAX_EXECUTION_WINDOWS_PER_JOB,
        "model": LOCKED_MODEL,
        "non_defer_categories": sorted(NON_DEFER_CATEGORIES),
        "output_aware_retry": "FORBIDDEN",
        "pass_rule": {
            "all_invariants_required": True,
            "required_succeeded_locked": JOB_COUNT,
            "terminal_failures_allowed": 0,
        },
        "protocol_id": PROTOCOL_ID,
        "protocol_schema_version": PROTOCOL_SCHEMA_VERSION,
        "request_fingerprints": {
            spec.job_id: spec.request_fingerprint for spec in specs
        },
        "runtime_version": RUNTIME_VERSION,
        "schema_response_mode": SCHEMA_RESPONSE_MODE,
        "stop_rule": {
            "alternate_protocol_after_result": "FORBIDDEN",
            "batch_rerun": "FORBIDDEN",
            "terminal_failed_after_third_window": "CONFIRMATION_FAIL",
        },
        "system_prompt_sha256": _sha256_text(SYSTEM_PROMPT),
        "task_id": TASK_ID,
        "user_prompt_template_sha256": _sha256_text(USER_PROMPT_TEMPLATE),
    }


# A machine-readable shape declaration accompanies the strict semantic validator.
# The semantic validator below additionally requires exact values and nested keys.
CONFIRMATION_PROTOCOL_SCHEMA_V1: dict[str, Any] = {
    "$id": PROTOCOL_SCHEMA_VERSION,
    "type": "object",
    "additionalProperties": False,
    "required": sorted(build_confirmation_protocol().keys()),
    "properties": {
        key: {"type": "integer"}
        if key
        in {
            "concurrency",
            "job_count",
            "max_provider_attempts_per_job",
            "max_provider_attempts_per_window",
            "max_windows_per_job",
        }
        else {"type": "array"}
        if key in {"defer_eligible_categories", "non_defer_categories"}
        else {"type": "object"}
        if key
        in {
            "cooldown_policy",
            "first_success_lock_policy",
            "generation_config",
            "global_pacing",
            "holdout_access_policy",
            "pass_rule",
            "request_fingerprints",
            "stop_rule",
        }
        else {"type": "string"}
        for key in build_confirmation_protocol()
    },
}


def _is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_schema(protocol: Any) -> None:
    if not isinstance(protocol, dict):
        raise ConfirmationProtocolError("Protocol root must be a JSON object")
    expected_keys = set(CONFIRMATION_PROTOCOL_SCHEMA_V1["required"])
    actual_keys = set(protocol)
    missing = sorted(expected_keys - actual_keys)
    unknown = sorted(actual_keys - expected_keys)
    if missing:
        raise ConfirmationProtocolError(
            "Protocol schema missing required field: " + missing[0]
        )
    if unknown:
        raise ConfirmationProtocolError(
            "Protocol schema contains unknown field: " + unknown[0]
        )
    for name, declaration in CONFIRMATION_PROTOCOL_SCHEMA_V1["properties"].items():
        value = protocol[name]
        expected_type = declaration["type"]
        valid = {
            "integer": _is_integer(value),
            "array": isinstance(value, list),
            "object": isinstance(value, dict),
            "string": isinstance(value, str),
        }[expected_type]
        if not valid:
            raise ConfirmationProtocolError(
                f"Protocol field has wrong type: {name}"
            )


def _first_difference(expected: Any, actual: Any, path: str = "protocol") -> str:
    if type(expected) is not type(actual):
        return path
    if isinstance(expected, dict):
        for key in expected:
            if key not in actual:
                return f"{path}.{key}"
            difference = _first_difference(expected[key], actual[key], f"{path}.{key}")
            if difference:
                return difference
        for key in actual:
            if key not in expected:
                return f"{path}.{key}"
        return ""
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return path
        for index, (expected_item, actual_item) in enumerate(zip(expected, actual)):
            difference = _first_difference(
                expected_item, actual_item, f"{path}[{index}]"
            )
            if difference:
                return difference
        return ""
    return "" if expected == actual else path


def validate_confirmation_protocol(
    protocol: Any,
    *,
    expected_base_commit: str = EXPECTED_BASE_COMMIT,
) -> dict[str, str]:
    """Validate shape, fixed semantics, and all generated job fingerprints."""
    _validate_schema(protocol)
    expected = build_confirmation_protocol(expected_base_commit)

    fingerprints = protocol["request_fingerprints"]
    expected_fingerprints = expected["request_fingerprints"]
    if fingerprints != expected_fingerprints:
        raise ConfirmationProtocolError("Protocol request fingerprints do not match jobs")

    difference = _first_difference(expected, protocol)
    if difference:
        raise ConfirmationProtocolError(
            f"Protocol semantic consistency mismatch: {difference}"
        )
    return {
        "parse": "PASS",
        "schema": "PASS",
        "semantic_consistency": "PASS",
        "fingerprints": "PASS",
    }


@dataclass(frozen=True)
class ValidatedConfirmationProtocol:
    path: Path
    protocol: Mapping[str, Any]
    protocol_sha256: str
    locked_bytes: bytes
    checks: Mapping[str, str]

    def assert_byte_identical(self) -> None:
        try:
            current = self.path.read_bytes()
        except OSError as error:
            raise ConfirmationProtocolError(
                "Protocol disappeared or became unreadable during execution"
            ) from error
        if current != self.locked_bytes:
            raise ConfirmationProtocolError(
                "Protocol bytes changed after validation lock"
            )


def validate_confirmation_protocol_file(
    path: Path,
    *,
    expected_base_commit: str = EXPECTED_BASE_COMMIT,
    expected_sha256: Optional[str] = None,
) -> ValidatedConfirmationProtocol:
    """Parse and validate before hashing, then optionally match the public lock."""
    if not path.is_file():
        raise ConfirmationProtocolError("Protocol file does not exist")
    try:
        locked_bytes = path.read_bytes()
        protocol = json.loads(locked_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ConfirmationProtocolError("Protocol is not valid UTF-8 JSON") from error

    checks = validate_confirmation_protocol(
        protocol, expected_base_commit=expected_base_commit
    )
    # The digest is deliberately calculated only after successful validation.
    protocol_sha256 = _sha256_bytes(locked_bytes)
    if expected_sha256 is not None and protocol_sha256 != expected_sha256.lower():
        raise ConfirmationProtocolError("Protocol hash does not match public lock")
    return ValidatedConfirmationProtocol(
        path=path,
        protocol=protocol,
        protocol_sha256=protocol_sha256,
        locked_bytes=locked_bytes,
        checks=checks,
    )


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_canonical_confirmation_protocol(
    path: Path,
    *,
    base_commit: str = EXPECTED_BASE_COMMIT,
) -> ValidatedConfirmationProtocol:
    """Programmatically serialize and immediately validate the canonical protocol."""
    _write_json_atomic(path, build_confirmation_protocol(base_commit))
    return validate_confirmation_protocol_file(
        path, expected_base_commit=base_commit
    )


def build_protocol_validation_result(
    validated: ValidatedConfirmationProtocol,
    *,
    forbidden_secrets: Iterable[str] = (),
) -> dict[str, Any]:
    """Build the private pre-live validation evidence without exposing secrets."""
    secrets = tuple(value for value in forbidden_secrets if value)
    if any(value.encode("utf-8") in validated.locked_bytes for value in secrets):
        raise ConfirmationProtocolError("Protocol secret scan failed")
    validated.assert_byte_identical()
    return {
        "artifact": "M4_04B1D2_PROTOCOL_VALIDATION_RESULT_V1",
        "base_commit": validated.protocol["base_commit"],
        "fingerprints": validated.checks["fingerprints"],
        "parse": validated.checks["parse"],
        "protocol_id": validated.protocol["protocol_id"],
        "protocol_sha256": validated.protocol_sha256,
        "schema": validated.checks["schema"],
        "secret_scan": "PASS",
        "semantic_consistency": validated.checks["semantic_consistency"],
    }


def write_protocol_validation_result(
    path: Path,
    validated: ValidatedConfirmationProtocol,
    *,
    forbidden_secrets: Iterable[str] = (),
) -> dict[str, Any]:
    result = build_protocol_validation_result(
        validated, forbidden_secrets=forbidden_secrets
    )
    _write_json_atomic(path, result)
    return result
