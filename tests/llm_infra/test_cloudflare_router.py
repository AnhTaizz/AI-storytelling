from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fixtures import (
    CF_ACCOUNT, CF_MODEL, CF_OTHER_ACCOUNT, CF_TOKEN, Clock, FakeCloudflare, cloudflare_body, cloudflare_settings,
)
from tools.llm_infra.cloudflare_config import GeminiConfigError, inspect_cloudflare_settings
from tools.llm_infra.cloudflare_free_models_v1 import DEFAULT_MODEL_CHAIN
from tools.llm_infra.cloudflare_router import CloudflareQuotaPaused, CloudflareRouter, CloudflareTransportError
from tools.llm_infra.cloudflare_transport import CloudflareClient
from tools.llm_infra.neuron_ledger import NeuronLedger, utc_day
from tools.llm_infra.quota_state import QuotaStateStore


class CloudflareRouterTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.store = QuotaStateStore(None, clock=self.clock)
        self.ledger = NeuronLedger()
        self.first_scope = "cloudflare_account_1"
        self.other_scope = "cloudflare_account_3"
        self.accounts = cloudflare_settings(CF_ACCOUNT, CF_ACCOUNT, CF_OTHER_ACCOUNT)
        self.success = (200, {}, cloudflare_body())

    def router(self, *actions, settings=None, **options):
        self.fake = FakeCloudflare(CloudflareClient, *actions)
        config = inspect_cloudflare_settings(self.accounts | (settings or {}))
        return CloudflareRouter(config, self.store, self.fake.factory, ledger=self.ledger,
                                clock=self.clock, sleep=self.clock.sleep, **options)

    def generate(self, router, model=CF_MODEL, text="synthetic query"):
        return router.generate("Reply with JSON.", text, model, {}, f"{CF_ACCOUNT}:{CF_TOKEN}")

    def used(self, scope):
        return self.ledger.used("cloudflare", scope, utc_day(self.clock()))

    def test_precheck_skips_an_account_across_models_and_reports_earliest_resume(self):
        router = self.router(self.success, settings={"CLOUDFLARE_DAILY_NEURON_BUDGET": "5"})
        self.ledger.add("cloudflare", self.first_scope, utc_day(self.clock()), 5, self.clock())
        record = self.generate(router)
        self.assertEqual((record["scope"], record["neurons_estimated"], record["neurons_used_today"]),
                         (self.other_scope, 2, 2))
        self.assertEqual((record["provider"], record["transport"], record["quota_scope"]),
                         ("Cloudflare Workers AI", "CLOUDFLARE_ROUTER_V1", "account_neurons"))
        self.store.block("cloudflare", "*", self.other_scope, 1100, "RPM", self.clock())
        with self.assertRaises(CloudflareQuotaPaused) as raised:
            self.generate(router, DEFAULT_MODEL_CHAIN[1])
        self.assertEqual((raised.exception.attempts, raised.exception.resume_after), (0, 1100))
        self.assertEqual(self.fake.factory_calls, [(CF_OTHER_ACCOUNT, "test-cf-token-not-real-3")])
        self.assertEqual(self.store.blocked_until("cloudflare", "*", self.first_scope, self.clock()), 86400)
        self.assertEqual(self.used(self.first_scope), 5)

    def test_success_adds_usage_or_estimates_missing_sides_and_blocks_at_budget(self):
        text = "x" * 90
        for usage, amount in [({}, 4), ({"prompt_tokens": 1}, 3), ({"completion_tokens": 1}, 2)]:
            with self.subTest(usage=usage):
                self.ledger = NeuronLedger()
                self.store = QuotaStateStore(None, clock=self.clock)
                body = cloudflare_body(usage=usage, choices=[{"message": {"content": text}}],
                                       id=f"/accounts/{CF_ACCOUNT}/ai/{CF_TOKEN}")
                router = self.router((200, {}, body), settings={"CLOUDFLARE_DAILY_NEURON_BUDGET": str(amount)})
                record = self.generate(router, text=text)
                self.assertEqual((record["neurons_estimated"], record["neurons_used_today"]), (amount, amount))
                self.assertEqual(self.used(self.first_scope), amount)
                self.assertEqual(self.store.active_blocks(self.clock())[0]["reason"], "RPD")
                for secret in (CF_ACCOUNT, CF_TOKEN):
                    self.assertNotIn(secret, repr(record))

    def test_all_accounts_over_budget_pause_even_just_before_midnight(self):
        self.accounts = cloudflare_settings(CF_ACCOUNT)
        self.clock.now = 86399
        router = self.router(self.success, settings={"CLOUDFLARE_DAILY_NEURON_BUDGET": "2"})
        self.ledger.add("cloudflare", self.first_scope, utc_day(self.clock()), 2, self.clock())
        with self.assertRaises(CloudflareQuotaPaused) as raised:
            self.generate(router)
        self.assertEqual((raised.exception.attempts, raised.exception.resume_after), (0, 86400))
        self.assertEqual(self.clock.waits, [])
        self.assertEqual(self.fake.factory_calls, [])
        self.clock.now = 86400
        self.assertEqual(self.generate(router)["neurons_used_today"], 2)
        self.assertEqual(self.store.blocked_until("cloudflare", "*", self.first_scope, self.clock()), 172800)

    def test_quota_refusals_hop_between_accounts_and_stop_at_limit(self):
        daily = (429, {}, {"errors": [{"code": 3036}]})
        for limit in (1, 2):
            with self.subTest(limit=limit):
                self.store = QuotaStateStore(None, clock=self.clock)
                router = self.router(daily, (429, {"Retry-After": "120"}, {}),
                                     settings={"CLOUDFLARE_MAX_RATE_LIMIT_HOPS": str(limit)})
                with self.assertRaises(CloudflareQuotaPaused) as raised:
                    self.generate(router)
                self.assertEqual((raised.exception.attempts, raised.exception.resume_after),
                                 (limit, 86400 if limit == 1 else 1120))
                self.assertEqual([account for account, _ in self.fake.factory_calls], [CF_ACCOUNT, CF_OTHER_ACCOUNT][:limit])
                self.assertEqual([row["reason"] for row in self.store.active_blocks(self.clock())], ["RPD", "RPM"][:limit])
                self.assertEqual(self.used(self.first_scope), 0)

    def test_minute_limit_can_wait_inline_once_then_succeed(self):
        self.accounts = cloudflare_settings(CF_ACCOUNT, CF_ACCOUNT)
        router = self.router((429, {"Retry-After": "3"}, {}), self.success)
        record = self.generate(router)
        self.assertEqual(self.clock.waits, [3])
        self.assertEqual([a["outcome"] for a in record["transport_attempts"]], ["RATE_LIMIT", "SUCCESS"])
        self.assertEqual(self.fake.factory_calls, [(CF_ACCOUNT, CF_TOKEN)] * 2)
        self.assertEqual(self.store.active_blocks(self.clock()), [])

    def test_repeated_minute_blocks_pause_after_one_inline_wait_even_with_hops_left(self):
        self.accounts = cloudflare_settings(CF_ACCOUNT)
        refusal = (429, {"Retry-After": "3"}, {})
        router = self.router(refusal, refusal, settings={"CLOUDFLARE_MAX_RATE_LIMIT_HOPS": "5"})
        with self.assertRaises(CloudflareQuotaPaused) as raised:
            self.generate(router)
        self.assertEqual((raised.exception.attempts, raised.exception.resume_after), (2, 1006))
        self.assertEqual(self.clock.waits, [3])

    def test_capacity_and_transport_retries_back_off_without_blocking_slot(self):
        router = self.router((429, {}, {"errors": [{"code": 3040}]}), (408, {}, {}), self.success,
                             max_transport_retries=2)
        record = self.generate(router)
        self.assertEqual(self.clock.waits, [1, 2])
        self.assertEqual([a["outcome"] for a in record["transport_attempts"]],
                         ["SERVER_FAILURE", "TRANSPORT_FAILURE", "SUCCESS"])
        self.assertEqual(self.fake.factory_calls, [(CF_ACCOUNT, CF_TOKEN)] * 3)
        self.assertEqual(self.store.active_blocks(self.clock()), [])
        router = self.router((503, {}, {}), max_transport_retries=0)
        with self.assertRaises(CloudflareTransportError) as raised:
            self.generate(router)
        self.assertEqual((raised.exception.code, raised.exception.attempts), ("SERVER_FAILURE", 1))

    def test_auth_failure_disables_only_slot_and_uses_next_token_for_same_account(self):
        router = self.router((401, {}, {}), self.success, self.success)
        record = self.generate(router)
        self.assertEqual([(a["slot_id"], a["outcome"]) for a in record["transport_attempts"]],
                         [("cloudflare_slot_1", "AUTH_FAILURE"), ("cloudflare_slot_2", "SUCCESS")])
        self.assertEqual(self.generate(router)["slot_id"], "cloudflare_slot_2")
        self.assertEqual(self.store.active_blocks(self.clock()), [])
        self.accounts = cloudflare_settings(CF_ACCOUNT)
        router = self.router((401, {}, {}))
        with self.assertRaises(CloudflareTransportError) as raised:
            self.generate(router)
        self.assertEqual(raised.exception.code, "NO_USABLE_CREDENTIAL")

    def test_terminal_errors_raise_without_retrying_blocking_or_disabling(self):
        for status, body, kind in [
            (403, {"errors": [{"code": 5035}]}, "MODEL_REQUIRES_PAID"),
            (403, {"errors": [{"code": 3023}]}, "ACCOUNT_BLOCKED"),
            (410, {"errors": [{"code": 5028}]}, "MODEL_UNAVAILABLE"),
            (403, {"error": {"message": "denied"}}, "FORBIDDEN"), (403, b"<html>", "EDGE_BLOCKED"),
            (413, {}, "REQUEST_TOO_LARGE"), (400, {}, "REQUEST_FAILURE"), (200, {}, "MALFORMED_RESPONSE"),
        ]:
            with self.subTest(kind=kind):
                router = self.router((status, {}, body), self.success)
                with self.assertRaises(CloudflareTransportError) as raised:
                    self.generate(router)
                self.assertEqual((raised.exception.code, raised.exception.attempts), (kind, 1))
                self.assertEqual(self.generate(router)["slot_id"], "cloudflare_slot_1")
                self.assertEqual(self.store.active_blocks(self.clock()), [])
        self.assertEqual(self.clock.waits, [])

    def test_default_client_writes_estimates_to_quota_file_and_checks_model_before_http(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "quota"
            store = QuotaStateStore(path, clock=self.clock)
            config = inspect_cloudflare_settings(self.accounts)
            fake = FakeCloudflare(CloudflareClient, self.success)
            router = CloudflareRouter(config, store, clock=self.clock)
            with patch("tools.llm_infra.cloudflare_transport._urllib_http", fake.http):
                with self.assertRaisesRegex(GeminiConfigError, "MODEL_NOT_FREE_TIER"):
                    self.generate(router, "test/paid")
                self.assertEqual(fake.http.calls, [])
                self.generate(router)
            self.assertEqual(NeuronLedger(path).used("cloudflare", self.first_scope, utc_day(self.clock())), 2)
            for opts in [{"max_transport_retries": -1}, {"base_backoff_seconds": float("inf")},
                         {"max_inline_wait_seconds": -1}]:
                with self.subTest(opts=opts), self.assertRaises(GeminiConfigError):
                    CloudflareRouter(config, store, **opts)
            secret_path = QuotaStateStore(Path(tmp) / CF_ACCOUNT, clock=self.clock)
            with self.assertRaisesRegex(GeminiConfigError, "credential material"):
                CloudflareRouter(config, secret_path)
