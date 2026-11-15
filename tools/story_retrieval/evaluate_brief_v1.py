"""Evaluate brief retrieval (M6 Phase 2) on the DEV probes against pinned chapter briefs.

Routes, all measured on the passages actually delivered (gold is passage ids):
- `passage_bm25`: v0 passage retrieval (the Phase 1 baseline that runs without a model);
- `brief_bm25`: the evidence of the top brief items, in rank order (`delivery`);
- `brief_then_passage`: brief evidence first, then passage hits not yet delivered.

    python -m tools.story_retrieval.evaluate_brief_v1 [--probes ...] [--briefs DIR] [--k-values 5 10 20 30]

No model calls. The pinned briefs are model output for public chapters 1-5
(tests/story_retrieval/fixtures/briefs_sample_v1); see DEC-021.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Sequence

import yaml

from tools.story_benchmark.multi_gold_metrics import calculate_probe_metrics
from tools.story_retrieval.brief_retrieval_v1 import build_brief_corpus, delivery, retrieve_briefs
from tools.story_retrieval.retrieval_v0 import Bm25RetrieverV0, RetrievalRequest, build_corpus, retrieve
from tools.story_retrieval.retrieve import DEFAULT_MANIFEST, REPO

DEFAULT_PROBES = REPO / "tests/story_retrieval/fixtures/dev_probes_v1.yaml"
DEFAULT_BRIEFS = REPO / "tests/story_retrieval/fixtures/briefs_sample_v1"
ROUTES = ("passage_bm25", "brief_bm25", "brief_then_passage")


def load_briefs(directory: Path | str) -> List[Dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8"))["brief"] for p in sorted(Path(directory).glob("chapter_*.json"))]


def _mean(rows: Sequence[Dict[str, float]]) -> Dict[str, float]:
    return {key: round(sum(r[key] for r in rows) / len(rows), 4) for key in rows[0]} if rows else {}


def evaluate(probes_path=DEFAULT_PROBES, briefs_dir=DEFAULT_BRIEFS, manifest_path=DEFAULT_MANIFEST,
             k_values: Sequence[int] = (5, 10, 20, 30), item_k: int = 30) -> Dict[str, Any]:
    if not k_values or any(k < 1 for k in k_values):
        raise ValueError("k_values must be positive")
    probes = yaml.safe_load(Path(probes_path).read_text(encoding="utf-8"))["probes"]
    briefs = load_briefs(briefs_dir)
    passages = build_corpus(manifest_path, max(p["cutoff_chapter"] for p in probes))
    passage_retriever = Bm25RetrieverV0()
    budget = max(k_values)
    rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    covered = 0
    for probe in probes:
        cutoff = probe["cutoff_chapter"]
        corpus = build_brief_corpus(passages.story_id, briefs, passages, cutoff, "vi")
        cited = {pid for item in corpus.items for pid in item.evidence}
        covered += any(set(group) <= cited for group in probe["gold_evidence_sets"])
        passage_ids = [h.passage_id for h in retrieve(RetrievalRequest(probe["query"], cutoff, budget),
                                                      passage_retriever, passages)]
        brief_ids = delivery(retrieve_briefs(probe["query"], corpus, k=item_k), budget)["passage_ids"]
        routes = {"passage_bm25": passage_ids, "brief_bm25": brief_ids,
                  "brief_then_passage": brief_ids + [pid for pid in passage_ids if pid not in brief_ids]}
        for route, ranked in routes.items():
            if any(int(pid.split(".")[0]) > cutoff for pid in ranked):
                raise RuntimeError(f"{route}: {probe['probe_id']} delivered a passage after the cutoff")
            metrics = calculate_probe_metrics(probe, ranked[:budget], k_values=tuple(k_values))
            metrics.pop("mrr", None)
            rows[route].append({"language": probe["language"], "metrics": metrics})
    result: Dict[str, Any] = {"probe_count": len(probes), "brief_coverage": round(covered / len(probes), 4),
                              "item_k": item_k, "routes": {}}
    for route in ROUTES:
        by_language = defaultdict(list)
        for row in rows[route]:
            by_language[row["language"]].append(row["metrics"])
        result["routes"][route] = {"overall": _mean([r["metrics"] for r in rows[route]]),
                                   "per_language": {lang: _mean(v) for lang, v in sorted(by_language.items())}}
    return result


def table(result: Dict[str, Any], k_values: Sequence[int]) -> str:
    lines = [f"probes: {result['probe_count']}; gold fully cited by some brief item: "
             f"{result['brief_coverage']:.1%}", "",
             "| Route | Language | " + " | ".join(f"Recall@{k} / Success@{k}" for k in k_values) + " |",
             "|---|---|" + "---|" * len(k_values)]
    for route, data in result["routes"].items():
        for language, metrics in [("all", data["overall"]), *data["per_language"].items()]:
            cells = [f"{metrics[f'recall@{k}']:.1%} / {metrics[f'success@{k}']:.1%}" for k in k_values]
            lines.append(f"| {route} | {language} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--probes", type=Path, default=DEFAULT_PROBES)
    parser.add_argument("--briefs", type=Path, default=DEFAULT_BRIEFS)
    parser.add_argument("--k-values", type=int, nargs="+", default=[5, 10, 20, 30])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = evaluate(args.probes, args.briefs, k_values=args.k_values)
    sys.stdout.write((json.dumps(result, ensure_ascii=False, indent=1) if args.json
                      else table(result, args.k_values)) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
