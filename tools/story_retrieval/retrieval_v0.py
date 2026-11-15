"""Deterministic retrieval with an inclusive chapter boundary.

BM25 delegates scoring and tokenization to the frozen BM25LexicalV1.
Dense dependencies are optional and loaded only when an encoder is first needed.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import AbstractSet, Protocol

from tools.story_benchmark.bm25_lexical_v1 import BM25LexicalV1
from tools.story_pipeline.source import Passage, load_scope
from tools.story_retrieval.cjk_lexical_v1 import CjkBm25V1

E5_SMALL_MODEL = 'intfloat/multilingual-e5-small'
E5_SMALL_REVISION = '614241f622f53c4eeff9890bdc4f31cfecc418b3'
E5_LARGE_MODEL = 'intfloat/multilingual-e5-large'
E5_LARGE_REVISION = '3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3'
RETRIEVER_NAMES = ('bm25', 'dense_e5', 'dense_e5_large', 'hybrid', 'hybrid_large')


@dataclass(frozen=True)
class RetrievalRequest:
    query: str
    cutoff_chapter: int
    k: int = 10
    chapters: tuple[int, int] | None = None
    story_id: str | None = None


def validate_story_id(story_id: str) -> str:
    """Portable single directory component; also reject Windows device names."""
    if (not isinstance(story_id, str)
            or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', story_id)
            or story_id.endswith('.') or '..' in story_id
            or story_id.split('.')[0].upper() in
            {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(10)),
             *(f'LPT{i}' for i in range(10))}):
        raise ValueError('story_id must be a safe single path component')
    return story_id


class StoryCorpus(list):
    """List-compatible passages retaining the manifest identity and language.

    Legacy bare sequences belong to the explicit `unscoped` Japanese namespace.
    Multi-story callers must retain StoryCorpus rather than flattening metadata.
    """

    def __init__(self, passages=(), *, story_id: str, source_language: str):
        super().__init__(passages)
        self.story_id = validate_story_id(story_id)
        self.source_language = source_language


def _corpus_identity(passages):
    return (validate_story_id(getattr(passages, 'story_id', 'unscoped')),
            getattr(passages, 'source_language', 'ja'), tuple(passages))


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


def build_corpus(manifest_path, cutoff_chapter: int, source_root=None) -> StoryCorpus:
    if cutoff_chapter < 1:
        raise ValueError('cutoff_chapter must be >= 1')
    scope = load_scope(manifest_path, (1, cutoff_chapter), source_root)
    passages = [p for c in sorted(scope.chapters, key=lambda c: c.order) for p in c.passages]
    if any(passage_chapter(p.passage_id) > cutoff_chapter for p in passages):
        raise RuntimeError('corpus contains a passage after the cutoff')
    return StoryCorpus(passages, story_id=scope.story_id, source_language=scope.source_language)


def retrieve(request: RetrievalRequest, retriever: Retriever,
             passages: Sequence[Passage]) -> list[Hit]:
    story_id, _, _ = _corpus_identity(passages)
    if request.story_id is not None and validate_story_id(request.story_id) != story_id:
        raise ValueError('request story_id does not match corpus story_id')
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
        self._identity = None
        self._model = BM25LexicalV1(k1=1.2, b=0.75)

    def index(self, passages: Sequence[Passage]) -> None:
        identity = _corpus_identity(passages)
        story_id, language, snapshot = identity
        if identity == self._identity:
            return
        if language not in ('ja', 'ko', 'zh'):
            raise ValueError(f'BM25 does not support source_language={language!r}; expected ja, ko or zh')
        model = (BM25LexicalV1 if language == 'ja' else CjkBm25V1)(k1=1.2, b=0.75)
        for passage in snapshot:
            model.add_document(passage.passage_id, passage.text)
        model.build()
        self._model, self._passages = model, snapshot
        self._identity = identity

    def search(self, query: str, allowed_ids: AbstractSet[str], k: int) -> list[tuple[str, float]]:
        return _rank(self._model.score(query, set(allowed_ids)), k)


Encoder = Callable[[Sequence[str]], Sequence[Sequence[float]]]


def _default_encoder(model_name: str, revision: str, batch_size: int) -> Encoder:
    import torch
    from sentence_transformers import SentenceTransformer

    torch.manual_seed(42)
    torch.use_deterministic_algorithms(True, warn_only=True)
    model = SentenceTransformer(model_name, revision=revision, device='cpu')
    model.max_seq_length = 512
    model.eval()
    return lambda texts: model.encode(list(texts), normalize_embeddings=True,
                                      batch_size=batch_size, show_progress_bar=False)


def _unit(vector: Sequence[float]) -> tuple[float, ...]:
    values = tuple(float(value) for value in vector)
    if not values or not all(math.isfinite(value) for value in values):
        raise ValueError('encoder must return nonempty finite vectors')
    norm = math.sqrt(sum(value * value for value in values))
    return tuple(value / norm for value in values) if norm else values


class DenseE5RetrieverV0:
    """Pinned E5; unknown model IDs require a revision and use dense_e5_custom_v0.

    Optional JSON caching preserves post-_unit Python floats without renormalizing.
    """

    def __init__(self, encoder: Encoder | None = None,
                 model_name: str = E5_SMALL_MODEL, revision: str | None = None,
                 batch_size: int = 32, cache_dir: Path | str | None = None):
        models = {E5_SMALL_MODEL: ('dense_e5_small_v0', E5_SMALL_REVISION),
                  E5_LARGE_MODEL: ('dense_e5_large_v0', E5_LARGE_REVISION)}
        self.name, default_revision = models.get(model_name, ('dense_e5_custom_v0', None))
        self.revision = revision if revision is not None else default_revision
        if not self.revision or batch_size < 1:
            raise ValueError('a model revision and positive batch_size are required')
        self.version = '0+' + self.revision[:7]
        self.model_name = model_name
        self.batch_size = batch_size
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self._encoder = encoder
        self._passages = None
        self._identity = None
        self._story_id = 'unscoped'
        self._vectors = {}

    def _encode(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        if self._encoder is None:
            self._encoder = _default_encoder(self.model_name, self.revision, self.batch_size)
        vectors = [_unit(row) for row in self._encoder(texts)]
        if len(vectors) != len(texts) or len({len(row) for row in vectors}) > 1:
            raise ValueError('encoder returned inconsistent vector count or dimensions')
        return vectors

    def _cache_path(self) -> Path:
        identity = json.dumps([self.model_name, self.revision], ensure_ascii=True)
        return self.cache_dir / self._story_id / (hashlib.sha256(identity.encode('utf-8')).hexdigest() + '.json')

    def _load_cache(self) -> dict[str, tuple[float, ...]]:
        try:
            data = json.loads(self._cache_path().read_text(encoding='utf-8'))
            if not isinstance(data, dict) or not isinstance(data.get('vectors'), dict):
                raise ValueError('invalid embedding cache')
            dimension = data.get('dimension')
            if not isinstance(dimension, int) or dimension < 1:
                raise ValueError('invalid cache dimension')
            vectors = {}
            for key, row in data['vectors'].items():
                if not re.fullmatch(r'[0-9a-f]{64}', key) or not isinstance(row, list):
                    raise ValueError('invalid cache entry')
                vector = tuple(float(value) for value in row)
                if len(vector) != dimension or not all(math.isfinite(v) for v in vector):
                    raise ValueError('inconsistent cache dimensions or values')
                norm = math.sqrt(sum(v * v for v in vector))
                if norm and abs(norm - 1.0) > 1e-6:
                    raise ValueError('cache vector must be unit length or zero')
                vectors[key] = vector
            return vectors
        except (OSError, ValueError, TypeError, OverflowError):
            return {}

    def _save_cache(self, vectors: dict[str, tuple[float, ...]]) -> None:
        path = self._cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Same-directory replacement never exposes a partially written JSON file.
        stream = tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                            dir=path.parent, delete=False)
        temporary = Path(stream.name)
        try:
            with stream:
                json.dump({'dimension': len(next(iter(vectors.values()))), 'vectors': vectors},
                          stream, allow_nan=False)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _passage_vectors(self, texts: Sequence[str], rebuild: bool = False) -> list[tuple[float, ...]]:
        if self.cache_dir is None:
            return self._encode(texts) if texts else []
        cached = {} if rebuild else self._load_cache()
        keys = [hashlib.sha256(text.encode('utf-8')).hexdigest() for text in texts]
        missing = dict((key, text) for key, text in zip(keys, texts) if key not in cached)
        if missing:
            encoded = self._encode(list(missing.values()))
            if cached and len(next(iter(cached.values()))) != len(encoded[0]):
                # The encoder's dimension changed: discard every old vector.
                return self._passage_vectors(texts, rebuild=True)
            cached.update(zip(missing, encoded))
            self._save_cache(cached)
        return [cached[key] for key in keys]

    def index(self, passages: Sequence[Passage]) -> None:
        identity = _corpus_identity(passages)
        story_id, _, snapshot = identity
        if identity == self._identity:
            return
        self._story_id = story_id
        self._identity = None
        self._vectors = {}
        vectors = self._passage_vectors(['passage: ' + p.text for p in snapshot])
        self._vectors = dict(zip((p.passage_id for p in snapshot), vectors))
        self._passages = snapshot
        self._identity = identity

    def search(self, query: str, allowed_ids: AbstractSet[str], k: int) -> list[tuple[str, float]]:
        if not self._vectors or not allowed_ids:
            return []
        q_vector = self._encode(['query: ' + query])[0]
        if self.cache_dir is not None and len(q_vector) != len(next(iter(self._vectors.values()))):
            vectors = self._passage_vectors(['passage: ' + p.text for p in self._passages], rebuild=True)
            self._vectors = dict(zip((p.passage_id for p in self._passages), vectors))
        if len(q_vector) != len(next(iter(self._vectors.values()))):
            raise ValueError('query and passage embedding dimensions differ')
        scores = ((pid, sum(a * b for a, b in zip(q_vector, vector)))
                  for pid, vector in self._vectors.items() if pid in allowed_ids)
        return _rank(scores, k)


class HybridRrfRetrieverV0:
    name = 'hybrid_rrf_v0'
    version = '0'

    def __init__(self, retrievers: Sequence[Retriever], rrf_k: int = 60,
                 name: str = 'hybrid_rrf_v0'):
        if rrf_k < 1 or not retrievers:
            raise ValueError('RRF requires components and a positive rrf_k')
        self.retrievers = tuple(retrievers)
        self.name = name
        self.version = '0[' + ','.join(f'{r.name}:{r.version}' for r in retrievers) + ']'
        self.rrf_k = rrf_k
        self._passages = None
        self._identity = None

    def index(self, passages: Sequence[Passage]) -> None:
        identity = _corpus_identity(passages)
        if identity == self._identity:
            return
        # A component failure must force the next attempt to re-index every component.
        self._passages = None
        self._identity = None
        for retriever in self.retrievers:
            retriever.index(passages)
        self._passages = identity[2]
        self._identity = identity

    def search(self, query: str, allowed_ids: AbstractSet[str], k: int) -> list[tuple[str, float]]:
        scores = defaultdict(float)
        for retriever in self.retrievers:
            for rank, (pid, score) in enumerate(retriever.search(query, allowed_ids, max(k, 100)), 1):
                if pid in allowed_ids and score > 0:
                    scores[pid] += 1.0 / (self.rrf_k + rank)
        return _rank(scores.items(), k)


def make_retriever(name: str, cache_dir: Path | str | None = None) -> Retriever:
    if name == 'bm25':
        return Bm25RetrieverV0()
    if name not in RETRIEVER_NAMES:
        raise ValueError(f'unknown retriever: {name}')
    large = name in ('dense_e5_large', 'hybrid_large')
    dense = (DenseE5RetrieverV0(model_name=E5_LARGE_MODEL, batch_size=4, cache_dir=cache_dir)
             if large else DenseE5RetrieverV0(cache_dir=cache_dir))
    if name in ('dense_e5', 'dense_e5_large'):
        return dense
    return HybridRrfRetrieverV0([Bm25RetrieverV0(), dense],
                               name='hybrid_rrf_large_v0' if large else 'hybrid_rrf_v0')
