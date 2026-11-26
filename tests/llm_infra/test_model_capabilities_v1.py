import unittest

from tools.llm_infra import cloudflare_free_models_v1, gemini_free_models_v1, groq_free_models_v1
from tools.llm_infra.model_capabilities_v1 import CAPABILITIES, UNKNOWN_CONTEXT_TOKENS, model_capability
from tools.llm_infra.openrouter_free_models_v1 import DEFAULT_MODEL_CHAIN


class CapabilityTests(unittest.TestCase):
    def test_snapshot_covers_maintained_free_models(self):
        lists = {"gemini": gemini_free_models_v1.FREE_TIER_TEXT_MODELS,
                 "groq": groq_free_models_v1.FREE_TIER_TEXT_MODELS,
                 "cloudflare": cloudflare_free_models_v1.ACTIVE_NEURON_PRICES, "openrouter": DEFAULT_MODEL_CHAIN}
        self.assertEqual(set(CAPABILITIES), {(provider, model) for provider, models in lists.items() for model in models})
        for (provider, model), capability in CAPABILITIES.items():
            with self.subTest(provider=provider, model=model):
                self.assertTrue(capability.source.startswith("https://"))
                self.assertRegex(capability.verified_on, r"^2026-11-2[34]$")
                self.assertEqual(capability.json_mode, "prompt" if provider == "cloudflare" else "native")
                self.assertEqual(capability.capacity, 8000 if provider == "groq" else UNKNOWN_CONTEXT_TOKENS)
        self.assertIsNotNone(model_capability("openrouter", "example/model:free"))
        self.assertIsNone(model_capability("openrouter", "example/model"))
