"""Offline tests for M4-04B1K credential/provider qualification."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.story_extraction.gemini_key_pool_v1 import CredentialConfig  # noqa: E402
from tools.story_extraction.run_gemini_credential_qualification_v1 import (  # noqa: E402
    CANDIDATES,
    GLOBAL_MAX_ATTEMPTS,
    GLOBAL_WINDOW_SECONDS,
    MAX_PROVIDER_OPERATIONS,
    MAX_SEMANTIC_REQUESTS,
    GlobalUnknownTopologyPacer,
    TaskBudget,
    execute,
    select_credential_slot,
)


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def summary(slot: int, *, p95: float, retries: int = 0, failures: int = 0):
    return {
        "credential_slot": f"gemini_slot_{slot}",
        "result": "PASS",
        "provider_failures": failures,
        "transport_retries": retries,
        "server_failure_503": 0,
        "rate_limit_429": 0,
        "provider_latency_ms": {"p95": p95},
    }


def fake_report(slot: str, *, p95: float) -> dict:
    return {
        "stage": "credential_screen",
        "model_requested": "gemini-3.5-flash-lite",
        "credential_slot": slot,
        "qualification_result": "PASS",
        "semantic_request_count": 3,
        "success_count": 3,
        "failure_count": 0,
        "provider_attempt_count": 3,
        "server_failure_503_count": 0,
        "other_5xx_count": 0,
        "rate_limit_429_count": 0,
        "timeout_count": 0,
        "network_failure_count": 0,
        "auth_failure_count": 0,
        "transport_retry_count": 0,
        "circuit_open_event_count": 0,
        "circuit_blocked_request_count": 0,
        "local_rpm_wait_count": 0,
        "local_tpm_wait_count": 0,
        "cross_slot_failover_count": 0,
        "latency_ms": {"p50": p95, "p95": p95},
        "provider_latency_ms": {"p50": p95, "p95": p95},
        "runtime_invariants": "PASS",
        "failure_fingerprints": {},
        "requests": [],
    }


class TestGlobalUnknownTopologyPacer(unittest.TestCase):
    def test_shared_rolling_window_never_exceeds_six(self):
        fake = FakeTime()
        pacer = GlobalUnknownTopologyPacer(clock=fake.clock, sleep=fake.sleep)
        waits = [pacer.acquire() for _ in range(7)]
        self.assertEqual(waits[:6], [0.0] * 6)
        self.assertEqual(waits[6], GLOBAL_WINDOW_SECONDS)
        snapshot = pacer.snapshot()
        self.assertEqual(snapshot["max_rolling_reservations_observed"], 6)
        self.assertEqual(snapshot["invariant"], "PASS")

    def test_invalid_limits_fail_closed(self):
        with self.assertRaises(ValueError):
            GlobalUnknownTopologyPacer(max_attempts=0)


class TestCredentialSelection(unittest.TestCase):
    def test_selection_rule_is_lexicographic_and_deterministic(self):
        candidates = [summary(3, p95=4), summary(2, p95=5), summary(1, p95=5)]
        self.assertEqual(select_credential_slot(candidates), "gemini_slot_3")
        tied = [summary(2, p95=5), summary(1, p95=5)]
        self.assertEqual(select_credential_slot(tied), "gemini_slot_1")

    def test_failed_slot_is_never_selected(self):
        failed = summary(1, p95=1)
        failed["result"] = "FAIL"
        self.assertIsNone(select_credential_slot([failed]))


class TestTaskBudget(unittest.TestCase):
    def test_preregistered_budget_caps_are_enforced(self):
        budget = TaskBudget()
        budget.reserve_semantic(MAX_SEMANTIC_REQUESTS)
        budget.record_provider_operations(MAX_PROVIDER_OPERATIONS)
        with self.assertRaises(RuntimeError):
            budget.reserve_semantic(1)
        with self.assertRaises(RuntimeError):
            budget.record_provider_operations(1)

    def test_fixed_candidate_order_and_no_c2_budget(self):
        self.assertEqual(
            [model for _, model in CANDIDATES],
            ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.5-flash-lite"],
        )
        self.assertEqual(MAX_SEMANTIC_REQUESTS, 66)
        self.assertEqual(GLOBAL_MAX_ATTEMPTS, 6)


class TestCredentialExecutionContract(unittest.TestCase):
    def test_slots_are_sorted_isolated_and_never_claim_independent_quota(self):
        credentials = (
            CredentialConfig("gemini_slot_2", "GEMINI_API_KEY_2", "PROJECT_GROUP_UNKNOWN", "g2", "secret2"),
            CredentialConfig("gemini_slot_1", "GEMINI_API_KEY_1", "PROJECT_GROUP_UNKNOWN", "g1", "secret1"),
        )
        calls: list[str] = []

        def fake_live_block(**kwargs):
            calls.append(kwargs["credential_slot"])
            report = fake_report(
                kwargs["credential_slot"],
                p95=2.0 if kwargs["credential_slot"].endswith("2") else 5.0,
            )
            kwargs["output"].parent.mkdir(parents=True, exist_ok=True)
            kwargs["output"].write_text(json.dumps(report), encoding="utf-8")
            kwargs["budget"].reserve_semantic(3)
            kwargs["budget"].record_provider_operations(3)
            return report

        unavailable = [
            {"role": role, "model": model, "availability": "UNAVAILABLE"}
            for role, model in CANDIDATES
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protocol = root / "protocol.yaml"
            protocol.write_text("locked: true\n", encoding="utf-8")
            result_path = root / "result.yaml"
            with (
                patch(
                    "tools.story_extraction.run_gemini_credential_qualification_v1.load_runtime_config",
                    return_value=SimpleNamespace(credentials=credentials),
                ),
                patch(
                    "tools.story_extraction.run_gemini_credential_qualification_v1._run_live_block",
                    side_effect=fake_live_block,
                ),
                patch(
                    "tools.story_extraction.run_gemini_credential_qualification_v1._model_availability",
                    return_value=unavailable,
                ),
            ):
                result = execute(
                    protocol_path=protocol,
                    output_dir=root / "blocks",
                    result_path=result_path,
                    profile_path=root / "profile.yaml",
                    sleep=lambda _: None,
                )

            self.assertEqual(calls, ["gemini_slot_1", "gemini_slot_2"])
            self.assertEqual(result["screened_credential_count"], 2)
            self.assertEqual(result["selected_credential_slot"], "gemini_slot_2")
            self.assertEqual(result["cross_slot_failover_count"], 0)
            self.assertEqual(result["credential_topology"], "UNKNOWN")
            self.assertFalse(result["quota_independence_claimed"])
            self.assertEqual(result["holdout"]["contamination"], "CLEAN")


if __name__ == "__main__":
    unittest.main()
