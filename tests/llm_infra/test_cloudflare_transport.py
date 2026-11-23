from functools import partial
from http.client import HTTPException
import traceback
import unittest
from urllib.parse import quote

from fixtures import CF_ACCOUNT, CF_MODEL, CF_TOKEN, FakeOpenRouterHTTP, cloudflare_body
from tools.llm_infra.cloudflare_transport import CloudflareClient, CloudflareHTTPError


class CloudflareTransportTests(unittest.TestCase):
    def client(self, http, account=CF_ACCOUNT, token=CF_TOKEN):
        return CloudflareClient(account, token, http=http)

    def generate(self, client, model=CF_MODEL, config=None):
        return client.generate(model, "Reply with JSON", "Test message", config or {})

    def test_openai_request_and_response(self):
        http = FakeOpenRouterHTTP((200, {"X-Test": "header"}, cloudflare_body()))
        response = self.generate(self.client(http), config={
            "temperature": 0.25, "max_output_tokens": 512, "response_mime_type": "application/json",
        })
        self.assertEqual(http.calls, [
            (f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT}/ai/v1/chat/completions",
             {"Authorization": f"Bearer {CF_TOKEN}", "User-Agent": "llm-infra-client/1.0",
              "Content-Type": "application/json"},
             {"model": CF_MODEL, "messages": [{"role": "system", "content": "Reply with JSON"},
                                              {"role": "user", "content": "Test message"}],
              "temperature": 0.25, "max_tokens": 512}, 120),
        ])
        self.assertEqual((response.text, response.model, response.status, response.response_id),
                         ('{"status":"ok"}', CF_MODEL, 200, "completion-id"))
        self.assertEqual(response.headers, {"x-test": "header"})
        self.assertEqual((response.prompt_tokens, response.completion_tokens), (30, 10))

    def test_native_wrappers_and_optional_fields(self):
        for result, counts, text in [
            (cloudflare_body(), (30, 10), '{"status":"ok"}'),
            ({"response": "native", "usage": {"prompt_tokens": True, "completion_tokens": -1}},
             (None, None), "native"),
            ({"response": "", "usage": ["bad"], "model": 42, "id": []}, (None, None), ""),
            ({"response": "zero", "usage": {"prompt_tokens": 0}}, (0, None), "zero"),
        ]:
            with self.subTest(result=result):
                response = self.generate(self.client(FakeOpenRouterHTTP((200, {}, {"success": True, "result": result}))))
                self.assertEqual((response.prompt_tokens, response.completion_tokens), counts)
                self.assertEqual((response.text, response.model), (text, CF_MODEL))

    def test_internal_codes_override_status_in_both_error_envelopes(self):
        for code, status, kind in [
            (3036, 429, "DAILY_ALLOCATION_EXHAUSTED"), (3040, 429, "SERVER_FAILURE"),
            (5035, 403, "MODEL_REQUIRES_PAID"), (5007, 400, "MODEL_UNAVAILABLE"),
            (3042, 404, "MODEL_UNAVAILABLE"), (5028, 410, "MODEL_UNAVAILABLE"),
            (3023, 403, "ACCOUNT_BLOCKED"), (3006, 413, "REQUEST_TOO_LARGE"),
            (3007, 408, "TRANSPORT_FAILURE"), (3008, 408, "TRANSPORT_FAILURE"),
            (3003, 429, "REQUEST_FAILURE"), (10000, 403, "AUTH_FAILURE"),
            (3036, 200, "DAILY_ALLOCATION_EXHAUSTED"),
        ]:
            error = {"code": code, "message": "test error"}
            for body in [{"success": False, "errors": [None, {"code": 1}, error]}, {"error": error}]:
                with self.subTest(code=code, status=status, native="errors" in body):
                    client = self.client(FakeOpenRouterHTTP((status, {}, body)))
                    with self.assertRaises(CloudflareHTTPError) as raised:
                        self.generate(client)
                    self.assertEqual((raised.exception.kind, raised.exception.status), (kind, status))

    def test_http_fallbacks_and_malformed_response(self):
        for status, body, kind in [
            (401, {}, "AUTH_FAILURE"), (403, b"<html>edge", "EDGE_BLOCKED"),
            (403, {"error": {"message": "denied"}}, "FORBIDDEN"),
            (403, {"success": False, "errors": []}, "FORBIDDEN"),
            (429, {"errors": [{"code": 42}]}, "RATE_LIMIT"), (408, {}, "TRANSPORT_FAILURE"),
            (413, {}, "REQUEST_TOO_LARGE"), (599, [], "SERVER_FAILURE"), (500, {}, "SERVER_FAILURE"),
            (404, {}, "REQUEST_FAILURE"), (410, {}, "REQUEST_FAILURE"), (422, {}, "REQUEST_FAILURE"),
            (302, {}, "REQUEST_FAILURE"), (200, b"oops", "MALFORMED_RESPONSE"),
            (200, {"choices": []}, "MALFORMED_RESPONSE"),
            (200, {"result": "unexpected"}, "MALFORMED_RESPONSE"),
            (200, {"choices": [{"message": {"content": {}}}]}, "MALFORMED_RESPONSE"),
            (200, {"success": False, "errors": [{"code": 9999}]}, "REQUEST_FAILURE"),
        ]:
            with self.subTest(status=status, body=body), self.assertRaises(CloudflareHTTPError) as raised:
                self.generate(self.client(FakeOpenRouterHTTP((status, {}, body))))
            self.assertEqual((raised.exception.kind, raised.exception.status), (kind, status))

    def test_refuses_unreviewed_models_and_invalid_credentials_before_http(self):
        http = FakeOpenRouterHTTP()
        for operation, kind in [
            (partial(self.generate, self.client(http), "test/paid"), "MODEL_NOT_FREE"),
            (partial(self.client, http, token=CF_TOKEN + "\n"), "AUTH_FAILURE"),
            (partial(self.client, http, account=""), "AUTH_FAILURE"),
        ]:
            with self.subTest(kind=kind), self.assertRaises(CloudflareHTTPError) as raised:
                operation()
            self.assertEqual(raised.exception.kind, kind)
        self.assertEqual(http.calls, [])

    def test_credentials_and_url_path_are_scrubbed_from_public_response_and_errors(self):
        account = CF_ACCOUNT + "/synthetic"
        encoded = quote(account, safe="")
        path = f"/client/v4/accounts/{encoded}/ai/v1/chat/completions"
        private = f"{path}:{account}:{CF_TOKEN}"
        headers = {CF_TOKEN: account, "X-Debug": private}
        http = FakeOpenRouterHTTP(
            (200, headers, cloudflare_body(choices=[{"message": {"content": private}}], id=private,
                                          model=private, usage={private: [private]})),
            (403, headers, {"error": {"code": 10000, "message": private}}),
        )
        client = self.client(http, account=account)
        response = self.generate(client)
        with self.assertRaises(CloudflareHTTPError) as raised:
            self.generate(client)
        error = raised.exception
        for value in (repr(client), repr(response), str(error), repr(error), repr(error.headers), repr(error.body)):
            for secret in (account, encoded, CF_TOKEN):
                self.assertNotIn(secret, value)
        self.assertIn("/accounts/[REDACTED]/ai", response.text)
        self.assertTrue(http.calls[0][0].endswith(path))

    def test_network_error_is_replaced_without_secret_containing_exception_context(self):
        for error in (OSError, HTTPException):
            def offline(url, *_):
                raise error(f"{url}: {CF_TOKEN}")

            with self.subTest(error=error), self.assertRaises(CloudflareHTTPError) as raised:
                try:
                    self.generate(self.client(offline))
                except CloudflareHTTPError as safe:
                    self.assertNotIn(CF_TOKEN, traceback.format_exc())
                    self.assertNotIn(CF_ACCOUNT, traceback.format_exc())
                    self.assertIsNone(safe.__context__)
                    raise
            self.assertEqual(raised.exception.kind, "TRANSPORT_FAILURE")
