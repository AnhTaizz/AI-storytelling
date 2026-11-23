from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import json
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
                (settings("") | {"GEMINI_PROJECT_BILLING_1":""}, "BLOCKED_NO_CONFIRMED_FREE_PROJECT"),
                (settings("") | {"GEMINI_PROJECT_BILLING_1":"BILLING_ENABLED"}, "BLOCKED_NO_CONFIRMED_FREE_PROJECT"),
                (settings("") | {"GEMINI_FREE_MODELS":"model-b"}, "BLOCKED_MODEL_NOT_CONFIRMED_FREE"),
                (settings("") | {"LLM_ALLOW_PAID":"true"}, "CONFIG_ERROR"),
                (settings("") | {"GEMINI_FREE_MODELS": " , "}, "BLOCKED_MODEL_NOT_CONFIRMED_FREE"),
                (settings("p", ""), "BLOCKED_PROJECT_LABEL_REQUIRED"),
                (settings("p", "q") | {"GEMINI_KEYS_FREE_TIER_CONFIRMED": "true"},
                 "BLOCKED_PER_PROJECT_CONFIRMATION_REQUIRED"),
                (settings("alias", "alias", "other") | {"GEMINI_PROJECT_BILLING_1": "",
                                                       "GEMINI_PROJECT_BILLING_3": ""}, "READY_FREE_ONLY"),
                ({"GEMINI_API_KEY_1": "test-key-not-real-1", "GEMINI_MODEL": "m", "GEMINI_FREE_MODELS": "m",
                  "GEMINI_KEYS_FREE_TIER_CONFIRMED": "true"}, "READY_FREE_ONLY")]:
                with self.subTest(status=status):
                    if status == "READY_FREE_ONLY":
                        QuotaStateStore(path, clock=clock).block("gemini","m","alias",2000,"RPM",clock())
                    capture = StringIO()
                    with redirect_stdout(capture):
                        result = main(["--env-file", str(Path(tmp)/"absent")],
                                      environ=config | {"LLM_QUOTA_STATE_PATH":str(path)}, clock=clock)
                    output = capture.getvalue()
                    self.assertNotIn("test-key-not-real", output)
                    lines = output.splitlines()
                    self.assertEqual(lines[-1], "Status: " + status)
                    ready = status == "READY_FREE_ONLY"
                    report = json.loads("\n".join(lines[:-2] if ready else lines[:-1]))
                    self.assertIs(report["billing_verified_by_system"], False)
                    self.assertEqual(report["application_policy"], "PASS" if ready else "BLOCKED")
                    if ready:
                        self.assertEqual(lines[-2], "Billing: owner-attested, not verified by this tool. "
                                         "READY_FREE_ONLY means the application policy passes; "
                                         "it is not a guarantee that Google cannot charge.")
                        if report["project_groups"] == 2:
                            self.assertEqual(report["projects"], [
                                {"project_label": "alias", "slots": [1, 2], "billing_status": "FREE_TIER_CONFIRMED",
                                 "source": "per_project"},
                                {"project_label": "other", "slots": [3], "billing_status": "UNVERIFIED",
                                 "source": "default"}])
                        else:
                            self.assertEqual(report["projects"][0]["source"], "bulk_line")
                    self.assertEqual(result, int(status != "READY_FREE_ONLY"))
                    if result == 0:
                        self.assertIn("1970-01-01T00:33:20Z", output)
                        self.assertIn("application limit only", output)
                    else:
                        self.assertFalse(path.exists())
