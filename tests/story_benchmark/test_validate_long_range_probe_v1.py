import unittest
import yaml
import json
import tempfile
import os
from pathlib import Path
from tools.story_benchmark.validate_long_range_probe_v1 import validate_probes, validate_freeze_integrity

class TestValidateLongRangeProbeV1(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.probes_path = Path(self.test_dir.name) / "probes.yaml"
        self.chunks_path = Path(self.test_dir.name) / "chunks.jsonl"
        self.freeze_path = Path(self.test_dir.name) / "freeze.yaml"
        
        # Write dummy chunks
        with open(self.chunks_path, "w", encoding="utf-8") as f:
            for i in range(1, 6):
                f.write(json.dumps({"chunk_id": f"ch00{i}_c001", "chapter_number": i}) + "\n")
                
        self.valid_probe_base = {
            "probe_id": "P_TEST",
            "category": "CHRONOLOGY",
            "question": "Q",
            "expected_answer": "A",
            "expected_facts": ["F"],
            "difficulty_notes": "N",
            "cutoff_chapter": 3,
            "required_evidence_chunk_ids": ["ch001_c001", "ch002_c001"],
            "supporting_evidence_chunk_ids": [],
            "earliest_required_chapter": 1,
            "latest_required_chapter": 2,
            "chapter_span": 2,
            "requires_multi_chunk": True,
            "requires_multi_chapter": True,
            "forbidden_future_chapters": [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30]
        }
        
        self.categories = ["CHRONOLOGY", "RELATIONSHIP_PROGRESSION", "CALLBACK", "TEMPORAL_STATE", "SPOILER_BOUNDARY"]
        
    def tearDown(self):
        self.test_dir.cleanup()
        
    def write_probes(self, probes_list):
        with open(self.probes_path, "w", encoding="utf-8") as f:
            yaml.dump({"probes": probes_list}, f)
            
    def get_valid_15_probes(self):
        probes = []
        for i, cat in enumerate(self.categories):
            for j in range(3):
                p = self.valid_probe_base.copy()
                p["probe_id"] = f"P_{cat}_{j}"
                p["category"] = cat
                if cat == "SPOILER_BOUNDARY":
                    p["cutoff_chapter"] = 2
                    p["required_evidence_chunk_ids"] = ["ch001_c001"]
                    p["earliest_required_chapter"] = 1
                    p["latest_required_chapter"] = 1
                    p["chapter_span"] = 1
                    p["requires_multi_chunk"] = False
                    p["requires_multi_chapter"] = False
                    p["forbidden_future_chapters"] = list(range(3, 31))
                probes.append(p)
        return probes
        
    def test_valid_minimal(self):
        probes = self.get_valid_15_probes()
        self.write_probes(probes)
        res = validate_probes(str(self.probes_path), str(self.chunks_path))
        self.assertTrue(res["pass"], f"Should pass: {res['issues']}")
        
    def test_wrong_category_distribution(self):
        probes = self.get_valid_15_probes()
        probes[0]["category"] = "CALLBACK" # Now 4 CALLBACK, 2 CHRONOLOGY
        self.write_probes(probes)
        res = validate_probes(str(self.probes_path), str(self.chunks_path))
        self.assertFalse(res["pass"])
        self.assertTrue(any("Category CHRONOLOGY has 2" in i for i in res["issues"]))
        
    def test_supporting_evidence_after_cutoff(self):
        probes = self.get_valid_15_probes()
        probes[0]["supporting_evidence_chunk_ids"] = ["ch004_c001"]
        self.write_probes(probes)
        res = validate_probes(str(self.probes_path), str(self.chunks_path))
        self.assertFalse(res["pass"])
        self.assertTrue(any("Supporting evidence chapter 4 > cutoff 3" in i for i in res["issues"]))
        
    def test_duplicate_chunk_inside_required_list(self):
        probes = self.get_valid_15_probes()
        probes[0]["required_evidence_chunk_ids"] = ["ch001_c001", "ch001_c001"]
        self.write_probes(probes)
        res = validate_probes(str(self.probes_path), str(self.chunks_path))
        self.assertFalse(res["pass"])
        self.assertTrue(any("Duplicate chunk in required list" in i for i in res["issues"]))
        
    def test_duplicate_chunk_inside_supporting_list(self):
        probes = self.get_valid_15_probes()
        probes[0]["supporting_evidence_chunk_ids"] = ["ch002_c001", "ch002_c001"]
        self.write_probes(probes)
        res = validate_probes(str(self.probes_path), str(self.chunks_path))
        self.assertFalse(res["pass"])
        self.assertTrue(any("Duplicate chunk in supporting list" in i for i in res["issues"]))
        
    def test_required_supporting_intersection(self):
        probes = self.get_valid_15_probes()
        probes[0]["supporting_evidence_chunk_ids"] = ["ch001_c001"]
        self.write_probes(probes)
        res = validate_probes(str(self.probes_path), str(self.chunks_path))
        self.assertFalse(res["pass"])
        self.assertTrue(any("Intersection" in i for i in res["issues"]))
        
    def test_blank_question(self):
        probes = self.get_valid_15_probes()
        probes[0]["question"] = ""
        self.write_probes(probes)
        res = validate_probes(str(self.probes_path), str(self.chunks_path))
        self.assertFalse(res["pass"])
        
    def test_incomplete_forbidden_future_chapters(self):
        probes = self.get_valid_15_probes()
        probes[0]["forbidden_future_chapters"] = [4, 5]
        self.write_probes(probes)
        res = validate_probes(str(self.probes_path), str(self.chunks_path))
        self.assertFalse(res["pass"])
        self.assertTrue(any("forbidden_future_chapters mismatch" in i for i in res["issues"]))
        
    def test_spoiler_boundary_with_cutoff_30(self):
        probes = self.get_valid_15_probes()
        p = probes[-1]
        p["cutoff_chapter"] = 30
        p["forbidden_future_chapters"] = []
        self.write_probes(probes)
        res = validate_probes(str(self.probes_path), str(self.chunks_path))
        self.assertFalse(res["pass"])
        self.assertTrue(any("SPOILER_BOUNDARY probe must have cutoff_chapter < 30" in i for i in res["issues"]))
        
    def test_freeze_metadata_count_mismatch(self):
        probes = self.get_valid_15_probes()
        self.write_probes(probes)
        
        import hashlib
        with open(self.probes_path, "rb") as f:
            psha = hashlib.sha256(f.read()).hexdigest()
        with open(self.chunks_path, "rb") as f:
            csha = hashlib.sha256(f.read()).hexdigest()
            
        freeze_data = {
            "probe_file_sha256": psha,
            "chunks_jsonl_sha256": csha,
            "benchmark_id": "LONG_RANGE_PROBE_V1",
            "benchmark_version": 1,
            "corpus_fingerprint_sha256": "7f9bb8106d6d50acd2b3760738c0b8040f36ab547c2d2f7eade1ca0b9a827ff8",
            "passage_contract_id": "OTONARI_LOCAL_PASSAGE_V1",
            "segmentation_version": "PARAGRAPH_PACK_V1",
            "probe_count": 999, # mismatch
            "per_category_counts": {c: 3 for c in self.categories},
            "multi_chunk_probe_count": 12,
            "multi_chapter_probe_count": 12,
            "span_ge_5_chapter_probe_count": 0,
            "span_ge_10_chapter_probe_count": 0,
            "minimum_chapter_span": 1,
            "maximum_chapter_span": 2
        }
        with open(self.freeze_path, "w", encoding="utf-8") as f:
            yaml.dump(freeze_data, f)
            
        ok, iss = validate_freeze_integrity(str(self.freeze_path), str(self.probes_path), str(self.chunks_path))
        self.assertFalse(ok)
        self.assertTrue(any("Metric probe_count mismatch" in i for i in iss))
        
    def test_freeze_probe_sha_mismatch(self):
        probes = self.get_valid_15_probes()
        self.write_probes(probes)
        
        freeze_data = {
            "probe_file_sha256": "wrong_sha"
        }
        with open(self.freeze_path, "w", encoding="utf-8") as f:
            yaml.dump(freeze_data, f)
            
        ok, iss = validate_freeze_integrity(str(self.freeze_path), str(self.probes_path), str(self.chunks_path))
        self.assertFalse(ok)
        self.assertTrue(any("Probe SHA mismatch" in i for i in iss))

if __name__ == "__main__":
    unittest.main()
