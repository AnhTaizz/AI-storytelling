"""Evaluate the public DEV probes and, when present, private cutoff-filtered probes."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import yaml

from tools.story_benchmark.multi_gold_metrics import calculate_probe_metrics
from tools.story_pipeline.source import Passage
from tools.story_retrieval.retrieval_v0 import (
    Bm25RetrieverV0, RetrievalRequest, build_corpus, make_retriever, retrieve,
)
from tools.story_retrieval.retrieve import DEFAULT_MANIFEST, REPO, write_stdout

DEFAULT_PROBES = REPO / 'tests/story_retrieval/fixtures/dev_probes_v0.yaml'
DEFAULT_PRIVATE_ROOT = REPO / '.local/story_integration/otonari_30ch'


def _read_probes(path):
    data = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    return data['probes'] if isinstance(data, dict) else data


def _means(rows):
    return {key: sum(row[key] for row in rows) / len(rows) for key in rows[0]} if rows else {}


def _metrics(probe, ranked_ids, hits, k_values):
    metrics = calculate_probe_metrics(probe, ranked_ids, k_values=k_values)
    for k in k_values:
        top = hits[:k]
        metrics[f'spoiler_violation@{k}'] = (
            sum(h.chapter > probe['cutoff_chapter'] for h in top) / len(top) if top else 0.0)
    return metrics


def evaluate_dev(probes_path, manifest_path, retrievers, k_values=(1, 5, 10)) -> dict:
    k_values = tuple(k_values)
    if not k_values or any(not isinstance(k, int) or k < 1 for k in k_values):
        raise ValueError('k_values must contain positive integers')
    probes = _read_probes(probes_path)
    passages = build_corpus(manifest_path, max(p['cutoff_chapter'] for p in probes))
    result = {}
    for retriever in retrievers:
        rows = []
        by_language = defaultdict(list)
        for probe in probes:
            hits = retrieve(RetrievalRequest(probe['query'], probe['cutoff_chapter'], max(k_values)),
                            retriever, passages)
            metrics = _metrics(probe, [h.passage_id for h in hits], hits, k_values)
            rows.append({'probe_id': probe['probe_id'], 'language': probe['language'],
                         'metrics': metrics,
                         'ranking': [{'passage_id': h.passage_id, 'rank': h.rank} for h in hits]})
            by_language[probe['language']].append(metrics)
        result[retriever.name] = {
            'overall': _means([row['metrics'] for row in rows]),
            'per_language': {lang: _means(values) for lang, values in sorted(by_language.items())},
            'per_probe': rows,
        }
    return {'probe_count': len(probes), 'retrievers': result}


def evaluate_private(root, retrievers=None) -> dict | None:
    """Return aggregates only; private queries, evidence IDs and text never leave this function.

    Index the entire pack for the frozen BM25 corpus statistics, then restrict the
    eligible IDs for each cutoff. MRR is measured through the comparison depth (10).
    """
    root = Path(root)
    probes_path = root / 'LONG_RANGE_PROBE_V1/probes.yaml'
    chunks_path = root / 'PARAGRAPH_PACK_V1/chunks.jsonl'
    if not probes_path.is_file() or not chunks_path.is_file():
        return None
    chunks = [json.loads(line) for line in chunks_path.read_text(encoding='utf-8').splitlines()
              if line.strip()]
    chunks.sort(key=lambda row: (row['chapter_number'], row['chunk_index']))
    passages = [Passage(f"{row['chapter_number']}.{row['chunk_index']}", row['text']) for row in chunks]
    chunk_ids = {p.passage_id: row['chunk_id'] for p, row in zip(passages, chunks)}
    if len(chunk_ids) != len(passages):
        raise ValueError('private pack contains duplicate chapter/chunk indices')
    probes = _read_probes(probes_path)
    result = {}
    for retriever in retrievers if retrievers is not None else [Bm25RetrieverV0()]:
        rows = []
        for probe in probes:
            hits = retrieve(RetrievalRequest(probe['question'], probe['cutoff_chapter'], 10),
                            retriever, passages)
            ranked_ids = [chunk_ids[h.passage_id] for h in hits]
            rows.append(_metrics(probe, ranked_ids, hits, (1, 3, 5, 10)))
        result[retriever.name] = _means(rows)
    return {'mode': 'CUTOFF_FILTERED', 'probe_count': len(probes), 'retrievers': result}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--retriever', nargs='+', choices=('bm25', 'dense_e5', 'hybrid'), default=['bm25'])
    parser.add_argument('--private-root', type=Path, default=DEFAULT_PRIVATE_ROOT)
    parser.add_argument('--json', action='store_true')
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    try:
        retrievers = [make_retriever(name) for name in args.retriever]
        dev = evaluate_dev(DEFAULT_PROBES, DEFAULT_MANIFEST, retrievers)
        summary = {'dev': {'probe_count': dev['probe_count'], 'retrievers': {
            name: {key: value for key, value in values.items() if key != 'per_probe'}
            for name, values in dev['retrievers'].items()}},
            'private': evaluate_private(args.private_root, retrievers)}
        if args.json:
            write_stdout(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            for section, values in summary.items():
                write_stdout(f'{section}: ' + (json.dumps(values, ensure_ascii=False) if values else 'not run'))
        return 0
    except (ValueError, OSError, RuntimeError, ImportError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
