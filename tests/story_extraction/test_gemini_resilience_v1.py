"""Deterministic fault-injection tests for GEMINI_TRANSPORT_RESILIENCE_V1."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
import unittest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.story_extraction.gemini_errors_v1 import ErrorCategory, classify_error  # noqa: E402
from tools.story_extraction.gemini_key_pool_v1 import (  # noqa: E402
    GeminiConfigError,
    GeminiKeyPool,
    load_runtime_config,
)
from tools.story_extraction.gemini_resilience_v1 import (  # noqa: E402
    CIRCUIT_VERSION,
    RESILIENCE_VERSION,
    GeminiResilienceError,
    GeminiResilientTransport,
    ProjectLimit,
    ResiliencePolicy,
    conservative_runtime_credentials,
    estimate_input_tokens,
)


FAKE_SECRET = "FAKE_SECRET_NEVER_LEAK_123"


class FakeClock:
    def __init__(self, value=1_700_000_000.0):
        self.value = value
        self.sleeps = []
        self._lock = threading.RLock()

    def __call__(self):
        with self._lock:
            return self.value

    def sleep(self, seconds):
        with self._lock:
            self.sleeps.append(seconds)
            self.value += seconds


class ProviderError(Exception):
    def __init__(self, status_code, message="provider detail", retry_after=None):
        self.status_code = status_code
        self.retry_after = retry_after
        super().__init__(message)


def response(text='{"status":"ok"}', *, prompt=4, output=2, model="gemini-test"):
    return SimpleNamespace(
        text=text,
        parsed=None,
        model_version=model,
        response_id="response-test",
        usage_metadata=SimpleNamespace(
            prompt_token_count=prompt,
            candidates_token_count=output,
            total_token_count=prompt + output,
            cached_content_token_count=None,
            thoughts_token_count=None,
        ),
        candidates=[],
    )


class FakeFactory:
    def __init__(self, outcomes, lock=None):
        self.outcomes = list(outcomes)
        self.keys_seen = []
        self.calls = []
        self._lock = lock or threading.RLock()

    def __call__(self, api_key):
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
    return load_runtime_config(REPO / "missing-resilience-env", env)


def policy(**overrides):
    values = {
        "default_project_limit": ProjectLimit(rpm=10_000, tpm=1_000_000),
        "base_backoff_seconds": 1.0,
        "max_scheduler_wait_seconds": 300.0,
        "max_local_rate_wait_seconds": 300.0,
    }
    values.update(overrides)
    return ResiliencePolicy(**values)


def build(config, outcomes, *, clock=None, selected=None, policy_value=None, factory=None):
    clock = clock or FakeClock()
    credentials = tuple(selected) if selected is not None else config.credentials
    pool = GeminiKeyPool(credentials, clock=clock)
    factory = factory or FakeFactory(outcomes)
    gate = GeminiResilientTransport(
        pool,
        factory,
        policy=policy_value or policy(),
        clock=clock,
        sleep=clock.sleep,
        monotonic=time.monotonic,
    )
    return gate, factory, pool, clock


def generate(gate, request_id="request-1", *, max_output_tokens=8):
    return gate.generate(
        "Return JSON.",
        '{"request":"status"}',
        "gemini-test",
        {"temperature": 0, "max_output_tokens": max_output_tokens},
        request_id,
    )


class TestErrorClassification(unittest.TestCase):
    def test_central_categories(self):
        cases = [
            (ProviderError(429), ErrorCategory.RATE_LIMIT),
            (ProviderError(401), ErrorCategory.AUTH_FAILURE),
            (ProviderError(403), ErrorCategory.AUTH_FAILURE),
            (ProviderError(500), ErrorCategory.SERVER_FAILURE),
            (TimeoutError(), ErrorCategory.TIMEOUT),
            (ConnectionResetError(), ErrorCategory.NETWORK_FAILURE),
            (ValueError(), ErrorCategory.PROVIDER_FAILURE),
        ]
        for error, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(classify_error(error), expected)

    def test_invalid_key_400_is_auth_failure(self):
        self.assertEqual(
            classify_error(ProviderError(400, "API key not valid")), ErrorCategory.AUTH_FAILURE
        )


class TestSuccessAndBudgets(unittest.TestCase):
    def test_200_success(self):
        gate, _, _, _ = build(runtime_config((1, "s1", "p1")), [response()])
        result = generate(gate)
        self.assertEqual(result["resilience"], RESILIENCE_VERSION)
        self.assertEqual(result["attempt_accounting"]["total_provider_attempts"], 1)
        self.assertEqual(result["attempt_accounting"]["structural_repair_calls"], 0)

    def test_invalid_json_is_not_semantically_regenerated(self):
        gate, factory, _, _ = build(runtime_config((1, "s1", "p1")), [response("bad-json")])
        result = generate(gate)
        self.assertEqual(result["raw_content"], "bad-json")
        self.assertEqual(len(factory.calls), 1)

    def test_attempt_cap_never_exceeds_three(self):
        outcomes = [ProviderError(503) for _ in range(6)]
        gate, factory, _, _ = build(runtime_config((1, "s1", "p1")), outcomes)
        with self.assertRaises(GeminiResilienceError) as caught:
            generate(gate)
        self.assertEqual(caught.exception.provider_attempts, 3)
        self.assertEqual(len(factory.calls), 3)

    def test_retry_and_failover_budgets_are_separate(self):
        config = runtime_config((1, "s1", "p1"), (2, "s2", "p2"))
        gate, _, _, _ = build(config, [ProviderError(503), response()])
        result = generate(gate)
        accounting = result["attempt_accounting"]
        self.assertEqual(accounting["transport_retry_count"], 1)
        self.assertEqual(accounting["credential_failover_count"], 1)
        self.assertEqual(accounting["project_group_failover_count"], 1)
        self.assertEqual(accounting["total_provider_attempts"], 2)

    def test_auth_failover_does_not_consume_transport_retry(self):
        config = runtime_config((1, "s1", "p"), (2, "s2", "p"))
        gate, _, _, _ = build(config, [ProviderError(401), response()])
        accounting = generate(gate)["attempt_accounting"]
        self.assertEqual(accounting["transport_retry_count"], 0)
        self.assertEqual(accounting["credential_failover_count"], 1)
        self.assertEqual(accounting["project_group_failover_count"], 0)

    def test_policy_rejects_attempt_cap_above_three(self):
        with self.assertRaises(GeminiConfigError):
            policy(max_total_provider_attempts=4)


class TestProviderFaults(unittest.TestCase):
    def test_429_retry_after_is_respected(self):
        gate, _, _, clock = build(
            runtime_config((1, "s1", "p1")),
            [ProviderError(429, retry_after=7), response()],
        )
        result = generate(gate)
        self.assertIn(7.0, clock.sleeps)
        self.assertEqual(result["attempt_accounting"]["transport_retry_count"], 1)

    def test_repeated_429_is_bounded(self):
        gate, factory, _, _ = build(
            runtime_config((1, "s1", "p1")), [ProviderError(429) for _ in range(4)]
        )
        with self.assertRaises(GeminiResilienceError):
            generate(gate)
        self.assertEqual(len(factory.calls), 3)
        self.assertEqual(gate.metrics.snapshot()["rate_limit_event_count"], 3)

    def test_429_does_not_open_transport_circuit(self):
        gate, _, _, _ = build(
            runtime_config((1, "s1", "p1")),
            [ProviderError(429)],
            policy_value=policy(
                max_total_provider_attempts=1,
                max_transport_retries=0,
                circuit_failure_threshold=1,
            ),
        )
        with self.assertRaises(GeminiResilienceError):
            generate(gate)
        self.assertEqual(gate.health_snapshot()["groups"][0]["circuit_state"], "CLOSED")

    def test_independent_project_fails_over_immediately_after_429(self):
        config = runtime_config((1, "s1", "p1"), (2, "s2", "p2"))
        gate, factory, _, clock = build(config, [ProviderError(429, retry_after=20), response()])
        result = generate(gate)
        self.assertEqual(factory.keys_seen, ["s1", "s2"])
        self.assertNotIn(20.0, clock.sleeps)
        self.assertEqual(result["attempt_accounting"]["project_group_failover_count"], 1)

    def test_same_project_keys_share_429_cooldown(self):
        config = runtime_config((1, "s1", "p"), (2, "s2", "p"))
        gate, factory, _, clock = build(config, [ProviderError(429, retry_after=9), response()])
        generate(gate)
        self.assertEqual(factory.keys_seen, ["s1", "s2"])
        self.assertIn(9.0, clock.sleeps)

    def test_401_and_403_disable_only_one_slot(self):
        for status in (401, 403):
            with self.subTest(status=status):
                config = runtime_config((1, "s1", "p"), (2, "s2", "p"))
                gate, factory, _, _ = build(config, [ProviderError(status), response()])
                generate(gate)
                self.assertEqual(factory.keys_seen, ["s1", "s2"])
                self.assertEqual(gate.metrics.snapshot()["auth_disable_event_count"], 1)

    def test_server_statuses_retry_bounded(self):
        for status in (500, 502, 503, 504):
            with self.subTest(status=status):
                gate, factory, _, _ = build(
                    runtime_config((1, "s1", "p")),
                    [ProviderError(status), response()],
                )
                generate(gate)
                self.assertEqual(len(factory.calls), 2)
                self.assertEqual(gate.metrics.snapshot()["server_failure_count"], 1)

    def test_timeout_connection_reset_and_network_exception(self):
        faults = [TimeoutError(), ConnectionResetError(), OSError()]
        metrics = ["timeout_count", "network_failure_count", "network_failure_count"]
        for fault, metric in zip(faults, metrics):
            with self.subTest(metric=metric):
                gate, _, _, _ = build(
                    runtime_config((1, "s1", "p")), [fault, response()]
                )
                generate(gate)
                self.assertEqual(gate.metrics.snapshot()[metric], 1)

    def test_all_keys_disabled_fails_closed(self):
        config = runtime_config((1, "s1", "p"), (2, "s2", "p"))
        gate, factory, pool, _ = build(config, [response()])
        pool.disable_slot("gemini_slot_1")
        pool.disable_slot("gemini_slot_2")
        with self.assertRaises(GeminiResilienceError):
            generate(gate)
        self.assertEqual(factory.calls, [])

    def test_all_groups_cooling_waits_bounded_then_continues(self):
        config = runtime_config((1, "s1", "p1"), (2, "s2", "p2"))
        gate, _, pool, clock = build(config, [response()])
        pool.cool_project_group("gemini_slot_1", 5, now=clock())
        pool.cool_project_group("gemini_slot_2", 8, now=clock())
        generate(gate)
        self.assertIn(5.0, clock.sleeps)

    def test_one_dead_project_one_healthy_project(self):
        config = runtime_config((1, "dead", "p1"), (2, "healthy", "p2"))
        gate, factory, _, _ = build(config, [ProviderError(503), response()])
        generate(gate)
        self.assertEqual(factory.keys_seen, ["dead", "healthy"])

    def test_slow_success_records_provider_latency(self):
        clock = FakeClock()

        def slow(_):
            clock.sleep(2.5)
            return response()

        gate, _, _, _ = build(runtime_config((1, "s1", "p")), [slow], clock=clock)
        generate(gate)
        self.assertEqual(gate.metrics.snapshot()["provider_latency_ms_p50"], 2500.0)


class TestRateLimiters(unittest.TestCase):
    def test_rpm_throttling(self):
        clock = FakeClock()
        gate, _, _, _ = build(
            runtime_config((1, "s1", "p")),
            [response(), response()],
            clock=clock,
            policy_value=policy(default_project_limit=ProjectLimit(rpm=1, tpm=1000)),
        )
        generate(gate, "one", max_output_tokens=5)
        generate(gate, "two", max_output_tokens=5)
        self.assertIn(60.0, clock.sleeps)
        self.assertEqual(gate.metrics.snapshot()["local_rpm_wait_count"], 1)

    def test_tpm_throttling_uses_post_request_correction(self):
        clock = FakeClock()
        first = response(prompt=15, output=4)
        gate, _, _, _ = build(
            runtime_config((1, "s1", "p")),
            [first, response(prompt=2, output=1)],
            clock=clock,
            policy_value=policy(default_project_limit=ProjectLimit(rpm=100, tpm=20)),
        )
        generate(gate, "one", max_output_tokens=5)
        generate(gate, "two", max_output_tokens=5)
        self.assertIn(60.0, clock.sleeps)
        metrics = gate.metrics.snapshot()
        self.assertEqual(metrics["local_tpm_wait_count"], 1)
        self.assertEqual(metrics["actual_input_tokens"], 17)
        self.assertEqual(metrics["actual_output_tokens"], 5)

    def test_same_project_keys_share_rpm_and_tpm(self):
        clock = FakeClock()
        config = runtime_config((1, "s1", "shared"), (2, "s2", "shared"))
        gate, factory, _, _ = build(
            config,
            [response(), response()],
            clock=clock,
            policy_value=policy(default_project_limit=ProjectLimit(rpm=1, tpm=1000)),
        )
        generate(gate, "one", max_output_tokens=5)
        generate(gate, "two", max_output_tokens=5)
        self.assertEqual(factory.keys_seen, ["s1", "s2"])
        self.assertEqual(gate.metrics.snapshot()["local_rpm_wait_count"], 1)

    def test_token_estimator_is_deterministic_and_local(self):
        self.assertEqual(estimate_input_tokens("abc", "def"), 2)
        self.assertEqual(estimate_input_tokens("abc", "def"), 2)


class TestCircuitBreaker(unittest.TestCase):
    def _single_attempt_policy(self):
        return policy(
            max_total_provider_attempts=1,
            max_transport_retries=0,
            circuit_failure_threshold=3,
            circuit_open_cooldown_seconds=30,
        )

    def test_closed_to_open_and_open_blocks_calls(self):
        gate, factory, _, _ = build(
            runtime_config((1, "s1", "p")),
            [ProviderError(503), ProviderError(503), ProviderError(503), response()],
            policy_value=self._single_attempt_policy(),
        )
        for index in range(3):
            with self.assertRaises(GeminiResilienceError):
                generate(gate, str(index))
        self.assertEqual(gate.health_snapshot()["groups"][0]["circuit_state"], "OPEN")
        with self.assertRaises(GeminiResilienceError):
            generate(gate, "blocked")
        self.assertEqual(len(factory.calls), 3)

    def test_open_to_half_open_success_to_closed(self):
        clock = FakeClock()
        gate, _, _, _ = build(
            runtime_config((1, "s1", "p")),
            [ProviderError(503), ProviderError(503), ProviderError(503), response()],
            clock=clock,
            policy_value=self._single_attempt_policy(),
        )
        for index in range(3):
            with self.assertRaises(GeminiResilienceError):
                generate(gate, str(index))
        clock.sleep(30)
        generate(gate, "probe")
        metrics = gate.metrics.snapshot()
        self.assertEqual(metrics["circuit_half_open_count"], 1)
        self.assertEqual(metrics["circuit_recovery_count"], 1)
        self.assertEqual(gate.health_snapshot()["groups"][0]["circuit_state"], "CLOSED")

    def test_half_open_failure_reopens(self):
        clock = FakeClock()
        gate, _, _, _ = build(
            runtime_config((1, "s1", "p")),
            [ProviderError(503), ProviderError(503), ProviderError(503), ProviderError(503)],
            clock=clock,
            policy_value=self._single_attempt_policy(),
        )
        for index in range(3):
            with self.assertRaises(GeminiResilienceError):
                generate(gate, str(index))
        clock.sleep(30)
        with self.assertRaises(GeminiResilienceError):
            generate(gate, "probe")
        self.assertEqual(gate.health_snapshot()["groups"][0]["circuit_state"], "OPEN")


class BlockingFactory:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self._lock = threading.Lock()

    def __call__(self, api_key):
        factory = self

        class Client:
            def generate(self, **kwargs):
                with factory._lock:
                    factory.calls += 1
                    call_number = factory.calls
                if call_number == 1:
                    factory.started.set()
                    if not factory.release.wait(3):
                        raise TimeoutError()
                return response()

        return Client()


class TestConcurrencyQueueAndHealth(unittest.TestCase):
    def test_queue_saturation_rejects_without_unbounded_spawn(self):
        config = runtime_config((1, "s1", "p"))
        factory = BlockingFactory()
        clock = FakeClock()
        gate, _, _, _ = build(
            config,
            [],
            clock=clock,
            factory=factory,
            policy_value=policy(
                max_total_provider_attempts=1,
                max_transport_retries=0,
                max_concurrency=1,
                queue_capacity=1,
                queue_wait_timeout_seconds=3,
            ),
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(generate, gate, "first")
            self.assertTrue(factory.started.wait(1))
            second = executor.submit(generate, gate, "second")
            deadline = time.time() + 1
            while gate.health_snapshot()["queued_requests"] != 1 and time.time() < deadline:
                time.sleep(0.01)
            with self.assertRaises(GeminiResilienceError) as caught:
                generate(gate, "third")
            self.assertEqual(caught.exception.category, ErrorCategory.QUEUE_REJECTED)
            factory.release.set()
            first.result(timeout=2)
            second.result(timeout=2)
        health = gate.health_snapshot()
        self.assertLessEqual(health["max_active_seen"], 1)
        self.assertEqual(health["max_queue_depth_seen"], 1)
        self.assertEqual(health["metrics"]["queue_rejected_count"], 1)

    def test_health_snapshot_is_sanitized(self):
        gate, _, _, _ = build(runtime_config((1, FAKE_SECRET, "safe-project")), [response()])
        generate(gate)
        serialized = json.dumps(gate.health_snapshot(), sort_keys=True)
        self.assertNotIn(FAKE_SECRET, serialized)
        self.assertIn(CIRCUIT_VERSION.split("_")[0], CIRCUIT_VERSION)


class TestConservativeUnknownAndHighVolume(unittest.TestCase):
    def test_multiple_unknown_credentials_reduce_to_one(self):
        config = runtime_config((1, "s1", ""), (2, "s2", ""), (3, "s3", ""))
        selected = conservative_runtime_credentials(config.credentials)
        self.assertEqual([slot.slot_id for slot in selected], ["gemini_slot_1"])

    def test_labeled_groups_remain_and_only_one_unknown_is_kept(self):
        config = runtime_config((1, "s1", ""), (2, "s2", "p2"), (3, "s3", ""))
        selected = conservative_runtime_credentials(config.credentials)
        self.assertEqual([slot.slot_id for slot in selected], ["gemini_slot_1", "gemini_slot_2"])

    def test_500_request_offline_scheduler_simulation(self):
        config = runtime_config((1, "s1", "p1"), (2, "s2", "p2"))
        def tiny_slow_success(_):
            time.sleep(0.0005)
            return response()

        outcomes = [tiny_slow_success for _ in range(500)]
        gate, factory, _, _ = build(
            config,
            outcomes,
            policy_value=policy(max_concurrency=2, queue_capacity=16),
        )
        # Submit in bounded batches: never more than eight worker/future objects.
        with ThreadPoolExecutor(max_workers=8) as executor:
            for start in range(0, 500, 8):
                futures = [
                    executor.submit(generate, gate, f"sim-{index}")
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
        self.assertEqual(metrics["request_success_count"], 500)
        self.assertEqual(factory.keys_seen.count("s1"), 250)
        self.assertEqual(factory.keys_seen.count("s2"), 250)
        self.assertLessEqual(gate.health_snapshot()["max_active_seen"], 2)
        self.assertLessEqual(gate.health_snapshot()["max_queue_depth_seen"], 16)


class TestSecretLeakAndNoFallback(unittest.TestCase):
    def test_secret_absent_from_every_public_surface(self):
        config = runtime_config((1, FAKE_SECRET, "safe"))
        gate, _, pool, _ = build(config, [response(FAKE_SECRET)])
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = generate(gate)
        surfaces = [
            json.dumps(result, sort_keys=True),
            json.dumps(gate.metrics.snapshot(), sort_keys=True),
            json.dumps(gate.health_snapshot(), sort_keys=True),
            json.dumps(pool.public_metadata(), sort_keys=True),
            repr(gate),
            repr(config.credentials[0]),
            stdout.getvalue(),
            stderr.getvalue(),
        ]
        self.assertTrue(all(FAKE_SECRET not in surface for surface in surfaces))
        self.assertEqual(result["raw_content"], "[REDACTED]")

    def test_provider_exception_is_sanitized(self):
        gate, _, _, _ = build(
            runtime_config((1, FAKE_SECRET, "safe")),
            [ProviderError(400, FAKE_SECRET)],
            policy_value=policy(max_total_provider_attempts=1),
        )
        with self.assertRaises(GeminiResilienceError) as caught:
            generate(gate)
        self.assertNotIn(FAKE_SECRET, str(caught.exception))
        self.assertNotIn(FAKE_SECRET, repr(caught.exception))

    def test_no_model_or_provider_fallback_in_resilience_source(self):
        source = (REPO / "tools/story_extraction/gemini_resilience_v1.py").read_text(
            encoding="utf-8"
        ).lower()
        self.assertNotIn("olla" + "ma", source)
        self.assertNotIn("model_fallback", source)


if __name__ == "__main__":
    unittest.main()
