from io import BytesIO
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from fixtures import GROQ_TEST_KEY
from tools.llm_infra.groq_transport import GroqClient, GroqHTTPError


class GroqTransportTests(unittest.TestCase):
    def test_http_and_generation_parameters(self):
        calls = []

        def http(url, headers, body, timeout):
            calls.append((url, headers, json.loads(body), timeout))
            return 200, {"X-RateLimit-Remaining-Requests": "100"}, json.dumps({
                "choices": [{"message": {"content": '{"status":"ok"}'}}],
                "usage": {"total_tokens": 15}, "model": "test-model", "id": "provider-id",
            }).encode()

        client = GroqClient(GROQ_TEST_KEY, http=http, timeout=12)
        for config, fields in [
            ({}, {}),
            ({"temperature": 0.1, "max_output_tokens": 10, "response_mime_type": "application/json",
              "top_p": 0.8}, {"temperature": 0.1, "max_tokens": 10, "response_format": {"type": "json_object"}}),
            ({"response_mime_type": "text/plain"}, {}),
        ]:
            with self.subTest(config=config):
                result = client.generate("test-model", "system", "user", config)
                url, headers, body, timeout = calls[-1]
                self.assertEqual(url, "https://api.groq.com/openai/v1/chat/completions")
                self.assertEqual(headers, {"Authorization": f"Bearer {GROQ_TEST_KEY}",
                                           "Content-Type": "application/json",
                                           "User-Agent": "llm-infra-client/1.0"})
                self.assertEqual(timeout, 12)
                self.assertEqual(body, {"model": "test-model", "messages": [
                    {"role": "system", "content": "system"}, {"role": "user", "content": "user"},
                ]} | fields)
                self.assertEqual((result.text, result.usage, result.model, result.response_id),
                                 ('{"status":"ok"}', {"total_tokens": 15}, "test-model", "provider-id"))
                self.assertEqual(result.headers, {"x-ratelimit-remaining-requests": "100"})
        self.assertNotIn(GROQ_TEST_KEY, repr(client))

    def test_error_status_and_error_code_mapping(self):
        for status, code, prefix, kind in [
            (429, "rate_limit_exceeded", "echo", "RATE_LIMIT"),
            (429, "rate_limit_exceeded", "Rate limit on tokens per minute", "RATE_LIMIT"),
            (413, None, "echo", "REQUEST_TOO_LARGE"),
            (429, "rate_limit_exceeded", "Request too large", "REQUEST_TOO_LARGE"),
            (400, "invalid_request_error", "REQUEST TOO LARGE", "REQUEST_TOO_LARGE"),
            *((n, None, "echo", "AUTH_FAILURE") for n in (401, 403)),
            *((n, None, "echo", "SERVER_FAILURE") for n in (498, 500, 502, 503, 504)),
            (404, None, "echo", "MODEL_UNAVAILABLE"), (400, "model_not_found", "echo", "MODEL_UNAVAILABLE"),
            (400, "model_decommissioned", "echo", "MODEL_UNAVAILABLE"),
            (400, "invalid_request_error", "echo", "REQUEST_FAILURE"), (422, None, "echo", "REQUEST_FAILURE"),
            (302, None, "echo", "REQUEST_FAILURE"),
        ]:
            with self.subTest(status=status, code=code, message=prefix):
                payload = {"error": {"code": code, "message": f"{prefix} {GROQ_TEST_KEY}", GROQ_TEST_KEY: GROQ_TEST_KEY}}
                client = GroqClient(GROQ_TEST_KEY, http=lambda *_: (
                    status, {"X-Echo": GROQ_TEST_KEY, "Retry-After": "5"}, json.dumps(payload).encode()))
                with self.assertRaises(GroqHTTPError) as caught:
                    client.generate("test-model", "system", "user", {})
                error = caught.exception
                self.assertEqual((error.status, error.kind), (status, kind))
                self.assertEqual(error.headers, {"x-echo": "[REDACTED]", "retry-after": "5"})
                self.assertEqual(error.body["error"]["message"], f"{prefix} [REDACTED]")
                self.assertNotIn(prefix, str(error))
                for exposed in (str(error), repr(error), repr(error.body), repr(error.headers)):
                    self.assertNotIn(GROQ_TEST_KEY, exposed)

    def test_unparseable_body_and_missing_content(self):
        for status, payload, kind in [
            (503, b"<html>unavailable</html>", "SERVER_FAILURE"),
            (403, b"error code: 1010", "EDGE_BLOCKED"),
            (200, b"\xff", "MALFORMED_RESPONSE"), (200, b"null", "MALFORMED_RESPONSE"),
            (200, b'{"choices":[]}', "MALFORMED_RESPONSE"),
            (200, b'{"choices":[{"message":{"content":null}}]}', "MALFORMED_RESPONSE"),
        ]:
            with self.subTest(status=status, payload=payload):
                client = GroqClient(GROQ_TEST_KEY, http=lambda *_: (status, {}, payload))
                with self.assertRaises(GroqHTTPError) as caught:
                    client.generate("test-model", "system", "user", {})
                self.assertEqual((caught.exception.status, caught.exception.kind), (status, kind))
                if payload[:1] != b"{":
                    self.assertEqual(caught.exception.body, {})

    def test_success_does_not_echo_key_in_content_or_metadata(self):
        data = {"model": GROQ_TEST_KEY, "id": GROQ_TEST_KEY, "usage": {GROQ_TEST_KEY: [GROQ_TEST_KEY]},
                "choices": [{"message": {"content": GROQ_TEST_KEY}}]}
        client = GroqClient(GROQ_TEST_KEY, http=lambda *_: (
            200, {"X-Echo": GROQ_TEST_KEY}, json.dumps(data).encode()))
        result = client.generate("test-model", "system", "user", {})
        self.assertEqual(result.text, "[REDACTED]")
        self.assertNotIn(GROQ_TEST_KEY, repr(result))

    def test_network_failures_hide_the_underlying_exception(self):
        for error_type in (URLError, TimeoutError, ConnectionError):
            with self.subTest(error_type=error_type):
                def http(*_):
                    raise error_type(GROQ_TEST_KEY)

                client = GroqClient(GROQ_TEST_KEY, http=http)
                with self.assertRaises(GroqHTTPError) as caught:
                    client.generate("test-model", "system", "user", {})
                self.assertEqual(caught.exception.kind, "TRANSPORT_FAILURE")
                self.assertIsNone(caught.exception.status)
                self.assertIsNone(caught.exception.__context__)
                self.assertNotIn(GROQ_TEST_KEY, repr(caught.exception))

    def test_default_http_converts_urllib_http_error(self):
        def open_request(request, timeout):
            self.assertEqual(request.get_method(), "POST")
            self.assertEqual(timeout, 120)
            raise HTTPError(request.full_url, 429, GROQ_TEST_KEY, {"Retry-After": "5"},
                            BytesIO(b'{"error":{"code":"rate_limit_exceeded"}}'))

        with patch("tools.llm_infra.groq_transport.build_opener", return_value=SimpleNamespace(open=open_request)):
            with self.assertRaises(GroqHTTPError) as caught:
                GroqClient(GROQ_TEST_KEY).generate("test-model", "system", "user", {})
        error = caught.exception
        self.assertEqual((error.kind, error.status, error.headers), ("RATE_LIMIT", 429, {"retry-after": "5"}))
        self.assertEqual(error.body, {"error": {"code": "rate_limit_exceeded"}})
        self.assertNotIn(GROQ_TEST_KEY, str(error))
