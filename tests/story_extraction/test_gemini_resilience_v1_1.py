"""Deterministic remediation tests for GEMINI_TRANSPORT_RESILIENCE_V1_1."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
import unittest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.story_extraction.gemini_errors_v1 import (  # noqa: E402
    ErrorCategory,
    failure_fingerprint,
    rate_limit_cause,
    sanitized_failure_metadata,
)
from tools.story_extraction.gemini_key_pool_v1 import GeminiKeyPool, load_runtime_config  # noqa: E402
from tools.story_extraction.gemini_resilience_v1 import ProjectLimit  # noqa: E402
from tools.story_extraction.gemini_resilience_v1_1 import (  # noqa: E402
    RESILIENCE_VERSION,
    GeminiResilienceV11Error,
    GeminiResilientTransportV11,
    ResiliencePolicyV11,
    live_safe_credentials,
    load_resilience_policy_v1_1,
)


FAKE_SECRET = "V11_FAKE_SECRET_MUST_NOT_LEAK"


class FakeClock:
    def __init__(self, value: float = 1_700_000_000.0) -> None:
        self.value = value
        self.sleeps: list[float] = []
        self._lock = threading.RLock()

    def __call__(self) -> float:
        with self._lock:
            return self.value

    def sleep(self, seconds: float) -> None:
        with self._lock:
            self.sleeps.append(seconds)
            self.value += seconds


class ProviderError(Exception):
    def __init__(
        self,
        status_code: int,
        message: str = "provider detail",
        *,
        retry_after: float | None = None,
        reason: str | None = None,
        quota_text: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.retry_after = retry_after
        self.status = reason
        detail = {"quotaMetric": quota_text} if quota_text else {}
        self.response_json = {
            "error": {"code": status_code, "status": reason, "details": [detail]}
        }
        super().__init__(message)


def response(model: str = "gemini-test"):
    return SimpleNamespace(
        text='{"status":"ok"}',
        parsed=None,
        model_version=model,
        response_id="response-test",
        usage_metadata=SimpleNamespace(
            prompt_token_count=4,
            candidates_token_count=2,
            total_token_count=6,
            cached_content_token_count=None,
            thoughts_token_count=None,
        ),
        candidates=[],
    )


class FakeFactory:
    def __init__(self, outcomes) -> None:
        self.outcomes = list(outcomes)
        self.keys_seen: list[str] = []
        self.calls: list[dict] = []
        self._lock = threading.RLock()

    def __call__(self, api_key: str):
        factory = self
        with self._lock:
            self.keys_seen.append(api_key)

        class Client:
            def generate(self, **kwargs):
                with factory._lock:
                    factory.calls.append(kwargs)
                    outcome = factory.outcomes.pop(0)
                if isinstance(outcome, BaseException):
                    raise outcome
                if callable(outcome):
                    return outcome(kwargs)
                return outcome

        return Client()


def runtime_config(*items):
    env = {"GEMINI_MODEL": "gemini-test"}
    for number, secret, label in items:
        env[f"GEMINI_API_KEY_{number}"] = secret
        env[f"GEMINI_PROJECT_LABEL_{number}"] = label
    return load_runtime_config(REPO / "missing-v11-env", env)


def policy(**overrides):
    values = {
        "default_project_limit": ProjectLimit(rpm=10_000, tpm=1_000_000),
        "max_scheduler_wait_seconds": 300.0,
        "max_local_rate_wait_seconds": 300.0,
        "base_backoff_seconds": 1.0,
    }
    values.update(overrides)
    return ResiliencePolicyV11(**values)


def build(config, outcomes, *, clock=None, policy_value=None, random_unit=lambda: 0.5):
    clock = clock or FakeClock()
    pool = GeminiKeyPool(config.credentials, clock=clock)
    factory = FakeFactory(outcomes)
    gate = GeminiResilientTransportV11(
        pool,
        factory,
        policy=policy_value or policy(),
        clock=clock,
        sleep=clock.sleep,
        monotonic=time.monotonic,
        random_unit=random_unit,
    )
    return gate, factory, clock


def generate(gate, request_id="request-1", *, model="gemini-test"):
    return gate.generate(
        "Return JSON.",
        '{"request":"status"}',
        model,
        {"temperature": 0, "max_output_tokens": 8},
        request_id,
    )


class TestAttemptAccounting(unittest.TestCase):
    def test_each_retry_consumes_fresh_rpm_and_tpm_reservation(self):
        gate, factory, _ = build(
            runtime_config((1, "s1", "p1")),
            [ProviderError(503), ProviderError(503), response()],
        )
        result = generate(gate)
        metrics = gate.metrics.snapshot()
        self.assertEqual(len(factory.calls), 3)
        self.assertEqual(result["attempt_accounting"]["total_provider_attempts"], 3)
        self.assertEqual(metrics["provider_attempt_count"], 3)
        self.assertEqual(metrics["rpm_reservation_count"], 3)
        self.assertEqual(metrics["tpm_reservation_count"], 3)

    def test_each_project_failover_attempt_consumes_fresh_reservation(self):
        gate, factory, _ = build(
            runtime_config((1, "s1", "p1"), (2, "s2", "p2")),
            [ProviderError(503), response()],
        )
        result = generate(gate)
        self.assertEqual(factory.keys_seen, ["s1", "s2"])
        self.assertEqual(result["attempt_accounting"]["project_group_failover_count"], 1)
        self.assertEqual(gate.metrics.snapshot()["rpm_reservation_count"], 2)

    def test_provider_attempt_cap_always_wins(self):
        gate, factory, _ = build(
            runtime_config((1, "s1", "p1")), [ProviderError(503) for _ in range(6)]
        )
        with self.assertRaises(GeminiResilienceV11Error) as caught:
            generate(gate)
        self.assertEqual(caught.exception.provider_attempts, 3)
        self.assertEqual(len(factory.calls), 3)

    def test_auth_uses_credential_failover_not_transport_retry(self):
        gate, factory, _ = build(
            runtime_config((1, "s1", "shared"), (2, "s2", "shared")),
            [ProviderError(401), response()],
        )
        accounting = generate(gate)["attempt_accounting"]
        self.assertEqual(factory.keys_seen, ["s1", "s2"])
        self.assertEqual(accounting["credential_failover_count"], 1)
        self.assertEqual(accounting["project_group_failover_count"], 0)
        self.assertEqual(accounting["transport_retry_count"], 0)


class TestModelAwareLimits(unittest.TestCase):
    def test_model_specific_buckets_are_independent(self):
        clock = FakeClock()
        gate, _, _ = build(
            runtime_config((1, "s1", "p1")),
            [response("model-a"), response("model-b")],
            clock=clock,
            policy_value=policy(default_project_limit=ProjectLimit(rpm=1, tpm=1000)),
        )
        generate(gate, "a", model="model-a")
        generate(gate, "b", model="model-b")
        self.assertNotIn(60.0, clock.sleeps)
        buckets = gate.health_snapshot()["project_model_buckets"]
        self.assertEqual({item["model"] for item in buckets}, {"model-a", "model-b"})

    def test_project_model_override_does_not_apply_to_other_model(self):
        clock = FakeClock()
        gate, _, _ = build(
            runtime_config((1, "s1", "p1")),
            [response(), response()],
            clock=clock,
            policy_value=policy(
                default_project_limit=ProjectLimit(rpm=100, tpm=1000),
                project_model_limits={("p1", "gemini-test"): ProjectLimit(rpm=1, tpm=1000)},
            ),
        )
        generate(gate, "one")
        generate(gate, "two")
        self.assertIn(60.0, clock.sleeps)

    def test_local_limit_config_is_optional_and_conservative(self):
        loaded = load_resilience_policy_v1_1(
            REPO / "missing-policy-env",
            {"GEMINI_DEFAULT_RPM": "7", "GEMINI_DEFAULT_TPM": "900"},
        )
        self.assertEqual(loaded.default_project_limit, ProjectLimit(rpm=7, tpm=900))


class TestAdaptive429(unittest.TestCase):
    def test_retry_after_429_is_honored_and_factor_reduced(self):
        clock = FakeClock()
        gate, _, _ = build(
            runtime_config((1, "s1", "p1")),
            [ProviderError(429, retry_after=7, reason="RESOURCE_EXHAUSTED"), response()],
            clock=clock,
        )
        result = generate(gate)
        self.assertIn(7.0, clock.sleeps)
        first = result["transport_attempts"][0]
        self.assertTrue(first["retry_after_present"])
        self.assertEqual(first["fingerprint"], "RATE_LIMIT:RESOURCE_EXHAUSTED")
        metrics = gate.metrics.snapshot()
        self.assertEqual(metrics["adaptive_rate_limit_event_count"], 1)
        self.assertEqual(metrics["retry_after_429_count"], 1)

    def test_same_project_key_rotation_cannot_bypass_429_cooldown(self):
        clock = FakeClock()
        gate, factory, _ = build(
            runtime_config((1, "s1", "shared"), (2, "s2", "shared")),
            [ProviderError(429, retry_after=9), response()],
            clock=clock,
        )
        generate(gate)
        self.assertEqual(factory.keys_seen, ["s1", "s2"])
        self.assertIn(9.0, clock.sleeps)

    def test_explicit_independent_project_is_preferred_after_429(self):
        clock = FakeClock()
        gate, factory, _ = build(
            runtime_config((1, "s1", "p1"), (2, "s2", "p2")),
            [ProviderError(429, retry_after=20), response()],
            clock=clock,
        )
        result = generate(gate)
        self.assertEqual(factory.keys_seen, ["s1", "s2"])
        self.assertNotIn(20.0, clock.sleeps)
        self.assertEqual(result["attempt_accounting"]["project_group_failover_count"], 1)

    def test_adaptive_recovery_is_gradual_and_bounded(self):
        clock = FakeClock()
        gate, _, _ = build(
            runtime_config((1, "s1", "p1")),
            [ProviderError(429, retry_after=1), response(), response()],
            clock=clock,
            policy_value=policy(adaptive_successes_per_recovery=2),
        )
        generate(gate, "first")
        generate(gate, "second")
        bucket = gate.health_snapshot()["project_model_buckets"][0]["rate_limit"]
        self.assertGreater(bucket["effective_factor"], 0.5)
        self.assertLessEqual(bucket["effective_factor"], 1.0)


class TestBackoffAndCircuit(unittest.TestCase):
    def test_retry_after_5xx_precedes_exponential_backoff(self):
        clock = FakeClock()
        gate, _, _ = build(
            runtime_config((1, "s1", "p1")),
            [ProviderError(503, retry_after=6), response()],
            clock=clock,
        )
        result = generate(gate)
        self.assertIn(6.0, clock.sleeps)
        self.assertEqual(result["transport_attempts"][0]["backoff_sleep_seconds"], 6.0)
        self.assertEqual(gate.metrics.snapshot()["retry_after_5xx_count"], 1)

    def test_jittered_exponential_backoff_is_bounded_and_injectable(self):
        clock = FakeClock()
        gate, _, _ = build(
            runtime_config((1, "s1", "p1")),
            [ProviderError(503), ProviderError(503), response()],
            clock=clock,
            random_unit=lambda: 1.0,
        )
        result = generate(gate)
        self.assertEqual(clock.sleeps[:2], [1.2, 2.4])
        self.assertEqual(
            [item["backoff_sleep_seconds"] for item in result["transport_attempts"][:2]],
            [1.2, 2.4],
        )

    def test_429_preserves_prior_5xx_streak(self):
        one_attempt = policy(
            max_total_provider_attempts=1,
            max_transport_retries=0,
            circuit_failure_threshold=3,
            adaptive_rate_limit_cooldown_seconds=1,
        )
        gate, factory, _ = build(
            runtime_config((1, "s1", "p1")),
            [ProviderError(503), ProviderError(503), ProviderError(429), ProviderError(503)],
            policy_value=one_attempt,
        )
        for index in range(4):
            with self.assertRaises(GeminiResilienceV11Error):
                generate(gate, f"mixed-{index}")
        bucket = gate.health_snapshot()["project_model_buckets"][0]
        self.assertEqual(bucket["circuit"]["state"], "OPEN")
        self.assertEqual(bucket["circuit"]["failure_streak"], 3)
        self.assertEqual(len(factory.calls), 4)


class TestDiagnosticsAndUnknownPolicy(unittest.TestCase):
    def test_sanitized_fingerprint_has_no_raw_message(self):
        error = ProviderError(
            429,
            FAKE_SECRET,
            reason="RESOURCE_EXHAUSTED",
            quota_text="requests_per_minute",
        )
        metadata = sanitized_failure_metadata(error, 1_700_000_000.0)
        serialized = json.dumps(metadata, sort_keys=True)
        self.assertNotIn(FAKE_SECRET, serialized)
        self.assertEqual(failure_fingerprint(error), "RATE_LIMIT:RESOURCE_EXHAUSTED")
        self.assertEqual(rate_limit_cause(error), "RPM_EXHAUSTION")

    def test_5xx_fingerprints_retain_only_http_code(self):
        for status in (500, 502, 503, 504):
            with self.subTest(status=status):
                self.assertEqual(
                    failure_fingerprint(ProviderError(status, FAKE_SECRET)),
                    f"SERVER_FAILURE:{status}",
                )

    def test_all_unknown_live_credentials_reduce_to_one(self):
        config = runtime_config((1, "s1", ""), (2, "s2", ""), (100, "s100", ""))
        selected = live_safe_credentials(config.credentials)
        self.assertEqual([item.slot_id for item in selected], ["gemini_slot_1"])

    def test_labeled_live_credentials_exclude_unknown_slots(self):
        config = runtime_config((1, "s1", ""), (2, "s2", "p2"), (3, "s3", "p3"))
        selected = live_safe_credentials(config.credentials)
        self.assertEqual([item.slot_id for item in selected], ["gemini_slot_2", "gemini_slot_3"])

    def test_failed_attempt_timeline_is_secret_safe(self):
        gate, _, _ = build(
            runtime_config((1, FAKE_SECRET, "p1")),
            [ProviderError(503, FAKE_SECRET)],
            policy_value=policy(max_total_provider_attempts=1, max_transport_retries=0),
        )
        with self.assertRaises(GeminiResilienceV11Error) as caught:
            generate(gate)
        serialized = json.dumps(caught.exception.attempts, sort_keys=True)
        self.assertNotIn(FAKE_SECRET, serialized)
        self.assertIn("SERVER_FAILURE:503", serialized)


class TestHighVolumeSimulation(unittest.TestCase):
    def test_500_requests_are_bounded_fair_and_model_aware(self):
        config = runtime_config((1, "s1", "p1"), (2, "s2", "p2"))

        def tiny_success(_):
            time.sleep(0.0005)
            return response("model-a")

        clock = FakeClock()
        pool = GeminiKeyPool(config.credentials, clock=clock)
        factory = FakeFactory([tiny_success for _ in range(500)])
        gate = GeminiResilientTransportV11(
            pool,
            factory,
            policy=policy(max_concurrency=2, queue_capacity=16),
            clock=clock,
            sleep=clock.sleep,
            monotonic=time.monotonic,
            random_unit=lambda: 0.5,
        )
        with ThreadPoolExecutor(max_workers=8) as executor:
            for start in range(0, 500, 8):
                futures = [
                    executor.submit(generate, gate, f"sim-{index}", model="model-a")
                    for index in range(start, min(start + 8, 500))
                ]
                for future in futures:
                    result = future.result(timeout=3)
                    self.assertLessEqual(
                        result["attempt_accounting"]["total_provider_attempts"], 3
                    )
        metrics = gate.metrics.snapshot()
        self.assertEqual(metrics["semantic_request_count"], 500)
        self.assertEqual(metrics["provider_attempt_count"], 500)
        self.assertEqual(metrics["rpm_reservation_count"], 500)
        self.assertEqual(factory.keys_seen.count("s1"), 250)
        self.assertEqual(factory.keys_seen.count("s2"), 250)
        health = gate.health_snapshot()
        self.assertLessEqual(health["max_active_seen"], 2)
        self.assertLessEqual(health["max_queue_depth_seen"], 16)
        self.assertEqual(
            {item["model"] for item in health["project_model_buckets"]}, {"model-a"}
        )


if __name__ == "__main__":
    unittest.main()

