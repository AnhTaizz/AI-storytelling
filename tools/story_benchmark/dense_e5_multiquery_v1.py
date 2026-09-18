"""
DENSE_E5_MULTIQUERY_V1 (TASK M1-30CH-I)

Deterministic question-only query decomposition (QUESTION_FACET_DECOMP_V1) plus
Reciprocal Rank Fusion over independent dense E5 rankings. Uses the unchanged
DENSE_E5_SMALL_V1 encoder / relevance path; only the query side changes.

See benchmarks/m1_script_quality/long_range_probe/DENSE_E5_MULTIQUERY_V1_METHOD.md
"""
import re
import unicodedata
from fractions import Fraction
from typing import Dict, List, Mapping, Sequence, Set, Tuple

import numpy as np

from tools.story_benchmark.dense_e5_small_v1 import DenseE5SmallV1, calculate_metrics

METHOD_ID = "DENSE_E5_MULTIQUERY_V1"
DECOMPOSITION_ID = "QUESTION_FACET_DECOMP_V1"

# Frozen constants — no sweeps.
K_RRF = 60
MIN_CONTENT_TOKENS = 2
MAX_QUERIES_PER_PROBE = 8
MIN_DECOMPOSED_PROBES_FOR_EVALUATION = 3
HIT10_MAJOR_COLLAPSE_DELTA = -0.10

# Only this probe field may be read by decomposition.
ALLOWED_DECOMPOSITION_FIELDS = ("question",)
FORBIDDEN_DECOMPOSITION_FIELDS = (
    "category",
    "required_evidence_chunk_ids",
    "supporting_evidence_chunk_ids",
    "expected_answer",
    "expected_facts",
    "earliest_required_chapter",
    "latest_required_chapter",
    "chapter_span",
    "requires_multi_chunk",
    "requires_multi_chapter",
    "forbidden_future_chapters",
    "difficulty_notes",
)

# Closed-class English function words (generic, no story knowledge). Frozen.
FUNCTION_WORDS_V1 = frozenset("""
a an the this that these those
i me my mine we us our ours you your yours he him his she her hers it its they them their theirs
who whom whose which what when where why how
is am are was were be been being do does did doing done have has had having
will would shall should can could may might must
of in on at to for from by with about as into onto upon over under between among through during
before after above below up down out off than then so such
and or but nor if because while although though whether
not no yes also just only very too
there here all any each every some both either neither other another
own same s
""".split())

_WS_RE = re.compile(r"\s+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.?!])\s+")
_ENUM_SPLIT_RE = re.compile(r"[,;]")
_TOKEN_RE = re.compile(r"[^\W_]+(?:'[^\W_]+)?")
_RANGE_PATTERNS = (
    re.compile(r"^(?P<stem>.*?)\bfrom\s+(?P<a>.+?)\s+to\s+(?P<b>.+)$", re.IGNORECASE),
    re.compile(r"^(?P<stem>.*?)\bbetween\s+(?P<a>.+?)\s+and\s+(?P<b>.+)$", re.IGNORECASE),
)
_FACET_STRIP_CHARS = " .?!,;:"


class DecompositionLeakageError(RuntimeError):
    """Raised when decomposition touches a probe field other than `question`."""


# ---------------------------------------------------------------------------
# Decomposition
# ---------------------------------------------------------------------------

def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return _WS_RE.sub(" ", text).strip()


def clean_facet(text: str) -> str:
    return normalize_text(text).strip(_FACET_STRIP_CHARS)


def dedup_key(text: str) -> str:
    return clean_facet(text).casefold()


def content_token_count(text: str) -> int:
    tokens = _TOKEN_RE.findall(text.casefold())
    return sum(1 for t in tokens if t not in FUNCTION_WORDS_V1 and not t.isdigit())


def split_sentences(text: str) -> List[str]:
    return [s for s in (p.strip() for p in _SENTENCE_SPLIT_RE.split(text)) if s]


def strip_directive(text: str) -> str:
    if ":" in text:
        return text.split(":", 1)[1].strip()
    return text


def split_enumeration(text: str) -> List[str]:
    return [s for s in (p.strip() for p in _ENUM_SPLIT_RE.split(text)) if s]


def split_range(text: str) -> List[str]:
    for pattern in _RANGE_PATTERNS:
        m = pattern.match(text)
        if m:
            stem = m.group("stem").strip()
            a = m.group("a").strip()
            b = m.group("b").strip()
            if stem:
                return [f"{stem} {a}", f"{stem} {b}"]
            return [a, b]
    return [text]


def decompose_question(question: str) -> List[str]:
    """QUESTION_FACET_DECOMP_V1. Returns [Q0, facet_1, ...]; Q0 is always first."""
    if not isinstance(question, str):
        raise TypeError("question must be a string")
    q0 = normalize_text(question)
    if not q0:
        raise ValueError("question is empty after normalization")

    stage_a = split_sentences(q0)
    stage_b = [strip_directive(s) for s in stage_a]
    stage_c = [item for s in stage_b for item in split_enumeration(s)]
    stage_d = [facet for item in stage_c for facet in split_range(item)]

    candidates = (stage_a if len(stage_a) > 1 else []) + stage_b + stage_c + stage_d

    queries = [q0]
    seen = {dedup_key(q0)}
    for cand in candidates:
        if len(queries) >= MAX_QUERIES_PER_PROBE:
            break
        facet = clean_facet(cand)
        if not facet or content_token_count(facet) < MIN_CONTENT_TOKENS:
            continue
        key = facet.casefold()
        if key in seen:
            continue
        seen.add(key)
        queries.append(facet)
    return queries


def question_only_view(probe: Mapping) -> Dict[str, str]:
    """The only probe access decomposition is allowed to make."""
    return {"question": probe["question"]}


def decompose_probe(probe: Mapping) -> List[str]:
    view = question_only_view(probe)
    return decompose_question(view["question"])


def decomposition_diagnostics(query_lists: Sequence[Sequence[str]]) -> dict:
    counts = [len(q) for q in query_lists]
    n = len(counts)
    hist: Dict[int, int] = {}
    for c in counts:
        hist[c] = hist.get(c, 0) + 1
    return {
        "probe_count": n,
        "probes_with_multiple_queries": sum(1 for c in counts if c > 1),
        "probes_with_single_query_only": sum(1 for c in counts if c == 1),
        "mean_queries_per_probe": (sum(counts) / n) if n else 0.0,
        "min_queries_per_probe": min(counts) if counts else 0,
        "max_queries_per_probe": max(counts) if counts else 0,
        "queries_per_probe_histogram": {int(k): int(v) for k, v in sorted(hist.items())},
    }


# ---------------------------------------------------------------------------
# Fusion
# ---------------------------------------------------------------------------

def rrf_fuse(rankings: Sequence[Sequence[str]], k_rrf: int = K_RRF) -> List[Tuple[str, float]]:
    """Reciprocal Rank Fusion with 1-based ranks, exact rational scores,
    ordering by score DESC then chunk_id ASC."""
    scores: Dict[str, Fraction] = {}
    for ranking in rankings:
        if len(set(ranking)) != len(ranking):
            raise ValueError("ranking contains duplicate ids")
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, Fraction(0)) + Fraction(1, k_rrf + rank)
    ordered = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
    return [(doc_id, float(score)) for doc_id, score in ordered]


def eligible_doc_ids(chunk_meta: Mapping[str, int], cutoff_chapter) -> Set[str]:
    if cutoff_chapter is None:
        return set(chunk_meta)
    return {cid for cid, chap in chunk_meta.items() if chap <= cutoff_chapter}


class DenseE5MultiQueryV1(DenseE5SmallV1):
    """Frozen DENSE_E5_SMALL_V1 encoder; adds per-query ranking + RRF fusion."""

    def encode_query_independent(self, query: str) -> np.ndarray:
        # Batch of one per query: identical call path to F, so Q0 == F query embedding.
        return self.encode_queries([query])[0]

    def rank_query_embeddings(self, q_embs: Sequence[np.ndarray], allowed_doc_ids: Set[str] = None) -> List[List[Tuple[str, float]]]:
        return [self.score_embedding(q, allowed_doc_ids) for q in q_embs]

    def multiquery_rank(self, q_embs: Sequence[np.ndarray], allowed_doc_ids: Set[str] = None):
        per_query = self.rank_query_embeddings(q_embs, allowed_doc_ids)
        fused = rrf_fuse([[d for d, _ in r] for r in per_query])
        return fused, per_query


# ---------------------------------------------------------------------------
# Diagnostics & interpretation
# ---------------------------------------------------------------------------

def change_diagnostics(control_top10: Sequence[Sequence[str]], mq_top10: Sequence[Sequence[str]],
                       control_metrics: Sequence[Mapping], mq_metrics: Sequence[Mapping]) -> dict:
    assert len(control_top10) == len(mq_top10) == len(control_metrics) == len(mq_metrics)
    n = len(control_top10)
    introduced, jaccards = [], []
    changed = improved = decreased = unchanged = s01 = s10 = 0
    for c, m, cm, mm in zip(control_top10, mq_top10, control_metrics, mq_metrics):
        cs, ms = set(c[:10]), set(m[:10])
        introduced.append(len(ms - cs))
        union = cs | ms
        jaccards.append(len(cs & ms) / len(union) if union else 1.0)
        if cs != ms:
            changed += 1
        dr = mm["recall@10"] - cm["recall@10"]
        if dr > 1e-12:
            improved += 1
        elif dr < -1e-12:
            decreased += 1
        else:
            unchanged += 1
        if cm["success@10"] == 0 and mm["success@10"] == 1:
            s01 += 1
        if cm["success@10"] == 1 and mm["success@10"] == 0:
            s10 += 1
    return {
        "probe_count": n,
        "mean_unique_chunks_introduced_top10": (sum(introduced) / n) if n else 0.0,
        "mean_top10_jaccard_overlap": (sum(jaccards) / n) if n else 0.0,
        "probes_top10_changed": changed,
        "probes_recall10_improved": improved,
        "probes_recall10_decreased": decreased,
        "probes_recall10_unchanged": unchanged,
        "full_evidence_success10_0_to_1": s01,
        "full_evidence_success10_1_to_0": s10,
    }


def interpret_verdict(delta_recall10: float, delta_success10: float, delta_hit10: float,
                      probes_with_multiple_queries: int, gates_passed: bool) -> str:
    if not gates_passed or probes_with_multiple_queries < MIN_DECOMPOSED_PROBES_FOR_EVALUATION:
        return "NOT_EVALUABLE"
    eps = 1e-12
    recall_up = delta_recall10 > eps
    success_up = delta_success10 > eps
    no_collapse = delta_hit10 >= HIT10_MAJOR_COLLAPSE_DELTA - eps
    if recall_up and success_up and no_collapse:
        return "SUPPORTED"
    if recall_up or success_up:
        return "PARTIALLY_SUPPORTED"
    return "NOT_SUPPORTED"


def find_private_leaks(serialized_public: str, forbidden_strings: Sequence[str]) -> List[str]:
    return sorted({s for s in forbidden_strings if s and s in serialized_public})


__all__ = [
    "METHOD_ID", "DECOMPOSITION_ID", "K_RRF", "MIN_CONTENT_TOKENS", "MAX_QUERIES_PER_PROBE",
    "ALLOWED_DECOMPOSITION_FIELDS", "FORBIDDEN_DECOMPOSITION_FIELDS", "FUNCTION_WORDS_V1",
    "DecompositionLeakageError", "normalize_text", "clean_facet", "dedup_key",
    "content_token_count", "split_sentences", "strip_directive", "split_enumeration",
    "split_range", "decompose_question", "question_only_view", "decompose_probe",
    "decomposition_diagnostics", "rrf_fuse", "eligible_doc_ids", "DenseE5MultiQueryV1",
    "calculate_metrics", "change_diagnostics", "interpret_verdict", "find_private_leaks",
]
