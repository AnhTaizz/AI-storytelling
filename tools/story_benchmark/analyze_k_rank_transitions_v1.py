"""
K_RANK_TRANSITION_DIAGNOSTIC_V1 (TASK M1-30CH-L)

Diagnostic only: compares frozen F (DENSE_E5_SMALL_V1) and K (DENSE_E5_LARGE_V1)
CUTOFF_FILTERED rankings per required evidence unit. No model, no retrieval.

See benchmarks/m1_script_quality/long_range_probe/K_RANK_TRANSITION_DIAGNOSTIC_V1_METHOD.md
"""
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence

import yaml

DIAGNOSTIC_ID = "K_RANK_TRANSITION_DIAGNOSTIC_V1"
F_DETAIL = "cutoff_filtered_per_probe.jsonl"
K_DETAIL = "cutoff_filtered_per_probe.jsonl"

BUCKETS = ("TOP_10", "NEAR_11_20", "MID_21_30", "MID_31_50", "DEEP_GT_50", "MISSING")
LOST_DESTINATIONS = ("11-15", "16-20", "21-30", "31-50", ">50", "missing")
GAIN_ORIGINS = ("11-20", "21-30", "31-50", ">50", "missing")
TRANSITIONS = ("STAY_TOP10", "F_TOP10_LOST_BY_K", "K_TOP10_GAIN_FROM_F", "STAY_OUTSIDE_TOP10")
ACCESS_DEPTHS = (10, 20, 30, 50)

ORDERING_MIN_LOST_WITHIN20_FRACTION_EXCLUSIVE = 0.50
ORDERING_MIN_K_FULL_SUCCESS_AT30 = 0.50
DEEP_MIN_UNITS_FRACTION_GT30 = 0.10
TOL = 1e-9

CHUNK_ID_RE = re.compile(r"ch\d{3}_c\d{4}")
PROBE_ID_RE = re.compile(r"\bP_[A-Z]+_\d{2}\b")


class GateFailure(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def rank_of(chunk_id: str, ranking: Sequence[str]) -> Optional[int]:
    try:
        return list(ranking).index(chunk_id) + 1
    except ValueError:
        return None


def within(rank: Optional[int], k: int) -> bool:
    return rank is not None and rank <= k


def rank_bucket(rank: Optional[int]) -> str:
    if rank is None:
        return "MISSING"
    if rank < 1:
        raise ValueError("ranks are 1-based")
    if rank <= 10:
        return "TOP_10"
    if rank <= 20:
        return "NEAR_11_20"
    if rank <= 30:
        return "MID_21_30"
    if rank <= 50:
        return "MID_31_50"
    return "DEEP_GT_50"


def lost_destination(rank: Optional[int]) -> str:
    if rank is None:
        return "missing"
    if rank <= 10:
        raise ValueError("not a lost unit")
    if rank <= 15:
        return "11-15"
    if rank <= 20:
        return "16-20"
    if rank <= 30:
        return "21-30"
    if rank <= 50:
        return "31-50"
    return ">50"


def gain_origin(rank: Optional[int]) -> str:
    if rank is None:
        return "missing"
    if rank <= 10:
        raise ValueError("not a gained unit")
    if rank <= 20:
        return "11-20"
    if rank <= 30:
        return "21-30"
    if rank <= 50:
        return "31-50"
    return ">50"


def transition_type(f_rank: Optional[int], k_rank: Optional[int]) -> str:
    f_in, k_in = within(f_rank, 10), within(k_rank, 10)
    if f_in and k_in:
        return "STAY_TOP10"
    if f_in:
        return "F_TOP10_LOST_BY_K"
    if k_in:
        return "K_TOP10_GAIN_FROM_F"
    return "STAY_OUTSIDE_TOP10"


def bool_transition(prefix: str, before: bool, after: bool) -> str:
    if before == after:
        return f"{prefix}_STABLE"
    return f"{prefix}_GAINED" if after else f"{prefix}_LOST"


def median(xs: Sequence[float]) -> Optional[float]:
    s = sorted(xs)
    if not s:
        return None
    m = len(s) // 2
    return float(s[m]) if len(s) % 2 else float((s[m - 1] + s[m]) / 2)


def mean(xs: Sequence[float]) -> Optional[float]:
    return float(sum(xs) / len(xs)) if xs else None


def counts(values: Sequence[str], keys: Sequence[str]) -> dict:
    n = len(values)
    return {k: {"count": sum(1 for v in values if v == k),
                "fraction": (sum(1 for v in values if v == k) / n) if n else 0.0} for k in keys}


def macro_at(probe_ranks: Sequence[Sequence[Optional[int]]], n: int) -> dict:
    p = len(probe_ranks)
    return {
        "probes_with_any_required": sum(1 for rs in probe_ranks if any(within(r, n) for r in rs)),
        "probes_with_all_required": sum(1 for rs in probe_ranks if all(within(r, n) for r in rs)),
        "recall": sum(sum(1 for r in rs if within(r, n)) / len(rs) for rs in probe_ranks) / p,
        "full_evidence_success": sum(1 for rs in probe_ranks if all(within(r, n) for r in rs)) / p,
        "hit": sum(1 for rs in probe_ranks if any(within(r, n) for r in rs)) / p,
        "raw_required_units": sum(1 for rs in probe_ranks for r in rs if within(r, n)),
    }


def classify(lost_within20_fraction: Optional[float], k_full_success_at30: float,
             k_gt30_units: int, total_units: int) -> dict:
    ordering = (lost_within20_fraction is not None
                and lost_within20_fraction > ORDERING_MIN_LOST_WITHIN20_FRACTION_EXCLUSIVE
                and k_full_success_at30 >= ORDERING_MIN_K_FULL_SUCCESS_AT30 - TOL)
    deep = total_units > 0 and (k_gt30_units / total_units) >= DEEP_MIN_UNITS_FRACTION_GT30 - TOL
    if ordering and not deep:
        label = "ORDERING_CONSISTENT"
    elif deep and not ordering:
        label = "DEEP_RELEVANCE_CONSISTENT"
    elif ordering and deep:
        label = "MIXED"
    else:
        label = "MIXED_INCONCLUSIVE"
    return {"ordering_condition": ordering, "deep_condition": deep, "classification": label}


def find_private_leaks(text: str, forbidden: Sequence[str]) -> List[str]:
    leaks = sorted({s for s in forbidden if s and s in text})
    if CHUNK_ID_RE.search(text):
        leaks.append("<chunk-id pattern>")
    if PROBE_ID_RE.search(text):
        leaks.append("<probe-id pattern>")
    return leaks


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------

def _load_yaml(p: Path):
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _rankings(p: Path) -> Dict[str, List[str]]:
    out = {}
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                out[r["probe_id"]] = r["retrieved_chunk_ids"]
    return out


def verify_sources(paths: Mapping[str, Path]) -> dict:
    for key, p in paths.items():
        if key != "out_dir" and not Path(p).exists():
            raise GateFailure(f"BLOCKED: missing required source {key}")
    freeze, f_res, k_res = _load_yaml(paths["freeze"]), _load_yaml(paths["f_result"]), _load_yaml(paths["k_result"])
    if freeze.get("status") != "FROZEN":
        raise GateFailure("BLOCKED: benchmark is not FROZEN")
    checks = [
        ("probe_file", paths["probes"], freeze["probe_file_sha256"]),
        ("chunks_jsonl", paths["chunks"], freeze["chunks_jsonl_sha256"]),
        ("f_cutoff_ranking", paths["f_detail"], f_res["detailed_results_sha256"][F_DETAIL]),
        ("k_cutoff_ranking", paths["k_detail"], k_res["detailed_results_sha256"][K_DETAIL]),
    ]
    hashes = {}
    for name, p, expected in checks:
        actual = sha256_file(p)
        if actual != expected:
            raise GateFailure(f"BLOCKED: {name} sha256 mismatch")
        hashes[name] = actual
    probes = _load_yaml(paths["probes"])["probes"]
    if len(probes) != freeze["probe_count"]:
        raise GateFailure("BLOCKED: probe count mismatch")
    return {"hashes": hashes, "probes": probes, "f_res": f_res, "k_res": k_res}


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def build_units(probes, f_rank_map, k_rank_map) -> List[dict]:
    units = []
    for p in probes:
        pid = p["probe_id"]
        if pid not in f_rank_map or pid not in k_rank_map:
            raise GateFailure("BLOCKED: probe missing from a source ranking")
        for cid in p["required_evidence_chunk_ids"]:
            fr, kr = rank_of(cid, f_rank_map[pid]), rank_of(cid, k_rank_map[pid])
            units.append({"probe_id": pid, "category": p["category"], "required_chunk_id": cid,
                          "f_rank": fr, "k_rank": kr, "f_bucket": rank_bucket(fr), "k_bucket": rank_bucket(kr),
                          "transition": transition_type(fr, kr)})
    return units


def build_probe_rows(probes, units) -> List[dict]:
    by = defaultdict(list)
    for u in units:
        by[u["probe_id"]].append(u)
    rows = []
    for p in probes:
        us = by[p["probe_id"]]
        fr, kr = [u["f_rank"] for u in us], [u["k_rank"] for u in us]
        f_hit, k_hit = any(within(r, 10) for r in fr), any(within(r, 10) for r in kr)
        f_full, k_full = all(within(r, 10) for r in fr), all(within(r, 10) for r in kr)
        rows.append({
            "probe_id": p["probe_id"], "category": p["category"], "required_count": len(us),
            "f_required_in_top10": sum(1 for r in fr if within(r, 10)),
            "k_required_in_top10": sum(1 for r in kr if within(r, 10)),
            "f_hit10": f_hit, "k_hit10": k_hit, "f_full_success10": f_full, "k_full_success10": k_full,
            "f_worst_required_rank": None if None in fr else max(fr),
            "k_worst_required_rank": None if None in kr else max(kr),
            "hit_transition": bool_transition("HIT", f_hit, k_hit),
            "full_success_transition": bool_transition("FULL_SUCCESS", f_full, k_full),
        })
    return rows


def deep_group(units, threshold: int) -> dict:
    g = [u for u in units if not within(u["k_rank"], threshold)]
    cats = defaultdict(int)
    for u in g:
        cats[u["category"]] += 1
    return {
        "count": len(g),
        "f_bucket_distribution": {b: sum(1 for u in g if u["f_bucket"] == b) for b in BUCKETS},
        "k_bucket_distribution": {b: sum(1 for u in g if u["k_bucket"] == b) for b in BUCKETS},
        "median_f_rank": median([u["f_rank"] for u in g if u["f_rank"] is not None]),
        "median_k_rank": median([u["k_rank"] for u in g if u["k_rank"] is not None]),
        "categories": dict(sorted(cats.items())),
    }


def analyze(probes, f_rank_map, k_rank_map, f_res, k_res):
    units = build_units(probes, f_rank_map, k_rank_map)
    probe_rows = build_probe_rows(probes, units)
    total = len(units)

    f_pr = [[u["f_rank"] for u in units if u["probe_id"] == p["probe_id"]] for p in probes]
    k_pr = [[u["k_rank"] for u in units if u["probe_id"] == p["probe_id"]] for p in probes]
    f_access = {f"top{n}": macro_at(f_pr, n) for n in ACCESS_DEPTHS}
    k_access = {f"top{n}": macro_at(k_pr, n) for n in ACCESS_DEPTHS}

    # Consistency with committed F and K results.
    for label, acc, res in (("F", f_access, f_res), ("K", k_access, k_res)):
        ov = res["CUTOFF_FILTERED"]["overall"]
        for mine, key in (("recall", "recall@10"), ("full_evidence_success", "success@10"), ("hit", "hit@10")):
            if abs(acc["top10"][mine] - ov[key]) > TOL:
                raise GateFailure(f"{label} {key} does not reproduce committed result")

    lost = [u for u in units if u["transition"] == "F_TOP10_LOST_BY_K"]
    gain = [u for u in units if u["transition"] == "K_TOP10_GAIN_FROM_F"]
    lost_k = [u["k_rank"] for u in lost if u["k_rank"] is not None]
    n_lost = len(lost)

    def frac_within(k):
        return (sum(1 for u in lost if within(u["k_rank"], k)) / n_lost) if n_lost else None

    lost_pop = {
        "population_size": n_lost,
        "k_destination": counts([lost_destination(u["k_rank"]) for u in lost], LOST_DESTINATIONS),
        "median_f_rank": median([u["f_rank"] for u in lost]),
        "median_k_rank": median(lost_k),
        "mean_k_rank": mean(lost_k),
        "fraction_within_k_top20": frac_within(20),
        "fraction_within_k_top30": frac_within(30),
        "fraction_within_k_top50": frac_within(50),
        "wording": "candidate-reachable within K Top-N (not reranker-solvable)",
    }
    gain_pop = {
        "population_size": len(gain),
        "f_origin": counts([gain_origin(u["f_rank"]) for u in gain], GAIN_ORIGINS),
        "median_f_rank": median([u["f_rank"] for u in gain if u["f_rank"] is not None]),
        "median_k_rank": median([u["k_rank"] for u in gain]),
    }

    outside = [u for u in units if u["transition"] == "STAY_OUTSIDE_TOP10"]
    transitions = {
        "total_units": total,
        "counts": {t: sum(1 for u in units if u["transition"] == t) for t in TRANSITIONS},
        "stay_outside_top10_f_buckets": {b: sum(1 for u in outside if u["f_bucket"] == b) for b in BUCKETS},
        "stay_outside_top10_k_buckets": {b: sum(1 for u in outside if u["k_bucket"] == b) for b in BUCKETS},
        "f_bucket_distribution_all": {b: sum(1 for u in units if u["f_bucket"] == b) for b in BUCKETS},
        "k_bucket_distribution_all": {b: sum(1 for u in units if u["k_bucket"] == b) for b in BUCKETS},
        "missing_verified": {"f": sum(1 for u in units if u["f_rank"] is None),
                             "k": sum(1 for u in units if u["k_rank"] is None)},
    }

    deep = {"k_rank_gt20": deep_group(units, 20), "k_rank_gt30": deep_group(units, 30),
            "k_rank_gt50": deep_group(units, 50), "note": "categories are descriptive only"}

    def ptc(key, val):
        return sum(1 for r in probe_rows if r[key] == val)

    probe_agg = {
        "probe_count": len(probe_rows),
        "f_hit_probes": ptc("f_hit10", True), "k_hit_probes": ptc("k_hit10", True),
        "f_full_success_probes": ptc("f_full_success10", True), "k_full_success_probes": ptc("k_full_success10", True),
        "hit_gained": ptc("hit_transition", "HIT_GAINED"), "hit_lost": ptc("hit_transition", "HIT_LOST"),
        "hit_stable_true": sum(1 for r in probe_rows if r["hit_transition"] == "HIT_STABLE" and r["f_hit10"]),
        "hit_stable_false": sum(1 for r in probe_rows if r["hit_transition"] == "HIT_STABLE" and not r["f_hit10"]),
        "full_success_gained": ptc("full_success_transition", "FULL_SUCCESS_GAINED"),
        "full_success_lost": ptc("full_success_transition", "FULL_SUCCESS_LOST"),
        "full_success_stable_true": sum(1 for r in probe_rows if r["full_success_transition"] == "FULL_SUCCESS_STABLE" and r["f_full_success10"]),
        "full_success_stable_false": sum(1 for r in probe_rows if r["full_success_transition"] == "FULL_SUCCESS_STABLE" and not r["f_full_success10"]),
        "probes_with_more_required_in_k_top10": sum(1 for r in probe_rows if r["k_required_in_top10"] > r["f_required_in_top10"]),
        "probes_with_fewer_required_in_k_top10": sum(1 for r in probe_rows if r["k_required_in_top10"] < r["f_required_in_top10"]),
        "probes_with_equal_required_in_top10": sum(1 for r in probe_rows if r["k_required_in_top10"] == r["f_required_in_top10"]),
    }

    req_counts = defaultdict(int)
    for r in probe_rows:
        req_counts[r["required_count"]] += 1
    raw_vs_macro = {
        "f_raw_required_units_in_top10": f_access["top10"]["raw_required_units"],
        "k_raw_required_units_in_top10": k_access["top10"]["raw_required_units"],
        "total_required_units": total,
        "f_micro_recall10": f_access["top10"]["raw_required_units"] / total,
        "k_micro_recall10": k_access["top10"]["raw_required_units"] / total,
        "f_macro_recall10": f_access["top10"]["recall"],
        "k_macro_recall10": k_access["top10"]["recall"],
        "probes_by_required_count": {int(k): v for k, v in sorted(req_counts.items())},
        "explanation": ("Raw evidence-unit count and macro Recall@10 are different statistics: each probe "
                        "contributes equally to macro recall, while probes require different numbers of "
                        "evidence units, so moving a unit between a 2-unit and a 3-unit probe changes macro "
                        "recall without changing the raw count."),
    }

    access = {"note": "candidate-access diagnostic from frozen rankings; NOT reranker performance",
              "K": k_access, "F_reference": f_access}

    per_cat = {}
    for cat in sorted({u["category"] for u in units}):
        cu = [u for u in units if u["category"] == cat]
        per_cat[cat] = {"units": len(cu), **{t: sum(1 for u in cu if u["transition"] == t) for t in TRANSITIONS},
                        "k_rank_gt20": sum(1 for u in cu if not within(u["k_rank"], 20)),
                        "k_rank_gt30": sum(1 for u in cu if not within(u["k_rank"], 30))}

    cls = classify(lost_pop["fraction_within_k_top20"], k_access["top30"]["full_evidence_success"],
                   deep["k_rank_gt30"]["count"], total)

    result = {
        "population": {"probe_count": len(probes), "required_evidence_units": total},
        "all_required_evidence_transition_counts": transitions,
        "f_top10_lost_population": lost_pop,
        "k_top10_gain_population": gain_pop,
        "remaining_deep_under_k": deep,
        "probe_transition_aggregates": probe_agg,
        "raw_unit_count_vs_macro_recall": raw_vs_macro,
        "candidate_access_by_depth": access,
        "per_category_descriptive": {"note": "descriptive only (3 probes per category)", **per_cat},
        "descriptive_classification": {
            **cls,
            "rule": {"ordering": "lost_within_k_top20 > 50% AND K full_evidence_success@30 >= 0.50",
                     "deep": "units with K rank > 30 >= 10% of required units"},
            "disclosure": "thresholds set after K result and K post-hoc counts were visible; descriptive only",
        },
    }
    return result, units, probe_rows


def interpretation_text(r: dict) -> str:
    lp, dp, acc = r["f_top10_lost_population"], r["remaining_deep_under_k"], r["candidate_access_by_depth"]["K"]
    total = r["population"]["required_evidence_units"]
    return (
        f"Of {lp['population_size']} required units F had in Top-10 but K ranked lower, "
        f"{lp['k_destination']['11-15']['count'] + lp['k_destination']['16-20']['count']} stay within K Top-20 and "
        f"{round((lp['fraction_within_k_top30'] or 0) * lp['population_size'])} within K Top-30, i.e. they moved just below "
        f"the output boundary rather than being lost. Under K, {acc['top20']['probes_with_all_required']}/15 probes have "
        f"all required evidence within Top-20 and {acc['top30']['probes_with_all_required']}/15 within Top-30 "
        f"(candidate access). {dp['k_rank_gt30']['count']}/{total} units remain beyond K rank 30 and "
        f"{dp['k_rank_gt50']['count']}/{total} beyond rank 50. Descriptive classification: "
        f"{r['descriptive_classification']['classification']}."
    )


def run(paths: Mapping[str, Path], expected_population=(15, 35)):
    src = verify_sources(paths)
    f_map, k_map = _rankings(paths["f_detail"]), _rankings(paths["k_detail"])
    result, units, probe_rows = analyze(src["probes"], f_map, k_map, src["f_res"], src["k_res"])
    if expected_population is not None and (result["population"]["probe_count"], result["population"]["required_evidence_units"]) != tuple(expected_population):
        raise GateFailure("BLOCKED: population is not 15 probes / 35 units")

    out = Path(paths["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    t1, t2 = out / "required_evidence_transitions.jsonl", out / "probe_transitions.jsonl"
    for path, rows in ((t1, units), (t2, probe_rows)):
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            for row in rows:
                f.write(json.dumps(row, sort_keys=True) + "\n")

    public = {
        "diagnostic_id": DIAGNOSTIC_ID,
        "status": "EXECUTED",
        "benchmark_id": "LONG_RANGE_PROBE_V1",
        "analysis_mode": "CUTOFF_FILTERED",
        "source_baselines": {"F": "DENSE_E5_SMALL_V1", "K": "DENSE_E5_LARGE_V1"},
        "artifact_integrity": {"status": "PASS", "source_sha256": src["hashes"],
                               "f_k_top10_metrics_reproduce_committed_results": "PASS"},
        **result,
        "local_table_sha256": {t1.name: sha256_file(t1), t2.name: sha256_file(t2)},
    }
    public["interpretation"] = interpretation_text(result)
    forbidden = sorted({p["probe_id"] for p in src["probes"]} | {p["question"] for p in src["probes"]}
                       | {str(p["expected_answer"]) for p in src["probes"] if p.get("expected_answer")}
                       | {u["required_chunk_id"] for u in units})
    return public, forbidden


def verify_determinism(a: dict, b: dict) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def default_paths(base_dir: Path) -> dict:
    local = base_dir / ".local/story_integration/otonari_30ch"
    pub = base_dir / "benchmarks/m1_script_quality/long_range_probe"
    return {
        "probes": local / "LONG_RANGE_PROBE_V1/probes.yaml",
        "chunks": local / "PARAGRAPH_PACK_V1/chunks.jsonl",
        "freeze": pub / "LONG_RANGE_PROBE_V1_FREEZE.yaml",
        "f_result": pub / "DENSE_E5_SMALL_V1_RESULT.yaml",
        "f_detail": local / "DENSE_E5_SMALL_V1" / F_DETAIL,
        "k_result": pub / "DENSE_E5_LARGE_V1_RESULT.yaml",
        "k_detail": local / "DENSE_E5_LARGE_V1" / K_DETAIL,
        "out_dir": local / DIAGNOSTIC_ID,
    }


def main():
    base = Path(__file__).resolve().parents[2]
    paths = default_paths(base)
    try:
        p1, forbidden = run(paths)
        p2, _ = run(paths)
    except GateFailure as e:
        print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)
    p1["determinism_status"] = "PASS" if verify_determinism(p1, p2) else "FAIL"
    p1["privacy_status"] = "PASS"
    text = yaml.dump(p1, sort_keys=False, allow_unicode=True)
    leaks = find_private_leaks(text, forbidden)
    if leaks:
        print(f"FAIL: privacy scan found {len(leaks)} private item(s)", file=sys.stderr)
        sys.exit(1)
    out = base / "benchmarks/m1_script_quality/long_range_probe" / f"{DIAGNOSTIC_ID}_RESULT.yaml"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"Determinism: {p1['determinism_status']}")
    print(f"Classification: {p1['descriptive_classification']['classification']}")
    if p1["determinism_status"] != "PASS":
        sys.exit(1)


if __name__ == "__main__":
    main()
