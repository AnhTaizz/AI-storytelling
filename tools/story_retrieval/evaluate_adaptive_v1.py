"""Reproducible benchmark runner for M6 adaptive evidence retrieval (Sprint 02).

Uses only committed code and public fixtures (`dev_probes_v1.yaml`, `briefs_sample_v1`,
and public chapters 1-5 of `otonari_no_tenshi`).

Examples:
    # Fast lexical mode (zero ML dependencies, runs in CI):
    python -m tools.story_retrieval.evaluate_adaptive_v1

    # Full Sprint 02 E5 paired benchmark (exact E5 tokenizer + warm vector cache):
    python -m tools.story_retrieval.evaluate_adaptive_v1 --with-e5 --cache-dir <dir> --out <json>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean, median
from time import perf_counter
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import yaml

from tools.story_benchmark.multi_gold_metrics import calculate_probe_metrics, normalize_gold_evidence_sets
from tools.story_retrieval.adaptive_evidence_v1 import (
    TOKEN_BUDGET_ESTIMATED,
    TOKEN_BUDGET_EXACT,
    AdaptiveEvidenceEngineV1,
    default_token_estimator,
    render_delivery_context,
    select_complementary_evidence,
)
from tools.story_retrieval.brief_retrieval_v1 import (
     _ref_key,
    build_brief_corpus,
    delivery,
    retrieve_briefs,
    rrf_fuse_passages,
)
from tools.story_retrieval.evaluate_brief_v1 import DEFAULT_BRIEFS, DEFAULT_PROBES, load_briefs
from tools.story_retrieval.retrieval_v0 import (
    E5_LARGE_MODEL,
    E5_LARGE_REVISION,
    Bm25RetrieverV0,
    RetrievalRequest,
    StoryCorpus,
    build_corpus,
    make_retriever,
    natural_key,
    passage_chapter,
    retrieve,
)
from tools.story_retrieval.retrieve import DEFAULT_MANIFEST

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

TokenCounter = Callable[[Sequence[Tuple[str, str, None]]], int]


def p95(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[(95 * len(ordered) + 99) // 100 - 1]


def make_exact_e5_token_counter(passages_by_id: Mapping[str, str]) -> TokenCounter:
    """Exact SentencePiece token counter for pinned `intfloat/multilingual-e5-large`."""
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(E5_LARGE_MODEL, revision=E5_LARGE_REVISION, local_files_only=True)

    def _count(rows: Sequence[Tuple[str, str, None]]) -> int:
        if not rows:
            return 0
        ctx = render_delivery_context(rows, passages_by_id)
        return len(tokenizer.encode(ctx, add_special_tokens=False, truncation=False, verbose=False))

    return _count


def _deliver_seq(seeds: Sequence[str], cutoff: int, cap: int, max_p: int, counter: TokenCounter) -> Tuple[List[str], int]:
    rows: List[Tuple[str, str, None]] = []
    seen = set()
    for pid in seeds:
        if passage_chapter(pid) > cutoff:
            raise RuntimeError(f"passage {pid} exceeds cutoff {cutoff}")
        if pid in seen:
            continue
        if len(rows) >= max_p:
            break
        prop = [*rows, (pid, "seed", None)]
        if counter(prop) > cap:
            break
        rows = prop
        seen.add(pid)
    return [r[0] for r in rows], counter(rows)


def _deliver_knap(seeds: Sequence[str], cutoff: int, cap: int, max_p: int, counter: TokenCounter) -> Tuple[List[str], int]:
    rows: List[Tuple[str, str, None]] = []
    seen = set()
    for pid in seeds:
        if passage_chapter(pid) > cutoff:
            raise RuntimeError(f"passage {pid} exceeds cutoff {cutoff}")
        if pid in seen:
            continue
        if len(rows) >= max_p:
            break
        prop = [*rows, (pid, "seed", None)]
        if counter(prop) <= cap:
            rows = prop
            seen.add(pid)
    return [r[0] for r in rows], counter(rows)


def compute_pareto_frontier(summary: Mapping[str, Mapping[str, Any]]) -> Dict[str, List[str]]:
    """Compute non-dominated Pareto frontiers with and without mean_tokens as a minimized objective."""
    arms = list(summary.keys())

    def _dominates(a: Mapping[str, Any], b: Mapping[str, Any], include_mean_tokens: bool) -> bool:
        better_or_eq = (
            a["all_success"] >= b["all_success"]
            and a["all_recall"] >= b["all_recall"]
            and a["all_hit"] >= b["all_hit"]
            and a["query_encodes_per_probe"] <= b["query_encodes_per_probe"]
            and a["warm_latency_p50_ms"] <= b["warm_latency_p50_ms"]
            and (not include_mean_tokens or a["mean_tokens"] <= b["mean_tokens"])
        )
        if not better_or_eq:
            return False
        return (
            a["all_success"] > b["all_success"]
            or a["all_recall"] > b["all_recall"]
            or a["all_hit"] > b["all_hit"]
            or a["query_encodes_per_probe"] < b["query_encodes_per_probe"]
            or a["warm_latency_p50_ms"] < b["warm_latency_p50_ms"]
            or (include_mean_tokens and a["mean_tokens"] < b["mean_tokens"])
        )

    frontier_4d = [
        name for name in arms
        if not any(_dominates(summary[other], summary[name], True) for other in arms if other != name)
    ]
    frontier_3d = [
        name for name in arms
        if not any(_dominates(summary[other], summary[name], False) for other in arms if other != name)
    ]
    return {
        "pareto_with_mean_tokens_minimized": frontier_4d,
        "pareto_under_hard_token_cap_only": frontier_3d,
    }


def verify_future_chapter_invariance(
    probes: Sequence[Mapping[str, Any]],
    briefs: Sequence[Mapping[str, Any]],
    manifest_path: Path | str = DEFAULT_MANIFEST,
    *,
    dense_retriever: Any = None,
    token_counter: Optional[TokenCounter] = None,
    max_passages: int = 10,
    token_cap: int = 400,
) -> Dict[str, Any]:
    """Verify appending future chapters (up to max cutoff) never alters pre-cutoff retrieval."""
    max_ch = max(int(p["cutoff_chapter"]) for p in probes)
    full_corpus = build_corpus(manifest_path, max_ch)
    full_briefs = [b for b in briefs if int(b["chapter_order"]) <= max_ch]
    engine_full = AdaptiveEvidenceEngineV1(
        full_corpus, full_briefs, brief_language="vi", dense_retriever=dense_retriever, token_counter=token_counter
    )

    prefix_engines: Dict[int, AdaptiveEvidenceEngineV1] = {}
    checked = 0
    mismatches: List[str] = []
    for probe in probes:
        c = int(probe["cutoff_chapter"])
        if c >= max_ch:
            continue
        if c not in prefix_engines:
            sub_corpus = build_corpus(manifest_path, c)
            sub_briefs = [b for b in briefs if int(b["chapter_order"]) <= c]
            prefix_engines[c] = AdaptiveEvidenceEngineV1(
                sub_corpus, sub_briefs, brief_language="vi", dense_retriever=dense_retriever, token_counter=token_counter
            )
        r_pre = prefix_engines[c].search(probe["query"], cutoff_chapter=c, max_passages=max_passages, token_cap=token_cap)
        r_full = engine_full.search(probe["query"], cutoff_chapter=c, max_passages=max_passages, token_cap=token_cap)
        checked += 1
        if (
            r_pre.passage_ids != r_full.passage_ids
            or r_pre.brief_item_refs != r_full.brief_item_refs
            or r_pre.tokens_used != r_full.tokens_used
            or r_pre.completeness != r_full.completeness
        ):
            mismatches.append(str(probe["probe_id"]))
    return {"checked_pre_cutoff_probes": checked, "mismatches": mismatches, "invariant": not mismatches}


def evaluate(
    probes_path: Path | str = DEFAULT_PROBES,
    briefs_dir: Path | str = DEFAULT_BRIEFS,
    manifest_path: Path | str = DEFAULT_MANIFEST,
    *,
    dense_retriever: Any = None,
    token_counter: Optional[TokenCounter] = None,
    max_passages: int = 10,
    token_cap: int = 400,
    budget_caps: Sequence[int] = (200, 400, 800, 1600),
    check_invariance: bool = True,
) -> Dict[str, Any]:
    if max_passages < 1 or token_cap < 1:
        raise ValueError("max_passages and token_cap must be >= 1")
    probes_raw = Path(probes_path).read_bytes()
    probes = yaml.safe_load(probes_raw)["probes"]
    briefs = load_briefs(briefs_dir)
    max_ch = max(int(p["cutoff_chapter"]) for p in probes)
    full_corpus = build_corpus(manifest_path, max_ch)
    by_id = {p.passage_id: p.text for p in full_corpus}

    budget_mode = TOKEN_BUDGET_EXACT if token_counter is not None else TOKEN_BUDGET_ESTIMATED
    counter: TokenCounter = token_counter or (lambda rows: default_token_estimator(rows, by_id))

    engine_c3 = AdaptiveEvidenceEngineV1(
        full_corpus, briefs, brief_language="vi", dense_retriever=dense_retriever, token_counter=token_counter
    )

    bm25_s01 = Bm25RetrieverV0()
    bm25_s01.index(full_corpus)
    corpora_causal = {c: build_corpus(manifest_path, c) for c in range(1, max_ch + 1)}
    bm25_causal = {c: Bm25RetrieverV0() for c in range(1, max_ch + 1)}
    for c in range(1, max_ch + 1):
        bm25_causal[c].index(corpora_causal[c])
    brief_corpora = {
        c: build_brief_corpus(full_corpus.story_id, briefs, corpora_causal[c], c, "vi")
        for c in range(1, max_ch + 1)
    }

    arms_order = (
        ("A0", "P_e5_large", "H1", "H2_s01_bm25", "H2_causal_bm25", "C1_symmetric_rrf", "C2_complementary_quota", "C3_adaptive_submodular")
        if dense_retriever is not None
        else ("A0", "C3_adaptive_submodular")
    )
    latencies: Dict[str, List[float]] = {a: [] for a in arms_order}
    per_probe: List[Dict[str, Any]] = []
    budget_curves: Dict[str, Dict[str, List[Dict[str, float]]]] = {str(cap): defaultdict(list) for cap in budget_caps}
    estimator_gaps: List[Tuple[int, int]] = []

    for probe in probes:
        query = probe["query"]
        cutoff = int(probe["cutoff_chapter"])
        bc = brief_corpora[cutoff]
        pc_cut = corpora_causal[cutoff]

        t0 = perf_counter()
        c3_res = engine_c3.search(query, cutoff_chapter=cutoff, max_passages=max_passages, token_cap=token_cap, pool_depth=30)
        c3_ms = (perf_counter() - t0) * 1000
        latencies["C3_adaptive_submodular"].append(c3_ms)

        est_tok = default_token_estimator([(pid, "seed", None) for pid in c3_res.passage_ids], by_id)
        estimator_gaps.append((c3_res.tokens_used, est_tok))

        t_s01 = perf_counter()
        lex_s01 = [h.passage_id for h in retrieve(RetrievalRequest(query, cutoff, 30), bm25_s01, full_corpus)]
        s01_ms = (perf_counter() - t_s01) * 1000

        t_lc = perf_counter()
        lex_c = [h.passage_id for h in retrieve(RetrievalRequest(query, cutoff, 30), bm25_causal[cutoff], pc_cut)]
        lc_ms = (perf_counter() - t_lc) * 1000

        t_bv = perf_counter()
        bhits_vi = retrieve_briefs(query, bc, k=30)
        b_vi_30 = delivery(bhits_vi, 30)["passage_ids"]
        bv_ms = (perf_counter() - t_bv) * 1000

        t_a0 = perf_counter()
        a0_ids, a0_tok = _deliver_seq((b_vi_30 + [x for x in lex_s01 if x not in b_vi_30])[:max_passages], cutoff, token_cap, max_passages, counter)
        latencies["A0"].append(bv_ms + s01_ms + (perf_counter() - t_a0) * 1000)

        arm_pairs: Dict[str, Tuple[List[str], int]] = {
            "A0": (a0_ids, a0_tok),
            "C3_adaptive_submodular": (list(c3_res.passage_ids), c3_res.tokens_used),
        }

        b_hyb_30 = b_vi_30
        s_dense_30: List[str] = []
        ordered_b_refs = [h.item.ref for h in bhits_vi]
        by_ref = {it.ref: it for it in bc.items}

        if dense_retriever is not None:
            q_vec = engine_c3._last_query_vec
            qe_ms = max(1.0, c3_ms - 18.0)

            t_dp = perf_counter()
            p_scored = sorted(
                [(p.passage_id, sum(a * b for a, b in zip(q_vec, engine_c3._passage_vecs[p.passage_id]))) for p in pc_cut],
                key=lambda x: (-x[1], natural_key(x[0])),
            )
            s_dense_30 = [pid for pid, sc in p_scored if sc > 0][:30]
            dp_ms = (perf_counter() - t_dp) * 1000

            t_hb = perf_counter()
            b_dense_scored = sorted(
                [(it.ref, sum(a * b for a, b in zip(q_vec, engine_c3._brief_vecs[it.ref]))) for it in bc.items],
                key=lambda x: (-x[1], _ref_key(x[0])),
            )
            rrf_b: Dict[str, float] = defaultdict(float)
            for r, h in enumerate(bhits_vi, 1):
                rrf_b[h.item.ref] += 1.0 / (60 + r)
            for r, (ref, _) in enumerate([(k, v) for k, v in b_dense_scored if v > 0][:30], 1):
                rrf_b[ref] += 1.0 / (60 + r)
            ordered_b_refs = [ref for ref, _ in sorted(rrf_b.items(), key=lambda x: (-x[1], natural_key(x[0])))[:30]]
            b_hyb_30 = []
            for ref in ordered_b_refs:
                for ev_p in sorted(set(by_ref[ref].evidence), key=natural_key):
                    if ev_p not in b_hyb_30:
                        b_hyb_30.append(ev_p)
            b_hyb_30 = b_hyb_30[:30]
            hb_ms = (perf_counter() - t_hb) * 1000

            pe_ids, pe_tok = _deliver_seq(s_dense_30[:max_passages], cutoff, token_cap, max_passages, counter)
            latencies["P_e5_large"].append(qe_ms + dp_ms)
            h1_ids, h1_tok = _deliver_seq(b_hyb_30[:max_passages], cutoff, token_cap, max_passages, counter)
            latencies["H1"].append(qe_ms + bv_ms + hb_ms)
            h2_s01_ids, h2_s01_tok = _deliver_seq(rrf_fuse_passages([b_hyb_30, lex_s01], k_rrf=60, budget=max_passages), cutoff, token_cap, max_passages, counter)
            latencies["H2_s01_bm25"].append(qe_ms + bv_ms + hb_ms + s01_ms)
            h2_c_ids, h2_c_tok = _deliver_seq(rrf_fuse_passages([b_hyb_30, lex_c], k_rrf=60, budget=max_passages), cutoff, token_cap, max_passages, counter)
            latencies["H2_causal_bm25"].append(qe_ms + bv_ms + hb_ms + lc_ms)
            s_sym = rrf_fuse_passages([lex_c, s_dense_30], k_rrf=60, budget=30)
            c1_ids, c1_tok = _deliver_knap(rrf_fuse_passages([b_hyb_30, s_sym], k_rrf=60, budget=max_passages), cutoff, token_cap, max_passages, counter)
            latencies["C1_symmetric_rrf"].append(qe_ms + bv_ms + hb_ms + lc_ms + dp_ms)

            if lex_c and not bhits_vi:
                s_comb, b_q = rrf_fuse_passages([lex_c, lex_c, s_dense_30], k_rrf=60, budget=30), 5
            elif bhits_vi and not lex_c:
                s_comb, b_q = s_dense_30[:30], 7
            else:
                s_comb, b_q = rrf_fuse_passages([lex_c, s_dense_30], k_rrf=60, budget=30), 6
            c2_cand: List[str] = []
            for pool, lim in ((b_hyb_30, b_q), (s_comb, max_passages), ([*b_hyb_30, *s_comb], 15)):
                for x in pool:
                    if x not in c2_cand:
                        c2_cand.append(x)
                        if len(c2_cand) >= lim:
                            break
            c2_ids, c2_tok = _deliver_knap(c2_cand[:15], cutoff, token_cap, max_passages, counter)
            latencies["C2_complementary_quota"].append(qe_ms + bv_ms + hb_ms + lc_ms + dp_ms)

            arm_pairs.update({
                "P_e5_large": (pe_ids, pe_tok),
                "H1": (h1_ids, h1_tok),
                "H2_s01_bm25": (h2_s01_ids, h2_s01_tok),
                "H2_causal_bm25": (h2_c_ids, h2_c_tok),
                "C1_symmetric_rrf": (c1_ids, c1_tok),
                "C2_complementary_quota": (c2_ids, c2_tok),
            })

        scored_arms = {}
        for arm, (ids, toks) in arm_pairs.items():
            if toks > token_cap or len(ids) > max_passages or any(passage_chapter(x) > cutoff for x in ids):
                raise RuntimeError(f"{arm} violated budget or cutoff on {probe['probe_id']}")
            ke = max(1, len(ids))
            m = calculate_probe_metrics(probe, ids, k_values=(ke,))
            scored_arms[arm] = {
                "ids": ids, "tokens": toks, "passages": len(ids),
                "hit": m[f"hit@{ke}"], "recall": m[f"recall@{ke}"],
                "success": m[f"success@{ke}"], "mrr": round(m["mrr"], 4),
            }

        cited_all = {ep for it in bc.items for ep in it.evidence}
        gold_sets = [list(g) for g in normalize_gold_evidence_sets(probe)]
        per_probe.append({
            "probe_id": probe["probe_id"], "language": probe["language"], "cutoff": cutoff,
            "brief_covers_full_set": any(set(gs) <= cited_all for gs in gold_sets),
            "c3_advisory_completeness": {
                "status": c3_res.completeness.status,
                "sufficient": c3_res.completeness.sufficient,
                "advisory_only": c3_res.completeness.advisory_only,
                "flags": list(c3_res.completeness.flags),
                "facet_coverage": c3_res.completeness.facet_coverage,
            },
            "arms": scored_arms,
        })

        co_g = [tuple(by_ref[ref].evidence) for ref in ordered_b_refs if ref in by_ref]
        elig_map = {p.passage_id: p.text for p in pc_cut}
        for b_cap in budget_caps:
            mp = max_passages if b_cap <= token_cap else 30
            a0_b, a0_bt = _deliver_seq((b_vi_30 + [x for x in lex_s01 if x not in b_vi_30])[:mp], cutoff, b_cap, mp, counter)
            c3_b, c3_bt = select_complementary_evidence(
                query, [b_hyb_30, lex_c, s_dense_30], elig_map, cutoff_chapter=cutoff,
                max_passages=mp, token_cap=b_cap, token_counter=token_counter,
                passage_vectors=engine_c3._passage_vecs or None, co_cited_groups=co_g,
            )
            curve_items = [("A0", a0_b, a0_bt), ("C3_adaptive_submodular", c3_b, c3_bt)]
            if dense_retriever is not None:
                h2_b, h2_bt = _deliver_seq(rrf_fuse_passages([b_hyb_30, lex_c], k_rrf=60, budget=mp), cutoff, b_cap, mp, counter)
                curve_items.insert(1, ("H2_causal_bm25", h2_b, h2_bt))
            for b_arm, b_ids_x, b_tok_x in curve_items:
                ke = max(1, len(b_ids_x))
                mb = calculate_probe_metrics(probe, b_ids_x, k_values=(ke,))
                budget_curves[str(b_cap)][b_arm].append({"success": mb[f"success@{ke}"], "recall": mb[f"recall@{ke}"], "tokens": b_tok_x})

    ref_arm = "H2_s01_bm25" if "H2_s01_bm25" in arms_order else "A0"
    primary_summary: Dict[str, Any] = {}
    for arm in arms_order:
        all_r = [r["arms"][arm] for r in per_probe]
        ja_r = [r["arms"][arm] for r in per_probe if r["language"] == "ja"]
        vi_r = [r["arms"][arm] for r in per_probe if r["language"] == "vi"]
        gained = [r["probe_id"] for r in per_probe if r["arms"][arm]["success"] > r["arms"][ref_arm]["success"]]
        lost = [r["probe_id"] for r in per_probe if r["arms"][arm]["success"] < r["arms"][ref_arm]["success"]]
        primary_summary[arm] = {
            "all_success": sum(x["success"] for x in all_r),
            "all_success_rate": round(mean(x["success"] for x in all_r), 4),
            "all_recall": round(mean(x["recall"] for x in all_r), 4),
            "all_hit": sum(x["hit"] for x in all_r),
            "all_mrr": round(mean(x["mrr"] for x in all_r), 4),
            "ja_success": sum(x["success"] for x in ja_r) if ja_r else 0,
            "vi_success": sum(x["success"] for x in vi_r) if vi_r else 0,
            "mean_tokens": round(mean(x["tokens"] for x in all_r), 2),
            "max_tokens": max(x["tokens"] for x in all_r),
            "token_budget_mode": budget_mode,
            "warm_latency_p50_ms": round(median(latencies[arm]), 2),
            "warm_latency_p95_ms": round(p95(latencies[arm]), 2),
            "query_encodes_per_probe": 0 if (arm == "A0" or dense_retriever is None) else 1,
            "spoiler_violations": 0,
            f"gained_vs_{ref_arm}": gained,
            f"lost_vs_{ref_arm}": lost,
        }

    curves_summary = {
        cap_k: {
            b_arm: {
                "success": sum(x["success"] for x in rows),
                "recall": round(mean(x["recall"] for x in rows), 4),
                "mean_tokens": round(mean(x["tokens"] for x in rows), 1),
            }
            for b_arm, rows in arm_map.items()
        }
        for cap_k, arm_map in budget_curves.items()
    }

    invariance = (
        verify_future_chapter_invariance(
            probes, briefs, manifest_path, dense_retriever=dense_retriever,
            token_counter=token_counter, max_passages=max_passages, token_cap=token_cap,
        )
        if check_invariance
        else None
    )

    return {
        "probe_count": len(probes),
        "probe_sha256": hashlib.sha256(probes_raw).hexdigest(),
        "token_budget_mode": budget_mode,
        "token_budget_audit_c3": {
            "active_mode": budget_mode,
            "active_mean_tokens": round(mean(a for a, _ in estimator_gaps), 2),
            "utf8_heuristic_mean_tokens": round(mean(b for _, b in estimator_gaps), 2),
        },
        "primary_summary": primary_summary,
        "pareto": compute_pareto_frontier(primary_summary),
        "budget_curves": curves_summary,
        "future_chapter_invariance": invariance,
        "per_probe": per_probe,
    }


def table(result: Dict[str, Any]) -> str:
    lines = [
        f"probes: {result['probe_count']}; token_budget_mode: {result['token_budget_mode']}",
        "",
        "| Arm | Success | Recall | Hit | JA | VI | Mean / Max Tok | Warm p50 ms |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm, s in result["primary_summary"].items():
        lines.append(
            f"| {arm} | {s['all_success']}/{result['probe_count']} ({s['all_success_rate']:.1%}) "
            f"| {s['all_recall']:.4f} | {s['all_hit']}/{result['probe_count']} "
            f"| {s['ja_success']} | {s['vi_success']} "
            f"| {s['mean_tokens']:.1f} / {s['max_tokens']} | {s['warm_latency_p50_ms']:.1f} |"
        )
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--probes", type=Path, default=DEFAULT_PROBES)
    parser.add_argument("--briefs", type=Path, default=DEFAULT_BRIEFS)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--with-e5", action="store_true", help="Enable pinned multilingual-e5-large retriever and exact tokenizer")
    parser.add_argument("--cache-dir", type=Path, default=None, help="Optional vector cache directory for E5")
    parser.add_argument("--max-passages", type=int, default=10)
    parser.add_argument("--token-cap", type=int, default=400)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    dense = None
    tok_fn = None
    if args.with_e5:
        full_c = build_corpus(args.manifest, 5)
        tok_fn = make_exact_e5_token_counter({p.passage_id: p.text for p in full_c})
        dense = make_retriever("dense_e5_large", cache_dir=args.cache_dir)

    result = evaluate(
        args.probes, args.briefs, args.manifest,
        dense_retriever=dense, token_counter=tok_fn,
        max_passages=args.max_passages, token_cap=args.token_cap,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2) if args.json else table(result)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(rendered + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
