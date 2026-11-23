from io import BytesIO
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from fixtures import (
    FakeOpenRouterHTTP, OPENROUTER_KEY_COUNTS, OPENROUTER_MODEL, OPENROUTER_TEST_KEY, openrouter_body,
)
from tools.llm_infra.openrouter_transport import USER_AGENT, OpenRouterClient, OpenRouterHTTPError


class OpenRouterTransportTests(unittest.TestCase):
    def test_chat_uses_one_free_model_and_only_expected_headers_and_fields(self):
        for privacy, config, extras in [
            (None, {"response_mime_type": "text/plain", "models": ["test/paid"]}, {}),
            ("allow", {}, {"provider": {"data_collection": "allow"}}),
            ("deny", {"temperature": 0, "max_output_tokens": 32, "response_mime_type": "application/json"}, {
                "temperature": 0, "max_tokens": 32, "response_format": {"type": "json_object"},
                "provider": {"data_collection": "deny"},
            }),
        ]:
            with self.subTest(privacy=privacy):
                http = FakeOpenRouterHTTP((200, {"X-Echo": OPENROUTER_TEST_KEY}, openrouter_body(
                    usage={"total_tokens": 14, "cost": 0, OPENROUTER_TEST_KEY: [OPENROUTER_TEST_KEY]},
                    id=OPENROUTER_TEST_KEY, choices=[{"message": {"content": OPENROUTER_TEST_KEY}}],
                )))
                client = OpenRouterClient(OPENROUTER_TEST_KEY, http=http, timeout=12, data_collection=privacy)
                response = client.generate("openrouter/free", "system", "user", config)
                self.assertEqual(http.calls, [(
                    "https://openrouter.ai/api/v1/chat/completions",
                    {"Authorization": f"Bearer {OPENROUTER_TEST_KEY}", "User-Agent": USER_AGENT, "Content-Type": "application/json"},
                    {"model": "openrouter/free", "usage": {"include": True}, "messages": [
                        {"role": "system", "content": "system"}, {"role": "user", "content": "user"},
                    ]} | extras, 12,
                )])
                self.assertEqual((response.model, response.cost, response.text, response.response_id),
                                 (OPENROUTER_MODEL, 0, "[REDACTED]", "[REDACTED]"))
                self.assertEqual(response.headers, {"x-echo": "[REDACTED]"})
                self.assertEqual(response.usage, {"total_tokens": 14, "cost": 0, "[REDACTED]": ["[REDACTED]"]})
                for value in (response, client):
                    self.assertNotIn(OPENROUTER_TEST_KEY, repr(value))

    def test_paid_and_ambiguous_request_models_never_reach_http(self):
        http = FakeOpenRouterHTTP()
        client = OpenRouterClient(OPENROUTER_TEST_KEY, http=http)
        for model in ("test/model", f"{OPENROUTER_MODEL},test/paid", "test/model:free:paid",
                      f"test/{OPENROUTER_TEST_KEY}:free"):
            with self.subTest(valid_free_suffix=model.endswith(":free")):
                with self.assertRaises(OpenRouterHTTPError) as caught:
                    client.generate(model, "system", "user", {})
                self.assertEqual(caught.exception.kind, "MODEL_NOT_FREE")
                self.assertNotIn(OPENROUTER_TEST_KEY, repr(caught.exception))
        self.assertEqual(http.calls, [])

    def test_detects_paid_cost_or_paid_reported_model(self):
        for status, fields in [
            (200, {"usage": {"cost": 0.000001}}), (200, {"model": "test/paid", "usage": {"cost": 0}}),
            (200, {"usage": {"cost": 1}, "error": {"code": 429}}), (200, {"model": OPENROUTER_TEST_KEY}),
            (503, {"usage": {"cost": 1}, "error": {"code": 503}}),
        ]:
            with self.subTest(status=status, fields=tuple(fields)):
                http = FakeOpenRouterHTTP((status, {}, openrouter_body(**fields)))
                with self.assertRaises(OpenRouterHTTPError) as caught:
                    OpenRouterClient(OPENROUTER_TEST_KEY, http=http).generate("openrouter/free", "", "", {})
                error = caught.exception
                self.assertEqual((error.kind, error.status), ("PAID_USAGE_DETECTED", status))
                self.assertEqual(len(http.calls), 1)
                self.assertNotIn(OPENROUTER_TEST_KEY, repr(error.body))

    def test_missing_cost_and_free_router_self_report(self):
        http = FakeOpenRouterHTTP((200, {}, openrouter_body(model="openrouter/free", usage=None, id=None)))
        response = OpenRouterClient(OPENROUTER_TEST_KEY, http=http).generate("openrouter/free", "", "", {})
        self.assertEqual((response.model, response.cost, response.usage, response.response_id),
                         ("openrouter/free", None, {}, None))

    def test_http_and_embedded_error_codes_have_the_same_kind(self):
        for code, kind in [
            (400, "REQUEST_FAILURE"), (401, "AUTH_FAILURE"), (402, "PAYMENT_REQUIRED"), (403, "FORBIDDEN"),
            (404, "MODEL_UNAVAILABLE"), (408, "TRANSPORT_FAILURE"), (413, "REQUEST_TOO_LARGE"),
            (422, "REQUEST_FAILURE"), (429, "RATE_LIMIT"), (500, "SERVER_FAILURE"), (502, "SERVER_FAILURE"),
            (503, "SERVER_FAILURE"), (504, "SERVER_FAILURE"),
        ]:
            for status in (code, 200):
                with self.subTest(status=status, code=code):
                    http = FakeOpenRouterHTTP((status, {"X-Echo": OPENROUTER_TEST_KEY}, {
                        "error": {"code": code, "message": OPENROUTER_TEST_KEY,
                                  "metadata": {"provider_code": 429}},
                    }))
                    with self.assertRaises(OpenRouterHTTPError) as caught:
                        OpenRouterClient(OPENROUTER_TEST_KEY, http=http).generate(OPENROUTER_MODEL, "", "", {})
                    error = caught.exception
                    self.assertEqual((error.kind, error.status), (kind, status))
                    self.assertEqual(error.body["error"]["message"], "[REDACTED]")
                    self.assertEqual(error.headers, {"x-echo": "[REDACTED]"})
                    self.assertNotIn(OPENROUTER_TEST_KEY, repr(error))
        for body in (b"error code: 1010", {"message": "blocked"}):
            with self.subTest(edge_body=body):
                http = FakeOpenRouterHTTP((403, {"Server": "cloudflare"}, body))
                with self.assertRaises(OpenRouterHTTPError) as caught:
                    OpenRouterClient(OPENROUTER_TEST_KEY, http=http).generate(OPENROUTER_MODEL, "", "", {})
                self.assertEqual((caught.exception.kind, caught.exception.status), ("EDGE_BLOCKED", 403))

    def test_malformed_success_is_rejected(self):
        for body in (b"\xff", [], openrouter_body(choices=[]), openrouter_body(model=None),
                     {"error": {"code": "bad"}}, {"error": "bad"}):
            with self.subTest(body=body):
                http = FakeOpenRouterHTTP((200, {}, body))
                with self.assertRaises(OpenRouterHTTPError) as caught:
                    OpenRouterClient(OPENROUTER_TEST_KEY, http=http).generate(OPENROUTER_MODEL, "", "", {})
                self.assertEqual(caught.exception.kind, "MALFORMED_RESPONSE")

    def test_key_info_only_returns_public_typed_counts(self):
        full = OPENROUTER_KEY_COUNTS | {"label": OPENROUTER_TEST_KEY, "usage": 11, "key": OPENROUTER_TEST_KEY}
        for data, expected in [
            (full, OPENROUTER_KEY_COUNTS),
            ({"limit": None, "limit_remaining": True, "usage_daily": float("inf"), "is_free_tier": "true",
              "free_model_daily_requests": {"used": "1", "limit": 50, "remaining": 49, "private": 1}},
             {"free_model_daily_requests": {"limit": 50, "remaining": 49}}),
        ]:
            with self.subTest(expected=expected):
                http = FakeOpenRouterHTTP((200, {}, {"data": data}))
                self.assertEqual(OpenRouterClient(OPENROUTER_TEST_KEY, http=http).key_info(), expected)
                self.assertEqual(http.calls, [("https://openrouter.ai/api/v1/key",
                                              {"Authorization": f"Bearer {OPENROUTER_TEST_KEY}", "User-Agent": USER_AGENT}, None, 120)])
        http = FakeOpenRouterHTTP((200, {}, {"data": []}))
        with self.assertRaisesRegex(OpenRouterHTTPError, "MALFORMED_RESPONSE"):
            OpenRouterClient(OPENROUTER_TEST_KEY, http=http).key_info()

    def test_network_failure_hides_original_exception(self):
        for error_type in (URLError, TimeoutError, ConnectionError):
            with self.subTest(error_type=error_type):
                def http(*_):
                    raise error_type(OPENROUTER_TEST_KEY)

                with self.assertRaises(OpenRouterHTTPError) as caught:
                    OpenRouterClient(OPENROUTER_TEST_KEY, http=http).key_info()
                self.assertEqual(caught.exception.kind, "TRANSPORT_FAILURE")
                self.assertIsNone(caught.exception.__context__)
                self.assertNotIn(OPENROUTER_TEST_KEY, repr(caught.exception))

    def test_default_urllib_adapter_sends_get_and_post_without_redirects(self):
        for method, path in (("GET", "/key"), ("POST", "/chat/completions")):
            with self.subTest(method=method):
                def open_request(request, timeout):
                    self.assertEqual(request.get_method(), method)
                    self.assertEqual(request.full_url, "https://openrouter.ai/api/v1" + path)
                    self.assertEqual(timeout, 120)
                    raise HTTPError(request.full_url, 429, OPENROUTER_TEST_KEY, {"Retry-After": "5"},
                                    BytesIO(b'{"error":{"code":429}}'))

                with patch("tools.llm_infra.openrouter_transport.build_opener",
                           return_value=SimpleNamespace(open=open_request)) as opener:
                    client = OpenRouterClient(OPENROUTER_TEST_KEY)
                    with self.assertRaises(OpenRouterHTTPError) as caught:
                        if method == "GET":
                            client.key_info()
                        else:
                            client.generate(OPENROUTER_MODEL, "", "", {})
                    redirect_handler = opener.call_args.args[0]
                    self.assertIsNone(redirect_handler.redirect_request(None, None, 302, "", {}, "https://elsewhere"))
                self.assertEqual((caught.exception.kind, caught.exception.headers), ("RATE_LIMIT", {"retry-after": "5"}))
                self.assertNotIn(OPENROUTER_TEST_KEY, str(caught.exception))

    def test_invalid_client_arguments_are_rejected_before_http(self):
        for key, privacy, kind in [("", None, "AUTH_FAILURE"), ("tést-key", None, "AUTH_FAILURE"),
                                   ("test\rkey", None, "AUTH_FAILURE"),
                                   (OPENROUTER_TEST_KEY, "unknown", "REQUEST_FAILURE")]:
            with self.subTest(kind=kind, privacy=privacy, key_length=len(key)):
                with self.assertRaisesRegex(OpenRouterHTTPError, kind):
                    OpenRouterClient(key, data_collection=privacy, http=FakeOpenRouterHTTP())
