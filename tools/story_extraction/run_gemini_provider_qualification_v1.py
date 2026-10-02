"""Run one preregistered Gemini provider-qualification block."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import statistics
import time
from typing import Any, Optional

from tools.story_extraction.gemini_key_pool_v1 import GeminiKeyPool, load_runtime_config
from tools.story_extraction.gemini_resilience_v1 import ProjectLimit
from tools.story_extraction.gemini_resilience_v1_1 import (
    GeminiResilienceV11Error,
    GeminiResilientTransportV11,
    ResiliencePolicyV11,
)


RUNNER_VERSION = "M4_GEMINI_PROVIDER_QUALIFICATION_RUNNER_V1"
OUTPUT_TOKEN_CAP = 128
SYSTEM_INSTRUCTION = "Return only a valid JSON object and no additional text."
USER_TEMPLATE = 'Return exactly: {"status":"ok","sequence":<SEQUENCE>}'
PROMPT_TEMPLATE_SHA256 = hashlib.sha256(
    (SYSTEM_INSTRUCTION + "\n" + USER_TEMPLATE).encode("utf-8")
).hexdigest()
STAGE_SPECS = {
    "stage_a": {"requests": 3, "concurrency": 1},
    "profile_s": {"requests": 12, "concurrency": 1},
    "profile_c2": {"requests": 12, "concurrency": 2},
}


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


def _reported_model_compatible(requested: str, reported: Optional[str]) -> bool:
    if not reported:
        return True
    normalized = reported.removeprefix("models/")
    return normalized == requested or normalized.startswith(requested + "-")


def _failure_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "server_failure_503_count": 0,
        "other_5xx_count": 0,
        "rate_limit_429_count": 0,
        "timeout_count": 0,
        "network_failure_count": 0,
    }
    for request in results:
        for attempt in request.get("transport_attempts", []):
            category = attempt.get("classified_result")
            status = attempt.get("http_status")
            if category == "SERVER_FAILURE" and status == 503:
                counts["server_failure_503_count"] += 1
            elif category == "SERVER_FAILURE":
                counts["other_5xx_count"] += 1
            elif category == "RATE_LIMIT":
                counts["rate_limit_429_count"] += 1
            elif category == "TIMEOUT":
                counts["timeout_count"] += 1
            elif category == "NETWORK_FAILURE":
                counts["network_failure_count"] += 1
    return counts


def run_block(
    *,
    output: Path,
    stage: str,
    block_id: str,
    model: str,
    credential_slot: str,
    rpm: int,
    tpm: int,
) -> dict[str, Any]:
    if stage not in STAGE_SPECS:
        raise ValueError("Unknown qualification stage")
    if rpm < 1 or rpm > 6 or tpm < 1 or tpm > 3000:
        raise ValueError("Qualification local limits exceed preregistered safety bounds")
    spec = STAGE_SPECS[stage]
    request_count = spec["requests"]
    concurrency = spec["concurrency"]
    config = load_runtime_config()
    selected = [item for item in config.credentials if item.slot_id == credential_slot]
    if len(selected) != 1:
        raise RuntimeError("Locked Gemini credential slot is unavailable")
    credential = selected[0]
    pool = GeminiKeyPool((credential,))
    policy = ResiliencePolicyV11(
        max_total_provider_attempts=3,
        max_transport_retries=2,
        max_credential_failovers=0,
        max_project_group_failovers=0,
        max_concurrency=concurrency,
        queue_capacity=2 if concurrency == 1 else 4,
        queue_wait_timeout_seconds=300,
        default_project_limit=ProjectLimit(rpm=rpm, tpm=tpm),
        max_local_rate_wait_seconds=300,
        max_scheduler_wait_seconds=300,
        base_backoff_seconds=1,
        max_backoff_seconds=30,
        backoff_jitter_ratio=0.20,
        circuit_failure_threshold=3,
        circuit_open_cooldown_seconds=30,
        half_open_probe_requests=1,
    )
    gate = GeminiResilientTransportV11(pool, policy=policy)

    def one(index: int) -> dict[str, Any]:
        request_id = f"M4B1Q_{block_id}_{index:02d}"
        user_content = USER_TEMPLATE.replace("<SEQUENCE>", str(index))
        started = time.perf_counter()
        try:
            result = gate.generate(
                SYSTEM_INSTRUCTION,
                user_content,
                model,
                {"temperature": 0, "max_output_tokens": OUTPUT_TOKEN_CAP},
                request_id,
            )
            reported = result["model_reported_if_available"]
            return {
                "request_id": request_id,
                "terminal_state": "SUCCESS",
                "category": "SUCCESS",
                "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
                "queue_wait_ms": result["queue_wait_ms"],
                "attempt_accounting": result["attempt_accounting"],
                "model_reported_if_available": reported,
                "model_identity_compatible": _reported_model_compatible(model, reported),
                "transport_attempts": result["transport_attempts"],
            }
        except GeminiResilienceV11Error as error:
            return {
                "request_id": request_id,
                "terminal_state": "FAILURE",
                "category": error.category.value,
                "fingerprint": error.fingerprint,
                "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
                "provider_attempts": error.provider_attempts,
                "transport_attempts": list(error.attempts),
            }
        except Exception:
            return {
                "request_id": request_id,
                "terminal_state": "FAILURE",
                "category": "UNCAUGHT_EXCEPTION",
                "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
                "provider_attempts": 0,
                "transport_attempts": [],
            }

    if concurrency == 1:
        results = [one(index) for index in range(1, request_count + 1)]
    else:
        results: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=4) as executor:
            for start in range(1, request_count + 1, 4):
                futures = [
                    executor.submit(one, index)
                    for index in range(start, min(start + 4, request_count + 1))
                ]
                results.extend(future.result(timeout=360) for future in futures)

    metrics = gate.metrics.snapshot()
    health = gate.health_snapshot()
    elapsed = [float(item["elapsed_ms"]) for item in results]
    attempts_per_request = [
        int(item.get("attempt_accounting", {}).get("total_provider_attempts", 0))
        if item["terminal_state"] == "SUCCESS"
        else int(item.get("provider_attempts", 0))
        for item in results
    ]
    success_count = sum(item["terminal_state"] == "SUCCESS" for item in results)
    uncaught = sum(item.get("category") == "UNCAUGHT_EXCEPTION" for item in results)
    circuit_blocked = sum(item.get("category") == "CIRCUIT_OPEN" for item in results)
    model_switches = sum(
        item.get("model_identity_compatible") is False for item in results
    )
    failure_counts = _failure_counts(results)
    invariant_pass = all(
        (
            len(results) == request_count,
            uncaught == 0,
            max(attempts_per_request, default=0) <= 3,
            metrics["rpm_reservation_count"] == metrics["provider_attempt_count"],
            metrics["tpm_reservation_count"] == metrics["provider_attempt_count"],
            health["max_active_seen"] <= concurrency,
            model_switches == 0,
        )
    )
    threshold = request_count if stage == "stage_a" else 11
    passed = success_count >= threshold and invariant_pass and metrics["auth_disable_event_count"] == 0
    report = {
        "task": "M4-04B1Q-GEMINI-PROVIDER-CAPACITY-QUALIFICATION",
        "runner": RUNNER_VERSION,
        "stage": stage,
        "block_id": block_id,
        "model_requested": model,
        "credential_slot": credential_slot,
        "credential_topology": "UNKNOWN",
        "official_live_credentials_used": 1,
        "multi_project_failover": "DISABLED",
        "prompt_template_sha256": PROMPT_TEMPLATE_SHA256,
        "prompt_contains_story_data": False,
        "semantic_request_count": request_count,
        "configured_concurrency": concurrency,
        "local_rpm": rpm,
        "local_tpm": tpm,
        "maximum_output_tokens_per_request": OUTPUT_TOKEN_CAP,
        "maximum_provider_attempts_per_request": 3,
        "maximum_theoretical_provider_attempts": request_count * 3,
        "bounded_terminal_state_count": len(results),
        "success_count": success_count,
        "failure_count": request_count - success_count,
        "provider_attempt_count": metrics["provider_attempt_count"],
        "attempts_per_request_mean": round(
            metrics["provider_attempt_count"] / request_count, 6
        ),
        "maximum_observed_attempts_per_request": max(attempts_per_request, default=0),
        **failure_counts,
        "auth_failure_count": metrics["auth_disable_event_count"],
        "transport_retry_count": metrics["transport_retry_count"],
        "circuit_open_event_count": metrics["circuit_open_count"],
        "circuit_blocked_request_count": circuit_blocked,
        "local_rpm_wait_count": metrics["local_rpm_wait_count"],
        "local_tpm_wait_count": metrics["local_tpm_wait_count"],
        "uncaught_exception_count": uncaught,
        "attempt_cap_violation_count": sum(value > 3 for value in attempts_per_request),
        "model_switch_count": model_switches,
        "provider_fallback_count": 0,
        "local_model_fallback_count": 0,
        "rpm_reservation_count": metrics["rpm_reservation_count"],
        "tpm_reservation_count": metrics["tpm_reservation_count"],
        "max_active_calls": health["max_active_seen"],
        "max_queue_depth": health["max_queue_depth_seen"],
        "failure_fingerprints": metrics["failure_fingerprints"],
        "latency_ms": {
            "minimum": round(min(elapsed), 3) if elapsed else 0.0,
            "p50": round(_percentile(elapsed, 0.50), 3),
            "p95": round(_percentile(elapsed, 0.95), 3),
            "maximum": round(max(elapsed), 3) if elapsed else 0.0,
            "mean": round(statistics.mean(elapsed), 3) if elapsed else 0.0,
        },
        "provider_latency_ms": {
            "p50": metrics["provider_latency_ms_p50"],
            "p95": metrics["provider_latency_ms_p95"],
        },
        "queue_wait_ms": {
            "p50": metrics["queue_wait_ms_p50"],
            "p95": metrics["queue_wait_ms_p95"],
        },
        "runtime_invariants": "PASS" if invariant_pass else "FAIL",
        "success_threshold": threshold,
        "qualification_result": "PASS" if passed else "FAIL",
        "metrics": metrics,
        "health": health,
        "requests": results,
    }
    serialized = json.dumps(report, sort_keys=True)
    if credential._api_key in serialized:
        raise RuntimeError("Credential leak guard rejected qualification report")
    report["secret_leak_count"] = 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--stage", required=True, choices=tuple(STAGE_SPECS))
    parser.add_argument("--block-id", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--credential-slot", required=True)
    parser.add_argument("--rpm", required=True, type=int)
    parser.add_argument("--tpm", required=True, type=int)
    args = parser.parse_args(argv)
    report = run_block(
        output=args.output,
        stage=args.stage,
        block_id=args.block_id,
        model=args.model,
        credential_slot=args.credential_slot,
        rpm=args.rpm,
        tpm=args.tpm,
    )
    print(f"Stage: {report['stage']}")
    print(f"Model: {report['model_requested']}")
    print(f"Semantic requests: {report['semantic_request_count']}")
    print(f"Provider attempts: {report['provider_attempt_count']}")
    print(f"Successes: {report['success_count']}")
    print(f"Failures: {report['failure_count']}")
    print(f"Qualification result: {report['qualification_result']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

