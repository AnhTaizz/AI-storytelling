# M6 Sprint 01 — Ranking & Evidence Selection Analysis (DEV v1)

Status: **DEV EXPERIMENT — default Phase 2 routes and M3 remain unchanged.**

This note analyzes the 5 cases where the pinned chapter briefs already contain a complete gold evidence set (`brief_covers_full_set = true`), yet M6 Phase 2 (`brief_then_passage`) failed to place a full gold set within the `DEPTH = 10`, `TOKEN_CAP = 400` context budget (`23/30` success, `0.7833` recall, `0` spoilers). No neighbor expansion is used.

## 1. Diagnosis of the 5 Brief-Covered Misses

Across the 7 Phase 2 baseline misses on `tests/story_retrieval/fixtures/dev_probes_v1.yaml` (30 probes, chapters 1–5):
- 2 probes (`v1_vi_04`, `v1_vi_11`) are outside brief coverage (`brief_covers_full_set = false`).
- 5 probes have full gold coverage in the briefs (`brief_covers_full_set = true`) and split into **two distinct root causes**:

| Probe | Lang | Gold | Brief items citing gold | Root cause in Phase 2 baseline |
|---|---|---|---|---|
| `v1_ja_03` | `ja` | `5.27` | `c5.CH3.F2` | `BriefLexicalRetrieverV1("vi")` uses `LatinBm25V1`; Japanese query yields **0 brief hits**. Fallback `passage_bm25` misses `5.27` in top 10. |
| `v1_ja_04` | `ja` | `1.55` | `c1.E6`, `c1.E7` | Same cross-lingual gap (**0 brief hits**); `passage_bm25` misses `1.55` in top 10. |
| `v1_ja_06` | `ja` | `3.71` / `3.75` | `c3.E8`, `c3.E9`, `c3.CH1.F3` | Same cross-lingual gap (**0 brief hits**); `passage_bm25` returns `3.70`/`3.74` instead of `3.71`/`3.75`. |
| `v1_ja_14` | `ja` | `2.63` | `c2.E4`, `c2.CH2.F3` | Same cross-lingual gap (**0 brief hits**); `passage_bm25` misses `2.63` in top 10. |
| `v1_vi_13` | `vi` | `1.15` | `c1.CH1.F3` (`['1.11', '1.15']`) | `c1.CH1.F3` **is retrieved at rank 5** (`score 4.609`), but top-4 multi-passage events (`c1.E3`, `c1.E4`, `c1.E2` with 5 passages, `c1.E1` with 4 passages) fill all 10 passage slots before rank 5 is reached. |

## 2. Minimal Opt-In Changes Tested

Added two opt-in helpers to `tools/story_retrieval/brief_retrieval_v1.py` (no change to default routes or frozen M3):
1. `BriefHybridRetrieverV1(language, dense_retriever, k_rrf=60)` — equal-weight Reciprocal Rank Fusion over lexical (`BriefLexicalRetrieverV1`) and dense (`dense_e5_large_v0`) retrieval on rendered brief items.
2. `rrf_fuse_passages(rankings, k_rrf=60, budget=...)` — deterministic equal-weight RRF over passage-ID rankings (`brief_hybrid` delivered passages + `passage_bm25` passages).

We also tested pure-lexical alternatives (round-robin evidence delivery, passage-level score aggregation, and source-quote BM25); each fixed some misses but introduced net regressions (`18/30` to `23/30` success), whereas equal-weight RRF over `BriefHybridRetrieverV1` + `passage_bm25` achieved a clear net gain without hand-tuned weights.

## 3. Paired DEV Results (`DEPTH = 10`, `TOKEN_CAP = 400`, `e5_large` tokenizer)

All arms use the same 30 DEV v1 probes (`e7af4a47b0ef02b9847ce812cff28298c4356407dcecad344e0b48827caa1a36`), the same `intfloat/multilingual-e5-large` (`3d7cfbd`) offline cache, and the same 400-token delivery cap. No API calls.

| Arm | All Success | All Recall | Mean Tokens | Max Tokens | `ja` Success | `vi` Success | Spoilers |
|---|---:|---:|---:|---:|---:|---:|---:|
| `A0_baseline_phase2` | 23/30 (77%) | 0.7833 | 342.8 | 389 | 11/15 | 12/15 | 0 |
| `H1_brief_hybrid_only` | 23/30 (77%) | 0.8333 | 316.6 | 388 | 10/15 | 13/15 | 0 |
| `H2_brief_hybrid_rrf_lex` | **26/30 (87%)** | **0.9167** | **327.9** | **400** | **13/15** | **13/15** | **0** |

* **5/5 Brief-covered misses recovered:** `v1_ja_03`, `v1_ja_04`, `v1_ja_06`, `v1_ja_14`, and `v1_vi_13`.
* **Regressions:** `H2` lost 2 `ja` probes (`v1_ja_08`, `v1_ja_10`) relative to `A0` (+5 gained, −2 lost → **+3 net**, +13.3 pp recall), and had **0 regressions on `vi`** (13/15 = 100% of Brief-covered `vi` probes).
* **Context budget:** Mean tokens decreased (`342.8 → 327.9`), `max_tokens = 400 ≤ 400`, `0` spoiler violations.

## 4. Limits and Next Decision

- Public DEV v1 covers 30 implementer-authored probes on one Japanese story (chapters 1–5); it is not a sealed cross-story benchmark.
- `BriefHybridRetrieverV1` requires a local dense encoder (`e5_large`) when used live; CI tests exercise it offline with a deterministic fake dense retriever.
- Default Phase 2 routes remain unchanged pending owner review of whether to adopt `H2` as an opt-in or default route when dense models are available.
