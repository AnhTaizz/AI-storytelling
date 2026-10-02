"""Run the locked M4-04B1D2 Flash-Lite durable confirmation exactly once."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, Callable, Mapping, Optional
import uuid

from tools.story_extraction.durable_research_executor_v1 import (
    CheckpointIntegrityError,
    CooldownPending,
    DurableJobSpec,
    DurableResearchExecutor,
    DurableTransportFailure,
    JobState,
    PersistentRollingOperationPacer,
    summarize_job,
)
from tools.story_extraction.gemini_key_pool_v1 import (
    GeminiKeyPool,
    GeminiRuntimeConfig,
    load_runtime_config,
)
from tools.story_extraction.gemini_resilience_v1 import ProjectLimit
from tools.story_extraction.gemini_resilience_v1_1 import (
    GeminiResilienceV11Error,
    GeminiResilientTransportV11,
    ResiliencePolicyV11,
)
from tools.story_extraction.gemini_transport_v1 import official_client_factory
from tools.story_extraction.m4_04b1d2_confirmation_protocol_v1 import (
    CONCURRENCY,
    EXPECTED_BASE_COMMIT,
    JOB_COUNT,
    LOCKED_CREDENTIAL_SLOT,
    LOCKED_CREDENTIAL_TOPOLOGY,
    LOCKED_MODEL,
    OUTPUT_TOKEN_CAP,
    PROTOCOL_ID,
    RUNTIME_VERSION,
    TASK_ID,
    WINDOW_COOLDOWN_SECONDS,
    ConfirmationProtocolError,
    ValidatedConfirmationProtocol,
    build_confirmation_specs,
    validate_confirmation_protocol_file,
)


RUNNER_VERSION = "M4_GEMINI_DURABLE_CONFIRMATION_RUNNER_V1"
QUALIFIED_STATUS = (
    "M4_04B1D2_DURABLE_PROFILE_QUALIFIED_PENDING_ORCHESTRATOR_REVIEW"
)
FAILED_STATUS = "M4_04B1D2_DURABLE_CONFIRMATION_FAILED"
PROTOCOL_FAILED_STATUS = "M4_04B1D2_PROTOCOL_VALIDATION_FAILED"
WAITING_STATUS = "M4_04B1D2_WAITING_FOR_CREDENTIAL"
RUNTIME_DEFECT_STATUS = "M4_04B1D2_RUNTIME_DEFECT_FOUND"
LOCAL_RPM = 6
LOCAL_TPM = 3000


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
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


class ConfirmationCredentialUnavailable(RuntimeError):
    """The one locked slot is not present exactly once."""


def _validate_private_validation_result(
    path: Path, validated: ValidatedConfirmationProtocol
) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ConfirmationProtocolError(
            "Pre-live protocol validation result is absent or invalid"
        ) from error
    required = {
        "artifact": "M4_04B1D2_PROTOCOL_VALIDATION_RESULT_V1",
        "base_commit": EXPECTED_BASE_COMMIT,
        "fingerprints": "PASS",
        "parse": "PASS",
        "protocol_id": PROTOCOL_ID,
        "protocol_sha256": validated.protocol_sha256,
        "schema": "PASS",
        "secret_scan": "PASS",
        "semantic_consistency": "PASS",
    }
    if value != required:
        raise ConfirmationProtocolError(
            "Pre-live protocol validation result does not match locked protocol"
        )
    return value


@dataclass(frozen=True)
class PreparedConfirmationRun:
    validated: ValidatedConfirmationProtocol
    config: GeminiRuntimeConfig
    credential: Any


def prepare_confirmation_run(
    *,
    protocol_path: Path,
    validation_result_path: Path,
    expected_protocol_sha256: str,
    expected_base_commit: str = EXPECTED_BASE_COMMIT,
    config_loader: Callable[[], GeminiRuntimeConfig] = load_runtime_config,
) -> PreparedConfirmationRun:
    """Finish every fail-closed protocol gate before loading a credential."""
    validated = validate_confirmation_protocol_file(
        protocol_path,
        expected_base_commit=expected_base_commit,
        expected_sha256=expected_protocol_sha256,
    )
    _validate_private_validation_result(validation_result_path, validated)
    validated.assert_byte_identical()
    config = config_loader()
    selected = [
        item for item in config.credentials if item.slot_id == LOCKED_CREDENTIAL_SLOT
    ]
    if len(selected) != 1:
        raise ConfirmationCredentialUnavailable(
            "Locked credential slot is not configured exactly once"
        )
    return PreparedConfirmationRun(validated, config, selected[0])


class _ProtocolGuardedClient:
    def __init__(self, client: Any, guard: Callable[[], None]) -> None:
        self._client = client
        self._guard = guard

    def generate(self, **kwargs: Any) -> Any:
        self._guard()
        response = self._client.generate(**kwargs)
        self._guard()
        return response


class GeminiConfirmationWindowTransport:
    """One V1.1 runtime instance per durable window with protocol byte guards."""

    def __init__(
        self,
        credential: Any,
        pacer: PersistentRollingOperationPacer,
        protocol_guard: Callable[[], None],
    ) -> None:
        self.credential = credential
        self.pacer = pacer
        self.protocol_guard = protocol_guard

    def __call__(
        self, spec: DurableJobSpec, window_number: int, request_id: str
    ) -> dict[str, Any]:
        del window_number
        self.protocol_guard()
        if spec.credential_slot != self.credential.slot_id:
            raise CheckpointIntegrityError("Confirmation credential lock mismatch")
        pool = GeminiKeyPool((self.credential,))
        global_waits: list[float] = []

        def client_factory(api_key: str) -> _ProtocolGuardedClient:
            self.protocol_guard()
            wait_seconds = float(self.pacer.acquire())
            self.protocol_guard()
            global_waits.append(wait_seconds)
            client = official_client_factory(api_key)
            return _ProtocolGuardedClient(client, self.protocol_guard)

        policy = ResiliencePolicyV11(
            max_total_provider_attempts=3,
            max_transport_retries=2,
            max_credential_failovers=0,
            max_project_group_failovers=0,
            max_concurrency=CONCURRENCY,
            queue_capacity=2,
            queue_wait_timeout_seconds=300,
            default_project_limit=ProjectLimit(rpm=LOCAL_RPM, tpm=LOCAL_TPM),
            max_local_rate_wait_seconds=300,
            max_scheduler_wait_seconds=300,
            base_backoff_seconds=1,
            max_backoff_seconds=30,
            backoff_jitter_ratio=0.20,
            circuit_failure_threshold=3,
            circuit_open_cooldown_seconds=30,
            half_open_probe_requests=1,
        )
        gate = GeminiResilientTransportV11(
            pool, client_factory=client_factory, policy=policy
        )
        try:
            result = gate.generate(
                spec.system_prompt,
                spec.user_prompt,
                spec.model,
                dict(spec.generation_config),
                request_id,
            )
        except GeminiResilienceV11Error as error:
            # Mutation exceptions raised inside the accepted runtime are checked
            # again here and therefore cannot be converted into durable retries.
            self.protocol_guard()
            attempts = [dict(item) for item in error.attempts]
            if len(attempts) != len(global_waits):
                raise CheckpointIntegrityError(
                    "Persistent pacing does not match failed provider attempts"
                ) from None
            for attempt, wait_seconds in zip(attempts, global_waits):
                attempt["global_safety_wait_seconds"] = round(wait_seconds, 6)
            retry_after_values = [
                float(item["retry_after_seconds"])
                for item in attempts
                if isinstance(item.get("retry_after_seconds"), (int, float))
            ]
            raise DurableTransportFailure(
                error.category.value,
                provider_attempts=error.provider_attempts,
                fingerprint=error.fingerprint,
                attempts=attempts,
                retry_after_seconds=max(retry_after_values, default=None),
            ) from None
        self.protocol_guard()
        attempts = [dict(item) for item in result.get("transport_attempts", [])]
        if len(attempts) != len(global_waits):
            raise CheckpointIntegrityError(
                "Persistent pacing does not match successful provider attempts"
            )
        for attempt, wait_seconds in zip(attempts, global_waits):
            attempt["global_safety_wait_seconds"] = round(wait_seconds, 6)
        result["transport_attempts"] = attempts
        return result


def _summary(
    specs: list[DurableJobSpec], executor: DurableResearchExecutor
) -> dict[str, Any]:
    jobs = [summarize_job(executor.load_job(spec)) for spec in specs]
    attempt_categories: Counter[str] = Counter()
    http_statuses: Counter[str] = Counter()
    failure_fingerprints: Counter[str] = Counter()
    reported_versions: set[str] = set()
    for item in jobs:
        attempt_categories.update(item["provider_attempt_categories"])
        http_statuses.update(item["provider_http_status_counts"])
        failure_fingerprints.update(item["failure_fingerprints"])
        if item.get("model_reported_version"):
            reported_versions.add(str(item["model_reported_version"]))

    success_count = sum(
        item["state"] == JobState.SUCCEEDED_LOCKED.value for item in jobs
    )
    terminal_count = sum(
        item["state"] == JobState.TERMINAL_FAILED.value for item in jobs
    )
    fingerprints = {spec.job_id: spec.request_fingerprint for spec in specs}
    fingerprint_mutations = sum(
        item["request_fingerprint"] != fingerprints[item["job_id"]] for item in jobs
    )
    attempt_cap_violations = sum(
        int(item["windows_used"]) > 3
        or int(item["total_provider_operations"]) > 9
        or any(int(value) > 3 for value in item["provider_attempts_per_window"])
        for item in jobs
    )
    invariant_pass = all(
        (
            all(item["credential_slot"] == LOCKED_CREDENTIAL_SLOT for item in jobs),
            all(item["model"] == LOCKED_MODEL for item in jobs),
            all(int(item["success_lock_count"]) <= 1 for item in jobs),
            fingerprint_mutations == 0,
            attempt_cap_violations == 0,
        )
    )
    return {
        "model": LOCKED_MODEL,
        "credential_slot": LOCKED_CREDENTIAL_SLOT,
        "jobs": JOB_COUNT,
        "eventual_successes": success_count,
        "terminal_failures": terminal_count,
        "unfinished_jobs": JOB_COUNT - success_count - terminal_count,
        "execution_windows": sum(int(item["windows_used"]) for item in jobs),
        "provider_attempts": sum(
            int(item["total_provider_operations"]) for item in jobs
        ),
        "server_failure_503": http_statuses["503"],
        "other_5xx": sum(
            count
            for status, count in http_statuses.items()
            if status.startswith("5") and status != "503"
        ),
        "rate_limit_429": http_statuses["429"],
        "timeouts": attempt_categories["TIMEOUT"],
        "network_failures": attempt_categories["NETWORK_FAILURE"],
        "provider_failures": attempt_categories["PROVIDER_FAILURE"],
        "auth_failures": attempt_categories["AUTH_FAILURE"],
        "deferred_count": sum(int(item["deferred_count"]) for item in jobs),
        "resumed_count": sum(int(item["resumed_count"]) for item in jobs),
        "success_locks": sum(int(item["success_lock_count"]) for item in jobs),
        "calls_after_success_lock": 0,
        "duplicate_success_calls": 0,
        "response_comparison_count": 0,
        "best_of_n_selection_count": 0,
        "output_aware_retry_count": 0,
        "credential_switch_count": 0,
        "model_switch_count": 0,
        "request_fingerprint_mutation_count": fingerprint_mutations,
        "attempt_cap_violation_count": attempt_cap_violations,
        "uncaught_exception_count": 0,
        "runtime_invariants": "PASS" if invariant_pass else "FAIL",
        "failure_fingerprints": dict(sorted(failure_fingerprints.items())),
        "provider_reported_versions": sorted(reported_versions),
        "job_results": jobs,
    }


def _run_jobs(
    *,
    specs: list[DurableJobSpec],
    executor: DurableResearchExecutor,
    transport: GeminiConfirmationWindowTransport,
) -> dict[str, Any]:
    for spec in specs:
        executor.ensure_job(spec)
    while True:
        progressed = False
        cooldowns: list[float] = []
        for spec in specs:
            record = executor.load_job(spec)
            state = JobState(record["state"])
            if state in {JobState.SUCCEEDED_LOCKED, JobState.TERMINAL_FAILED}:
                continue
            try:
                record = executor.execute_window(spec, transport)
                progressed = True
                print(
                    f"{spec.job_id} window={record['window_count']} "
                    f"state={record['state']}",
                    flush=True,
                )
                if record["state"] == JobState.TERMINAL_FAILED.value:
                    return _summary(specs, executor)
            except CooldownPending as pending:
                cooldowns.append(pending.remaining_seconds)

        summary = _summary(specs, executor)
        if summary["eventual_successes"] == JOB_COUNT:
            return summary
        if summary["terminal_failures"] > 0:
            return summary
        if not progressed:
            if not cooldowns:
                raise CheckpointIntegrityError("Confirmation scheduler made no progress")
            wait_seconds = max(0.001, min(cooldowns))
            print(f"Deferred cooldown wait={wait_seconds:.3f}s", flush=True)
            time.sleep(wait_seconds)


def _base_result(
    *,
    protocol_sha256: str,
    lock_commit: str,
    status: str,
) -> dict[str, Any]:
    return {
        "task_id": TASK_ID,
        "runner": RUNNER_VERSION,
        "completed_at_utc": _utc_now(),
        "base_commit": EXPECTED_BASE_COMMIT,
        "lock_commit_sha": lock_commit,
        "status": status,
        "protocol_id": PROTOCOL_ID,
        "protocol_sha256": protocol_sha256,
        "runtime": RUNTIME_VERSION,
        "durable_executor": "DURABLE_RESEARCH_EXECUTOR_V1",
        "credential_slot": LOCKED_CREDENTIAL_SLOT,
        "credential_topology": LOCKED_CREDENTIAL_TOPOLOGY,
        "model": LOCKED_MODEL,
        "job_count": JOB_COUNT,
        "holdout": {
            "input_opened": False,
            "gold_opened": False,
            "predictions_run": False,
            "contamination": "CLEAN",
        },
        "research_state": {
            "extraction_quality_model": "NOT_SELECTED",
            "extractor": "NOT_LOCKED",
            "m4_04b2": "NOT_STARTED",
            "m5": "NOT_STARTED",
        },
    }


def execute(
    *,
    protocol_path: Path,
    validation_result_path: Path,
    expected_protocol_sha256: str,
    lock_commit: str,
    checkpoint_directory: Path,
    result_path: Path,
    profile_path: Path,
    config_loader: Callable[[], GeminiRuntimeConfig] = load_runtime_config,
) -> dict[str, Any]:
    """Execute the one locked batch; protocol gates precede every provider object."""
    try:
        prepared = prepare_confirmation_run(
            protocol_path=protocol_path,
            validation_result_path=validation_result_path,
            expected_protocol_sha256=expected_protocol_sha256,
            config_loader=config_loader,
        )
    except ConfirmationCredentialUnavailable:
        result = _base_result(
            protocol_sha256=expected_protocol_sha256,
            lock_commit=lock_commit,
            status=WAITING_STATUS,
        )
        _write_json(result_path, result)
        return result

    validated = prepared.validated
    specs = build_confirmation_specs()
    pacer = PersistentRollingOperationPacer(
        checkpoint_directory / "global_pacing.json"
    )
    executor = DurableResearchExecutor(
        checkpoint_directory / "jobs",
        protocol_id=f"{PROTOCOL_ID}:{validated.protocol_sha256}",
        window_cooldown_seconds=WINDOW_COOLDOWN_SECONDS,
        forbidden_secrets=tuple(
            item._api_key for item in prepared.config.credentials
        ),
    )
    transport = GeminiConfirmationWindowTransport(
        prepared.credential, pacer, validated.assert_byte_identical
    )
    summary: Optional[dict[str, Any]] = None
    status = RUNTIME_DEFECT_STATUS
    try:
        summary = _run_jobs(
            specs=specs,
            executor=executor,
            transport=transport,
        )
        validated.assert_byte_identical()
        pacing = pacer.snapshot()
        if pacing["invariant"] != "PASS" or summary["runtime_invariants"] != "PASS":
            status = RUNTIME_DEFECT_STATUS
        elif summary["auth_failures"] > 0:
            status = WAITING_STATUS
        elif (
            summary["eventual_successes"] == JOB_COUNT
            and summary["terminal_failures"] == 0
        ):
            status = QUALIFIED_STATUS
        else:
            status = FAILED_STATUS
    except (CheckpointIntegrityError, ConfirmationProtocolError):
        pacing = pacer.snapshot()
        status = RUNTIME_DEFECT_STATUS

    result = _base_result(
        protocol_sha256=validated.protocol_sha256,
        lock_commit=lock_commit,
        status=status,
    )
    result.update(
        {
            "request_fingerprints": {
                spec.job_id: spec.request_fingerprint for spec in specs
            },
            "durable_result": summary,
            "global_pacing": pacing,
            "m4_04b2_eligible": status == QUALIFIED_STATUS,
            "m4_04b2_state": (
                "ELIGIBLE_NOT_STARTED"
                if status == QUALIFIED_STATUS
                else "BLOCKED_NOT_STARTED"
            ),
        }
    )
    _write_json(result_path, result)

    if status == QUALIFIED_STATUS and summary is not None:
        profile = {
            "profile": "M4_DURABLE_RESEARCH_EXECUTION_PROFILE_V1",
            "provider": "Google Gemini API",
            "credential": {
                "slot_id": LOCKED_CREDENTIAL_SLOT,
                "topology": LOCKED_CREDENTIAL_TOPOLOGY,
            },
            "model": {
                "requested_id": LOCKED_MODEL,
                "provider_reported_versions": summary["provider_reported_versions"],
            },
            "runtime": RUNTIME_VERSION,
            "durable_executor": "DURABLE_RESEARCH_EXECUTOR_V1",
            "concurrency": CONCURRENCY,
            "global_pacing": "6_PROVIDER_OPERATIONS_PER_ROLLING_60_SECONDS",
            "max_execution_windows_per_job": 3,
            "max_provider_attempts_per_window": 3,
            "max_provider_attempts_per_job": 9,
            "first_success_response": "IMMUTABLE_LOCK",
            "transport_only_deferred_policy": "ENABLED",
            "output_aware_retry": "FORBIDDEN",
            "confirmation_protocol_sha256": validated.protocol_sha256,
            "protocol_lock_commit_sha": lock_commit,
            "confirmation_result_sha256": hashlib.sha256(
                result_path.read_bytes()
            ).hexdigest(),
        }
        _write_json(profile_path, profile)

    print(f"Final status: {status}", flush=True)
    return result


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--validation-result", required=True, type=Path)
    parser.add_argument("--expected-protocol-sha256", required=True)
    parser.add_argument("--lock-commit", required=True)
    parser.add_argument("--checkpoint-directory", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--profile", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = execute(
            protocol_path=args.protocol,
            validation_result_path=args.validation_result,
            expected_protocol_sha256=args.expected_protocol_sha256,
            lock_commit=args.lock_commit,
            checkpoint_directory=args.checkpoint_directory,
            result_path=args.result,
            profile_path=args.profile,
        )
    except ConfirmationProtocolError:
        print(f"Final status: {PROTOCOL_FAILED_STATUS}", flush=True)
        return 2
    return 0 if result["status"] in {QUALIFIED_STATUS, FAILED_STATUS} else 2


if __name__ == "__main__":
    raise SystemExit(main())
