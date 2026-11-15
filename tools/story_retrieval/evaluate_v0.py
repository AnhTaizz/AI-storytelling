"""Evaluate the public DEV probes and, when present, private cutoff-filtered probes."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import yaml

from tools.story_benchmark.multi_gold_metrics import calculate_probe_metrics, normalize_gold_evidence_sets
from tools.story_ingestion.light_novel_adapter_v0 import IngestionError
from tools.story_pipeline.source import Passage
from tools.story_retrieval.retrieval_v0 import (
    RETRIEVER_NAMES, Bm25RetrieverV0, RetrievalRequest, StoryCorpus, build_corpus,
    make_retriever, passage_chapter, retrieve,
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


def _depths(k_values):
    k_values = tuple(k_values)
    if not k_values or any(not isinstance(k, int) or k < 1 for k in k_values):
        raise ValueError('k_values must contain positive integers')
    return k_values


def _passage_counts(passages, probes):
    return {'indexed': len(passages), 'by_cutoff': {
        str(cutoff): sum(passage_chapter(p.passage_id) <= cutoff for p in passages)
        for cutoff in sorted({p['cutoff_chapter'] for p in probes})}}


def evaluate_dev(probes_path, manifest_path, retrievers, k_values=(1, 5, 10)) -> dict:
    k_values = _depths(k_values)
    probes = _read_probes(probes_path)
    passages = build_corpus(manifest_path, max(p['cutoff_chapter'] for p in probes))
    result = {}
    for retriever in retrievers:
        rows = []
        by_language = defaultdict(list)
        by_category = defaultdict(list)
        multi = defaultdict(list)
        for probe in probes:
            hits = retrieve(RetrievalRequest(probe['query'], probe['cutoff_chapter'], max(1, len(passages))),
                            retriever, passages)
            ranked_ids = [h.passage_id for h in hits]
            metrics = _metrics(probe, ranked_ids, hits, k_values)
            metrics['mrr@10'] = calculate_probe_metrics(probe, ranked_ids[:10], k_values=())['mrr']
            rows.append({'probe_id': probe['probe_id'], 'language': probe['language'],
                         'metrics': metrics,
                         'ranking': [{'passage_id': h.passage_id, 'rank': h.rank} for h in hits[:max(k_values)]]})
            by_language[probe['language']].append(metrics)
            if 'category' in probe:
                by_category[probe['category']].append(metrics)
            if all(len(group) > 1 for group in normalize_gold_evidence_sets(probe)):
                multi[probe['language']].append(metrics)
        result[retriever.name] = {
            'version': retriever.version,
            'overall': _means([row['metrics'] for row in rows]),
            'per_language': {lang: _means(values) for lang, values in sorted(by_language.items())},
            'per_probe': rows,
        }
        if by_category:
            result[retriever.name]['per_category'] = {
                category: _means(values) for category, values in sorted(by_category.items())}
        if multi:
            multi_rows = [row for values in multi.values() for row in values]
            result[retriever.name]['multi_passage'] = {
                'probe_count': len(multi_rows), 'overall': _means(multi_rows),
                'per_language': {lang: _means(values) for lang, values in sorted(multi.items())}}
    return {'probe_count': len(probes), 'passages_in_scope': _passage_counts(passages, probes),
            'retrievers': result}


def evaluate_private(root, retrievers=None, k_values=(1, 3, 5, 10, 20)) -> dict | None:
    """Return aggregates only; private queries, evidence IDs and text never leave this function.

    Index the entire pack for the frozen BM25 corpus statistics, then restrict the
    eligible IDs for each cutoff. MRR covers the full positive eligible ranking;
    mrr@10 retains the old truncated value for comparison. No per-probe data is returned.
    """
    k_values = tuple(sorted(set((*_depths(k_values), 10))))
    root = Path(root)
    probes_path = root / 'LONG_RANGE_PROBE_V1/probes.yaml'
    chunks_path = root / 'PARAGRAPH_PACK_V1/chunks.jsonl'
    if not probes_path.is_file() or not chunks_path.is_file():
        return None
    chunks = [json.loads(line) for line in chunks_path.read_text(encoding='utf-8').splitlines()
              if line.strip()]
    chunks.sort(key=lambda row: (row['chapter_number'], row['chunk_index']))
    # This legacy pack has no story manifest; the adapter names its own namespace.
    passages = StoryCorpus(
        [Passage(f"{row['chapter_number']}.{row['chunk_index']}", row['text']) for row in chunks],
        story_id='private-' + root.name, source_language='ja')
    chunk_ids = {p.passage_id: row['chunk_id'] for p, row in zip(passages, chunks)}
    if len(chunk_ids) != len(passages):
        raise ValueError('private pack contains duplicate chapter/chunk indices')
    probes = _read_probes(probes_path)
    result = {}
    versions = {}
    for retriever in retrievers if retrievers is not None else [Bm25RetrieverV0()]:
        rows = []
        for probe in probes:
            hits = retrieve(RetrievalRequest(probe['question'], probe['cutoff_chapter'], max(1, len(passages))),
                            retriever, passages)
            ranked_ids = [chunk_ids[h.passage_id] for h in hits]
            metrics = _metrics(probe, ranked_ids, hits, k_values)
            metrics['mrr@10'] = calculate_probe_metrics(probe, ranked_ids[:10], k_values=())['mrr']
            rows.append(metrics)
        result[retriever.name] = _means(rows)
        versions[retriever.name] = retriever.version
    return {'mode': 'CUTOFF_FILTERED', 'probe_count': len(probes),
            'passages_in_scope': _passage_counts(passages, probes),
            'retriever_versions': versions, 'retrievers': result}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--retriever', nargs='+', choices=RETRIEVER_NAMES, default=['bm25'])
    parser.add_argument('--private-root', type=Path, default=DEFAULT_PRIVATE_ROOT)
    parser.add_argument('--probes', type=Path, default=DEFAULT_PROBES)
    parser.add_argument('--cache-dir', type=Path)
    parser.add_argument('--k-values', type=int, nargs='+')
    parser.add_argument('--json', action='store_true')
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    try:
        depths = _depths(args.k_values) if args.k_values is not None else None
        retrievers = [make_retriever(name, cache_dir=args.cache_dir) for name in args.retriever]
        dev = evaluate_dev(args.probes, DEFAULT_MANIFEST, retrievers,
                           depths if depths is not None else (1, 5, 10))
        summary = {'dev': {'probe_count': dev['probe_count'],
                          'passages_in_scope': dev['passages_in_scope'], 'retrievers': {
            name: {key: value for key, value in values.items() if key != 'per_probe'}
            for name, values in dev['retrievers'].items()}},
            'private': evaluate_private(args.private_root, retrievers,
                                       depths if depths is not None else (1, 3, 5, 10, 20))}
        if args.json:
            write_stdout(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            for section, values in summary.items():
                if values:
                    values = {key: value for key, value in values.items() if key != 'passages_in_scope'}
                write_stdout(f'{section}: ' + (json.dumps(values, ensure_ascii=False) if values else 'not run'))
        return 0
    except (ValueError, OSError, RuntimeError, ImportError, yaml.YAMLError, IngestionError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
