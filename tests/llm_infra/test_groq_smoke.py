from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fixtures import Clock, FakeGroq, GROQ_TEST_KEY, groq_settings
from tools.llm_infra.groq_free_models_v1 import DEFAULT_MODEL_CHAIN
from tools.llm_infra.groq_smoke import main
from tools.llm_infra.groq_transport import GroqHTTPError, GroqResponse
from tools.llm_infra.quota_state import QuotaStateStore


class GroqSmokeTests(unittest.TestCase):
    def test_offline_statuses_summary_and_first_model_blocks_without_a_client(self):
        first, second = DEFAULT_MODEL_CHAIN
        clock = Clock()
        client = FakeGroq()
        with TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            store = QuotaStateStore(state, clock=clock)
            store.block("groq", first, "org", 2000, "TPD", clock())
            store.block("groq", second, "org", 2000, "RPD", clock())
            store.block("gemini", first, "org", 2000, "RPM", clock())
            for settings, status in [
                (groq_settings("", "", ""), "READY_FREE_PLAN"),
                ({}, "WAITING_FOR_USER_CREDENTIALS"),
                (groq_settings("") | {"GROQ_MODEL": "llama-3.1-8b-instant"}, "BLOCKED_MODEL_NOT_FREE_PLAN"),
                (groq_settings("", "") | {"GROQ_ORG_PLAN_2": "PAID_PLAN"}, "CONFIG_ERROR"),
                (groq_settings("") | {"GROQ_ORG_PLAN_1": "PAID_PLAN"}, "CONFIG_ERROR"),
            ]:
                with self.subTest(status=status):
                    capture = StringIO()
                    with redirect_stdout(capture):
                        result = main(["--env-file", str(Path(tmp) / "absent")],
                                      environ=settings | {"LLM_QUOTA_STATE_PATH": str(state)},
                                      client_factory=client.factory, clock=clock)
                    self.assertEqual(result, int(status != "READY_FREE_PLAN"))
                    self.assertEqual(client.factory_calls, [])
                    self.assertEqual(client.calls, [])
                    self.assertNotIn(GROQ_TEST_KEY, capture.getvalue())
                    report = json.loads(capture.getvalue())
                    self.assertEqual((report["mode"], report["status"]), ("offline", status))
                    self.assertEqual(report["plan_notice"], "The app cannot see the Groq plan. Keep the account "
                                     "on Free; do not add a card or upgrade to Developer.")
                    if status == "READY_FREE_PLAN":
                        self.assertEqual((report["keys_configured"], report["key_scopes"]), (3, 1))
                        self.assertEqual(report["model_chain"], [first, second])
                        self.assertEqual(report["blocked"], [
                            {"scope": "org", "until_utc": "1970-01-01T00:33:20Z", "reason": "TPD"},
                        ])
                    elif status == "BLOCKED_MODEL_NOT_FREE_PLAN":
                        self.assertEqual(report["blocked"], [])
                        self.assertEqual(report["model_chain"], ["llama-3.1-8b-instant"])

    def test_one_json_mode_request_and_small_secret_safe_output(self):
        headers = {
            "x-ratelimit-limit-requests": "1000", "x-ratelimit-limit-tokens": "8000",
            "x-ratelimit-remaining-requests": "0", "x-ratelimit-remaining-tokens": "7990",
            "x-ratelimit-reset-requests": "1h", "x-ratelimit-reset-tokens": "2s", "retry-after": "5",
        }
        usage = {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings"
            path.write_text(f"GROQ_API_KEY_1={GROQ_TEST_KEY}\nGROQ_ORG_LABEL_1=smoke-org\n"
                            "GROQ_MODEL=openai/gpt-oss-120b\n", encoding="utf-8")
            state = Path(tmp) / "state"
            for model in (None, "openai/gpt-oss-120b"):
                with self.subTest(model=model):
                    clock = Clock()
                    client = FakeGroq(GroqResponse("private response", usage | {"reasoning_tokens": 1},
                                                    GROQ_TEST_KEY, headers | {"Authorization": GROQ_TEST_KEY},
                                                    response_id="private id", status=201))
                    capture = StringIO()
                    args = ["--env-file", str(path), "--live"] + (["--model", model] if model else [])
                    with redirect_stdout(capture):
                        result = main(args, environ={"LLM_QUOTA_STATE_PATH": str(state),
                                                     "GROQ_API_KEY_2": "test-groq-key-not-real-2"},
                                      client_factory=client.factory, clock=clock)
                    self.assertEqual(result, 0)
                    for private in (GROQ_TEST_KEY, "private response", "private id", "Authorization"):
                        self.assertNotIn(private, capture.getvalue())
                    expected = model or "openai/gpt-oss-20b"
                    self.assertEqual(json.loads(capture.getvalue()), {
                        "mode": "live", "http_status": 201, "model": {"requested": expected, "reported": "[REDACTED]"},
                        "outcome": "SUCCESS", "latency_ms": 0, "usage": usage, "rate_limit": headers, "error_code": None,
                    })
                    self.assertEqual(client.factory_calls, [GROQ_TEST_KEY])
                    self.assertEqual(client.calls, [(GROQ_TEST_KEY, {
                        "model": expected, "system_instruction": "Reply briefly.",
                        "user_content": "Reply with the word OK.",
                        "generation_config": {"temperature": 0, "max_output_tokens": 32},
                    })])
                    self.assertFalse(state.exists())

    def test_failures_return_only_public_metadata(self):
        with TemporaryDirectory() as tmp:
            # Only a short identifier-like Groq error code is shown; anything else is dropped.
            for model, http_status, outcome, code, shown in [
                (GROQ_TEST_KEY, None, "CONFIG_ERROR", None, None),
                ("llama-3.1-8b-instant", None, "BLOCKED_MODEL_NOT_FREE_PLAN", None, None),
                ("openai/gpt-oss-120b,openai/gpt-oss-20b", None, "BLOCKED_MODEL_NOT_FREE_PLAN", None, None),
                (None, 400, "REQUEST_FAILURE", "json_validate_failed", "json_validate_failed"),
                (None, 429, "RATE_LIMIT", "rate_limit_exceeded", "rate_limit_exceeded"),
                (None, 503, "SERVER_FAILURE", f"sensitive message {GROQ_TEST_KEY}", None),
            ]:
                with self.subTest(model=model, outcome=outcome):
                    clock = Clock()
                    state = Path(tmp) / "state"
                    client = FakeGroq(GroqHTTPError(kind=outcome, status=http_status,
                                                    headers={"Retry-After": "5", "Authorization": GROQ_TEST_KEY},
                                                    body={"error": {"message": f"sensitive message {GROQ_TEST_KEY}",
                                                                    "code": code}}))
                    capture = StringIO()
                    args = ["--env-file", str(Path(tmp) / "absent"), "--live"] + (["--model", model] if model else [])
                    with redirect_stdout(capture):
                        result = main(args, environ=groq_settings("", "other-org") | {
                            "LLM_QUOTA_STATE_PATH": str(state),
                        }, client_factory=client.factory, clock=clock)
                    self.assertEqual(result, 1)
                    self.assertEqual(client.factory_calls, [GROQ_TEST_KEY] if http_status else [])
                    self.assertEqual([key for key, _ in client.calls], client.factory_calls)
                    self.assertFalse(state.exists())
                    for private in (GROQ_TEST_KEY, "sensitive message", "Authorization"):
                        self.assertNotIn(private, capture.getvalue())
                    self.assertEqual(json.loads(capture.getvalue()), {
                        "mode": "live", "http_status": http_status, "model": {
                            "requested": "openai/gpt-oss-20b" if http_status else None, "reported": None,
                        },
                        "outcome": outcome, "latency_ms": 0, "usage": {},
                        "rate_limit": {"retry-after": "5"} if http_status else {}, "error_code": shown,
                    })

    def test_default_client_uses_twenty_second_timeout(self):
        with TemporaryDirectory() as tmp, redirect_stdout(StringIO()), patch(
            "tools.llm_infra.groq_transport._urllib_http",
            return_value=(200, {}, b'{"choices":[{"message":{"content":"{}"}}]}'),
        ) as http:
            result = main(["--env-file", str(Path(tmp) / "absent"), "--live"],
                          environ=groq_settings(""), clock=Clock())
        self.assertEqual(result, 0)
        self.assertEqual(http.call_count, 1)
        self.assertEqual(http.call_args.args[-1], 20)
