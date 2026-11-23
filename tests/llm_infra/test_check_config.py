from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fixtures import Clock, GROQ_TEST_KEY, groq_settings, settings
from tools.llm_infra.check_config import main
from tools.llm_infra.groq_free_models_v1 import DEFAULT_MODEL_CHAIN
from tools.llm_infra.quota_state import QuotaStateStore


class CheckTests(unittest.TestCase):
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
                ({}, {"GROQ_API_KEY_9": GROQ_TEST_KEY}, "READY_FREE_ONLY"),
                (settings("gemini"), {"GROQ_FREE_MODELS": f"{model},preview", "GROQ_MODEL": "preview"},
                 "BLOCKED_MODEL_NOT_FREE_TIER"),
                (settings("gemini"), {"GROQ_KEYS_FREE_PLAN_CONFIRMED": "false"}, "BLOCKED_NO_ELIGIBLE_KEY"),
                (settings("gemini"), {"GROQ_ORG_LABEL_1": GROQ_TEST_KEY}, "CONFIG_ERROR"),
            ]:
                with self.subTest(groq_status=groq_status):
                    capture = StringIO()
                    environ = groq_settings("org") | gemini | changes
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
                                          groq["labels_used"]), (2, 1, 1, 1))
                        self.assertEqual(groq["model_chain"], list(DEFAULT_MODEL_CHAIN))
                        self.assertEqual(groq["model_source"], "default")
                        self.assertEqual(groq["plan_status_counts"]["FREE_PLAN_CONFIRMED"], 1)
                        self.assertIn("An API key cannot show the Groq plan", groq["notice"])
                    elif groq_status == "BLOCKED_MODEL_NOT_FREE_TIER":
                        self.assertEqual(groq["effective_allowlist"], [model])
                        self.assertEqual(groq["ignored_models"], ["preview"])
