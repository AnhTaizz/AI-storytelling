"""Synthetic tests for V1.1 projection and content-agnostic DEV3 sealing."""
from pathlib import Path
import sys
import unittest
import zipfile
from io import BytesIO
import yaml


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixture_builder as fx

from tools.story_extraction.dev3_seal_v1 import (
    build_blindness_manifest,
    check_input_zero_gold,
    check_package_separation,
    deterministic_zip_bytes,
    sha256_bytes,
)
from tools.story_extraction.draft_compiler_v1 import COLLECTIONS, DraftCompilerContext
from tools.story_extraction.draft_compiler_v1_1 import compile_story_extraction_draft_v1_1
from tools.story_extraction.draft_coverage_v1 import canonical_representation_signature
from tools.story_extraction.draft_coverage_v1_1 import canonical_gold_to_draft_v1_1


class Dev3SealV1Tests(unittest.TestCase):
    def test_projection_round_trips_all_synthetic_graphs_without_mention_links(self):
        for case_id in fx.CASES:
            with self.subTest(case_id=case_id):
                ingestion, base, gold = fx.build(case_id)
                scope = gold["scope"]
                context = DraftCompilerContext(
                    base, scope["passage_inputs"], scope["as_of_position"], scope["profile_id"],
                    "dev3-projection-test", "v1.1", case_id, ingestion,
                )
                draft, mapping = canonical_gold_to_draft_v1_1(gold, context)
                self.assertTrue(all("evidence_handle" not in item for item in draft["mentions"]))
                compiled = compile_story_extraction_draft_v1_1(draft, context)
                reverse = {
                    record["id"]: next(
                        handle for handle in mapping.values() if record["id"].endswith("-" + handle)
                    )
                    for collection in COLLECTIONS.values()
                    for record in compiled["candidate_records"][collection]
                }
                reverse.update({rid: handle for rid, handle in mapping.items() if "_EXISTING_" in handle})
                self.assertEqual(
                    canonical_representation_signature(gold, mapping),
                    canonical_representation_signature(compiled, reverse),
                )

    def test_deterministic_zip_has_sorted_fixed_members(self):
        entries = {"z.json": b"{}\n", "a.txt": b"alpha\n"}
        first = deterministic_zip_bytes(entries)
        second = deterministic_zip_bytes(dict(reversed(list(entries.items()))))
        self.assertEqual(first, second)
        with zipfile.ZipFile(BytesIO(first)) as archive:
            self.assertEqual(archive.namelist(), ["a.txt", "z.json"])
            self.assertTrue(all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist()))

    def test_input_gold_scan_and_package_separation_fail_closed(self):
        clean = {"input_manifest.json": b'{"artifact":"INPUT"}\n'}
        dirty = {"case.json": b'{"gold_status":"AGENT_DRAFT_GOLD"}\n'}
        self.assertEqual(check_input_zero_gold(clean), [])
        self.assertTrue(check_input_zero_gold(dirty))
        self.assertTrue(check_package_separation(clean, clean, "a" * 64, "a" * 64))

    def test_blindness_manifest_forbids_extractor_gold_access(self):
        manifest = build_blindness_manifest("a" * 64, "b" * 64)
        self.assertEqual(manifest["extractor_access"], {"input": True, "gold": False})
        self.assertTrue(manifest["gold_may_be_opened_after"]["predictions_locked_and_hashed"])
        self.assertEqual(sha256_bytes(b"x"), sha256_bytes(b"x"))

    def test_public_seal_record_is_hash_bound_and_blind(self):
        path = REPO / "benchmarks/m4_extraction/M4_04B3E_FRESH_DEV3_SEAL_RESULT.yaml"
        record = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.assertEqual(record["freshness"]["original_mini_narratives"], 10)
        self.assertEqual(record["offline_v1_1_gate"]["representable"], "10/10 PASS")
        self.assertFalse(record["private_seal"]["input_package"]["contains_gold"])
        self.assertEqual(record["private_seal"]["shared_member_names"], 0)
        self.assertRegex(record["private_seal"]["input_package"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(record["private_seal"]["gold_package"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertFalse(record["boundaries"]["holdout_opened"])
        self.assertFalse(record["boundaries"]["dev2_private_authoring_inputs_opened"])


if __name__ == "__main__":
    unittest.main()
