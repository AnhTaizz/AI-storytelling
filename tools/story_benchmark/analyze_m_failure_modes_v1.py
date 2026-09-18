"""
M_FAILURE_MODE_DIAGNOSTIC_V1 (TASK M1-30CH-N)

Diagnostic only: explains why candidate-complete probes still fail Full Evidence Success@10 after
BGE_RERANKER_V2_M3_TOP30_V1 (M). Reads existing M/K artifacts; no model, no reranking.

See benchmarks/m1_script_quality/long_range_probe/M_FAILURE_MODE_DIAGNOSTIC_V1_METHOD.md
"""
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence

import yaml

DIAGNOSTIC_ID = "M_FAILURE_MODE_DIAGNOSTIC_V1"
M_ID = "BGE_RERANKER_V2_M3_TOP30_V1"
M_FILES = ("reranked_per_probe.jsonl", "required_evidence_transitions.jsonl", "probe_transitions.jsonl", "pair_scores.jsonl")
K_DETAIL = "cutoff_filtered_per_probe.jsonl"
CANDIDATE_DEPTH = 30
PASSAGE_MAX_LENGTH = 512
MISSING_BUCKETS = ("11-15", "16-20", "21-30")
TRANSITIONS = ("STAY_TOP10", "K_TOP10_LOST_BY_RERANK", "RERANK_TOP10_GAIN_FROM_K", "STAY_OUTSIDE_TOP10")
METRIC_KEYS = [
    "hit@1", "hit@3", "hit@5", "hit@10", "recall@1", "recall@3", "recall@5", "recall@10",
    "success@1", "success@3", "success@5", "success@10",
    "spoiler_violation@1", "spoiler_violation@3", "spoiler_violation@5", "spoiler_violation@10", "mrr",
]
NEAR_BOUNDARY_DOMINANT_MIN_FRACTION = 2 / 3
TRUNCATION_ENRICHMENT_MIN_DIFF = 0.20
TOL = 1e-9
CHUNK_ID_RE = re.compile(r"ch\d{3}_c\d{4}")
PROBE_ID_RE = re.compile(r"\bP_[A-Z]+_\d{2}\b")


class GateFailure(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def sha256_file(p: Path) -> str:
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def rank_of(chunk_id: str, ranking: Sequence[str]) -> Optional[int]:
    try:
        return list(ranking).index(chunk_id) + 1
    except ValueError:
        return None


def within(rank: Optional[int], k: int) -> bool:
    return rank is not None and rank <= k


def missing_bucket(rank: Optional[int]) -> str:
    if rank is None or rank > CANDIDATE_DEPTH:
        raise GateFailure("missing required unit outside candidate-complete Top-30 (artifact inconsistency)")
    if rank <= 10:
        raise ValueError("not a missing unit")
    if rank <= 15:
        return "11-15"
    if rank <= 20:
        return "16-20"
    return "21-30"


def is_truncation_exposed(passage_tokens: int) -> bool:
    return passage_tokens > PASSAGE_MAX_LENGTH


def score_gap_to_top10(m_rank10_score: float, m_score: float) -> float:
    return m_rank10_score - m_score


def probe_label(missing_ranks: Sequence[int]) -> str:
    if not missing_ranks:
        raise ValueError("a failure probe has at least one missing unit")
    return "NEAR_BOUNDARY_ORDERING" if all(11 <= r <= 15 for r in missing_ranks) else "MID_POOL_ORDERING"


def stats(xs: Sequence[float]) -> dict:
    s = sorted(xs)
    if not s:
        return {"n": 0, "min": None, "median": None, "mean": None, "max": None}
    m = len(s) // 2
    med = s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2
    return {"n": len(s), "min": float(s[0]), "median": float(med), "mean": float(sum(s) / len(s)), "max": float(s[-1])}


def truncation_summary(flags: Sequence[bool]) -> dict:
    n = len(flags)
    t = sum(1 for f in flags if f)
    return {"count": n, "truncated_count": t, "non_truncated_count": n - t,
            "truncated_fraction": (t / n) if n else None}


def enrichment_statement(missing_frac: Optional[float], promoted_frac: Optional[float]) -> dict:
    if missing_frac is None or promoted_frac is None:
        return {"difference": None, "statement": "insufficient data"}
    diff = missing_frac - promoted_frac
    stmt = ("associated with truncation exposure" if diff >= TRUNCATION_ENRICHMENT_MIN_DIFF - TOL
            else "no clear enrichment in truncation exposure")
    return {"difference": diff, "statement": stmt}


def find_private_leaks(text: str, forbidden: Sequence[str]) -> List[str]:
    leaks = sorted({s for s in forbidden if s and s in text})
    if CHUNK_ID_RE.search(text):
        leaks.append("<chunk-id pattern>")
    if PROBE_ID_RE.search(text):
        leaks.append("<probe-id pattern>")
    return leaks


# ---------------------------------------------------------------------------
# Loading + gates
# ---------------------------------------------------------------------------

def _yaml(p: Path):
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _jsonl(p: Path) -> List[dict]:
    with open(p, "r", encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def verify_sources(paths: Mapping[str, Path]) -> dict:
    for key, p in paths.items():
        if key == "out_dir":
            continue
        if key == "m_dir":
            for name in M_FILES:
                if not (Path(p) / name).exists():
                    raise GateFailure(f"BLOCKED: missing required artifact {name}")
        elif not Path(p).exists():
            raise GateFailure(f"BLOCKED: missing required artifact {key}")
    freeze, k_res, m_res = _yaml(paths["freeze"]), _yaml(paths["k_result"]), _yaml(paths["m_result"])
    if freeze.get("status") != "FROZEN":
        raise GateFailure("BLOCKED: benchmark not FROZEN")
    checks = [("probe_file", paths["probes"], freeze["probe_file_sha256"]),
              ("chunks_jsonl", paths["chunks"], freeze["chunks_jsonl_sha256"]),
              ("k_cutoff_ranking", paths["k_detail"], k_res["detailed_results_sha256"][K_DETAIL])]
    checks += [(f"m_{n}", Path(paths["m_dir"]) / n, m_res["detailed_results_sha256"][n]) for n in M_FILES]
    hashes = {}
    for name, p, expected in checks:
        actual = sha256_file(p)
        if actual != expected:
            raise GateFailure(f"BLOCKED: {name} sha256 mismatch")
        hashes[name] = actual
    return {"hashes": hashes, "m_res": m_res, "freeze": freeze}


def _aggregate_overall(metric_rows: Sequence[dict]) -> dict:
    n = len(metric_rows)
    return {k: sum(m[k] for m in metric_rows) / n for k in METRIC_KEYS}


def reproduce_m(probes, chunk_meta, reranked, transitions, probe_trans, pairs, m_res, expected_population=(15, 35)) -> None:
    from tools.story_benchmark.dense_e5_large_v1 import calculate_metrics
    from tools.story_benchmark.run_bm25_lexical_v1 import compute_spoiler_violations
    if expected_population is not None and (len(probes), sum(len(p["required_evidence_chunk_ids"]) for p in probes)) != tuple(expected_population):
        raise GateFailure("population is not 15 probes / 35 units")
    by = {r["probe_id"]: r for r in reranked}
    rows = []
    for p in probes:
        m = calculate_metrics(p, by[p["probe_id"]]["evaluated_ranking"])
        m.update(compute_spoiler_violations(p, by[p["probe_id"]]["evaluated_ranking"], chunk_meta))
        rows.append(m)
    ov, ref = _aggregate_overall(rows), m_res["RERANKED"]["overall"]
    bad = [k for k in METRIC_KEYS if abs(ov[k] - ref[k]) > TOL]
    if bad:
        raise GateFailure(f"M RERANKED metrics not reproduced: {bad}")
    counts = {t: sum(1 for r in transitions if r["transition"] == t) for t in TRANSITIONS}
    if counts != m_res["required_evidence_transitions"]["counts"]:
        raise GateFailure("M transition counts not reproduced")
    if sum(1 for r in probe_trans if r["candidate_complete"]) != m_res["candidate_ceiling"]["candidate_complete_probes"]:
        raise GateFailure("candidate-complete count not reproduced")
    if sum(1 for r in probe_trans if r["r_full"]) != m_res["probe_transitions"]["reranked_full_success_probes"]:
        raise GateFailure("reranked full-success count not reproduced")
    if sum(1 for r in pairs if is_truncation_exposed(r["passage_tokens"])) != m_res["truncation_diagnostics"]["passage_truncation_count"]:
        raise GateFailure("passage truncation count not reproduced from recorded passage_tokens")


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyze(probes, k_rank: Dict[str, List[str]], reranked, transitions, probe_trans, pairs) -> dict:
    rr = {r["probe_id"]: r for r in reranked}
    pair_by = {(r["probe_id"], r["chunk_id"]): r for r in pairs}
    trans_by = {(r["probe_id"], r["chunk_id"]): r for r in transitions}
    pt_by = {r["probe_id"]: r for r in probe_trans}

    units, fail_probes = [], []
    candidate_complete = 0
    for p in probes:
        pid, req = p["probe_id"], p["required_evidence_chunk_ids"]
        top30 = k_rank[pid][:CANDIDATE_DEPTH]
        complete = all(c in top30 for c in req)
        if complete != pt_by[pid]["candidate_complete"]:
            raise GateFailure("candidate-complete flag disagrees with M probe_transitions")
        if not complete:
            continue
        candidate_complete += 1
        ranking = rr[pid]["evaluated_ranking"]
        m_ranks = [rank_of(c, ranking) for c in req]
        if all(within(r, 10) for r in m_ranks):
            continue
        rank10_score = rr[pid]["scores"][9]
        rows = []
        for c, mr in zip(req, m_ranks):
            kr = rank_of(c, k_rank[pid])
            if (kr, mr) != (trans_by[(pid, c)]["k_rank"], trans_by[(pid, c)]["reranked_rank"]):
                raise GateFailure("rank disagreement with M required_evidence_transitions")
            pr = pair_by[(pid, c)]
            row = {"probe_id": pid, "category": p["category"], "chunk_id": c, "k_rank": kr, "m_rank": mr,
                   "rank_delta": mr - kr, "in_m_top10": within(mr, 10), "m_score": pr["score"],
                   "m_rank10_score": rank10_score, "score_gap_to_top10": score_gap_to_top10(rank10_score, pr["score"]),
                   "passage_tokens": pr["passage_tokens"],
                   "passage_truncated": is_truncation_exposed(pr["passage_tokens"]),
                   "transition": trans_by[(pid, c)]["transition"]}
            if not row["in_m_top10"]:
                row["missing_bucket"] = missing_bucket(mr)
            rows.append(row)
        units.extend(rows)
        missing = [r for r in rows if not r["in_m_top10"]]
        mr_missing = [r["m_rank"] for r in missing]
        fail_probes.append({
            "probe_id": pid, "category": p["category"], "required_count": len(req),
            "required_in_m_top10": len(req) - len(missing), "missing_required_count": len(missing),
            "worst_required_m_rank": max(m_ranks), "best_missing_m_rank": min(mr_missing),
            "worst_missing_m_rank": max(mr_missing),
            "all_missing_within_15": all(r <= 15 for r in mr_missing),
            "any_missing_rank_16_30": any(r >= 16 for r in mr_missing),
            "any_missing_truncation_exposed": any(r["passage_truncated"] for r in missing),
            "all_missing_truncation_exposed": all(r["passage_truncated"] for r in missing),
            "K_full_success_top10": pt_by[pid]["k_full"], "M_full_success_top10": pt_by[pid]["r_full"],
            "label": probe_label(mr_missing),
            "truncation_exposed_flag": any(r["passage_truncated"] for r in missing),
        })

    missing = [u for u in units if not u["in_m_top10"]]
    promoted = [u for u in units if u["in_m_top10"]]
    n_miss = len(missing)
    bucket_counts = {b: sum(1 for u in missing if u["missing_bucket"] == b) for b in MISSING_BUCKETS}

    miss_tr = truncation_summary([u["passage_truncated"] for u in missing])
    prom_tr = truncation_summary([u["passage_truncated"] for u in promoted])

    label_counts = defaultdict(int)
    for fp in fail_probes:
        label_counts[f"{fp['label']}+{'TRUNCATION_EXPOSED' if fp['truncation_exposed_flag'] else 'NOT_TRUNCATION_EXPOSED'}"] += 1

    near_frac = (bucket_counts["11-15"] / n_miss) if n_miss else None
    return {
        "units": units, "fail_probes": fail_probes,
        "public": {
            "population": {
                "probe_count": len(probes),
                "required_evidence_units": sum(len(p["required_evidence_chunk_ids"]) for p in probes),
                "candidate_complete_probes": candidate_complete,
                "candidate_complete_full_success_probes": candidate_complete - len(fail_probes),
                "candidate_complete_failure_probes": len(fail_probes),
                "required_units_in_failure_probes": len(units),
                "missing_required_units": n_miss,
                "promoted_required_units": len(promoted),
            },
            "missing_required_rank_distribution": {
                "buckets": {b: {"count": c, "fraction": (c / n_miss) if n_miss else 0.0} for b, c in bucket_counts.items()},
                "gt30_or_missing": 0,
                "m_rank": stats([u["m_rank"] for u in missing]),
                "k_rank": stats([u["k_rank"] for u in missing]),
            },
            "rank_movement": {
                "population": "missing required units (failure probes, M rank > 10)",
                "improved_m_lt_k": sum(1 for u in missing if u["m_rank"] < u["k_rank"]),
                "unchanged": sum(1 for u in missing if u["m_rank"] == u["k_rank"]),
                "worsened_m_gt_k": sum(1 for u in missing if u["m_rank"] > u["k_rank"]),
                "rank_delta_m_minus_k": stats([u["rank_delta"] for u in missing]),
            },
            "top10_score_gap": {
                "definition": "m_rank10_score - m_score (raw BGE logits; no semantic threshold)",
                "missing_units": stats([u["score_gap_to_top10"] for u in missing]),
                "by_bucket": {b: stats([u["score_gap_to_top10"] for u in missing if u["missing_bucket"] == b])
                              for b in MISSING_BUCKETS},
                "promoted_units_for_reference": stats([u["score_gap_to_top10"] for u in promoted]),
            },
            "truncation_exposure": {
                "definition": "TRUNCATION_EXPOSED = recorded passage_tokens > 512 in the M pair contract",
                "missing_required_units": miss_tr,
                "promoted_required_units_same_probes": prom_tr,
                "enrichment": enrichment_statement(miss_tr["truncated_fraction"], prom_tr["truncated_fraction"]),
                "reference_all_m_pairs": {"truncated": sum(1 for r in pairs if is_truncation_exposed(r["passage_tokens"])),
                                          "pairs": len(pairs)},
                "limit": "chunk-level exposure only; evidence token spans are not labeled, so this is not causal",
            },
            "probe_failure_modes": {
                "failure_probes": len(fail_probes),
                "all_missing_rank_11_15": sum(1 for fp in fail_probes if fp["all_missing_within_15"]),
                "any_missing_rank_16_30": sum(1 for fp in fail_probes if fp["any_missing_rank_16_30"]),
                "every_missing_unit_truncation_exposed": sum(1 for fp in fail_probes if fp["all_missing_truncation_exposed"]),
                "at_least_one_non_truncated_missing_unit": sum(1 for fp in fail_probes if not fp["all_missing_truncation_exposed"]),
                "label_counts": dict(sorted(label_counts.items())),
                "k_full_success_among_failure_probes": sum(1 for fp in fail_probes if fp["K_full_success_top10"]),
                "note": "descriptive labels only; not hypothesis verdicts",
            },
            "candidate_complete_transition_context": {
                "population": "required units of candidate-complete failure probes",
                "k_top10_to_m_top10": sum(1 for u in units if u["transition"] == "STAY_TOP10"),
                "k_outside_to_m_top10": sum(1 for u in units if u["transition"] == "RERANK_TOP10_GAIN_FROM_K"),
                "k_top10_to_m_outside": sum(1 for u in units if u["transition"] == "K_TOP10_LOST_BY_RERANK"),
                "outside_both": sum(1 for u in units if u["transition"] == "STAY_OUTSIDE_TOP10"),
            },
            "descriptive_summary": {
                "near_boundary_fraction_of_missing": near_frac,
                "near_boundary_dominant": (near_frac is not None and near_frac >= NEAR_BOUNDARY_DOMINANT_MIN_FRACTION - TOL),
                "truncation_statement": enrichment_statement(miss_tr["truncated_fraction"], prom_tr["truncated_fraction"])["statement"],
                "rules": {"near_boundary_dominant": ">= 2/3 of missing units rank 11-15",
                          "truncation_enrichment": "missing minus promoted truncated fraction >= +0.20"},
            },
        },
    }


INTERPRETATION_LIMIT = ("The current benchmark labels the evidence-bearing chunk, not the exact evidence token span. "
                        "Therefore this diagnostic can determine whether a failed required chunk was truncated by the "
                        "M pair contract, but cannot determine whether the gold evidence itself occurred in the "
                        "truncated tail.")


def run(paths: Mapping[str, Path], expected_population=(15, 35)):
    src = verify_sources(paths)
    probes = _yaml(paths["probes"])["probes"]
    chunk_meta = {}
    with open(paths["chunks"], "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                c = json.loads(line)
                chunk_meta[c["chunk_id"]] = c["chapter_number"]
    k_rank = {r["probe_id"]: r["retrieved_chunk_ids"] for r in _jsonl(paths["k_detail"])}
    m_dir = Path(paths["m_dir"])
    reranked = _jsonl(m_dir / "reranked_per_probe.jsonl")
    transitions = _jsonl(m_dir / "required_evidence_transitions.jsonl")
    probe_trans = _jsonl(m_dir / "probe_transitions.jsonl")
    pairs = _jsonl(m_dir / "pair_scores.jsonl")
    reproduce_m(probes, chunk_meta, reranked, transitions, probe_trans, pairs, src["m_res"], expected_population)

    res = analyze(probes, k_rank, reranked, transitions, probe_trans, pairs)
    out = Path(paths["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    f1, f2 = out / "missing_required_units.jsonl", out / "failure_probes.jsonl"
    with open(f1, "w", encoding="utf-8", newline="\n") as f:
        for u in res["units"]:
            if not u["in_m_top10"]:
                f.write(json.dumps(u, sort_keys=True) + "\n")
    with open(f2, "w", encoding="utf-8", newline="\n") as f:
        for fp in res["fail_probes"]:
            f.write(json.dumps(fp, sort_keys=True) + "\n")

    public = {
        "diagnostic_id": DIAGNOSTIC_ID,
        "status": "EXECUTED",
        "benchmark_id": "LONG_RANGE_PROBE_V1",
        "source_experiment": {"id": M_ID, "candidate_source": "DENSE_E5_LARGE_V1 CUTOFF_FILTERED Top-30",
                              "model_inference": "none"},
        "artifact_integrity": {"status": "PASS", "source_sha256": src["hashes"],
                               "m_metrics_transitions_counts_truncation_reproduced": "PASS"},
        **res["public"],
        "local_table_sha256": {f1.name: sha256_file(f1), f2.name: sha256_file(f2)},
        "interpretation_limit": INTERPRETATION_LIMIT,
    }
    forbidden = sorted({p["probe_id"] for p in probes} | {p["question"] for p in probes}
                       | {str(p["expected_answer"]) for p in probes if p.get("expected_answer")} | set(chunk_meta))
    return public, forbidden


def interpretation_text(pub: dict) -> str:
    pop, dist, mv = pub["population"], pub["missing_required_rank_distribution"], pub["rank_movement"]
    tr, fm = pub["truncation_exposure"], pub["probe_failure_modes"]
    b = dist["buckets"]
    return (
        f"{pop['candidate_complete_failure_probes']} of {pop['candidate_complete_probes']} candidate-complete probes fail "
        f"Full Evidence Success@10 after reranking, with {pop['missing_required_units']} missing required units: "
        f"{b['11-15']['count']} at rank 11-15, {b['16-20']['count']} at 16-20, {b['21-30']['count']} at 21-30. "
        f"Relative to K, {mv['improved_m_lt_k']} missing units moved up, {mv['unchanged']} were unchanged and "
        f"{mv['worsened_m_gt_k']} moved down. Truncation exposure: missing "
        f"{tr['missing_required_units']['truncated_count']}/{tr['missing_required_units']['count']} vs promoted "
        f"{tr['promoted_required_units_same_probes']['truncated_count']}/{tr['promoted_required_units_same_probes']['count']} "
        f"({tr['enrichment']['statement']}). Probe labels: {fm['all_missing_rank_11_15']} near-boundary, "
        f"{fm['any_missing_rank_16_30']} mid-pool. " + INTERPRETATION_LIMIT
    )


def default_paths(base: Path) -> dict:
    local = base / ".local/story_integration/otonari_30ch"
    pub = base / "benchmarks/m1_script_quality/long_range_probe"
    return {
        "probes": local / "LONG_RANGE_PROBE_V1/probes.yaml",
        "chunks": local / "PARAGRAPH_PACK_V1/chunks.jsonl",
        "freeze": pub / "LONG_RANGE_PROBE_V1_FREEZE.yaml",
        "k_result": pub / "DENSE_E5_LARGE_V1_RESULT.yaml",
        "k_detail": local / "DENSE_E5_LARGE_V1" / K_DETAIL,
        "m_result": pub / f"{M_ID}_RESULT.yaml",
        "m_dir": local / M_ID,
        "out_dir": local / DIAGNOSTIC_ID,
    }


def verify_determinism(a: dict, b: dict) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def main():
    base = Path(__file__).resolve().parents[2]
    paths = default_paths(base)
    try:
        p1, forbidden = run(paths)
        p2, _ = run(paths)
    except GateFailure as e:
        print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)
    p1["interpretation"] = interpretation_text(p1)
    p2["interpretation"] = interpretation_text(p2)
    p1["determinism_status"] = "PASS" if verify_determinism(p1, p2) else "FAIL"
    p1["privacy_status"] = "PASS"
    text = yaml.dump(p1, sort_keys=False, allow_unicode=True)
    leaks = find_private_leaks(text, forbidden)
    if leaks:
        print(f"FAIL: privacy scan found {len(leaks)} private item(s)", file=sys.stderr)
        sys.exit(1)
    with open(base / "benchmarks/m1_script_quality/long_range_probe" / f"{DIAGNOSTIC_ID}_RESULT.yaml", "w",
              encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"Determinism: {p1['determinism_status']}")
    print(f"Failure probes: {p1['population']['candidate_complete_failure_probes']}  missing units: {p1['population']['missing_required_units']}")
    if p1["determinism_status"] != "PASS":
        sys.exit(1)


if __name__ == "__main__":
    main()
