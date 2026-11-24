import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

from fixtures import (CF_ACCOUNT, FakeCloudflare, FakeOpenRouterHTTP, cloudflare_body, cloudflare_settings,
                      groq_settings, openrouter_body, openrouter_settings, settings)
from tools.llm_infra.cloudflare_transport import CloudflareClient
from tools.llm_infra.groq_transport import GroqClient, GroqHTTPError
from tools.llm_infra.openrouter_transport import OpenRouterClient
from tools.llm_infra.pipeline_clients import MAX_TRANSPORT_CALLS, ProviderFailure, build_adapter, transport_budget
from tools.llm_infra.quota_state import QuotaStateStore
from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError
from tools.story_pipeline.llm import QUOTA_PATTERN


class AdapterTests(unittest.TestCase):
    def test_generate_via_existing_router_and_transport(self):
        headers = {"x-ratelimit-remaining-tokens": "35", "Authorization": "private"}
        body = openrouter_body(usage={"prompt_tokens": 9, "completion_tokens": 10,
                                     "completion_tokens_details": {"reasoning_tokens": 4}, "cost": 0})
        for provider, config, client in [("groq", groq_settings(""), GroqClient),
                                         ("openrouter", openrouter_settings(""), OpenRouterClient),
                                         ("cloudflare", cloudflare_settings(CF_ACCOUNT), CloudflareClient)]:
            with self.subTest(provider=provider):
                payload = cloudflare_body(usage=body["usage"]) if provider == "cloudflare" else body
                if provider == "cloudflare":
                    fake = FakeCloudflare(client, (200, headers, payload))
                    http, factory = fake.http, fake.factory
                else:
                    http = FakeOpenRouterHTTP((200, headers, payload))
                    factory = lambda key: client(key, http=http)
                adapter = build_adapter(provider, config, QuotaStateStore(None), client_factory=factory)
                record = adapter.complete(system="JSON please", user="fixture", request_id="brief:ch1:attempt1")
                request = http.calls[0][2]
                self.assertEqual(request["max_tokens"], 4096)
                self.assertEqual(request.get("response_format"),
                                 None if provider == "cloudflare" else {"type": "json_object"})
                self.assertEqual("Reply with one JSON object only." in request["messages"][0]["content"],
                                 provider == "cloudflare")
                self.assertEqual(record["raw_content"], '{"status":"ok"}')
                self.assertEqual(record["provider"], provider)
                self.assertEqual(record["model_requested"], adapter.models[0])
                self.assertEqual(record["model_reported"], payload["model"])
                self.assertEqual(record["usage"], {"input_tokens": 9, "output_tokens": 10, "reasoning_tokens": 4})
                self.assertEqual(record["quota_remaining"], {"x-ratelimit-remaining-tokens": 35})
                self.assertGreaterEqual(record["latency_ms"], 0)
                self.assertTrue(record["quota_scope"])

    def test_paid_and_non_free_models_are_refused_before_factory(self):
        for provider, config in [("groq", groq_settings("")), ("openrouter", openrouter_settings("")),
                                 ("cloudflare", cloudflare_settings(CF_ACCOUNT)), ("gemini", settings("project"))]:
            with self.subTest(provider=provider):
                with self.assertRaisesRegex(GeminiConfigError, "MODEL_NOT_FREE_TIER"):
                    build_adapter(provider, config, QuotaStateStore(None), model="paid/model",
                                  client_factory=self.fail, strict=True)

    def test_transport_error_mapping(self):
        for code in ("REQUEST_TOO_LARGE", "AUTH_FAILURE", "MODEL_UNAVAILABLE", "EDGE_BLOCKED", "RATE_LIMIT"):
            with self.subTest(code=code):
                def generate(**kwargs):
                    raise GroqHTTPError(kind=code, status=429, body={"message": "private input"})
                adapter = build_adapter("groq", groq_settings(""), QuotaStateStore(None),
                                        client_factory=lambda key: SimpleNamespace(generate=generate))
                adapter.router._max_wait = 0
                with self.assertRaises(ProviderFailure) as raised:
                    adapter.complete(system="", user="", request_id="example")
                error = raised.exception
                expected = {"RATE_LIMIT": "QUOTA_EXHAUSTED", "AUTH_FAILURE": "NO_USABLE_CREDENTIAL"}.get(code, code)
                self.assertEqual(error.code, expected)
                self.assertEqual(bool(QUOTA_PATTERN.search(str(error))), code == "RATE_LIMIT")
                self.assertNotIn("private input", str(error))

    def test_dispatch_budget_bounds_authentication_hops(self):
        calls = []

        def factory(key):
            def generate(**kwargs):
                calls.append(key)
                raise GroqHTTPError(kind="AUTH_FAILURE", status=401)
            return SimpleNamespace(generate=generate)

        adapter = build_adapter("groq", groq_settings(*([""] * (MAX_TRANSPORT_CALLS + 2))),
                                QuotaStateStore(None), client_factory=factory)
        with transport_budget(), self.assertRaisesRegex(ProviderFailure, "DISPATCH_LIMIT"):
            adapter.complete(system="", user="", request_id="utility")
        self.assertEqual(len(calls), MAX_TRANSPORT_CALLS)

    def test_direct_endpoint_and_sdk_are_absent_from_tools(self):
        for path in (Path(__file__).resolve().parents[2] / "tools").rglob("*.py"):
            content = path.read_text(encoding="utf-8")
            self.assertNotIn("api.openai.com", content.lower(), str(path))
            for node in ast.walk(ast.parse(content)):
                if isinstance(node, ast.Import):
                    self.assertFalse(any(name.name.split(".")[0] == "openai" for name in node.names), str(path))
                elif isinstance(node, ast.ImportFrom):
                    self.assertNotEqual((node.module or "").split(".")[0], "openai", str(path))
