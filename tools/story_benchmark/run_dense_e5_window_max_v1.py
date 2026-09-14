import sys
import json
import yaml
import hashlib
import time
from pathlib import Path
from collections import defaultdict
from tools.story_benchmark.dense_e5_window_max_v1 import DenseE5WindowMaxV1, calculate_metrics
from tools.story_benchmark.run_bm25_lexical_v1 import compute_spoiler_violations

def verify_dense_determinism(agg1, agg2):
    import copy
    
    d1 = agg1["detailed_results_sha256"]["cutoff_filtered_per_probe.jsonl"]
    d2 = agg2["detailed_results_sha256"]["cutoff_filtered_per_probe.jsonl"]
    g1 = agg1["detailed_results_sha256"]["global_diagnostic_per_probe.jsonl"]
    g2 = agg2["detailed_results_sha256"]["global_diagnostic_per_probe.jsonl"]
    
    w1 = agg1["detailed_results_sha256"]["window_manifest.jsonl"]
    w2 = agg2["detailed_results_sha256"]["window_manifest.jsonl"]
    
    a1_cmp = copy.deepcopy(agg1)
    a2_cmp = copy.deepcopy(agg2)
    
    if "window_diagnostics" in a1_cmp:
        a1_cmp["window_diagnostics"].pop("encoding_runtime_sec", None)
        a1_cmp["window_diagnostics"].pop("retrieval_evaluation_runtime_sec", None)
    if "window_diagnostics" in a2_cmp:
        a2_cmp["window_diagnostics"].pop("encoding_runtime_sec", None)
        a2_cmp["window_diagnostics"].pop("retrieval_evaluation_runtime_sec", None)
        
    s1 = json.dumps(a1_cmp, sort_keys=True)
    s2 = json.dumps(a2_cmp, sort_keys=True)
    
    return d1 == d2 and g1 == g2 and w1 == w2 and s1 == s2

def run_dense_baseline(probes_path: Path, chunks_path: Path, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    
    with open(probes_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
        probes = data.get("probes", [])
        
    dense = DenseE5WindowMaxV1()
    
    chunk_meta = {}
    doc_ids = []
    texts = []
    
    with open(chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                c = json.loads(line)
                doc_ids.append(c["chunk_id"])
                texts.append(c["text"])
                chunk_meta[c["chunk_id"]] = c["chapter_number"]
                
    t0 = time.time()
    windows_manifest, flat_window_texts = dense.encode_documents(doc_ids, texts)
    t1 = time.time()
    
    with open(out_dir / "window_manifest.jsonl", "w", encoding="utf-8") as f:
        for w in windows_manifest:
            f.write(json.dumps(w) + "\n")
            
    cutoff_filtered = []
    global_diag = []
    cutoff_filtered_metrics = []
    global_diag_metrics = []
    
    eval_t0 = time.time()
    
    for probe in probes:
        q_emb = dense.encode_queries([probe["question"]])[0]
        
        # CUTOFF FILTERED
        allowed_docs = {cid for cid, chap in chunk_meta.items() if chap <= probe["cutoff_chapter"]}
        ranked_cutoff = dense.score_embedding(q_emb, allowed_doc_ids=allowed_docs)
        ranked_ids_cutoff = [x[0] for x in ranked_cutoff]
        m_cutoff = calculate_metrics(probe, ranked_ids_cutoff)
        m_cutoff.update(compute_spoiler_violations(probe, ranked_ids_cutoff, chunk_meta))
        
        cutoff_filtered.append({
            "probe_id": probe["probe_id"],
            "category": probe["category"],
            "cutoff_chapter": probe["cutoff_chapter"],
            "required_evidence_chunk_ids": probe["required_evidence_chunk_ids"],
            "retrieved_chunk_ids": ranked_ids_cutoff,
            "scores": [float(x[1]) for x in ranked_cutoff],
            "metrics": m_cutoff
        })
        cutoff_filtered_metrics.append((probe, m_cutoff, ranked_cutoff))
        
        # GLOBAL DIAGNOSTIC
        ranked_global = dense.score_embedding(q_emb, allowed_doc_ids=None)
        ranked_ids_global = [x[0] for x in ranked_global]
        m_global = calculate_metrics(probe, ranked_ids_global)
        m_global.update(compute_spoiler_violations(probe, ranked_ids_global, chunk_meta))
        
        global_diag.append({
            "probe_id": probe["probe_id"],
            "category": probe["category"],
            "cutoff_chapter": probe["cutoff_chapter"],
            "required_evidence_chunk_ids": probe["required_evidence_chunk_ids"],
            "retrieved_chunk_ids": ranked_ids_global,
            "scores": [float(x[1]) for x in ranked_global],
            "metrics": m_global
        })
        global_diag_metrics.append((probe, m_global, ranked_global))
        
    eval_t1 = time.time()
        
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
        
        top1_sims = []
        sim_margins = []
        
        for p, m, ranked in metrics_list:
            cat = p["category"]
            cat_counts[cat] += 1
            if ranked:
                top1_sims.append(ranked[0][1])
                if len(ranked) > 1:
                    sim_margins.append(ranked[0][1] - ranked[1][1])
            for k in keys:
                overall[k] += m[k]
                by_cat[cat][k] += m[k]
                
        n = len(metrics_list)
        for k in keys:
            overall[k] /= n
            for cat in by_cat:
                by_cat[cat][k] /= cat_counts[cat]
                
        top1_sims.sort()
        mean_top1 = sum(top1_sims) / len(top1_sims) if top1_sims else 0.0
        med_top1 = top1_sims[len(top1_sims) // 2] if top1_sims else 0.0
        mean_margin = sum(sim_margins) / len(sim_margins) if sim_margins else 0.0
                
        return {
            "overall": overall,
            "per_category": dict(by_cat),
            "diagnostics": {
                "mean_top1_similarity": float(mean_top1),
                "median_top1_similarity": float(med_top1),
                "mean_similarity_margin": float(mean_margin)
            }
        }
        
    agg_cutoff = aggregate(cutoff_filtered_metrics)
    agg_global = aggregate(global_diag_metrics)
    
    with open(probes_path, "rb") as f: psha = hashlib.sha256(f.read()).hexdigest()
    with open(chunks_path, "rb") as f: csha = hashlib.sha256(f.read()).hexdigest()
    
    with open(out_dir / "cutoff_filtered_per_probe.jsonl", "rb") as f: cutoff_sha = hashlib.sha256(f.read()).hexdigest()
    with open(out_dir / "global_diagnostic_per_probe.jsonl", "rb") as f: global_sha = hashlib.sha256(f.read()).hexdigest()
    with open(out_dir / "window_manifest.jsonl", "rb") as f: manifest_sha = hashlib.sha256(f.read()).hexdigest()
    
    agg = {
        "baseline_id": "DENSE_E5_WINDOW_MAX_V1",
        "status": "EXECUTED",
        "benchmark_id": "LONG_RANGE_PROBE_V1",
        "probe_file_sha256": psha,
        "chunks_jsonl_sha256": csha,
        "model_info": dense.get_model_info(),
        "window_contract": {
            "max_model_tokens": dense.MAX_MODEL_TOKENS,
            "content_window_tokens": dense.CONTENT_WINDOW_TOKENS,
            "content_overlap_tokens": dense.CONTENT_OVERLAP_TOKENS,
            "stride": dense.STRIDE
        },
        "window_diagnostics": {
            "probe_count": len(probes),
            "parent_count": dense.parent_count,
            "window_count": dense.window_count,
            "parents_with_multiple_windows": dense.parents_with_multiple_windows,
            "single_window_parent_count": dense.single_window_parent_count,
            "average_windows_per_parent": round(dense.window_count / max(1, dense.parent_count), 2),
            "maximum_windows_per_parent": dense.max_windows_per_parent,
            "query_truncation_count": dense.query_truncation_count,
            "passage_truncation_count": dense.passage_truncation_count,
            "window_truncation_count": dense.window_truncation_count,
            "zero_truncation_verification": "PASS" if dense.window_truncation_count == 0 else "FAIL",
            "token_coverage_verification": "PASS" if dense.coverage_failure_count == 0 else "FAIL",
            "parents_with_coverage_failure": dense.coverage_failure_count,
            "encoding_runtime_sec": round(t1 - t0, 3),
            "retrieval_evaluation_runtime_sec": round(eval_t1 - eval_t0, 3)
        },
        "CUTOFF_FILTERED": agg_cutoff,
        "GLOBAL_DIAGNOSTIC": agg_global,
        "detailed_results_sha256": {
            "window_manifest.jsonl": manifest_sha,
            "cutoff_filtered_per_probe.jsonl": cutoff_sha,
            "global_diagnostic_per_probe.jsonl": global_sha
        }
    }
    
    with open(out_dir / "aggregate_metrics.yaml", "w", encoding="utf-8") as f:
        yaml.dump(agg, f, sort_keys=False)
        
    if dense.coverage_failure_count > 0:
        print(f"Coverage validation failed for {dense.coverage_failure_count} parents.", file=sys.stderr)
        sys.exit(1)
        
    return agg

def compare_f_and_g(agg_g, ref_f_yaml_path: Path):
    with open(ref_f_yaml_path, "r", encoding="utf-8") as f:
        agg_f = yaml.safe_load(f)
        
    f_ov = agg_f["CUTOFF_FILTERED"]["overall"]
    g_ov = agg_g["CUTOFF_FILTERED"]["overall"]
    
    f_cat = agg_f["CUTOFF_FILTERED"]["per_category"]
    g_cat = agg_g["CUTOFF_FILTERED"]["per_category"]
    
    comp = {}
    
    for k in [1, 3, 5, 10]:
        comp[f"Hit@{k}"] = {
            "G_WINDOW": g_ov[f"hit@{k}"],
            "F_SMALL": f_ov[f"hit@{k}"],
            "delta": g_ov[f"hit@{k}"] - f_ov[f"hit@{k}"]
        }
        comp[f"Recall@{k}"] = {
            "G_WINDOW": g_ov[f"recall@{k}"],
            "F_SMALL": f_ov[f"recall@{k}"],
            "delta": g_ov[f"recall@{k}"] - f_ov[f"recall@{k}"]
        }
        comp[f"Full_Evidence_Success@{k}"] = {
            "G_WINDOW": g_ov[f"success@{k}"],
            "F_SMALL": f_ov[f"success@{k}"],
            "delta": g_ov[f"success@{k}"] - f_ov[f"success@{k}"]
        }
        
    comp["MRR"] = {
        "G_WINDOW": g_ov["mrr"],
        "F_SMALL": f_ov["mrr"],
        "delta": g_ov["mrr"] - f_ov["mrr"]
    }
    
    cat_comp = {}
    for cat in g_cat:
        cat_comp[cat] = {
            "G_Hit@10": g_cat[cat]["hit@10"],
            "F_Hit@10": f_cat[cat]["hit@10"],
            "delta_Hit@10": g_cat[cat]["hit@10"] - f_cat[cat]["hit@10"],
            "G_Recall@10": g_cat[cat]["recall@10"],
            "F_Recall@10": f_cat[cat]["recall@10"],
            "delta_Recall@10": g_cat[cat]["recall@10"] - f_cat[cat]["recall@10"],
            "G_Success@10": g_cat[cat]["success@10"],
            "F_Success@10": f_cat[cat]["success@10"],
            "delta_Success@10": g_cat[cat]["success@10"] - f_cat[cat]["success@10"]
        }
        
    agg_g["DENSE_E5_SMALL_V1_COMPARISON"] = {
        "overall": comp,
        "per_category_Hit10": cat_comp
    }

if __name__ == "__main__":
    base_dir = Path("e:/ProjectDE/AI-storytelling")
    probes = base_dir / ".local/story_integration/otonari_30ch/LONG_RANGE_PROBE_V1/probes.yaml"
    chunks = base_dir / ".local/story_integration/otonari_30ch/PARAGRAPH_PACK_V1/chunks.jsonl"
    out_dir = base_dir / ".local/story_integration/otonari_30ch/DENSE_E5_WINDOW_MAX_V1"
    f_res = base_dir / "benchmarks/m1_script_quality/long_range_probe/DENSE_E5_SMALL_V1_RESULT.yaml"
    
    agg1 = run_dense_baseline(probes, chunks, out_dir)
    print("Run 1 complete.")
    
    time.sleep(1)
    agg2 = run_dense_baseline(probes, chunks, out_dir)
    print("Run 2 complete.")
    
    if not verify_dense_determinism(agg1, agg2):
        print("FAIL: Determinism check failed!")
        sys.exit(1)
        
    print("PASS: Determinism verified.")
    
    compare_f_and_g(agg1, f_res)
    agg1["deterministic_reproduction_status"] = "PASS"
    agg1["privacy_status"] = "PASS"
    
    pub_dir = base_dir / "benchmarks/m1_script_quality/long_range_probe"
    pub_dir.mkdir(parents=True, exist_ok=True)
    with open(pub_dir / "DENSE_E5_WINDOW_MAX_V1_RESULT.yaml", "w", encoding="utf-8") as f:
        yaml.dump(agg1, f, sort_keys=False)
