from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fixtures import (
    Clock, FakeOpenRouter, FakeOpenRouterHTTP, OPENROUTER_KEY_COUNTS, OPENROUTER_MODEL, OPENROUTER_TEST_KEY,
    openrouter_body, openrouter_settings,
)
from tools.llm_infra.openrouter_router import ACCOUNT_WIDE_MODEL
from tools.llm_infra.openrouter_smoke import main
from tools.llm_infra.openrouter_transport import OpenRouterHTTPError, OpenRouterResponse
from tools.llm_infra.quota_state import QuotaStateStore


class OpenRouterSmokeTests(unittest.TestCase):
    def setUp(self):
        folder = Path(self.enterContext(TemporaryDirectory()))
        self.state = folder / "state"
        self.args = ["--env-file", str(folder / "absent")]
        self.clock = Clock()

    def run_smoke(self, args, environ, factory=None):
        capture = StringIO()
        with redirect_stdout(capture):
            result = main(self.args + args, environ=environ | {"LLM_QUOTA_STATE_PATH": str(self.state)},
                          client_factory=factory, clock=self.clock)
        self.assertNotIn(OPENROUTER_TEST_KEY, capture.getvalue())
        return result, json.loads(capture.getvalue())

    def test_offline_status_summary_and_openrouter_blocks_without_client(self):
        store = QuotaStateStore(self.state, clock=self.clock)
        store.block("openrouter", ACCOUNT_WIDE_MODEL, OPENROUTER_TEST_KEY, 2000, "RPD", self.clock())
        store.block("groq", OPENROUTER_MODEL, "org", 2000, "RPM", self.clock())
        for environ, status in [
            ({}, "WAITING_FOR_USER_CREDENTIALS"),
            (openrouter_settings(""), "READY_FREE_ONLY"),
            (openrouter_settings("") | {"OPENROUTER_MODEL": "test/paid"}, "BLOCKED_MODEL_NOT_FREE_TIER"),
            (openrouter_settings("") | {"OPENROUTER_ACCOUNT_LABEL_1": OPENROUTER_TEST_KEY}, "CONFIG_ERROR"),
        ]:
            with self.subTest(status=status):
                client = FakeOpenRouter()
                result, report = self.run_smoke([], environ, client.factory)
                self.assertEqual((report["mode"], report["status"], result),
                                 ("offline", status, int(status != "READY_FREE_ONLY")))
                self.assertEqual(client.factory_calls, [])
                if status == "READY_FREE_ONLY":
                    self.assertEqual(report["model_chain"], ["openrouter/free"])
                    self.assertEqual(report["keys_configured"], 1)
                    self.assertEqual(report["blocked"], [{"scope": "[REDACTED]", "reason": "RPD",
                                                         "until_utc": "1970-01-01T00:33:20Z"}])

    def test_live_calls_key_then_chat_once_with_first_key_and_selected_model(self):
        for explicit in (False, True):
            with self.subTest(explicit=explicit):
                model = OPENROUTER_MODEL if explicit else "openrouter/free"
                args = ["--live", "--model", model] if explicit else ["--live"]
                response = OpenRouterResponse("private content", {}, f"test/{OPENROUTER_TEST_KEY}:free", {},
                                              response_id="private id", cost=0)
                client = FakeOpenRouter(response, key_info=OPENROUTER_KEY_COUNTS | {"label": "private label"})
                config = openrouter_settings("first-account", "") | {
                    "OPENROUTER_MODEL": f"openrouter/free,{OPENROUTER_MODEL}",
                }
                result, report = self.run_smoke(args, config, client.factory)
                self.assertEqual(result, 0)
                self.assertEqual(report, {
                    "mode": "live", "outcome": "SUCCESS", "slot_id": "openrouter_slot_1", "scope": "first-account",
                    "model": {"requested": model, "reported": "test/[REDACTED]:free"}, "key_outcome": "SUCCESS",
                    "key_info": OPENROUTER_KEY_COUNTS, "http_status": 200, "latency_ms": 0, "cost": 0,
                })
                self.assertEqual(client.factory_calls, [OPENROUTER_TEST_KEY])
                self.assertEqual(client.calls, [
                    ("key", OPENROUTER_TEST_KEY, None), ("generate", OPENROUTER_TEST_KEY, {
                        "model": model, "system_instruction": "Reply with JSON only.",
                        "user_content": 'Return {"status":"ok"}',
                        "generation_config": {"temperature": 0, "max_output_tokens": 32,
                                              "response_mime_type": "application/json"},
                    }),
                ])
                self.assertFalse(self.state.exists())

    def test_live_failures_report_public_metadata_without_retry(self):
        key_failure = OpenRouterHTTPError(kind="RATE_LIMIT", status=429)
        chat_failure = OpenRouterHTTPError(kind="PAYMENT_REQUIRED", status=402, body={"private": OPENROUTER_TEST_KEY})
        paid = OpenRouterHTTPError(kind="PAID_USAGE_DETECTED", status=200,
                                   body={"model": "test/paid", "usage": {"cost": 0.01, "private": OPENROUTER_TEST_KEY}})
        for key_info, actions, key_outcome, outcome, status, model, cost in [
            (key_failure, (), "RATE_LIMIT", "SUCCESS", 200, OPENROUTER_MODEL, 0),
            (None, (chat_failure,), "SUCCESS", "PAYMENT_REQUIRED", 402, None, None),
            (None, (paid,), "SUCCESS", "PAID_USAGE_DETECTED", 200, "test/paid", 0.01),
        ]:
            with self.subTest(outcome=outcome, key_outcome=key_outcome):
                client = FakeOpenRouter(*actions, key_info=key_info)
                result, report = self.run_smoke(["--live"], openrouter_settings("", "other"), client.factory)
                self.assertEqual(result, 1)
                self.assertEqual((report["key_outcome"], report["outcome"], report["http_status"]),
                                 (key_outcome, outcome, status))
                self.assertEqual((report["model"]["reported"], report["cost"]), (model, cost))
                self.assertEqual(report["key_info"], {} if key_info else OPENROUTER_KEY_COUNTS)
                self.assertEqual([operation for operation, *_ in client.calls], ["key", "generate"])
                self.assertFalse(self.state.exists())

    def test_live_blocks_invalid_config_and_model_before_any_call(self):
        for config, args, expected in [
            ({}, [], "CONFIG_ERROR"),
            (openrouter_settings(""), ["--model", "test/paid"], "BLOCKED_MODEL_NOT_FREE_TIER"),
            (openrouter_settings(""), ["--model", f"{OPENROUTER_MODEL},openrouter/free"],
             "BLOCKED_MODEL_NOT_FREE_TIER"),
            (openrouter_settings(""), ["--model", OPENROUTER_TEST_KEY], "CONFIG_ERROR"),
            (openrouter_settings("") | {"OPENROUTER_MODEL": "openrouter/free,test/paid"}, [],
             "BLOCKED_MODEL_NOT_FREE_TIER"),
        ]:
            with self.subTest(outcome=expected, override=bool(args)):
                client = FakeOpenRouter()
                result, report = self.run_smoke(["--live"] + args, config, client.factory)
                self.assertEqual((result, report["outcome"]), (1, expected))
                self.assertEqual(client.factory_calls, [])

    def test_default_client_uses_twenty_second_timeout_and_configured_privacy(self):
        http = FakeOpenRouterHTTP((200, {}, {"data": OPENROUTER_KEY_COUNTS}), (200, {}, openrouter_body()))
        with patch("tools.llm_infra.openrouter_transport._urllib_http", http):
            result, _ = self.run_smoke(["--live"], openrouter_settings("") | {"OPENROUTER_DATA_COLLECTION": "deny"})
        self.assertEqual(result, 0)
        self.assertEqual([call[-1] for call in http.calls], [20, 20])
        self.assertIsNone(http.calls[0][2])
        self.assertEqual(http.calls[1][2]["provider"], {"data_collection": "deny"})

    def test_default_client_reports_invalid_key_without_http(self):
        with patch("tools.llm_infra.openrouter_transport._urllib_http", FakeOpenRouterHTTP()):
            result, report = self.run_smoke(["--live"], {"OPENROUTER_API_KEY_1": "test-openrouter\nkey"})
        self.assertEqual((result, report["outcome"]), (1, "AUTH_FAILURE"))
