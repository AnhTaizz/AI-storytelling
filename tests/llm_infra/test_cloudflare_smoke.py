from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fixtures import CF_ACCOUNT, CF_MODEL, CF_TOKEN, Clock, FakeCloudflare, cloudflare_body, cloudflare_settings
from tools.llm_infra.cloudflare_free_models_v1 import DEFAULT_MODEL_CHAIN
from tools.llm_infra.cloudflare_smoke import main
from tools.llm_infra.cloudflare_transport import CloudflareClient
from tools.llm_infra.neuron_ledger import NeuronLedger, utc_day
from tools.llm_infra.quota_state import QuotaStateStore


class CloudflareSmokeTests(unittest.TestCase):
    def setUp(self):
        directory = Path(self.enterContext(TemporaryDirectory()))
        self.state = directory / "state"
        self.args = ["--env-file", str(directory / "absent")]
        self.clock = Clock()
        self.settings = cloudflare_settings(CF_ACCOUNT)
        self.scope = "cloudflare_account_1"
        self.ledger = NeuronLedger(self.state)

    def run_smoke(self, args, values, factory=None):
        capture = StringIO()
        with redirect_stdout(capture):
            result = main(self.args + args, environ=values | {"LLM_QUOTA_STATE_PATH": str(self.state)},
                          client_factory=factory, clock=self.clock)
        output = capture.getvalue()
        for secret in (CF_TOKEN, CF_ACCOUNT):
            self.assertNotIn(secret, output)
        return result, json.loads(output)

    def test_offline_reports_status_and_state_without_a_client(self):
        self.ledger.add("cloudflare", self.scope, utc_day(self.clock()), 22, self.clock())
        store = QuotaStateStore(self.state, clock=self.clock)
        store.block("cloudflare", "*", self.scope, 2000, "RPD", self.clock())
        store.block("openrouter", "*", "openrouter_account", 2000, "RPM", self.clock())
        for environ, status in [
            ({}, "WAITING_FOR_USER_CREDENTIALS"),
            (self.settings, "READY_FREE_ONLY"),
            (self.settings | {"CLOUDFLARE_MODEL": "test/paid"}, "BLOCKED_MODEL_NOT_FREE_TIER"),
            (self.settings | {"CLOUDFLARE_PLAN_1": "WORKERS_PAID"}, "BLOCKED_NO_ELIGIBLE_KEY"),
            ({"CLOUDFLARE_API_TOKEN_1": CF_TOKEN}, "CONFIG_ERROR"),
        ]:
            with self.subTest(status=status):
                fake = FakeCloudflare(CloudflareClient)
                result, report = self.run_smoke([], environ, fake.factory)
                self.assertEqual((result, report["mode"], report["status"]),
                                 (int(status != "READY_FREE_ONLY"), "offline", status))
                self.assertEqual(fake.factory_calls, [])
                if status == "READY_FREE_ONLY":
                    self.assertEqual(report["model_chain"], list(DEFAULT_MODEL_CHAIN))
                    self.assertEqual(report["blocked"], [{"model": "*", "scope": self.scope, "reason": "RPD",
                                                          "until_utc": "1970-01-01T00:33:20Z"}])
                    self.assertEqual(report["neurons_used_today"], {self.scope: 22})

    def test_live_sends_one_prompt_and_records_reported_or_estimated_usage(self):
        for args, expected_model, body, expected in [
            ([], CF_MODEL, cloudflare_body(), (30, 10, 2, True)),
            (["--model", DEFAULT_MODEL_CHAIN[1]], DEFAULT_MODEL_CHAIN[1],
             {"result": {"response": f"/accounts/{CF_ACCOUNT}/{CF_TOKEN}"}}, (None, None, 1, False)),
        ]:
            with self.subTest(model=expected_model):
                fake = FakeCloudflare(CloudflareClient, (200, {}, body))
                result, report = self.run_smoke(["--live", *args], self.settings, fake.factory)
                self.assertEqual((result, report["outcome"], report["http_status"], report["latency_ms"]),
                                 (0, "SUCCESS", 200, 0))
                self.assertEqual((report["slot_id"], report["scope"], report["model"]),
                                 ("cloudflare_slot_1", self.scope, expected_model))
                self.assertEqual((report["prompt_tokens"], report["completion_tokens"],
                                  report["neurons_estimated"], report["parsed_json"]), expected)
                self.assertEqual(fake.factory_calls, [(CF_ACCOUNT, CF_TOKEN)])
                self.assertEqual(len(fake.http.calls), 1)
                payload = fake.http.calls[0][2]
                self.assertEqual(payload["messages"][-1]["content"], 'Return {"status":"ok"}')
                self.assertEqual(payload["max_tokens"], 512)
                self.assertNotIn("response_format", payload)
        self.assertEqual(self.ledger.used("cloudflare", self.scope, utc_day(self.clock())), 3)

    def test_live_failed_request_does_not_retry_or_add_neurons(self):
        body = {"errors": [{"code": 3040, "message": f"/accounts/{CF_ACCOUNT}/{CF_TOKEN}"}]}
        fake = FakeCloudflare(CloudflareClient, (429, {}, body))
        result, report = self.run_smoke(["--live"], self.settings, fake.factory)
        self.assertEqual((result, report["outcome"], report["http_status"]), (1, "SERVER_FAILURE", 429))
        self.assertEqual(len(fake.http.calls), 1)
        self.assertFalse(self.state.exists())

    def test_live_respects_daily_budget_and_existing_blocks(self):
        values = self.settings | {"CLOUDFLARE_DAILY_NEURON_BUDGET": "2"}
        fake = FakeCloudflare(CloudflareClient, (200, {}, cloudflare_body()))
        result, _ = self.run_smoke(["--live"], values, fake.factory)
        self.assertEqual(result, 0)
        for config in (values, self.settings):
            with self.subTest(budget=config.get("CLOUDFLARE_DAILY_NEURON_BUDGET")):
                result, report = self.run_smoke(["--live"], config, fake.factory)
                self.assertEqual((result, report["outcome"]), (1, "QUOTA_EXHAUSTED"))
                self.assertEqual(len(fake.http.calls), 1)
        self.assertEqual(QuotaStateStore(self.state, clock=self.clock).active_blocks(self.clock())[0]["reason"], "RPD")

    def test_live_rejects_invalid_configuration_and_model_before_network(self):
        for config, args, status in [
            ({}, [], "CONFIG_ERROR"),
            (self.settings | {"CLOUDFLARE_PLAN_1": "WORKERS_PAID"}, [], "CONFIG_ERROR"),
            (self.settings, ["--model", "test/paid"], "BLOCKED_MODEL_NOT_FREE_TIER"),
            (self.settings, ["--model", ",".join(DEFAULT_MODEL_CHAIN)], "BLOCKED_MODEL_NOT_FREE_TIER"),
        ]:
            with self.subTest(args=args, status=status):
                fake = FakeCloudflare(CloudflareClient)
                result, report = self.run_smoke(["--live", *args], config, fake.factory)
                self.assertEqual((result, report["outcome"]), (1, status))
                self.assertEqual(fake.factory_calls, [])

    def test_live_default_transport_has_short_timeout(self):
        fake = FakeCloudflare(CloudflareClient, (200, {}, cloudflare_body()))
        with patch("tools.llm_infra.cloudflare_transport._urllib_http", fake.http):
            result, _ = self.run_smoke(["--live"], self.settings)
        self.assertEqual(result, 0)
        self.assertEqual(fake.http.calls[0][-1], 20)
