"""Run the controlled V1.1 Gemini precheck or preregistered regate."""

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
from tools.story_extraction.gemini_resilience_v1_1 import (
    GeminiResilienceV11Error,
    GeminiResilientTransportV11,
    live_safe_credentials,
    load_resilience_policy_v1_1,
)


OUTPUT_TOKEN_CAP = 128
SYSTEM_INSTRUCTION = "Return only a JSON object and no additional text."
USER_CONTENT = 'Return exactly: {"status":"ok"}'
PROMPT_SHA256 = hashlib.sha256(
    (SYSTEM_INSTRUCTION + "\n" + USER_CONTENT).encode("utf-8")
).hexdigest()


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


def run(*, output: Path, mode: str, model: str) -> dict[str, Any]:
    if mode not in {"precheck", "regate"}:
        raise ValueError("Mode must be precheck or regate")
    request_count = 4 if mode == "precheck" else 12
    concurrency = 1 if mode == "precheck" else 2
    config = load_runtime_config()
    selected = live_safe_credentials(config.credentials)
    if not selected:
        raise RuntimeError("No Gemini credential slots configured")
    pool = GeminiKeyPool(selected)
    policy = load_resilience_policy_v1_1(
        max_total_provider_attempts=3,
        max_transport_retries=2,
        max_credential_failovers=2,
        max_project_group_failovers=2,
        max_concurrency=concurrency,
        queue_capacity=2 if mode == "precheck" else 4,
        queue_wait_timeout_seconds=240,
        max_local_rate_wait_seconds=240,
        max_scheduler_wait_seconds=240,
        circuit_failure_threshold=3,
        circuit_open_cooldown_seconds=30,
        half_open_probe_requests=1,
    )
    gate = GeminiResilientTransportV11(pool, policy=policy)

    def one(index: int) -> dict[str, Any]:
        request_id = f"M4B1R_{mode.upper()}_{index:02d}"
        started = time.perf_counter()
        try:
            result = gate.generate(
                SYSTEM_INSTRUCTION,
                USER_CONTENT,
                model,
                {"temperature": 0, "max_output_tokens": OUTPUT_TOKEN_CAP},
                request_id,
            )
            return {
                "request_id": request_id,
                "terminal_state": "SUCCESS",
                "category": "SUCCESS",
                "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
                "queue_wait_ms": result["queue_wait_ms"],
                "attempt_accounting": result["attempt_accounting"],
                "model_reported_if_available": result["model_reported_if_available"],
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
            # Never serialize the raw exception because SDK/provider diagnostics
            # can contain request details or credentials.
            return {
                "request_id": request_id,
                "terminal_state": "FAILURE",
                "category": "UNCAUGHT_EXCEPTION",
                "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
                "provider_attempts": 0,
                "transport_attempts": [],
            }

    results: list[dict[str, Any]] = []
    if concurrency == 1:
        results = [one(index) for index in range(1, request_count + 1)]
    else:
        with ThreadPoolExecutor(max_workers=4) as executor:
            for start in range(1, request_count + 1, 4):
                futures = [
                    executor.submit(one, index)
                    for index in range(start, min(start + 4, request_count + 1))
                ]
                results.extend(future.result(timeout=300) for future in futures)

    metrics = gate.metrics.snapshot()
    health = gate.health_snapshot()
    elapsed = [float(item["elapsed_ms"]) for item in results]
    queue_waits = [
        float(item["queue_wait_ms"]) for item in results if "queue_wait_ms" in item
    ]
    success_count = sum(item["terminal_state"] == "SUCCESS" for item in results)
    uncaught = sum(item.get("category") == "UNCAUGHT_EXCEPTION" for item in results)
    max_observed_attempts = max(
        (
            int(item.get("attempt_accounting", {}).get("total_provider_attempts", 0))
            if item["terminal_state"] == "SUCCESS"
            else int(item.get("provider_attempts", 0))
            for item in results
        ),
        default=0,
    )
    report = {
        "task": f"M4-04B1R-{mode.upper()}",
        "mode": mode,
        "transport_smoke_model": model,
        "prompt_sha256": PROMPT_SHA256,
        "prompt_contains_story_data": False,
        "configured_credential_slot_count": len(config.credentials),
        "configured_labeled_slot_count": sum(
            item.project_label != "PROJECT_GROUP_UNKNOWN" for item in config.credentials
        ),
        "effective_credential_slot_count": len(selected),
        "effective_project_group_count": len(pool.public_metadata()["groups"]),
        "multi_project_failover_testability": (
            "TESTABLE" if len(pool.public_metadata()["groups"]) > 1 else "MULTI_PROJECT_FAILOVER_NOT_TESTABLE"
        ),
        "semantic_request_count": request_count,
        "configured_concurrency": concurrency,
        "maximum_provider_attempts_per_request": 3,
        "maximum_observed_provider_attempts_per_request": max_observed_attempts,
        "maximum_theoretical_provider_calls": request_count * 3,
        "maximum_output_tokens_per_request": OUTPUT_TOKEN_CAP,
        "success_count": success_count,
        "failure_count": request_count - success_count,
        "bounded_terminal_state_count": len(results),
        "uncaught_exception_count": uncaught,
        "provider_attempt_count": metrics["provider_attempt_count"],
        "latency_ms": {
            "minimum": round(min(elapsed), 3) if elapsed else 0.0,
            "maximum": round(max(elapsed), 3) if elapsed else 0.0,
            "p50": round(_percentile(elapsed, 0.50), 3),
            "p95": round(_percentile(elapsed, 0.95), 3),
            "mean": round(statistics.mean(elapsed), 3) if elapsed else 0.0,
        },
        "queue_wait_ms": {
            "p50": round(_percentile(queue_waits, 0.50), 3),
            "p95": round(_percentile(queue_waits, 0.95), 3),
        },
        "metrics": metrics,
        "health": health,
        "requests": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=("precheck", "regate"))
    parser.add_argument("--model", required=True)
    args = parser.parse_args(argv)
    report = run(output=args.output, mode=args.mode, model=args.model)
    print(f"Mode: {report['mode']}")
    print(f"Semantic requests: {report['semantic_request_count']}")
    print(f"Provider attempts: {report['provider_attempt_count']}")
    print(f"Successes: {report['success_count']}")
    print(f"Failures: {report['failure_count']}")
    print(f"Uncaught exceptions: {report['uncaught_exception_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

