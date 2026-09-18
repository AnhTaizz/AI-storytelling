import copy
import gc
import hashlib
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import yaml

from tools.story_benchmark.bge_reranker_v2_m3_top30_v1 import (
    CANDIDATE_DEPTH,
    MODEL_ID,
    PAIR_FORMAT,
    PASSAGE_MAX_LENGTH,
    QUERY_MAX_LENGTH,
    SCORING_BATCH_SIZE,
    BgeRerankerV2M3,
    check_candidate_equality,
    evaluated_ranking,
    extract_candidates,
    interpret_verdict,
    rank_of,
    rerank_order,
    transition_type,
    within,
)
from tools.story_benchmark.dense_e5_large_v1 import calculate_metrics
from tools.story_benchmark.run_bm25_lexical_v1 import compute_spoiler_violations

BASELINE_ID = "BGE_RERANKER_V2_M3_TOP30_V1"
DETAIL = "cutoff_filtered_per_probe.jsonl"
METRIC_KEYS = [
    "hit@1", "hit@3", "hit@5", "hit@10",
    "recall@1", "recall@3", "recall@5", "recall@10",
    "success@1", "success@3", "success@5", "success@10",
    "spoiler_violation@1", "spoiler_violation@3", "spoiler_violation@5", "spoiler_violation@10",
    "mrr",
]
TRANSITIONS = ("STAY_TOP10", "K_TOP10_LOST_BY_RERANK", "RERANK_TOP10_GAIN_FROM_K", "STAY_OUTSIDE_TOP10")
CHUNK_ID_RE = re.compile(r"ch\d{3}_c\d{4}")
PROBE_ID_RE = re.compile(r"\bP_[A-Z]+_\d{2}\b")
TOL = 1e-9


class GateFailure(RuntimeError):
    pass


def sha256_file(p: Path) -> str:
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _yaml(p: Path):
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _rankings(p: Path) -> dict:
    out = {}
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                out[r["probe_id"]] = r["retrieved_chunk_ids"]
    return out


def write_jsonl(p: Path, rows):
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n")


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
    return {"overall": overall, "per_category": {c: dict(v) for c, v in sorted(by_cat.items())}}


def evaluate(probe, ranking, chunk_meta):
    m = calculate_metrics(probe, ranking)
    m.update(compute_spoiler_violations(probe, ranking, chunk_meta))
    return m


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------

def verify_inputs(paths) -> dict:
    for key, p in paths.items():
        if key != "out_dir" and not Path(p).exists():
            raise GateFailure(f"BLOCKED: missing required artifact {key}")
    freeze = _yaml(paths["freeze"])
    probes = _yaml(paths["probes"])["probes"]
    k_res, f_res, l_res = _yaml(paths["k_result"]), _yaml(paths["f_result"]), _yaml(paths["l_result"])
    if freeze.get("status") != "FROZEN" or freeze.get("probe_count") != len(probes):
        raise GateFailure("benchmark freeze status/probe count mismatch")
    hashes = {}
    for name, p, expected in (
        ("probe_file", paths["probes"], freeze["probe_file_sha256"]),
        ("chunks_jsonl", paths["chunks"], freeze["chunks_jsonl_sha256"]),
        ("k_cutoff_ranking", paths["k_detail"], k_res["detailed_results_sha256"][DETAIL]),
        ("f_cutoff_ranking", paths["f_detail"], f_res["detailed_results_sha256"][DETAIL]),
    ):
        actual = sha256_file(p)
        if actual != expected:
            raise GateFailure(f"{name} sha256 mismatch")
        hashes[name] = actual
    chunk_meta, texts = {}, {}
    fingerprints = set()
    with open(paths["chunks"], "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                c = json.loads(line)
                chunk_meta[c["chunk_id"]] = c["chapter_number"]
                texts[c["chunk_id"]] = c["text"]
                fingerprints.add(c.get("corpus_fingerprint_sha256"))
    if fingerprints != {freeze["corpus_fingerprint_sha256"]}:
        raise GateFailure("corpus fingerprint mismatch")
    units = sum(len(p["required_evidence_chunk_ids"]) for p in probes)
    if len(probes) != 15 or units != 35:
        raise GateFailure("population is not 15 probes / 35 units")
    if l_res["artifact_integrity"]["source_sha256"]["k_cutoff_ranking"] != hashes["k_cutoff_ranking"] or \
       l_res["artifact_integrity"]["source_sha256"]["f_cutoff_ranking"] != hashes["f_cutoff_ranking"]:
        raise GateFailure("L diagnostic was computed from different F/K rankings")
    return {"probes": probes, "chunk_meta": chunk_meta, "texts": texts, "hashes": hashes,
            "k_res": k_res, "f_res": f_res, "l_res": l_res,
            "corpus_fingerprint_sha256": freeze["corpus_fingerprint_sha256"]}


def reproduce_k_control(probes, k_rank, chunk_meta, k_res) -> dict:
    ml = [(p["category"], evaluate(p, k_rank[p["probe_id"]], chunk_meta)) for p in probes]
    agg = aggregate(ml)
    ov = k_res["CUTOFF_FILTERED"]["overall"]
    bad = [k for k in METRIC_KEYS if abs(agg["overall"][k] - ov[k]) > TOL]
    if bad:
        raise GateFailure(f"K control does not reproduce committed K metrics: {bad}")
    return agg


def l_lost_population(probes, f_rank, k_rank, l_res) -> list:
    pop = []
    for p in probes:
        for c in p["required_evidence_chunk_ids"]:
            fr, kr = rank_of(c, f_rank[p["probe_id"]]), rank_of(c, k_rank[p["probe_id"]])
            if within(fr, 10) and not within(kr, 10):
                pop.append((p["probe_id"], c, fr, kr))
    expected = l_res["all_required_evidence_transition_counts"]["counts"]["F_TOP10_LOST_BY_K"]
    if len(pop) != expected:
        raise GateFailure("L F_TOP10_LOST_BY_K population reconstruction mismatch")
    return pop


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def run_once(paths, reranker_factory=BgeRerankerV2M3):
    out = Path(paths["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    inp = verify_inputs(paths)
    probes, chunk_meta, texts = inp["probes"], inp["chunk_meta"], inp["texts"]
    k_rank, f_rank = _rankings(paths["k_detail"]), _rankings(paths["f_detail"])
    k_agg = reproduce_k_control(probes, k_rank, chunk_meta, inp["k_res"])
    l_pop = l_lost_population(probes, f_rank, k_rank, inp["l_res"])

    # Candidate pools and ceiling (before any scoring).
    candidates, pool_sizes = {}, {}
    for p in probes:
        pid = p["probe_id"]
        pool_sizes[pid] = len(k_rank[pid])
        candidates[pid] = extract_candidates(k_rank[pid])
        if any(chunk_meta[c] > p["cutoff_chapter"] for c in candidates[pid]):
            raise GateFailure("candidate beyond cutoff")
    complete = [p for p in probes if all(c in set(candidates[p["probe_id"]]) for c in p["required_evidence_chunk_ids"])]

    t0 = time.time()
    rr = reranker_factory()
    t1 = time.time()
    model_info = rr.get_model_info()
    if model_info["num_labels"] != 1 or model_info["dtype"] != "torch.float32":
        raise GateFailure("model identity gate: unexpected head or dtype")

    pair_rows, reranked_rows, r_metrics, r_rank = [], [], [], {}
    q_trunc = p_trunc = 0
    for p in probes:
        pid, cands = p["probe_id"], candidates[p["probe_id"]]
        scores = {}
        for c in cands:
            s, pair = rr.score(p["question"], texts[c])
            scores[c] = s
            q_trunc += int(pair["query_truncated"])
            p_trunc += int(pair["passage_truncated"])
            pair_rows.append({"probe_id": pid, "chunk_id": c, "k_rank": cands.index(c) + 1, "score": s,
                              "query_tokens": pair["query_tokens"], "passage_tokens": pair["passage_tokens"]})
        ordered = rerank_order(cands, scores)
        after = [c for c, _ in ordered]
        check_candidate_equality(cands, after, pool_sizes[pid])
        full = evaluated_ranking(after, k_rank[pid])
        r_rank[pid] = full
        m = evaluate(p, full, chunk_meta)  # gold read only after reordering
        r_metrics.append((p["category"], m))
        reranked_rows.append({"probe_id": pid, "category": p["category"], "reranked_top_candidates": after,
                              "scores": [s for _, s in ordered], "evaluated_ranking": full, "metrics": m})
    t2 = time.time()

    # Transitions K -> reranked.
    trans_rows = []
    for p in probes:
        for c in p["required_evidence_chunk_ids"]:
            kr, rrk = rank_of(c, k_rank[p["probe_id"]]), rank_of(c, r_rank[p["probe_id"]])
            trans_rows.append({"probe_id": p["probe_id"], "category": p["category"], "chunk_id": c,
                               "k_rank": kr, "reranked_rank": rrk, "transition": transition_type(kr, rrk)})
    probe_rows = []
    for p in probes:
        req = p["required_evidence_chunk_ids"]
        kin = [within(rank_of(c, k_rank[p["probe_id"]]), 10) for c in req]
        rin = [within(rank_of(c, r_rank[p["probe_id"]]), 10) for c in req]
        probe_rows.append({"probe_id": p["probe_id"], "k_hit": any(kin), "r_hit": any(rin),
                           "k_full": all(kin), "r_full": all(rin), "candidate_complete": p in complete})
    write_jsonl(out / "pair_scores.jsonl", pair_rows)
    write_jsonl(out / "reranked_per_probe.jsonl", reranked_rows)
    write_jsonl(out / "required_evidence_transitions.jsonl", trans_rows)
    write_jsonl(out / "probe_transitions.jsonl", probe_rows)

    r_agg = aggregate(r_metrics)
    if any(r_agg["overall"][f"spoiler_violation@{k}"] != 0.0 for k in (1, 3, 5, 10)):
        raise GateFailure("spoiler violation in reranked CUTOFF ranking")

    restored = sum(1 for pid, c, _, _ in l_pop if within(rank_of(c, r_rank[pid]), 10))
    tcounts = {t: sum(1 for r in trans_rows if r["transition"] == t) for t in TRANSITIONS}

    def n(key):
        return sum(1 for r in probe_rows if r[key])

    r_full = n("r_full")
    comp = {}
    for k in (1, 3, 5, 10):
        for label, key in (("Hit", "hit"), ("Recall", "recall"), ("Full_Evidence_Success", "success"),
                           ("Spoiler_Violation", "spoiler_violation")):
            comp[f"{label}@{k}"] = {"K": k_agg["overall"][f"{key}@{k}"], "RERANKED": r_agg["overall"][f"{key}@{k}"],
                                    "delta": r_agg["overall"][f"{key}@{k}"] - k_agg["overall"][f"{key}@{k}"]}
    comp["MRR"] = {"K": k_agg["overall"]["mrr"], "RERANKED": r_agg["overall"]["mrr"],
                   "delta": r_agg["overall"]["mrr"] - k_agg["overall"]["mrr"]}

    detail_sha = {name: sha256_file(out / name) for name in
                  ("reranked_per_probe.jsonl", "required_evidence_transitions.jsonl", "probe_transitions.jsonl", "pair_scores.jsonl")}

    agg = {
        "baseline_id": BASELINE_ID,
        "status": "EXECUTED",
        "benchmark_id": "LONG_RANGE_PROBE_V1",
        "candidate_source": {"baseline_id": "DENSE_E5_LARGE_V1", "mode": "CUTOFF_FILTERED",
                             "candidate_depth": CANDIDATE_DEPTH,
                             "evaluated_ranking": "reranked Top-30 followed by unchanged K ranks > 30"},
        "model_info": model_info,
        "pair_contract": {"format": PAIR_FORMAT,
                          "query_max_length": QUERY_MAX_LENGTH, "passage_max_length": PASSAGE_MAX_LENGTH,
                          "score": "raw classification logit (no sigmoid)", "scoring_batch_size": SCORING_BATCH_SIZE,
                          "tie_break": "score DESC, original K rank ASC, chunk_id ASC"},
        "input_integrity": {"benchmark_freeze": "PASS", "corpus_fingerprint_sha256": inp["corpus_fingerprint_sha256"],
                            **{f"{k}_sha256": v for k, v in inp["hashes"].items()},
                            "population": "PASS (15 probes / 35 units)", "k_control_reproduction": "PASS",
                            "l_population_reconstruction": "PASS", "model_identity": "PASS"},
        "candidate_set_integrity": {"status": "PASS", "probes": len(probes),
                                    "probes_with_full_depth_30": sum(1 for v in pool_sizes.values() if v >= CANDIDATE_DEPTH),
                                    "probes_with_fewer_than_30": sum(1 for v in pool_sizes.values() if v < CANDIDATE_DEPTH),
                                    "min_eligible_pool_size": min(pool_sizes.values()),
                                    "total_pairs_scored": len(pair_rows)},
        "K_CONTROL": k_agg,
        "RERANKED": r_agg,
        "K_COMPARISON": {"overall": comp},
        "F_HISTORICAL_CONTEXT": {"note": "historical only; F is not the control for M",
                                 "hit@10": inp["f_res"]["CUTOFF_FILTERED"]["overall"]["hit@10"],
                                 "recall@10": inp["f_res"]["CUTOFF_FILTERED"]["overall"]["recall@10"],
                                 "success@10": inp["f_res"]["CUTOFF_FILTERED"]["overall"]["success@10"],
                                 "mrr": inp["f_res"]["CUTOFF_FILTERED"]["overall"]["mrr"]},
        "candidate_ceiling": {"candidate_complete_probes": len(complete),
                              "candidate_complete_fraction": len(complete) / len(probes),
                              "reranked_full_success_probes": r_full,
                              "reranker_ceiling_utilization": (r_full / len(complete)) if complete else None,
                              "note": "descriptive only; evidence outside K Top-30 cannot be recovered"},
        "required_evidence_transitions": {"total_units": len(trans_rows), "counts": tcounts,
                                          "l_f_top10_lost_by_k_population": len(l_pop),
                                          "l_lost_restored_to_reranked_top10": restored},
        "probe_transitions": {"k_hit_probes": n("k_hit"), "reranked_hit_probes": n("r_hit"),
                              "k_full_success_probes": n("k_full"), "reranked_full_success_probes": r_full,
                              "hit_gained": sum(1 for r in probe_rows if r["r_hit"] and not r["k_hit"]),
                              "hit_lost": sum(1 for r in probe_rows if r["k_hit"] and not r["r_hit"]),
                              "full_success_gained": sum(1 for r in probe_rows if r["r_full"] and not r["k_full"]),
                              "full_success_lost": sum(1 for r in probe_rows if r["k_full"] and not r["r_full"])},
        "truncation_diagnostics": {"query_truncation_count": q_trunc, "passage_truncation_count": p_trunc,
                                   "pairs": len(pair_rows), "query_max_length": QUERY_MAX_LENGTH,
                                   "passage_max_length": PASSAGE_MAX_LENGTH},
        "runtime_diagnostics": {"model_load_runtime_sec": round(t1 - t0, 3),
                                "scoring_runtime_sec": round(t2 - t1, 3)},
        "detailed_results_sha256": detail_sha,
    }
    forbidden = sorted({p["probe_id"] for p in probes} | {p["question"] for p in probes}
                       | {str(p["expected_answer"]) for p in probes if p.get("expected_answer")}
                       | set(chunk_meta))
    del rr
    gc.collect()
    return agg, forbidden


def strip_runtime(a: dict) -> dict:
    b = copy.deepcopy(a)
    b.pop("runtime_diagnostics", None)
    return b


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


def finalize(a1: dict, a2: dict) -> dict:
    ok = verify_determinism(a1, a2)
    out = copy.deepcopy(a1)
    out["deterministic_reproduction_status"] = "PASS" if ok else "FAIL"
    out["privacy_status"] = "PASS"
    c = out["K_COMPARISON"]["overall"]
    pt = out["probe_transitions"]
    out["verdict"] = interpret_verdict(c["Full_Evidence_Success@10"]["delta"], c["Recall@10"]["delta"],
                                       c["Hit@10"]["delta"], pt["k_full_success_probes"],
                                       pt["reranked_full_success_probes"], gates_passed=ok)
    return out


def default_paths(base: Path) -> dict:
    local = base / ".local/story_integration/otonari_30ch"
    pub = base / "benchmarks/m1_script_quality/long_range_probe"
    return {
        "probes": local / "LONG_RANGE_PROBE_V1/probes.yaml",
        "chunks": local / "PARAGRAPH_PACK_V1/chunks.jsonl",
        "freeze": pub / "LONG_RANGE_PROBE_V1_FREEZE.yaml",
        "k_result": pub / "DENSE_E5_LARGE_V1_RESULT.yaml",
        "k_detail": local / "DENSE_E5_LARGE_V1" / DETAIL,
        "f_result": pub / "DENSE_E5_SMALL_V1_RESULT.yaml",
        "f_detail": local / "DENSE_E5_SMALL_V1" / DETAIL,
        "l_result": pub / "K_RANK_TRANSITION_DIAGNOSTIC_V1_RESULT.yaml",
        "out_dir": local / BASELINE_ID,
    }


def main():
    base = Path(__file__).resolve().parents[2]
    paths = default_paths(base)
    try:
        a1, forbidden = run_once(paths)
        print("Run 1 complete.", flush=True)
        a2, _ = run_once(paths)
        print("Run 2 complete.", flush=True)
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
    result = finalize(a1, a2)
    text = yaml.dump(result, sort_keys=False, allow_unicode=True)
    leaks = find_private_leaks(text, forbidden)
    if leaks:
        print(f"FAIL: privacy scan found {len(leaks)} private item(s)", file=sys.stderr)
        sys.exit(1)
    with open(Path(paths["out_dir"]) / "aggregate_metrics.yaml", "w", encoding="utf-8") as f:
        f.write(text)
    with open(base / "benchmarks/m1_script_quality/long_range_probe" / f"{BASELINE_ID}_RESULT.yaml", "w",
              encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"Determinism: {result['deterministic_reproduction_status']}")
    print(f"Verdict: {result['verdict']}")
    if result["deterministic_reproduction_status"] != "PASS":
        sys.exit(1)


if __name__ == "__main__":
    main()
