import unittest

from fixtures import OPENROUTER_MODEL
from tools.llm_infra.openrouter_free_models_v1 import (
    DEFAULT_MODEL_CHAIN, SOURCE_URL, VERIFICATION_NOTE, VERIFIED_ON, is_free_model,
)


class OpenRouterFreeModelsTests(unittest.TestCase):
    def test_reviewed_rule_and_default_chain(self):
        self.assertEqual(DEFAULT_MODEL_CHAIN, ("openrouter/free",))
        self.assertEqual(SOURCE_URL, "https://openrouter.ai/docs/guides/routing/model-variants/free")
        self.assertEqual(VERIFIED_ON, "2026-11-23")
        self.assertIn("openrouter/free", VERIFICATION_NOTE)
        for model, allowed in [
            ("openrouter/free", True), (OPENROUTER_MODEL, True), ("test/model-v2.1:free", True),
            ("test/model", False), ("openrouter/auto", False), ("OpenRouter/free", False),
            ("TEST/model:free", False), ("test/model:FREE", False), ("test/model:free:paid", False),
            ("test/model:free:free", False), ("model:free-variant:free", False),
            (f"{OPENROUTER_MODEL},test/paid", False), (f"test/paid,{OPENROUTER_MODEL}", False),
            (" test/model:free", False), ("test/model:free\n", False), ("openrouter/free ", False),
            ("test/\tmodel:free", False), ("test/\u2003model:free", False), ("test/\x00model:free", False),
            ("", False), (":free", False), (None, False), (17, False),
        ]:
            with self.subTest(model=model):
                self.assertIs(is_free_model(model), allowed)
