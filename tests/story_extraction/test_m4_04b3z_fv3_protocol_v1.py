"""DEC-030 public bindings and protocol pinning."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest import mock

from tools.story_extraction import m4_04b3z_fv3_protocol_v1 as lock


class ProtocolTests(unittest.TestCase):
    def test_canonical_lock_binds_dependencies_and_refuses_drift(self):
        value = lock.build_protocol()
        self.assertEqual(value, lock.build_protocol())
        paths = set(lock.bound_paths())
        self.assertEqual(paths, set(value["public_bindings"]))
        for name in ("quote_resolution", "mention_anchoring", "mention_evidence", "sentence_evidence",
                     "transfer_bounds", "date_anchor", "vocabulary_guard"):
            self.assertIn(f"tools/story_extraction/draft_{name}_v1.py", paths)
        self.assertIn("tools/canonical_story/conformance_v0.py", paths)
        self.assertIn((lock.dev.PROMPT_ROOT / "story_extraction_draft_p4r8_system_v1_1.txt")
                      .relative_to(lock.REPO_ROOT).as_posix(), paths)
        self.assertEqual(value["host_repairs"], ["QR", "AM", "ME", "SE", "TB", "DA", "VG"])
        self.assertEqual(value["case_ids"], [f"fv3-{n:02d}" for n in range(1, 17)])
        self.assertEqual(value["generation"]["temperature"], 0)
        self.assertEqual(value["stop_rules"]["maximum_semantic_jobs"], 32)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.assertEqual(lock.main(["--directory", tmp]), 0)
            path = directory / lock.PROTOCOL_NAME
            digest = lock.file_sha256(path)
            lock.validate_protocol_file(path, digest).assert_unchanged()
            self.assertEqual(lock.main(["--directory", tmp]), 2)
            # Redirect just one public dependency to genuinely different bytes.
            changed = directory / "changed.py"
            changed.write_bytes(b"changed")
            source = lock.REPO_ROOT / "tools/story_extraction/draft_vocabulary_guard_v1.py"
            original = lock.file_sha256
            with mock.patch.object(lock, "file_sha256", side_effect=lambda p: original(changed if p == source else p)):
                with self.assertRaisesRegex(lock.Fv3ProtocolError, "binding mismatch"):
                    lock.validate_protocol_file(path, digest)
            for content in (b"{", b"[]", json.dumps(value).encode(),
                            lock.canonical_json_bytes({**value, "host_repairs": ["ME"]})):
                with self.subTest(content=content[:12]), self.assertRaises(lock.Fv3ProtocolError):
                    path.write_bytes(content)
                    lock.validate_protocol_file(path, lock.sha256_bytes(content))
