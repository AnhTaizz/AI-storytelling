from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fixtures import CF_ACCOUNT, CF_MODEL, CF_OTHER_ACCOUNT, CF_TOKEN, cloudflare_settings
from tools.llm_infra.cloudflare_config import (
    GeminiConfigError, inspect_cloudflare_settings, load_cloudflare_routing_config,
)
from tools.llm_infra.cloudflare_free_models_v1 import DEFAULT_MODEL_CHAIN, NEURON_PRICES


class CloudflareConfigTests(unittest.TestCase):
    def test_pairs_use_numeric_priority_and_first_slot_alias_per_account(self):
        pairs = cloudflare_settings(CF_ACCOUNT, CF_OTHER_ACCOUNT, CF_ACCOUNT) | {
            "CLOUDFLARE_ACCOUNT_ID_10": CF_ACCOUNT, "CLOUDFLARE_API_TOKEN_10": CF_TOKEN,
            "CLOUDFLARE_ACCOUNT_ID_8": CF_OTHER_ACCOUNT, "CLOUDFLARE_API_TOKEN_8": CF_TOKEN,
            "CLOUDFLARE_ACCOUNT_ID_9": "", "CLOUDFLARE_API_TOKEN_9": "",
        }
        with TemporaryDirectory() as tmp:
            config = load_cloudflare_routing_config(Path(tmp) / "absent", dict(reversed(list(pairs.items()))))
        self.assertEqual([(s.slot_id, s.scope) for s in config.slots], [
            ("cloudflare_slot_1", "cloudflare_account_1"), ("cloudflare_slot_2", "cloudflare_account_2"),
            ("cloudflare_slot_3", "cloudflare_account_1"), ("cloudflare_slot_8", "cloudflare_account_2"),
        ])
        self.assertEqual(config.model_chain, DEFAULT_MODEL_CHAIN)
        self.assertEqual(config.effective_allowlist, set(NEURON_PRICES))
        self.assertEqual((config.daily_neuron_budget, config.max_rate_limit_hops), (9000, 2))
        summary = config.public_summary()
        self.assertEqual((summary["keys_configured"], summary["keys_eligible"], summary["duplicates_dropped"],
                          summary["key_scopes"]), (5, 4, 1, 2))
        for secret in (CF_ACCOUNT, CF_OTHER_ACCOUNT, CF_TOKEN):
            self.assertNotIn(secret, repr(config) + repr(summary))

    def test_rejects_bad_pairing_and_plan_conflicts_without_echoing_values(self):
        pairs = cloudflare_settings(CF_ACCOUNT, CF_ACCOUNT)
        for values, message in [
            ({"CLOUDFLARE_ACCOUNT_ID_1": CF_ACCOUNT}, "slot 1"),
            ({"CLOUDFLARE_API_TOKEN_2": CF_TOKEN}, "slot 2"),
            (pairs | {"CLOUDFLARE_API_TOKEN_01": CF_TOKEN}, "Duplicate or invalid"),
            (pairs | {"CLOUDFLARE_ACCOUNT_ID_0": CF_ACCOUNT}, "Duplicate or invalid"),
            (pairs | {"CLOUDFLARE_PLAN_2": "WORKERS_PAID"}, "Conflicting"),
            (pairs | {"CLOUDFLARE_PLAN_2": "UNVERIFIED", "CLOUDFLARE_API_TOKEN_2": CF_TOKEN}, "Conflicting"),
            (pairs | {"CLOUDFLARE_PLAN_2": CF_TOKEN}, "plan declaration for slot 2"),
            (pairs | {"CLOUDFLARE_KEYS_FREE_PLAN_CONFIRMED": "unknown"}, "Expected true or false"),
            (pairs | {"CLOUDFLARE_MODEL": CF_ACCOUNT}, "credential material"),
            (pairs | {"LLM_QUOTA_STATE_PATH": CF_TOKEN}, "credential material"),
            (pairs | {"CLOUDFLARE_ACCOUNT_ID_" + "1" * 5000: CF_ACCOUNT}, "Invalid Cloudflare credential"),
        ]:
            with self.subTest(message=message), self.assertRaisesRegex(GeminiConfigError, message) as raised:
                inspect_cloudflare_settings(values)
            self.assertNotIn(CF_ACCOUNT, str(raised.exception))
            self.assertNotIn(CF_TOKEN, str(raised.exception))

    def test_only_workers_free_is_eligible(self):
        pairs = cloudflare_settings(CF_ACCOUNT, CF_OTHER_ACCOUNT) | {
            "CLOUDFLARE_KEYS_FREE_PLAN_CONFIRMED": "false", "CLOUDFLARE_PLAN_2": "WORKERS_PAID",
        }
        config = inspect_cloudflare_settings(pairs)
        with self.assertRaisesRegex(GeminiConfigError, "NO_ELIGIBLE_KEY"):
            config.check_eligible()
        self.assertEqual(config.public_summary()["plan_status_counts"],
                         {"WORKERS_FREE_CONFIRMED": 0, "UNVERIFIED": 1, "WORKERS_PAID": 1})
        config = inspect_cloudflare_settings(pairs | {"CLOUDFLARE_PLAN_1": "WORKERS_FREE_CONFIRMED"})
        self.assertEqual([s.scope for s in config.slots], ["cloudflare_account_1"])

    def test_narrowing_and_cost_controls_apply(self):
        pairs = cloudflare_settings(CF_ACCOUNT)
        narrow = {"CLOUDFLARE_FREE_MODELS": f"{CF_MODEL},preview"}
        config = inspect_cloudflare_settings(pairs | narrow, CF_MODEL)
        self.assertEqual(config.model_chain, (CF_MODEL,))
        self.assertEqual(config.effective_allowlist, {CF_MODEL})
        self.assertEqual(config.ignored_models, {"preview"})
        for changes, message in [
            (narrow, "MODEL_NOT_FREE_TIER"), ({"CLOUDFLARE_MODEL": "preview"}, "MODEL_NOT_FREE_TIER"),
            ({"CLOUDFLARE_MODEL": f"{CF_MODEL},"}, "MODEL_NOT_FREE_TIER"),
            ({"LLM_ALLOW_PAID": "true"}, "Paid use"), ({"LLM_FREE_ONLY": "false"}, "Paid use"),
            ({"MAX_PAID_SPEND_USD": "0.01"}, "Paid use"),
        ]:
            with self.subTest(changes=changes), self.assertRaisesRegex(GeminiConfigError, message):
                inspect_cloudflare_settings(pairs | changes)

    def test_budget_bounds_and_hops(self):
        for budget, hops, valid in [("1", "1", True), ("10000", "3", True), ("0", "2", False),
                                    ("10001", "2", False), ("1.5", "2", False), ("2", "0", False)]:
            with self.subTest(budget=budget, hops=hops):
                values = {"CLOUDFLARE_DAILY_NEURON_BUDGET": budget, "CLOUDFLARE_MAX_RATE_LIMIT_HOPS": hops}
                if valid:
                    config = inspect_cloudflare_settings(values)
                    self.assertEqual((config.daily_neuron_budget, config.max_rate_limit_hops),
                                     (int(budget), int(hops)))
                else:
                    with self.assertRaisesRegex(GeminiConfigError, "must be an integer"):
                        inspect_cloudflare_settings(values)
