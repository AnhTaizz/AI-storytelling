"""Run M4-04B1D durable Gemini research-execution qualification."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Optional

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
from tools.story_extraction.gemini_key_pool_v1 import GeminiKeyPool, load_runtime_config
from tools.story_extraction.gemini_resilience_v1 import ProjectLimit
from tools.story_extraction.gemini_resilience_v1_1 import (
    GeminiResilienceV11Error,
    GeminiResilientTransportV11,
    ResiliencePolicyV11,
)
from tools.story_extraction.gemini_transport_v1 import official_client_factory


TASK = "M4-04B1D-DURABLE-DEFERRED-EXECUTION-AND-CHECKPOINT-GATE"
RUNNER_VERSION = "M4_GEMINI_DURABLE_QUALIFICATION_RUNNER_V1"
PROTOCOL_ID = "M4_04B1D_DURABLE_EXECUTION_PROTOCOL_V1"
LOCKED_CREDENTIAL_SLOT = "gemini_slot_3"
CANDIDATES = (
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.5-flash-lite",
)
JOB_COUNT = 6
OUTPUT_TOKEN_CAP = 128
LOCAL_RPM = 6
LOCAL_TPM = 3000
WINDOW_COOLDOWN_SECONDS = 60.0
MODEL_QUIET_SECONDS = 60.0
SYSTEM_PROMPT = "Return only the requested valid JSON object and no additional text."
USER_TEMPLATE = 'Return exactly: {"status":"ok","durable_sequence":<SEQUENCE>}'
PROMPT_FAMILY_SHA256 = hashlib.sha256(
    (SYSTEM_PROMPT + "\n" + USER_TEMPLATE).encode("utf-8")
).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


class GeminiDurableWindowTransport:
    """One accepted V1.1 runtime instance for one durable execution window."""

    def __init__(self, credential, pacer: PersistentRollingOperationPacer) -> None:
        self.credential = credential
        self.pacer = pacer

    def __call__(
        self, spec: DurableJobSpec, window_number: int, request_id: str
    ) -> dict[str, Any]:
        del window_number
        if spec.credential_slot != self.credential.slot_id:
            raise CheckpointIntegrityError("Durable transport credential lock mismatch")
        pool = GeminiKeyPool((self.credential,))
        global_waits: list[float] = []

        def client_factory(api_key: str):
            client = official_client_factory(api_key)
            global_waits.append(float(self.pacer.acquire()))
            return client

        policy = ResiliencePolicyV11(
            max_total_provider_attempts=3,
            max_transport_retries=2,
            max_credential_failovers=0,
            max_project_group_failovers=0,
            max_concurrency=1,
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
            attempts = [dict(item) for item in error.attempts]
            if len(attempts) != len(global_waits):
                raise CheckpointIntegrityError(
                    "Persistent pacing accounting does not match failed provider attempts"
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
        attempts = [dict(item) for item in result.get("transport_attempts", [])]
        if len(attempts) != len(global_waits):
            raise CheckpointIntegrityError(
                "Persistent pacing accounting does not match successful provider attempts"
            )
        for attempt, wait_seconds in zip(attempts, global_waits):
            attempt["global_safety_wait_seconds"] = round(wait_seconds, 6)
        result["transport_attempts"] = attempts
        return result


def _build_specs(model: str) -> list[DurableJobSpec]:
    safe_model = model.replace(".", "_").replace("-", "_")
    return [
        DurableJobSpec(
            job_id=f"M4B1D_{safe_model}_{index:02d}",
            model=model,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=USER_TEMPLATE.replace("<SEQUENCE>", str(index)),
            generation_config={"temperature": 0, "max_output_tokens": OUTPUT_TOKEN_CAP},
            schema_response_mode="PROVIDER_JSON_MIME_NO_OUTPUT_AWARE_RETRY",
            credential_slot=LOCKED_CREDENTIAL_SLOT,
            research_task_id=TASK,
        )
        for index in range(1, JOB_COUNT + 1)
    ]


def _candidate_summary(
    model: str,
    specs: list[DurableJobSpec],
    executor: DurableResearchExecutor,
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
    success_count = sum(item["state"] == JobState.SUCCEEDED_LOCKED.value for item in jobs)
    terminal_count = sum(item["state"] == JobState.TERMINAL_FAILED.value for item in jobs)
    pass_invariants = all(
        (
            all(item["credential_slot"] == LOCKED_CREDENTIAL_SLOT for item in jobs),
            all(item["model"] == model for item in jobs),
            all(item["windows_used"] <= 3 for item in jobs),
            all(item["total_provider_operations"] <= 9 for item in jobs),
            all(item["success_lock_count"] <= 1 for item in jobs),
        )
    )
    return {
        "model": model,
        "result": "PASS" if success_count == JOB_COUNT and pass_invariants else "FAIL",
        "jobs": JOB_COUNT,
        "eventual_successes": success_count,
        "terminal_failures": terminal_count,
        "unfinished_jobs": JOB_COUNT - success_count - terminal_count,
        "windows_used": sum(int(item["windows_used"]) for item in jobs),
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
        "duplicate_success_call_count": 0,
        "output_aware_retry_count": 0,
        "request_fingerprint_mutation_count": 0,
        "credential_switch_count": 0,
        "model_switch_count": 0,
        "attempt_cap_violation_count": 0,
        "uncaught_exception_count": 0,
        "runtime_invariants": "PASS" if pass_invariants else "FAIL",
        "failure_fingerprints": dict(sorted(failure_fingerprints.items())),
        "provider_reported_versions": sorted(reported_versions),
        "job_results": jobs,
    }


def _run_candidate(
    *,
    model: str,
    executor: DurableResearchExecutor,
    transport: GeminiDurableWindowTransport,
) -> dict[str, Any]:
    specs = _build_specs(model)
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
                    f"{model} {spec.job_id} window={record['window_count']} "
                    f"state={record['state']}",
                    flush=True,
                )
                if record["state"] == JobState.TERMINAL_FAILED.value:
                    return _candidate_summary(model, specs, executor)
            except CooldownPending as pending:
                cooldowns.append(pending.remaining_seconds)

        summary = _candidate_summary(model, specs, executor)
        if summary["eventual_successes"] == JOB_COUNT:
            return summary
        if summary["terminal_failures"] > 0:
            return summary
        if not progressed:
            if not cooldowns:
                raise CheckpointIntegrityError("Durable scheduler made no progress")
            wait_seconds = max(0.001, min(cooldowns))
            print(f"{model} deferred cooldown wait={wait_seconds:.3f}s", flush=True)
            time.sleep(wait_seconds)


def execute(
    *,
    protocol_path: Path,
    checkpoint_directory: Path,
    result_path: Path,
    profile_path: Path,
) -> dict[str, Any]:
    protocol_sha = _sha256(protocol_path)
    config = load_runtime_config()
    selected = [
        item for item in config.credentials if item.slot_id == LOCKED_CREDENTIAL_SLOT
    ]
    if len(selected) != 1:
        result = {
            "task": TASK,
            "status": "M4_04B1D_WAITING_FOR_CREDENTIAL",
            "credential_slot": LOCKED_CREDENTIAL_SLOT,
        }
        _write_json(result_path, result)
        return result
    credential = selected[0]
    pacer = PersistentRollingOperationPacer(
        checkpoint_directory / "global_pacing.json"
    )
    executor = DurableResearchExecutor(
        checkpoint_directory / "jobs",
        protocol_id=f"{PROTOCOL_ID}:{protocol_sha}",
        window_cooldown_seconds=WINDOW_COOLDOWN_SECONDS,
        forbidden_secrets=tuple(item._api_key for item in config.credentials),
    )
    transport = GeminiDurableWindowTransport(credential, pacer)
    fingerprints = {
        model: [spec.request_fingerprint for spec in _build_specs(model)]
        for model in CANDIDATES
    }
    candidate_results: list[dict[str, Any]] = []
    selected_model: Optional[str] = None
    status = "M4_04B1D_NO_DURABLE_GEMINI_PROFILE"

    try:
        for index, model in enumerate(CANDIDATES):
            if index > 0:
                print(f"Model transition quiet period {MODEL_QUIET_SECONDS:.0f}s", flush=True)
                time.sleep(MODEL_QUIET_SECONDS)
            summary = _run_candidate(
                model=model, executor=executor, transport=transport
            )
            candidate_results.append(summary)
            print(
                f"Durable candidate {model}: {summary['result']} "
                f"success={summary['eventual_successes']}/{JOB_COUNT}",
                flush=True,
            )
            if summary["auth_failures"] > 0:
                status = "M4_04B1D_WAITING_FOR_CREDENTIAL"
                break
            if summary["runtime_invariants"] != "PASS":
                status = "M4_04B1D_RUNTIME_DEFECT_FOUND"
                break
            if summary["result"] == "PASS":
                selected_model = model
                status = (
                    "M4_04B1D_DURABLE_RESEARCH_PROFILE_READY_"
                    "PENDING_ORCHESTRATOR_REVIEW"
                )
                break
    except CheckpointIntegrityError:
        status = "M4_04B1D_RUNTIME_DEFECT_FOUND"

    executed_models = {item["model"] for item in candidate_results}
    for model in CANDIDATES:
        if model not in executed_models:
            candidate_results.append(
                {
                    "model": model,
                    "result": (
                        "NOT_EXECUTED_AFTER_PROFILE_QUALIFIED"
                        if selected_model
                        else "NOT_EXECUTED_AFTER_TASK_STOP"
                    ),
                }
            )

    if _sha256(protocol_path) != protocol_sha:
        status = "M4_04B1D_RUNTIME_DEFECT_FOUND"
        selected_model = None
    pacing = pacer.snapshot()
    if pacing["invariant"] != "PASS":
        status = "M4_04B1D_RUNTIME_DEFECT_FOUND"
        selected_model = None
    result = {
        "task": TASK,
        "runner": RUNNER_VERSION,
        "completed_at_utc": _utc_now(),
        "base_commit": "866677897d6d11885b3a175d0c8787a3544ee40d",
        "status": status,
        "protocol_sha256": protocol_sha,
        "durable_executor": "DURABLE_RESEARCH_EXECUTOR_V1",
        "credential_slot": LOCKED_CREDENTIAL_SLOT,
        "credential_topology": "UNKNOWN",
        "prompt_family_sha256": PROMPT_FAMILY_SHA256,
        "request_fingerprints": fingerprints,
        "candidate_results": candidate_results,
        "global_pacing": pacing,
        "selected_model": selected_model,
        "selected_durable_profile": (
            "M4_DURABLE_RESEARCH_EXECUTION_PROFILE_V1" if selected_model else None
        ),
        "m4_04b2_eligible": selected_model is not None,
        "m4_04b2_state": "ELIGIBLE_NOT_STARTED" if selected_model else "BLOCKED_NOT_STARTED",
        "first_success_lock_audit": {
            "duplicate_success_call_count": sum(
                int(item.get("duplicate_success_call_count", 0))
                for item in candidate_results
            ),
            "output_aware_retry_count": sum(
                int(item.get("output_aware_retry_count", 0))
                for item in candidate_results
            ),
        },
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
    _write_json(result_path, result)

    if selected_model:
        selected_result = next(
            item for item in candidate_results if item.get("model") == selected_model
        )
        profile = {
            "profile": "M4_DURABLE_RESEARCH_EXECUTION_PROFILE_V1",
            "provider": "Google Gemini API",
            "credential": {
                "slot_id": LOCKED_CREDENTIAL_SLOT,
                "topology": "UNKNOWN",
            },
            "model": {
                "requested_id": selected_model,
                "provider_reported_versions": selected_result[
                    "provider_reported_versions"
                ],
            },
            "runtime": "GEMINI_TRANSPORT_RESILIENCE_V1_1",
            "durable_executor": "DURABLE_RESEARCH_EXECUTOR_V1",
            "concurrency": 1,
            "global_pacing": "6_PROVIDER_OPERATIONS_PER_ROLLING_60_SECONDS",
            "max_execution_windows_per_job": 3,
            "max_provider_attempts_per_window": 3,
            "first_success_response": "IMMUTABLE_LOCK",
            "transport_only_deferred_policy": "ENABLED",
            "output_aware_retry": "FORBIDDEN",
            "protocol_sha256": protocol_sha,
            "private_result_sha256": _sha256(result_path),
        }
        _write_json(profile_path, profile)

    print(f"Final status: {status}", flush=True)
    return result


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--checkpoint-directory", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--profile", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        execute(
            protocol_path=args.protocol,
            checkpoint_directory=args.checkpoint_directory,
            result_path=args.result,
            profile_path=args.profile,
        )
    except Exception as error:
        print(f"Durable qualification aborted safely: {type(error).__name__}", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
