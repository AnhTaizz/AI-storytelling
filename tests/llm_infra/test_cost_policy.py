import unittest

from fixtures import settings
from tools.llm_infra.cost_policy import CostPolicy
from tools.llm_infra.gemini_free_models_v1 import FREE_TIER_TEXT_MODELS, SOURCE_URL, VERIFIED_ON
from tools.llm_infra.gemini_config import inspect_settings
from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError


class CostTests(unittest.TestCase):
    def test_closed_configuration(self):
        for change, message in [
            ({"LLM_FREE_ONLY":"false"}, "Phase 1"), ({"LLM_ALLOW_PAID":"true"}, "Phase 1"),
            ({"MAX_PAID_SPEND_USD":"5"}, "Phase 1"), ({"MAX_PAID_SPEND_USD":"?"}, "Invalid"),
            ({"LLM_ALLOW_PAID":"sometimes"}, "true or false"),
            ({"GEMINI_PROJECT_BILLING_1":"maybe"}, "Invalid"),
            ({"GEMINI_PROJECT_BILLING_1":"UNVERIFIED"}, "Conflicting")]:
            with self.subTest(change=change), self.assertRaisesRegex(GeminiConfigError, message):
                inspect_settings(settings("p","p") | change)

    def test_eligible_slots_and_all_missing_models(self):
        cfg = inspect_settings(settings("a","b","c") | {"GEMINI_KEYS_FREE_TIER_CONFIRMED": "false",
                                                       "GEMINI_PROJECT_BILLING_2":"",
                                                       "GEMINI_PROJECT_BILLING_3":"BILLING_ENABLED"})
        self.assertIsInstance(cfg.policy, CostPolicy)
        self.assertEqual([c.group_id for c in cfg.policy.eligible_credentials(cfg.credentials)], ["a"])
        self.assertEqual(set(cfg.policy.public_summary()["billing_status_counts"].values()), {1})
        with self.assertRaisesRegex(GeminiConfigError, "model-c, model-d"):
            cfg.policy.check_models([FREE_TIER_TEXT_MODELS[0], "model-c", "model-d"])
        keys_only = {"GEMINI_API_KEY_1": "test-key-not-real-1", "GEMINI_API_KEY_2": "test-key-not-real-2"}
        both = ["gemini_slot_1", "gemini_slot_2"]
        for extra, eligible in [
            ({}, both),
            ({"GEMINI_KEYS_FREE_TIER_CONFIRMED": ""}, both),
            ({"GEMINI_KEYS_FREE_TIER_CONFIRMED": "true"}, both),
            ({"GEMINI_PROJECT_BILLING_2": "BILLING_ENABLED"}, ["gemini_slot_1"]),
        ]:
            with self.subTest(extra=extra):
                one_line = inspect_settings(keys_only | extra)
                self.assertEqual([c.slot_id for c in one_line.policy.eligible_credentials(one_line.credentials)],
                                 eligible)
                one_line.policy.check_models(FREE_TIER_TEXT_MODELS)
                if not extra:
                    self.assertEqual(set(one_line.policy.billing_sources.values()), {"owner_standing_decision"})
        # Unlabeled slots may be different projects, so their billing answers may differ.
        unlabeled = inspect_settings(settings("", "") | {"GEMINI_PROJECT_BILLING_2": "UNVERIFIED"})
        self.assertEqual([c.slot_id for c in unlabeled.policy.eligible_credentials(unlabeled.credentials)],
                         ["gemini_slot_1"])

    def test_override_only_narrows_reviewed_models(self):
        allowed = FREE_TIER_TEXT_MODELS[0]
        unknown = "gemini-4-carbon"
        for override, expected in [(unknown, []), (f"{unknown},{allowed}", [allowed])]:
            with self.subTest(override=override):
                policy = inspect_settings({"GEMINI_FREE_MODELS": override}).policy
                self.assertEqual(policy.public_summary()["effective_allowlist"], expected)
                self.assertEqual(policy.public_summary()["ignored_models"], [unknown])
                with self.assertRaisesRegex(GeminiConfigError, "^MODEL_NOT_FREE_TIER:") as error:
                    policy.check_models([allowed, unknown])
                for detail in (unknown, SOURCE_URL, VERIFIED_ON):
                    self.assertIn(detail, str(error.exception))
