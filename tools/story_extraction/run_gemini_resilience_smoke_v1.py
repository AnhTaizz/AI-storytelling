"""Run the preregistered 12-request synthetic Gemini transport smoke.

This runner never reads story data. With multiple unlabeled credentials it uses
one slot conservatively and never fans out across unknown project groups.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import statistics
from typing import Any, Optional

from tools.story_extraction.gemini_key_pool_v1 import GeminiKeyPool, load_runtime_config
from tools.story_extraction.gemini_resilience_v1 import (
    GeminiResilienceError,
    GeminiResilientTransport,
    ProjectLimit,
    ResiliencePolicy,
    conservative_runtime_credentials,
)


LIVE_REQUEST_COUNT = 12
LIVE_CONCURRENCY = 2
LIVE_OUTPUT_TOKEN_CAP = 128
SYSTEM_INSTRUCTION = "Return only a JSON object and no additional text."
USER_CONTENT = 'Return exactly: {"status":"ok"}'


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


def run(output: Path) -> dict[str, Any]:
    config = load_runtime_config()
    if not config.credentials:
        raise RuntimeError("No Gemini credential slots configured")
    if not config.model:
        raise RuntimeError("No Gemini smoke model configured")

    selected = conservative_runtime_credentials(config.credentials)
    pool = GeminiKeyPool(selected)
    policy = ResiliencePolicy(
        max_total_provider_attempts=3,
        max_transport_retries=2,
        max_credential_failovers=2,
        max_project_group_failovers=2,
        max_concurrency=LIVE_CONCURRENCY,
        queue_capacity=4,
        queue_wait_timeout_seconds=240,
        default_project_limit=ProjectLimit(rpm=10, tpm=3000),
        max_local_rate_wait_seconds=240,
        max_scheduler_wait_seconds=240,
        base_backoff_seconds=1,
        circuit_failure_threshold=3,
        circuit_open_cooldown_seconds=30,
        half_open_probe_requests=1,
    )
    gate = GeminiResilientTransport(pool, policy=policy)

    def one(index: int) -> dict[str, Any]:
        request_id = f"M4B1_LIVE_{index:02d}"
        try:
            result = gate.generate(
                SYSTEM_INSTRUCTION,
                USER_CONTENT,
                config.model,
                {"temperature": 0, "max_output_tokens": LIVE_OUTPUT_TOKEN_CAP},
                request_id,
            )
            return {
                "request_id": request_id,
                "terminal_state": "SUCCESS",
                "latency_seconds": result["latency_seconds"],
                "queue_wait_ms": result["queue_wait_ms"],
                "attempt_accounting": result["attempt_accounting"],
                "model_reported_if_available": result["model_reported_if_available"],
                "raw_content": result["raw_content"],
            }
        except GeminiResilienceError as error:
            return {
                "request_id": request_id,
                "terminal_state": "FAILURE",
                "category": error.category.value,
                "provider_attempts": error.provider_attempts,
            }
        except Exception:
            # Never serialize a raw provider exception; it might contain secret
            # request details. The gate treats this as a bounded terminal state.
            return {
                "request_id": request_id,
                "terminal_state": "FAILURE",
                "category": "UNCAUGHT_EXCEPTION",
                "provider_attempts": 0,
            }

    results: list[dict[str, Any]] = []
    # Four submitted tasks means at most two active plus two admitted waiters.
    # The fixed batch is preregistered and never creates an unbounded future set.
    with ThreadPoolExecutor(max_workers=4) as executor:
        for start in range(1, LIVE_REQUEST_COUNT + 1, 4):
            futures = [
                executor.submit(one, index)
                for index in range(start, min(start + 4, LIVE_REQUEST_COUNT + 1))
            ]
            results.extend(future.result(timeout=300) for future in futures)

    metrics = gate.metrics.snapshot()
    health = gate.health_snapshot()
    latencies = [
        float(item["latency_seconds"]) * 1000.0
        for item in results
        if item["terminal_state"] == "SUCCESS"
    ]
    queue_waits = [
        float(item["queue_wait_ms"])
        for item in results
        if item["terminal_state"] == "SUCCESS"
    ]
    success_count = sum(item["terminal_state"] == "SUCCESS" for item in results)
    report = {
        "task": "M4-04B1-LIVE-RESILIENCE-SMOKE",
        "transport_smoke_model": config.model,
        "configured_credential_slot_count": len(config.credentials),
        "effective_credential_slot_count": len(selected),
        "effective_project_group_count": len(pool.public_metadata()["groups"]),
        "unknown_credentials_restricted_conservatively": len(selected) < len(config.credentials),
        "semantic_request_count": LIVE_REQUEST_COUNT,
        "maximum_provider_attempts_per_request": 3,
        "maximum_theoretical_provider_calls": LIVE_REQUEST_COUNT * 3,
        "maximum_output_tokens_per_request": LIVE_OUTPUT_TOKEN_CAP,
        "maximum_theoretical_output_tokens": LIVE_REQUEST_COUNT * LIVE_OUTPUT_TOKEN_CAP,
        "success_count": success_count,
        "failure_count": LIVE_REQUEST_COUNT - success_count,
        "provider_attempt_count": metrics["provider_attempt_count"],
        "latency_ms": {
            "minimum": round(min(latencies), 3) if latencies else 0.0,
            "maximum": round(max(latencies), 3) if latencies else 0.0,
            "p50": round(_percentile(latencies, 0.50), 3),
            "p95": round(_percentile(latencies, 0.95), 3),
            "mean": round(statistics.mean(latencies), 3) if latencies else 0.0,
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
    parser = argparse.ArgumentParser(description="Run bounded Gemini resilience smoke")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    report = run(args.output)
    print(f"Live semantic requests: {report['semantic_request_count']}")
    print(f"Live provider attempts: {report['provider_attempt_count']}")
    print(f"Live successes: {report['success_count']}")
    print(f"Live failures: {report['failure_count']}")
    print(f"Effective credential slots: {report['effective_credential_slot_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
