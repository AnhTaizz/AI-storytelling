from dataclasses import replace
import unittest
from unittest.mock import Mock

from tools.llm_infra.model_capabilities_v1 import CAPABILITIES
from tools.llm_infra.pipeline_clients import ProviderFailure
from tools.llm_infra.routing_policy import DEFAULT_POLICY, RoutingPolicy, Tier, load_policy
from tools.llm_infra.telemetry import Telemetry
from tools.llm_infra.unified_router import MAX_PROVIDER_CALLS, ObservedGeminiClient, UnifiedLLMClient
from tools.story_pipeline.llm import QUOTA_PATTERN


MODELS = {"gemini": "gemini-3.8-flash", "groq": "openai/gpt-oss-20b",
          "cloudflare": "@cf/openai/gpt-oss-120b", "openrouter": "openrouter/free"}


def adapter(provider, *, skip=(None, None), error=None, usage=None):
    stub = Mock()
    stub.models = (MODELS[provider],)
    stub.allows.return_value = True
    stub.availability.return_value = skip
    stub.complete.side_effect = error
    stub.complete.return_value = {"raw_content": "{}", "provider": provider,
                                  "model_requested": stub.models[0], "usage": usage}
    return stub


def complete(client, stage="utility", user="hello"):
    return client.complete(system="", user=user, request_id=f"{stage}::attempt1")


def policy(candidates, cross=True):
    return RoutingPolicy({"default": "test"}, {"test": Tier(tuple(candidates), cross, 4096)}, "a" * 64)


class UnifiedTests(unittest.TestCase):
    def test_first_eligible_provider_and_capacity_skips(self):
        for payload_size, expected in [(1, "groq"), (12_000, "cloudflare"), (49_000, None)]:
            with self.subTest(payload_size=payload_size):
                adapters = {p: adapter(p) for p in MODELS}
                telemetry = Telemetry(":memory:")
                client = UnifiedLLMClient(load_policy(DEFAULT_POLICY), adapters, telemetry=telemetry).for_run("run-test")
                if expected is None:
                    with self.assertRaisesRegex(RuntimeError, "NO_ELIGIBLE_PROVIDER.*REQUEST_TOO_LARGE"):
                        complete(client, user="x" * payload_size)
                else:
                    self.assertEqual(complete(client, user="x" * payload_size)["provider"], expected)
                for provider, stub in adapters.items():
                    self.assertEqual(stub.complete.call_count, int(provider == expected))
                rows = telemetry._memory.execute("SELECT provider, outcome, tokens_source, input_tokens, "
                                                 "output_tokens, run_id, stage, routing_policy_sha256 "
                                                 "FROM llm_requests ORDER BY id").fetchall()
                self.assertEqual(rows[0][:3], ("groq", "SUCCESS" if expected == "groq" else "SKIPPED", "estimated"))
                self.assertEqual(rows[0][3:], ((payload_size + 2) // 3, 4096, "run-test", "utility", client.policy_hash))

    def test_quality_tier_never_crosses_providers(self):
        for unavailable in (False, True):
            with self.subTest(unavailable=unavailable):
                adapters = {"cloudflare": adapter("cloudflare")}
                if not unavailable:
                    adapters["gemini"] = adapter("gemini", error=ProviderFailure("SERVER_FAILURE"))
                client = UnifiedLLMClient(policy(["gemini:*", "cloudflare:*"], cross=False), adapters)
                with self.assertRaisesRegex(RuntimeError, "NOT_CONFIGURED" if unavailable else "SERVER_FAILURE"):
                    complete(client, stage="plan")
                adapters["cloudflare"].complete.assert_not_called()

    def test_utility_fallback_only_on_eligible_failures(self):
        for code in ("QUOTA_EXHAUSTED", "SERVER_FAILURE", "TIMEOUT", "EDGE_BLOCKED", "REQUEST_TOO_LARGE"):
            with self.subTest(code=code):
                groq = adapter("groq", error=ProviderFailure(code))
                cloudflare = adapter("cloudflare", usage={"input_tokens": 10, "output_tokens": 5,
                                                          "reasoning_tokens": 3})
                telemetry = Telemetry(":memory:")
                client = UnifiedLLMClient(policy(["groq:*", "cloudflare:*"]), {"groq": groq, "cloudflare": cloudflare},
                                          telemetry=telemetry)
                if code in {"EDGE_BLOCKED", "REQUEST_TOO_LARGE"}:
                    with self.assertRaisesRegex(ProviderFailure, code):
                        complete(client)
                    cloudflare.complete.assert_not_called()
                else:
                    result = complete(client)
                    self.assertEqual(result["provider"], "cloudflare")
                    self.assertEqual(result["fallback_from"], [{"provider": "groq", "model": MODELS["groq"], "code": code}])
                rows = telemetry._memory.execute("SELECT provider, outcome, error_code, tokens_source, "
                                                 "input_tokens, output_tokens, reasoning_tokens "
                                                 "FROM llm_requests ORDER BY id").fetchall()
                self.assertEqual(rows[0], ("groq", "FAILED", code, "unknown", None, None, None))
                if len(rows) == 2:
                    self.assertEqual(rows[1], ("cloudflare", "SUCCESS", None, "reported", 10, 5, 3))

    def test_all_quota_pauses_but_mixed_skips_do_not(self):
        adapters = {"groq": adapter("groq", skip=("QUOTA_EXHAUSTED", 2000)),
                    "gemini": adapter("gemini", skip=("QUOTA_EXHAUSTED", 1500))}
        for other in (None, "cloudflare:*", "groq:paid/model"):
            with self.subTest(other=other):
                candidates = ["groq:*", "gemini:*"] + ([other] if other else [])
                client = UnifiedLLMClient(policy(candidates), adapters)
                with self.assertRaises(RuntimeError) as raised:
                    complete(client)
                if other:
                    self.assertIn("NO_ELIGIBLE_PROVIDER", str(raised.exception))
                    self.assertIsNone(QUOTA_PATTERN.search(str(raised.exception)))
                else:
                    self.assertEqual(raised.exception.resume_after, 1500)
                    self.assertRegex(str(raised.exception), QUOTA_PATTERN)
        for stub in adapters.values():
            stub.complete.assert_not_called()

    def test_policy_filters_unsupported_json_and_honors_known_context(self):
        groq = adapter("groq")
        key = ("groq", MODELS["groq"])
        for changes, code in [({"json_mode": "none"}, "JSON_UNSUPPORTED"),
                              ({"context_tokens": 4000}, "REQUEST_TOO_LARGE")]:
            with self.subTest(code=code):
                capabilities = CAPABILITIES | {key: replace(CAPABILITIES[key], **changes)}
                client = UnifiedLLMClient(policy(["groq:*"]), {"groq": groq}, capabilities)
                with self.assertRaisesRegex(RuntimeError, code):
                    complete(client)
        groq.complete.assert_not_called()

    def test_router_dispatch_cap_counts_candidates(self):
        alternate = adapter("openrouter", error=ProviderFailure("SERVER_FAILURE"))
        candidates = [f"openrouter:example/model-{i}:free" for i in range(MAX_PROVIDER_CALLS + 2)]
        client = UnifiedLLMClient(policy(candidates), {"openrouter": alternate})
        with self.assertRaisesRegex(RuntimeError, "DISPATCH_LIMIT"):
            complete(client)
        self.assertEqual(alternate.complete.call_count, MAX_PROVIDER_CALLS)

    def test_telemetry_failure_does_not_fail_call(self):
        telemetry = Mock()
        telemetry.write.side_effect = OSError("fake path or credential")
        client = UnifiedLLMClient(policy(["groq:*"]), {"groq": adapter("groq")}, telemetry=telemetry)
        with self.assertLogs("tools.llm_infra.telemetry", "WARNING") as logged:
            self.assertEqual(complete(client)["provider"], "groq")
        self.assertNotIn("fake path", str(logged.output))

    def test_legacy_gemini_records_usage_and_preserves_errors(self):
        gemini = Mock(model=MODELS["gemini"])
        gemini.complete.return_value = {"raw_content": "{}", "model_requested": MODELS["gemini"],
                                        "model_reported_if_available": MODELS["gemini"] + "-version",
                                        "usage_metadata": {"prompt_token_count": 8, "thoughts_token_count": 2}}
        telemetry = Telemetry(":memory:")
        client = ObservedGeminiClient(gemini, telemetry).for_run("ep01")
        self.assertEqual(complete(client, "script")["provider"], "gemini")
        gemini.complete.side_effect = RuntimeError("Gemini transport failed safely: SERVER_FAILURE")
        with self.assertRaisesRegex(RuntimeError, "Gemini transport failed safely: SERVER_FAILURE"):
            complete(client, "revise")
        rows = telemetry._memory.execute("SELECT run_id, stage, provider, model_requested, tokens_source, "
                                         "input_tokens, reasoning_tokens, error_code FROM llm_requests ORDER BY id").fetchall()
        self.assertEqual(rows, [("ep01", "script", "gemini", MODELS["gemini"], "reported", 8, 2, None),
                                ("ep01", "revise", "gemini", MODELS["gemini"], "unknown", None, None, "SERVER_FAILURE")])
