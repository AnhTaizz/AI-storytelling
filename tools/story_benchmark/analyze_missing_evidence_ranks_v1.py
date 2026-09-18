"""
MISSING_EVIDENCE_RANK_DIAGNOSTIC_V1 (TASK M1-30CH-J)

Diagnostic only: reads frozen F / I ranking artifacts and reports where required
evidence ranks. No retrieval, no embeddings, no new method.

See benchmarks/m1_script_quality/long_range_probe/MISSING_EVIDENCE_RANK_DIAGNOSTIC_V1_METHOD.md
"""
import copy
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence

import yaml

DIAGNOSTIC_ID = "MISSING_EVIDENCE_RANK_DIAGNOSTIC_V1"
CUTOFF_MODE = "CUTOFF_FILTERED"

# Frozen buckets / thresholds.
BUCKETS = ("TOP_10", "NEAR_MISS", "MID_RANK", "DEEP_RANK", "MISSING")
COMPLETENESS_KS = (10, 20, 30, 50)
SHALLOW_MIN_FRACTION = 0.70
DEEP_MIN_FRACTION_EXCLUSIVE = 0.50
FUSION_SIGNAL_MIN_UNITS = 3
CONSISTENCY_TOLERANCE = 1e-9

F_DETAIL = "cutoff_filtered_per_probe.jsonl"
I_FUSED = "multiquery_cutoff_per_probe.jsonl"
I_PER_QUERY = "per_query_rankings.jsonl"

CHUNK_ID_RE = re.compile(r"ch\d{3}_c\d{4}")


class GateFailure(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def rank_of(chunk_id: str, ranking: Sequence[str]) -> Optional[int]:
    """Exact 1-based rank, or None if absent."""
    try:
        return list(ranking).index(chunk_id) + 1
    except ValueError:
        return None


def rank_bucket(rank: Optional[int]) -> str:
    if rank is None:
        return "MISSING"
    if rank < 1:
        raise ValueError("ranks are 1-based")
    if rank <= 10:
        return "TOP_10"
    if rank <= 20:
        return "NEAR_MISS"
    if rank <= 50:
        return "MID_RANK"
    return "DEEP_RANK"


def within(rank: Optional[int], k: int) -> bool:
    return rank is not None and rank <= k


def best_query_rank(query_ranks: Sequence[Optional[int]]):
    """(min rank, lowest query index achieving it); (None, None) if absent everywhere."""
    best, best_idx = None, None
    for idx, r in enumerate(query_ranks):
        if r is not None and (best is None or r < best):
            best, best_idx = r, idx
    return best, best_idx


def worst_required_rank(ranks: Sequence[Optional[int]]) -> Optional[int]:
    """None (unbounded) if any required unit is absent."""
    if any(r is None for r in ranks):
        return None
    return max(ranks)


def completeness_at_k(probe_ranks: Sequence[Sequence[Optional[int]]], k: int) -> dict:
    """Macro Recall@K and Full Evidence Success@K from per-probe required ranks."""
    n = len(probe_ranks)
    recall = sum(sum(1 for r in rs if within(r, k)) / len(rs) for rs in probe_ranks) / n
    success = sum(1 for rs in probe_ranks if all(within(r, k) for r in rs)) / n
    return {"recall": recall, "full_evidence_success": success}


def is_fusion_bottleneck(f_rank, best_i_rank, i_fused_rank) -> bool:
    return (not within(f_rank, 10)) and within(best_i_rank, 10) and (not within(i_fused_rank, 10))


def classify(missed_f_ranks: Sequence[Optional[int]]) -> str:
    n = len(missed_f_ranks)
    if n == 0:
        return "NO_MISSED_EVIDENCE"
    near = sum(1 for r in missed_f_ranks if r is not None and 11 <= r <= 20) / n
    deep = sum(1 for r in missed_f_ranks if r is None or r > 20) / n
    if near >= SHALLOW_MIN_FRACTION:
        return "SHALLOW_RANKING_BOTTLENECK"
    if deep > DEEP_MIN_FRACTION_EXCLUSIVE:
        return "DEEP_RELEVANCE_BOTTLENECK"
    return "MIXED_REACHABILITY"


def distribution(values: Sequence[str], keys: Sequence[str]) -> dict:
    n = len(values)
    return {k: {"count": sum(1 for v in values if v == k),
                "fraction": (sum(1 for v in values if v == k) / n) if n else 0.0} for k in keys}


def median(xs: Sequence[float]) -> float:
    s = sorted(xs)
    if not s:
        return 0.0
    m = len(s) // 2
    return float(s[m]) if len(s) % 2 else float((s[m - 1] + s[m]) / 2)


def find_private_leaks(serialized_public: str, forbidden_strings: Sequence[str]) -> List[str]:
    leaks = sorted({s for s in forbidden_strings if s and s in serialized_public})
    if CHUNK_ID_RE.search(serialized_public):
        leaks.append("<chunk-id pattern>")
    return leaks


# ---------------------------------------------------------------------------
# Artifact loading + integrity gates
# ---------------------------------------------------------------------------

def _read_jsonl(path: Path) -> List[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def _require(path: Path):
    if not path.exists():
        raise GateFailure(f"BLOCKED: missing required artifact {path}")


def verify_sources(paths: Mapping[str, Path]) -> dict:
    for key in ("probes", "chunks", "freeze", "f_result", "f_detail", "i_result", "i_fused", "i_per_query"):
        _require(paths[key])

    with open(paths["freeze"], "r", encoding="utf-8") as f:
        freeze = yaml.safe_load(f)
    with open(paths["f_result"], "r", encoding="utf-8") as f:
        f_res = yaml.safe_load(f)
    with open(paths["i_result"], "r", encoding="utf-8") as f:
        i_res = yaml.safe_load(f)

    checks = [
        ("probe_file", paths["probes"], freeze["probe_file_sha256"]),
        ("chunks_jsonl", paths["chunks"], freeze["chunks_jsonl_sha256"]),
        ("f_cutoff_ranking", paths["f_detail"], f_res["detailed_results_sha256"][F_DETAIL]),
        ("i_fused_cutoff_ranking", paths["i_fused"], i_res["detailed_results_sha256"][I_FUSED]),
        ("i_per_query_rankings", paths["i_per_query"], i_res["detailed_results_sha256"][I_PER_QUERY]),
    ]
    hashes = {}
    for name, path, expected in checks:
        actual = sha256_file(path)
        if actual != expected:
            raise GateFailure(f"BLOCKED: {name} sha256 mismatch ({actual} != {expected})")
        hashes[name] = actual
    if freeze.get("status") != "FROZEN":
        raise GateFailure("BLOCKED: benchmark is not FROZEN")
    return {"hashes": hashes, "f_result": f_res, "i_result": i_res, "freeze": freeze}


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def build_unit_table(probes, f_rows, i_fused_rows, i_query_rows) -> List[dict]:
    f_by = {r["probe_id"]: r for r in f_rows}
    i_by = {r["probe_id"]: r for r in i_fused_rows}
    q_by = defaultdict(dict)
    for r in i_query_rows:
        if r["mode"] == CUTOFF_MODE:
            q_by[r["probe_id"]][r["query_index"]] = r["retrieved_chunk_ids"]

    units = []
    for p in probes:
        pid = p["probe_id"]
        if pid not in f_by or pid not in i_by or pid not in q_by:
            raise GateFailure(f"BLOCKED: probe missing from source rankings")
        f_ids = f_by[pid]["retrieved_chunk_ids"]
        f_scores = f_by[pid].get("scores")
        i_ids = i_by[pid]["retrieved_chunk_ids"]
        qidx = sorted(q_by[pid])
        if qidx != list(range(len(qidx))) or len(qidx) != i_by[pid]["query_count"]:
            raise GateFailure("BLOCKED: per-query rankings inconsistent with fused artifact")
        pool = len(f_ids)
        for cid in p["required_evidence_chunk_ids"]:
            f_rank = rank_of(cid, f_ids)
            q_ranks = [rank_of(cid, q_by[pid][i]) for i in qidx]
            best, best_idx = best_query_rank(q_ranks)
            row = {
                "probe_id": pid,
                "category": p["category"],
                "required_chunk_id": cid,
                "eligible_pool_size": pool,
                "f_rank": f_rank,
                "f_bucket": rank_bucket(f_rank),
                "f_in_top10": within(f_rank, 10),
                "i_fused_rank": rank_of(cid, i_ids),
                "i_fused_in_top10": within(rank_of(cid, i_ids), 10),
                "i_query_ranks": q_ranks,
                "i_best_query_rank": best,
                "i_best_query_index": best_idx,
                "query_count": len(qidx),
            }
            if f_scores is not None and len(f_scores) == len(f_ids) and f_rank is not None and len(f_scores) >= 10:
                row["f_score"] = f_scores[f_rank - 1]
                row["f_top10_boundary_score"] = f_scores[9]
                row["f_score_gap_to_rank10"] = f_scores[9] - f_scores[f_rank - 1]
            units.append(row)
    return units


def probe_completeness(units: Sequence[dict]) -> List[dict]:
    by = defaultdict(list)
    order = []
    for u in units:
        if u["probe_id"] not in by:
            order.append(u["probe_id"])
        by[u["probe_id"]].append(u)
    out = []
    for pid in order:
        rs = [u["f_rank"] for u in by[pid]]
        present = [r for r in rs if r is not None]
        out.append({
            "probe_id": pid,
            "category": by[pid][0]["category"],
            "required_count": len(rs),
            "required_in_top10": sum(1 for r in rs if within(r, 10)),
            "best_required_rank": min(present) if present else None,
            "worst_required_rank": worst_required_rank(rs),
            "f_ranks": rs,
        })
    return out


def missed_summary(missed: Sequence[dict]) -> dict:
    n = len(missed)
    f_ranks = [u["f_rank"] for u in missed]
    return {
        "count": n,
        "rank_11_20": sum(1 for r in f_ranks if r is not None and 11 <= r <= 20),
        "rank_21_50": sum(1 for r in f_ranks if r is not None and 21 <= r <= 50),
        "rank_gt_50": sum(1 for r in f_ranks if r is not None and r > 50),
        "missing": sum(1 for r in f_ranks if r is None),
    }


def analyze(probes, f_rows, i_fused_rows, i_query_rows, f_reference_overall: Mapping) -> (dict, list):
    units = build_unit_table(probes, f_rows, i_fused_rows, i_query_rows)
    probes_c = probe_completeness(units)
    missed = [u for u in units if not u["f_in_top10"]]
    n_units, n_missed = len(units), len(missed)

    # Distributions
    all_dist = distribution([u["f_bucket"] for u in units], BUCKETS)
    ms = missed_summary(missed)
    missed_dist = {
        "rank_11_20": {"count": ms["rank_11_20"], "fraction": ms["rank_11_20"] / n_missed if n_missed else 0.0},
        "rank_21_50": {"count": ms["rank_21_50"], "fraction": ms["rank_21_50"] / n_missed if n_missed else 0.0},
        "rank_gt_50": {"count": ms["rank_gt_50"], "fraction": ms["rank_gt_50"] / n_missed if n_missed else 0.0},
        "missing": {"count": ms["missing"], "fraction": ms["missing"] / n_missed if n_missed else 0.0},
    }

    # Completeness curve (+ consistency gate at K=10)
    probe_ranks = [pc["f_ranks"] for pc in probes_c]
    curve = {f"K{k}": completeness_at_k(probe_ranks, k) for k in COMPLETENESS_KS}
    if abs(curve["K10"]["recall"] - f_reference_overall["recall@10"]) > CONSISTENCY_TOLERANCE or \
       abs(curve["K10"]["full_evidence_success"] - f_reference_overall["success@10"]) > CONSISTENCY_TOLERANCE:
        raise GateFailure("K=10 oracle curve does not reproduce committed F Recall@10 / Success@10")

    # Reachability
    worst = [pc["worst_required_rank"] for pc in probes_c]
    reach = {
        "f_top10_missed_units": n_missed,
        "missed_within_top20": {"count": sum(1 for u in missed if within(u["f_rank"], 20)),
                                "fraction": sum(1 for u in missed if within(u["f_rank"], 20)) / n_missed if n_missed else 0.0},
        "missed_within_top50": {"count": sum(1 for u in missed if within(u["f_rank"], 50)),
                                "fraction": sum(1 for u in missed if within(u["f_rank"], 50)) / n_missed if n_missed else 0.0},
        "small_candidate_reachable_units": ms["rank_11_20"],
        "medium_candidate_reachable_units": ms["rank_21_50"],
        "deep_units": ms["rank_gt_50"] + ms["missing"],
        "probes_all_required_within_top10": sum(1 for w in worst if within(w, 10)),
        "probes_all_required_within_top20": sum(1 for w in worst if within(w, 20)),
        "probes_all_required_within_top50": sum(1 for w in worst if within(w, 50)),
        "probe_count": len(probes_c),
        "wording": "candidate-reachable (gold present in the candidate pool); NOT reranker-solvable",
    }

    # Context: position relative to eligible pool; score gap
    rel_pos = [u["f_rank"] / u["eligible_pool_size"] for u in missed if u["f_rank"] is not None]
    gaps = [u["f_score_gap_to_rank10"] for u in missed if "f_score_gap_to_rank10" in u]
    context = {
        "missed_units_median_relative_rank": median(rel_pos),
        "missed_units_in_bottom_half_of_pool": sum(1 for x in rel_pos if x > 0.5),
        "missed_units_median_eligible_pool_size": median([u["eligible_pool_size"] for u in missed]),
        "missed_units_median_f_rank": median([u["f_rank"] for u in missed if u["f_rank"] is not None]),
        "missed_units_median_cosine_gap_to_rank10": median(gaps),
        "probe_worst_required_rank_median": median([w for w in worst if w is not None]),
    }

    # Multi-query diagnostic (on F-missed units)
    better = sum(1 for u in missed if u["i_best_query_rank"] is not None and u["f_rank"] is not None and u["i_best_query_rank"] < u["f_rank"])
    same = sum(1 for u in missed if u["i_best_query_rank"] is not None and u["i_best_query_rank"] == u["f_rank"])
    worse = sum(1 for u in missed if u["i_best_query_rank"] is not None and u["f_rank"] is not None and u["i_best_query_rank"] > u["f_rank"])
    f_miss_i_q_top10 = sum(1 for u in missed if within(u["i_best_query_rank"], 10))
    f_gt20_i_q_top20 = sum(1 for u in missed if not within(u["f_rank"], 20) and within(u["i_best_query_rank"], 20))
    fusion_cond = sum(1 for u in missed if is_fusion_bottleneck(u["f_rank"], u["i_best_query_rank"], u["i_fused_rank"]))
    fused_better = sum(1 for u in missed if u["i_fused_rank"] is not None and u["f_rank"] is not None and u["i_fused_rank"] < u["f_rank"])
    fused_top10 = sum(1 for u in missed if within(u["i_fused_rank"], 10))
    lost_by_i = sum(1 for u in units if u["f_in_top10"] and not u["i_fused_in_top10"])
    mq = {
        "population": "F Top-10 missed required evidence units",
        "unit_count": n_missed,
        "best_query_rank_better_than_f": better,
        "best_query_rank_equal_to_f": same,
        "best_query_rank_worse_than_f": worse,
        "f_rank_gt10_and_some_i_query_top10": f_miss_i_q_top10,
        "f_rank_gt20_and_some_i_query_top20": f_gt20_i_q_top20,
        "fusion_bottleneck_condition_count": fusion_cond,
        "i_fused_rank_better_than_f": fused_better,
        "i_fused_rescued_into_top10": fused_top10,
        "f_top10_units_lost_by_i_fused": lost_by_i,
        "median_best_query_rank": median([u["i_best_query_rank"] for u in missed if u["i_best_query_rank"] is not None]),
        "median_i_fused_rank": median([u["i_fused_rank"] for u in missed if u["i_fused_rank"] is not None]),
        "fusion_bottleneck_signal": fusion_cond >= FUSION_SIGNAL_MIN_UNITS,
    }

    # Categories (descriptive only)
    per_cat = {}
    for cat in sorted({u["category"] for u in units}):
        cu = [u for u in units if u["category"] == cat]
        cm = [u for u in cu if not u["f_in_top10"]]
        cms = missed_summary(cm)
        cpc = [pc for pc in probes_c if pc["category"] == cat]
        per_cat[cat] = {
            "probe_count": len(cpc),
            "required_evidence_units": len(cu),
            "f_top10_missed_units": len(cm),
            "missed_rank_11_20": cms["rank_11_20"],
            "missed_rank_21_50": cms["rank_21_50"],
            "missed_rank_gt_50": cms["rank_gt_50"],
            "missed_missing": cms["missing"],
            "probes_all_required_within_top20": sum(1 for pc in cpc if within(pc["worst_required_rank"], 20)),
            "probes_all_required_within_top50": sum(1 for pc in cpc if within(pc["worst_required_rank"], 50)),
            "missed_best_i_query_top10": sum(1 for u in cm if within(u["i_best_query_rank"], 10)),
        }

    classification = classify([u["f_rank"] for u in missed])

    result = {
        "required_evidence_unit_count": n_units,
        "probe_count": len(probes_c),
        "f_rank_bucket_distribution": all_dist,
        "f_missed_evidence_bucket_distribution": missed_dist,
        "missing_verified_zero": ms["missing"] == 0 and all_dist["MISSING"]["count"] == 0,
        "candidate_reachability": reach,
        "probe_completeness_by_k": {
            "note": "Diagnostic measurement of the frozen F ranking; NOT a new retrieval baseline.",
            **curve,
        },
        "rank_context": context,
        "multiquery_rank_diagnostic": mq,
        "per_category_aggregates": {
            "note": "Descriptive only (3 probes per category); not statistically conclusive.",
            **per_cat,
        },
        "classification": classification,
        "fusion_bottleneck_signal": mq["fusion_bottleneck_signal"],
    }
    return result, units


def interpretation_text(result: dict) -> str:
    c = result["classification"]
    r = result["candidate_reachability"]
    mq = result["multiquery_rank_diagnostic"]
    base = {
        "SHALLOW_RANKING_BOTTLENECK": "Most F-missed required evidence sits just outside Top-10 (ranks 11-20).",
        "DEEP_RELEVANCE_BOTTLENECK": "Most F-missed required evidence ranks beyond 20, outside a small Top-20 candidate pool.",
        "MIXED_REACHABILITY": "F-missed required evidence is split between near-miss and deeper ranks; no single population dominates.",
        "NO_MISSED_EVIDENCE": "F misses no required evidence in Top-10.",
    }[c]
    return (f"{base} {r['missed_within_top20']['count']}/{r['f_top10_missed_units']} missed units are "
            f"candidate-reachable within Top-20 and {r['missed_within_top50']['count']}/{r['f_top10_missed_units']} "
            f"within Top-50. {r['probes_all_required_within_top20']}/{r['probe_count']} probes have all required "
            f"evidence within Top-20. Individual I subqueries placed {mq['f_rank_gt10_and_some_i_query_top10']} "
            f"F-missed units in Top-10; the fusion-bottleneck condition holds for "
            f"{mq['fusion_bottleneck_condition_count']} unit(s).")


def run(paths: Mapping[str, Path], out_dir: Path) -> (dict, dict):
    src = verify_sources(paths)
    with open(paths["probes"], "r", encoding="utf-8") as f:
        probes = yaml.safe_load(f)["probes"]
    if len(probes) != src["freeze"]["probe_count"]:
        raise GateFailure("BLOCKED: probe count mismatch")
    f_rows = _read_jsonl(paths["f_detail"])
    i_fused = _read_jsonl(paths["i_fused"])
    i_q = _read_jsonl(paths["i_per_query"])

    result, units = analyze(probes, f_rows, i_fused, i_q, src["f_result"]["CUTOFF_FILTERED"]["overall"])

    out_dir.mkdir(parents=True, exist_ok=True)
    table = out_dir / "required_evidence_ranks.jsonl"
    with open(table, "w", encoding="utf-8", newline="\n") as f:
        for u in units:
            f.write(json.dumps(u, sort_keys=True) + "\n")
    pc = out_dir / "probe_completeness.jsonl"
    with open(pc, "w", encoding="utf-8", newline="\n") as f:
        for row in probe_completeness(units):
            f.write(json.dumps(row, sort_keys=True) + "\n")

    public = {
        "diagnostic_id": DIAGNOSTIC_ID,
        "status": "EXECUTED",
        "benchmark_id": "LONG_RANGE_PROBE_V1",
        "analysis_mode": CUTOFF_MODE,
        "source_baselines": {
            "F": "DENSE_E5_SMALL_V1",
            "I": "DENSE_E5_MULTIQUERY_V1",
        },
        "artifact_integrity": {
            "status": "PASS",
            "source_sha256": src["hashes"],
            "k10_consistency_with_f_result": "PASS",
        },
        "frozen_rules": {
            "buckets": {"TOP_10": "1-10", "NEAR_MISS": "11-20", "MID_RANK": "21-50", "DEEP_RANK": ">50", "MISSING": "absent"},
            "completeness_ks": list(COMPLETENESS_KS),
            "shallow_min_fraction_rank_11_20": SHALLOW_MIN_FRACTION,
            "deep_min_fraction_rank_gt_20_exclusive": DEEP_MIN_FRACTION_EXCLUSIVE,
            "fusion_signal_min_units": FUSION_SIGNAL_MIN_UNITS,
        },
        **result,
        "local_table_sha256": {
            "required_evidence_ranks.jsonl": sha256_file(table),
            "probe_completeness.jsonl": sha256_file(pc),
        },
    }
    public["interpretation"] = interpretation_text(result)

    private = {"forbidden_strings": sorted(
        {p["probe_id"] for p in probes}
        | {p["question"] for p in probes}
        | {str(p.get("expected_answer", "")) for p in probes if p.get("expected_answer")}
        | {u["required_chunk_id"] for u in units}
    )}
    return public, private


def verify_determinism(pub1: dict, pub2: dict) -> bool:
    return json.dumps(pub1, sort_keys=True) == json.dumps(pub2, sort_keys=True)


def default_paths(base_dir: Path) -> Dict[str, Path]:
    local = base_dir / ".local/story_integration/otonari_30ch"
    pub = base_dir / "benchmarks/m1_script_quality/long_range_probe"
    return {
        "probes": local / "LONG_RANGE_PROBE_V1/probes.yaml",
        "chunks": local / "PARAGRAPH_PACK_V1/chunks.jsonl",
        "freeze": pub / "LONG_RANGE_PROBE_V1_FREEZE.yaml",
        "f_result": pub / "DENSE_E5_SMALL_V1_RESULT.yaml",
        "f_detail": local / "DENSE_E5_SMALL_V1" / F_DETAIL,
        "i_result": pub / "DENSE_E5_MULTIQUERY_V1_RESULT.yaml",
        "i_fused": local / "DENSE_E5_MULTIQUERY_V1" / I_FUSED,
        "i_per_query": local / "DENSE_E5_MULTIQUERY_V1" / I_PER_QUERY,
    }


def main():
    base_dir = Path(__file__).resolve().parents[2]
    paths = default_paths(base_dir)
    out_dir = base_dir / ".local/story_integration/otonari_30ch" / DIAGNOSTIC_ID
    try:
        pub1, private = run(paths, out_dir)
        pub2, _ = run(paths, out_dir)
    except GateFailure as e:
        print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)

    deterministic = verify_determinism(pub1, pub2)
    pub1["determinism_status"] = "PASS" if deterministic else "FAIL"
    pub1["privacy_status"] = "PASS"
    serialized = yaml.dump(pub1, sort_keys=False, allow_unicode=True)
    leaks = find_private_leaks(serialized, private["forbidden_strings"])
    if leaks:
        print(f"FAIL: privacy scan found {len(leaks)} private string(s)", file=sys.stderr)
        sys.exit(1)
    out = base_dir / "benchmarks/m1_script_quality/long_range_probe" / f"{DIAGNOSTIC_ID}_RESULT.yaml"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(serialized)
    print(f"Determinism: {pub1['determinism_status']}")
    print(f"Classification: {pub1['classification']}  fusion_bottleneck_signal: {pub1['fusion_bottleneck_signal']}")
    if not deterministic:
        sys.exit(1)


if __name__ == "__main__":
    main()
