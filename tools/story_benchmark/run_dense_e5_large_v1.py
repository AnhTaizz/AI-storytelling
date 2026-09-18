import copy
import gc
import hashlib
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import yaml

from tools.story_benchmark.dense_e5_large_v1 import (
    COMPLETENESS_KS,
    EXPECTED_EMBEDDING_DIMENSION,
    MAX_SEQ_LENGTH,
    MODEL_ID,
    MODEL_REVISION,
    PASSAGE_ENCODE_BATCH_SIZE,
    QUERY_PREFIX,
    PASSAGE_PREFIX,
    DenseE5LargeV1,
    calculate_metrics,
    completeness_curve,
    eligible_doc_ids,
    f_missed_population,
    interpret_verdict,
    rank_bucket,
    rank_shift_aggregate,
    rank_shift_rows,
)
from tools.story_benchmark.run_bm25_lexical_v1 import compute_spoiler_violations

BASELINE_ID = "DENSE_E5_LARGE_V1"
METRIC_KEYS = [
    "hit@1", "hit@3", "hit@5", "hit@10",
    "recall@1", "recall@3", "recall@5", "recall@10",
    "success@1", "success@3", "success@5", "success@10",
    "spoiler_violation@1", "spoiler_violation@3", "spoiler_violation@5", "spoiler_violation@10",
    "mrr",
]
RUNTIME_ONLY_KEYS = ("model_load_runtime_sec", "encoding_runtime_sec", "retrieval_evaluation_runtime_sec")
CHUNK_ID_RE = re.compile(r"ch\d{3}_c\d{4}")
PROBE_ID_RE = re.compile(r"\bP_[A-Z]+_\d{2}\b")
TOL = 1e-9


class GateFailure(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def write_jsonl(path: Path, rows):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")


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


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------

def verify_inputs(paths) -> dict:
    for key, p in paths.items():
        if key != "out_dir" and not Path(p).exists():
            raise GateFailure(f"BLOCKED: missing required artifact {key}")
    with open(paths["freeze"], "r", encoding="utf-8") as f:
        freeze = yaml.safe_load(f)
    with open(paths["probes"], "r", encoding="utf-8") as f:
        probes = yaml.safe_load(f)["probes"]
    if freeze.get("status") != "FROZEN":
        raise GateFailure("benchmark freeze status is not FROZEN")
    if freeze.get("probe_count") != 15 or len(probes) != freeze["probe_count"]:
        raise GateFailure("probe count mismatch")
    psha, csha = sha256_file(paths["probes"]), sha256_file(paths["chunks"])
    if psha != freeze["probe_file_sha256"]:
        raise GateFailure("probe file sha256 mismatch vs freeze")
    if csha != freeze["chunks_jsonl_sha256"]:
        raise GateFailure("chunks sha256 mismatch vs freeze")
    with open(paths["chunks"], "r", encoding="utf-8") as f:
        first = json.loads(f.readline())
    if first.get("corpus_fingerprint_sha256") != freeze["corpus_fingerprint_sha256"]:
        raise GateFailure("chunk corpus fingerprint mismatch vs freeze")
    return {"freeze": freeze, "probes": probes, "probe_file_sha256": psha, "chunks_jsonl_sha256": csha,
            "corpus_fingerprint_sha256": freeze["corpus_fingerprint_sha256"]}


def load_f_control(paths) -> dict:
    with open(paths["f_result"], "r", encoding="utf-8") as f:
        f_res = yaml.safe_load(f)
    expected = f_res["detailed_results_sha256"]["cutoff_filtered_per_probe.jsonl"]
    actual = sha256_file(paths["f_detail"])
    if actual != expected:
        raise GateFailure("F detailed ranking sha256 mismatch vs DENSE_E5_SMALL_V1_RESULT.yaml")
    rankings = {}
    with open(paths["f_detail"], "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                rankings[r["probe_id"]] = r["retrieved_chunk_ids"]
    return {"result": f_res, "rankings": rankings, "detail_sha256": actual}


def reconstruct_j(probes, f_rankings, j_res: dict, f_detail_sha: str) -> list:
    """Rebuild J's F-missed population from gold + verified F ranking and check it against committed J."""
    if j_res["artifact_integrity"]["source_sha256"]["f_cutoff_ranking"] != f_detail_sha:
        raise GateFailure("J was computed from a different F ranking")
    pop = f_missed_population(probes, f_rankings)
    total_units = sum(len(p["required_evidence_chunk_ids"]) for p in probes)
    buckets = defaultdict(int)
    for u in pop:
        buckets[rank_bucket(u["f_rank"])] += 1
    jm = j_res["f_missed_evidence_bucket_distribution"]
    checks = [
        (total_units, j_res["required_evidence_unit_count"]),
        (len(pop), j_res["candidate_reachability"]["f_top10_missed_units"]),
        (buckets["11-20"], jm["rank_11_20"]["count"]),
        (buckets["21-50"], jm["rank_21_50"]["count"]),
        (buckets[">50"], jm["rank_gt_50"]["count"]),
        (buckets["missing"], jm["missing"]["count"]),
    ]
    if any(a != b for a, b in checks):
        raise GateFailure(f"J population reconstruction mismatch: {checks}")
    f_curve = completeness_curve(probes, f_rankings)
    for k in COMPLETENESS_KS:
        jc = j_res["probe_completeness_by_k"][f"K{k}"]
        if abs(f_curve[f"K{k}"]["recall"] - jc["recall"]) > TOL or \
           abs(f_curve[f"K{k}"]["full_evidence_success"] - jc["full_evidence_success"]) > TOL:
            raise GateFailure(f"J completeness curve mismatch at K={k}")
    return pop


def aggregate(metrics_list):
    overall = {k: 0.0 for k in METRIC_KEYS}
    by_cat = defaultdict(lambda: {k: 0.0 for k in METRIC_KEYS})
    counts = defaultdict(int)
    for cat, m in metrics_list:
        counts[cat] += 1
        for k in METRIC_KEYS:
            overall[k] += m[k]
            by_cat[cat][k] += m[k]
    n = len(metrics_list)
    for k in METRIC_KEYS:
        overall[k] /= n
        for c in by_cat:
            by_cat[c][k] /= counts[c]
    return {"overall": overall, "per_category": {c: dict(v) for c, v in by_cat.items()}}


def compare_with_f(k_agg: dict, f_res: dict) -> dict:
    f_ov, k_ov = f_res["CUTOFF_FILTERED"]["overall"], k_agg["overall"]
    f_cat, k_cat = f_res["CUTOFF_FILTERED"]["per_category"], k_agg["per_category"]
    comp = {}
    for k in (1, 3, 5, 10):
        for label, key in (("Hit", "hit"), ("Recall", "recall"), ("Full_Evidence_Success", "success"),
                           ("Spoiler_Violation", "spoiler_violation")):
            comp[f"{label}@{k}"] = {"K_LARGE": k_ov[f"{key}@{k}"], "F_SMALL": f_ov[f"{key}@{k}"],
                                    "delta": k_ov[f"{key}@{k}"] - f_ov[f"{key}@{k}"]}
    comp["MRR"] = {"K_LARGE": k_ov["mrr"], "F_SMALL": f_ov["mrr"], "delta": k_ov["mrr"] - f_ov["mrr"]}
    cats = {}
    for c in sorted(k_cat):
        cats[c] = {}
        for label, key in (("Hit@10", "hit@10"), ("Recall@10", "recall@10"), ("Success@10", "success@10"), ("MRR", "mrr")):
            cats[c][f"K_{label}"] = k_cat[c][key]
            cats[c][f"F_{label}"] = f_cat[c][key]
            cats[c][f"delta_{label}"] = k_cat[c][key] - f_cat[c][key]
    return {"overall": comp, "per_category": cats}


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def run_once(paths, dense_factory=DenseE5LargeV1) -> (dict, dict):
    out_dir = Path(paths["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    inp = verify_inputs(paths)
    probes = inp["probes"]
    f_ctl = load_f_control(paths)
    with open(paths["j_result"], "r", encoding="utf-8") as f:
        j_res = yaml.safe_load(f)
    population = reconstruct_j(probes, f_ctl["rankings"], j_res, f_ctl["detail_sha256"])

    chunk_meta, doc_ids, texts = load_chunks(paths["chunks"])

    t0 = time.time()
    dense = dense_factory()
    t1 = time.time()
    model_info = dense.get_model_info()
    if model_info["embedding_dimension"] != EXPECTED_EMBEDDING_DIMENSION or model_info["max_seq_length"] != MAX_SEQ_LENGTH:
        raise GateFailure("model identity gate: embedding dimension / max_seq_length mismatch")

    dense.encode_documents(doc_ids, texts)
    t2 = time.time()
    np.save(str(out_dir / "passage_embeddings.npy"), dense.doc_embeddings)

    cutoff_rows, global_rows, cutoff_m, global_m = [], [], [], []
    k_rankings, q_embs = {}, []
    for p in probes:
        q = dense.encode_queries([p["question"]])[0]
        q_embs.append(q)
        for mode, allowed, rows, mlist in (
            ("CUTOFF_FILTERED", eligible_doc_ids(chunk_meta, p["cutoff_chapter"]), cutoff_rows, cutoff_m),
            ("GLOBAL_DIAGNOSTIC", None, global_rows, global_m),
        ):
            ranked = dense.score_embedding(q, allowed_doc_ids=allowed)
            ids = [d for d, _ in ranked]
            m = calculate_metrics(p, ids)  # gold read only after ranking
            m.update(compute_spoiler_violations(p, ids, chunk_meta))
            rows.append({"probe_id": p["probe_id"], "category": p["category"], "cutoff_chapter": p["cutoff_chapter"],
                         "required_evidence_chunk_ids": p["required_evidence_chunk_ids"],
                         "retrieved_chunk_ids": ids, "scores": [float(s) for _, s in ranked], "metrics": m})
            mlist.append((p["category"], m))
            if mode == "CUTOFF_FILTERED":
                k_rankings[p["probe_id"]] = ids
    t3 = time.time()
    np.save(str(out_dir / "query_embeddings.npy"), np.array(q_embs))

    write_jsonl(out_dir / "cutoff_filtered_per_probe.jsonl", cutoff_rows)
    write_jsonl(out_dir / "global_diagnostic_per_probe.jsonl", global_rows)
    shift_rows = rank_shift_rows(population, k_rankings)
    write_jsonl(out_dir / "f_missed_rank_shift.jsonl", shift_rows)

    agg_cut, agg_glob = aggregate(cutoff_m), aggregate(global_m)
    if any(agg_cut["overall"][f"spoiler_violation@{k}"] != 0.0 for k in (1, 3, 5, 10)):
        raise GateFailure("CUTOFF_FILTERED spoiler violation detected")

    f_diag = f_ctl["result"]["dense_diagnostics"]
    detail_sha = {n: sha256_file(out_dir / n) for n in
                  ("cutoff_filtered_per_probe.jsonl", "global_diagnostic_per_probe.jsonl", "f_missed_rank_shift.jsonl")}

    k_curve = completeness_curve(probes, k_rankings)
    j_curve = j_res["probe_completeness_by_k"]
    curve = {f"K{k}": {
        "F_recall": j_curve[f"K{k}"]["recall"], "K_recall": k_curve[f"K{k}"]["recall"],
        "delta_recall": k_curve[f"K{k}"]["recall"] - j_curve[f"K{k}"]["recall"],
        "F_full_evidence_success": j_curve[f"K{k}"]["full_evidence_success"],
        "K_full_evidence_success": k_curve[f"K{k}"]["full_evidence_success"],
        "delta_full_evidence_success": k_curve[f"K{k}"]["full_evidence_success"] - j_curve[f"K{k}"]["full_evidence_success"],
    } for k in COMPLETENESS_KS}

    agg = {
        "baseline_id": BASELINE_ID,
        "status": "EXECUTED",
        "benchmark_id": "LONG_RANGE_PROBE_V1",
        "reference_baseline_id": "DENSE_E5_SMALL_V1",
        "model_info": model_info,
        "retrieval_contract": {
            "representation": "one embedding per original parent chunk (PARAGRAPH_PACK_V1); no windows",
            "query_prefix": QUERY_PREFIX,
            "passage_prefix": PASSAGE_PREFIX,
            "max_seq_length": MAX_SEQ_LENGTH,
            "normalize_embeddings": True,
            "similarity": "dot product of unit-normalized embeddings (cosine)",
            "tie_break": "chunk_id ASC",
            "passage_encode_batch_size": PASSAGE_ENCODE_BATCH_SIZE,
            "query_encode": "one query per encode call (same as F)",
        },
        "input_integrity": {
            "benchmark_freeze": "PASS",
            "probe_file_sha256": inp["probe_file_sha256"],
            "chunks_jsonl_sha256": inp["chunks_jsonl_sha256"],
            "corpus_fingerprint_sha256": inp["corpus_fingerprint_sha256"],
            "f_detailed_ranking": "PASS",
            "f_detailed_ranking_sha256": f_ctl["detail_sha256"],
            "j_population_reconstruction": "PASS",
            "model_identity": "PASS",
        },
        "CUTOFF_FILTERED": agg_cut,
        "GLOBAL_DIAGNOSTIC": agg_glob,
        "J_MISSED_EVIDENCE_RANK_DIAGNOSTIC": rank_shift_aggregate(shift_rows),
        "COMPLETENESS_CURVE": {"note": "Diagnostic depths from the frozen rankings; F values read from the committed J result.",
                               **curve},
        "truncation_diagnostics": {
            "k_query_truncation_count": dense.query_truncation_count,
            "k_passage_truncation_count": dense.passage_truncation_count,
            "f_query_truncation_count": f_diag["query_truncation_count"],
            "f_passage_truncation_count": f_diag["passage_truncation_count"],
            "passage_count": len(doc_ids),
            "probe_count": len(probes),
        },
        "runtime_diagnostics": {
            "model_load_runtime_sec": round(t1 - t0, 3),
            "encoding_runtime_sec": round(t2 - t1, 3),
            "retrieval_evaluation_runtime_sec": round(t3 - t2, 3),
        },
        "detailed_results_sha256": detail_sha,
    }
    private = {"forbidden_strings": sorted(
        {p["probe_id"] for p in probes} | {p["question"] for p in probes}
        | {str(p["expected_answer"]) for p in probes if p.get("expected_answer")}
        | set(doc_ids))}

    del dense
    gc.collect()
    return agg, private


def strip_runtime(agg: dict) -> dict:
    a = copy.deepcopy(agg)
    a.pop("runtime_diagnostics", None)
    return a


def verify_determinism(a1: dict, a2: dict) -> bool:
    return (a1["detailed_results_sha256"] == a2["detailed_results_sha256"]
            and json.dumps(strip_runtime(a1), sort_keys=True) == json.dumps(strip_runtime(a2), sort_keys=True))


def find_private_leaks(text: str, forbidden) -> list:
    leaks = sorted({s for s in forbidden if s and s in text})
    if CHUNK_ID_RE.search(text):
        leaks.append("<chunk-id pattern>")
    if PROBE_ID_RE.search(text):
        leaks.append("<probe-id pattern>")
    return leaks


def finalize(agg1: dict, agg2: dict, f_res: dict) -> dict:
    deterministic = verify_determinism(agg1, agg2)
    out = copy.deepcopy(agg1)
    out["F_COMPARISON"] = compare_with_f(out["CUTOFF_FILTERED"], f_res)
    out["deterministic_reproduction_status"] = "PASS" if deterministic else "FAIL"
    ov = out["F_COMPARISON"]["overall"]
    out["privacy_status"] = "PASS"
    out["verdict"] = interpret_verdict(
        ov["Recall@10"]["delta"], ov["Full_Evidence_Success@10"]["delta"], ov["Hit@10"]["delta"],
        out["J_MISSED_EVIDENCE_RANK_DIAGNOSTIC"]["f_gt20_to_k_le20"], gates_passed=deterministic)
    return out


def default_paths(base_dir: Path) -> dict:
    local = base_dir / ".local/story_integration/otonari_30ch"
    pub = base_dir / "benchmarks/m1_script_quality/long_range_probe"
    return {
        "probes": local / "LONG_RANGE_PROBE_V1/probes.yaml",
        "chunks": local / "PARAGRAPH_PACK_V1/chunks.jsonl",
        "freeze": pub / "LONG_RANGE_PROBE_V1_FREEZE.yaml",
        "f_result": pub / "DENSE_E5_SMALL_V1_RESULT.yaml",
        "f_detail": local / "DENSE_E5_SMALL_V1/cutoff_filtered_per_probe.jsonl",
        "j_result": pub / "MISSING_EVIDENCE_RANK_DIAGNOSTIC_V1_RESULT.yaml",
        "out_dir": local / BASELINE_ID,
    }


def main():
    base_dir = Path(__file__).resolve().parents[2]
    paths = default_paths(base_dir)
    try:
        agg1, private = run_once(paths)
        print("Run 1 complete.", flush=True)
        agg2, _ = run_once(paths)
        print("Run 2 complete.", flush=True)
    except Exception as e:  # gates and model identity errors both stop the experiment
        print(f"FAIL: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)

    with open(paths["f_result"], "r", encoding="utf-8") as f:
        f_res = yaml.safe_load(f)
    result = finalize(agg1, agg2, f_res)
    serialized = yaml.dump(result, sort_keys=False, allow_unicode=True)
    leaks = find_private_leaks(serialized, private["forbidden_strings"])
    if leaks:
        print(f"FAIL: privacy scan found {len(leaks)} private item(s)", file=sys.stderr)
        sys.exit(1)
    with open(Path(paths["out_dir"]) / "aggregate_metrics.yaml", "w", encoding="utf-8") as f:
        f.write(serialized)
    out = base_dir / "benchmarks/m1_script_quality/long_range_probe" / f"{BASELINE_ID}_RESULT.yaml"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(serialized)
    print(f"Determinism: {result['deterministic_reproduction_status']}")
    print(f"Verdict: {result['verdict']}")
    if result["deterministic_reproduction_status"] != "PASS":
        sys.exit(1)


if __name__ == "__main__":
    main()
