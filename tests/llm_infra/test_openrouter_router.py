from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fixtures import Clock, FakeOpenRouter, FakeOpenRouterHTTP, OPENROUTER_MODEL, OPENROUTER_TEST_KEY, openrouter_settings
from tools.llm_infra.openrouter_config import DEFAULT_ACCOUNT_SCOPE, inspect_openrouter_settings
from tools.llm_infra.openrouter_router import (
    ACCOUNT_WIDE_MODEL, OpenRouterQuotaPaused, OpenRouterRouter, OpenRouterTransportError,
)
from tools.llm_infra.openrouter_transport import OpenRouterHTTPError, OpenRouterResponse
from tools.llm_infra.quota_state import QuotaStateStore
from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError


class OpenRouterRouterTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.store = QuotaStateStore(None, clock=self.clock)

    def router(self, client, *labels, changes=None, **options):
        config = inspect_openrouter_settings(openrouter_settings(*labels) | (changes or {}))
        return OpenRouterRouter(config, self.store, client.factory if client else None, clock=self.clock,
                                sleep=self.clock.sleep, **options)

    def generate(self, router, model=OPENROUTER_MODEL):
        return router.generate("system", "user", model, {}, "request-id")

    def rate_limit(self, seconds):
        return OpenRouterHTTPError(kind="RATE_LIMIT", headers={"X-RateLimit-Limit": "20",
                                                              "Retry-After": str(seconds)})

    def test_group_priority_and_auth_disable_last_for_router_lifetime(self):
        client = FakeOpenRouter(OpenRouterHTTPError(kind="AUTH_FAILURE"))
        router = self.router(client, "", "other", "")
        for expected_attempts in (["AUTH_FAILURE", "SUCCESS"], ["SUCCESS"]):
            with self.subTest(attempts=expected_attempts):
                result = self.generate(router)
                self.assertEqual(result["slot_id"], "openrouter_slot_3")
                self.assertEqual(result["scope"], DEFAULT_ACCOUNT_SCOPE)
                self.assertEqual([attempt["outcome"] for attempt in result["transport_attempts"]],
                                 expected_attempts)
        self.assertEqual(client.factory_calls, [OPENROUTER_TEST_KEY, "test-openrouter-key-not-real-3",
                                                "test-openrouter-key-not-real-3"])
        client.actions.extend([OpenRouterHTTPError(kind="AUTH_FAILURE")] * 2)
        with self.assertRaises(OpenRouterTransportError) as caught:
            self.generate(router)
        self.assertEqual((caught.exception.code, caught.exception.attempts), ("NO_USABLE_CREDENTIAL", 2))
        self.assertEqual(self.store.active_blocks(self.clock()), [])

    def test_429_persists_across_models_and_never_rotates_within_account(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "state"
            self.store = QuotaStateStore(path, clock=self.clock)
            client = FakeOpenRouter(self.rate_limit(70))
            result = self.generate(self.router(client, "", "", "other"))
            self.assertEqual([attempt["slot_id"] for attempt in result["transport_attempts"]],
                             ["openrouter_slot_1", "openrouter_slot_3"])
            self.store = QuotaStateStore(path, clock=self.clock)
            restarted = self.router(client, "", "")
            with self.assertRaises(OpenRouterQuotaPaused) as caught:
                self.generate(restarted, "another/model:free")
            self.assertEqual((caught.exception.attempts, caught.exception.resume_after), (0, 1070))
            self.assertEqual(len(client.factory_calls), 2)
            block, = self.store.active_blocks(self.clock())
            self.assertEqual((block["provider"], block["model"], block["project_alias"], block["reason"]),
                             ("openrouter", ACCOUNT_WIDE_MODEL, DEFAULT_ACCOUNT_SCOPE, "RPM"))

    def test_hop_cap_pauses_with_earliest_refusal_and_preserves_untried_scope(self):
        client = FakeOpenRouter(self.rate_limit(80), self.rate_limit(15))
        router = self.router(client, "", "second", "third")
        with self.assertRaises(OpenRouterQuotaPaused) as caught:
            self.generate(router)
        error = caught.exception
        self.assertEqual((error.code, error.attempts, error.resume_after), ("QUOTA_EXHAUSTED", 2, 1015))
        self.assertIn("1970-01-01T00:16:55Z", str(error))
        self.assertEqual(self.clock.waits, [])
        self.assertEqual(self.generate(router)["slot_id"], "openrouter_slot_3")

    def test_inline_wait_happens_at_most_once_before_success_or_pause(self):
        for next_action, max_wait, expected_attempts, waits in [
            (None, 5, 2, [5]), (self.rate_limit(6), 60, 2, [5]), (None, 4, 1, []),
        ]:
            with self.subTest(second_429=next_action is not None, max_wait=max_wait):
                self.clock = Clock()
                self.store = QuotaStateStore(None, clock=self.clock)
                client = FakeOpenRouter(self.rate_limit(5), *([next_action] if next_action else []))
                router = self.router(client, "", changes={"OPENROUTER_MAX_RATE_LIMIT_HOPS": "3"},
                                     max_inline_wait_seconds=max_wait)
                if next_action or not waits:
                    with self.assertRaises(OpenRouterQuotaPaused) as caught:
                        self.generate(router)
                    self.assertEqual(caught.exception.attempts, expected_attempts)
                    self.assertEqual(caught.exception.resume_after, 1011 if next_action else 1005)
                else:
                    result = self.generate(router)
                    self.assertEqual(len(result["transport_attempts"]), expected_attempts)
                self.assertEqual(self.clock.waits, waits)
                self.assertEqual(client.factory_calls, [OPENROUTER_TEST_KEY] * expected_attempts)

    def test_payment_paid_usage_and_request_errors_stop_without_retry_or_block(self):
        for kind in ("PAYMENT_REQUIRED", "PAID_USAGE_DETECTED", "FORBIDDEN", "MODEL_UNAVAILABLE",
                     "REQUEST_TOO_LARGE", "REQUEST_FAILURE", "MALFORMED_RESPONSE", "MODEL_NOT_FREE"):
            with self.subTest(kind=kind):
                client = FakeOpenRouter(OpenRouterHTTPError(kind=kind, body={"private": OPENROUTER_TEST_KEY}))
                with self.assertRaises(OpenRouterTransportError) as caught:
                    self.generate(self.router(client, "", "", "other"))
                error = caught.exception
                self.assertEqual((error.code, error.attempts), (kind, 1))
                self.assertNotIn(OPENROUTER_TEST_KEY, repr(error))
                self.assertIsNone(error.__context__)
                self.assertEqual(client.factory_calls, [OPENROUTER_TEST_KEY])
                self.assertEqual(self.clock.waits, [])
                self.assertEqual(self.store.active_blocks(self.clock()), [])

    def test_transient_failures_back_off_and_use_the_same_slot(self):
        for number_of_failures in (2, 3):
            with self.subTest(number_of_failures=number_of_failures):
                self.clock = Clock()
                failures = [OpenRouterHTTPError(kind=kind)
                            for kind in ("SERVER_FAILURE", "TRANSPORT_FAILURE", "SERVER_FAILURE")]
                client = FakeOpenRouter(*failures[:number_of_failures])
                router = self.router(client, "", "other", base_backoff_seconds=0.25)
                if number_of_failures == 3:
                    with self.assertRaises(OpenRouterTransportError) as caught:
                        self.generate(router)
                    self.assertEqual((caught.exception.code, caught.exception.attempts), ("SERVER_FAILURE", 3))
                else:
                    result = self.generate(router)
                    self.assertEqual(result["latency_seconds"], 0.75)
                    self.assertEqual([attempt["outcome"] for attempt in result["transport_attempts"]],
                                     ["SERVER_FAILURE", "TRANSPORT_FAILURE", "SUCCESS"])
                self.assertEqual(self.clock.waits, [0.25, 0.5])
                self.assertEqual(client.factory_calls, [OPENROUTER_TEST_KEY] * 3)

    def test_success_reports_cost_and_clears_streak_with_redacted_record(self):
        quota_key = ("openrouter", ACCOUNT_WIDE_MODEL, DEFAULT_ACCOUNT_SCOPE)
        self.store.block(*quota_key, self.clock() - 1, "UNKNOWN_429", self.clock() - 70)
        response = OpenRouterResponse(OPENROUTER_TEST_KEY, {OPENROUTER_TEST_KEY: [OPENROUTER_TEST_KEY]},
                                      OPENROUTER_MODEL, {}, response_id=OPENROUTER_TEST_KEY, cost=0)
        router = self.router(FakeOpenRouter(response), "", "other")
        result = router.generate("", "", "openrouter/free", {}, OPENROUTER_TEST_KEY)
        self.assertEqual(self.store.unknown_streak(*quota_key), 0)
        self.assertEqual((result["provider"], result["transport"], result["quota_scope"], result["cost_reported"]),
                         ("OpenRouter", "OPENROUTER_ROUTER_V1", "account_model", 0))
        self.assertEqual((result["model_requested"], result["model_reported_if_available"]),
                         ("openrouter/free", OPENROUTER_MODEL))
        self.assertEqual(result["provider_response_metadata"], {"response_id": "[REDACTED]"})
        self.assertNotIn(OPENROUTER_TEST_KEY, repr(result))

    def test_default_client_sends_privacy_option_and_surfaces_http_402(self):
        http = FakeOpenRouterHTTP((402, {"Retry-After": "5"}, {"error": {"code": 402}}))
        with patch("tools.llm_infra.openrouter_transport._urllib_http", http):
            with self.assertRaises(OpenRouterTransportError) as caught:
                self.generate(self.router(None, "", "other", changes={"OPENROUTER_DATA_COLLECTION": "deny"}))
        self.assertEqual(caught.exception.code, "PAYMENT_REQUIRED")
        self.assertEqual(len(http.calls), 1)
        self.assertEqual(http.calls[0][2]["provider"], {"data_collection": "deny"})
        self.assertEqual(self.store.active_blocks(self.clock()), [])

    def test_invalid_configuration_and_models_stop_before_client(self):
        client = FakeOpenRouter()
        for options, message in [({"max_transport_retries": -1}, "transport retries"),
                                 ({"max_transport_retries": 1.5}, "transport retries"),
                                 ({"base_backoff_seconds": -1}, "backoff"),
                                 ({"max_inline_wait_seconds": float("inf")}, "wait limits")]:
            with self.subTest(options=options):
                with self.assertRaisesRegex(GeminiConfigError, message):
                    self.router(client, "", **options)
        router = self.router(client, "")
        for model, message in [("test/paid", "MODEL_NOT_FREE_TIER"),
                               (f"test/{OPENROUTER_TEST_KEY}:free", "credential material")]:
            with self.subTest(message=message):
                with self.assertRaisesRegex(GeminiConfigError, message):
                    self.generate(router, model)
        self.assertEqual(client.factory_calls, [])
