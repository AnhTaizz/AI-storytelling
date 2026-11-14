"""Deterministic retrieval with an inclusive chapter boundary.

BM25 delegates scoring and tokenization to the frozen BM25LexicalV1.
Dense dependencies are optional and loaded only when an encoder is first needed.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from typing import AbstractSet, Protocol

from tools.story_benchmark.bm25_lexical_v1 import BM25LexicalV1
from tools.story_pipeline.source import Passage, load_scope


@dataclass(frozen=True)
class RetrievalRequest:
    query: str
    cutoff_chapter: int
    k: int = 10
    chapters: tuple[int, int] | None = None


@dataclass(frozen=True)
class Hit:
    passage_id: str
    chapter: int
    score: float
    rank: int
    text: str
    retriever: str


class Retriever(Protocol):
    name: str
    version: str

    def index(self, passages: Sequence[Passage]) -> None: ...

    def search(self, query: str, allowed_ids: AbstractSet[str],
               k: int) -> list[tuple[str, float]]: ...


def passage_chapter(passage_id: str) -> int:
    return int(passage_id.split('.', 1)[0])


def natural_key(passage_id: str) -> tuple:
    """Tagged runs avoid mixed int/string comparisons; spelling breaks numeric ties."""
    runs = tuple((0, int(run)) if run.isdecimal() else (1, run)
                 for run in re.split(r'(\d+)', passage_id) if run)
    return runs, passage_id


def _rank(scores, k: int) -> list[tuple[str, float]]:
    return sorted(((pid, float(score)) for pid, score in scores if score > 0),
                  key=lambda item: (-item[1], natural_key(item[0])))[:k]


def build_corpus(manifest_path, cutoff_chapter: int, source_root=None) -> list[Passage]:
    if cutoff_chapter < 1:
        raise ValueError('cutoff_chapter must be >= 1')
    scope = load_scope(manifest_path, (1, cutoff_chapter), source_root)
    passages = [p for c in sorted(scope.chapters, key=lambda c: c.order) for p in c.passages]
    if any(passage_chapter(p.passage_id) > cutoff_chapter for p in passages):
        raise RuntimeError('corpus contains a passage after the cutoff')
    return passages


def retrieve(request: RetrievalRequest, retriever: Retriever,
             passages: Sequence[Passage]) -> list[Hit]:
    if not request.query.strip():
        raise ValueError('query must not be empty')
    if request.k < 1 or request.cutoff_chapter < 1:
        raise ValueError('k and cutoff_chapter must be >= 1')
    start, end = request.chapters if request.chapters is not None else (1, request.cutoff_chapter)
    if not 1 <= start <= end <= request.cutoff_chapter:
        raise ValueError('chapters must satisfy 1 <= start <= end <= cutoff_chapter')
    by_id = {p.passage_id: p for p in passages}
    allowed = {pid for pid in by_id if start <= passage_chapter(pid) <= end}
    retriever.index(passages)
    scores = retriever.search(request.query, allowed, request.k)
    ranked = _rank(((pid, score) for pid, score in scores if pid in allowed), request.k)
    hits = [Hit(pid, passage_chapter(pid), score, rank, by_id[pid].text, retriever.name)
            for rank, (pid, score) in enumerate(ranked, 1)]
    if any(hit.chapter > request.cutoff_chapter for hit in hits):
        raise RuntimeError('retrieval returned a passage after the cutoff')
    return hits


def result_to_dict(request: RetrievalRequest, retriever: Retriever,
                   passages: Sequence[Passage], hits: Sequence[Hit]) -> dict:
    chapters = [passage_chapter(p.passage_id) for p in passages
                if passage_chapter(p.passage_id) <= request.cutoff_chapter]
    return {
        'schema_version': 'retrieval_result_v0',
        'request': {'query': request.query, 'cutoff_chapter': request.cutoff_chapter,
                    'k': request.k, 'chapters': list(request.chapters) if request.chapters else None},
        'retriever': {'name': retriever.name, 'version': retriever.version},
        'corpus_chapters': {'first': min(chapters) if chapters else None,
                            'last': max(chapters) if chapters else None},
        'hits': [asdict(hit) for hit in hits],
    }


class Bm25RetrieverV0:
    """BM25 k1=1.2, b=0.75, jp_simple_lexical_v1; natural-order ties."""

    name = 'bm25_v0'
    version = '0'

    def __init__(self):
        self._passages = None
        self._model = BM25LexicalV1(k1=1.2, b=0.75)

    def index(self, passages: Sequence[Passage]) -> None:
        snapshot = tuple(passages)
        if snapshot == self._passages:
            return
        model = BM25LexicalV1(k1=1.2, b=0.75)
        for passage in snapshot:
            model.add_document(passage.passage_id, passage.text)
        model.build()
        self._model, self._passages = model, snapshot

    def search(self, query: str, allowed_ids: AbstractSet[str], k: int) -> list[tuple[str, float]]:
        return _rank(self._model.score(query, set(allowed_ids)), k)


Encoder = Callable[[Sequence[str]], Sequence[Sequence[float]]]


def _default_encoder(model_name: str) -> Encoder:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name, device='cpu')
    model.eval()
    return lambda texts: model.encode(list(texts), normalize_embeddings=True,
                                      show_progress_bar=False)


def _unit(vector: Sequence[float]) -> tuple[float, ...]:
    values = tuple(float(value) for value in vector)
    if not values or not all(math.isfinite(value) for value in values):
        raise ValueError('encoder must return nonempty finite vectors')
    norm = math.sqrt(sum(value * value for value in values))
    return tuple(value / norm for value in values) if norm else values


class DenseE5RetrieverV0:
    name = 'dense_e5_small_v0'
    version = '0'

    def __init__(self, encoder: Encoder | None = None,
                 model_name: str = 'intfloat/multilingual-e5-small'):
        self.model_name = model_name
        self._encoder = encoder
        self._passages = None
        self._vectors = {}

    def _encode(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        if self._encoder is None:
            self._encoder = _default_encoder(self.model_name)
        vectors = [_unit(row) for row in self._encoder(texts)]
        if len(vectors) != len(texts) or len({len(row) for row in vectors}) > 1:
            raise ValueError('encoder returned inconsistent vector count or dimensions')
        return vectors

    def index(self, passages: Sequence[Passage]) -> None:
        snapshot = tuple(passages)
        if snapshot == self._passages:
            return
        vectors = self._encode(['passage: ' + p.text for p in snapshot]) if snapshot else []
        self._vectors = dict(zip((p.passage_id for p in snapshot), vectors))
        self._passages = snapshot

    def search(self, query: str, allowed_ids: AbstractSet[str], k: int) -> list[tuple[str, float]]:
        if not self._vectors or not allowed_ids:
            return []
        q_vector = self._encode(['query: ' + query])[0]
        if len(q_vector) != len(next(iter(self._vectors.values()))):
            raise ValueError('query and passage embedding dimensions differ')
        scores = ((pid, sum(a * b for a, b in zip(q_vector, vector)))
                  for pid, vector in self._vectors.items() if pid in allowed_ids)
        return _rank(scores, k)


class HybridRrfRetrieverV0:
    name = 'hybrid_rrf_v0'
    version = '0'

    def __init__(self, retrievers: Sequence[Retriever], rrf_k: int = 60):
        if rrf_k < 1 or not retrievers:
            raise ValueError('RRF requires components and a positive rrf_k')
        self.retrievers = tuple(retrievers)
        self.rrf_k = rrf_k
        self._passages = None

    def index(self, passages: Sequence[Passage]) -> None:
        snapshot = tuple(passages)
        if snapshot == self._passages:
            return
        for retriever in self.retrievers:
            retriever.index(snapshot)
        self._passages = snapshot

    def search(self, query: str, allowed_ids: AbstractSet[str], k: int) -> list[tuple[str, float]]:
        scores = defaultdict(float)
        for retriever in self.retrievers:
            for rank, (pid, score) in enumerate(retriever.search(query, allowed_ids, max(k, 100)), 1):
                if pid in allowed_ids and score > 0:
                    scores[pid] += 1.0 / (self.rrf_k + rank)
        return _rank(scores.items(), k)


def make_retriever(name: str) -> Retriever:
    if name == 'bm25':
        return Bm25RetrieverV0()
    if name == 'dense_e5':
        return DenseE5RetrieverV0()
    if name == 'hybrid':
        return HybridRrfRetrieverV0([Bm25RetrieverV0(), DenseE5RetrieverV0()])
    raise ValueError(f'unknown retriever: {name}')
