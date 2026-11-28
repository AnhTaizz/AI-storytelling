"""Adaptive set-aware evidence retrieval and gold-free completeness estimation (M6 Sprint 02).

Addresses two structural limitations of independent top-k and naive RRF over Story Brief + Source:
1. Asymmetric cross-lingual source blindness and 2x RRF overlap inflation (which crowds out novel
   source-only passages omitted by lossy chapter briefs).
2. Silent partial/unanswerable delivery (assuming top-k similarity hits always form complete evidence).

All components are deterministic, strictly cutoff-bounded (zero post-cutoff content or BM25 IDF leak),
require zero external LLM calls, and reuse at most one local query embedding per query when dense
retrieval is enabled. Existing v0 and Phase 2 default routes remain unchanged.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from tools.story_benchmark.bm25_lexical_v1 import jp_simple_lexical_v1
from tools.story_pipeline.source import Passage
from tools.story_retrieval.brief_retrieval_v1 import (
    BriefCorpus,
    BriefHit,
    BriefLexicalRetrieverV1,
    LatinBm25V1,
     _ref_key,
    build_brief_corpus,
    delivery,
    expand_evidence,
    retrieve_briefs,
)
from tools.story_retrieval.retrieval_v0 import (
    Bm25RetrieverV0,
    RetrievalRequest,
    StoryCorpus,
    natural_key,
    passage_chapter,
    retrieve,
)

STOP_TOKENS = frozenset({
    "là", "của", "và", "có", "không", "trong", "cho", "với", "được", "đã", "đang", "sẽ",
    "một", "các", "những", "này", "đó", "khi", "thì", "mà", "ở", "từ", "đến", "về", "ra",
    "sao", "gì", "nào", "ai", "đâu", "thế", "như", "cậu", "cô", "anh", "ấy", "mình",
    "bao", "nhiêu", "mấy", "lúc", "tại", "hãy", "biết", "nêu", "kể", "việc", "chuyện", "người",
    "the", "and", "for", "with", "from", "that", "this", "what", "who", "where", "when", "how",
    "の", "に", "は", "を", "た", "が", "で", "て", "と", "し", "れ", "さ", "ある", "いる",
    "も", "する", "から", "な", "こと", "として", "い", "や", "れる", "など", "なっ", "ない",
    "この", "ため", "その", "あっ", "よう", "また", "もの", "という", "あり", "まで", "られ",
    "なる", "へ", "か", "だ", "これ", "によって", "により", "おり", "より", "による", "ず",
    "なり", "られる", "において", "ば", "なかっ", "なく", "しかし", "について", "せ", "だっ",
    "どう", "どんな", "何", "誰", "いつ", "どこ", "教え", "まとめ", "整理", "説明", "振り返っ",
})

CONTRAST_GROUPS: Tuple[Tuple[frozenset[str], frozenset[str]], ...] = (
    (frozenset({"khóa", "đóng", "chặt", "closed", "locked"}), frozenset({"mở", "toang", "open", "unlocked"})),
    (frozenset({"trúng", "số"}), frozenset({"phẫu", "thuật", "nhập", "viện"})),
    (frozenset({"độc", "thân", "chưa"}), frozenset({"bạn", "gái", "người", "yêu"})),
)

FLASHBACK_MARKERS = (
    "trước đó", "tháng trước", "năm trước", "hồi mùa", "quá khứ", "nhớ lại",
    "以前", "数ヶ月前", "昔", "あの日",
)


@dataclass(frozen=True)
class CompletenessReport:
    status: str  # COMPLETE_CANDIDATE | PARTIAL | CONFLICTING_OR_HEDGED | ABSTAIN
    sufficient: bool
    flags: Tuple[str, ...]
    facet_coverage: float
    content_overlap: float


@dataclass(frozen=True)
class AdaptiveRetrievalResult:
    passage_ids: Tuple[str, ...]
    candidate_ids: Tuple[str, ...]
    brief_item_refs: Tuple[str, ...]
    completeness: CompletenessReport
    tokens_used: int
    query_encodes: int


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def content_tokens(text: str) -> Set[str]:
    """Extract informative lexical tokens (CJK kanji/bigrams or Latin words) without function words."""
    if any("\u3040" <= ch <= "\u9fff" for ch in text):
        raw = jp_simple_lexical_v1(text)
        return {t for t in raw if (len(t) >= 2 or ("\u4e00" <= t[0] <= "\u9fff")) and t not in STOP_TOKENS}
    words = re.findall(r"[^\W_]+", unicodedata.normalize("NFC", text).casefold())
    return {w for w in words if len(w) >= 2 and w not in STOP_TOKENS}


def split_query_facets(query: str) -> List[str]:
    """Deterministically split multi-clause questions into verifiable facets without LLM calls."""
    parts = re.split(r"\s*(?:,|;|:|\bvà\b|\bcùng\b|\bhay\b|\bnhưng\b|、|と(?=.{4,})|その後)\s*", query.strip())
    facets = [p.strip(" ?.!？。") for p in parts if len(content_tokens(p)) >= 2]
    return facets if len(facets) >= 2 else ([query.strip()] if query.strip() else [])


def has_antonym_contrast(words_a: Set[str], words_b: Set[str]) -> bool:
    """Detect opposing lexical predicates over shared topic words so contradictions are never deduplicated."""
    if len(words_a & words_b) < 2:
        return False
    return any((words_a & left and words_b & right) or (words_a & right and words_b & left)
               for left, right in CONTRAST_GROUPS)


def default_token_estimator(rows: Sequence[Tuple[str, str, None]], passages_by_id: Mapping[str, str]) -> int:
    """Fast deterministic UTF-8 token estimator when no model tokenizer is supplied."""
    if not rows:
        return 0
    rendered = "\n\n".join(f"[{pid}] {kind}\n{passages_by_id[pid]}" for pid, kind, _ in rows)
    return max(1, (len(rendered.encode("utf-8")) + 2) // 3)


def select_complementary_evidence(
    query: str,
    channels: Sequence[Sequence[str]],
    passages_by_id: Mapping[str, str],
    *,
    cutoff_chapter: int,
    max_passages: int = 10,
    token_cap: int = 400,
    token_counter: Optional[Callable[[Sequence[Tuple[str, str, None]]], int]] = None,
    passage_vectors: Optional[Mapping[str, Sequence[float]]] = None,
    co_cited_groups: Sequence[Sequence[str]] = (),
    k_rrf: int = 60,
    eps_confirm: float = 0.08,
    alpha_facet: float = 0.0015,
    beta_redundancy: float = 0.003,
) -> Tuple[List[str], int]:
    """Submodular set-aware selection under passage and token budgets.

    Uses concave max-channel rank utility (`max + eps * rest`) to prevent 2x Brief/Source
    overlap inflation, marginal query-term coverage gain for multi-facet completeness,
    contradiction-safe semantic redundancy penalty, and knapsack budget packing.
    """
    if cutoff_chapter < 1 or max_passages < 1 or token_cap < 1 or k_rrf < 1:
        raise ValueError("cutoff_chapter, max_passages, token_cap and k_rrf must be >= 1")
    counter = token_counter or (lambda rows: default_token_estimator(rows, passages_by_id))

    rank_in: Dict[str, List[int]] = defaultdict(list)
    best_rank: Dict[str, int] = {}
    for ch in channels:
        seen_ch: Set[str] = set()
        r = 0
        for pid in ch:
            if pid in seen_ch or pid not in passages_by_id:
                continue
            if passage_chapter(pid) > cutoff_chapter:
                raise ValueError(f"candidate passage {pid} exceeds cutoff_chapter {cutoff_chapter}")
            seen_ch.add(pid)
            r += 1
            rank_in[pid].append(r)
            if pid not in best_rank or r < best_rank[pid]:
                best_rank[pid] = r

    if not rank_in:
        return [], 0

    base_u: Dict[str, float] = {}
    for pid, ranks in rank_in.items():
        vals = [1.0 / (k_rrf + r) for r in ranks]
        top_v = max(vals)
        base_u[pid] = top_v + eps_confirm * (sum(vals) - top_v)

    co_cited: Dict[str, Set[str]] = defaultdict(set)
    for group in co_cited_groups[:3]:
        if 1 < len(group) <= 3:
            for a in group:
                for b in group:
                    if a != b:
                        co_cited[a].add(b)

    candidates = sorted(base_u.keys(), key=lambda p: (-base_u[p], best_rank[p], natural_key(p)))
    cand_tokens = {pid: content_tokens(passages_by_id[pid]) for pid in candidates}
    cand_order = {pid: idx for idx, pid in enumerate(candidates)}

    q_terms = content_tokens(query)
    covered_terms: Set[str] = set()
    selected_rows: List[Tuple[str, str, None]] = []
    selected_ids: Set[str] = set()
    current_tokens = 0

    while len(selected_rows) < max_passages and current_tokens + 5 <= token_cap:
        scored_step: List[Tuple[float, int, str]] = []
        for pid in candidates:
            if pid in selected_ids:
                continue

            gain = base_u[pid]
            if q_terms:
                new_terms = (cand_tokens[pid] & q_terms) - covered_terms
                gain += alpha_facet * (len(new_terms) / len(q_terms))

            if selected_ids:
                is_contradictory = any(has_antonym_contrast(cand_tokens[pid], cand_tokens[g]) for g in selected_ids)
                if any(g in co_cited.get(pid, ()) for g in selected_ids):
                    gain += 0.0005
                elif passage_vectors is not None and pid in passage_vectors and not is_contradictory:
                    vec_p = passage_vectors[pid]
                    max_sim = max(
                        (_dot(vec_p, passage_vectors[g]) for g in selected_ids if g in passage_vectors),
                        default=0.0,
                    )
                    if max_sim > 0.86:
                        gain -= beta_redundancy * (max_sim - 0.86)

            scored_step.append((-gain, cand_order[pid], pid))

        scored_step.sort()
        best_pid: Optional[str] = None
        best_exact_tokens = current_tokens
        for _, _, pid in scored_step:
            exact_tok = counter([*selected_rows, (pid, "seed", None)])
            if exact_tok <= token_cap:
                best_pid = pid
                best_exact_tokens = exact_tok
                break

        if best_pid is None:
            break
        selected_rows.append((best_pid, "seed", None))
        selected_ids.add(best_pid)
        current_tokens = best_exact_tokens
        covered_terms |= (cand_tokens[best_pid] & q_terms)

    # Final defensive spoiler and uniqueness guard
    out_ids = [r[0] for r in selected_rows]
    if any(passage_chapter(pid) > cutoff_chapter for pid in out_ids) or len(out_ids) != len(set(out_ids)):
        raise RuntimeError("selected evidence violated cutoff or uniqueness invariant")
    return out_ids, current_tokens


def assess_evidence_completeness(
    query: str,
    delivered_ids: Sequence[str],
    passages_by_id: Mapping[str, str],
    *,
    briefs_up_to_cutoff: Sequence[Mapping[str, Any]] = (),
    matched_brief_hits: Sequence[BriefHit] = (),
    max_dense_score: float = 0.0,
    dense_margin: float = 1.0,
    has_content_lexical_hit: bool = False,
    overflow_count: int = 0,
    dense_floor: float = 0.80,
) -> CompletenessReport:
    """Estimate evidence completeness, ambiguity, epistemic status, and abstention without gold."""
    q_terms = content_tokens(query)
    pid_terms = {pid: content_tokens(passages_by_id.get(pid, "")) for pid in delivered_ids}
    delivered_terms: Set[str] = set().union(*pid_terms.values()) if pid_terms else set()
    overlap = (len(q_terms & delivered_terms) / len(q_terms)) if q_terms else 0.0
    max_single_overlap = (
        max((len(q_terms & terms) / len(q_terms) for terms in pid_terms.values()), default=0.0)
        if q_terms else 0.0
    )

    dense_grounded = max_dense_score >= (dense_floor + 0.03) or (
        max_dense_score >= dense_floor and dense_margin >= 0.025
    )
    if not delivered_ids or (not has_content_lexical_hit and not dense_grounded and max_single_overlap < 0.25):
        return CompletenessReport(
            status="ABSTAIN",
            sufficient=False,
            flags=("NO_RELIABLE_EVIDENCE_ABOVE_FLOOR",),
            facet_coverage=0.0,
            content_overlap=round(overlap, 3),
        )

    flags: List[str] = []
    unknown_matched = False
    for b in briefs_up_to_cutoff:
        ch_ord = b.get("chapter_order", "?")
        for unk in b.get("unknowns") or ():
            unk_terms = content_tokens(unk)
            if unk_terms and len(q_terms & unk_terms) / max(1, min(len(q_terms), len(unk_terms))) >= 0.5:
                flags.append(f"DECLARED_UNKNOWN_IN_BRIEF:{ch_ord}")
                unknown_matched = True

    # Homonym / shared-alias entity ambiguity across eligible roster
    alias_map: Dict[str, Set[str]] = defaultdict(set)
    canonical_names: Set[str] = set()
    for b in briefs_up_to_cutoff:
        for ch in b.get("characters") or ():
            cname = ch.get("romanized_name") or ch.get("name") or ""
            if not cname:
                continue
            canonical_names.add(cname)
            for tok in re.findall(r"[^\W_]+", cname.casefold()):
                if len(tok) >= 3:
                    alias_map[tok].add(cname)
            for alias in ch.get("aliases") or ():
                if alias:
                    alias_map[alias.casefold()].add(cname)

    q_low = unicodedata.normalize("NFC", query).casefold()
    for tok, owners in sorted(alias_map.items()):
        if len(owners) > 1 and re.search(rf"(?<!\w){re.escape(tok)}(?!\w)", q_low):
            if not any(owner.casefold() in q_low for owner in owners):
                flags.append(f"AMBIGUOUS_HOMONYM_ENTITY:{tok}->{sorted(owners)}")

    # Unanchored standalone quote check
    quote_prefixes = ('"', "“", "「", "『")
    delivered_set = set(delivered_ids)
    brief_cited_pids = {p for h in matched_brief_hits for p, _ in h.evidence}
    char_tokens = {c.split()[-1].casefold() for c in canonical_names if c.split()}
    for pid in delivered_ids:
        txt = passages_by_id.get(pid, "").strip()
        if txt.startswith(quote_prefixes) and "." in pid and pid not in brief_cited_pids:
            ch_s, ord_s = pid.split(".", 1)
            if ch_s.isdigit() and ord_s.isdigit():
                ch_n, ord_n = int(ch_s), int(ord_s)
                if not any(ct in txt.casefold() for ct in char_tokens):
                    neighbors = [f"{ch_n}.{ord_n - 1}", f"{ch_n}.{ord_n + 1}"]
                    anchored_by_neighbor = any(
                        nb in delivered_set and any(ct in passages_by_id.get(nb, "").casefold() for ct in char_tokens)
                        for nb in neighbors
                    )
                    if not anchored_by_neighbor:
                        flags.append(f"UNANCHORED_DIALOGUE_PASSAGE:{pid}")

    # Epistemic check scoped strictly to query-relevant brief hits whose evidence was delivered
    relevant_hits: List[BriefHit] = []
    top_bhit_score = matched_brief_hits[0].score if matched_brief_hits else 0.0
    for h in matched_brief_hits:
        ev_pids = {p for p, _ in h.evidence}
        if not (ev_pids & delivered_set):
            continue
        item_terms = content_tokens(h.item.text)
        if (q_terms & item_terms) or (top_bhit_score > 0 and h.score >= 0.85 * top_bhit_score):
            relevant_hits.append(h)

    epistemics = {h.item.epistemic for h in relevant_hits}
    if epistemics and epistemics <= {"REPORTED", "SPECULATION", "APPEARANCE", "FIGURATIVE"}:
        flags.append(f"NON_FACTUAL_EPISTEMIC_ONLY:{sorted(epistemics)}")
    elif "REPORTED" in epistemics and "EXPLICIT" in epistemics:
        flags.append("MIXED_RUMOR_AND_EXPLICIT_EVIDENCE")

    # Contradictory claims across query-relevant delivered passages
    same_script_query = bool(q_terms & delivered_terms)
    cand_contra = [p for p in delivered_ids if (q_terms & pid_terms[p])] if same_script_query else list(delivered_ids[:4])
    for i, p1 in enumerate(cand_contra):
        for p2 in cand_contra[i + 1:]:
            if has_antonym_contrast(pid_terms[p1], pid_terms[p2]):
                flags.append(f"POTENTIAL_CONTRADICTORY_CLAIMS:{p1}_vs_{p2}")

    # Non-monotonic flashback chronology marker in multi-chapter results
    chapters = sorted({passage_chapter(p) for p in delivered_ids})
    if len(chapters) >= 2:
        max_ch = max(chapters)
        for pid in delivered_ids:
            if passage_chapter(pid) == max_ch:
                low_txt = passages_by_id.get(pid, "").casefold()
                if any(m in low_txt for m in FLASHBACK_MARKERS):
                    flags.append(f"NON_MONOTONIC_FLASHBACK_CHRONOLOGY:{pid}")

    # Facet coverage
    facets = split_query_facets(query)
    covered_f = 0
    uncovered_f = 0
    same_script_query = bool(q_terms & delivered_terms)
    for f in facets:
        ft = content_tokens(f)
        if not ft:
            covered_f += 1
            continue
        if same_script_query:
            best_f = max((len(ft & pid_terms[p]) / len(ft) for p in delivered_ids), default=0.0)
            if best_f >= 0.34:
                covered_f += 1
            else:
                uncovered_f += 1
        else:
            # Cross-lingual query: rely on brief lexical match or dense floor per facet
            b_terms = set().union(*(content_tokens(h.item.text) for h in relevant_hits)) if relevant_hits else set()
            if (ft & b_terms) and len(ft & b_terms) / len(ft) >= 0.34:
                covered_f += 1
            elif max_dense_score >= dense_floor and not unknown_matched:
                covered_f += 1
            else:
                uncovered_f += 1

    facet_cov = (covered_f / len(facets)) if facets else 0.0
    if uncovered_f > 0:
        flags.append(f"UNCOVERED_QUERY_FACETS:{uncovered_f}/{len(facets)}")
    if overflow_count > 0:
        flags.append(f"BUDGET_OVERFLOW_DROPPED:{overflow_count}")

    if unknown_matched and len(facets) <= 1 and overlap < 0.6:
        status, sufficient = "ABSTAIN", False
    elif (
        unknown_matched
        or uncovered_f > 0
        or any(f.startswith(("AMBIGUOUS_HOMONYM_ENTITY", "UNANCHORED_DIALOGUE_PASSAGE")) for f in flags)
    ):
        status, sufficient = "PARTIAL", False
    elif any(f.startswith(("POTENTIAL_CONTRADICTORY", "NON_FACTUAL_EPISTEMIC_ONLY", "MIXED_RUMOR")) for f in flags):
        status, sufficient = "CONFLICTING_OR_HEDGED", False
    else:
        status, sufficient = "COMPLETE_CANDIDATE", True

    return CompletenessReport(
        status=status,
        sufficient=sufficient,
        flags=tuple(flags),
        facet_coverage=round(facet_cov, 3),
        content_overlap=round(overlap, 3),
    )


class AdaptiveEvidenceEngineV1:
    """Cutoff-safe, story-isolated orchestrator sharing one query encoding across Brief + Source."""

    def __init__(
        self,
        story_corpus: StoryCorpus,
        briefs: Sequence[Mapping[str, Any]],
        *,
        brief_language: str = "vi",
        dense_retriever: Any = None,
        token_counter: Optional[Callable[[Sequence[Tuple[str, str, None]]], int]] = None,
        dense_floor: float = 0.80,
    ):
        self.story_id = story_corpus.story_id
        self.source_language = story_corpus.source_language
        self.brief_language = brief_language
        self._all_passages = tuple(story_corpus)
        self._passages_by_id = {p.passage_id: p.text for p in self._all_passages}
        self._max_chapter = max((passage_chapter(p.passage_id) for p in self._all_passages), default=1)
        self._briefs_by_ch = {int(b["chapter_order"]): dict(b) for b in briefs}
        self._token_counter = token_counter
        self._dense = dense_retriever
        self._dense_floor = dense_floor
        self._last_query_vec: Tuple[float, ...] = ()

        # Pre-index dense passage & brief vectors once (content-isolated per story, zero cross-chapter leak)
        self._passage_vecs: Dict[str, Tuple[float, ...]] = {}
        self._brief_vecs: Dict[str, Tuple[float, ...]] = {}
        if self._dense is not None:
            self._dense.index(story_corpus)
            self._passage_vecs = dict(self._dense._vectors)
            max_brief_ch = max(self._briefs_by_ch.keys(), default=0)
            if max_brief_ch >= 1:
                full_bc = build_brief_corpus(self.story_id, briefs, self._all_passages, max_brief_ch, brief_language)
                brief_sc = StoryCorpus(
                    [Passage(it.ref, it.text) for it in full_bc.items],
                    story_id=f"{self.story_id}__brief_{brief_language}",
                    source_language=brief_language,
                )
                self._dense.index(brief_sc)
                self._brief_vecs = dict(self._dense._vectors)
                # Restore passage identity on shared dense retriever so external callers never see mutated state
                self._dense.index(story_corpus)

    def search(
        self,
        query: str,
        *,
        cutoff_chapter: int,
        max_passages: int = 10,
        token_cap: int = 400,
        pool_depth: int = 30,
        abstain_on_insufficient: bool = False,
    ) -> AdaptiveRetrievalResult:
        if not query or not query.strip():
            raise ValueError("query must not be empty")
        if cutoff_chapter < 1:
            raise ValueError("cutoff_chapter must be >= 1")

        elig_passages = [p for p in self._all_passages if passage_chapter(p.passage_id) <= cutoff_chapter]
        elig_by_id = {p.passage_id: p.text for p in elig_passages}
        elig_briefs = [b for ch, b in sorted(self._briefs_by_ch.items()) if ch <= cutoff_chapter]

        # 1. Strictly cutoff-scoped Source Lexical BM25 (supports CJK & Latin source scripts)
        if self.source_language in ("ja", "ko", "zh"):
            sc_cut = StoryCorpus(elig_passages, story_id=self.story_id, source_language=self.source_language)
            bm = Bm25RetrieverV0()
            bm.index(sc_cut)
            s_lex_ids = [h.passage_id for h in retrieve(RetrievalRequest(query, cutoff_chapter, pool_depth), bm, sc_cut)]
        else:
            lat_bm = LatinBm25V1(k1=1.2, b=0.75)
            for p in elig_passages:
                lat_bm.add_document(p.passage_id, p.text)
            lat_bm.build()
            scored = [(pid, float(s)) for pid, s in lat_bm.score(query, set(elig_by_id)) if s > 0]
            scored.sort(key=lambda x: (-x[1], natural_key(x[0])))
            s_lex_ids = [pid for pid, _ in scored[:pool_depth]]

        # 2. Strictly cutoff-scoped Brief Corpus & Lexical BM25
        has_complete_briefs = len(elig_briefs) == cutoff_chapter and all(
            (i + 1) in self._briefs_by_ch for i in range(cutoff_chapter)
        )
        bc: Optional[BriefCorpus] = None
        bhits_lex: List[BriefHit] = []
        if has_complete_briefs and elig_passages:
            bc = build_brief_corpus(self.story_id, elig_briefs, elig_passages, cutoff_chapter, self.brief_language)
            bhits_lex = retrieve_briefs(query, bc, k=pool_depth)

        # 3. Single shared query embedding for both Source Dense and Brief Dense
        query_encodes = 0
        s_dense_ids: List[str] = []
        max_dense_score = 0.0
        dense_margin = 1.0
        bhits_final: List[BriefHit] = bhits_lex

        if self._dense is not None and elig_passages:
            q_vec = self._dense._encode(["query: " + query])[0]
            self._last_query_vec = q_vec
            query_encodes = 1

            p_scored = [(pid, _dot(q_vec, self._passage_vecs[pid])) for pid in elig_by_id if pid in self._passage_vecs]
            p_scored = [(pid, s) for pid, s in p_scored if s > 0]
            p_scored.sort(key=lambda x: (-x[1], natural_key(x[0])))
            if p_scored:
                max_dense_score = p_scored[0][1]
                med_p = p_scored[len(p_scored) // 2][1]
                dense_margin = max_dense_score - med_p
                p_cut = min(self._dense_floor, max_dense_score - 0.05)
                s_dense_ids = [pid for pid, s in p_scored if s >= p_cut][:pool_depth]

            if bc is not None:
                b_dense_scored = [
                    (it.ref, _dot(q_vec, self._brief_vecs[it.ref]))
                    for it in bc.items if it.ref in self._brief_vecs
                ]
                b_dense_scored = [(ref, s) for ref, s in b_dense_scored if s > 0]
                b_dense_scored.sort(key=lambda x: (-x[1], _ref_key(x[0])))
                b_dense_kept = b_dense_scored
                if b_dense_scored:
                    top_b = b_dense_scored[0][1]
                    med_b = b_dense_scored[len(b_dense_scored) // 2][1]
                    b_margin = top_b - med_b
                    if top_b > max_dense_score:
                        max_dense_score = top_b
                    if b_margin > dense_margin:
                        dense_margin = b_margin
                    b_cut = min(self._dense_floor, top_b - 0.05)
                    b_dense_kept = [(ref, s) for ref, s in b_dense_scored if s >= b_cut]

                # Equal-weight RRF over Brief Lexical + Brief Dense items
                rrf_b: Dict[str, float] = {}
                for r, h in enumerate(bhits_lex, start=1):
                    rrf_b[h.item.ref] = rrf_b.get(h.item.ref, 0.0) + 1.0 / (60 + r)
                for r, (ref, _) in enumerate(b_dense_kept[:pool_depth], start=1):
                    rrf_b[ref] = rrf_b.get(ref, 0.0) + 1.0 / (60 + r)
                by_ref = {it.ref: it for it in bc.items}
                ordered_refs = sorted(rrf_b.items(), key=lambda x: (-x[1], _ref_key(x[0])))[:pool_depth]
                bhits_final = [
                    BriefHit(by_ref[ref], sc, rank, "brief_hybrid_shared_v1", expand_evidence(by_ref[ref], bc))
                    for rank, (ref, sc) in enumerate(ordered_refs, start=1)
                ]

        b_deliv = delivery(bhits_final, pool_depth) if bhits_final else {"passage_ids": [], "overflow": [], "items": []}
        b_ids = b_deliv["passage_ids"]
        co_groups = [tuple(p for p, _ in h.evidence) for h in bhits_final]

        # Check genuine content-token lexical hit (require >=25% query term support, ignoring single-word accidents)
        q_terms = content_tokens(query)
        min_lex_shared = 1 if len(q_terms) <= 3 else max(2, (len(q_terms) + 3) // 4)
        has_content_lex = False
        if q_terms:
            for pid in s_lex_ids[:5]:
                if len(q_terms & content_tokens(elig_by_id[pid])) >= min_lex_shared:
                    has_content_lex = True
                    break
            if not has_content_lex:
                for h in bhits_lex[:5]:
                    if len(q_terms & content_tokens(h.item.text)) >= min_lex_shared:
                        has_content_lex = True
                        break

        selected_ids, used_tokens = select_complementary_evidence(
            query,
            [b_ids, s_lex_ids, s_dense_ids],
            elig_by_id,
            cutoff_chapter=cutoff_chapter,
            max_passages=max_passages,
            token_cap=token_cap,
            token_counter=self._token_counter,
            passage_vectors=self._passage_vecs if self._passage_vecs else None,
            co_cited_groups=co_groups,
        )

        comp = assess_evidence_completeness(
            query,
            selected_ids,
            elig_by_id,
            briefs_up_to_cutoff=elig_briefs,
            matched_brief_hits=bhits_final,
            max_dense_score=max_dense_score,
            dense_margin=dense_margin,
            has_content_lexical_hit=has_content_lex,
            overflow_count=len(b_deliv["overflow"]),
            dense_floor=self._dense_floor,
        )

        final_ids = () if (abstain_on_insufficient and comp.status == "ABSTAIN") else tuple(selected_ids)
        final_tokens = 0 if not final_ids else used_tokens
        return AdaptiveRetrievalResult(
            passage_ids=final_ids,
            candidate_ids=tuple(selected_ids),
            brief_item_refs=tuple(h.item.ref for h in bhits_final[:max_passages]),
            completeness=comp,
            tokens_used=final_tokens,
            query_encodes=query_encodes,
        )
