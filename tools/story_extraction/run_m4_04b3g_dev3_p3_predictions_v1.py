"""Fail-closed future blind runner core for locked DEV3 P3 predictions.

This module has no provider implementation, credential loader, gold reader, or
evaluator import. Offline readiness tests inject an in-memory provider. A future
authorized task may attach the accepted durable transport only after preflight.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Protocol, Sequence
import zipfile

from tools.story_extraction.draft_compiler_v1 import DraftCompilerContext
from tools.story_extraction.draft_compiler_v1_1 import (
    DraftCompilationErrorV1_1,
    compile_story_extraction_draft_v1_1,
    validate_draft_v1_1,
)
from tools.story_extraction.durable_research_executor_v1 import DurableJobSpec
from tools.story_extraction.m4_04b3f_dev3_p3_protocol_v1 import (
    CASE_IDS,
    CONCURRENCY,
    CREDENTIAL_SLOT,
    DEV3_INPUT_SHA256,
    EXPECTED_BASE_COMMIT,
    MODEL,
    REPAIR_ELIGIBLE_CATEGORIES,
    SCHEMA_RESPONSE_MODE,
    TEMPERATURE,
    Dev3ProtocolError,
    build_primary_spec,
    build_repair_spec,
    sanitize_all_blockers,
    sha256_bytes,
    validate_protocol_file,
)


RUNNER_ID = "M4_04B3G_DEV3_P3_BLIND_RUNNER_V1"
LOCKED_PROTOCOL_SHA256 = "f9cf1c25a21bb3bfc910b8e218c8dac9f032d67957f8d7cb58397134a0504bae"


class Dev3RunnerError(RuntimeError):
    """Fail-closed runner, access, or immutable-success violation."""


@dataclass(frozen=True)
class CaseInput:
    case_id: str
    prepared_input: Mapping[str, Any]
    compiler_context: DraftCompilerContext


@dataclass(frozen=True)
class ProviderFirstSuccess:
    """The provider adapter's immutable first successful response."""

    raw_response: str
    provider_operations: int
    success_identity: str


class FirstSuccessProvider(Protocol):
    actual_provider_operations: int

    def first_success(self, spec: DurableJobSpec) -> ProviderFirstSuccess:
        ...


class OfflineMockProvider:
    """In-memory provider for synthetic tests; it performs zero real operations."""

    actual_provider_operations = 0

    def __init__(self, responses: Mapping[str, str]):
        self._responses = dict(responses)
        self.calls: list[str] = []

    def first_success(self, spec: DurableJobSpec) -> ProviderFirstSuccess:
        _assert_locked_job_spec(spec)
        if spec.job_id not in self._responses:
            raise Dev3RunnerError("Mock response is not preregistered")
        if spec.job_id in self.calls:
            raise Dev3RunnerError("A locked job cannot be invoked twice")
        self.calls.append(spec.job_id)
        raw = self._responses[spec.job_id]
        return ProviderFirstSuccess(
            raw_response=raw,
            provider_operations=0,
            success_identity=sha256_bytes(raw.encode("utf-8")),
        )


class FirstSuccessLedger:
    """Locks the first successful response identity for every request fingerprint."""

    def __init__(self):
        self._locked: dict[str, tuple[str, str]] = {}

    def lock(self, spec: DurableJobSpec, success: ProviderFirstSuccess) -> str:
        if not isinstance(success.raw_response, str) or not success.raw_response:
            raise Dev3RunnerError("First success must contain one non-empty response")
        if success.provider_operations < 0:
            raise Dev3RunnerError("Provider operation count is invalid")
        identity = sha256_bytes(success.raw_response.encode("utf-8"))
        if identity != success.success_identity:
            raise Dev3RunnerError("First-success response identity mismatch")
        locked = (spec.request_fingerprint, identity)
        previous = self._locked.setdefault(spec.job_id, locked)
        if previous != locked:
            raise Dev3RunnerError("Immutable first-success lock mismatch")
        return success.raw_response


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_member_name(member: str) -> PurePosixPath:
    path = PurePosixPath(member)
    if (
        not member
        or path.is_absolute()
        or path.as_posix() != member
        or ".." in path.parts
        or any("gold" in part.lower() for part in path.parts)
    ):
        raise Dev3RunnerError("Input archive member is forbidden")
    return path


def verify_locked_protocol(protocol_path: Path) -> Mapping[str, Any]:
    """Verify the exact B3F protocol before any input or provider operation."""
    try:
        validated = validate_protocol_file(
            protocol_path,
            expected_sha256=LOCKED_PROTOCOL_SHA256,
            expected_base_commit=EXPECTED_BASE_COMMIT,
        )
    except (Dev3ProtocolError, OSError) as error:
        raise Dev3RunnerError("Locked P3 protocol verification failed") from error
    return validated.value


def verify_dev3_input_archive(input_archive: Path) -> tuple[str, ...]:
    """Verify the authorized package hash before inspecting its member inventory."""
    if any("gold" in part.lower() for part in input_archive.parts):
        raise Dev3RunnerError("Gold-like input path is forbidden")
    try:
        actual = _sha256_file(input_archive)
    except OSError as error:
        raise Dev3RunnerError("DEV3 input archive is unavailable") from error
    if actual != DEV3_INPUT_SHA256:
        raise Dev3RunnerError("DEV3 input archive hash mismatch")
    try:
        with zipfile.ZipFile(input_archive) as archive:
            names = [item.filename for item in archive.infolist() if not item.is_dir()]
    except (OSError, zipfile.BadZipFile) as error:
        raise Dev3RunnerError("Authorized DEV3 input archive is unreadable") from error
    if not names or len(names) != len(set(names)):
        raise Dev3RunnerError("DEV3 input inventory is empty or duplicated")
    for name in names:
        _validate_member_name(name)
    return tuple(names)


def preflight(*, protocol_path: Path, input_archive: Path) -> dict[str, Any]:
    """Perform the two immutable hash gates; accepts no gold or evaluator path."""
    protocol = verify_locked_protocol(protocol_path)
    members = verify_dev3_input_archive(input_archive)
    return {
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": LOCKED_PROTOCOL_SHA256,
        "input_sha256": DEV3_INPUT_SHA256,
        "member_count": len(members),
        "provider_operations": 0,
    }


def _assert_locked_job_spec(spec: DurableJobSpec) -> None:
    expected_generation = {"temperature": TEMPERATURE, "max_output_tokens": 16384}
    if (
        spec.model != MODEL
        or spec.credential_slot != CREDENTIAL_SLOT
        or dict(spec.generation_config) != expected_generation
        or spec.schema_response_mode != SCHEMA_RESPONSE_MODE
    ):
        raise Dev3RunnerError("Model, credential, or generation settings differ from P3")


def _validation_failure(category: str, blockers: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    if category not in REPAIR_ELIGIBLE_CATEGORIES:
        raise Dev3RunnerError("Non-structural retry category is forbidden")
    return {
        "pass": False,
        "category": category,
        "blockers": sanitize_all_blockers(blockers),
    }


def compile_raw_response(raw: str, case: CaseInput) -> tuple[Any, Any, dict[str, Any]]:
    """Parse, validate, and compile while returning every sanitized blocker."""
    try:
        draft = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None, None, _validation_failure(
            "JSON_PARSE_FAILURE",
            [{"phase": "JSON", "code": "JSON_PARSE_FAILURE", "path": "$"}],
        )
    try:
        validate_draft_v1_1(draft)
    except DraftCompilationErrorV1_1 as error:
        return draft, None, _validation_failure(
            "DRAFT_SCHEMA_FAILURE", [item.as_dict() for item in error.blockers]
        )
    try:
        batch = compile_story_extraction_draft_v1_1(draft, case.compiler_context)
    except DraftCompilationErrorV1_1 as error:
        return draft, None, _validation_failure(
            "DRAFT_COMPILER_FAILURE", [item.as_dict() for item in error.blockers]
        )
    return draft, batch, {"pass": True, "category": None, "blockers": []}


def _invoke_first_success(
    provider: FirstSuccessProvider,
    ledger: FirstSuccessLedger,
    spec: DurableJobSpec,
    *,
    offline_only: bool,
) -> str:
    _assert_locked_job_spec(spec)
    before = provider.actual_provider_operations
    success = provider.first_success(spec)
    after = provider.actual_provider_operations
    if after - before != success.provider_operations:
        raise Dev3RunnerError("Provider operation telemetry mismatch")
    if offline_only and (success.provider_operations != 0 or after != 0):
        raise Dev3RunnerError("Offline readiness forbids provider operations")
    return ledger.lock(spec, success)


def execute_case(
    case: CaseInput,
    provider: FirstSuccessProvider,
    *,
    ledger: FirstSuccessLedger | None = None,
    offline_only: bool = True,
) -> dict[str, Any]:
    """Execute one loaded case; at most one structure-only repair can be constructed."""
    if case.case_id not in CASE_IDS:
        raise Dev3RunnerError("Case is outside the locked DEV3 order")
    active_ledger = ledger or FirstSuccessLedger()
    before = provider.actual_provider_operations

    primary_spec = build_primary_spec(case.case_id, case.prepared_input)
    primary_raw = _invoke_first_success(
        provider, active_ledger, primary_spec, offline_only=offline_only
    )
    _, batch, primary_validation = compile_raw_response(primary_raw, case)
    repair_count = 0
    repair_validation = None

    if not primary_validation["pass"]:
        category = primary_validation["category"]
        if category not in REPAIR_ELIGIBLE_CATEGORIES:
            raise Dev3RunnerError("Semantic or quality retry is forbidden")
        repair_count = 1
        repair_spec = build_repair_spec(
            case.case_id,
            case.prepared_input,
            primary_raw,
            category,
            primary_validation["blockers"],
        )
        repair_raw = _invoke_first_success(
            provider, active_ledger, repair_spec, offline_only=offline_only
        )
        _, batch, repair_validation = compile_raw_response(repair_raw, case)

    terminal_validation = repair_validation or primary_validation
    terminal_status = "STRUCTURAL_VALID" if terminal_validation["pass"] else "STRUCTURAL_FAILURE"
    return {
        "case_id": case.case_id,
        "primary_request_fingerprint": primary_spec.request_fingerprint,
        "repair_count": repair_count,
        "terminal_status": terminal_status,
        "terminal_validation": terminal_validation,
        "compiled_batch": batch,
        "actual_provider_operations": provider.actual_provider_operations - before,
        "quality_or_coverage_retries": 0,
    }


def execute_loaded_cases(
    *,
    protocol_path: Path,
    input_archive: Path,
    cases: Sequence[CaseInput],
    provider: FirstSuccessProvider,
    offline_only: bool = False,
) -> list[dict[str, Any]]:
    """Future authorized entrypoint; protocol and input hashes precede all calls."""
    preflight(protocol_path=protocol_path, input_archive=input_archive)
    if [case.case_id for case in cases] != list(CASE_IDS):
        raise Dev3RunnerError("Loaded DEV3 case order differs from the lock")
    ledger = FirstSuccessLedger()
    return [
        execute_case(case, provider, ledger=ledger, offline_only=offline_only)
        for case in cases
    ]
