"""
Runner for KM_CONSENSUS_RANK_SUM_V1 (TASK M1-30CH-O)

Deterministic rank-sum consensus between DENSE_E5_LARGE_V1 (K) Top-30
and BGE_RERANKER_V2_M3_TOP30_V1 (M) reranked Top-30.

See benchmarks/m1_script_quality/long_range_probe/KM_CONSENSUS_RANK_SUM_V1_METHOD.md
"""
import copy
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import yaml

from tools.story_benchmark.dense_e5_large_v1 import calculate_metrics
from tools.story_benchmark.km_consensus_rank_sum_v1 import (
    CANDIDATE_DEPTH,
    TRANSITIONS,
    CandidateSetError,
    evaluated_ranking,
    interpret_verdict,
    rank_bucket,
    rank_of,
    rank_sum_details,
    select_consensus,
    transition_type,
    within,
)
from tools.story_benchmark.run_bm25_lexical_v1 import compute_spoiler_violations

EXPERIMENT_ID = "KM_CONSENSUS_RANK_SUM_V1"
BENCHMARK_ID = "LONG_RANGE_PROBE_V1"
METRIC_KEYS = [
    "hit@1", "hit@3", "hit@5", "hit@10",
    "recall@1", "recall@3", "recall@5", "recall@10",
    "success@1", "success@3", "success@5", "success@10",
    "spoiler_violation@1", "spoiler_violation@3", "spoiler_violation@5", "spoiler_violation@10",
    "mrr",
]
TOL = 1e-9
CHUNK_ID_RE = re.compile(r"ch\d{3}_c\d{4}")
PROBE_ID_RE = re.compile(r"\bP_[A-Z]+_\d{2}\b")


class GateFailure(RuntimeError):
    pass


def sha256_file(p: Path) -> str:
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _yaml(p: Path) -> dict:
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


def _m_evaluated_rankings(p: Path) -> dict:
    out = {}
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                out[r["probe_id"]] = r["evaluated_ranking"]
    return out


def _m_top_candidates(p: Path) -> dict:
    out = {}
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                out[r["probe_id"]] = r["reranked_top_candidates"]
    return out


def write_jsonl(p: Path, rows):
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n")


def aggregate(metrics_list: List[Tuple[str, dict]]) -> dict:
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


def evaluate_probe(probe: dict, ranking: Sequence[str], chunk_meta: dict) -> dict:
    m = calculate_metrics(probe, ranking)
    m.update(compute_spoiler_violations(probe, ranking, chunk_meta))
    return m


def verify_inputs(paths: Dict[str, Path]) -> dict:
    for key, p in paths.items():
        if key not in ("out_dir", "public_result") and not p.exists():
            raise GateFailure(f"BLOCKED: missing required artifact {key}: {p}")

    freeze = _yaml(paths["freeze"])
    probes = _yaml(paths["probes"])["probes"]
    k_res = _yaml(paths["k_result"])
    m_res = _yaml(paths["m_result"])
    n_res = _yaml(paths["n_result"])

    if freeze.get("status") != "FROZEN" or freeze.get("probe_count") != len(probes):
        raise GateFailure("benchmark freeze status/probe count mismatch")

    hashes = {}
    for name, p, expected in (
        ("probe_file", paths["probes"], freeze["probe_file_sha256"]),
        ("chunks_jsonl", paths["chunks"], freeze["chunks_jsonl_sha256"]),
        ("k_cutoff_ranking", paths["k_detail"], k_res["detailed_results_sha256"]["cutoff_filtered_per_probe.jsonl"]),
        ("m_reranked_per_probe", paths["m_detail"], m_res["detailed_results_sha256"]["reranked_per_probe.jsonl"]),
    ):
        actual = sha256_file(p)
        if actual != expected:
            raise GateFailure(f"{name} sha256 mismatch: expected {expected}, got {actual}")
        hashes[name] = actual

    chunk_meta = {}
    texts = {}
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
        raise GateFailure(f"population is not 15 probes / 35 units: {len(probes)} / {units}")

    return {
        "probes": probes,
        "chunk_meta": chunk_meta,
        "texts": texts,
        "hashes": hashes,
        "k_res": k_res,
        "m_res": m_res,
        "n_res": n_res,
        "corpus_fingerprint_sha256": freeze["corpus_fingerprint_sha256"],
    }


def reproduce_k_control(probes: list, k_rank: dict, chunk_meta: dict, k_res: dict) -> dict:
    ml = [(p["category"], evaluate_probe(p, k_rank[p["probe_id"]], chunk_meta)) for p in probes]
    agg = aggregate(ml)
    ov = k_res["CUTOFF_FILTERED"]["overall"]
    bad = [k for k in METRIC_KEYS if abs(agg["overall"][k] - ov[k]) > TOL]
    if bad:
        raise GateFailure(f"K control does not reproduce committed K metrics: {bad}")
    return agg


def reproduce_m_control(probes: list, m_rank: dict, chunk_meta: dict, m_res: dict) -> dict:
    ml = [(p["category"], evaluate_probe(p, m_rank[p["probe_id"]], chunk_meta)) for p in probes]
    agg = aggregate(ml)
    ov = m_res["RERANKED"]["overall"]
    bad = [k for k in METRIC_KEYS if abs(agg["overall"][k] - ov[k]) > TOL]
    if bad:
        raise GateFailure(f"M control does not reproduce committed M metrics: {bad}")
    return agg


def find_private_leaks(text: str, forbidden_strings: Sequence[str]) -> List[str]:
    leaks = sorted({s for s in forbidden_strings if s and s in text})
    if CHUNK_ID_RE.search(text):
        leaks.append("<chunk-id pattern>")
    if PROBE_ID_RE.search(text):
        leaks.append("<probe-id pattern>")
    return leaks


def run_experiment(paths: Dict[str, Path]) -> dict:
    out = paths["out_dir"]
    out.mkdir(parents=True, exist_ok=True)

    inp = verify_inputs(paths)
    probes = inp["probes"]
    chunk_meta = inp["chunk_meta"]
    texts = inp["texts"]
    k_res = inp["k_res"]
    m_res = inp["m_res"]
    n_res = inp["n_res"]

    k_rank = _rankings(paths["k_detail"])
    m_eval_rank = _m_evaluated_rankings(paths["m_detail"])
    m_top_cands = _m_top_candidates(paths["m_detail"])

    # 1. Reproduce K and M controls
    k_agg = reproduce_k_control(probes, k_rank, chunk_meta, k_res)
    m_agg = reproduce_m_control(probes, m_eval_rank, chunk_meta, m_res)

    # 2. Candidate set integrity verification
    for p in probes:
        pid = p["probe_id"]
        k_cands = k_rank[pid][:CANDIDATE_DEPTH]
        m_cands = m_top_cands[pid]
        if len(k_cands) != CANDIDATE_DEPTH or len(m_cands) != CANDIDATE_DEPTH:
            raise GateFailure(f"candidate depth mismatch for probe {pid}")
        if set(k_cands) != set(m_cands):
            raise GateFailure(f"candidate set difference between K and M for probe {pid}")

    # 3. Candidate ceiling check (derived before consensus ordering)
    candidate_complete_pids = []
    for p in probes:
        pid = p["probe_id"]
        k_cands_set = set(k_rank[pid][:CANDIDATE_DEPTH])
        if all(c in k_cands_set for c in p["required_evidence_chunk_ids"]):
            candidate_complete_pids.append(pid)

    if len(candidate_complete_pids) != n_res["population"]["candidate_complete_probes"]:
        raise GateFailure(
            f"Candidate complete probe count mismatch with N: "
            f"derived {len(candidate_complete_pids)} vs expected {n_res['population']['candidate_complete_probes']}"
        )

    # 4. Anti-leakage pure selection (GOLD-BLIND)
    # The selector receives ONLY the candidate chunk ID sequences of K and M.
    consensus_top_per_probe = {}
    consensus_eval_rank_per_probe = {}
    consensus_details_per_probe = {}

    for p in probes:
        pid = p["probe_id"]
        k_cands = k_rank[pid][:CANDIDATE_DEPTH]
        m_cands = m_top_cands[pid]

        # Pure selection:
        selected = select_consensus(k_cands, m_cands, expected_depth=CANDIDATE_DEPTH)
        details = rank_sum_details(k_cands, m_cands, expected_depth=CANDIDATE_DEPTH)
        eval_rk = evaluated_ranking(selected, k_rank[pid])

        consensus_top_per_probe[pid] = selected
        consensus_eval_rank_per_probe[pid] = eval_rk
        consensus_details_per_probe[pid] = details

    # 5. Evaluation with Gold Labels (Read ONLY after ranking is frozen)
    consensus_metrics = []
    per_probe_rows = []
    for p in probes:
        pid = p["probe_id"]
        m = evaluate_probe(p, consensus_eval_rank_per_probe[pid], chunk_meta)
        consensus_metrics.append((p["category"], m))
        per_probe_rows.append({
            "probe_id": pid,
            "category": p["category"],
            "consensus_top_candidates": consensus_top_per_probe[pid],
            "evaluated_ranking": consensus_eval_rank_per_probe[pid],
            "metrics": m,
        })

    c_agg = aggregate(consensus_metrics)

    # Spoiler violation gate
    if any(c_agg["overall"][f"spoiler_violation@{k}"] != 0.0 for k in (1, 3, 5, 10)):
        raise GateFailure("spoiler violation in consensus CUTOFF ranking")

    # 6. Global Required-Evidence Transitions (35 units)
    # Compare M Top-10 to Consensus Top-10
    trans_rows = []
    for p in probes:
        pid = p["probe_id"]
        for c in p["required_evidence_chunk_ids"]:
            mr = rank_of(c, m_eval_rank[pid])
            cr = rank_of(c, consensus_eval_rank_per_probe[pid])
            kr = rank_of(c, k_rank[pid])
            ttype = transition_type(mr, cr)
            trans_rows.append({
                "probe_id": pid,
                "category": p["category"],
                "chunk_id": c,
                "k_rank": kr,
                "m_rank": mr,
                "consensus_rank": cr,
                "transition": ttype,
            })

    trans_counts = {t: sum(1 for r in trans_rows if r["transition"] == t) for t in TRANSITIONS}

    # Probe-level transitions (hit and full-success)
    probe_trans_rows = []
    m_hit_count = c_hit_count = 0
    m_full_count = c_full_count = 0
    hit_gained = hit_lost = 0
    full_gained = full_lost = 0

    for p in probes:
        pid = p["probe_id"]
        req = p["required_evidence_chunk_ids"]
        m_in = [within(rank_of(c, m_eval_rank[pid]), 10) for c in req]
        c_in = [within(rank_of(c, consensus_eval_rank_per_probe[pid]), 10) for c in req]

        m_hit = any(m_in)
        c_hit = any(c_in)
        m_full = all(m_in)
        c_full = all(c_in)

        if m_hit:
            m_hit_count += 1
        if c_hit:
            c_hit_count += 1
        if not m_hit and c_hit:
            hit_gained += 1
        if m_hit and not c_hit:
            hit_lost += 1

        if m_full:
            m_full_count += 1
        if c_full:
            c_full_count += 1
        if not m_full and c_full:
            full_gained += 1
        if m_full and not c_full:
            full_lost += 1

        probe_trans_rows.append({
            "probe_id": pid,
            "m_hit": m_hit,
            "c_hit": c_hit,
            "m_full": m_full,
            "c_full": c_full,
            "candidate_complete": pid in candidate_complete_pids,
        })

    # Verify candidate complete full success probes
    candidate_complete_full_success_probes = sum(1 for r in probe_trans_rows if r["candidate_complete"] and r["c_full"])
    ceiling_utilization = candidate_complete_full_success_probes / len(candidate_complete_pids)

    # 7. N Failure Population Diagnostic
    # Reconstruct N candidate_complete_failure probes
    # In M, candidate_complete failure probes are candidate_complete probes with not m_full.
    n_failure_probes = [p for p in probes if p["probe_id"] in candidate_complete_pids and not all(
        within(rank_of(c, m_eval_rank[p["probe_id"]]), 10) for c in p["required_evidence_chunk_ids"]
    )]

    if len(n_failure_probes) != n_res["population"]["candidate_complete_failure_probes"]:
        raise GateFailure(
            f"N failure probe population count mismatch: derived {len(n_failure_probes)} "
            f"vs expected {n_res['population']['candidate_complete_failure_probes']}"
        )

    n_failure_probes_full_success = 0
    n_failure_probes_remains_failure = 0
    n_failure_probes_m_full_fail_improved = 0
    n_failure_probes_worsened = 0

    n_missing_units_rows = []
    n_failure_probe_rows = []

    for p in n_failure_probes:
        pid = p["probe_id"]
        req = p["required_evidence_chunk_ids"]
        m_in_count = sum(1 for c in req if within(rank_of(c, m_eval_rank[pid]), 10))
        c_in_count = sum(1 for c in req if within(rank_of(c, consensus_eval_rank_per_probe[pid]), 10))

        is_c_full = (c_in_count == len(req))
        if is_c_full:
            n_failure_probes_full_success += 1
        else:
            n_failure_probes_remains_failure += 1

        if m_in_count == 0 and c_in_count > 0:
            n_failure_probes_m_full_fail_improved += 1

        if c_in_count < m_in_count:
            n_failure_probes_worsened += 1

        n_failure_probe_rows.append({
            "probe_id": pid,
            "required_count": len(req),
            "m_in_top10": m_in_count,
            "c_in_top10": c_in_count,
            "full_success_under_consensus": is_c_full,
        })

        # Missing required units under M (rank > 10)
        for c in req:
            mr = rank_of(c, m_eval_rank[pid])
            if not within(mr, 10):
                cr = rank_of(c, consensus_eval_rank_per_probe[pid])
                kr = rank_of(c, k_rank[pid])
                n_missing_units_rows.append({
                    "probe_id": pid,
                    "chunk_id": c,
                    "k_rank": kr,
                    "m_rank": mr,
                    "consensus_rank": cr,
                    "m_bucket": rank_bucket(mr),
                    "consensus_bucket": rank_bucket(cr),
                    "entered_top10": within(cr, 10),
                    "stayed_outside_top10": not within(cr, 10),
                    "moved_upward": cr < mr,
                    "moved_downward": cr > mr,
                    "unchanged": cr == mr,
                })

    if len(n_missing_units_rows) != n_res["population"]["missing_required_units"]:
        raise GateFailure(
            f"N missing units count mismatch: derived {len(n_missing_units_rows)} "
            f"vs expected {n_res['population']['missing_required_units']}"
        )

    # N missing units summary
    n_missing_summary = {
        "count": len(n_missing_units_rows),
        "entered_top10": sum(1 for r in n_missing_units_rows if r["entered_top10"]),
        "stayed_outside_top10": sum(1 for r in n_missing_units_rows if r["stayed_outside_top10"]),
        "moved_upward": sum(1 for r in n_missing_units_rows if r["moved_upward"]),
        "moved_downward": sum(1 for r in n_missing_units_rows if r["moved_downward"]),
        "unchanged": sum(1 for r in n_missing_units_rows if r["unchanged"]),
        "m_bucket_distribution": {
            b: sum(1 for r in n_missing_units_rows if r["m_bucket"] == b)
            for b in ("11-15", "16-20", "21-30")
        },
        "consensus_bucket_distribution": {
            b: sum(1 for r in n_missing_units_rows if r["consensus_bucket"] == b)
            for b in ("<=10", "11-15", "16-20", "21-30", ">30")
        },
    }

    # Write private local tables
    write_jsonl(out / "consensus_per_probe.jsonl", per_probe_rows)
    write_jsonl(out / "required_evidence_transitions.jsonl", trans_rows)
    write_jsonl(out / "n_failure_population_transitions.jsonl", {
        "failure_probes": n_failure_probe_rows,
        "missing_units": n_missing_units_rows,
    } if False else (n_failure_probe_rows + n_missing_units_rows))

    local_table_hashes = {
        "consensus_per_probe.jsonl": sha256_file(out / "consensus_per_probe.jsonl"),
        "required_evidence_transitions.jsonl": sha256_file(out / "required_evidence_transitions.jsonl"),
        "n_failure_population_transitions.jsonl": sha256_file(out / "n_failure_population_transitions.jsonl"),
    }

    # Compute comparisons and verdict
    m_overall = m_agg["overall"]
    c_overall = c_agg["overall"]
    k_overall = k_agg["overall"]

    delta_hit10 = c_overall["hit@10"] - m_overall["hit@10"]
    delta_recall10 = c_overall["recall@10"] - m_overall["recall@10"]
    delta_success10 = c_overall["success@10"] - m_overall["success@10"]
    delta_mrr = c_overall["mrr"] - m_overall["mrr"]

    verdict = interpret_verdict(
        delta_success10=delta_success10,
        delta_recall10=delta_recall10,
        delta_hit10=delta_hit10,
        full_success_gained=full_gained,
        full_success_lost=full_lost,
        gates_passed=True,
    )

    # Detailed comparison tables
    m_comparison_overall = {}
    for k in (
        "Hit@1", "Recall@1", "Full_Evidence_Success@1", "Spoiler_Violation@1",
        "Hit@3", "Recall@3", "Full_Evidence_Success@3", "Spoiler_Violation@3",
        "Hit@5", "Recall@5", "Full_Evidence_Success@5", "Spoiler_Violation@5",
        "Hit@10", "Recall@10", "Full_Evidence_Success@10", "Spoiler_Violation@10", "MRR"
    ):
        key_lower = k.lower().replace("full_evidence_", "")
        m_val = m_overall[key_lower]
        c_val = c_overall[key_lower]
        m_comparison_overall[k] = {
            "M": m_val,
            "CONSENSUS": c_val,
            "delta": c_val - m_val,
        }

    k_historical_overall = {}
    for k in (
        "Hit@1", "Recall@1", "Full_Evidence_Success@1", "Spoiler_Violation@1",
        "Hit@3", "Recall@3", "Full_Evidence_Success@3", "Spoiler_Violation@3",
        "Hit@5", "Recall@5", "Full_Evidence_Success@5", "Spoiler_Violation@5",
        "Hit@10", "Recall@10", "Full_Evidence_Success@10", "Spoiler_Violation@10", "MRR"
    ):
        key_lower = k.lower().replace("full_evidence_", "")
        k_val = k_overall[key_lower]
        c_val = c_overall[key_lower]
        k_historical_overall[k] = {
            "K": k_val,
            "CONSENSUS": c_val,
            "delta": c_val - k_val,
        }

    # Interpretation statement
    if verdict == "SUPPORTED":
        interp = (
            f"Equal-weight rank sum consensus of K and M Top-30 successfully improves Full Evidence Success@10 "
            f"over M alone ({m_overall['success@10']:.4f} -> {c_overall['success@10']:.4f}, +{delta_success10:.4f}) "
            f"while preserving Hit@10 ({c_overall['hit@10']:.4f}) and Recall@10 ({c_overall['recall@10']:.4f}). "
            f"Full-success probes gained: {full_gained}, lost: {full_lost}. "
            f"Combining complementary bi-encoder (K) and cross-encoder (M) ranking signals reduces destructive swaps "
            f"on this frozen benchmark."
        )
    elif verdict == "PARTIALLY_SUPPORTED":
        interp = (
            f"Rank sum consensus produced mixed effects relative to M. Full Evidence Success@10 moved "
            f"{m_overall['success@10']:.4f} -> {c_overall['success@10']:.4f} ({delta_success10:+.4f}), "
            f"Recall@10 moved {m_overall['recall@10']:.4f} -> {c_overall['recall@10']:.4f} ({delta_recall10:+.4f}), "
            f"Hit@10 moved {m_overall['hit@10']:.4f} -> {c_overall['hit@10']:.4f} ({delta_hit10:+.4f}), "
            f"and MRR moved {m_overall['mrr']:.4f} -> {c_overall['mrr']:.4f} ({delta_mrr:+.4f}). "
            f"Full-success probes gained: {full_gained}, lost: {full_lost}."
        )
    else:
        interp = (
            f"Simple equal-weight rank sum consensus failed to improve multi-evidence assembly over M alone. "
            f"Full Evidence Success@10 moved {m_overall['success@10']:.4f} -> {c_overall['success@10']:.4f} ({delta_success10:+.4f}), "
            f"Recall@10 moved {m_overall['recall@10']:.4f} -> {c_overall['recall@10']:.4f} ({delta_recall10:+.4f}), "
            f"and Hit@10 moved {m_overall['hit@10']:.4f} -> {c_overall['hit@10']:.4f} ({delta_hit10:+.4f}). "
            f"Simple rank consensus does not resolve the residual near-boundary ordering bottleneck."
        )

    result = {
        "experiment_id": EXPERIMENT_ID,
        "status": "EXECUTED",
        "benchmark_id": BENCHMARK_ID,
        "primary_control": "BGE_RERANKER_V2_M3_TOP30_V1",
        "historical_context": "DENSE_E5_LARGE_V1",
        "selection_contract": {
            "method": "KM_CONSENSUS_RANK_SUM_V1",
            "formula": "rank_sum(c) = k_rank(c) + m_rank(c) ASC",
            "tie_break": "max(k_rank, m_rank) ASC, min(k_rank, m_rank) ASC, chunk_id ASC",
            "candidate_depth": CANDIDATE_DEPTH,
            "evaluated_ranking": "consensus Top-30 followed by unchanged K tail (> 30)",
            "anti_leakage_gate": "PASS (pure selector with no gold/probe metadata inputs)",
        },
        "artifact_integrity": {
            "status": "PASS",
            "source_sha256": {
                "probe_file": inp["hashes"]["probe_file"],
                "chunks_jsonl": inp["hashes"]["chunks_jsonl"],
                "k_cutoff_ranking": inp["hashes"]["k_cutoff_ranking"],
                "m_reranked_per_probe": inp["hashes"]["m_reranked_per_probe"],
            },
            "k_control_reproduction": "PASS",
            "m_control_reproduction": "PASS",
            "n_diagnostic_reproduction": "PASS",
        },
        "candidate_set_integrity": {
            "status": "PASS",
            "probes": len(probes),
            "candidate_depth_per_probe": CANDIDATE_DEPTH,
            "candidate_set_match_k_m": "PASS (identical 30-candidate set for 15/15 probes)",
        },
        "M_CONTROL": m_agg,
        "CONSENSUS": c_agg,
        "M_COMPARISON": {
            "overall": m_comparison_overall,
        },
        "K_HISTORICAL_CONTEXT": {
            "overall": k_historical_overall,
        },
        "candidate_ceiling": {
            "candidate_complete_probes": len(candidate_complete_pids),
            "candidate_complete_fraction": len(candidate_complete_pids) / len(probes),
            "consensus_full_success_probes": candidate_complete_full_success_probes,
            "ceiling_utilization": ceiling_utilization,
            "note": "descriptive only; evidence outside K Top-30 cannot be recovered",
        },
        "required_evidence_transitions": {
            "total_units": 35,
            "counts": trans_counts,
        },
        "probe_transitions": {
            "m_hit_probes": m_hit_count,
            "consensus_hit_probes": c_hit_count,
            "m_full_success_probes": m_full_count,
            "consensus_full_success_probes": c_full_count,
            "hit_gained": hit_gained,
            "hit_lost": hit_lost,
            "full_success_gained": full_gained,
            "full_success_lost": full_lost,
        },
        "n_failure_population": {
            "population_size": len(n_failure_probes),
            "probes_full_success_under_consensus": n_failure_probes_full_success,
            "probes_remain_failure": n_failure_probes_remains_failure,
            "probes_m_full_fail_improved": n_failure_probes_m_full_fail_improved,
            "probes_worsened": n_failure_probes_worsened,
            "missing_units_analysis": n_missing_summary,
        },
        "local_table_sha256": local_table_hashes,
        "determinism_status": "PENDING_CHECK",
        "privacy_status": "PENDING_CHECK",
        "verdict": verdict,
        "interpretation": interp,
    }

    return {
        "result": result,
        "raw_text": yaml.dump(result, sort_keys=False, allow_unicode=True),
        "local_hashes": local_table_hashes,
    }


def main():
    base_dir = Path(__file__).resolve().parent.parent.parent
    paths = {
        "freeze": base_dir / "benchmarks" / "m1_script_quality" / "long_range_probe" / "LONG_RANGE_PROBE_V1_FREEZE.yaml",
        "probes": base_dir / ".local" / "story_integration" / "otonari_30ch" / "LONG_RANGE_PROBE_V1" / "probes.yaml",
        "chunks": base_dir / ".local" / "story_integration" / "otonari_30ch" / "PARAGRAPH_PACK_V1" / "chunks.jsonl",
        "k_detail": base_dir / ".local" / "story_integration" / "otonari_30ch" / "DENSE_E5_LARGE_V1" / "cutoff_filtered_per_probe.jsonl",
        "m_detail": base_dir / ".local" / "story_integration" / "otonari_30ch" / "BGE_RERANKER_V2_M3_TOP30_V1" / "reranked_per_probe.jsonl",
        "k_result": base_dir / "benchmarks" / "m1_script_quality" / "long_range_probe" / "DENSE_E5_LARGE_V1_RESULT.yaml",
        "m_result": base_dir / "benchmarks" / "m1_script_quality" / "long_range_probe" / "BGE_RERANKER_V2_M3_TOP30_V1_RESULT.yaml",
        "n_result": base_dir / "benchmarks" / "m1_script_quality" / "long_range_probe" / "M_FAILURE_MODE_DIAGNOSTIC_V1_RESULT.yaml",
        "out_dir": base_dir / ".local" / "story_integration" / "otonari_30ch" / "KM_CONSENSUS_RANK_SUM_V1",
        "public_result": base_dir / "benchmarks" / "m1_script_quality" / "long_range_probe" / "KM_CONSENSUS_RANK_SUM_V1_RESULT.yaml",
    }

    print("Running Pass 1...")
    run1 = run_experiment(paths)

    print("Running Pass 2 (Determinism verification)...")
    run2 = run_experiment(paths)

    # Check determinism between pass 1 and pass 2
    if run1["local_hashes"] != run2["local_hashes"]:
        raise GateFailure("DETERMINISM FAILED: local table hashes differ between runs")

    res1 = copy.deepcopy(run1["result"])
    res2 = copy.deepcopy(run2["result"])
    # Set status
    res1["determinism_status"] = "PASS"
    res2["determinism_status"] = "PASS"

    # Privacy verification
    forbidden = []
    # Load probes to get forbidden questions/answers
    probes = _yaml(paths["probes"])["probes"]
    for p in probes:
        forbidden.append(p["question"])
        forbidden.append(p["expected_answer"])

    # Convert to yaml string for privacy scan
    yaml_text = yaml.dump(res1, sort_keys=False, allow_unicode=True)
    leaks = find_private_leaks(yaml_text, forbidden)
    if leaks:
        raise GateFailure(f"PRIVACY FAILED: detected private leaks in public result: {leaks}")

    res1["privacy_status"] = "PASS"
    yaml_final = yaml.dump(res1, sort_keys=False, allow_unicode=True)

    # Write public result file
    with open(paths["public_result"], "w", encoding="utf-8", newline="\n") as f:
        f.write(yaml_final)

    print(f"KM_CONSENSUS_RANK_SUM_V1 successfully executed!")
    print(f"Verdict: {res1['verdict']}")
    print(f"Public result written to {paths['public_result']}")


if __name__ == "__main__":
    main()
