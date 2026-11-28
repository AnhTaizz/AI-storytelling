"""M6 Phase 2: retrieval over Story Brief items, with complete source-evidence expansion.

Decided in DEC-021 (from M6_PHASE2_BRIEF_RETRIEVAL_PROPOSAL_V0.md). Briefs are written in the
brief language (Vietnamese for this channel), so a Vietnamese question can be matched against
Vietnamese brief text even when the source is Japanese, and every hit carries the source
passages its item cites, so the writer always receives the evidence, never only a paraphrase.

- Items: every event (`c3.E2`), character fact (`c3.CH1.F2`) and relationship (`c3.R1`) of
  every chapter brief up to the cutoff. Refs are synthetic and bound to one brief snapshot
  (`stamps`: chapter -> sha256 of the brief's canonical JSON); regeneration may renumber them.
- Spoiler safety: briefs after the cutoff are dropped before anything is rendered or indexed;
  every item's evidence must resolve to a passage of its own chapter, so no item can carry a
  later passage; results and expansions are checked against the request cutoff again.
- Rendering (`brief_render_v1`) keeps the brief's own words, names of the item's own chapter
  and its epistemic label; nothing is translated, merged from later chapters or inferred.
- Ranking: lexical BM25 by brief language (no model download needed), or any retriever with
  the v0 `index`/`search` protocol (for example the dense e5 retrievers).
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import AbstractSet, Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from tools.story_benchmark.bm25_lexical_v1 import BM25LexicalV1
from tools.story_pipeline.source import Passage
from tools.story_retrieval.cjk_lexical_v1 import CjkBm25V1
from tools.story_retrieval.retrieval_v0 import StoryCorpus, natural_key, passage_chapter

RENDERER = "brief_render_v1"
KINDS = ("event", "fact", "relationship")
_REF = re.compile(r"^c(\d+)\.(E\d+|CH\d+\.F\d+|R\d+)$")


@dataclass(frozen=True)
class BriefItem:
    ref: str
    kind: str
    chapter: int
    text: str
    evidence: Tuple[str, ...]
    epistemic: str
    importance: Optional[str] = None
    quote: str = ""
    summary: str = ""   # the brief's own sentence (event summary, fact text, relationship state)


@dataclass(frozen=True)
class BriefCorpus:
    story_id: str
    cutoff_chapter: int
    language: str
    items: Tuple[BriefItem, ...]
    passages: Mapping[str, str]
    stamps: Tuple[Tuple[int, str], ...]
    renderer: str = RENDERER

    @property
    def snapshot(self) -> str:
        """Identity of everything a result depends on (story, cutoff, briefs, renderer)."""
        digest = hashlib.sha256(json.dumps([self.story_id, self.cutoff_chapter, self.language, self.renderer,
                                            list(self.stamps)]).encode("utf-8"))
        return digest.hexdigest()


@dataclass(frozen=True)
class BriefHit:
    item: BriefItem
    score: float
    rank: int
    retriever: str
    evidence: Tuple[Tuple[str, str], ...] = field(default=())  # (passage id, source text), complete


def brief_sha256(brief: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(brief, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def render_items(brief: Mapping[str, Any]) -> List[BriefItem]:
    """The retrievable items of one chapter brief, in brief order."""
    n = int(brief["chapter_order"])
    names = {c["id"]: c["romanized_name"] for c in brief["characters"]}
    items: List[BriefItem] = []
    for event in brief["events"]:
        who = ", ".join(names.get(p, p) for p in event.get("participants", []))
        parts = [event["summary"]]
        if who:
            parts.append(f"Nhân vật: {who}")
        if event.get("location"):
            parts.append(f"Địa điểm: {event['location']}")
        motivation = event.get("motivation") or {}
        if motivation.get("text"):
            parts.append(f"Động cơ ({motivation.get('status', '?')}): {motivation['text']}")
        if event.get("consequence"):
            parts.append(f"Hệ quả: {event['consequence']}")
        items.append(BriefItem(f"c{n}.{event['id']}", "event", n, ". ".join(parts), tuple(event["evidence"]),
                               event["epistemic"], event["importance"], event.get("quote", ""), event["summary"]))
    for character in brief["characters"]:
        label = " / ".join(dict.fromkeys([character["romanized_name"], character["name"], *character["aliases"]]))
        for index, fact in enumerate(character["facts"], start=1):
            items.append(BriefItem(f"c{n}.{character['id']}.F{index}", "fact", n, f"{label}: {fact['text']}",
                                   tuple(fact["evidence"]), fact["epistemic"], None, fact.get("quote", ""),
                                   fact["text"]))
    for index, relation in enumerate(brief["relationships"], start=1):
        pair = " – ".join(names.get(c, c) for c in relation["between"])
        items.append(BriefItem(f"c{n}.R{index}", "relationship", n, f"{pair}: {relation['state']}",
                               tuple(relation["evidence"]), relation["epistemic"], None, relation.get("quote", ""),
                               relation["state"]))
    return items


def build_brief_corpus(story_id: str, briefs: Iterable[Mapping[str, Any]], passages: Iterable[Passage],
                       cutoff_chapter: int, language: str) -> BriefCorpus:
    """Validate and render the briefs of chapters 1..cutoff (later ones are ignored).

    A missing chapter, an item without evidence, or evidence outside its own chapter rejects
    the whole corpus: an item is never trimmed to make it eligible."""
    if cutoff_chapter < 1:
        raise ValueError("cutoff_chapter must be >= 1")
    eligible = {int(b["chapter_order"]): b for b in briefs if int(b["chapter_order"]) <= cutoff_chapter}
    missing = [n for n in range(1, cutoff_chapter + 1) if n not in eligible]
    if missing:
        raise ValueError(f"no brief for chapters {missing}; generate them before retrieval")
    texts = {p.passage_id: p.text for p in passages if passage_chapter(p.passage_id) <= cutoff_chapter}
    items: List[BriefItem] = []
    for n in sorted(eligible):
        for item in render_items(eligible[n]):
            if not item.evidence:
                raise ValueError(f"{item.ref}: no evidence")
            for pid in item.evidence:
                if pid not in texts:
                    raise ValueError(f"{item.ref}: evidence {pid} is not a passage up to chapter {cutoff_chapter}")
                if passage_chapter(pid) != item.chapter:
                    raise ValueError(f"{item.ref}: evidence {pid} is outside chapter {item.chapter}")
            items.append(item)
    refs = [i.ref for i in items]
    if len(refs) != len(set(refs)):
        raise ValueError("duplicate item refs")
    stamps = tuple((n, brief_sha256(eligible[n])) for n in sorted(eligible))
    return BriefCorpus(story_id, cutoff_chapter, language, tuple(items), texts, stamps)


# --------------------------------------------------------------------------- lexical ranking

def latin_words_bigrams_v1(text: str) -> List[str]:
    """Words and adjacent word pairs. Vietnamese is written in syllables, so a pair such as
    "hàng xóm" is the unit of meaning that a single syllable is not."""
    words = re.findall(r"[^\W_]+", unicodedata.normalize("NFC", text).casefold())
    return words + [f"{a}_{b}" for a, b in zip(words, words[1:])]


class LatinBm25V1(BM25LexicalV1):
    """The frozen BM25 scorer over latin_words_bigrams_v1 tokens (hex-encoded, as CjkBm25V1)."""

    @staticmethod
    def _render(text: str) -> str:
        return " ".join("t" + token.encode("utf-8").hex() for token in latin_words_bigrams_v1(text))

    def add_document(self, doc_id, text):
        super().add_document(doc_id, self._render(text))

    def score(self, query, allowed_doc_ids=None):
        return super().score(self._render(query), allowed_doc_ids)


class BriefLexicalRetrieverV1:
    """BM25 over rendered brief items, tokenized for the brief language."""

    version = "1"

    def __init__(self, language: str):
        self.language = language
        self.name = "brief_bm25_v1"
        self._model: Optional[BM25LexicalV1] = None
        self._identity: Optional[Tuple[str, ...]] = None

    def _new_model(self) -> BM25LexicalV1:
        if self.language == "ja":
            return BM25LexicalV1(k1=1.2, b=0.75)
        if self.language in ("ko", "zh"):
            return CjkBm25V1(k1=1.2, b=0.75)
        return LatinBm25V1(k1=1.2, b=0.75)

    def index(self, passages: Sequence[Passage]) -> None:
        identity = tuple(f"{p.passage_id}\0{p.text}" for p in passages)
        if identity == self._identity:
            return
        model = self._new_model()
        for passage in passages:
            model.add_document(passage.passage_id, passage.text)
        model.build()
        self._model, self._identity = model, identity

    def search(self, query: str, allowed_ids: AbstractSet[str], k: int) -> List[Tuple[str, float]]:
        assert self._model is not None, "index() first"
        scores = [(ref, float(s)) for ref, s in self._model.score(query, set(allowed_ids)) if s > 0]
        return sorted(scores, key=lambda x: (-x[1], _ref_key(x[0])))[:k]


def _ref_key(ref: str) -> Tuple:
    return tuple(int(part) if part.isdigit() else part for part in re.findall(r"\d+|\D+", ref))


class BriefHybridRetrieverV1:
    """Equal-weight RRF over lexical and dense retrieval on rendered brief items.

    When a cross-lingual query yields no lexical matches on the brief language, the dense
    component supplies the ranking cleanly without changing the `retrieve_briefs` contract.
    """

    version = "1"

    def __init__(self, language: str, dense_retriever: Any, *, k_rrf: int = 60):
        if k_rrf < 1:
            raise ValueError("k_rrf must be >= 1")
        self.language = language
        self.lexical = BriefLexicalRetrieverV1(language)
        self.dense = dense_retriever
        self.k_rrf = k_rrf
        self.name = f"brief_hybrid_rrf_v1({self.lexical.name}+{dense_retriever.name})"

    def index(self, passages: Sequence[Passage]) -> None:
        self.lexical.index(passages)
        self.dense.index(passages)

    def search(self, query: str, allowed_ids: AbstractSet[str], k: int) -> List[Tuple[str, float]]:
        depth = max(k, 30)
        scores: Dict[str, float] = {}
        for component in (self.lexical, self.dense):
            for rank, (ref, score) in enumerate(component.search(query, allowed_ids, depth), start=1):
                if ref in allowed_ids and score > 0:
                    scores[ref] = scores.get(ref, 0.0) + 1.0 / (self.k_rrf + rank)
        return sorted(scores.items(), key=lambda x: (-x[1], _ref_key(x[0])))[:k]


def rrf_fuse_passages(rankings: Sequence[Sequence[str]], *, k_rrf: int = 60,
                      budget: Optional[int] = None) -> List[str]:
    """Deterministic equal-weight Reciprocal Rank Fusion over passage-ID rankings."""
    if k_rrf < 1:
        raise ValueError("k_rrf must be >= 1")
    if budget is not None and budget < 0:
        raise ValueError("budget must be >= 0")
    scores: Dict[str, float] = {}
    best_rank: Dict[str, int] = {}
    for ranking in rankings:
        seen: set[str] = set()
        rank = 0
        for pid in ranking:
            if pid in seen:
                continue
            seen.add(pid)
            rank += 1
            scores[pid] = scores.get(pid, 0.0) + 1.0 / (k_rrf + rank)
            if pid not in best_rank or rank < best_rank[pid]:
                best_rank[pid] = rank
    ordered = [pid for pid, _ in sorted(scores.items(), key=lambda x: (-x[1], best_rank[x[0]], natural_key(x[0])))]
    return ordered[:budget] if budget is not None else ordered


# --------------------------------------------------------------------------- requests

def expand_evidence(item: BriefItem, corpus: BriefCorpus) -> Tuple[Tuple[str, str], ...]:
    """Every passage the item cites, in passage order (never truncated)."""
    missing = [pid for pid in item.evidence if pid not in corpus.passages]
    if missing:
        raise ValueError(f"{item.ref}: evidence {missing} not in the corpus")
    return tuple((pid, corpus.passages[pid]) for pid in sorted(set(item.evidence), key=natural_key))


def retrieve_briefs(query: str, corpus: BriefCorpus, *, cutoff_chapter: Optional[int] = None, k: int = 10,
                    kinds: Sequence[str] = KINDS, chapters: Optional[Tuple[int, int]] = None,
                    retriever: Any = None) -> List[BriefHit]:
    """The k brief items most relevant to `query`, each with its complete source evidence.
    `chapters` restricts the chapters items were observed in; it must end by the cutoff."""
    cutoff = corpus.cutoff_chapter if cutoff_chapter is None else cutoff_chapter
    if not query.strip():
        raise ValueError("query must not be empty")
    if k < 1 or cutoff < 1:
        raise ValueError("k and cutoff_chapter must be >= 1")
    if cutoff > corpus.cutoff_chapter:
        raise ValueError(f"cutoff {cutoff} is after the corpus cutoff {corpus.cutoff_chapter}")
    unknown = set(kinds) - set(KINDS)
    if unknown or not kinds:
        raise ValueError(f"kinds must be a non-empty subset of {KINDS}")
    start, end = chapters if chapters is not None else (1, cutoff)
    if not 1 <= start <= end <= cutoff:
        raise ValueError("chapters must satisfy 1 <= start <= end <= cutoff_chapter")
    retriever = retriever or BriefLexicalRetrieverV1(corpus.language)
    by_ref = {item.ref: item for item in corpus.items}
    allowed = {i.ref for i in corpus.items if i.kind in kinds and start <= i.chapter <= end}
    item_passages = [Passage(i.ref, i.text) for i in corpus.items]
    try:
        scoped_items: Sequence[Passage] = StoryCorpus(
            item_passages,
            story_id=f"{corpus.story_id}__brief_{corpus.language}",
            source_language=corpus.language,
        )
    except ValueError:
        scoped_items = item_passages
    retriever.index(scoped_items)
    ranked = [(ref, score) for ref, score in retriever.search(query, allowed, k) if ref in allowed and score > 0]
    ranked = sorted(ranked, key=lambda x: (-x[1], _ref_key(x[0])))[:k]
    hits = [BriefHit(by_ref[ref], score, rank, retriever.name, expand_evidence(by_ref[ref], corpus))
            for rank, (ref, score) in enumerate(ranked, start=1)]
    for hit in hits:  # independent check of every returned item and passage
        if hit.item.chapter > cutoff or any(passage_chapter(pid) > cutoff for pid, _ in hit.evidence):
            raise RuntimeError(f"{hit.item.ref}: returned content after cutoff {cutoff}")
    return hits


def delivery(hits: Sequence[BriefHit], budget: int) -> Dict[str, Any]:
    """The passages handed to a writer: evidence of the hits in rank order, deduplicated, up to
    `budget` passages. Support that does not fit is reported, never silently dropped."""
    order: List[str] = []
    for hit in hits:
        order += [pid for pid, _ in hit.evidence if pid not in order]
    return {"passage_ids": order[:budget], "overflow": order[budget:], "items": [h.item.ref for h in hits]}


def entity_evidence(corpus: BriefCorpus, names: Sequence[str]) -> Dict[str, Any]:
    """Every brief item up to the cutoff that names the entity, in chapter order, with its
    evidence. Always `partial`: briefs keep selected facts only, so a missing item is not
    proof of absence (exhaustive dossiers wait for M4 extraction, see DEC-021)."""
    keys = [unicodedata.normalize("NFC", n).casefold() for n in names if n and n.strip()]
    if not keys:
        raise ValueError("names must not be empty")
    found = []
    for item in corpus.items:
        text = unicodedata.normalize("NFC", item.text).casefold()
        if any(re.search(rf"(?<!\w){re.escape(key)}(?!\w)", text) for key in keys):
            found.append(item)
    passages: List[str] = []
    for item in found:
        passages += [pid for pid in sorted(item.evidence, key=natural_key) if pid not in passages]
    return {"status": "partial", "cutoff_chapter": corpus.cutoff_chapter, "names": list(names),
            "items": [i.ref for i in found], "passage_ids": passages}


def callback_candidates(corpus: BriefCorpus, queries: Sequence[str], *, per_query: int = 2, limit: int = 8,
                        exclude: AbstractSet[str] = frozenset(), retriever: Any = None) -> List[Dict[str, Any]]:
    """Earlier events (any importance) that the episode's events recall, for the recap.

    Each episode event is one query; the best `per_query` earlier events of each are pooled
    in query order, without `exclude` (events the recap already carries), up to `limit`."""
    retriever = retriever or BriefLexicalRetrieverV1(corpus.language)
    chosen: Dict[str, BriefHit] = {}
    for query in queries:
        if not query.strip():
            continue
        hits = retrieve_briefs(query, corpus, k=per_query + len(exclude), kinds=("event",), retriever=retriever)
        for hit in [h for h in hits if h.item.ref not in exclude][:per_query]:
            chosen.setdefault(hit.item.ref, hit)
    out = []
    for hit in list(chosen.values())[:limit]:
        out.append({"ref": hit.item.ref, "chapter": hit.item.chapter, "summary": hit.item.summary,
                    "importance": hit.item.importance, "epistemic": hit.item.epistemic,
                    "quote": hit.item.quote, "evidence": [pid for pid, _ in hit.evidence]})
    return out


def is_item_ref(ref: str) -> bool:
    return bool(_REF.match(ref))
