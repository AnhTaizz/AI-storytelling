import sys
import copy
import json
import yaml
import hashlib
import time
import numpy as np
from pathlib import Path
from collections import defaultdict

from tools.story_benchmark.dense_e5_multiquery_v1 import (
    METHOD_ID,
    DECOMPOSITION_ID,
    K_RRF,
    MIN_CONTENT_TOKENS,
    MAX_QUERIES_PER_PROBE,
    MIN_DECOMPOSED_PROBES_FOR_EVALUATION,
    HIT10_MAJOR_COLLAPSE_DELTA,
    DenseE5MultiQueryV1,
    calculate_metrics,
    decompose_probe,
    decomposition_diagnostics,
    eligible_doc_ids,
    change_diagnostics,
    interpret_verdict,
    find_private_leaks,
)
from tools.story_benchmark.run_bm25_lexical_v1 import compute_spoiler_violations

METRIC_KEYS = [
    "hit@1", "hit@3", "hit@5", "hit@10",
    "recall@1", "recall@3", "recall@5", "recall@10",
    "success@1", "success@3", "success@5", "success@10",
    "spoiler_violation@1", "spoiler_violation@3", "spoiler_violation@5", "spoiler_violation@10",
    "mrr",
]
RUNTIME_ONLY_KEYS = ("encoding_runtime_sec", "retrieval_evaluation_runtime_sec")
AGG_TOLERANCE = 1e-9


class GateFailure(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def write_jsonl(path: Path, rows):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def load_probes(probes_path: Path):
    with open(probes_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f).get("probes", [])


def load_chunks(chunks_path: Path):
    chunk_meta, doc_ids, texts = {}, [], []
    with open(chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                c = json.loads(line)
                doc_ids.append(c["chunk_id"])
                texts.append(c["text"])
                chunk_meta[c["chunk_id"]] = c["chapter_number"]
    return chunk_meta, doc_ids, texts


def verify_benchmark_freeze(probes_path: Path, chunks_path: Path, freeze_yaml: Path, probes) -> dict:
    with open(freeze_yaml, "r", encoding="utf-8") as f:
        freeze = yaml.safe_load(f)
    psha, csha = sha256_file(probes_path), sha256_file(chunks_path)
    if freeze.get("status") != "FROZEN":
        raise GateFailure("benchmark freeze status is not FROZEN")
    if psha != freeze["probe_file_sha256"]:
        raise GateFailure(f"probe file sha mismatch: {psha} != {freeze['probe_file_sha256']}")
    if csha != freeze["chunks_jsonl_sha256"]:
        raise GateFailure(f"chunks sha mismatch: {csha} != {freeze['chunks_jsonl_sha256']}")
    if len(probes) != freeze["probe_count"]:
        raise GateFailure(f"probe count mismatch: {len(probes)} != {freeze['probe_count']}")
    return {"probe_file_sha256": psha, "chunks_jsonl_sha256": csha}


def load_f_reference(f_detail_path: Path, f_result_yaml: Path):
    if not f_detail_path.exists():
        raise GateFailure(f"STOP: missing DENSE_E5_SMALL_V1 detailed artifact at {f_detail_path}; "
                          f"refusing to reconstruct an approximate baseline.")
    with open(f_result_yaml, "r", encoding="utf-8") as f:
        f_agg = yaml.safe_load(f)
    expected_sha = f_agg["detailed_results_sha256"]["cutoff_filtered_per_probe.jsonl"]
    actual_sha = sha256_file(f_detail_path)
    if actual_sha != expected_sha:
        raise GateFailure(f"F detailed artifact sha mismatch: {actual_sha} != {expected_sha}")
    f_rankings = {}
    with open(f_detail_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                f_rankings[r["probe_id"]] = r["retrieved_chunk_ids"]
    return f_agg, f_rankings, actual_sha


def check_control_rankings(control_rankings: dict, f_rankings: dict) -> list:
    """Exact ordered chunk-id equality per probe. Returns list of mismatching probe ids."""
    mismatches = []
    for pid, ranked in control_rankings.items():
        if f_rankings.get(pid) != ranked:
            mismatches.append(pid)
    for pid in f_rankings:
        if pid not in control_rankings:
            mismatches.append(pid)
    return sorted(set(mismatches))


def check_control_aggregate(control_overall: dict, f_overall: dict, tol: float = AGG_TOLERANCE) -> list:
    return [k for k in METRIC_KEYS if abs(control_overall[k] - f_overall[k]) > tol]


def aggregate(metrics_list):
    overall = {k: 0.0 for k in METRIC_KEYS}
    by_cat = defaultdict(lambda: {k: 0.0 for k in METRIC_KEYS})
    cat_counts = defaultdict(int)
    for category, m in metrics_list:
        cat_counts[category] += 1
        for k in METRIC_KEYS:
            overall[k] += m[k]
            by_cat[category][k] += m[k]
    n = len(metrics_list)
    for k in METRIC_KEYS:
        overall[k] /= n
        for cat in by_cat:
            by_cat[cat][k] /= cat_counts[cat]
    return {"overall": overall, "per_category": {c: dict(v) for c, v in by_cat.items()}}


def evaluate(probe, ranked_ids, chunk_meta):
    # Gold fields are read only here, after retrieval.
    m = calculate_metrics(probe, ranked_ids)
    m.update(compute_spoiler_violations(probe, ranked_ids, chunk_meta))
    return m


def run_multiquery(probes_path: Path, chunks_path: Path, out_dir: Path, freeze_yaml: Path,
                   f_detail_path: Path, f_result_yaml: Path, dense=None):
    out_dir.mkdir(parents=True, exist_ok=True)
    probes = load_probes(probes_path)
    input_hashes = verify_benchmark_freeze(probes_path, chunks_path, freeze_yaml, probes)
    f_agg, f_rankings, f_detail_sha = load_f_reference(f_detail_path, f_result_yaml)

    chunk_meta, doc_ids, texts = load_chunks(chunks_path)
    if dense is None:
        dense = DenseE5MultiQueryV1()

    t0 = time.time()
    dense.encode_documents(doc_ids, texts)
    t1 = time.time()

    # 1. Decomposition (question-only; before any gold access).
    decompositions = [decompose_probe(p) for p in probes]
    manifest = [{"probe_id": p["probe_id"], "decomposition_id": DECOMPOSITION_ID, "queries": qs}
                for p, qs in zip(probes, decompositions)]
    write_jsonl(out_dir / "decomposition_manifest.jsonl", manifest)
    decomp_diag = decomposition_diagnostics(decompositions)

    eval_t0 = time.time()
    # 2. Encode every query independently.
    query_embs = [[dense.encode_query_independent(q) for q in qs] for qs in decompositions]
    np.savez(str(out_dir / "query_embeddings.npz"),
             **{p["probe_id"]: np.array(e) for p, e in zip(probes, query_embs)})

    # 3. Relevance control gate: Q0 alone, cosine, CUTOFF_FILTERED.
    control_rows, control_rankings, control_metrics = [], {}, []
    for p, embs in zip(probes, query_embs):
        allowed = eligible_doc_ids(chunk_meta, p["cutoff_chapter"])
        ranked = dense.score_embedding(embs[0], allowed_doc_ids=allowed)
        ids = [d for d, _ in ranked]
        control_rankings[p["probe_id"]] = ids
        control_rows.append({"probe_id": p["probe_id"], "retrieved_chunk_ids": ids,
                             "scores": [float(s) for _, s in ranked]})
        control_metrics.append((p["category"], evaluate(p, ids, chunk_meta)))
    write_jsonl(out_dir / "relevance_control_per_probe.jsonl", control_rows)

    mismatches = check_control_rankings(control_rankings, f_rankings)
    if mismatches:
        raise GateFailure(f"Relevance control exact-ranking mismatch on {len(mismatches)} probe(s)")
    control_agg = aggregate(control_metrics)
    agg_mismatch = check_control_aggregate(control_agg["overall"], f_agg["CUTOFF_FILTERED"]["overall"])
    if agg_mismatch:
        raise GateFailure(f"Relevance control aggregate mismatch on {agg_mismatch}")

    # 4. Multi-query retrieval + RRF.
    per_query_rows, cutoff_rows, global_rows = [], [], []
    cutoff_metrics, global_metrics = [], []
    for p, embs in zip(probes, query_embs):
        for mode, allowed, rows, mlist in (
            ("CUTOFF_FILTERED", eligible_doc_ids(chunk_meta, p["cutoff_chapter"]), cutoff_rows, cutoff_metrics),
            ("GLOBAL_DIAGNOSTIC", None, global_rows, global_metrics),
        ):
            fused, per_query = dense.multiquery_rank(embs, allowed_doc_ids=allowed)
            for qi, r in enumerate(per_query):
                per_query_rows.append({"probe_id": p["probe_id"], "mode": mode, "query_index": qi,
                                       "retrieved_chunk_ids": [d for d, _ in r],
                                       "scores": [float(s) for _, s in r]})
            ids = [d for d, _ in fused]
            m = evaluate(p, ids, chunk_meta)
            rows.append({"probe_id": p["probe_id"], "category": p["category"],
                         "cutoff_chapter": p["cutoff_chapter"], "query_count": len(embs),
                         "retrieved_chunk_ids": ids, "rrf_scores": [s for _, s in fused],
                         "metrics": m})
            mlist.append((p["category"], m))
    eval_t1 = time.time()

    write_jsonl(out_dir / "per_query_rankings.jsonl", per_query_rows)
    write_jsonl(out_dir / "multiquery_cutoff_per_probe.jsonl", cutoff_rows)
    write_jsonl(out_dir / "multiquery_global_per_probe.jsonl", global_rows)

    agg_cutoff = aggregate(cutoff_metrics)
    agg_global = aggregate(global_metrics)

    spoiler_cutoff = all(agg_cutoff["overall"][f"spoiler_violation@{k}"] == 0.0 for k in (1, 3, 5, 10))
    if not spoiler_cutoff:
        raise GateFailure("CUTOFF_FILTERED spoiler violation detected")

    change = change_diagnostics(
        [r["retrieved_chunk_ids"][:10] for r in control_rows],
        [r["retrieved_chunk_ids"][:10] for r in cutoff_rows],
        [m for _, m in control_metrics],
        [r["metrics"] for r in cutoff_rows],
    )

    detail_files = ["decomposition_manifest.jsonl", "relevance_control_per_probe.jsonl",
                    "per_query_rankings.jsonl", "multiquery_cutoff_per_probe.jsonl",
                    "multiquery_global_per_probe.jsonl"]
    detail_sha = {name: sha256_file(out_dir / name) for name in detail_files}

    agg = {
        "baseline_id": METHOD_ID,
        "status": "EXECUTED",
        "benchmark_id": "LONG_RANGE_PROBE_V1",
        "probe_file_sha256": input_hashes["probe_file_sha256"],
        "chunks_jsonl_sha256": input_hashes["chunks_jsonl_sha256"],
        "benchmark_freeze_integrity": "PASS",
        "model_info": dense.get_model_info(),
        "frozen_parameters": {
            "decomposition_id": DECOMPOSITION_ID,
            "decomposition_input_fields": ["question"],
            "k_rrf": K_RRF,
            "rank_base": 1,
            "tie_break": "chunk_id ASC",
            "min_content_tokens": MIN_CONTENT_TOKENS,
            "max_queries_per_probe": MAX_QUERIES_PER_PROBE,
            "min_decomposed_probes_for_evaluation": MIN_DECOMPOSED_PROBES_FOR_EVALUATION,
            "hit10_major_collapse_delta": HIT10_MAJOR_COLLAPSE_DELTA,
            "representation": "DENSE_E5_SMALL_V1 parent-chunk (no window-max, no MMR)",
        },
        "relevance_control": {
            "reference_baseline_id": "DENSE_E5_SMALL_V1",
            "reference_detail_file": "DENSE_E5_SMALL_V1/cutoff_filtered_per_probe.jsonl",
            "reference_detail_sha256": f_detail_sha,
            "exact_ranking_reproduction": "PASS",
            "aggregate_reproduction": "PASS",
            "probe_count": len(probes),
        },
        "spoiler_cutoff_status": "PASS",
        "DECOMPOSITION_DIAGNOSTICS": decomp_diag,
        "CUTOFF_FILTERED": agg_cutoff,
        "GLOBAL_DIAGNOSTIC": agg_global,
        "CHANGE_DIAGNOSTICS_VS_Q0_CONTROL": change,
        "dense_diagnostics": {
            "probe_count": len(probes),
            "passage_count": len(doc_ids),
            "total_query_count": sum(len(q) for q in decompositions),
            "query_truncation_count": dense.query_truncation_count,
            "passage_truncation_count": dense.passage_truncation_count,
            "encoding_runtime_sec": round(t1 - t0, 3),
            "retrieval_evaluation_runtime_sec": round(eval_t1 - eval_t0, 3),
        },
        "detailed_results_sha256": detail_sha,
    }

    private = {
        "forbidden_strings": sorted(
            {p["question"] for p in probes}
            | {q for qs in decompositions for q in qs}
            | set(doc_ids)
            | {p["probe_id"] for p in probes}
        )
    }

    with open(out_dir / "aggregate_metrics.yaml", "w", encoding="utf-8") as f:
        yaml.dump(agg, f, sort_keys=False, allow_unicode=True)
    return agg, private


def strip_runtime(agg: dict) -> dict:
    a = copy.deepcopy(agg)
    for k in RUNTIME_ONLY_KEYS:
        a.get("dense_diagnostics", {}).pop(k, None)
    return a


def verify_multiquery_determinism(agg1: dict, agg2: dict) -> bool:
    if agg1["detailed_results_sha256"] != agg2["detailed_results_sha256"]:
        return False
    return json.dumps(strip_runtime(agg1), sort_keys=True) == json.dumps(strip_runtime(agg2), sort_keys=True)


def compare_with_f(agg_i: dict, f_agg: dict) -> dict:
    f_ov, i_ov = f_agg["CUTOFF_FILTERED"]["overall"], agg_i["CUTOFF_FILTERED"]["overall"]
    f_cat, i_cat = f_agg["CUTOFF_FILTERED"]["per_category"], agg_i["CUTOFF_FILTERED"]["per_category"]
    comp = {}
    for k in (1, 3, 5, 10):
        for label, key in (("Hit", "hit"), ("Recall", "recall"), ("Full_Evidence_Success", "success")):
            comp[f"{label}@{k}"] = {"I_MULTIQUERY": i_ov[f"{key}@{k}"], "F_SMALL": f_ov[f"{key}@{k}"],
                                    "delta": i_ov[f"{key}@{k}"] - f_ov[f"{key}@{k}"]}
    comp["MRR"] = {"I_MULTIQUERY": i_ov["mrr"], "F_SMALL": f_ov["mrr"], "delta": i_ov["mrr"] - f_ov["mrr"]}
    cat_comp = {}
    for cat in i_cat:
        cat_comp[cat] = {}
        for label, key in (("Hit@10", "hit@10"), ("Recall@10", "recall@10"),
                           ("Success@10", "success@10"), ("MRR", "mrr")):
            cat_comp[cat][f"I_{label}"] = i_cat[cat][key]
            cat_comp[cat][f"F_{label}"] = f_cat[cat][key]
            cat_comp[cat][f"delta_{label}"] = i_cat[cat][key] - f_cat[cat][key]
    return {"overall": comp, "per_category": cat_comp}


def main():
    base_dir = Path(__file__).resolve().parents[2]
    local = base_dir / ".local/story_integration/otonari_30ch"
    pub_dir = base_dir / "benchmarks/m1_script_quality/long_range_probe"
    probes = local / "LONG_RANGE_PROBE_V1/probes.yaml"
    chunks = local / "PARAGRAPH_PACK_V1/chunks.jsonl"
    out_dir = local / "DENSE_E5_MULTIQUERY_V1"
    freeze_yaml = pub_dir / "LONG_RANGE_PROBE_V1_FREEZE.yaml"
    f_detail = local / "DENSE_E5_SMALL_V1/cutoff_filtered_per_probe.jsonl"
    f_result = pub_dir / "DENSE_E5_SMALL_V1_RESULT.yaml"

    try:
        dense = DenseE5MultiQueryV1()
        agg1, private = run_multiquery(probes, chunks, out_dir, freeze_yaml, f_detail, f_result, dense=dense)
        print("Run 1 complete. Relevance control gate PASS.")
        dense2 = DenseE5MultiQueryV1()
        agg2, _ = run_multiquery(probes, chunks, out_dir, freeze_yaml, f_detail, f_result, dense=dense2)
        print("Run 2 complete. Relevance control gate PASS.")
    except GateFailure as e:
        print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)

    deterministic = verify_multiquery_determinism(agg1, agg2)
    if not deterministic:
        print("FAIL: Determinism check failed!", file=sys.stderr)

    with open(f_result, "r", encoding="utf-8") as f:
        f_agg = yaml.safe_load(f)
    comparison = compare_with_f(agg1, f_agg)
    agg1["DENSE_E5_SMALL_V1_COMPARISON"] = comparison
    agg1["deterministic_reproduction_status"] = "PASS" if deterministic else "FAIL"

    ov = comparison["overall"]
    agg1["verdict"] = interpret_verdict(
        ov["Recall@10"]["delta"], ov["Full_Evidence_Success@10"]["delta"], ov["Hit@10"]["delta"],
        agg1["DECOMPOSITION_DIAGNOSTICS"]["probes_with_multiple_queries"],
        gates_passed=deterministic,
    )

    agg1["privacy_status"] = "PASS"
    serialized = yaml.dump(agg1, sort_keys=False, allow_unicode=True)
    leaks = find_private_leaks(serialized, private["forbidden_strings"])
    if leaks:
        print(f"FAIL: privacy scan found {len(leaks)} private string(s) in public payload", file=sys.stderr)
        sys.exit(1)

    with open(out_dir / "run_manifest.yaml", "w", encoding="utf-8") as f:
        yaml.dump({"files": ["decomposition_manifest.jsonl", "query_embeddings.npz",
                             "relevance_control_per_probe.jsonl", "per_query_rankings.jsonl",
                             "multiquery_cutoff_per_probe.jsonl", "multiquery_global_per_probe.jsonl",
                             "aggregate_metrics.yaml"]}, f)

    with open(pub_dir / "DENSE_E5_MULTIQUERY_V1_RESULT.yaml", "w", encoding="utf-8") as f:
        f.write(serialized)

    print(f"Determinism: {agg1['deterministic_reproduction_status']}")
    print(f"Verdict: {agg1['verdict']}")
    if not deterministic:
        sys.exit(1)


if __name__ == "__main__":
    main()
