"""Retrieve source passages within an inclusive chapter cutoff."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tools.story_ingestion.light_novel_adapter_v0 import IngestionError
from tools.story_pipeline.source import parse_range
from tools.story_retrieval.retrieval_v0 import (
    RetrievalRequest, build_corpus, make_retriever, result_to_dict, retrieve,
)

REPO = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = REPO / 'data/sample/otonari_no_tenshi/wn_jp/LIGHT_NOVEL_SOURCE_MANIFEST_SAMPLE_V0.yaml'


def write_stdout(text: str) -> None:
    """Use UTF-8 on Windows, while also supporting redirected StringIO in callers."""
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    print(text)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cutoff', type=int, required=True)
    parser.add_argument('--query', required=True)
    parser.add_argument('--k', type=int, default=10)
    parser.add_argument('--retriever', choices=('bm25', 'dense_e5', 'hybrid'), default='bm25')
    parser.add_argument('--chapters')
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument('--source-root', type=Path)
    parser.add_argument('--json', action='store_true')
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    try:
        request = RetrievalRequest(args.query, args.cutoff, args.k,
                                   parse_range(args.chapters) if args.chapters else None)
        passages = build_corpus(args.manifest, args.cutoff, args.source_root)
        retriever = make_retriever(args.retriever)
        hits = retrieve(request, retriever, passages)
        if args.json:
            write_stdout(json.dumps(result_to_dict(request, retriever, passages, hits),
                                    ensure_ascii=False))
        elif hits:
            write_stdout('\n'.join(f'{h.rank}\t{h.passage_id}\t{h.score:.6f}\t'
                                   f'{" ".join(h.text.split())[:100]}' for h in hits))
        return 0
    except (ValueError, OSError, RuntimeError, ImportError, IngestionError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
