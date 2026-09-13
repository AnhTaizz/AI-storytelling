import unittest
import yaml
import json
import tempfile
import os
from pathlib import Path
from tools.story_benchmark.validate_long_range_probe_v1 import validate_probes

class TestValidateLongRangeProbeV1(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.probes_path = Path(self.test_dir.name) / "probes.yaml"
        self.chunks_path = Path(self.test_dir.name) / "chunks.jsonl"
        
        # Write dummy chunks
        with open(self.chunks_path, "w", encoding="utf-8") as f:
            for i in range(1, 4):
                f.write(json.dumps({"chunk_id": f"ch00{i}_c001", "chapter_number": i}) + "\n")
                
        self.valid_probe = {
            "probe_id": "P_TEST",
            "category": "CHRONOLOGY",
            "cutoff_chapter": 3,
            "required_evidence_chunk_ids": ["ch001_c001", "ch002_c001"],
            "expected_answer": "ans",
            "expected_facts": ["fact"],
            "earliest_required_chapter": 1,
            "latest_required_chapter": 2,
            "chapter_span": 2,
            "requires_multi_chunk": True,
            "requires_multi_chapter": True,
            "forbidden_future_chapters": [4]
        }
        
    def tearDown(self):
        self.test_dir.cleanup()
        
    def write_probes(self, probes_list):
        with open(self.probes_path, "w", encoding="utf-8") as f:
            yaml.dump({"probes": probes_list}, f)
            
    def test_valid_minimal(self):
        # Requires exactly 15 probes to pass overall validation
        probes = []
        for i in range(15):
            p = self.valid_probe.copy()
            p["probe_id"] = f"P_TEST_{i}"
            probes.append(p)
            
        self.write_probes(probes)
        self.assertTrue(validate_probes(str(self.probes_path), str(self.chunks_path)))
        
    def test_duplicate_probe_id(self):
        probes = [self.valid_probe.copy() for _ in range(15)]
        self.write_probes(probes)
        self.assertFalse(validate_probes(str(self.probes_path), str(self.chunks_path)))
        
    def test_invalid_category(self):
        p = self.valid_probe.copy()
        p["category"] = "INVALID"
        self.write_probes([p] * 15)
        self.assertFalse(validate_probes(str(self.probes_path), str(self.chunks_path)))
        
    def test_missing_chunk_reference(self):
        p = self.valid_probe.copy()
        p["required_evidence_chunk_ids"] = ["ch004_c001"] # doesn't exist
        self.write_probes([p] * 15)
        self.assertFalse(validate_probes(str(self.probes_path), str(self.chunks_path)))
        
    def test_required_evidence_after_cutoff(self):
        p = self.valid_probe.copy()
        p["cutoff_chapter"] = 1
        self.write_probes([p] * 15)
        self.assertFalse(validate_probes(str(self.probes_path), str(self.chunks_path)))
        
    def test_incorrect_chapter_span(self):
        p = self.valid_probe.copy()
        p["chapter_span"] = 3
        self.write_probes([p] * 15)
        self.assertFalse(validate_probes(str(self.probes_path), str(self.chunks_path)))
        
    def test_incorrect_multi_chapter_flag(self):
        p = self.valid_probe.copy()
        p["requires_multi_chapter"] = False
        self.write_probes([p] * 15)
        self.assertFalse(validate_probes(str(self.probes_path), str(self.chunks_path)))

if __name__ == "__main__":
    unittest.main()
