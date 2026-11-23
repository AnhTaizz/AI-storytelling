from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fixtures import Clock, settings
from tools.llm_infra.check_config import main
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
