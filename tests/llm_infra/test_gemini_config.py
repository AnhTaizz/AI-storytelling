from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fixtures import settings
from tools.llm_infra.gemini_config import load_routing_config
from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError, UNKNOWN_PROJECT_LABEL as UNKNOWN


class ConfigTests(unittest.TestCase):
    def test_merge_then_deduplicate_and_keep_unlabeled_keys_separate(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings"
            path.write_text("GEMINI_MODEL=file-model\nGEMINI_API_KEY_9=test-key-not-real-1\n"
                            "GEMINI_PROJECT_LABEL_9=discarded\n", encoding="utf-8")
            cfg = load_routing_config(path, settings("", ""))
            self.assertEqual(cfg.model, "gemini-3.8-flash")
            self.assertEqual(cfg.duplicates_dropped, 1)
            self.assertEqual([(c.slot_id,c.group_id) for c in cfg.credentials],
                             [("gemini_slot_1", f"{UNKNOWN}:gemini_slot_1"), ("gemini_slot_2", f"{UNKNOWN}:gemini_slot_2")])
            with self.assertRaisesRegex(GeminiConfigError, "credential material"):
                load_routing_config(path, settings("") | {"GEMINI_FREE_MODELS":"test-key-not-real-1"})
