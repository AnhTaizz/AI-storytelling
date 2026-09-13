import os
import sys
import yaml
import json
import hashlib
from pathlib import Path
from typing import Dict, Any, Tuple

def validate_probes(probes_path: str, chunks_path: str) -> Dict[str, Any]:
    issues = []
    if not os.path.exists(probes_path):
        issues.append(f"Probe file not found at {probes_path}")
        return {"pass": False, "issues": issues, "metrics": {}}
        
    if not os.path.exists(chunks_path):
        issues.append(f"Chunks file not found at {chunks_path}")
        return {"pass": False, "issues": issues, "metrics": {}}
        
    with open(probes_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
        
    probes = data.get("probes", [])
    if len(probes) != 15:
        issues.append(f"Expected 15 probes, got {len(probes)}")
        
    chunk_meta = {}
    with open(chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                c = json.loads(line)
                chunk_meta[c["chunk_id"]] = c["chapter_number"]
                
    probe_ids = set()
    categories = ["CHRONOLOGY", "RELATIONSHIP_PROGRESSION", "CALLBACK", "TEMPORAL_STATE", "SPOILER_BOUNDARY"]
    cat_counts = {c: 0 for c in categories}
    
    multi_chunk_count = 0
    multi_chap_count = 0
    span_ge_5_count = 0
    span_ge_10_count = 0
    
    chapter_spans = []
    
    for p in probes:
        pid = p.get("probe_id")
        if not pid:
            issues.append("Empty probe_id found")
            continue
            
        if pid in probe_ids:
            issues.append(f"Duplicate probe_id {pid}")
        probe_ids.add(pid)
        
        cat = p.get("category")
        if not cat:
            issues.append(f"Empty category in {pid}")
        elif cat not in categories:
            issues.append(f"Invalid category {cat} in {pid}")
        else:
            cat_counts[cat] += 1
            
        if cat == "SPOILER_BOUNDARY" and p.get("cutoff_chapter", 30) >= 30:
            issues.append(f"SPOILER_BOUNDARY probe must have cutoff_chapter < 30 in {pid}")
            
        # Non-empty checks
        for field in ["question", "expected_answer", "expected_facts", "difficulty_notes"]:
            if not p.get(field):
                issues.append(f"Empty {field} in {pid}")
                
        cutoff = p.get("cutoff_chapter")
        if not cutoff or not (1 <= cutoff <= 30):
            issues.append(f"Invalid cutoff_chapter {cutoff} in {pid}")
            cutoff = 30
            
        req = p.get("required_evidence_chunk_ids", [])
        sup = p.get("supporting_evidence_chunk_ids", [])
        
        if not req:
            issues.append(f"required_evidence_chunk_ids empty in {pid}")
            
        if len(req) != len(set(req)):
            issues.append(f"Duplicate chunk in required list in {pid}")
        if len(sup) != len(set(sup)):
            issues.append(f"Duplicate chunk in supporting list in {pid}")
            
        if set(req).intersection(set(sup)):
            issues.append(f"Intersection between required and supporting evidence in {pid}")
            
        req_chapters = []
        for cid in req:
            if cid not in chunk_meta:
                issues.append(f"Chunk {cid} not found in chunks.jsonl for {pid}")
            else:
                req_chapters.append(chunk_meta[cid])
                if chunk_meta[cid] > cutoff:
                    issues.append(f"Required evidence chapter {chunk_meta[cid]} > cutoff {cutoff} in {pid}")
                    
        for cid in sup:
            if cid not in chunk_meta:
                issues.append(f"Chunk {cid} not found in chunks.jsonl for {pid}")
            else:
                if chunk_meta[cid] > cutoff:
                    issues.append(f"Supporting evidence chapter {chunk_meta[cid]} > cutoff {cutoff} in {pid}")
                    
        if req_chapters:
            earliest = min(req_chapters)
            latest = max(req_chapters)
            
            if p.get("earliest_required_chapter") != earliest:
                issues.append(f"earliest_required_chapter mismatch in {pid}: expected {earliest}")
            if p.get("latest_required_chapter") != latest:
                issues.append(f"latest_required_chapter mismatch in {pid}: expected {latest}")
                
            expected_span = latest - earliest + 1 if latest != earliest else 1
            if p.get("chapter_span") != expected_span:
                issues.append(f"chapter_span mismatch in {pid}: expected {expected_span}")
                
            if p.get("requires_multi_chunk") != (len(req) > 1):
                issues.append(f"requires_multi_chunk mismatch in {pid}")
                
            if p.get("requires_multi_chapter") != (earliest != latest):
                issues.append(f"requires_multi_chapter mismatch in {pid}")
                
            if len(req) > 1: multi_chunk_count += 1
            if earliest != latest: multi_chap_count += 1
            if expected_span >= 5: span_ge_5_count += 1
            if expected_span >= 10: span_ge_10_count += 1
            chapter_spans.append(expected_span)
            
        forbidden = p.get("forbidden_future_chapters", [])
        expected_forbidden = list(range(cutoff + 1, 31))
        if forbidden != expected_forbidden:
            issues.append(f"forbidden_future_chapters mismatch in {pid}: expected {expected_forbidden}, got {forbidden}")
            
    for cat in categories:
        if cat_counts[cat] != 3:
            issues.append(f"Category {cat} has {cat_counts[cat]} probes, expected 3")
            
    if multi_chunk_count < 10:
        issues.append(f"Benchmark quality gate failed: multi_chunk_probe_count ({multi_chunk_count}) < 10")
    if multi_chap_count < 10:
        issues.append(f"Benchmark quality gate failed: multi_chapter_probe_count ({multi_chap_count}) < 10")
    if span_ge_5_count < 10:
        issues.append(f"Benchmark quality gate failed: span_ge_5_chapter_probe_count ({span_ge_5_count}) < 10")
    if span_ge_10_count < 1:
        issues.append(f"Benchmark quality gate failed: span_ge_10_chapter_probe_count ({span_ge_10_count}) < 1")
            
    metrics = {
        "probe_count": len(probes),
        "per_category_counts": cat_counts,
        "multi_chunk_probe_count": multi_chunk_count,
        "multi_chapter_probe_count": multi_chap_count,
        "span_ge_5_chapter_probe_count": span_ge_5_count,
        "span_ge_10_chapter_probe_count": span_ge_10_count,
        "minimum_chapter_span": min(chapter_spans) if chapter_spans else 0,
        "maximum_chapter_span": max(chapter_spans) if chapter_spans else 0,
    }
    
    return {
        "pass": len(issues) == 0,
        "issues": issues,
        "metrics": metrics
    }

def validate_freeze_integrity(freeze_yaml_path: str, probes_path: str, chunks_path: str) -> Tuple[bool, list]:
    issues = []
    
    if not os.path.exists(freeze_yaml_path):
        return False, [f"Freeze file not found at {freeze_yaml_path}"]
        
    with open(freeze_yaml_path, "r", encoding="utf-8") as f:
        freeze_data = yaml.safe_load(f)
        
    val_res = validate_probes(probes_path, chunks_path)
    if not val_res["pass"]:
        issues.append("Benchmark validation failed internally.")
        issues.extend(val_res["issues"])
        
    with open(probes_path, "rb") as f:
        actual_probe_sha = hashlib.sha256(f.read()).hexdigest()
        
    with open(chunks_path, "rb") as f:
        actual_chunks_sha = hashlib.sha256(f.read()).hexdigest()
        
    if freeze_data.get("probe_file_sha256") != actual_probe_sha:
        issues.append(f"Probe SHA mismatch: expected {freeze_data.get('probe_file_sha256')}, got {actual_probe_sha}")
        
    if freeze_data.get("chunks_jsonl_sha256") != actual_chunks_sha:
        issues.append(f"Chunks SHA mismatch: expected {freeze_data.get('chunks_jsonl_sha256')}, got {actual_chunks_sha}")
        
    fixed_identities = {
        "benchmark_id": "LONG_RANGE_PROBE_V1",
        "benchmark_version": 1,
        "corpus_fingerprint_sha256": "7f9bb8106d6d50acd2b3760738c0b8040f36ab547c2d2f7eade1ca0b9a827ff8",
        "passage_contract_id": "OTONARI_LOCAL_PASSAGE_V1",
        "segmentation_version": "PARAGRAPH_PACK_V1",
    }
    
    for k, v in fixed_identities.items():
        if freeze_data.get(k) != v:
            issues.append(f"Fixed identity {k} mismatch: expected {v}, got {freeze_data.get(k)}")
            
    derived = val_res["metrics"]
    for k in [
        "probe_count", "multi_chunk_probe_count", "multi_chapter_probe_count",
        "span_ge_5_chapter_probe_count", "span_ge_10_chapter_probe_count",
        "minimum_chapter_span", "maximum_chapter_span"
    ]:
        if freeze_data.get(k) != derived.get(k):
            issues.append(f"Metric {k} mismatch: freeze {freeze_data.get(k)}, actual {derived.get(k)}")
            
    if freeze_data.get("per_category_counts") != derived.get("per_category_counts"):
        issues.append(f"Category counts mismatch: freeze {freeze_data.get('per_category_counts')}, actual {derived.get('per_category_counts')}")
        
    return len(issues) == 0, issues

if __name__ == "__main__":
    base_dir = Path("e:/ProjectDE/AI-storytelling")
    probes = base_dir / ".local/story_integration/otonari_30ch/LONG_RANGE_PROBE_V1/probes.yaml"
    chunks = base_dir / ".local/story_integration/otonari_30ch/PARAGRAPH_PACK_V1/chunks.jsonl"
    freeze = base_dir / "benchmarks/m1_script_quality/long_range_probe/LONG_RANGE_PROBE_V1_FREEZE.yaml"
    
    if len(sys.argv) > 1:
        probes = Path(sys.argv[1])
    if len(sys.argv) > 2:
        chunks = Path(sys.argv[2])
    if len(sys.argv) > 3:
        freeze = Path(sys.argv[3])
        
    res = validate_probes(str(probes), str(chunks))
    if not res["pass"]:
        for i in res["issues"]: print(f"FAIL: {i}")
        sys.exit(1)
    else:
        print("PASS: Benchmark validation successful")
        print(json.dumps(res["metrics"], indent=2))
        
    if freeze.exists():
        ok, iss = validate_freeze_integrity(str(freeze), str(probes), str(chunks))
        if not ok:
            for i in iss: print(f"FREEZE FAIL: {i}")
            sys.exit(1)
        else:
            print("PASS: Freeze integrity validation successful")
            
    sys.exit(0)
