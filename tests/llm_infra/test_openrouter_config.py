from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fixtures import OPENROUTER_MODEL, OPENROUTER_TEST_KEY, openrouter_settings
from tools.llm_infra.openrouter_config import (
    DEFAULT_ACCOUNT_SCOPE, NOTICE, inspect_openrouter_settings, load_openrouter_routing_config,
)
from tools.llm_infra.openrouter_free_models_v1 import DEFAULT_MODEL_CHAIN
from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError


class OpenRouterConfigTests(unittest.TestCase):
    def test_dedupe_priority_scopes_and_process_overrides(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "settings"
            path.write_text(f"OPENROUTER_API_KEY_9={OPENROUTER_TEST_KEY}\n"
                            "OPENROUTER_ACCOUNT_LABEL_9=discarded\nOPENROUTER_MODEL=test/paid\n",
                            encoding="utf-8")
            config = load_openrouter_routing_config(path, openrouter_settings("", "account-b", "account-b", "") | {
                "OPENROUTER_MODEL": f"{OPENROUTER_MODEL}, openrouter/free", "OPENROUTER_MAX_RATE_LIMIT_HOPS": "5",
            })
        self.assertEqual([(slot.slot_id, slot.scope) for slot in config.slots], [
            ("openrouter_slot_1", DEFAULT_ACCOUNT_SCOPE), ("openrouter_slot_2", "account-b"),
            ("openrouter_slot_3", "account-b"), ("openrouter_slot_4", DEFAULT_ACCOUNT_SCOPE),
        ])
        summary = config.public_summary()
        self.assertEqual(summary["model_chain"], [OPENROUTER_MODEL, "openrouter/free"])
        self.assertEqual(summary["model_source"], "configured")
        self.assertEqual(summary["max_rate_limit_hops"], 5)
        self.assertEqual((summary["keys_configured"], summary["keys_eligible"], summary["duplicates_dropped"],
                          summary["key_scopes"], summary["labels_used"]), (5, 4, 1, 2, 1))
        self.assertEqual(summary["notice"], NOTICE)
        for value in (config, config.slots, summary):
            self.assertNotIn("test-openrouter-key-not-real", repr(value))

    def test_defaults_and_narrowing(self):
        settings = openrouter_settings("")
        config = inspect_openrouter_settings(settings)
        self.assertEqual(config.model_chain, DEFAULT_MODEL_CHAIN)
        self.assertEqual(config.model_source, "default")
        self.assertIsNone(config.effective_allowlist)
        self.assertIsNone(config.data_collection)
        self.assertEqual(config.max_rate_limit_hops, 2)
        for privacy in ("allow", "deny"):
            with self.subTest(privacy=privacy):
                restricted = inspect_openrouter_settings(settings | {
                    "OPENROUTER_FREE_MODELS": f"test/paid, {OPENROUTER_MODEL},TEST/model:free",
                    "OPENROUTER_DATA_COLLECTION": privacy,
                }, model=OPENROUTER_MODEL)
                summary = restricted.public_summary()
                self.assertEqual(summary["effective_allowlist"], [OPENROUTER_MODEL])
                self.assertEqual(summary["ignored_models"], ["TEST/model:free", "test/paid"])
                self.assertEqual(summary["data_collection"], privacy)
                with self.assertRaisesRegex(GeminiConfigError, "^MODEL_NOT_FREE_TIER:"):
                    restricted.check_models(("openrouter/free",))

    def test_invalid_and_unsafe_settings_are_rejected(self):
        for changes, message in [
            ({"OPENROUTER_API_KEY_0": "test-openrouter-key-not-real-2"}, "slot number"),
            ({"OPENROUTER_API_KEY_01": "test-openrouter-key-not-real-2"}, "slot number"),
            ({"OPENROUTER_ACCOUNT_LABEL_1": "invalid\x00label"}, "account scope"),
            ({"OPENROUTER_ACCOUNT_LABEL_1": OPENROUTER_TEST_KEY}, "credential material"),
            ({"OPENROUTER_MODEL": f"test/{OPENROUTER_TEST_KEY}:free"}, "credential material"),
            ({"OPENROUTER_FREE_MODELS": OPENROUTER_TEST_KEY}, "credential material"),
            ({"LLM_QUOTA_STATE_PATH": OPENROUTER_TEST_KEY}, "credential material"),
            ({"OPENROUTER_DATA_COLLECTION": "off"}, "DATA_COLLECTION"),
            ({"OPENROUTER_MAX_RATE_LIMIT_HOPS": "0"}, "MAX_RATE_LIMIT_HOPS"),
            ({"OPENROUTER_MAX_RATE_LIMIT_HOPS": "1.5"}, "MAX_RATE_LIMIT_HOPS"),
            ({"LLM_ALLOW_PAID": "true"}, "Paid use"),
            ({"OPENROUTER_MODEL": f"{OPENROUTER_MODEL},test/paid"}, "^MODEL_NOT_FREE_TIER:"),
            ({"OPENROUTER_MODEL": "test/model:free,"}, "^MODEL_NOT_FREE_TIER:"),
            ({"OPENROUTER_FREE_MODELS": "test/paid"}, "^MODEL_NOT_FREE_TIER:"),
        ]:
            with self.subTest(setting=next(iter(changes)), message=message):
                with self.assertRaisesRegex(GeminiConfigError, message) as caught:
                    inspect_openrouter_settings(openrouter_settings("") | changes)
                self.assertNotIn(OPENROUTER_TEST_KEY, str(caught.exception))
        with self.assertRaisesRegex(GeminiConfigError, "^NO_ELIGIBLE_KEY:"):
            inspect_openrouter_settings({}).check_eligible()
