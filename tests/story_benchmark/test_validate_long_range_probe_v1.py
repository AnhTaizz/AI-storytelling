import unittest
import yaml
import json
import tempfile
import os
import hashlib
from pathlib import Path
from tools.story_benchmark.validate_long_range_probe_v1 import validate_probes, validate_freeze_integrity

class TestValidateLongRangeProbeV1(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.probes_path = Path(self.test_dir.name) / "probes.yaml"
        self.chunks_path = Path(self.test_dir.name) / "chunks.jsonl"
        self.freeze_path = Path(self.test_dir.name) / "freeze.yaml"
        
        # Write dummy chunks for 30 chapters
        with open(self.chunks_path, "w", encoding="utf-8") as f:
            for i in range(1, 31):
                f.write(json.dumps({"chunk_id": f"ch{i:03d}_c001", "chapter_number": i}) + "\n")
                
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
                p = {
                    "probe_id": f"P_{cat}_{j}",
                    "category": cat,
                    "question": "Q",
                    "expected_answer": "A",
                    "expected_facts": ["F"],
                    "difficulty_notes": "N",
                    "cutoff_chapter": 30,
                    "supporting_evidence_chunk_ids": [],
                    "requires_multi_chunk": True,
                    "requires_multi_chapter": True,
                    "forbidden_future_chapters": []
                }
                
                if cat == "SPOILER_BOUNDARY":
                    p["cutoff_chapter"] = 15
                    p["required_evidence_chunk_ids"] = ["ch001_c001", "ch010_c001"] # span 10
                    p["earliest_required_chapter"] = 1
                    p["latest_required_chapter"] = 10
                    p["chapter_span"] = 10
                    p["forbidden_future_chapters"] = list(range(16, 31))
                else:
                    p["required_evidence_chunk_ids"] = ["ch001_c001", "ch011_c001"] # span 11
                    p["earliest_required_chapter"] = 1
                    p["latest_required_chapter"] = 11
                    p["chapter_span"] = 11
                    
                probes.append(p)
        return probes
        
    def test_valid_minimal(self):
        probes = self.get_valid_15_probes()
        self.write_probes(probes)
        res = validate_probes(str(self.probes_path), str(self.chunks_path))
        self.assertTrue(res["pass"], f"Should pass: {res['issues']}")
        
    # --- Quality Gate Tests (from FIX2) ---
    def test_fail_multi_chunk_gate(self):
        probes = self.get_valid_15_probes()
        for i in range(6):
            probes[i]["required_evidence_chunk_ids"] = ["ch001_c001"]
            probes[i]["earliest_required_chapter"] = 1
            probes[i]["latest_required_chapter"] = 1
            probes[i]["chapter_span"] = 1
            probes[i]["requires_multi_chunk"] = False
            probes[i]["requires_multi_chapter"] = False
        self.write_probes(probes)
        res = validate_probes(str(self.probes_path), str(self.chunks_path))
        self.assertFalse(res["pass"])
        self.assertTrue(any("multi_chunk_probe_count" in i for i in res["issues"]))
        
    def test_fail_multi_chap_gate(self):
        probes = self.get_valid_15_probes()
        # Need multiple chunks in the same chapter to preserve multi_chunk=True but multi_chapter=False
        with open(self.chunks_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"chunk_id": "ch001_c002", "chapter_number": 1}) + "\n")
                
        for i in range(6):
            probes[i]["required_evidence_chunk_ids"] = ["ch001_c001", "ch001_c002"]
            probes[i]["earliest_required_chapter"] = 1
            probes[i]["latest_required_chapter"] = 1
            probes[i]["chapter_span"] = 1
            probes[i]["requires_multi_chunk"] = True
            probes[i]["requires_multi_chapter"] = False
            
        self.write_probes(probes)
        res = validate_probes(str(self.probes_path), str(self.chunks_path))
        self.assertFalse(res["pass"])
        self.assertTrue(any("multi_chapter_probe_count" in i for i in res["issues"]))
        
    def test_fail_span_ge_5_gate(self):
        probes = self.get_valid_15_probes()
        for i in range(6):
            probes[i]["required_evidence_chunk_ids"] = ["ch001_c001", "ch004_c001"]
            probes[i]["earliest_required_chapter"] = 1
            probes[i]["latest_required_chapter"] = 4
            probes[i]["chapter_span"] = 4
            
        self.write_probes(probes)
        res = validate_probes(str(self.probes_path), str(self.chunks_path))
        self.assertFalse(res["pass"])
        self.assertTrue(any("span_ge_5_chapter_probe_count" in i for i in res["issues"]))
        
    def test_fail_span_ge_10_gate(self):
        probes = self.get_valid_15_probes()
        for i in range(15):
            probes[i]["required_evidence_chunk_ids"] = ["ch001_c001", "ch009_c001"]
            probes[i]["earliest_required_chapter"] = 1
            probes[i]["latest_required_chapter"] = 9
            probes[i]["chapter_span"] = 9
            
        self.write_probes(probes)
        res = validate_probes(str(self.probes_path), str(self.chunks_path))
        self.assertFalse(res["pass"])
        self.assertTrue(any("span_ge_10_chapter_probe_count" in i for i in res["issues"]))
        
    # --- Regression Tests (restored from FIX1) ---
    def test_wrong_category_distribution(self):
        probes = self.get_valid_15_probes()
        probes[0]["category"] = "CALLBACK" 
        self.write_probes(probes)
        res = validate_probes(str(self.probes_path), str(self.chunks_path))
        self.assertFalse(res["pass"])
        
    def test_supporting_evidence_after_cutoff(self):
        probes = self.get_valid_15_probes()
        probes[0]["cutoff_chapter"] = 10
        probes[0]["forbidden_future_chapters"] = list(range(11, 31))
        # Supporting evidence in ch011
        probes[0]["supporting_evidence_chunk_ids"] = ["ch011_c001"]
        # Make sure req is valid
        probes[0]["required_evidence_chunk_ids"] = ["ch001_c001", "ch010_c001"]
        probes[0]["earliest_required_chapter"] = 1
        probes[0]["latest_required_chapter"] = 10
        probes[0]["chapter_span"] = 10
        
        self.write_probes(probes)
        res = validate_probes(str(self.probes_path), str(self.chunks_path))
        self.assertFalse(res["pass"])
        self.assertTrue(any("Supporting evidence chapter 11 > cutoff 10" in i for i in res["issues"]))

    def test_duplicate_chunk_inside_required_list(self):
        probes = self.get_valid_15_probes()
        probes[0]["required_evidence_chunk_ids"] = ["ch001_c001", "ch001_c001", "ch011_c001"]
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
        p = probes[-1] # SPOILER_BOUNDARY probe has cutoff 15
        p["forbidden_future_chapters"] = [16, 17] # missing 18..30
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
        
    def test_duplicate_probe_id(self):
        probes = self.get_valid_15_probes()
        probes[1]["probe_id"] = probes[0]["probe_id"]
        self.write_probes(probes)
        res = validate_probes(str(self.probes_path), str(self.chunks_path))
        self.assertFalse(res["pass"])
        self.assertTrue(any("Duplicate probe_id" in i for i in res["issues"]))
        
    def test_invalid_category(self):
        probes = self.get_valid_15_probes()
        probes[0]["category"] = "INVALID"
        self.write_probes(probes)
        res = validate_probes(str(self.probes_path), str(self.chunks_path))
        self.assertFalse(res["pass"])
        
    def test_missing_chunk_reference(self):
        probes = self.get_valid_15_probes()
        probes[0]["required_evidence_chunk_ids"] = ["ch001_c001", "ch099_c001"] # doesn't exist
        self.write_probes(probes)
        res = validate_probes(str(self.probes_path), str(self.chunks_path))
        self.assertFalse(res["pass"])
        self.assertTrue(any("not found in chunks.jsonl" in i for i in res["issues"]))
        
    def test_required_evidence_after_cutoff(self):
        probes = self.get_valid_15_probes()
        probes[0]["cutoff_chapter"] = 10
        probes[0]["forbidden_future_chapters"] = list(range(11, 31))
        # But req says 11
        probes[0]["required_evidence_chunk_ids"] = ["ch001_c001", "ch011_c001"]
        self.write_probes(probes)
        res = validate_probes(str(self.probes_path), str(self.chunks_path))
        self.assertFalse(res["pass"])
        self.assertTrue(any("Required evidence chapter 11 > cutoff 10" in i for i in res["issues"]))
        
    def test_incorrect_chapter_span(self):
        probes = self.get_valid_15_probes()
        probes[0]["chapter_span"] = 99
        self.write_probes(probes)
        res = validate_probes(str(self.probes_path), str(self.chunks_path))
        self.assertFalse(res["pass"])
        self.assertTrue(any("chapter_span mismatch" in i for i in res["issues"]))
        
    def test_incorrect_requires_multi_chapter_flag(self):
        probes = self.get_valid_15_probes()
        probes[0]["requires_multi_chapter"] = False
        self.write_probes(probes)
        res = validate_probes(str(self.probes_path), str(self.chunks_path))
        self.assertFalse(res["pass"])
        self.assertTrue(any("requires_multi_chapter mismatch" in i for i in res["issues"]))

    # --- Freeze tests ---
    def test_freeze_metadata_count_mismatch(self):
        probes = self.get_valid_15_probes()
        self.write_probes(probes)
        
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
            "multi_chunk_probe_count": 15,
            "multi_chapter_probe_count": 15,
            "span_ge_5_chapter_probe_count": 15,
            "span_ge_10_chapter_probe_count": 15,
            "minimum_chapter_span": 10,
            "maximum_chapter_span": 11
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
