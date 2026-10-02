"""Run the preregistered M4-04B1K credential and provider qualification."""

from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
import time
from typing import Any, Callable, Optional

from tools.story_extraction.gemini_errors_v1 import sanitized_failure_metadata
from tools.story_extraction.gemini_key_pool_v1 import CredentialConfig, load_runtime_config
from tools.story_extraction.run_gemini_provider_qualification_v1 import run_block


TASK = "M4-04B1K-CREDENTIAL-HEALTH-AND-PROVIDER-REQUALIFICATION"
RUNNER_VERSION = "M4_GEMINI_CREDENTIAL_QUALIFICATION_RUNNER_V1"
PROBE_MODEL = "gemini-3.5-flash-lite"
CANDIDATES = (
    ("A_LATEST_STABLE_FLASH", "gemini-3.8-flash"),
    ("B_PREVIOUS_STABLE_FLASH_GENERATION", "gemini-3.7-flash"),
    ("C_STABLE_FLASH_LITE", "gemini-3.5-flash-lite"),
)
GLOBAL_MAX_ATTEMPTS = 6
GLOBAL_WINDOW_SECONDS = 60.0
LOCAL_RPM = 6
LOCAL_TPM = 3000
SLOT_TRANSITION_QUIET_SECONDS = 10.0
MODEL_REQUALIFICATION_QUIET_SECONDS = 60.0
MODEL_BLOCK_QUIET_SECONDS = 30.0
MAX_SEMANTIC_REQUESTS = 66
MAX_PROVIDER_OPERATIONS = 201


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _slot_number(slot_id: str) -> int:
    return int(slot_id.rsplit("_", 1)[1])


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + ((ordered[upper] - ordered[lower]) * fraction)


class GlobalUnknownTopologyPacer:
    """Sliding-window limiter shared by every credential and qualification block."""

    def __init__(
        self,
        max_attempts: int = GLOBAL_MAX_ATTEMPTS,
        window_seconds: float = GLOBAL_WINDOW_SECONDS,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_attempts < 1 or window_seconds <= 0:
            raise ValueError("Global pacing limits must be positive")
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._clock = clock
        self._sleep = sleep
        self._active: deque[float] = deque()
        self._history: list[float] = []
        self._lock = threading.Lock()
        self._wait_count = 0
        self._wait_seconds = 0.0
        self._max_rolling_observed = 0

    def acquire(self) -> float:
        waited = 0.0
        counted_wait = False
        while True:
            with self._lock:
                now = self._clock()
                cutoff = now - self.window_seconds
                while self._active and self._active[0] <= cutoff:
                    self._active.popleft()
                if len(self._active) < self.max_attempts:
                    self._active.append(now)
                    self._history.append(now)
                    self._max_rolling_observed = max(
                        self._max_rolling_observed, len(self._active)
                    )
                    if counted_wait:
                        self._wait_count += 1
                        self._wait_seconds += waited
                    return waited
                delay = max(0.001, self._active[0] + self.window_seconds - now)
            counted_wait = True
            self._sleep(delay)
            waited += delay

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "identity": "TASK_LEVEL_UNKNOWN_TOPOLOGY_ROLLING_ATTEMPT_LIMITER_V1",
                "max_provider_attempts": self.max_attempts,
                "rolling_window_seconds": self.window_seconds,
                "reservation_count": len(self._history),
                "wait_count": self._wait_count,
                "wait_seconds_total": round(self._wait_seconds, 6),
                "max_rolling_reservations_observed": self._max_rolling_observed,
                "invariant": (
                    "PASS"
                    if self._max_rolling_observed <= self.max_attempts
                    else "FAIL"
                ),
            }


class TaskBudget:
    """Fail-closed accounting for the preregistered task request budget."""

    def __init__(
        self,
        max_semantic_requests: int = MAX_SEMANTIC_REQUESTS,
        max_provider_operations: int = MAX_PROVIDER_OPERATIONS,
    ) -> None:
        self.max_semantic_requests = max_semantic_requests
        self.max_provider_operations = max_provider_operations
        self.semantic_requests = 0
        self.provider_operations = 0

    def reserve_semantic(self, count: int) -> None:
        if count < 0 or self.semantic_requests + count > self.max_semantic_requests:
            raise RuntimeError("Preregistered semantic request budget would be exceeded")
        self.semantic_requests += count

    def record_provider_operations(self, count: int) -> None:
        if count < 0 or self.provider_operations + count > self.max_provider_operations:
            raise RuntimeError("Preregistered provider operation budget was exceeded")
        self.provider_operations += count

    def snapshot(self) -> dict[str, int]:
        return {
            "semantic_requests_used": self.semantic_requests,
            "semantic_requests_maximum": self.max_semantic_requests,
            "provider_operations_used": self.provider_operations,
            "provider_operations_maximum": self.max_provider_operations,
        }


def _block_summary(report: dict[str, Any], path: Path) -> dict[str, Any]:
    provider_failure_count = sum(
        int(report[name])
        for name in (
            "server_failure_503_count",
            "other_5xx_count",
            "rate_limit_429_count",
            "timeout_count",
            "network_failure_count",
            "auth_failure_count",
        )
    )
    reported_models = sorted(
        {
            str(request["model_reported_if_available"])
            for request in report["requests"]
            if request.get("model_reported_if_available")
        }
    )
    return {
        "stage": report["stage"],
        "model": report["model_requested"],
        "credential_slot": report["credential_slot"],
        "result": report["qualification_result"],
        "semantic_requests": report["semantic_request_count"],
        "success": report["success_count"],
        "failure": report["failure_count"],
        "provider_attempts": report["provider_attempt_count"],
        "provider_failures": provider_failure_count,
        "server_failure_503": report["server_failure_503_count"],
        "other_5xx": report["other_5xx_count"],
        "rate_limit_429": report["rate_limit_429_count"],
        "timeout": report["timeout_count"],
        "network_failure": report["network_failure_count"],
        "auth_failure": report["auth_failure_count"],
        "transport_retries": report["transport_retry_count"],
        "circuit_open": report["circuit_open_event_count"],
        "circuit_blocked": report["circuit_blocked_request_count"],
        "local_rpm_wait": report["local_rpm_wait_count"],
        "local_tpm_wait": report["local_tpm_wait_count"],
        "cross_slot_failover": report["cross_slot_failover_count"],
        "request_latency_ms": {
            "p50": report["latency_ms"]["p50"],
            "p95": report["latency_ms"]["p95"],
        },
        "provider_latency_ms": report["provider_latency_ms"],
        "runtime_invariants": report["runtime_invariants"],
        "failure_fingerprints": report["failure_fingerprints"],
        "provider_reported_models": reported_models,
        "private_result_sha256": _sha256(path),
    }


def _slot_selection_key(summary: dict[str, Any]) -> tuple[Any, ...]:
    return (
        int(summary["provider_failures"]),
        int(summary["transport_retries"]),
        int(summary["server_failure_503"]),
        int(summary["rate_limit_429"]),
        float(summary["provider_latency_ms"]["p95"]),
        _slot_number(str(summary["credential_slot"])),
    )


def select_credential_slot(summaries: list[dict[str, Any]]) -> Optional[str]:
    passing = [item for item in summaries if item["result"] == "PASS"]
    if not passing:
        return None
    return str(min(passing, key=_slot_selection_key)["credential_slot"])


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _model_availability(
    credential: CredentialConfig,
    pacer: GlobalUnknownTopologyPacer,
    budget: TaskBudget,
) -> list[dict[str, Any]]:
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=credential._api_key,
        http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)),
    )
    results: list[dict[str, Any]] = []
    try:
        for role, model_id in CANDIDATES:
            wait_seconds = pacer.acquire()
            budget.record_provider_operations(1)
            try:
                model = client.models.get(model=model_id)
                results.append(
                    {
                        "role": role,
                        "model": model_id,
                        "availability": "AVAILABLE",
                        "provider_reported_version": getattr(model, "version", None),
                        "global_safety_wait_seconds": round(wait_seconds, 6),
                    }
                )
            except Exception as error:
                safe = sanitized_failure_metadata(error, time.time())
                unavailable = safe.get("http_status") == 404
                results.append(
                    {
                        "role": role,
                        "model": model_id,
                        "availability": "UNAVAILABLE" if unavailable else "UNKNOWN",
                        "failure_fingerprint": safe["fingerprint"],
                        "global_safety_wait_seconds": round(wait_seconds, 6),
                    }
                )
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
    return results


def _run_live_block(
    *,
    output: Path,
    stage: str,
    block_id: str,
    model: str,
    credential_slot: str,
    pacer: GlobalUnknownTopologyPacer,
    budget: TaskBudget,
) -> dict[str, Any]:
    semantic_count = 3 if stage in {"credential_screen", "stage_a"} else 12
    budget.reserve_semantic(semantic_count)
    report = run_block(
        output=output,
        stage=stage,
        block_id=block_id,
        model=model,
        credential_slot=credential_slot,
        rpm=LOCAL_RPM,
        tpm=LOCAL_TPM,
        report_task=TASK,
        request_prefix="M4B1K",
        provider_attempt_pacer=pacer,
    )
    budget.record_provider_operations(int(report["provider_attempt_count"]))
    return report


def execute(
    *,
    protocol_path: Path,
    output_dir: Path,
    result_path: Path,
    profile_path: Path,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    protocol_sha = _sha256(protocol_path)
    config = load_runtime_config()
    credentials = sorted(config.credentials, key=lambda item: _slot_number(item.slot_id))
    if not credentials:
        result = {
            "task": TASK,
            "status": "M4_04B1K_WAITING_FOR_CREDENTIALS",
            "configured_credential_count": 0,
        }
        _write_json(result_path, result)
        return result

    output_dir.mkdir(parents=True, exist_ok=True)
    pacer = GlobalUnknownTopologyPacer(sleep=sleep)
    budget = TaskBudget()
    credential_summaries: list[dict[str, Any]] = []

    for index, credential in enumerate(credentials):
        private_path = output_dir / f"M4_04B1K_CREDENTIAL_SCREEN_{credential.slot_id}.json"
        report = _run_live_block(
            output=private_path,
            stage="credential_screen",
            block_id=f"CREDENTIAL_{credential.slot_id}",
            model=PROBE_MODEL,
            credential_slot=credential.slot_id,
            pacer=pacer,
            budget=budget,
        )
        summary = _block_summary(report, private_path)
        credential_summaries.append(summary)
        print(
            f"Credential screen {credential.slot_id}: {summary['result']} "
            f"({summary['success']}/3)",
            flush=True,
        )
        if summary["runtime_invariants"] != "PASS":
            break
        if index + 1 < len(credentials):
            sleep(SLOT_TRANSITION_QUIET_SECONDS)

    runtime_defect = any(
        item["runtime_invariants"] != "PASS" for item in credential_summaries
    )
    selected_slot = None if runtime_defect else select_credential_slot(credential_summaries)
    credential_result_path = output_dir / "M4_04B1K_CREDENTIAL_SCREEN_RESULT_V1.yaml"
    credential_result = {
        "task": TASK,
        "credential_topology": "UNKNOWN",
        "independent_project_count": "UNKNOWN",
        "quota_independence_claimed": False,
        "configured_slots": [item.slot_id for item in credentials],
        "screened_slots": [item["credential_slot"] for item in credential_summaries],
        "probe_model": PROBE_MODEL,
        "fresh_runtime_instances": len(credential_summaries),
        "cross_slot_failover_count": sum(
            int(item["cross_slot_failover"]) for item in credential_summaries
        ),
        "slot_results": credential_summaries,
        "passing_slots": [
            item["credential_slot"]
            for item in credential_summaries
            if item["result"] == "PASS"
        ],
        "selected_credential_slot": selected_slot,
        "selection_rule": [
            "3_of_3_success_required",
            "fewer_provider_failures",
            "fewer_retries",
            "fewer_503",
            "fewer_429",
            "lower_provider_latency_p95",
            "lower_slot_number",
        ],
    }
    _write_json(credential_result_path, credential_result)

    availability: list[dict[str, Any]] = []
    stage_a: list[dict[str, Any]] = []
    profile_s: list[dict[str, Any]] = []
    selected_model: Optional[str] = None
    selected_profile_summary: Optional[dict[str, Any]] = None

    if runtime_defect:
        status = "M4_04B1K_RUNTIME_DEFECT_FOUND"
    elif selected_slot is None:
        status = "M4_04B1K_NO_HEALTHY_CREDENTIAL_SLOT"
    else:
        print(
            f"Selected credential: {selected_slot}; quiet period "
            f"{int(MODEL_REQUALIFICATION_QUIET_SECONDS)}s",
            flush=True,
        )
        sleep(MODEL_REQUALIFICATION_QUIET_SECONDS)
        selected_credential = next(
            item for item in credentials if item.slot_id == selected_slot
        )
        availability = _model_availability(selected_credential, pacer, budget)
        executable = {
            item["model"]
            for item in availability
            if item["availability"] != "UNAVAILABLE"
        }
        first_model_block = True
        for role, model_id in CANDIDATES:
            if model_id not in executable:
                stage_a.append(
                    {
                        "role": role,
                        "model": model_id,
                        "result": "NOT_EXECUTED_PROVIDER_DISCOVERY_UNAVAILABLE",
                    }
                )
                continue
            if not first_model_block:
                sleep(MODEL_BLOCK_QUIET_SECONDS)
            first_model_block = False
            private_path = output_dir / f"M4_04B1K_STAGE_A_{model_id}.json"
            report = _run_live_block(
                output=private_path,
                stage="stage_a",
                block_id=f"STAGE_A_{role}",
                model=model_id,
                credential_slot=selected_slot,
                pacer=pacer,
                budget=budget,
            )
            summary = {"role": role, **_block_summary(report, private_path)}
            stage_a.append(summary)
            print(
                f"Model Stage A {model_id}: {summary['result']} "
                f"({summary['success']}/3)",
                flush=True,
            )
            if summary["runtime_invariants"] != "PASS":
                runtime_defect = True
                break

        passing_models = [
            item for item in stage_a if item.get("result") == "PASS"
        ]
        if runtime_defect:
            status = "M4_04B1K_RUNTIME_DEFECT_FOUND"
        elif not passing_models:
            status = "M4_04B1K_NO_STABLE_MODEL_ON_SELECTED_CREDENTIAL"
        else:
            for profile_index, item in enumerate(passing_models):
                if profile_index > 0 or stage_a:
                    sleep(MODEL_BLOCK_QUIET_SECONDS)
                model_id = str(item["model"])
                private_path = output_dir / f"M4_04B1K_PROFILE_S_{model_id}.json"
                report = _run_live_block(
                    output=private_path,
                    stage="profile_s",
                    block_id=f"PROFILE_S_{item['role']}",
                    model=model_id,
                    credential_slot=selected_slot,
                    pacer=pacer,
                    budget=budget,
                )
                summary = {"role": item["role"], **_block_summary(report, private_path)}
                profile_s.append(summary)
                print(
                    f"Profile S {model_id}: {summary['result']} "
                    f"({summary['success']}/12)",
                    flush=True,
                )
                if summary["runtime_invariants"] != "PASS":
                    runtime_defect = True
                    break
                if summary["result"] == "PASS":
                    selected_model = model_id
                    selected_profile_summary = summary
                    break
            tested_profile_models = {item["model"] for item in profile_s}
            for item in passing_models:
                if item["model"] not in tested_profile_models:
                    profile_s.append(
                        {
                            "role": item["role"],
                            "model": item["model"],
                            "result": "NOT_EXECUTED_AFTER_PROFILE_QUALIFIED",
                        }
                    )
            if runtime_defect:
                status = "M4_04B1K_RUNTIME_DEFECT_FOUND"
            elif selected_model is None:
                status = "M4_04B1K_NO_STABLE_PROVIDER_PROFILE"
            else:
                status = (
                    "M4_04B1K_RESEARCH_EXECUTION_PROFILE_READY_"
                    "PENDING_ORCHESTRATOR_REVIEW"
                )

    if _sha256(protocol_path) != protocol_sha:
        raise RuntimeError("Preregistered protocol changed after live execution began")
    pacing = pacer.snapshot()
    if pacing["invariant"] != "PASS":
        status = "M4_04B1K_RUNTIME_DEFECT_FOUND"
        selected_model = None
        selected_profile_summary = None

    result = {
        "task": TASK,
        "runner": RUNNER_VERSION,
        "completed_at_utc": _utc_now(),
        "base_commit": "2054f9f76f84097a678ae75c34866a0953412443",
        "status": status,
        "protocol_sha256": protocol_sha,
        "credential_topology": "UNKNOWN",
        "independent_project_count": "UNKNOWN",
        "quota_independence_claimed": False,
        "configured_credential_count": len(credentials),
        "screened_credential_count": len(credential_summaries),
        "credential_screen_result_sha256": _sha256(credential_result_path),
        "credential_results": credential_summaries,
        "passing_slots": credential_result["passing_slots"],
        "selected_credential_slot": selected_slot,
        "cross_slot_failover_count": credential_result["cross_slot_failover_count"],
        "global_safety_pacing": pacing,
        "model_availability": availability,
        "model_stage_a": stage_a,
        "profile_s": profile_s,
        "selected_model": selected_model,
        "selected_research_execution_profile": (
            "M4_RESEARCH_EXECUTION_PROFILE_V1" if selected_model else None
        ),
        "m4_04b2_eligible": selected_model is not None,
        "m4_04b2_state": "ELIGIBLE_NOT_STARTED" if selected_model else "BLOCKED_NOT_STARTED",
        "request_budget": budget.snapshot(),
        "historical_results_preserved": {
            "m4_04b1_live_fail": True,
            "m4_04b1r_provider_gate_unhealthy": True,
            "m4_04b1q_no_stable_model_profile": True,
        },
        "holdout": {
            "input_opened": False,
            "gold_opened": False,
            "predictions_run": False,
            "contamination": "CLEAN",
        },
        "research_state": {
            "extraction_model": "NOT_SELECTED_FOR_QUALITY",
            "extractor": "NOT_LOCKED",
            "m4_04b2": "NOT_STARTED",
            "m5": "NOT_STARTED",
        },
    }
    _write_json(result_path, result)

    if selected_model and selected_profile_summary and selected_slot:
        provider_versions = selected_profile_summary.get("provider_reported_models", [])
        profile = {
            "profile": "M4_RESEARCH_EXECUTION_PROFILE_V1",
            "provider": "Google Gemini API",
            "credential": {
                "selected_slot_id": selected_slot,
                "topology": "UNKNOWN",
                "quota_independence_claimed": False,
            },
            "model": {
                "requested_id": selected_model,
                "provider_reported_versions": provider_versions,
            },
            "runtime": "GEMINI_TRANSPORT_RESILIENCE_V1_1",
            "concurrency": 1,
            "local_rpm": LOCAL_RPM,
            "local_tpm": LOCAL_TPM,
            "global_unknown_topology_pacing": {
                "max_provider_attempts": GLOBAL_MAX_ATTEMPTS,
                "rolling_window_seconds": GLOBAL_WINDOW_SECONDS,
            },
            "max_provider_attempts_per_semantic_request": 3,
            "retry_policy": "V1_1_BOUNDED_TRANSPORT_RETRY_NO_CREDENTIAL_FAILOVER",
            "circuit_policy": "V1_1_PROJECT_GROUP_MODEL_CIRCUIT",
            "credential_qualification_protocol_sha256": protocol_sha,
            "credential_result_sha256": _sha256(credential_result_path),
            "model_qualification_result_sha256": selected_profile_summary[
                "private_result_sha256"
            ],
            "scope": "M4_DEVELOPMENT_RESEARCH_TRANSPORT_ONLY",
            "extraction_quality_selected": False,
        }
        _write_json(profile_path, profile)

    print(f"Final status: {status}", flush=True)
    return result


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--profile", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        execute(
            protocol_path=args.protocol,
            output_dir=args.output_dir,
            result_path=args.result,
            profile_path=args.profile,
        )
    except Exception as error:
        print(f"Qualification aborted safely: {type(error).__name__}", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
