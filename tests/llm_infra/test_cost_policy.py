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

    def test_project_attestation_source_and_inheritance(self):
        for labels, declarations, bulk, expected, source in [
            (("",), ("",), True, "FREE_TIER_CONFIRMED", "bulk_line"),
            (("p", "p"), ("", ""), True, "FREE_TIER_CONFIRMED", "bulk_line"),
            (("p", "p"), ("", "FREE_TIER_CONFIRMED"), False, "FREE_TIER_CONFIRMED", "per_project"),
            (("p", "p"), ("UNVERIFIED", ""), True, "UNVERIFIED", "per_project"),
            (("p", "p"), ("", "BILLING_ENABLED"), True, "BILLING_ENABLED", "per_project"),
            (("p", "p"), ("", ""), False, "UNVERIFIED", "default"),
        ]:
            with self.subTest(labels=labels, declarations=declarations, bulk=bulk):
                env = settings(*labels)
                env.update({f"GEMINI_PROJECT_BILLING_{i}": v for i, v in enumerate(declarations, 1)})
                cfg = inspect_settings(env | {"GEMINI_KEYS_FREE_TIER_CONFIRMED": str(bulk)})
                self.assertEqual(set(cfg.policy.billing.values()), {expected})
                self.assertEqual(cfg.policy.projects, [{
                    "project_label": cfg.credentials[0].project_label, "slots": list(range(1, len(labels)+1)),
                    "billing_status": expected, "source": source}])
                if expected == "FREE_TIER_CONFIRMED":
                    self.assertEqual(cfg.policy.eligible_credentials(cfg.credentials), cfg.credentials)
                else:
                    with self.assertRaisesRegex(GeminiConfigError, "^NO_FREE_TIER_CONFIRMED_PROJECT"):
                        cfg.policy.eligible_credentials(cfg.credentials)
        with self.assertRaisesRegex(GeminiConfigError, "^PER_PROJECT_CONFIRMATION_REQUIRED:") as error:
            inspect_settings(settings("a", "b") | {"GEMINI_KEYS_FREE_TIER_CONFIRMED": "true"})
        self.assertNotIn("test-key-not-real", str(error.exception))
