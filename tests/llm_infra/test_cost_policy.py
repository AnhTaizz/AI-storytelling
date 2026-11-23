import unittest

from fixtures import settings
from tools.llm_infra.cost_policy import CostPolicy
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
        cfg = inspect_settings(settings("a","b","c") | {"GEMINI_PROJECT_BILLING_2":"",
                                                       "GEMINI_PROJECT_BILLING_3":"BILLING_ENABLED"})
        self.assertIsInstance(cfg.policy, CostPolicy)
        self.assertEqual([c.group_id for c in cfg.policy.eligible_credentials(cfg.credentials)], ["a"])
        self.assertEqual(set(cfg.policy.public_summary()["billing_status_counts"].values()), {1})
        with self.assertRaisesRegex(GeminiConfigError, "model-c, model-d"):
            cfg.policy.check_models(["model-a", "model-c", "model-d"])
        # Unlabeled slots may be different projects, so their billing answers may differ.
        unlabeled = inspect_settings(settings("", "") | {"GEMINI_PROJECT_BILLING_2": "UNVERIFIED"})
        self.assertEqual([c.slot_id for c in unlabeled.policy.eligible_credentials(unlabeled.credentials)],
                         ["gemini_slot_1"])
