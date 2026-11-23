from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fixtures import GROQ_TEST_KEY, groq_settings
from tools.llm_infra.groq_config import DEFAULT_ORG_SCOPE, inspect_groq_settings, load_groq_routing_config
from tools.llm_infra.groq_free_models_v1 import (
    DEFAULT_MODEL_CHAIN, FREE_PLAN_TPM, FREE_TIER_TEXT_MODELS, SMOKE_MODEL, SOURCE_URL,
    VERIFICATION_NOTE, VERIFIED_ON,
)
from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError


class GroqConfigTests(unittest.TestCase):
    def test_process_overrides_and_lowest_duplicate_wins(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings"
            path.write_text(f"GROQ_API_KEY_9={GROQ_TEST_KEY}\nGROQ_ORG_LABEL_9=discarded\n"
                            f"GROQ_API_KEY_4={GROQ_TEST_KEY}\n"
                            "GROQ_MODEL=llama-3.1-8b-instant\n", encoding="utf-8")
            config = load_groq_routing_config(path, groq_settings("team-a", "team-a", "") | {
                "GROQ_API_KEY_4": "test-groq-key-not-real-4", "GROQ_MODEL": "openai/gpt-oss-20b",
                "GROQ_MAX_RATE_LIMIT_HOPS": "5",
            })
        self.assertEqual([(slot.slot_id, slot.scope) for slot in config.slots],
                         [("groq_slot_1", "team-a"), ("groq_slot_2", "team-a"),
                          ("groq_slot_3", "org"), ("groq_slot_4", "org")])
        self.assertEqual(config.model_chain, ("openai/gpt-oss-20b",))
        self.assertEqual(config.model_source, "configured")
        self.assertEqual(config.max_rate_limit_hops, 5)
        summary = config.public_summary()
        self.assertEqual((summary["keys_configured"], summary["duplicates_dropped"]), (5, 1))
        self.assertEqual((summary["key_scopes"], summary["labels_used"]), (2, 1))
        for public in (config, config.slots, summary):
            self.assertNotIn("test-groq-key-not-real", repr(public))
        self.assertNotIn("team-a", repr(summary))

    def test_default_scope_and_explicit_organization_labels(self):
        for label, expected in (("", "org"), ("org", "org"), ("other-org", "other-org")):
            with self.subTest(label=label):
                config = inspect_groq_settings(groq_settings("", "", label))
                self.assertEqual(DEFAULT_ORG_SCOPE, "org")
                self.assertEqual([slot.scope for slot in config.slots], ["org", "org", expected])
                self.assertEqual(config.public_summary()["key_scopes"], len({"org", expected}))

    def test_reviewed_models_and_narrowing(self):
        config = inspect_groq_settings(groq_settings(""))
        self.assertEqual(config.model_chain, ("openai/gpt-oss-120b", "openai/gpt-oss-20b"))
        self.assertEqual(config.model_chain, DEFAULT_MODEL_CHAIN)
        self.assertEqual(config.model_source, "default")
        self.assertEqual(config.max_rate_limit_hops, 3)
        self.assertEqual(set(config.public_summary()["effective_allowlist"]), {
            "openai/gpt-oss-120b", "openai/gpt-oss-20b",
        })
        self.assertEqual((SOURCE_URL, VERIFIED_ON), ("https://console.groq.com/docs/models", "2026-11-23"))
        self.assertIn("console.groq.com/settings/limits", VERIFICATION_NOTE)
        self.assertIn("console.groq.com/docs/deprecations", VERIFICATION_NOTE)
        self.assertIn("2026-08-16", VERIFICATION_NOTE)
        self.assertEqual((SMOKE_MODEL, FREE_PLAN_TPM), ("openai/gpt-oss-20b", 8000))
        allowed = FREE_TIER_TEXT_MODELS[0]
        preview = "qwen/qwen3.8-27b"
        config = inspect_groq_settings({"GROQ_FREE_MODELS": f" {preview}, {allowed} ",
                                        "GROQ_MODEL": preview}, model=allowed)
        self.assertEqual(config.public_summary()["effective_allowlist"], [allowed])
        self.assertEqual(config.public_summary()["ignored_models"], [preview])
        for changes in ({"GROQ_MODEL": preview}, {"GROQ_MODEL": " , "},
                        {"GROQ_FREE_MODELS": preview}, {"GROQ_FREE_MODELS": allowed},
                        {"GROQ_MODEL": "llama-3.1-8b-instant"}, {"GROQ_MODEL": "llama-3.3-70b-versatile"}):
            with self.subTest(changes=changes), self.assertRaisesRegex(GeminiConfigError, "^MODEL_NOT_FREE_TIER:"):
                inspect_groq_settings(changes)

    def test_default_declaration_and_explicit_exclusions(self):
        source = groq_settings("", "paid-org", "unverified-org", "")
        declared = {"GROQ_ORG_PLAN_1": "FREE_PLAN_CONFIRMED", "GROQ_ORG_PLAN_2": "PAID_PLAN",
                    "GROQ_ORG_PLAN_3": "UNVERIFIED"}
        for confirmation, keys, expected in [
            ({}, source, [1, 4]), ({"GROQ_KEYS_FREE_PLAN_CONFIRMED": "true"}, source, [1, 4]),
            ({"GROQ_KEYS_FREE_PLAN_CONFIRMED": "false"}, source | {"GROQ_ORG_LABEL_4": "undeclared-org"}, [1]),
        ]:
            with self.subTest(confirmation=confirmation):
                config = inspect_groq_settings(keys | declared | confirmation)
                self.assertEqual([slot.slot_id for slot in config.slots], [f"groq_slot_{n}" for n in expected])
                self.assertEqual(config.public_summary()["plan_status_counts"], {
                    "FREE_PLAN_CONFIRMED": len(expected), "PAID_PLAN": 1, "UNVERIFIED": 3 - len(expected),
                })
                self.assertIn("An API key cannot show the Groq plan", config.public_summary()["notice"])
        for label in ("", "org", "shared"):
            for plan in ("PAID_PLAN", "UNVERIFIED"):
                with self.subTest(label=label, plan=plan), self.assertRaises(GeminiConfigError) as caught:
                    inspect_groq_settings(groq_settings(label, "shared" if label == "shared" else "")
                                          | {"GROQ_ORG_PLAN_2": plan})
                self.assertEqual(str(caught.exception), "Conflicting plan declarations for a shared Groq "
                                 "organization; label keys from different organizations with GROQ_ORG_LABEL_<n>")
        with TemporaryDirectory() as tmp, self.assertRaisesRegex(GeminiConfigError, "^NO_ELIGIBLE_KEY:"):
            load_groq_routing_config(Path(tmp) / "absent", groq_settings("") | {
                "GROQ_KEYS_FREE_PLAN_CONFIRMED": "false",
            })

    def test_unsafe_or_ambiguous_configuration_fails_safely(self):
        for changes, message in [
            ({"LLM_FREE_ONLY": "false"}, "Phase 2"),
            ({"LLM_ALLOW_PAID": "true"}, "Phase 2"),
            ({"MAX_PAID_SPEND_USD": "0.001"}, "Phase 2"),
            ({"MAX_PAID_SPEND_USD": "NaN"}, "Phase 2"),
            ({"MAX_PAID_SPEND_USD": "unknown"}, "Invalid"),
            ({"GROQ_KEYS_FREE_PLAN_CONFIRMED": "maybe"}, "true or false"),
            ({"GROQ_ORG_PLAN_1": GROQ_TEST_KEY}, "Invalid"),
            ({"GROQ_ORG_PLAN_2": "PAID_PLAN"}, "Conflicting plan"),
            ({"GROQ_API_KEY_0": GROQ_TEST_KEY}, "slot number"),
            ({"GROQ_API_KEY_01": GROQ_TEST_KEY}, "slot number"),
            ({"GROQ_ORG_LABEL_1": "team\nname"}, "Invalid Groq organization scope"),
            ({"GROQ_ORG_LABEL_1": f"team-{GROQ_TEST_KEY}"}, "credential material"),
            ({"GROQ_MODEL": GROQ_TEST_KEY}, "credential material"),
            ({"GROQ_FREE_MODELS": GROQ_TEST_KEY}, "credential material"),
            ({"LLM_QUOTA_STATE_PATH": GROQ_TEST_KEY}, "credential material"),
            ({"GROQ_MAX_RATE_LIMIT_HOPS": "0"}, "integer"),
            ({"GROQ_MAX_RATE_LIMIT_HOPS": "1.5"}, "integer"),
        ]:
            with self.subTest(changes=changes), self.assertRaisesRegex(GeminiConfigError, message) as caught:
                inspect_groq_settings(groq_settings("team-a", "team-a") | changes)
            self.assertNotIn(GROQ_TEST_KEY, repr(caught.exception))
