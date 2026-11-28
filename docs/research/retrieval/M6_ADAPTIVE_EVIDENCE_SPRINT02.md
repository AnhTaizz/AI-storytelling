# M6 Adaptive Evidence Retrieval & Completeness Estimation (Sprint 02)

Status: **Accepted best DEV retrieval candidate (`C3`, `opt-in`; production defaults unchanged)**
Base commit: `da462cfcc64ebbe349c01eb012e340ea410831ef` (PR #55, parent `origin/main` `790902a`)

## 1. Problem & Architectural Critique

Phase 2 (`DEC-021`) and Sprint 01 (`H2_brief_hybrid_rrf_lex`) established that Story Brief retrieval bridges cross-lingual (`vi` ↔ `ja`) vocabulary gaps on summarized events, reaching `26/30` Full Evidence Success on DEV v1 under `DEPTH = 10, TOKEN_CAP = 400`. An end-to-end audit of all 30 DEV v1 probes exposed four structural flaws in independent top-$k$ and naive RRF fusion:

1. **Zero candidate-generation misses, 100% selection/routing misses:** Every gold passage across all 30 DEV v1 probes already ranks in top `1–9` of at least one local channel (`Brief BM25/Dense` or `Source BM25/Dense`). Contextual re-chunking is unnecessary for these failures.
2. **Asymmetric cross-lingual source blindness (`v1_vi_03`, `v1_vi_11`):** `20%` (`6/30`) of DEV v1 probes require source details omitted by lossy chapter briefs (`DEC-021`). `H2` queried `e5-large` only on Brief items while relying on lexical `passage_bm25` for raw Japanese source (`0` hits on Vietnamese queries), leaving cached source passage embeddings unused despite already paying for the query embedding.
3. **2× RRF overlap inflation (`v1_ja_08`, `v1_ja_10`):** Standard `rrf_fuse_passages([brief_hybrid, passage_bm25])` sums `1/(60+r)` across redundant channels. Passages present in `Brief ∩ Source` receive ~2× score, crowding out novel `Source \ Brief` passages at BM25 rank `#8` (explaining why `H2` recovered 5 Brief-covered probes over `A0` while losing `v1_ja_08` and `v1_ja_10`).
4. **Vector namespace collision & BM25 future-IDF leakage:**
   - Passing a bare `list[Passage]` in `retrieve_briefs` set `DenseE5RetrieverV0._story_id = "unscoped"` and overwrote shared passage vectors with brief item refs.
   - Indexing chapters `1..5` once in `Bm25RetrieverV0` while filtering `allowed_ids <= cutoff` leaked future-chapter IDF/`avgdl` statistics (`0` post-cutoff passages returned, but `H2` drops from `26/30` to `25/30` on `v1_ja_14` when BM25 is strictly indexed on `1..cutoff`).

## 2. Method & Contracts (`tools/story_retrieval/adaptive_evidence_v1.py`)

`AdaptiveEvidenceEngineV1` (`C3`) is deterministic, strictly causal (`chapters <= cutoff_chapter` for both BM25 IDF and dense candidate pools, verified invariant when future chapters are appended), uses **zero external LLM calls**, and shares **1 query embedding** by default across Brief Dense and Source Dense:

1. **Story-scoped pre-indexing (`brief_retrieval_v1.py` + `AdaptiveEvidenceEngineV1`):** Brief corpora index under `f"{story_id}__brief_{language}"` without mutating passage vector state.
2. **Concave complementary set selection (`select_complementary_evidence`):**
   - Channel rank utility uses concave confirmation `u(p) = max_c rrf_c(p) + eps * sum_{c != best} rrf_c(p)` (`eps = 0.08`), preserving rank-1/top-3 novel `Source \ Brief` passages alongside Brief anchors.
   - Greedy knapsack packing maximizes marginal gain (`base_u + alpha * new_query_term_coverage + co_citation_bonus - contradiction_safe_redundancy`) subject to `token_cap` and `max_passages`, evaluating exact tokenization lazily in descending-gain order.
3. **Exact vs. Estimated Token Budget Modes:**
   - **`TOKEN_BUDGET_EXACT` (`"exact_tokenizer"`):** Active whenever a model `token_counter` is supplied (e.g. `make_exact_e5_token_counter` using pinned `intfloat/multilingual-e5-large` SentencePiece `add_special_tokens=False` over `render_delivery_context`). All Sprint 01/02 paired benchmark results use `exact_tokenizer` (`C3` mean `334.3`, max `399 <= 400`).
   - **`TOKEN_BUDGET_ESTIMATED` (`"utf8_heuristic_estimate"`):** Fallback `(utf8_bytes + 2) // 3` used only when no model tokenizer is installed (e.g. lightweight CI/lexical runs). On the 30 DEV v1 Japanese contexts, UTF-8 3-byte CJK encoding causes the heuristic to overestimate true E5 subword counts by **`1.457×` on average (`1.326× – 1.581×`, mean `488.6` estimated vs `334.3` exact)** — making it conservative (safe against overflow, ~31% under-packed), never a substitute for `exact_tokenizer` in paired benchmarks.
4. **Advisory-Only Completeness Signals (`assess_evidence_completeness`):**
   - Emits `CompletenessReport(advisory_only=True)` with `COMPLETE_CANDIDATE`, `PARTIAL`, `CONFLICTING_OR_HEDGED`, or `ABSTAIN` (`NO_RELIABLE_EVIDENCE_ABOVE_FLOOR`, `DECLARED_UNKNOWN_IN_BRIEF`, `AMBIGUOUS_HOMONYM_ENTITY`, `UNANCHORED_DIALOGUE_PASSAGE`, `NON_FACTUAL_EPISTEMIC_ONLY`, `MIXED_RUMOR_AND_EXPLICIT_EVIDENCE`, `POTENTIAL_CONTRADICTORY_CLAIMS`, `NON_MONOTONIC_FLASHBACK_CHRONOLOGY`, `UNCOVERED_QUERY_FACETS`).
   - **No hard abstention:** `AdaptiveEvidenceEngineV1.search` never clears or truncates `passage_ids` based on completeness flags. Multi-facet queries check each facet independently so a high dense score on one facet never masks an ungrounded second facet.

## 3. Reproducible Benchmark & Pareto Analysis (`DEPTH = 10`, `TOKEN_CAP = 400`)

Committed single-command runner (uses only tracked repo code and public fixtures):
```powershell
python -m tools.story_retrieval.evaluate_adaptive_v1 --with-e5 --cache-dir <cache_dir> --out <json_path>
```

| Arm | Success | Recall | Hit | MRR | `ja` | `vi` | Exact Mean / Max Tok | Warm `p50 / p95` (ms) | Enc/Q | Spoilers | vs `H2_s01` | vs `H2_causal` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `A0` (Phase 2 lexical) | 23/30 (76.7%) | 0.7833 | 24/30 | 0.6708 | 11/15 | 12/15 | 342.8 / 389 | 71.9 / 153.0 | 0 | 0 | +2 / -5 | +2 / -4 |
| `P_e5_large` (Source dense) | 18/30 (60.0%) | 0.6833 | 23/30 | 0.5403 | 10/15 | 8/15 | 339.9 / 389 | 779.8 / 1223.0 | 1 | 0 | +1 / -9 | +1 / -8 |
| `H1` (Brief hybrid only) | 23/30 (76.7%) | 0.8333 | 27/30 | 0.7056 | 10/15 | 13/15 | **316.6** / 388 | 813.0 / 1263.4 | 1 | 0 | +0 / -3 | +1 / -3 |
| `H2_s01_bm25` (Sprint 01) | 26/30 (86.7%) | 0.9167 | 29/30 | 0.6834 | 13/15 | 13/15 | 327.9 / 400 | 818.7 / 1280.1 | 1 | 0 | baseline | +1 / -0 |
| `H2_causal_bm25` (strict IDF) | 25/30 (83.3%) | 0.8833 | 28/30 | 0.6704 | 12/15 | 13/15 | 327.8 / 400 | 820.3 / 1286.0 | 1 | 0 | +0 / -1 | baseline |
| `C1_symmetric_rrf` (rejected) | 25/30 (83.3%) | 0.8833 | 28/30 | 0.7439 | 12/15 | 13/15 | 339.8 / 397 | 858.7 / 1320.8 | 1 | 0 | +1 / -2 | +2 / -2 |
| `C2_complementary_quota` (rejected) | 26/30 (86.7%) | 0.9167 | 29/30 | 0.7153 | 11/15 | **15/15** | 332.2 / 391 | 864.1 / 1318.1 | 1 | 0 | +2 / -2 | +3 / -2 |
| **`C3_adaptive_submodular`** | **28/30 (93.3%)** | **0.9667** | **30/30** | **0.7184** | **13/15** | **15/15** | **334.3 / 399** | **757.3 / 1204.4** | **1** | **0** | **+2 / -0** | **+3 / -0** |

### Pareto Dominance Clarification
- **Under the hard 400-token ceiling (`Quality ↑, Warm Latency ↓, Query Encodes ↓`, s.t. `tokens <= 400`):** Only `{A0, C3_adaptive_submodular}` are non-dominated (`C3` beats `H2` on Success, Recall, Hit, MRR, probe regressions `+2/-0`, and warm `p50` latency `757.3` vs `818.7 ms`).
- **Including `Mean Context Tokens ↓` as a minimized objective:** **`C3` does NOT strictly Pareto-dominate `H1` or `H2`**, because knapsack packing utilizes remaining sub-400-token slack (`334.30` mean tokens vs `327.87` for `H2_s01_bm25` and `316.57` for `H1`, i.e. **`+6.43` mean tokens / `+2.0%`** vs `H2`). Over all four axes, the non-dominated set is `{A0, H1, H2_s01_bm25, H2_causal_bm25, C3_adaptive_submodular}` (while `P_e5_large`, `C1`, and `C2` remain strictly dominated). At a tighter cap (`TOKEN_CAP = 200`), `C3` achieves `25/30` (`0.883` Recall) at `196.4` mean tokens — matching `H2_causal_bm25` at `400` cap (`327.8` mean tokens) with `40%` fewer tokens.

## 4. Open Items & Boundaries

1. **DEV-only empirical scope:** Sprint 02 ends at `28/30` without further tuning toward `30/30`. Generalization beyond `otonari_no_tenshi` chapters 1–5 requires a future locked validation pass on an unseen permitted corpus (without touching M9 or sealed holdouts).
2. **Advisory flag precision on natural LN prose:** `assess_evidence_completeness` catches `2/2` incomplete DEV v1 probes (`0` false-complete misses) but flags `21/28` complete probes as `PARTIAL` or `CONFLICTING_OR_HEDGED` due to flat RRF tail scores, Japanese quotative `と`, and lower-rank standalone quotes. Flags must remain advisory until calibrated.
