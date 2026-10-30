"""Which M4 checks are sensitive to CRLF/LF checkouts, shown with temporary copies only.

No tracked file is modified: CRLF copies are written to a temporary directory and the
modules under test are pointed at them with ``mock.patch``.
"""
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixture_builder as fx  # noqa: E402
from p3_v1_1_offline_support import oracle_case  # noqa: E402

from tools.story_extraction import draft_compiler_v1, draft_compiler_v1_1  # noqa: E402
from tools.story_extraction import draft_v1_1_schema_bundle_v1 as bundle_module  # noqa: E402
from tools.story_extraction import m4_draft_v1_1_candidate_p3_v1 as candidate  # noqa: E402

V1_SCHEMA = REPO / "schemas/story_extraction/story_extraction_draft_v1.schema.json"
V1_1_SCHEMA = REPO / "schemas/story_extraction/story_extraction_draft_v1_1.schema.json"
V1_COMPILER = REPO / "tools/story_extraction/draft_compiler_v1.py"
RECORDED_V1_SCHEMA_SHA256 = "498edf8dba8d45b80380a180d1383787f5c0e4ecea5060254883cc27c7d83e80"
RECORDED_V1_COMPILER_SHA256 = "bcd15328cefafe86dd8e686fb35a155b2cb2c261b20017486ed106e85371d836"


def lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def crlf(data: bytes) -> bytes:
    return lf(data).replace(b"\n", b"\r\n")


class LineEndingSensitivityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def crlf_copy(self, path: Path) -> Path:
        target = self.root / path.name
        target.write_bytes(crlf(path.read_bytes()))
        return target

    def test_raw_byte_hash_is_sensitive_content_hash_is_not(self):
        copy = self.crlf_copy(V1_1_SCHEMA)
        original, converted = candidate.file_hash_record(V1_1_SCHEMA), candidate.file_hash_record(copy)
        self.assertNotEqual(hashlib.sha256(copy.read_bytes()).hexdigest(),
                            hashlib.sha256(lf(V1_1_SCHEMA.read_bytes())).hexdigest())
        self.assertEqual(original["content_sha256_lf"], converted["content_sha256_lf"])
        self.assertEqual(original["git_blob_sha1_lf"], converted["git_blob_sha1_lf"])
        self.assertEqual(converted["observed_line_endings"], "CRLF")

    def test_historical_v1_locks_are_crlf_raw_hashes_of_unchanged_content(self):
        """D1: the recorded hashes equal the CRLF form of today's content, not the LF form."""
        for path, recorded in ((V1_SCHEMA, RECORDED_V1_SCHEMA_SHA256),
                               (V1_COMPILER, RECORDED_V1_COMPILER_SHA256)):
            with self.subTest(path=path.name):
                content = path.read_bytes()
                self.assertEqual(hashlib.sha256(crlf(content)).hexdigest(), recorded)
                self.assertNotEqual(hashlib.sha256(lf(content)).hexdigest(), recorded)

    def test_prompt_material_is_line_ending_insensitive(self):
        before = candidate.prompt_hashes()
        with mock.patch.multiple(
            candidate,
            SYSTEM_PREAMBLE_PATH=self.crlf_copy(candidate.SYSTEM_PREAMBLE_PATH),
            USER_TEMPLATE_PATH=self.crlf_copy(candidate.USER_TEMPLATE_PATH),
            REPAIR_USER_TEMPLATE_PATH=self.crlf_copy(candidate.REPAIR_USER_TEMPLATE_PATH),
            PREDICATE_REGISTRY_PATH=self.crlf_copy(candidate.PREDICATE_REGISTRY_PATH),
        ), mock.patch.multiple(
            bundle_module,
            V1_SCHEMA_PATH=self.crlf_copy(V1_SCHEMA),
            V1_1_SCHEMA_PATH=self.crlf_copy(V1_1_SCHEMA),
        ):
            self.assertEqual(candidate.prompt_hashes(), before)

    def test_compiler_behaviour_is_line_ending_insensitive(self):
        case, draft = oracle_case("c17_conceal_convey")
        expected = draft_compiler_v1_1.compile_story_extraction_draft_v1_1(deepcopy(draft),
                                                                          case.context)
        v1_copy, v1_1_copy = self.crlf_copy(V1_SCHEMA), self.crlf_copy(V1_1_SCHEMA)
        with mock.patch.object(draft_compiler_v1, "SCHEMA_PATH", v1_copy), \
                mock.patch.object(draft_compiler_v1_1, "SCHEMA_PATH", v1_1_copy), \
                mock.patch.object(draft_compiler_v1_1, "V1_SCHEMA_PATH", v1_copy):
            actual = draft_compiler_v1_1.compile_story_extraction_draft_v1_1(deepcopy(draft),
                                                                            case.context)
        self.assertEqual(candidate.canonical_json_bytes(actual),
                         candidate.canonical_json_bytes(expected))

    def test_source_text_bytes_are_meaningful_and_must_never_be_normalized(self):
        text = "真白は笑った。\n\n遥は窓を開けた。"
        lf_ingestion, _ = fx.ingest_text(text)
        crlf_ingestion, _ = fx.ingest_text(text.replace("\n", "\r\n"))
        self.assertNotEqual(lf_ingestion.fingerprint, crlf_ingestion.fingerprint)
        lf_segments = lf_ingestion.documents[0].segments
        crlf_segments = crlf_ingestion.documents[0].segments
        self.assertNotEqual(lf_segments[-1]["locator"]["char_start"],
                            crlf_segments[-1]["locator"]["char_start"])


if __name__ == "__main__":
    unittest.main()
