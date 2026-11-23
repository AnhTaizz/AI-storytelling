import unittest

from tools.llm_infra.cloudflare_free_models_v1 import (
    DAILY_FREE_NEURONS, DEFAULT_MODEL_CHAIN, NEURON_PRICES, SOURCE_URL, VERIFIED_ON,
)


class CloudflareFreeModelsTests(unittest.TestCase):
    def test_reviewed_pricing_snapshot(self):
        self.assertEqual(SOURCE_URL, "https://developers.cloudflare.com/workers-ai/platform/pricing/")
        self.assertEqual(VERIFIED_ON, "2026-11-24")
        self.assertEqual(DAILY_FREE_NEURONS, 10000)
        self.assertEqual(DEFAULT_MODEL_CHAIN, ("@cf/openai/gpt-oss-120b", "@cf/qwen/qwen3-30b-a3b-fp8"))
        self.assertEqual(len(NEURON_PRICES), 8)
        for model, price in NEURON_PRICES.items():
            with self.subTest(model=model):
                self.assertTrue(model.startswith("@cf/"))
                self.assertLess(0, price[0])
                self.assertLess(price[0], price[1])
