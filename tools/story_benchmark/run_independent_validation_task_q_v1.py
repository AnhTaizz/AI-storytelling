"""TASK Q executor for the frozen INDEPENDENT_VALIDATION_FIXTURE_V1.

Orchestration only.  Ranking behavior comes unchanged from the frozen cores:
  K  tools/story_benchmark/dense_e5_large_v1.py
  M  tools/story_benchmark/bge_reranker_v2_m3_top30_v1.py
  O  tools/story_benchmark/km_consensus_rank_sum_v1.py
  metrics  tools/story_benchmark/multi_gold_metrics.py
Protocol: INDEPENDENT_VALIDATION_FIXTURE_V1_SPEC.md section 6 (pre-registered).

Gold blindness: every ranking stage receives only ``RankingQuery`` (question and
cutoff).  All three rankings are persisted before any gold field is read.

Declarations fixed before execution (not tuning; they implement the protocol):
- Candidate pool for M and O is the first min(30, eligible_pool) K ids, exactly
  as the frozen M method defines it; ``select_consensus`` is therefore called
  with ``expected_depth = min(30, pool)``.  Ranking formulas are unchanged.
- Paired bootstrap: ``numpy.random.default_rng(42)``, B index vectors of size n
  drawn with replacement, the same indices for M and O; 95% percentile CI
  (numpy linear interpolation) of the per-resample mean difference O - M.
- Exact McNemar: two-sided binomial test on discordant pairs (p = 1 if none).
- Paired permutation: exact enumeration of all 2^n sign flips of the per-probe
  differences; two-sided p on |mean difference|.
- Descriptive classes are applied exactly as pre-registered.  The pre-registered
  rules do not cover "no decrease, some increase, success unchanged"; that case
  is reported as ``PREREGISTERED_RULES_DO_NOT_COVER`` rather than assigned.

This file contains no fixture content.
"""
import argparse
import hashlib
import json
import math
import platform
import re
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime
from itertools import product
from pathlib import Path
from typing import Callable, Dict, List, Sequence

import yaml

from tools.story_benchmark import bge_reranker_v2_m3_top30_v1 as M
from tools.story_benchmark import dense_e5_large_v1 as K
from tools.story_benchmark import fixture_freeze as ff
from tools.story_benchmark import km_consensus_rank_sum_v1 as O
from tools.story_benchmark.multi_gold_metrics import (
    calculate_probe_metrics,
    normalize_gold_evidence_sets,
)

TASK_ID = "M1-30CH-Q-INDEPENDENT-VALIDATION-EXECUTION"
EXPECTED_PRIMARY = 16
EXPECTED_SINGLE_GOLD = 14
EXPECTED_MULTI_GOLD = 2
TOP_K = 10
METRIC_KEYS = ("success@10", "recall@10", "hit@10", "mrr")
CLASS_METRICS = ("success@10", "recall@10", "hit@10")
EPS = 1e-12


class TaskQGateError(RuntimeError):
    """Integrity or protocol gate failure: the run is NOT_EVALUABLE."""


def sha256_path(path) -> str:
    return ff.sha256_path(Path(path))


# ---------------------------------------------------------------------------
# Input gates
# ---------------------------------------------------------------------------

def load_frozen_probes(frozen_zip: Path, expected_sha256: str) -> List[dict]:
    """Probes come only from frozen_primary_fixture.yaml inside the frozen ZIP."""
    if sha256_path(frozen_zip) != expected_sha256:
        raise TaskQGateError("frozen fixture hash mismatch")
    try:
        with zipfile.ZipFile(frozen_zip) as zf:
            names = [n for n in zf.namelist() if n.rsplit("/", 1)[-1] == "frozen_primary_fixture.yaml"]
            if len(names) != 1:
                raise TaskQGateError("frozen_primary_fixture.yaml not found exactly once")
            fixture = yaml.safe_load(zf.read(names[0]).decode("utf-8"))
    except zipfile.BadZipFile as exc:
        raise TaskQGateError(f"not a frozen fixture package: {exc}") from exc
    if fixture.get("status") != "FROZEN" or fixture.get("frozen") is not True:
        raise TaskQGateError("fixture is not frozen")
    if fixture.get("evaluation_allowed") is not True:
        raise TaskQGateError("evaluation not allowed by frozen fixture")
    probes = fixture.get("probes") or []
    counts = [len(normalize_gold_evidence_sets(p)) for p in probes]
    if (len(probes), sum(c == 1 for c in counts), sum(c > 1 for c in counts)) != (
        EXPECTED_PRIMARY, EXPECTED_SINGLE_GOLD, EXPECTED_MULTI_GOLD
    ):
        raise TaskQGateError(
            f"population mismatch: {len(probes)} probes, {sum(c == 1 for c in counts)} single, "
            f"{sum(c > 1 for c in counts)} multi"
        )
    return probes


def verify_run_plan(plan_path: Path, expected_plan_sha256: str, frozen_zip: Path) -> dict:
    if sha256_path(plan_path) != expected_plan_sha256:
        raise TaskQGateError("run plan hash mismatch (plan modified)")
    plan = yaml.safe_load(Path(plan_path).read_text(encoding="utf-8"))
    check = ff.validate_task_q_run_plan(plan, frozen_zip)
    if not check["pass"]:
        raise TaskQGateError(f"run plan invalid: {check['issues']}")
    check_core_matches_plan(plan)
    return plan


def check_core_matches_plan(plan: dict, k_core=K, m_core=M, o_core=O) -> None:
    """The frozen core constants must equal what the plan pre-registered."""
    expected = [
        (plan["method_K"]["model"], k_core.MODEL_ID, "K model"),
        (plan["method_K"]["revision"], k_core.MODEL_REVISION, "K revision"),
        (plan["method_M"]["model"], m_core.MODEL_ID, "M model"),
        (plan["method_M"]["revision"], m_core.MODEL_REVISION, "M revision"),
        (plan["candidate_depth"], m_core.CANDIDATE_DEPTH, "M candidate depth"),
        (plan["candidate_depth"], o_core.CANDIDATE_DEPTH, "O candidate depth"),
        (plan["top_k"], TOP_K, "top_k"),
        ("query: ", k_core.QUERY_PREFIX, "K query prefix"),
        ("passage: ", k_core.PASSAGE_PREFIX, "K passage prefix"),
        ("cpu", k_core.EXECUTION_DEVICE, "K device"),
        ("cpu", m_core.EXECUTION_DEVICE, "M device"),
        ("float32", m_core.DTYPE, "M dtype"),
    ]
    for want, have, label in expected:
        if want != have:
            raise TaskQGateError(f"{label} mismatch: plan {want!r} vs core {have!r}")


def load_corpus(chunks_path: Path, expected_sha256: str, corpus_fingerprint: str):
    if sha256_path(chunks_path) != expected_sha256:
        raise TaskQGateError("chunks.jsonl hash mismatch")
    doc_ids, texts, chapters = [], {}, {}
    for line in Path(chunks_path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("corpus_fingerprint_sha256") != corpus_fingerprint:
            raise TaskQGateError("corpus fingerprint mismatch")
        doc_ids.append(row["chunk_id"])
        texts[row["chunk_id"]] = row["text"]
        chapters[row["chunk_id"]] = row["chapter_number"]
    return doc_ids, texts, chapters


# ---------------------------------------------------------------------------
# Gold-blind ranking stages
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RankingQuery:
    """The only probe information any ranking stage may see."""
    index: int
    question: str
    cutoff_chapter: int


def ranking_view(probes: Sequence[dict]) -> List[RankingQuery]:
    return [RankingQuery(i, p["question"], int(p["cutoff_chapter"])) for i, p in enumerate(probes)]


def k_rank(query: RankingQuery, q_emb, doc_ids, doc_embeddings, chapters) -> List[str]:
    allowed = K.eligible_doc_ids(chapters, query.cutoff_chapter)
    ranked = K.rank_by_cosine(doc_ids, doc_embeddings, q_emb, allowed_doc_ids=allowed)
    ids = [d for d, _ in ranked]
    if any(chapters[c] > query.cutoff_chapter for c in ids):
        raise TaskQGateError("K ranking contains a chunk beyond cutoff")
    if set(ids) != allowed:
        raise TaskQGateError("K ranking does not cover the eligible pool exactly")
    return ids


def m_rank(query: RankingQuery, k_ids: Sequence[str], texts: Dict[str, str],
           score_fn: Callable[[str, str], float]) -> dict:
    candidates = M.extract_candidates(k_ids)
    scores = {c: float(score_fn(query.question, texts[c])) for c in candidates}
    ordered = M.rerank_order(candidates, scores)
    after = [c for c, _ in ordered]
    M.check_candidate_equality(candidates, after, len(k_ids))
    return {
        "candidates": candidates,
        "reranked_top": after,
        "scores": [s for _, s in ordered],
        "evaluated_ranking": M.evaluated_ranking(after, k_ids),
    }


def o_rank(k_ids: Sequence[str], m_top: Sequence[str]) -> dict:
    """Receives only chunk-ID orderings: no query, cutoff, category, or gold."""
    depth = min(O.CANDIDATE_DEPTH, len(k_ids))
    k_top = list(k_ids[:depth])
    selected = O.select_consensus(k_top, list(m_top), expected_depth=depth)
    return {"consensus_top": selected, "depth": depth,
            "evaluated_ranking": O.evaluated_ranking(selected, k_ids)}


# ---------------------------------------------------------------------------
# Metrics and statistics (gold is read only here)
# ---------------------------------------------------------------------------

def probe_metrics(probe: dict, ranking: Sequence[str]) -> dict:
    metrics = calculate_probe_metrics(probe, ranking, k_values=(TOP_K,))
    return {key: metrics[key] for key in METRIC_KEYS}


def aggregate(per_probe: Sequence[dict]) -> dict:
    n = len(per_probe)
    out = {"n": n}
    for key in METRIC_KEYS:
        values = [row[key] for row in per_probe]
        out[key] = sum(values) / n
        if key in ("success@10", "hit@10"):
            out[f"{key}_count"] = int(sum(values))
    return out


def deltas(o_agg: dict, m_agg: dict) -> dict:
    return {key: o_agg[key] - m_agg[key] for key in METRIC_KEYS}


def descriptive_class(delta: dict, integrity_ok: bool = True) -> str:
    if not integrity_ok:
        return "NOT_EVALUABLE"
    up = [delta[k] > EPS for k in CLASS_METRICS]
    down = [delta[k] < -EPS for k in CLASS_METRICS]
    if delta["success@10"] > EPS and delta["recall@10"] >= -EPS and delta["hit@10"] >= -EPS:
        return "DESCRIPTIVE_SUPPORT"
    if any(up) and any(down):
        return "MIXED_TRADE_OFF"
    if not any(up):
        return "NO_OBSERVED_GAIN"
    return "PREREGISTERED_RULES_DO_NOT_COVER"


def paired_bootstrap(m_values: Sequence[float], o_values: Sequence[float], B: int, seed: int) -> dict:
    import numpy as np
    m_arr, o_arr = np.asarray(m_values, dtype=float), np.asarray(o_values, dtype=float)
    n = len(m_arr)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(B, n))
    diffs = o_arr[idx].mean(axis=1) - m_arr[idx].mean(axis=1)
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return {"B": B, "seed": seed, "observed_delta": float(o_arr.mean() - m_arr.mean()),
            "ci95_low": float(lo), "ci95_high": float(hi)}


def mcnemar_exact(m_success: Sequence[int], o_success: Sequence[int]) -> dict:
    b = sum(1 for m, o in zip(m_success, o_success) if m == 0 and o == 1)
    c = sum(1 for m, o in zip(m_success, o_success) if m == 1 and o == 0)
    n = b + c
    if n == 0:
        p = 1.0
    else:
        tail = sum(math.comb(n, i) for i in range(0, min(b, c) + 1)) / 2 ** n
        p = min(1.0, 2 * tail)
    return {"m_fail_o_success": b, "m_success_o_fail": c, "discordant": n, "p_value_two_sided": p}


def paired_permutation_exact(m_values: Sequence[float], o_values: Sequence[float]) -> dict:
    diffs = [o - m for m, o in zip(m_values, o_values)]
    n = len(diffs)
    observed = abs(sum(diffs) / n)
    nonzero = [d for d in diffs if abs(d) > EPS]
    extreme = 0
    for signs in product((1, -1), repeat=len(nonzero)):
        stat = abs(sum(s * d for s, d in zip(signs, nonzero)) / n)
        if stat >= observed - EPS:
            extreme += 1
    total = 2 ** len(nonzero)
    return {"method": "exact sign-flip enumeration", "permutations": total,
            "observed_abs_mean_delta": observed, "p_value_two_sided": extreme / total}


def transitions(m_rows: Sequence[dict], o_rows: Sequence[dict]) -> dict:
    success = {"m_fail_o_success": 0, "m_success_o_fail": 0, "both_success": 0, "both_fail": 0}
    recall = {"improved": 0, "unchanged": 0, "worsened": 0}
    per_probe = []
    for m_row, o_row in zip(m_rows, o_rows):
        ms, os_ = m_row["success@10"], o_row["success@10"]
        s_key = ("both_success" if ms and os_ else "both_fail" if not ms and not os_
                 else "m_fail_o_success" if os_ else "m_success_o_fail")
        d = o_row["recall@10"] - m_row["recall@10"]
        r_key = "improved" if d > EPS else "worsened" if d < -EPS else "unchanged"
        success[s_key] += 1
        recall[r_key] += 1
        per_probe.append({"success_transition": s_key, "recall_transition": r_key})
    return {"success": success, "recall": recall, "per_probe": per_probe}


# ---------------------------------------------------------------------------
# Public summary guard
# ---------------------------------------------------------------------------

PRIVATE_PATTERNS = [
    (re.compile(r"[぀-ヿ㐀-鿿]"), "Japanese text"),
    (re.compile(r"ch\d{3}_c\d{4}"), "chunk ID"),
    (re.compile(r"\bV_[A-Z]+_\d{2}\b"), "probe ID"),
]
PRIVATE_KEYS = {"question", "expected_answer", "propositions", "evaluated_ranking", "reranked_top",
                "consensus_top", "candidates", "per_probe", "gold_evidence_sets", "scores", "source_excerpt"}


def check_public_summary(summary: dict) -> List[str]:
    findings = []
    text = json.dumps(summary, ensure_ascii=False)
    for pattern, label in PRIVATE_PATTERNS:
        if pattern.search(text):
            findings.append(label)

    def walk(obj, path=""):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in PRIVATE_KEYS:
                    findings.append(f"private key {path}/{key}")
                walk(value, f"{path}/{key}")
        elif isinstance(obj, list):
            for i, value in enumerate(obj):
                walk(value, f"{path}[{i}]")
    walk(summary)
    return findings


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _write_jsonl(path: Path, rows: Sequence[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows),
                    encoding="utf-8", newline="\n")


def execute(args) -> dict:
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=False)
    log_lines: List[str] = []

    def log(msg):
        line = f"{datetime.now().astimezone().isoformat(timespec='seconds')} {msg}"
        log_lines.append(line)
        print(line, flush=True)
        (out / "run_log.txt").write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    # Phase 1-2: identities and plan before any model loads.
    frozen_check = ff.validate_frozen_fixture(Path(args.frozen_zip), Path(args.source_zip),
                                              args.source_sha256, EXPECTED_PRIMARY)
    if not frozen_check["pass"]:
        raise TaskQGateError(f"frozen fixture validation failed: {frozen_check['issues']}")
    plan = verify_run_plan(Path(args.run_plan), args.run_plan_sha256, Path(args.frozen_zip))
    probes = load_frozen_probes(Path(args.frozen_zip), args.frozen_sha256)
    signoff_sha = _signoff_sha(Path(args.frozen_zip))
    if signoff_sha != args.signoff_sha256:
        raise TaskQGateError("human sign-off hash mismatch")
    doc_ids, texts, chapters = load_corpus(Path(args.chunks), args.chunks_sha256, args.corpus_fingerprint)
    integrity = {
        "frozen_fixture_sha256": args.frozen_sha256,
        "source_package_sha256": args.source_sha256,
        "human_signoff_sha256": signoff_sha,
        "task_q_run_plan_sha256": args.run_plan_sha256,
        "corpus_fingerprint_sha256": args.corpus_fingerprint,
        "chunks_jsonl_sha256": args.chunks_sha256,
        "frozen_fixture_validation": frozen_check,
        "run_plan_validation": "PASS",
        "probe_source": "frozen_primary_fixture.yaml inside the frozen ZIP only",
    }
    (out / "input_integrity.json").write_text(json.dumps(integrity, indent=2) + "\n", encoding="utf-8")
    log("integrity gates passed")

    queries = ranking_view(probes)

    # Phase 7: K.
    dense = K.DenseE5LargeV1()
    k_info = dense.get_model_info()
    if k_info["embedding_dimension"] != K.EXPECTED_EMBEDDING_DIMENSION or k_info["max_seq_length"] != K.MAX_SEQ_LENGTH:
        raise TaskQGateError("K model gate: embedding dimension / max_seq_length mismatch")
    dense.encode_documents(doc_ids, [texts[d] for d in doc_ids])
    k_rankings = []
    for q in queries:
        q_emb = dense.encode_queries([q.question])[0]
        k_rankings.append(k_rank(q, q_emb, dense.doc_ids, dense.doc_embeddings, chapters))
    k_info["passage_truncation_count"] = dense.passage_truncation_count
    k_info["query_truncation_count"] = dense.query_truncation_count
    del dense
    log("K rankings complete")

    # Phase 8: M.
    reranker = M.BgeRerankerV2M3()
    m_info = reranker.get_model_info()
    if m_info["num_labels"] != 1 or m_info["dtype"] != "torch.float32":
        raise TaskQGateError("M model gate: unexpected head or dtype")
    m_results = [m_rank(q, k_rankings[q.index], texts, lambda qq, pp: reranker.score(qq, pp)[0])
                 for q in queries]
    log("M rankings complete")

    # Phase 9: O (chunk-ID orderings only).
    o_results = [o_rank(k_rankings[i], m_results[i]["reranked_top"]) for i in range(len(queries))]
    log("O rankings complete")

    # Phase 11: persist rankings BEFORE reading gold.
    ranking_rows = []
    for i, p in enumerate(probes):
        ranking_rows.append({
            "probe_id": p["probe_id"], "pool_size": len(k_rankings[i]),
            "k_ranking": k_rankings[i],
            "m_candidates": m_results[i]["candidates"], "m_reranked_top": m_results[i]["reranked_top"],
            "m_scores": m_results[i]["scores"], "m_evaluated_ranking": m_results[i]["evaluated_ranking"],
            "o_depth": o_results[i]["depth"], "o_consensus_top": o_results[i]["consensus_top"],
            "o_evaluated_ranking": o_results[i]["evaluated_ranking"],
        })
    _write_jsonl(out / "rankings_before_gold.jsonl", ranking_rows)
    rankings_sha = sha256_path(out / "rankings_before_gold.jsonl")
    log(f"rankings persisted before gold read: sha256={rankings_sha}")

    # Phase 10: metrics (first gold read).
    rows = {"K": [], "M": [], "O": []}
    for i, p in enumerate(probes):
        for name, ranking in (("K", k_rankings[i]), ("M", m_results[i]["evaluated_ranking"]),
                              ("O", o_results[i]["evaluated_ranking"])):
            rows[name].append({"probe_id": p["probe_id"], "category": p["category"],
                               "gold_set_count": len(p["gold_evidence_sets"]),
                               **probe_metrics(p, ranking)})
    for name, filename in (("K", "k_per_probe.jsonl"), ("M", "m_per_probe.jsonl"), ("O", "o_per_probe.jsonl")):
        _write_jsonl(out / filename, rows[name])

    aggs = {name: aggregate(rows[name]) for name in rows}
    delta = deltas(aggs["O"], aggs["M"])
    klass = descriptive_class(delta)
    B, seed = plan["bootstrap_B"], plan["bootstrap_seed"]
    boot = {key: paired_bootstrap([r[key] for r in rows["M"]], [r[key] for r in rows["O"]], B, seed)
            for key in METRIC_KEYS}
    mcn = mcnemar_exact([r["success@10"] for r in rows["M"]], [r["success@10"] for r in rows["O"]])
    perm = paired_permutation_exact([r["success@10"] for r in rows["M"]], [r["success@10"] for r in rows["O"]])
    trans = transitions(rows["M"], rows["O"])
    _write_jsonl(out / "transitions_private.jsonl",
                 [{"probe_id": p["probe_id"], **t} for p, t in zip(probes, trans["per_probe"])])
    log("metrics and statistics complete")

    env = {
        "python": sys.version, "platform": platform.platform(),
        "K_model": k_info, "M_model": m_info,
        "o_depth_by_pool": sorted({r["o_depth"] for r in ranking_rows}),
        "pools_below_30": sum(1 for r in ranking_rows if r["pool_size"] < 30),
    }
    (out / "execution_environment.json").write_text(json.dumps(env, indent=2) + "\n", encoding="utf-8")
    results = {
        "aggregates": aggs, "deltas_O_minus_M": delta, "descriptive_class": klass,
        "bootstrap": boot, "mcnemar_exact": mcn, "paired_permutation_exact": perm,
        "transitions": {"success": trans["success"], "recall": trans["recall"]},
    }
    (out / "aggregate_results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    return {"results": results, "env": env, "integrity": integrity, "rankings_sha256": rankings_sha,
            "plan": plan}


def _signoff_sha(frozen_zip: Path) -> str:
    with zipfile.ZipFile(frozen_zip) as zf:
        name = next(n for n in zf.namelist() if n.endswith("human_signoff_v3.csv"))
        return hashlib.sha256(zf.read(name)).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("frozen-zip", "frozen-sha256", "source-zip", "source-sha256", "signoff-sha256",
                 "run-plan", "run-plan-sha256", "chunks", "chunks-sha256", "corpus-fingerprint", "out-dir"):
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args(argv)
    started = time.time()
    result = execute(args)
    print(json.dumps({"seconds": round(time.time() - started, 1), **result["results"]}, indent=2))


if __name__ == "__main__":
    main()
