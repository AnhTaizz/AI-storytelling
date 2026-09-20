"""
Unit tests for INDEPENDENT_VALIDATION_FIXTURE_V1 validator (TASK M1-30CH-P)
"""
import copy
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from tools.story_benchmark.validate_independent_validation_fixture_v1 import (
    CATEGORIES,
    EXPECTED_PER_CATEGORY,
    EXPECTED_PROBE_COUNT,
    find_privacy_leaks_in_manifest,
    validate_validation_probes,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class TestIndependentValidationFixtureValidator(unittest.TestCase):

    def setUp(self):
        self.probes_path = REPO_ROOT / ".local/story_integration/otonari_30ch/INDEPENDENT_VALIDATION_FIXTURE_V1/draft_probes.yaml"
        self.chunks_path = REPO_ROOT / ".local/story_integration/otonari_30ch/PARAGRAPH_PACK_V1/chunks.jsonl"
        self.orig_path = REPO_ROOT / ".local/story_integration/otonari_30ch/LONG_RANGE_PROBE_V1/probes.yaml"

    def test_real_draft_probes_validation_passes(self):
        res = validate_validation_probes(self.probes_path, self.chunks_path, self.orig_path)
        self.assertTrue(res["pass"], f"Validation failed with issues: {res.get('issues')}")
        m = res["metrics"]
        self.assertEqual(m["probe_count"], EXPECTED_PROBE_COUNT)
        for cat in CATEGORIES:
            self.assertEqual(m["per_category_counts"][cat], EXPECTED_PER_CATEGORY)
        self.assertEqual(m["annotation_status_counts"]["PENDING_REVIEW"], EXPECTED_PROBE_COUNT)
        self.assertEqual(m["multi_chunk_probe_count"], EXPECTED_PROBE_COUNT)

    def test_category_count_mismatch(self):
        with open(self.probes_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # Remove 1 probe from CHRONOLOGY
        probes = [p for p in data["probes"] if p["probe_id"] != "V_CHRONO_01"]
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".yaml", encoding="utf-8") as tf:
            yaml.dump({"probes": probes}, tf)
            tmp_path = Path(tf.name)

        try:
            res = validate_validation_probes(tmp_path, self.chunks_path, self.orig_path)
            self.assertFalse(res["pass"])
            self.assertTrue(any("Expected 25 probes" in issue for issue in res["issues"]))
            self.assertTrue(any("Category CHRONOLOGY has 4 probes" in issue for issue in res["issues"]))
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_invalid_category(self):
        with open(self.probes_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        probes = copy.deepcopy(data["probes"])
        probes[0]["category"] = "INVALID_CATEGORY"
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".yaml", encoding="utf-8") as tf:
            yaml.dump({"probes": probes}, tf)
            tmp_path = Path(tf.name)

        try:
            res = validate_validation_probes(tmp_path, self.chunks_path, self.orig_path)
            self.assertFalse(res["pass"])
            self.assertTrue(any("Invalid category" in issue for issue in res["issues"]))
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_missing_annotation_status(self):
        with open(self.probes_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        probes = copy.deepcopy(data["probes"])
        del probes[0]["annotation_status"]
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".yaml", encoding="utf-8") as tf:
            yaml.dump({"probes": probes}, tf)
            tmp_path = Path(tf.name)

        try:
            res = validate_validation_probes(tmp_path, self.chunks_path, self.orig_path)
            self.assertFalse(res["pass"])
            self.assertTrue(any("Missing annotation_status" in issue for issue in res["issues"]))
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_spoiler_boundary_cutoff_violation(self):
        with open(self.probes_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        probes = copy.deepcopy(data["probes"])
        for p in probes:
            if p["category"] == "SPOILER_BOUNDARY":
                p["cutoff_chapter"] = 30
                break

        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".yaml", encoding="utf-8") as tf:
            yaml.dump({"probes": probes}, tf)
            tmp_path = Path(tf.name)

        try:
            res = validate_validation_probes(tmp_path, self.chunks_path, self.orig_path)
            self.assertFalse(res["pass"])
            self.assertTrue(any("SPOILER_BOUNDARY probe must have cutoff_chapter < 30" in issue for issue in res["issues"]))
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_fewer_than_two_chunks(self):
        with open(self.probes_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        probes = copy.deepcopy(data["probes"])
        probes[0]["required_evidence_chunk_ids"] = [probes[0]["required_evidence_chunk_ids"][0]]
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".yaml", encoding="utf-8") as tf:
            yaml.dump({"probes": probes}, tf)
            tmp_path = Path(tf.name)

        try:
            res = validate_validation_probes(tmp_path, self.chunks_path, self.orig_path)
            self.assertFalse(res["pass"])
            self.assertTrue(any("must require at least 2 chunks" in issue for issue in res["issues"]))
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_overlap_with_original_probe_evidence(self):
        with open(self.probes_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # Load first original probe required evidence
        with open(self.orig_path, "r", encoding="utf-8") as f:
            orig_req = yaml.safe_load(f)["probes"][0]["required_evidence_chunk_ids"]

        probes = copy.deepcopy(data["probes"])
        probes[0]["required_evidence_chunk_ids"] = list(orig_req)
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".yaml", encoding="utf-8") as tf:
            yaml.dump({"probes": probes}, tf)
            tmp_path = Path(tf.name)

        try:
            res = validate_validation_probes(tmp_path, self.chunks_path, self.orig_path)
            self.assertFalse(res["pass"])
            self.assertTrue(any("identical to original probe" in issue for issue in res["issues"]))
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_privacy_leak_scan(self):
        clean_manifest = "status: PREPARED_PENDING_HUMAN_REVIEW\nprobe_count: 25\n"
        self.assertEqual(find_privacy_leaks_in_manifest(clean_manifest), [])

        leak_chunk = "evidence: ch001_c0001"
        self.assertIn("<chunk-id pattern>", find_privacy_leaks_in_manifest(leak_chunk))

        leak_probe = "target probe: V_CHRONO_01"
        self.assertIn("<validation-probe-id pattern>", find_privacy_leaks_in_manifest(leak_probe))

    def test_flexible_probe_count_when_targets_none(self):
        with open(self.probes_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # Slice to 10 probes across arbitrary categories
        probes = data["probes"][:10]
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".yaml", encoding="utf-8") as tf:
            yaml.dump({"probes": probes}, tf)
            tmp_path = Path(tf.name)

        try:
            res = validate_validation_probes(
                tmp_path,
                self.chunks_path,
                self.orig_path,
                expected_probe_count=None,
                expected_per_category=None,
            )
            self.assertTrue(res["pass"], f"Flexible count failed: {res.get('issues')}")
            self.assertEqual(res["metrics"]["probe_count"], 10)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_intra_fixture_duplicate_detection(self):
        # Legacy draft has intra-fixture duplicate V_CALL_02 and V_SPOIL_02
        res = validate_validation_probes(
            self.probes_path,
            self.chunks_path,
            self.orig_path,
            check_intra_fixture_duplicates=True,
        )
        self.assertFalse(res["pass"])
        self.assertTrue(any("Intra-fixture duplicate required evidence set" in issue for issue in res["issues"]))

    def test_revised_draft_probes_validation_passes(self):
        revised_path = REPO_ROOT / ".local/story_integration/otonari_30ch/M1_30CH_P_REPAIR/revised_draft_probes.yaml"
        if revised_path.exists():
            res = validate_validation_probes(
                revised_path,
                self.chunks_path,
                self.orig_path,
                expected_probe_count=18,
                expected_per_category=None,
                check_intra_fixture_duplicates=True,
            )
            self.assertTrue(res["pass"], f"Revised validation failed: {res.get('issues')}")
            self.assertEqual(res["metrics"]["probe_count"], 18)
            self.assertEqual(res["metrics"]["multi_chunk_probe_count"], 18)


if __name__ == "__main__":
    unittest.main()
