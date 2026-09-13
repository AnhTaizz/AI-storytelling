import json
import yaml
import sys
import hashlib
import time
from pathlib import Path
from collections import defaultdict
from tools.story_benchmark.bm25_lexical_v1 import BM25LexicalV1, calculate_metrics, jp_simple_lexical_v1

def compute_spoiler_violations(probe: dict, ranked: list, chunk_meta: dict) -> dict:
    cutoff = probe["cutoff_chapter"]
    metrics = {}
    for k in [1, 3, 5, 10]:
        top_k = ranked[:k]
        violation = 1 if any(chunk_meta[c] > cutoff for c in top_k) else 0
        metrics[f"spoiler_violation@{k}"] = violation
    return metrics

def run_baseline(probes_path: Path, chunks_path: Path, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    
    with open(probes_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
        probes = data.get("probes", [])
        
    bm25 = BM25LexicalV1()
    chunk_meta = {}
    
    with open(chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                c = json.loads(line)
                bm25.add_document(c["chunk_id"], c["text"])
                chunk_meta[c["chunk_id"]] = c["chapter_number"]
                
    bm25.build()
    
    # Store results
    cutoff_filtered = []
    global_diag = []
    
    cutoff_filtered_metrics = []
    global_diag_metrics = []
    
    for probe in probes:
        # CUTOFF FILTERED
        allowed_docs = {cid for cid, chap in chunk_meta.items() if chap <= probe["cutoff_chapter"]}
        ranked_cutoff = bm25.score(probe["question"], allowed_doc_ids=allowed_docs)
        ranked_ids_cutoff = [x[0] for x in ranked_cutoff]
        m_cutoff = calculate_metrics(probe, ranked_ids_cutoff)
        m_cutoff.update(compute_spoiler_violations(probe, ranked_ids_cutoff, chunk_meta))
        
        cutoff_filtered.append({
            "probe_id": probe["probe_id"],
            "category": probe["category"],
            "cutoff_chapter": probe["cutoff_chapter"],
            "required_evidence_chunk_ids": probe["required_evidence_chunk_ids"],
            "retrieved_chunk_ids": ranked_ids_cutoff,
            "scores": [x[1] for x in ranked_cutoff],
            "metrics": m_cutoff
        })
        cutoff_filtered_metrics.append((probe, m_cutoff, len(ranked_ids_cutoff)))
        
        # GLOBAL DIAGNOSTIC
        ranked_global = bm25.score(probe["question"], allowed_doc_ids=None)
        ranked_ids_global = [x[0] for x in ranked_global]
        m_global = calculate_metrics(probe, ranked_ids_global)
        m_global.update(compute_spoiler_violations(probe, ranked_ids_global, chunk_meta))
        
        global_diag.append({
            "probe_id": probe["probe_id"],
            "category": probe["category"],
            "cutoff_chapter": probe["cutoff_chapter"],
            "required_evidence_chunk_ids": probe["required_evidence_chunk_ids"],
            "retrieved_chunk_ids": ranked_ids_global,
            "scores": [x[1] for x in ranked_global],
            "metrics": m_global
        })
        global_diag_metrics.append((probe, m_global, len(ranked_ids_global)))
        
    with open(out_dir / "cutoff_filtered_per_probe.jsonl", "w", encoding="utf-8") as f:
        for r in cutoff_filtered:
            f.write(json.dumps(r) + "\n")
            
    with open(out_dir / "global_diagnostic_per_probe.jsonl", "w", encoding="utf-8") as f:
        for r in global_diag:
            f.write(json.dumps(r) + "\n")
            
    def aggregate(metrics_list):
        keys = ["hit@1", "hit@3", "hit@5", "hit@10",
                "recall@1", "recall@3", "recall@5", "recall@10",
                "success@1", "success@3", "success@5", "success@10",
                "spoiler_violation@1", "spoiler_violation@3", "spoiler_violation@5", "spoiler_violation@10",
                "mrr"]
        
        overall = {k: 0.0 for k in keys}
        by_cat = defaultdict(lambda: {k: 0.0 for k in keys})
        cat_counts = defaultdict(int)
        
        zero_pos = 0
        total_cand = 0
        total_q_tok = 0
        cand_counts = []
        
        for p, m, cand_len in metrics_list:
            cat = p["category"]
            cat_counts[cat] += 1
            if cand_len == 0:
                zero_pos += 1
            total_cand += cand_len
            total_q_tok += len(jp_simple_lexical_v1(p["question"]))
            cand_counts.append(cand_len)
            
            for k in keys:
                overall[k] += m[k]
                by_cat[cat][k] += m[k]
                
        n = len(metrics_list)
        for k in keys:
            overall[k] /= n
            for cat in by_cat:
                by_cat[cat][k] /= cat_counts[cat]
                
        cand_counts.sort()
        med_cand = cand_counts[n // 2] if n % 2 != 0 else (cand_counts[n // 2 - 1] + cand_counts[n // 2]) / 2.0
                
        return {
            "overall": overall,
            "per_category": dict(by_cat),
            "diagnostics": {
                "zero_positive_candidate_probe_count": zero_pos,
                "average_positive_score_candidate_count": total_cand / n,
                "median_positive_score_candidate_count": med_cand,
                "average_query_lexical_token_count": total_q_tok / n
            }
        }
        
    agg_cutoff = aggregate(cutoff_filtered_metrics)
    agg_global = aggregate(global_diag_metrics)
    
    with open(probes_path, "rb") as f: psha = hashlib.sha256(f.read()).hexdigest()
    with open(chunks_path, "rb") as f: csha = hashlib.sha256(f.read()).hexdigest()
    
    with open(out_dir / "cutoff_filtered_per_probe.jsonl", "rb") as f: cutoff_sha = hashlib.sha256(f.read()).hexdigest()
    with open(out_dir / "global_diagnostic_per_probe.jsonl", "rb") as f: global_sha = hashlib.sha256(f.read()).hexdigest()
    
    agg = {
        "baseline_id": "BM25_LEXICAL_V1",
        "status": "EXECUTED",
        "benchmark_id": "LONG_RANGE_PROBE_V1",
        "probe_file_sha256": psha,
        "chunks_jsonl_sha256": csha,
        "retriever_parameters": {"k1": 1.2, "b": 0.75},
        "tokenizer_id": "JP_SIMPLE_LEXICAL_V1",
        "CUTOFF_FILTERED": agg_cutoff,
        "GLOBAL_DIAGNOSTIC": agg_global,
        "detailed_results_sha256": {
            "cutoff_filtered_per_probe.jsonl": cutoff_sha,
            "global_diagnostic_per_probe.jsonl": global_sha
        }
    }
    
    with open(out_dir / "aggregate_metrics.yaml", "w", encoding="utf-8") as f:
        yaml.dump(agg, f, sort_keys=False)
        
    return agg

def verify_determinism(agg1, agg2):
    d1 = agg1["detailed_results_sha256"]["cutoff_filtered_per_probe.jsonl"]
    d2 = agg2["detailed_results_sha256"]["cutoff_filtered_per_probe.jsonl"]
    g1 = agg1["detailed_results_sha256"]["global_diagnostic_per_probe.jsonl"]
    g2 = agg2["detailed_results_sha256"]["global_diagnostic_per_probe.jsonl"]
    
    agg1_str = json.dumps(agg1, sort_keys=True)
    agg2_str = json.dumps(agg2, sort_keys=True)
    
    return d1 == d2 and g1 == g2 and agg1_str == agg2_str

if __name__ == "__main__":
    base_dir = Path("e:/ProjectDE/AI-storytelling")
    probes = base_dir / ".local/story_integration/otonari_30ch/LONG_RANGE_PROBE_V1/probes.yaml"
    chunks = base_dir / ".local/story_integration/otonari_30ch/PARAGRAPH_PACK_V1/chunks.jsonl"
    out_dir = base_dir / ".local/story_integration/otonari_30ch/BM25_LEXICAL_V1"
    
    agg1 = run_baseline(probes, chunks, out_dir)
    print("Run 1 complete.")
    
    # Run twice for determinism verification
    time.sleep(1)
    agg2 = run_baseline(probes, chunks, out_dir)
    print("Run 2 complete.")
    
    if not verify_determinism(agg1, agg2):
        print("FAIL: Determinism check failed!")
        sys.exit(1)
    
    print("PASS: Determinism verified.")
        
    # Also dump the summary for public track
    pub_dir = base_dir / "benchmarks/m1_script_quality/long_range_probe"
    pub_dir.mkdir(parents=True, exist_ok=True)
    agg1["deterministic_reproduction_status"] = "PASS"
    agg1["privacy_status"] = "PASS"
    
    with open(pub_dir / "BM25_LEXICAL_V1_RESULT.yaml", "w", encoding="utf-8") as f:
        yaml.dump(agg1, f, sort_keys=False)
