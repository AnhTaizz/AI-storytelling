import os
import sys
import yaml
import json
from pathlib import Path

def validate_probes(probes_path: str, chunks_path: str):
    if not os.path.exists(probes_path):
        print(f"FAIL: Probe file not found at {probes_path}")
        return False
        
    if not os.path.exists(chunks_path):
        print(f"FAIL: Chunks file not found at {chunks_path}")
        return False
        
    with open(probes_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
        
    probes = data.get("probes", [])
    if len(probes) != 15:
        print(f"FAIL: Expected 15 probes, got {len(probes)}")
        return False
        
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
    
    issues = []
    
    for p in probes:
        pid = p.get("probe_id")
        if pid in probe_ids:
            issues.append(f"Duplicate probe_id {pid}")
        probe_ids.add(pid)
        
        cat = p.get("category")
        if cat not in categories:
            issues.append(f"Invalid category {cat} in {pid}")
        else:
            cat_counts[cat] += 1
            
        cutoff = p.get("cutoff_chapter")
        if not (1 <= cutoff <= 30):
            issues.append(f"Invalid cutoff_chapter {cutoff} in {pid}")
            
        req = p.get("required_evidence_chunk_ids", [])
        sup = p.get("supporting_evidence_chunk_ids", [])
        
        if not req:
            issues.append(f"required_evidence_chunk_ids empty in {pid}")
            
        if set(req).intersection(set(sup)):
            issues.append(f"Intersection between required and supporting evidence in {pid}")
            
        req_chapters = []
        for cid in req + sup:
            if cid not in chunk_meta:
                issues.append(f"Chunk {cid} not found in chunks.jsonl for {pid}")
            else:
                if cid in req:
                    req_chapters.append(chunk_meta[cid])
                    
        for ch in req_chapters:
            if ch > cutoff:
                issues.append(f"Required evidence chapter {ch} > cutoff {cutoff} in {pid}")
                
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
            
        forbidden = p.get("forbidden_future_chapters", [])
        for ch in forbidden:
            if ch <= cutoff:
                issues.append(f"Forbidden chapter {ch} <= cutoff {cutoff} in {pid}")
                
        if not p.get("expected_answer"):
            issues.append(f"expected_answer empty in {pid}")
        if not p.get("expected_facts"):
            issues.append(f"expected_facts empty in {pid}")
            
    if issues:
        for i in issues: print(f"FAIL: {i}")
        return False
        
    print("PASS: Benchmark validation successful")
    print(f"Categories: {cat_counts}")
    print(f"Multi-chunk probes: {multi_chunk_count}")
    print(f"Multi-chapter probes: {multi_chap_count}")
    print(f"Spanning >= 5 chapters: {span_ge_5_count}")
    print(f"Spanning >= 10 chapters: {span_ge_10_count}")
    return True

if __name__ == "__main__":
    base_dir = Path("e:/ProjectDE/AI-storytelling")
    probes = base_dir / ".local/story_integration/otonari_30ch/LONG_RANGE_PROBE_V1/probes.yaml"
    chunks = base_dir / ".local/story_integration/otonari_30ch/PARAGRAPH_PACK_V1/chunks.jsonl"
    
    if len(sys.argv) > 1:
        probes = Path(sys.argv[1])
    if len(sys.argv) > 2:
        chunks = Path(sys.argv[2])
        
    success = validate_probes(str(probes), str(chunks))
    sys.exit(0 if success else 1)
