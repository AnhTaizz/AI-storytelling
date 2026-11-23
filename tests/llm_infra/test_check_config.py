from contextlib import redirect_stdout
from io import StringIO
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
                (settings("") | {"GEMINI_PROJECT_BILLING_1":""}, "BLOCKED_NO_CONFIRMED_FREE_PROJECT"),
                (settings("") | {"GEMINI_PROJECT_BILLING_1":"BILLING_ENABLED"}, "BLOCKED_NO_CONFIRMED_FREE_PROJECT"),
                (settings("") | {"GEMINI_FREE_MODELS":"model-b"}, "BLOCKED_MODEL_NOT_CONFIRMED_FREE"),
                (settings("") | {"LLM_ALLOW_PAID":"true"}, "CONFIG_ERROR"),
                (settings("alias"), "READY_FREE_ONLY"),
                ({"GEMINI_API_KEY_1": "test-key-not-real-1", "GEMINI_MODEL": "m",
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
                    self.assertTrue(output.rstrip().endswith(status))
                    self.assertEqual(result, int(status != "READY_FREE_ONLY"))
                    if result == 0:
                        self.assertIn("1970-01-01T00:33:20Z", output)
                        self.assertIn("application limit only", output)
                    else:
                        self.assertFalse(path.exists())
