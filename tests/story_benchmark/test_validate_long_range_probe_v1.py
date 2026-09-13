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
                
                # To satisfy gates: we need at least 10 probes with span >= 5, 1 with span >= 10.
                # Let's just make all probes span 10 chapters (e.g. chapter 1 and chapter 10)
                # except for SPOILER_BOUNDARY which needs cutoff < 30.
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
        
    def test_fail_multi_chunk_gate(self):
        probes = self.get_valid_15_probes()
        # Reduce multi_chunk count to 9
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
        # Make them multi_chunk but single chapter
        for i in range(6):
            probes[i]["required_evidence_chunk_ids"] = ["ch001_c001", "ch001_c001"] # Wait, duplicates not allowed.
            # I can't use same chunk, but my mock only has 1 chunk per chapter. Let's add one to chunks.jsonl
            with open(self.chunks_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"chunk_id": "ch001_c002", "chapter_number": 1}) + "\n")
                
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
            probes[i]["required_evidence_chunk_ids"] = ["ch001_c001", "ch004_c001"] # span 4
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
            probes[i]["required_evidence_chunk_ids"] = ["ch001_c001", "ch009_c001"] # span 9
            probes[i]["earliest_required_chapter"] = 1
            probes[i]["latest_required_chapter"] = 9
            probes[i]["chapter_span"] = 9
            
        self.write_probes(probes)
        res = validate_probes(str(self.probes_path), str(self.chunks_path))
        self.assertFalse(res["pass"])
        self.assertTrue(any("span_ge_10_chapter_probe_count" in i for i in res["issues"]))
        
    # Re-include some other basic tests to ensure everything still passes
    def test_wrong_category_distribution(self):
        probes = self.get_valid_15_probes()
        probes[0]["category"] = "CALLBACK" 
        self.write_probes(probes)
        res = validate_probes(str(self.probes_path), str(self.chunks_path))
        self.assertFalse(res["pass"])
        
if __name__ == "__main__":
    unittest.main()
