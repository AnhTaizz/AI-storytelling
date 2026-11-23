from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fixtures import settings
from tools.llm_infra.gemini_config import load_routing_config
from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError, UNKNOWN_PROJECT_LABEL as UNKNOWN


class ConfigTests(unittest.TestCase):
    def test_merge_then_deduplicate_and_allow_one_unlabeled_key(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings"
            path.write_text("GEMINI_MODEL=file-model\nGEMINI_API_KEY_9=test-key-not-real-1\n"
                            "GEMINI_PROJECT_LABEL_9=discarded\n", encoding="utf-8")
            cfg = load_routing_config(path, settings(""))
            self.assertEqual(cfg.model, "model-a")
            self.assertEqual(cfg.duplicates_dropped, 1)
            self.assertEqual([(c.slot_id,c.group_id) for c in cfg.credentials],
                             [("gemini_slot_1", f"{UNKNOWN}:gemini_slot_1")])
            with self.assertRaisesRegex(GeminiConfigError, "credential material"):
                load_routing_config(path, settings("") | {"GEMINI_FREE_MODELS":"test-key-not-real-1"})

    def test_multiple_credentials_require_project_labels(self):
        for labels, missing in [(("", ""), "1, 2"), (("p", " "), "2")]:
            with self.subTest(labels=labels), TemporaryDirectory() as tmp:
                with self.assertRaisesRegex(GeminiConfigError, "^PROJECT_LABEL_REQUIRED:") as error:
                    load_routing_config(Path(tmp) / "absent", settings(*labels))
                message = str(error.exception)
                self.assertIn("slots " + missing + ".", message)
                self.assertIn("AI Studio API keys page", message)
                self.assertNotIn("test-key-not-real", message)
