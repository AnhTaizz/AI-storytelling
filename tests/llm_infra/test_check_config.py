from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fixtures import (
    CF_ACCOUNT, CF_MODEL, CF_OTHER_ACCOUNT, CF_TOKEN, Clock, GROQ_TEST_KEY, OPENROUTER_MODEL, OPENROUTER_TEST_KEY,
    cloudflare_settings, groq_settings, openrouter_settings, settings,
)
from tools.llm_infra.check_config import main
from tools.llm_infra.groq_free_models_v1 import DEFAULT_MODEL_CHAIN
from tools.llm_infra.neuron_ledger import NeuronLedger, utc_day
from tools.llm_infra.openrouter_router import ACCOUNT_WIDE_MODEL
from tools.llm_infra.quota_state import QuotaStateStore


class CheckTests(unittest.TestCase):
    def test_routing_report_filters_free_models_and_active_blocks(self):
        clock = Clock()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "state"
            store = QuotaStateStore(path, clock=clock)
            store.block("groq", DEFAULT_MODEL_CHAIN[0], "org", 2000, "TPM", clock())
            capture = StringIO()
            config = settings("") | groq_settings("") | openrouter_settings("") | {"OPENROUTER_MODEL": "test/paid"}
            with redirect_stdout(capture):
                code = main(["--env-file", str(Path(tmp) / "absent"), "--state", str(path)],
                            environ=config, clock=clock)
            self.assertEqual(code, 0)
            routing = json.loads(capture.getvalue().split("\nBilling:")[0])["routing"]
            self.assertRegex(routing["policy_sha256"], r"^[a-f0-9]{64}$")
            self.assertTrue(routing["policy_path"].endswith("policy_v1.yaml"))
            self.assertEqual(routing["providers"]["openrouter"], {"configured": True, "eligible": False})
            self.assertEqual(routing["tiers"]["quality_critical"], ["gemini:gemini-3.8-flash"])
            self.assertEqual(routing["tiers"]["utility"], [f"groq:{DEFAULT_MODEL_CHAIN[1]}", "gemini:gemini-3.8-flash"])

    def test_cloudflare_reports_daily_neurons_and_blocks_without_controlling_exit_status(self):
        clock = Clock()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "state"
            store = QuotaStateStore(path, clock=clock)
            ledger = NeuronLedger(path)
            ledger.add("cloudflare", "cloudflare_account_1", utc_day(clock()), 21, clock())
            store.block("cloudflare", "*", "cloudflare_account_1", 2000, "RPD", clock())
            store.block("cloudflare", "*", f"/accounts/{CF_ACCOUNT}/{CF_TOKEN}", 2000, "RPM", clock())
            numbered = cloudflare_settings(CF_ACCOUNT, CF_OTHER_ACCOUNT)
            unnumbered = {name.removesuffix("_1"): value for name, value in numbered.items()}
            for gemini, values, status in [
                ({}, numbered, "READY_FREE_ONLY"),
                ({}, unnumbered, "READY_FREE_ONLY"),
                (settings(""), cloudflare_settings(CF_ACCOUNT) | {"CLOUDFLARE_MODEL": "test/paid"},
                 "BLOCKED_MODEL_NOT_FREE_TIER"),
                (settings(""), cloudflare_settings(CF_ACCOUNT) | {"CLOUDFLARE_PLAN_1": "WORKERS_PAID"},
                 "BLOCKED_NO_ELIGIBLE_KEY"),
                (settings(""), {"CLOUDFLARE_ACCOUNT_ID_1": CF_ACCOUNT}, "CONFIG_ERROR"),
                (settings(""), {"CLOUDFLARE_API_TOKEN_1": CF_TOKEN}, "CONFIG_ERROR"),
                (settings(""), {"CLOUDFLARE_ACCOUNT_ID": CF_ACCOUNT}, "CONFIG_ERROR"),
                (settings(""), {"CLOUDFLARE_API_TOKEN": CF_TOKEN}, "CONFIG_ERROR"),
                (settings(""), dict.fromkeys(numbered.keys() | unnumbered.keys(), ""), None),
            ]:
                with self.subTest(names=sorted(values), status=status):
                    capture = StringIO()
                    with redirect_stdout(capture), patch("tools.llm_infra.cloudflare_transport._urllib_http") as http:
                        result = main(["--env-file", str(Path(tmp) / "absent"), "--state", str(path)],
                                      environ=gemini | values, clock=clock)
                    http.assert_not_called()
                    output = capture.getvalue()
                    for secret in (CF_ACCOUNT, CF_OTHER_ACCOUNT, CF_TOKEN):
                        if secret in values.values():
                            self.assertNotIn(secret, output)
                    self.assertEqual(result, int(not gemini))
                    tree = json.loads(output.split("\nBilling:")[0])
                    self.assertEqual(tree["blocked"], [])
                    if status is None:
                        self.assertNotIn("cloudflare", tree)
                        continue
                    report = tree["cloudflare"]
                    self.assertEqual(report["status"], status)
                    self.assertEqual({block["reason"] for block in report["blocked"]}, {"RPD", "RPM"})
                    if status == "CONFIG_ERROR" and values.keys() & {"CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"}:
                        self.assertIn("slot 1 (unnumbered)", report["error"])
                    if status == "READY_FREE_ONLY":
                        self.assertEqual({block["scope"] for block in report["blocked"]},
                                         {"cloudflare_account_1", "/accounts/[REDACTED]/[REDACTED]"})
                        self.assertEqual(report["neurons_used_today"], {"cloudflare_account_1": 21,
                                                                       "cloudflare_account_2": 0})
                        self.assertEqual((report["keys_configured"], report["key_scopes"]), (2, 2))
                        self.assertEqual(report["model_chain"][0], CF_MODEL)
                        self.assertEqual(len(report["effective_allowlist"]), 6)
                        self.assertEqual(report["daily_neuron_budget"], 9000)
                        self.assertIn("A token cannot show the Workers plan.", report["notice"])

    def test_status_and_secret_safe_diagnostics(self):
        clock = Clock()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "state"
            for config, status in [
                ({}, "WAITING_FOR_USER_CREDENTIALS"),
                (settings("") | {"GEMINI_PROJECT_BILLING_1":"", "GEMINI_KEYS_FREE_TIER_CONFIRMED":"false"}, "BLOCKED_NO_ELIGIBLE_KEY"),
                (settings("") | {"GEMINI_PROJECT_BILLING_1":"BILLING_ENABLED"}, "BLOCKED_NO_ELIGIBLE_KEY"),
                (settings("") | {"GEMINI_FREE_MODELS":"gemini-3.6-flash"}, "BLOCKED_MODEL_NOT_FREE_TIER"),
                (settings("") | {"LLM_ALLOW_PAID":"true"}, "CONFIG_ERROR"),
                (settings("alias"), "READY_FREE_ONLY"),
                ({"GEMINI_API_KEY_1": "test-key-not-real-1"}, "READY_FREE_ONLY")]:
                with self.subTest(status=status):
                    if status == "READY_FREE_ONLY":
                        QuotaStateStore(path, clock=clock).block("gemini","gemini-3.8-flash","alias",2000,"RPM",clock())
                    capture = StringIO()
                    with redirect_stdout(capture):
                        result = main(["--env-file", str(Path(tmp)/"absent")],
                                      environ=config | {"LLM_QUOTA_STATE_PATH":str(path)}, clock=clock)
                    output = capture.getvalue()
                    self.assertNotIn("test-key-not-real", output)
                    self.assertTrue(output.rstrip().endswith(status))
                    self.assertEqual(result, int(status != "READY_FREE_ONLY"))
                    self.assertIn("Billing: not verified by this tool.", output.splitlines()[-2])
                    if result == 0:
                        report = json.loads(output.split("\nBilling:")[0])
                        labeled = bool(config.get("GEMINI_PROJECT_LABEL_1"))
                        self.assertEqual(report["available_now"], int(not labeled))
                        self.assertEqual(report["labels_used"], int(labeled))
                        self.assertEqual(report["model_source"], "configured" if labeled else "default")
                        if not labeled:
                            self.assertEqual(report["model_chain"], ["gemini-3.8-flash", "gemini-3.6-flash"])
                        self.assertFalse(report["billing_verified_by_system"])
                        self.assertIn("1970-01-01T00:33:20Z", output)
                        self.assertIn("application limit only", output)
                    else:
                        self.assertFalse(path.exists())

    def test_groq_report_status_blocks_and_redaction_leave_gemini_exit_status(self):
        model = DEFAULT_MODEL_CHAIN[0]
        clock = Clock()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "state"
            store = QuotaStateStore(path, clock=clock)
            store.block("groq", model, "org", 2000, "TPD", clock())
            store.block("groq", model, GROQ_TEST_KEY, 2000, "RPD", clock())
            store.block("gemini", "gemini-3.8-flash", "gemini", 2000, "RPM", clock())
            for gemini, changes, groq_status in [
                ({}, groq_settings("", "", "") | {"GROQ_API_KEY_9": GROQ_TEST_KEY}, "READY_FREE_ONLY"),
                (settings("gemini"), {"GROQ_FREE_MODELS": f"{model},preview", "GROQ_MODEL": "preview"},
                 "BLOCKED_MODEL_NOT_FREE_TIER"),
                (settings("gemini"), {"GROQ_KEYS_FREE_PLAN_CONFIRMED": "false"}, "BLOCKED_NO_ELIGIBLE_KEY"),
                (settings("gemini"), {"GROQ_ORG_LABEL_1": GROQ_TEST_KEY}, "CONFIG_ERROR"),
                (settings("gemini"), groq_settings("", "") | {"GROQ_ORG_PLAN_2": "PAID_PLAN"}, "CONFIG_ERROR"),
            ]:
                with self.subTest(groq_status=groq_status):
                    capture = StringIO()
                    environ = groq_settings("") | gemini | changes
                    with redirect_stdout(capture):
                        result = main(["--env-file", str(Path(tmp) / "absent"), "--state", str(path)],
                                      environ=environ, clock=clock)
                    output = capture.getvalue()
                    self.assertNotIn(GROQ_TEST_KEY, output)
                    self.assertNotIn("test-key-not-real-1", output)
                    self.assertEqual(result, int(not gemini))
                    self.assertTrue(output.rstrip().endswith("READY_FREE_ONLY" if gemini
                                                             else "WAITING_FOR_USER_CREDENTIALS"))
                    tree = json.loads(output.split("\nBilling:")[0])
                    groq = tree["groq"]
                    self.assertEqual(groq["status"], groq_status)
                    self.assertEqual({b["scope"] for b in groq["blocked"]}, {"org", "[REDACTED]"})
                    self.assertEqual([b["scope"] for b in tree["blocked"]], ["gemini"])
                    if groq_status == "READY_FREE_ONLY":
                        self.assertEqual((groq["keys_configured"], groq["duplicates_dropped"], groq["key_scopes"],
                                          groq["labels_used"]), (4, 1, 1, 0))
                        self.assertEqual(groq["model_chain"], list(DEFAULT_MODEL_CHAIN))
                        self.assertEqual(groq["model_source"], "default")
                        self.assertEqual(groq["plan_status_counts"]["FREE_PLAN_CONFIRMED"], 3)
                        self.assertIn("An API key cannot show the Groq plan", groq["notice"])
                    elif groq_status == "BLOCKED_MODEL_NOT_FREE_TIER":
                        self.assertEqual(groq["effective_allowlist"], [model])
                        self.assertEqual(groq["ignored_models"], ["preview"])

    def test_openrouter_status_counts_blocks_and_redaction_leave_gemini_exit_status(self):
        clock = Clock()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "state"
            store = QuotaStateStore(path, clock=clock)
            store.block("openrouter", ACCOUNT_WIDE_MODEL, "openrouter_account", 2000, "RPM", clock())
            store.block("openrouter", ACCOUNT_WIDE_MODEL, OPENROUTER_TEST_KEY, 2000, "RPD", clock())
            store.block("groq", DEFAULT_MODEL_CHAIN[0], "org", 2000, "RPM", clock())
            for gemini, changes, status in [
                ({}, {"OPENROUTER_API_KEY_9": OPENROUTER_TEST_KEY, "OPENROUTER_DATA_COLLECTION": "deny"},
                 "READY_FREE_ONLY"),
                (settings(""), {"OPENROUTER_MODEL": "test/paid", "OPENROUTER_FREE_MODELS": OPENROUTER_MODEL},
                 "BLOCKED_MODEL_NOT_FREE_TIER"),
                (settings(""), {"OPENROUTER_ACCOUNT_LABEL_1": OPENROUTER_TEST_KEY}, "CONFIG_ERROR"),
                (settings(""), {"OPENROUTER_API_KEY_1": ""}, None),
            ]:
                with self.subTest(openrouter_status=status):
                    capture = StringIO()
                    with redirect_stdout(capture):
                        result = main(["--env-file", str(Path(tmp) / "absent"), "--state", str(path)],
                                      environ=gemini | groq_settings("") | openrouter_settings("") | changes, clock=clock)
                    output = capture.getvalue()
                    self.assertNotIn(OPENROUTER_TEST_KEY, output)
                    self.assertNotIn(GROQ_TEST_KEY, output)
                    self.assertEqual(result, int(not gemini))
                    tree = json.loads(output.split("\nBilling:")[0])
                    self.assertEqual(tree["groq"]["status"], "READY_FREE_ONLY")
                    if status is None:
                        self.assertNotIn("openrouter", tree)
                        continue
                    report = tree["openrouter"]
                    self.assertEqual(report["status"], status)
                    self.assertEqual({block["scope"] for block in report["blocked"]},
                                     {"openrouter_account", "[REDACTED]"})
                    if status == "READY_FREE_ONLY":
                        self.assertEqual((report["keys_configured"], report["keys_eligible"],
                                          report["duplicates_dropped"], report["key_scopes"]), (2, 1, 1, 1))
                        self.assertEqual(report["model_chain"], ["openrouter/free"])
                        self.assertEqual(report["data_collection"], "deny")
                        self.assertIn(":free", report["free_model_rule"])
