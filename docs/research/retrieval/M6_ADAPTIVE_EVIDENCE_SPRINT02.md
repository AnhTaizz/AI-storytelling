# M6 Adaptive Evidence Retrieval & Completeness Estimation (Sprint 02)

Status: **Research candidate (`opt-in`, DEV-evaluated; production defaults unchanged)**
Base commit: `da462cfcc64ebbe349c01eb012e340ea410831ef` (PR #55, parent `origin/main` `790902a`)

## 1. Problem & Architectural Critique

Phase 2 (`DEC-021`) and Sprint 01 (`H2_brief_hybrid_rrf_lex`) established that Story Brief retrieval bridges cross-lingual (`vi` ↔ `ja`) vocabulary gaps on summarized events, reaching `26/30` Full Evidence Success on DEV v1 under `DEPTH = 10, TOKEN_CAP = 400`. An end-to-end audit of all 30 DEV v1 probes exposed four structural flaws in independent top-$k$ and naive RRF fusion:

1. **Zero candidate-generation misses, 100% selection/routing misses:** Every gold passage across all 30 DEV v1 probes already ranks in top `1–9` of at least one local channel (`Brief BM25/Dense` or `Source BM25/Dense`). Contextual re-chunking is unnecessary for these failures.
2. **Asymmetric cross-lingual source blindness (`v1_vi_03`, `v1_vi_11`):** `20%` (`6/30`) of DEV v1 probes require source details omitted by lossy chapter briefs (`DEC-021`). `H2` queried `e5-large` only on Brief items while relying on lexical `passage_bm25` for raw Japanese source (`0` hits on Vietnamese queries), leaving cached source passage embeddings unused despite already paying for the query embedding.
3. **2× RRF overlap inflation (`v1_ja_08`, `v1_ja_10`):** Standard `rrf_fuse_passages([brief_hybrid, passage_bm25])` sums `1/(60+r)` across redundant channels. Passages present in `Brief ∩ Source` receive ~2× score, crowding out novel `Source \ Brief` passages at BM25 rank `#8` (exactly explaining why `H2` recovered 5 Brief-covered probes over `A0` while losing `v1_ja_08` and `v1_ja_10`).
4. **Silent state & causal-IDF leaks + silent incompleteness:**
   - Passing a bare `list[Passage]` in `retrieve_briefs` set `DenseE5RetrieverV0._story_id = "unscoped"` and overwrote shared passage vectors with brief item refs, while varying `cutoff_chapter` re-encoded brief items `3,034` times across a 30-probe uncached pass instead of `93` unique items.
   - Indexing chapters `1..5` once in `Bm25RetrieverV0` while filtering `allowed_ids <= cutoff` leaked future-chapter IDF/`avgdl` statistics (`0` post-cutoff passages returned, but `H2` drops from `26/30` to `25/30` on `v1_ja_14` when BM25 is strictly indexed on `1..cutoff`).
   - Top-$k$ similarity never reports whether returned passages actually cover all query facets, resolve homonyms/speaker-dropped quotes, or should abstain.

## 2. Method (`tools/story_retrieval/adaptive_evidence_v1.py`)

`AdaptiveEvidenceEngineV1` is deterministic, strictly causal (`chapters <= cutoff_chapter` for both BM25 IDF and dense candidate pools), uses **zero external LLM calls**, and shares **at most 1 query embedding** across Brief Dense and Source Dense:

1. **Story-scoped pre-indexing (`brief_retrieval_v1.py` + `AdaptiveEvidenceEngineV1`):** Brief corpora index under `f"{story_id}__brief_{language}"` without mutating passage vector state.
2. **Concave complementary set selection (`select_complementary_evidence`):**
   - Instead of additive RRF (`sum`), channel rank utility uses concave confirmation `u(p) = max_c rrf_c(p) + eps * sum_{c != best} rrf_c(p)` (`eps = 0.08`), preserving rank-1/top-3 novel `Source \ Brief` passages alongside Brief anchors.
   - Greedy knapsack packing maximizes marginal gain (`base_u + alpha * new_query_term_coverage + co_citation_bonus - contradiction_safe_redundancy`) subject to exact `token_cap` and `max_passages`, evaluating exact tokenization lazily in descending-gain order.
3. **Gold-free completeness & abstention (`assess_evidence_completeness`):**
   - Emits `COMPLETE_CANDIDATE`, `PARTIAL`, `CONFLICTING_OR_HEDGED`, or `ABSTAIN` using only runtime signals: per-passage lexical & dense floor/margin grounding (`NO_RELIABLE_EVIDENCE_ABOVE_FLOOR`), brief `unknowns` (`DECLARED_UNKNOWN_IN_BRIEF`), roster homonyms (`AMBIGUOUS_HOMONYM_ENTITY`), speakerless standalone quotes (`UNANCHORED_DIALOGUE_PASSAGE`), brief `epistemic` labels (`REPORTED`/`SPECULATION` vs `EXPLICIT`), antonym contrast (`POTENTIAL_CONTRADICTORY_CLAIMS`), flashback markers (`NON_MONOTONIC_FLASHBACK_CHRONOLOGY`), and multi-clause `UNCOVERED_QUERY_FACETS`.

## 3. Controlled DEV v1 Results (`DEPTH = 10`, `TOKEN_CAP = 400`)

Reproducible via single command:
```powershell
python .local/product-quality-sprint02/run_sprint02_benchmark.py --repo-root . --cache-dir <cache_dir> --out-dir <out_dir>
```

| Arm | Success | Recall | Hit | MRR | `ja` | `vi` | Mean / Max Tok | Warm `p50 / p95` (ms) | Enc/Q | Spoilers | vs `H2_s01` | vs `H2_causal` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `A0` (Phase 2 lexical) | 23/30 (76.7%) | 0.7833 | 24/30 | 0.6708 | 11/15 | 12/15 | 342.8 / 389 | 71.9 / 153.0 | 0 | 0 | +2 / -5 | +2 / -4 |
| `P_e5_large` (Source dense) | 18/30 (60.0%) | 0.6833 | 23/30 | 0.5403 | 10/15 | 8/15 | 339.9 / 389 | 779.8 / 1223.0 | 1 | 0 | +1 / -9 | +1 / -8 |
| `H1` (Brief hybrid only) | 23/30 (76.7%) | 0.8333 | 27/30 | 0.7056 | 10/15 | 13/15 | 316.6 / 388 | 813.0 / 1263.4 | 1 | 0 | +0 / -3 | +1 / -3 |
| `H2_s01_bm25` (Sprint 01) | 26/30 (86.7%) | 0.9167 | 29/30 | 0.6834 | 13/15 | 13/15 | 327.9 / 400 | 818.7 / 1280.1 | 1 | 0 | baseline | +1 / -0 |
| `H2_causal_bm25` (strict IDF) | 25/30 (83.3%) | 0.8833 | 28/30 | 0.6704 | 12/15 | 13/15 | 327.8 / 400 | 820.3 / 1286.0 | 1 | 0 | +0 / -1 | baseline |
| `C1_symmetric_rrf` (rejected) | 25/30 (83.3%) | 0.8833 | 28/30 | 0.7439 | 12/15 | 13/15 | 339.8 / 397 | 858.7 / 1320.8 | 1 | 0 | +1 / -2 | +2 / -2 |
| `C2_complementary_quota` (rejected) | 26/30 (86.7%) | 0.9167 | 29/30 | 0.7153 | 11/15 | **15/15** | 332.2 / 391 | 864.1 / 1318.1 | 1 | 0 | +2 / -2 | +3 / -2 |
| **`C3_adaptive_submodular`** | **28/30 (93.3%)** | **0.9667** | **30/30** | **0.7184** | **13/15** | **15/15** | **334.3 / 399** | **757.3 / 1204.4** | **1** | **0** | **+2 / -0** | **+3 / -0** |

- **Cold init (CPU weight load):** `34.65 s`; **Warm cache load (353 passages + 93 brief items):** `0.81 s`.
- **Secondary budget curves (`Success / Recall`):**
  - `200` tokens: `A0 = 20/30 (0.717)` · `H2_causal = 22/30 (0.783)` · **`C3 = 25/30 (0.883)`**
  - `400` tokens: `A0 = 23/30 (0.783)` · `H2_causal = 25/30 (0.883)` · **`C3 = 28/30 (0.967)`**
  - `800` tokens: `A0 = 26/30 (0.883)` · `H2_causal = 28/30 (0.950)` · **`C3 = 29/30 (0.983)`**
  - `1600` tokens: `A0 = 27/30 (0.917)` · `H2_causal = 28/30 (0.950)` · **`C3 = 30/30 (1.000)`**
- **Adversarial behavioral suite (`test_adaptive_evidence_v1.py` & live E5):** `11/11` scenarios pass (homonyms, anchored vs unanchored subject-dropped dialogue, multi-chapter event, partial uncovered facet, rumor-only vs rumor+explicit fact, inverted flashback chronology, contradictory witnesses, out-of-story abstention, post-cutoff spoiler trap).

## 4. Limitations & Self-Review

1. **DEV-only empirical evidence:** The 30 DEV v1 probes (`otonari_no_tenshi` chapters 1–5) have been inspected across Phase 2, Sprint 01, and Sprint 02. No unseen Brief+Source validation set exists outside sealed holdouts / locked M9. Improvements on DEV v1 screen out bad designs (`C1`, `C2`) and do **not** prove cross-series generalization.
2. **Remaining 2 partial `ja` probes at 400 tokens (`v1_ja_08`, `v1_ja_10`):** Both hit 1 of 2 gold passages (`Hit = 30/30`), missing their second non-Brief passage (`3.52` and `1.23`, both at `passage_bm25` rank `#8` and `passage_e5` rank `#39–50`). Both are recovered at `800–1600` tokens (`30/30`) and both are correctly flagged `PARTIAL` (`sufficient=False`) by `C3` at `400` tokens.
3. **Conservative completeness warnings on natural LN prose:** On DEV v1, `assess_evidence_completeness` catches `2/2` incomplete probes (`0` false-complete misses, `0` false abstentions) but marks `21/28` complete probes as `PARTIAL` or `CONFLICTING_OR_HEDGED` because RRF's flat `1/(60+r)` curve admits lower-rank `REPORTED` brief items, Japanese quotative `と` triggers clause splits, and standalone quotes at ranks `3–10` trigger `UNANCHORED_DIALOGUE_PASSAGE`. Use `status == "ABSTAIN"` for hard abstention and treat `PARTIAL` / `CONFLICTING_OR_HEDGED` as advisory planner/reviewer warnings until calibrated on an independent corpus.
