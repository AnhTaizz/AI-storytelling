import unittest

from tools.llm_infra.model_capabilities_v1 import UNKNOWN_CONTEXT_TOKENS
from tools.llm_infra.pipeline_clients import JSON_PROMPT
from tools.llm_infra.token_estimate import estimate_input_tokens
from tools.model_bench.dataset import load_dataset
from tools.model_bench.planning import SYSTEM, approval_sha256, make_plan, plan_markdown, user_prompt
from tools.model_bench.registry import select_model


class PlanningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = load_dataset()[1][0]

    def test_estimates_include_provider_prompt_and_output_reserve(self):
        model = select_model("cloudflare", "@cf/openai/gpt-oss-20b")
        item, = make_plan(model, [self.case], 512)
        self.assertEqual(item["input"], estimate_input_tokens(SYSTEM, user_prompt(self.case), JSON_PROMPT))
        self.assertEqual(item["reserved_output"], 512)
        self.assertGreater(item["neurons"], 0)
        self.assertEqual(item["flags"], [])

    def test_known_limits_and_unknown_adapter_context(self):
        model = select_model("groq", "openai/gpt-oss-20b")
        scenarios = [(model, 8000, ["tpm"]),
                     (model, UNKNOWN_CONTEXT_TOKENS, ["adapter_context_guard", "tpm"]),
                     (model | {"context_tokens": 250, "max_output_tokens": 100}, 250,
                      ["context", "max_output_tokens"])]
        for entry, reserve, flags in scenarios:
            with self.subTest(reserve=reserve):
                self.assertEqual(make_plan(entry, [self.case], reserve)[0]["flags"], flags)
        self.assertIsNone(model["context_tokens"])

    def test_plan_fingerprint_and_daily_floor(self):
        model = select_model("openrouter", "demo/model:free")
        plan = make_plan(model, [self.case] * 25, 512)
        dry = approval_sha256({"mode": "dry-run"}, model, plan)
        self.assertEqual(dry, approval_sha256({"mode": "live"}, model, plan))
        self.assertNotEqual(dry, approval_sha256({"mode": "live"}, model, plan[:-1]))
        markdown = plan_markdown(model, plan, dry)
        self.assertIn("| event_extraction | 25 | 75 |", markdown)
        self.assertTrue(markdown.rstrip().endswith("| 2 |"))
