# Project State

## Current Milestone

M2 — Canonical Story Model capability: COMPLETE / FROZEN (Canonical Story Model v0: FROZEN / ACCEPTED, DEC-016).

M1 research: CLOSED. M1 Formal Script Quality Contract: CANDIDATE PENDING ORCHESTRATOR REVIEW (`SCRIPT_QUALITY_CONTRACT/v0`; not frozen).

Project transition to M3: PENDING closure of the outstanding M1 Formal Script Quality Contract, unless the roadmap dependency is explicitly amended by a future decision. M3 has not started.

## Milestone Lifecycle

- M0 — Product Foundation: CLOSED.
- M1 — Script Quality & Narrative Contract:
  - Empirical / research program: CLOSED for the current scope.
  - Formal Script Quality Contract: CANDIDATE PENDING ORCHESTRATOR REVIEW (`SCRIPT_QUALITY_CONTRACT/v0`, not frozen). The M1 capability gate is therefore not yet complete.
- M2 — Canonical Story Model: capability COMPLETE / FROZEN (DEC-016). The expected capability has been established as `canonical_story/v0` + `predicate_registry/v0.1`. M2 ran under the roadmap's evidence-driven overlap semantics (see ROADMAP Execution Semantics, DEC-015).
- M3: NOT STARTED. Transition is pending closure of the M1 Formal Script Quality Contract, unless a future decision amends that roadmap dependency. The roadmap is unchanged.

*Correction (M2-02): an earlier version of this section labelled M1 "COMPLETED / CLOSED FOR CURRENT RESEARCH SCOPE". That overstated completion while the formal Script Quality Contract remains open. The M1 research program is closed; the contract is not.*

## M1 Closure Note

The M1 research program closed its current scope on 2026-09-30 (Task Q commit `8c6ff438e5bfafaebf9cbc4c249485ba0f2d1116`). The formal Script Quality Contract remains open.

- **Completed work:**
  - 30-chapter corpus research.
  - Script-side hypotheses H1, H2, H6 and H6b (partially supported or supported, as recorded below).
  - Development retrieval experiments E–O.
  - Creation, Product Owner sign-off, and freeze of the independent validation fixture V1.
  - Task Q, executed once.
- **Task Q primary endpoint:** Full Evidence Success@10 was M 11 / 16 and O 11 / 16. O showed exploratory Recall@10 and MRR improvements but no primary-endpoint improvement. The outcome is not covered by the pre-registered descriptive classes.
- **Claims not made:** M1 does not show that O generalizes better than M, nor that M and O are equivalent (N = 16, limited power).
- **Protocol closed:** the K/M/O protocol is closed for frozen fixture V1, and no post-hoc tuning on that fixture is permitted.
- **Not produced:** M1 did not freeze a formal Script Quality Contract. That item remains an open decision below; M1 contributed evidence for it.
- **Next:** lessons carried into M2 are recorded in `docs/research/m2/M2_CANONICAL_STORY_MODEL_REQUIREMENTS.md`.

## M1 History (status notes recorded during M1)

M0 Product Foundation complete.
M1 ready for planning.
M1 execution uses evidence-driven vertical iteration.
M1 empirical benchmark fixture established.
Application implementation has not started.

Golden Story v0 selected: Otonari no Tenshi-sama Japanese Web Novel Chapter 1.
Tracked sample corpus available for Chapters 1–5.
RUN_0001_BASELINE_A executed using Chapter 1 only.
First real Vietnamese storytelling script produced.
Project Owner human review pending.
RUN_0001 Baseline A received preliminary Orchestrator failure analysis.
Baseline showed generally adequate event comprehension but weak creator-oriented narrative transformation.
Human / Project Owner qualitative review remains pending.
No advanced retrieval/memory architecture is justified by this single-chapter run.

H1 stronger narrative instructions formally evaluated.
Prompt V2 improved narrative transformation, pacing, and spoken style, while factual/interpretive drift and output-language corruption remained.
H1 verdict: PARTIALLY_SUPPORTED.
Project Owner A/B preference remains pending.

H2 Separate Story Brief experiment executed as RUN_0003.
RUN_0003 introduces a minimal factual Story Brief between source understanding and narrative generation.
H2 verdict: PARTIALLY_SUPPORTED. Story Brief showed factual utility, but Writer adherence remains a problem.
Project Owner preference pending.

H6 Factual Script Critic formally evaluated.
H6 verdict: PARTIALLY_SUPPORTED.
Critic detected genuine Writer deviations but coverage remained incomplete.
Critic-guided revision achieved the recorded output length of 1074 words from 1648 and corrected
some flagged drift, while some unsupported or stronger-than-Brief claims remained.
Project Owner preference remains pending.

## M0 — Verified Completed

- Repository foundation created and published.
- Product Vision reviewed and accepted.
- MVP Scope reviewed and accepted.
- Architectural Principles reviewed and accepted.
- High-Level Roadmap reviewed and accepted.
- Initial Decisions reviewed and accepted.
- M0 cross-document consistency audit passed.

## M0 Closure

Status: CLOSED

Foundation closure commit: dabc3f94e4e5dd028ef2f54d2ffe3a7d3f568f4d

## Implementation Status

Application implementation has not started.

Not yet implemented:
- Canonical Story Model
- Light Novel ingestion
- Story Extraction
- Persistent Story Memory implementation
- Retrieval implementation
- Story Brief generation
- Narrative Planning
- Script Generation
- Validation pipeline
- Temporal / Graph Story Memory
- Manga ingestion
- Production automation

## Open Decisions

- Script Quality Contract
- Canonical Story Model
- Narrative Profile / behavior specification
- Persistence architecture
- Graph representation and persistence technology
- Embedding strategy
- Retrieval implementation
- LLM selection per pipeline stage
- Model Router / orchestration strategy
- Evaluation benchmark details
- Human-vs-automation workflow policy

## Current Quality Gate

M0 Foundation Gate: PASSED

Script Quality Gate: NOT YET EVALUATED

RUN_0007 executed the first real deterministic full-coverage H6b semantic Critic attempt using Gemini 3.1 Pro High in a fresh Antigravity conversation.
32 deterministic review units expected.
mechanical coverage PASS.
raw YAML parse PASS.
schema conformance FAIL (violations preserved).

## Hypothesis Status

- H6b (Claim-Level Factual Critic vs Baseline Critic): SUPPORTED — on the frozen RUN3 controlled instance,
deterministic claim-level auditing substantially improved useful detection
coverage over Critic V1, but remained incomplete (11/33 robust issues detected).

## Current Task

30-chapter corpus identity: FROZEN
Corpus fingerprint: 7f9bb8106d6d50acd2b3760738c0b8040f36ab547c2d2f7eade1ca0b9a827ff8

Local passage contract: OTONARI_LOCAL_PASSAGE_V1 / PARAGRAPH_PACK_V1
Execution: PASS

LONG_RANGE_PROBE_V1: FROZEN
- 15 probes
- 5 categories (3 each)
- Benchmark SHA-256: 24ca1f9c92531a19f59d409c7d3e68ef90b91ab24aab6d7854f0c52667c136e2
- Validator: PASS
- Freeze integrity: PASS

M1-30CH-E — BM25_LEXICAL_V1: EXECUTED
- Baseline Identity: JP_SIMPLE_LEXICAL_V1 Tokenizer, pure deterministic BM25
- CUTOFF_FILTERED overall metrics: Hit@10 = 20%, MRR = 0.133
- GLOBAL_DIAGNOSTIC overall metrics: Identical to Cutoff Filtered
- Zero positive-score candidates for 8/15 probes.
- Lexical retrieval heavily limited on raw Japanese prose without semantic understanding or morphological analyzers.

M1-30CH-F — DENSE_E5_SMALL_V1: EXECUTED
- Baseline Identity: `intfloat/multilingual-e5-small` via local sentence-transformers CPU inference
- CUTOFF_FILTERED overall metrics: Hit@10 = 93.3% (+73.3%), Recall@10 = 56.6% (+47.7%), Full_Evidence_Success@10 = 20.0% (+20.0%), MRR = 0.344 (+0.211)
- GLOBAL_DIAGNOSTIC overall metrics: Hit@10 = 80.0%, Spoiler_Violation@10 = 40.0%
- Dense retrieval improves evidence retrieval significantly over lexical BM25 on LONG_RANGE_PROBE_V1.
- Dense_diagnostics note: 77/97 chunk passages exceeded the 512 token limit and required truncation, but semantic matching still largely succeeded.

M1-30CH-G — DENSE_E5_WINDOW_MAX_V1: EXECUTED (Fixed by M1-30CH-G-FIX)
- Baseline Identity: `intfloat/multilingual-e5-small` via local sentence-transformers CPU inference
- Semantic Window Contract: 448 tokens window, 64 token overlap. Exact HuggingFace snapshot frozen (`614241f...`).
- Zero truncation achieved. Passage truncation completely eliminated. Token coverage verified strictly with 0 gaps. (Diagnostics mechanically verified: 97 parents mapped to 176 windows).
- CUTOFF_FILTERED overall metrics: Hit@10 = 80.0% (-13.3%), Recall@10 = 52.2% (-4.4%), Full_Evidence_Success@10 = 20.0% (+0.0%), MRR = 0.260 (-0.084)
- GLOBAL_DIAGNOSTIC overall metrics: Hit@10 = 66.6%, Spoiler_Violation@10 = 26.6%
- Interpretation: Eliminating parent-chunk truncation through this fixed window/max-pooling representation did not improve long-range evidence recovery on the frozen benchmark. In particular, Full Evidence Success@10 remained 20%. This reduces the likelihood that original 512-token passage truncation was the primary bottleneck. The next experiment may test multi-evidence retrieval because it is now better motivated.

M1-30CH-H — DENSE_E5_MMR_V1: EXECUTED
- Baseline Identity: `intfloat/multilingual-e5-small` via local sentence-transformers CPU inference, using identical parent-chunk representation to F.
- MMR Contract: lambda = 0.70. Selected dynamically over full eligible dense candidate set.
- CUTOFF_FILTERED overall metrics: Hit@10 = 80.0% (-13.3%), Recall@10 = 53.3% (-3.3%), Full_Evidence_Success@10 = 20.0% (+0.0%), MRR = 0.289 (-0.055)
- GLOBAL_DIAGNOSTIC overall metrics: Hit@10 = 80.0%, Spoiler_Violation@10 = 33.3%
- Diversity diagnostics deltas (Control vs MMR): mean_unique_chapters_top10 = +0.066, mean_pairwise_similarity_top10 = -0.011, mean_query_relevance_top10 = -0.001
- Interpretation: Control vs MMR diagnostics mechanically demonstrate that MMR successfully increased diversity (more unique chapters, lower pairwise similarity) in the candidate pool. However, correctness metrics did not improve. Redundancy/diversity alone is unlikely to be the main remaining bottleneck. This motivates testing whether a single query under-specifies multiple evidence needs.

M1-30CH-I — DENSE_E5_MULTIQUERY_V1: EXECUTED — Verdict: NOT_SUPPORTED
- Method Identity: Frozen F encoder and parent-chunk representation (`intfloat/multilingual-e5-small` @ `614241f...`, CPU, `query: ` / `passage: `). Question-only deterministic decomposition `QUESTION_FACET_DECOMP_V1` (sentence split → directive strip → `,`/`;` enumeration split → `from…to` / `between…and` range split with stem, ≥2 content tokens, dedup, max 8 queries). Each query embedded independently and fused with Reciprocal Rank Fusion (`K_RRF = 60`, 1-based ranks, tie-break `chunk_id ASC`). No MMR, no windowing, no LLM.
- Relevance Control Gate: Q0-only cosine ranking reproduced the F cutoff-filtered ranking exactly (ordered chunk-id equality, 15/15 probes) and the F aggregate metrics. PASS.
- Decomposition: 14/15 probes produced more than one query; mean 2.8 queries per probe (min 1, max 5).
- CUTOFF_FILTERED overall metrics (Δ vs F): Hit@10 = 73.3% (-20.0%), Recall@10 = 47.8% (-8.9%), Full_Evidence_Success@10 = 20.0% (+0.0%), MRR = 0.242 (-0.103)
- GLOBAL_DIAGNOSTIC overall metrics: Hit@10 = 60.0%, Spoiler_Violation@10 = 26.7%
- Change diagnostics vs Q0-only control: Top-10 changed for 13/15 probes (mean Jaccard 0.728, mean 1.73 new chunks). Recall@10 improved for 1 probe, decreased for 4 and stayed unchanged for 10. Full Evidence Success@10 moved 0→1 for 1 probe and 1→0 for 1 probe.
- Determinism: PASS (two consecutive runs gave identical aggregates and identical decomposition, control, per-query and fused ranking hashes). Privacy: PASS.
- Interpretation: Question-only facet decomposition with RRF changed candidate discovery substantially but did not recover more required evidence. Recall, Hit and MRR all fell, and Full Evidence Success did not change. On this benchmark the evidence does not support single-query under-specification (as operationalized by surface question decomposition) as the remaining bottleneck. Together with G (truncation) and H (redundancy), three query- and selection-side interventions around the same e5-small relevance signal have now failed to raise Full Evidence Success@10 above 20%.

M1-30CH-J — MISSING_EVIDENCE_RANK_DIAGNOSTIC_V1: EXECUTED — Classification: DEEP_RELEVANCE_BOTTLENECK (fusion_bottleneck_signal = true)
- Diagnostic only; no new retrieval method. Reads the frozen F and I CUTOFF_FILTERED rankings.
- Source artifact integrity: PASS. Probe and chunk hashes match the freeze file; the F ranking and the I fused and per-query ranking hashes match their committed results; the K=10 oracle reproduces F Recall@10 and Full Evidence Success@10.
- Population: 15 probes, 35 required evidence units; F misses 15 of them in Top-10.
- F rank of the 15 missed units: 11–20: 6 (40%); 21–50: 6 (40%); >50: 3 (20%); missing: 0. Median F rank of a missed unit is 28, in a median eligible pool of 97 chunks.
- Candidate reachability (gold present in the pool, not reranker-solvable): 6/15 missed units are within Top-20 and 12/15 within Top-50. Probes with all required evidence within Top-20: 8/15; within Top-50: 12/15.
- Full Evidence Success diagnostic curve on the frozen F ranking (not a baseline): K=10: 0.20, K=20: 0.53, K=30: 0.67, K=50: 0.80. Recall at the same K: 0.57, 0.73, 0.82, 0.91.
- Multi-query best-rank finding: the best I subquery ranked 9/15 missed units higher than F, 6 the same and 0 lower. 3 missed units reached an individual subquery's Top-10, and all 3 were pushed back out of Top-10 by RRF (the fusion-bottleneck condition). No subquery lifted a unit from beyond rank 20 into Top-20.
- Interpretation: 60% of F-missed required evidence ranks beyond 20, so a small Top-20 reranker would lack access to most of it. Top-50 covers more, but on a corpus of at most 97 chunks that is about half of it. Decomposition improved individual ranks only near the boundary, and fusion discarded those gains.

M1-30CH-K — DENSE_E5_LARGE_V1: EXECUTED — Verdict: PARTIALLY_SUPPORTED
- Model identity: `intfloat/multilingual-e5-large` @ `3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3`; `model.safetensors` SHA-256 `020afdeb…1def6` and `tokenizer.json` SHA-256 `62c24cdc…75626`, both verified locally before load. Dimension 1024, CPU, fp32; sentence-transformers 6.0.1, transformers 5.17.0, torch 2.14.0+cpu. Everything else is identical to F: parent chunks, `query: ` / `passage: ` prefixes, max 512 tokens, normalized cosine, `chunk_id` tie-break. The method was frozen before scoring.
- Input gates: benchmark freeze, chunks, F detailed ranking, J population reconstruction (35 units, 15 F misses, 6/6/3/0) and model identity all PASS.
- CUTOFF_FILTERED overall metrics (Δ vs F): Hit@10 = 80.0% (-13.3%), Recall@10 = 57.8% (+1.1%), Full_Evidence_Success@10 = 26.7% (+6.7%), MRR = 0.421 (+0.076)
- GLOBAL_DIAGNOSTIC overall metrics: Hit@10 = 66.7%, Spoiler_Violation@10 = 33.3%
- J failure population (15 F misses): rank improved for 13, stayed the same for 0 and worsened for 2. F>10→K≤10: 8; F>20→K≤20: 7 of 9; F>50→K≤50: 2 of 3. Median rank went from 28 (F) to 10 (K). K ranks for these units: 1–10: 8, 11–20: 4, 21–50: 1, >50: 2, missing: 0.
- Completeness curve, Recall / Full Evidence Success (F → K): @10 0.567→0.578 / 0.20→0.27; @20 0.733→0.822 / 0.53→0.60; @30 0.822→0.911 / 0.67→0.80; @50 0.911→0.933 / 0.80→0.87.
- Truncation: queries 0 (F 0), passages 77/97 (F 77/97). The tokenizer family is the same, and the counts are identical.
- Determinism: PASS (two fresh-load runs gave identical aggregates and ranking and rank-shift hashes). Privacy: PASS.
- Interpretation: E5-large ranks J's deep evidence much higher (7 of 9 units beyond rank 20 moved into Top-20). It also raises MRR and Full Evidence Success@10. However, the Top-10 budget was reshuffled rather than enlarged. A post-hoc count from the local tables shows 8 required units entered Top-10 and 8 left, so there were 20 units in Top-10 under both models. Evidence concentrated within fewer probes, and probes with no required evidence in Top-10 rose from 1 to 3; hence Hit@10 fell below the frozen −0.10 guard. Extra encoder capacity improves the relevance signal substantially at depth 20–30, but only marginally at Top-10.

M1-30CH-L — K_RANK_TRANSITION_DIAGNOSTIC_V1: EXECUTED — Descriptive classification: ORDERING_CONSISTENT (borderline)
- Diagnostic only: reads the frozen F and K CUTOFF_FILTERED rankings, with no model and no retrieval. All integrity gates PASS (freeze, chunks, F and K ranking SHAs, 15 probes / 35 units). The analysis reproduces the committed F and K Hit/Recall/Full Evidence Success@10.
- Transitions across 35 units: stayed in Top-10 12; F Top-10 lost by K 8; K Top-10 gained 8; stayed outside Top-10 7. Required units in Top-10: F 20, K 20. Micro recall is 0.571 for both; macro Recall@10 is 0.567 → 0.578 because probes require 2 or 3 units.
- K destinations of the 8 lost units: 11–15: 4, 16–20: 1, 21–30: 3, >30: 0 (median K rank 16; 62.5% within Top-20, 100% within Top-30). F origins of the 8 gained units: 11–20: 5, 21–30: 1, 31–50: 1, >50: 1.
- Remaining deep under K: K rank > 20: 6 units (3 of them were in F Top-10); K > 30: 3; K > 50: 2.
- Probe transitions @10: hit probes 14 → 12 (gained 1, lost 3); full-success probes 3 → 4 (gained 3, lost 2).
- Candidate access under K (probes with all required evidence available / Full Evidence Success): Top-20 9/15 (0.60), Top-30 12/15 (0.80), Top-50 13/15 (0.87). This measures candidate access, not the performance of any reranker.
- Interpretation: K's Top-10 losses moved just below the output boundary, not deep: all 8 are within K Top-30. Complete evidence is available within K Top-30 for 12 of 15 probes. Only 3 of 35 units lie beyond K rank 30. The pattern is consistent with a mainly Top-10 ordering problem plus a small residual deep-relevance population. Both classification thresholds are borderline: the ordering condition holds at 62.5% against >50%, and the deep condition misses at 3/35 = 8.6% against 10%. The thresholds were set after K's result was visible, so the label is descriptive only.

M1-30CH-M — BGE_RERANKER_V2_M3_TOP30_V1: EXECUTED — Verdict: PARTIALLY_SUPPORTED
- Reranker identity: `BAAI/bge-reranker-v2-m3` @ `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`; `model.safetensors` SHA-256 `d9e3e081…5286` and `tokenizer.json` SHA-256 `69564b69…9c15`, both verified before load. `XLMRobertaForSequenceClassification` with 1 logit, CPU, fp32; transformers 5.17.0, torch 2.14.0+cpu; FlagEmbedding not used.
- Candidate contract: exactly the first 30 CUTOFF_FILTERED candidates of the verified K ranking. The candidate-set equality gate PASSED for 15/15 probes (all pools ≥ 30; 450 pairs). Pairs are `<s> question </s></s> passage </s>`, with the query capped at 256 tokens and the passage at 512, one pair per forward pass. Order is the raw logit descending, then K rank, then chunk_id. The method was frozen before scoring.
- Primary metrics (reranked vs K Top-10): Hit@10 0.800 → 0.933 (+0.133), Recall@10 0.578 → 0.644 (+0.067), Full_Evidence_Success@10 0.267 → 0.267 (+0.000), MRR 0.421 → 0.514 (+0.093). At shallower depths Full Evidence Success fell (@3: 0.133 → 0.000; @5: 0.200 → 0.067).
- Candidate ceiling: 12/15 probes have complete evidence within K Top-30, and the reranker achieved full success for 4 of them (utilization 0.33).
- Top-10 transitions across 35 units: stayed 16, lost 4, gained 6, stayed outside 9. It restored 3 of the 8 units K had pushed out of F's Top-10. Probes with a hit: 12 → 14 (gained 2, lost 0). Probes with full evidence: 4 → 4 (gained 2, lost 2).
- Truncation: queries 0/450; passages 367/450 pairs exceed 512 tokens and are truncated, recorded rather than fixed.
- Determinism: PASS (two fresh-load runs gave identical aggregates and identical ranking, transition and pair-score hashes). Privacy: PASS.
- Interpretation: Cross-encoder reranking improved Top-10 ordering at the unit and hit level. It recovered K's Hit@10 loss (back to F's 0.933), raised Recall@10 and MRR, and restored 3 of the 8 displaced units. It did not raise Full Evidence Success@10: of the 12 probes with complete evidence available, it assembled every required unit in Top-10 for only 4, and full success at @3/@5 dropped. Candidate availability (12/15) is therefore far from realized. The reranker ranks individual relevant passages higher, but it does not reliably bring all of a probe's evidence together. Most passages are truncated to 512 tokens in the pair input, which may limit what the reranker sees.

M1-30CH-N — M_FAILURE_MODE_DIAGNOSTIC_V1: EXECUTED
- Diagnostic only: existing M and K artifacts, no model inference. Gates PASS: all M detailed hashes match, and the M metrics, transition counts, candidate-complete and full-success counts and the 367/450 truncation count are reproduced.
- Population: 12 candidate-complete probes, of which 8 fail Full Evidence Success@10 after reranking. Each failure probe misses exactly one required unit, so there are 8 missing units against 12 promoted units in the same probes.
- M ranks of the missing units: 11–15: 5, 16–20: 2, 21–30: 1, >30: 0 (median M rank 13.5; median K rank 9).
- K → M movement of the missing units: 3 moved up, 0 unchanged, 5 moved down. Within these probes, 4 required units in K's Top-10 were pushed out by M, 3 were pulled in, 9 stayed in Top-10 and 4 were outside under both. 2 of the 8 failure probes were full-success under K.
- Gap to M's rank-10 score (raw logits): median 0.226, range 0.06–1.38. For the 11–15 group the median is 0.097 and the maximum 0.26.
- Truncation exposure (passage > 512 tokens): 8/8 missing units against 11/12 promoted units (base rate 367/450 pairs), so there is no clear enrichment.
- Probe labels (descriptive): NEAR_BOUNDARY_ORDERING 5, MID_POOL_ORDERING 3. All 8 are TRUNCATION_EXPOSED, as are almost all required chunks.
- Interpretation: The flat Full Evidence Success is driven by one missing unit per probe, mostly just below the Top-10 cutoff by a small score margin. The reranker often pushed down a unit K already had in its Top-10. By the frozen two-thirds rule the pattern is not near-boundary dominant (62.5%), but near-boundary ordering is the larger population. Truncation exposure is almost universal among required chunks and is not enriched in failures. The benchmark labels the evidence-bearing chunk, not the exact evidence token span, so this diagnostic can say whether a failed chunk was truncated by the M pair contract, but not whether the gold evidence itself lay in the truncated tail.

M1-30CH-O — KM_CONSENSUS_RANK_SUM_V1: EXECUTED — Verdict: PARTIALLY_SUPPORTED
- Selection rule: Deterministic equal-weight rank sum consensus over frozen Top-30 candidate pool (`rank_sum(c) = k_rank(c) + m_rank(c) ASC`). Symmetric tie-break: `max(k_rank, m_rank) ASC`, `min(k_rank, m_rank) ASC`, `chunk_id ASC`. Evaluated ranking appends unchanged K tail beyond 30. Pure selector with zero gold inputs.
- Source artifact integrity: PASS (benchmark freeze, probes, chunks, K ranking, and M reranked ranking SHA-256 verified; K and M control metrics reproduced exactly; candidate sets identical for 15/15 probes).
- Primary metrics (Consensus vs M Top-10):
  - Full Evidence Success@10: 0.2667 → 0.4667 (+0.2000, 4 → 7 probes)
  - Recall@10: 0.6444 → 0.6889 (+0.0444)
  - Hit@10: 0.9333 → 0.8667 (-0.0667, 14 → 13 probes)
  - MRR: 0.5143 → 0.4963 (-0.0180)
- Candidate ceiling: Candidate-complete probes = 12/15 (0.80). Consensus achieved full success for 7 probes (ceiling utilization = 0.5833, up from 0.3333 under M).
- Required evidence transitions (35 units): STAY_TOP10 = 19, M_TOP10_LOST_BY_CONSENSUS = 3, CONSENSUS_TOP10_GAIN_FROM_M = 5, STAY_OUTSIDE_TOP10 = 8.
- Probe transitions: Full success gained = 3, lost = 0 (net +3 full-success probes). Hit gained = 1, lost = 2 (net -1 hit probe).
- N failure population (8 candidate-complete failure probes under M):
  - 3 probes converted to full success under consensus; 5 remain failures; 1 probe worsened.
  - Of the 8 missing units: 4 entered Top-10, 4 stayed outside Top-10, 5 moved upward, 3 moved downward.
- Determinism: PASS (two consecutive runs produced identical rankings, local table hashes, and metrics). Privacy: PASS (public result contains aggregate-only data, zero sensitive string/ID pattern leaks).
- Interpretation: Combining complementary bi-encoder (K) and cross-encoder (M) ranking signals via simple rank sum consensus significantly boosted complete multi-evidence retrieval (Full Evidence Success@10 from 26.7% to 46.7%, recovering 3 of N's 8 failure probes with 0 full-success regressions). However, because Hit@10 slipped from 93.3% to 86.7% (1 net hit lost), the result formally registers as PARTIALLY_SUPPORTED under the frozen gate rule. Consensus mitigates destructive swaps for multi-evidence probes, but equal-weight sum pushed single-evidence candidates in 2 probes just outside Top-10.

M1-30CH-P — INDEPENDENT_VALIDATION_FIXTURE_V1: PREPARED_PENDING_HUMAN_REVIEW
- Status: PREPARED_PENDING_HUMAN_REVIEW.
- Purpose: Prepare an independent 25-probe held-out validation fixture to evaluate whether frozen K+M consensus (O) generalizes to unseen questions on the 30-chapter Otonari corpus without unacceptable Hit@10 regression. Retrieval evaluation was not executed in this task.
- Scope and limitations: Explicitly classified as query-held-out validation on the shared 30-chapter corpus (OTONARI_LOCAL_PASSAGE_V1 / PARAGRAPH_PACK_V1). It does not test cross-story generalization.
- Fixture composition: 25 probes across 5 canonical categories (5 probes each: CHRONOLOGY, RELATIONSHIP_PROGRESSION, CALLBACK, TEMPORAL_STATE, SPOILER_BOUNDARY). 25/25 require multi-chunk evidence; 22/25 span multiple chapters.
- Human review gate: All 25 probes hold PENDING_REVIEW status pending comprehensive source audit and human review.

M1-30CH-P-AUDIT — SOURCE-GROUNDED GOLD REVIEW: EXECUTED — Fixture Status: PREPARED_PENDING_HUMAN_REVIEW
- Methodology and provenance disclosure: Post-mortem examination of Task P authoring revealed that chunk selection relied on 120–200 character terminal slice previews rather than full-chunk reading, factual support was checked via superficial heuristics (`'keyword' in text or len(text) > 0`), and semantic overlap screening checked only token Jaccard and set equality. The authoring agent also had prior exposure to the 15 development probes in `LONG_RANGE_PROBE_V1/probes.yaml`. Neither independent verification nor fully blinded authoring was achieved in Task P.
- Source audit of all 25 probes: Every probe was audited against the full Japanese source text from `PARAGRAPH_PACK_V1/chunks.jsonl`. Each required chunk and target proposition was verified with exact 0-indexed character offsets `[start, end)`.
- Audit breakdown (25 probes total):
  - Provisional KEEP: 7 probes.
  - Proposed REVISION: 16 probes.
  - NEEDS_HUMAN_REVIEW: 2 probes.
  - Total flagged: 18 / 25 probes (72%).
- Critical issues identified:
  - Gold chunk misassignments (4 probes): Evidence absent from assigned chunk (e.g. event located in a different chunk or recalled off-screen in a subsequent chapter).
  - Expected answer hallucinations (4 probes): Assertions not supported by source (e.g. private dinner hallucination beyond corpus boundary, tea conversation topic misattribution, clothing ownership error).
  - Minimality padding (4 probes): Redundant chunks artificially added to satisfy multi-chunk quota where a single chunk was sufficient.
  - Intra-fixture duplicate blocker (1 probe pair): Two validation probes share identical required chunk sets and query the identical event; one must be replaced.
  - Overlap with development fixture: 1 high semantic overlap probe pair and 6 moderate overlaps identified and cataloged.
- Five private deliverables generated in `.local/story_integration/otonari_30ch/M1_30CH_P_AUDIT/`:
  - `source_gold_audit.jsonl`: 25 structured JSON lines, 60 verifiable propositions with exact 0-indexed character offsets and cutoff checks.
  - `human_review_packet.md`: Human review packet with bilingual questions, target propositions, exact Japanese source excerpts, minimality tables, and sign-off checkboxes.
  - `proposed_revisions.yaml`: Concrete revision proposals for all 18 flagged probes leaving original `draft_probes.yaml` untouched.
  - `overlap_audit_review.json`: Deep semantic overlap analysis across dev probes and intra-fixture probes.
  - `audit_summary.md`: Executive summary of audit findings, provenance, and pre-freeze blockers.
- Protocol updates and pre-registration in `SPEC.md`:
  - Primary comparison pre-registered as O vs M on Top-10 metrics.
  - Previous proposal of acceptable Hit drop threshold marked as unapproved research proposal; replaced with conservative descriptive rules.
  - Uncertainty reporting: 95% paired bootstrap confidence intervals (B=10,000) and McNemar's / exact permutation test.
  - Strict anti-tuning rule: Prohibits parameter tuning of K, M, or O after inspecting validation performance.
  - Single-gold evaluator limitation formally recorded as a blocker.
- No model inference or evaluation executed; Task Q not started; no probe marked APPROVED or FROZEN.

M1-30CH-P-REPAIR — REVISED VALIDATION DRAFT: EXECUTED — Fixture Status: PREPARED_PENDING_HUMAN_REVIEW
- Objective: Create a rigorous revised validation draft grounded in full source evidence for direct human review without forced quota padding or artificial balance.
- Fixture Accounting across all 25 draft probes:
  - Primary multi-evidence validation fixture: 18 probes (100% genuine multi-chunk; 16 multi-chapter; every required chunk strictly NECESSARY under counterfactual removal tests).
  - Category distribution in primary fixture: CHRONOLOGY (5), RELATIONSHIP_PROGRESSION (4), CALLBACK (4), TEMPORAL_STATE (2), SPOILER_BOUNDARY (3).
  - Auxiliary single-chunk candidate pool: 5 probes (inquiries 100% self-contained in a single chunk; segregated to prevent multi-chunk dilution).
  - Deferred pool: 2 probes (1 intra-fixture duplicate and 1 development-set overlap probe held in reserve).
- All distinct audit issues resolved:
  - 4 chunk misassignments corrected to exact source chunks with verified character offsets.
  - 4 answer hallucinations eliminated and reconciled with source text.
  - 5 minimality padding instances segregated into auxiliary single-chunk pool.
  - 1 intra-fixture duplicate blocker resolved by retaining spoiler boundary probe and deferring duplicate callback.
- Protocol corrections in `SPEC.md`:
  - Hit drop tolerance rule of -0.04 formally recorded as an unapproved research proposal and discarded.
  - Conservative descriptive classifications established: DESCRIPTIVE_SUPPORT, MIXED_TRADE_OFF, NO_OBSERVED_GAIN, NOT_EVALUABLE. No trade-off termed 'acceptable' without product criteria.
  - Uncertainty protocol: 95% paired bootstrap CIs (B=10,000, seed 42, identical sample indices for M and O) for macro metrics; exact McNemar's test for primary binary success endpoint. Secondary analyses marked exploratory.
- Six private deliverables created in `.local/story_integration/otonari_30ch/M1_30CH_P_REPAIR/`:
  - `revised_draft_probes.yaml`: 18 primary multi-evidence probes.
  - `deferred_or_auxiliary_probes.yaml`: 5 auxiliary single-chunk probes + 2 deferred probes.
  - `revision_log.jsonl`: 25 structured revision log entries tracking every probe's changes and rationale.
  - `revised_source_gold_audit.jsonl`: 18 audited probe records with 100% verified 0-indexed character offsets into full chunk text.
  - `revised_human_review_packet.md`: Comprehensive human review packet with bilingual questions/answers, verifiable proposition tables, minimality counterfactual tables, and review checklists.
  - `repair_summary.md`: Executive summary of repair accounting, methodology, and protocol corrections.
- Validator enhancements: Validator in `tools/story_benchmark/` updated to separate target counts from validity conditions and add intra-fixture duplicate detection. All 11 unit tests passed.

M1-30CH-P-CORRECTION — FIX SOURCE-CONFIRMED GOLD ERRORS: EXECUTED — Fixture Status: PREPARED_PENDING_HUMAN_REVIEW
- Objective: Fix reviewer-identified gold errors confirmed directly against raw chunks.jsonl, synchronize draft probes, audit records, and human review packet, and implement automated regression prevention.
- Fixture Accounting across all 25 probes:
  - Primary multi-evidence validation fixture: 16 probes (100% genuine multi-chunk; 100% multi-chapter; every required chunk strictly necessary under counterfactual analysis).
  - Category distribution in primary fixture: CHRONOLOGY (5), RELATIONSHIP_PROGRESSION (4), CALLBACK (2), TEMPORAL_STATE (2), SPOILER_BOUNDARY (3).
  - Auxiliary single-chunk candidate pool: 6 probes (including retrospective recall probes where prior events are fully detailed within later single chunks).
  - Deferred pool: 3 probes (1 intra-fixture duplicate, 1 dev-set overlap, 1 alternative-evidence probe held due to single-gold evaluator limitation).
- Key Source-Confirmed Error Corrections:
  - Key handoff & naming boundaries: Separated temporary emergency handoff in Ch 22 from ongoing key retention in Ch 25; accurately represented private first-name permission in Ch 24 and polite/neighbor boundaries in Ch 4.
  - Parental discovery grounding: Grounded maternal discovery in Ch 22 strictly on source text (Mahiru resting against the edge of the bed hugging a cushion on her lap; dining tableware discovery); eliminated ungrounded shoe claims and false Ch 23 dependency.
  - Relationship progression cleanups: Grounded physical contact progression across ankle first aid (Ch 13), piggybacking home (Ch 13), and feeding cake (Ch 26); removed over-interpreted balcony distancing and pre-packaged rhetorical conclusions.
  - Retrospective recall segregation: Segregated retrospective recall into auxiliary pool (Ch 2 umbrella lending and cold).
  - Multi-gold evaluator reservation: Deferred probes with alternative valid evidence paths (crepe compensation advice in Ch 20) until evaluator supports multi-gold sets.
- Verification & Test Suite:
  - 100% of character offset spans [char_offset_start:char_offset_end] match raw chunk slices in chunks.jsonl with zero mismatch.
  - Extended validator in `tools/story_benchmark/` with `validate_source_gold_audit_and_partitions()`.
  - Added 6 synthetic negative unit tests in `tests/story_benchmark/test_validate_independent_validation_fixture_v1.py` covering invalid bounds, excerpt mismatches, unmapped chunks/propositions, draft-audit divergence, and partition leaks.
  - Full test suite execution across all 13 test files in `tests/story_benchmark`: 217 / 217 tests passed cleanly in 28.9s (exit code 0; raw log preserved).
- Five private deliverables and test log packaged into `.local/story_integration/otonari_30ch/M1_30CH_P_CORRECTION_PACKAGE.zip`:
  - `corrected_draft_probes.yaml`
  - `auxiliary_and_deferred.yaml`
  - `corrected_source_gold_audit.jsonl`
  - `corrected_revision_log.jsonl`
  - `corrected_human_review_packet.md`
  - `raw_test_log.txt`
- No retrieval, embedding, BGE reranking, or scoring executed; Task Q not started; all probes remain strictly PENDING_REVIEW.

M1_30CH_P_SEMANTIC_FIX — SOURCE SEMANTICS & REQUIRED-EVIDENCE REPAIR: EXECUTED — Fixture Status: PREPARED_PENDING_HUMAN_REVIEW
- Re-read the Japanese source for 9 reviewer-flagged primary probes and revised questions, answers, facts, propositions, source spans, and counterfactual necessity explanations from one generator-backed definition.
- Corrected the inability-to-walk contradiction; removed unsupported tree, laundering, bedroom, contacts/bangs, and "unpolished gem" details; represented the early relationship boundary as Amane's statement rather than a mutual agreement.
- Reframed callback, spoiler-boundary, relationship-progression, chronology, and temporal questions so each required chunk supplies a concrete answer part requested by the question.
- Partition accounting remains 16 primary / 6 auxiliary / 3 deferred because all 9 repaired probes retain source-grounded necessity, not because of a quota. Actual primary structure is 16 multi-chunk and 13 multi-chapter.
- Added complete private artifacts under `.local/story_integration/otonari_30ch/M1_30CH_P_SEMANTIC_FIX/`: `draft_probes.yaml`, `source_gold_audit.jsonl`, `human_review_packet.md`, `revision_log.jsonl`, `auxiliary_and_deferred.yaml`, `validation_report.json`, `raw_test_log.txt`, and `manifest.json`.
- Extended the public validator with complete review-bundle checks: exact source slices, cutoffs, proposition mapping, partition coverage, all-`PENDING_REVIEW` status, review-packet synchronization, derived counts, and manifest hashes.
- Relevant verification passed: fixture validator 18 tests, frozen long-range validator 21 tests, ingestion/corpus 20 tests (59 total, all exit 0). Corpus, segmentation artifacts, and LONG_RANGE_PROBE_V1 hashes remained unchanged.
- Packaged private artifacts as `.local/story_integration/otonari_30ch/M1_30CH_P_SEMANTIC_FIX.zip` (SHA-256 `44fe92f9fffd6eb9f72382b51faad5c0239d024fbdc1072e73d9bb7f3a8e5f87`). No retrieval experiment, K/M/O evaluation, approval, or freeze was performed.

M1-30CH-P-REVIEW-GATE — SOURCE-GROUNDED VALIDATION REVIEW & PRE-FREEZE BLOCKER RESOLUTION: EXECUTED — Fixture Status: PREPARED_PENDING_HUMAN_REVIEW
- Independent source audit across all 25 probes against the full 30-chapter Japanese source (`PARAGRAPH_PACK_V1`, 97 chunks, 96,972 characters).
- Verified 16 primary probes: 100% source-grounded with exact character offset slices [start, end), zero chapter cutoff violations, and confirmed counterfactual necessity (each chunk supplies an essential, non-redundant answer component).
- Critical source finding in auxiliary pool: 3 of 6 auxiliary probes contain severe factual hallucinations carried over from early unverified drafts (V_TEMP_01 claims rolled cabbage in Ch 5; V_SPOIL_03 claims pudding in Ch 16; V_SPOIL_05 claims light bulb replacement in Ch 27; all three terms are completely absent from the 30-chapter Web Novel corpus). Flagged as NEEDS_REVISION / REJECTED in review decision register.
- Formally analyzed the Multi-Gold Evaluator Blocker in `multi_gold_feasibility.md`: formulated schema representation, mathematical metrics (Hit, Recall, Full Evidence Success, MRR), and proved 100% backwards compatibility on single-gold benchmarks. Kept V_CALL_03 in deferred pool until evaluator implementation.
- Prepared comprehensive human review packet in Vietnamese (`review_packet_vi.md`) and decision register (`review_decisions.csv`) covering all 25 probes with default status PENDING_REVIEW (no automated approval granted).
- Extended validator with `validate_review_gate_deliverables()` and added regression unit tests in `tests/story_benchmark/test_validate_independent_validation_fixture_v1.py`.
- Full relevant verification passed: 61 tests (fixture validator 20, frozen long-range validator 21, ingestion/corpus 20; all exit code 0).
- Eight private deliverables packaged in `.local/story_integration/otonari_30ch/M1_30CH_P_REVIEW_GATE/` and `.local/story_integration/otonari_30ch/M1_30CH_P_REVIEW_GATE.zip` (SHA-256 `4d1c1cdcd4889415697603e8e056011aff97d749433b72b68ba83292e53e5ce0`). Zero private data leaked.
M1-30CH-P-PREFREEZE-CORRECTION — PRE-FREEZE EVIDENCE RECONCILIATION & FINAL REVIEW PACKAGE: EXECUTED — Fixture Status: PREPARED_PENDING_HUMAN_REVIEW
- Investigated and resolved historical probe ID inconsistencies: all files on disk consistently use canonical `V_CHRONO_01` to `V_CHRONO_05`; earlier conversational references to `V_CHRO_01`/`03` and deferred `V_CHRO_02` classified as `REPORT_ONLY_TYPO`. Confirmed all 5 previous spot-checks were genuine primary probes (`V_CHRONO_01`, `V_CHRONO_02`, `V_REL_01`, `V_TEMP_02`, `V_SPOIL_01`).
- Completed exhaustive source audit across all 16 genuine primary probes against the 30-chapter Japanese corpus (`PARAGRAPH_PACK_V1`, 97 chunks):
  - 40/40 atomic propositions verified `EXPLICITLY_STATED` in source chunks with 100% exact character offset slice matches [start:end) (zero mismatches).
  - Zero chapter cutoff violations; temporal ordering verified; relationship and boundary semantics accurately represented (Amane's unilateral statements vs mutual agreements).
  - Counterfactual minimality verified for every required chunk (zero redundant padding chunks).
  - Alternative evidence paths documented: adjacent scene chunk `ch013_c0003` for `V_CHRONO_01`; 15 remaining probes verified `NO_ALTERNATIVE_FOUND` within corpus boundaries.
- Finalized auxiliary and deferred disposition:
  - 3 hallucinated auxiliary probes (`V_TEMP_01` rolled cabbage, `V_SPOIL_03` pudding, `V_SPOIL_05` light bulb) designated `REJECT_AS_CURRENTLY_WRITTEN`; prohibited from entering primary benchmark.
  - 3 valid auxiliary probes (`V_TEMP_04`, `V_TEMP_05`, `V_CALL_01`) retained in single-chunk auxiliary pool.
  - Confirmed corrected identity of `V_CALL_03` (Chitose / plush teddy bear / station crepe advice; eliminated erroneous first-name description); held in deferred pool due to multi-gold evaluator constraints.
  - All 25 human decision fields strictly preserved as `PENDING_REVIEW` (no automated approval).
- Evaluator compatibility verified: existing `calculate_metrics` scored 16/16 primary probes consistently. Observed category distribution reported without forced quotas: CHRONOLOGY (5), RELATIONSHIP_PROGRESSION (4), CALLBACK (2), TEMPORAL_STATE (2), SPOILER_BOUNDARY (3).
- Nine private deliverables created under `.local/story_integration/otonari_30ch/M1_30CH_P_PREFREEZE_CORRECTION/`: `canonical_probe_inventory.csv`, `primary_gold_audit.jsonl`, `corrected_human_review_packet_vi.md`, `auxiliary_deferred_disposition.md`, `evaluation_readiness.md`, `correction_log.md`, `validation_report.json`, `raw_test_log.txt`, `manifest.json`.
- Private deliverables packaged as `.local/story_integration/otonari_30ch/M1_30CH_P_PREFREEZE_CORRECTION.zip` (SHA-256 `89c09b85fd01fe1a3ac88d056d149508ddbc2a0350910d8cb5e3067a206990a8`).
- Public validator updated with `validate_prefreeze_correction_deliverables()` and unit tests added. Full relevant test suite passed: 63 tests (fixture validator 22, frozen long-range validator 21, ingestion/corpus 20; exit code 0; raw test log preserved).
- Evaluation readiness discipline maintained: `DATA_PREPARED = true`, `TECHNICAL_VALIDATION_PASSED = true`, `HUMAN_REVIEW_PENDING = true`, `FROZEN = false`, `EVALUATION_ALLOWED = false`. Task Q evaluation remains strictly blocked.

M1-30CH-P-HUMAN-REVIEW-HANDOFF — MULTI-GOLD PROTOCOL RECONCILIATION, V_CHRONO_01 SOURCE AUDIT & HUMAN REVIEW HANDOFF: EXECUTED — Fixture Status: READY_FOR_HUMAN_REVIEW
- Reconciled evaluation-protocol ambiguity:
  - Addressed discrepancy between `INDEPENDENT_VALIDATION_FIXTURE_V1_SPEC.md` / `MANIFEST.yaml` (requiring multi-gold representation before final freeze) and recent proposals to freeze 16 single-gold primary probes.
  - Documented protocol reconciliation in `protocol_reconciliation.md` as `PROPOSED` (awaiting Product Owner formal sign-off; no unilateral modification of pre-registered specifications).
- In-depth source audit of suspected alternative evidence for `V_CHRONO_01`:
  - Investigated adjacent chunk `ch013_c0003` (Mahiru spraining ankle at park, Amane lending hoodie, piggybacking her on the way home) against `ch013_c0004` (dropping her off at the apartment door).
  - Evaluated against 4 strict criteria: (1) not merely contextual, (2) shares ongoing multi-passage action, (3) fully substitutes required evidence for the question, (4) forms a complete minimal alternative gold set: Gold Set 1 (`ch001_c0003`, `ch008_c0003`, `ch013_c0004`) and Gold Set 2 (`ch001_c0003`, `ch008_c0003`, `ch013_c0003`).
  - Under single-gold scoring, returning Gold Set 2 yields Recall@10 = 0.6667 and Full Evidence Success@10 = 0 (artificial false negative).
  - Officially designated `V_CHRONO_01` as `PRIMARY_FREEZE_BLOCKER`. Recommended either deferring `V_CHRONO_01` to freeze 15 strictly single-gold probes, or implementing multi-gold evaluation before freeze.
- Semantic verification provenance and epistemic limits audit:
  - Inspected code provenance for "40/40 atomic propositions = EXPLICITLY_STATED": confirmed 100% exact Unicode character offset slice match in `chunks.jsonl`, but clarified that the `EXPLICITLY_STATED` label was assigned by heuristic script convention rather than an automated semantic prover.
  - Articulated epistemic boundaries across 4 levels: exact character slice match, manual semantic entailment, counterfactual minimality, and corpus-wide alternative search.
- Produced 7 comprehensive human-review handoff deliverables in `.local/story_integration/otonari_30ch/M1_30CH_P_HUMAN_REVIEW_HANDOFF/`:
  1. `protocol_reconciliation.md`
  2. `v_chrono_01_alternative_audit.md`
  3. `semantic_verification_provenance.md`
  4. `human_review_guide_vi.md`
  5. `human_decision_template.csv`
  6. `readiness_and_blockers.md`
  7. `manifest.json`
- Human review package packaged into `.local/story_integration/otonari_30ch/M1_30CH_P_HUMAN_REVIEW_HANDOFF.zip` (SHA-256 `63ea3432525b9a956a27b3abeaad55548e97b6793a65bb006dcb586220950bb0`).
- Validator extended with `validate_human_review_handoff_deliverables()` with flexible decision status validation; regression unit tests added; all 24 validator unit tests passed cleanly.
- Evaluation readiness strictly maintained: `DATA_PREPARED = true`, `TECHNICAL_VALIDATION_PASSED = true`, `HUMAN_REVIEW_PENDING = true`, `FROZEN = false`, `EVALUATION_ALLOWED = false`. Task Q remains strictly blocked until Product Owner sign-off and blocker resolution.

Private chunk text, probes, and review sheets remain LOCAL_ONLY. No LLM / embedding / retrieval external API performed.

M1-30CH-P-FINAL-VALIDATION-FREEZE-CANDIDATE — EXECUTED — Fixture Status: FIX_REQUIRED
- Independently rehashed the 30 raw chapters, paragraph pack, and required prior packages; all critical declared hashes matched.
- Reconstructed 25 candidate probes from source data: 16 primary, 6 auxiliary, and 3 deferred. Human decisions remain pending.
- Re-read all 40 primary propositions against source and neighboring context. Aggregate result: 34 directly explicit, 3 strongly entailed, 1 interpretive inference, 0 ambiguous, and 2 unsupported.
- Probe-level result: 12 pass, 2 need revision, and 2 are blocked. All declared primary sets remain multi-evidence within their current wording, but one has a questionable context split.
- Systematic non-retrieval alternative-evidence audit result: 4 with no complete alternative found, 10 with partial alternatives, 2 with complete alternative gold paths, and 0 uncertain. The two complete paths are primary freeze blockers for the current single-gold evaluator.
- Corrected the historical claim that one deferred callback was multi-gold: its retrospective evidence is self-contained; continued deferral is justified by overlap, not a second complete gold path.
- Recorded `PROPOSED_PROTOCOL_REVISION_MULTI_GOLD_SCOPE` as `PROPOSED_PENDING_PRODUCT_OWNER_APPROVAL`. The current population fails both the original global prerequisite and the proposed per-probe rule.
- Added an unsigned, hash-bound human sign-off workflow and machine-checkable final-package validator. Package mutation makes a separate sign-off stale.
- No retrieval, model scoring, Task Q, human approval, or fixture freeze was performed. `EVALUATION_ALLOWED = false`.

## Next Candidate

M1-30CH-P-BLOCKER-REPAIR-MULTIGOLD — EXECUTED — Fixture Status: READY_FOR_HUMAN_SIGNOFF

- Repaired the four confirmed blockers without running retrieval: two semantic formulations were narrowed to local-source entailment, including removal of an unsupported exact-date assertion, and two chronology probes now contain every verified complete minimal gold path.
- Preserved 16 primary probes with observed category distribution: CHRONOLOGY 5, RELATIONSHIP_PROGRESSION 4, CALLBACK 2, TEMPORAL_STATE 2, SPOILER_BOUNDARY 3. The repaired fixture has 14 single-gold and 2 multi-gold primary probes.
- Final proposition audit: 37 `DIRECTLY_EXPLICIT`, 3 `STRONGLY_ENTAILED`, 0 `INTERPRETIVE_INFERENCE`, 0 `AMBIGUOUS`, and 0 `UNSUPPORTED`.
- Implemented one canonical multi-gold normalizer and shared metric calculator. Hit and MRR use the union of valid evidence; Recall uses the best-compatible valid path; Full Evidence Success accepts completion of any valid path.
- Proved exact single-gold compatibility across all 16 historical primary structures: 160 / 160 values equal for Hit@1/5/10, Recall@1/5/10, Full Evidence Success@1/5/10, and MRR.
- Marked the unapproved narrower protocol proposal `SUPERSEDED_UNAPPROVED_BY_MULTIGOLD_IMPLEMENTATION`; the original stricter prerequisite remains intact.
- Focused validation passed (7 multi-gold metric tests, 38 fixture-validator tests, 21 frozen long-range validator tests, and 20 ingestion/corpus tests). The broader story-benchmark discovery was attempted and is recorded `INCOMPLETE_DUE_TO_TIMEOUT` after 180 seconds, not PASS.
- Generated a new LOCAL_ONLY unsigned package at `.local/story_integration/otonari_30ch/M1_30CH_P_BLOCKER_REPAIR_MULTIGOLD.zip`, SHA-256 `15fbecac77b949d9743e38b80e831e79b283f45a3b76fe521d172d575eb4e301`. The old v1 package/sign-off hash is stale for this lifecycle.
- No retrieval, embeddings, reranker scoring, K/M/O execution, Task Q, human approval, or fixture freeze occurred. `HUMAN_REVIEW_PENDING = true`, `FROZEN = false`, and `EVALUATION_ALLOWED = false`.

## Next Candidate

M1-30CH-P-SIGNOFF-PACKAGE-CONSISTENCY-REPAIR — EXECUTED — Fixture Status: READY_FOR_HUMAN_SIGNOFF

- Correction to the previous entry: the v2 package was not sign-off ready. Its evaluated fixture and its review artifacts came from different lineages. For 9 of 16 primary probes, the question and expected answer that Task Q would evaluate differed from the text shown to the reviewer (36 field mismatches across semantic audit and review guide).
- A new structural audit of v2 also found 21 defects: one probe whose gold set omitted a chunk essential to its reviewed answer (a partial retrieval would have scored Full Evidence Success), two multi-gold probes whose alternative path did not support a proposition as worded, stale or missing minimality records, and 13 evidence excerpts truncated below the span their offsets declared.
- Established one canonical source of truth per primary probe (question, answer, propositions, proposition support, gold sets). Semantic audit, review guide, inventory, and sign-off template are now generated projections; evaluation facts are derived from propositions.
- Added a proposition-support model: each proposition lists the chunks that independently support it, and gold sets must equal the minimal hitting sets of that support. This single rule enforces coverage, minimality, and complete alternative-path representation for single- and multi-gold probes.
- Added validator checks for exact fixture/audit/guide/inventory equality, excerpt-equals-source-slice, stale minimality, and derived facts, with synthetic regression tests (19).
- Source-verified repairs narrowed several propositions and answers to what the source states, and reclassified two hedged claims from explicit to strongly entailed. Final proposition audit: 35 `DIRECTLY_EXPLICIT`, 5 `STRONGLY_ENTAILED`, 0 `INTERPRETIVE_INFERENCE`, 0 `AMBIGUOUS`, 0 `UNSUPPORTED`. Population unchanged: 16 primary (14 single-gold, 2 multi-gold).
- Tests: 19 consistency, 38 fixture-validator, 7 multi-gold, 21 frozen long-range, 20 ingestion; the full story-benchmark discovery completed (264 / 264).
- New LOCAL_ONLY unsigned package `.local/story_integration/otonari_30ch/M1_30CH_P_SIGNOFF_CONSISTENCY_REPAIR.zip`, SHA-256 `fcd147eb57c7b8ab9500c85ad633436524b96a014aa4ef8b68dfdfbf9d4515a6`. The v2 hash `15fbecac77b949d9743e38b80e831e79b283f45a3b76fe521d172d575eb4e301` and the v1 hash are stale and invalid for sign-off.
- No retrieval, K/M/O execution, Task Q, human approval, or fixture freeze occurred. `HUMAN_REVIEW_PENDING = true`, `FROZEN = false`, `EVALUATION_ALLOWED = false`.

## Next Candidate

M1-30CH-P-HUMAN-SIGNOFF-FREEZE-GATE — EXECUTED — Fixture Status: FROZEN

- The Product Owner explicitly authorized decisions for the v3 package. The agent transcribed them verbatim into a separate sign-off artifact bound to the v3 ZIP SHA-256: 16 primary `APPROVED`, 3 auxiliary `REJECTED`, 6 auxiliary/deferred `DEFERRED`, 0 pending. Sign-off SHA-256 `03de5485c07ec84d5e8e32624db23e1e3f22d91ffc11828c4a458005513a9037`.
- The sign-off validated against the exact v3 hash, and the stale v2 hash was rejected in both directions (sign-off against v2 package; v2-hash sign-off against v3 package).
- Freeze gate passed: technical gate, complete sign-off, all primary probes approved, package hash match, privacy, and no Task Q execution. The frozen package was derived from the reviewed ZIP bytes, not an editable directory.
- Frozen fixture version 1: SHA-256 `f07b2d4048f424d8e885221ff4b14f3d572a22bf2e5a405382782ad1672f1dc1`; 16 primary probes (14 single-gold, 2 multi-gold); frozen from Git `37625d5`. `EVALUATION_ALLOWED = true`, `TASK_Q_EXECUTED = false`.
- Added `fixture_freeze.py` (eligibility gate, frozen-package validator, Task Q plan binding to the pre-registered protocol) with 15 synthetic tests.
- Recorded accepted decision `INDEPENDENT_VALIDATION_FIXTURE_V1_FREEZE` in `DECISIONS.md`.
- Task Q is prepared (local run plan bound to the frozen hash) but NOT executed. No K/M/O run, validation score inspection, or post-freeze tuning occurred.

## Next Candidate

M1-30CH-Q-INDEPENDENT-VALIDATION-EXECUTION — EXECUTED — Status: TASK_Q_COMPLETE

- Executed once against frozen fixture `f07b2d40…1dc1` under the unchanged pre-registered protocol, using the frozen K/M/O cores through a new dedicated executor (`run_independent_validation_task_q_v1.py`). All rankings were persisted before any gold label was read.
- Results on 16 held-out primary probes (Top-10):
  - K: Full Evidence Success 10 / 16, Recall 0.8125, Hit 16 / 16, MRR 0.6656.
  - M: Full Evidence Success 11 / 16, Recall 0.8333, Hit 16 / 16, MRR 0.7365.
  - O: Full Evidence Success 11 / 16, Recall 0.8542, Hit 16 / 16, MRR 0.8021.
- O − M: Success 0.0000, Recall +0.0208, Hit 0.0000, MRR +0.0656. Paired bootstrap 95% CI for Success delta [−0.1875, +0.1875]. Discordant pairs 1 / 1; exact McNemar p = 1.0; exact paired permutation p = 1.0. N = 16, so power is limited, and non-significance is not equivalence.
- Descriptive classification: `PREREGISTERED_RULES_DO_NOT_COVER`. The outcome (Success unchanged, Recall up, Hit unchanged, nothing down) matches none of the four pre-registered classes. The executor declared this handling before execution; interpretation is left to the Master Orchestrator.
- Disclosure: a first attempt was terminated by a host session ending before rankings were persisted, gold was read, or any metric existed. It is preserved privately; the second attempt re-ran the identical command.
- The frozen fixture was not modified. No tuning, retry of alternative weights, or new method occurred.

Master Orchestrator interpretation followed: M1 closed for its current research scope (see M1 Closure Note at the top).

M2-01-CANONICAL-STORY-MODEL-DOMAIN-REQUIREMENTS — EXECUTED — Status: M2_01_COMPLETE_READY_FOR_M2_02

- Created `docs/research/m2/M2_CANONICAL_STORY_MODEL_REQUIREMENTS.md`.
- It derives capability groups from the foundation documents and M1 findings: identity, events, time, relationships, entity state, information and knowledge, claims, provenance, spoiler scope, and uncertainty.
- It proposes 18 domain invariants (INV-01 to INV-18), a candidate concept inventory with first-class / uncertain / deferred status, temporal, epistemic, provenance and source-independence requirements, 13 open questions, and acceptance criteria for M2-02.
- Research only: no schema, storage, extraction, or technology choice was made, and nothing was added to `DECISIONS.md`.

M2-02-CANONICAL-STORY-MODEL-CORE-CONCEPTS — COMPLETED — Status: PENDING ORCHESTRATOR REVIEW

- Corrected the M1 lifecycle wording at the top of this file: the research program is closed, and the formal Script Quality Contract is still open.
- Corrected the M2-01 boundary: M2-02 covers logical concepts and boundaries; M2-03 covers Canonical Schema v0.
- Created `docs/research/m2/M2_CORE_CONCEPTS_AND_BOUNDARIES.md`.
- Core thesis: a truth-neutral Proposition is distinct from the canonical Assertion that commits to it, with polarity, epistemic status, validity, evidence sets, derivation, and review.
- Knowledge states are attitude Assertions that embed a Proposition without asserting it. KNOWS and MISTAKEN are derived per view.
- Relationship, Secret, StoryClaim, Alias, and reader knowledge are derived views. Character reveals are events; reader reveal is derived from evidence availability.
- A leak-free as-of view is defined through each Assertion's availability position.
- Proposes an amendment to INV-06: the same distinctions, carried on orthogonal dimensions.
- All 13 M2-01 open questions are resolved or explicitly deferred. Stress tests A–J are represented.
- Research proposal only: no schema, no technology choice, and no `DECISIONS.md` entry.

M2-03-CANONICAL-STORY-SCHEMA-V0 — COMPLETED — Status: PENDING ORCHESTRATOR REVIEW

- Formalized layers L1–L4 as Canonical Story Schema v0, using JSON Schema Draft 2020-12 as notation only; no storage or framework was chosen.
  - `schemas/canonical_story/canonical_story_v0.schema.json`
  - `schemas/canonical_story/predicate_registry_v0.yaml`
  - `docs/research/m2/M2_CANONICAL_SCHEMA_V0.md`
- Added a semantic conformance validator (`tools/canonical_story/conformance_v0.py`) with the normative support-path availability rule. Only SUFFICIENT evidence sets and derivations count, as alternatives.
- Corrected the PARATEXT rule to an authority-policy matter (not accepted as sufficient grounding under `DEFAULT_V0`).
- Synthetic fixtures: stress tests A–J all pass the structural and semantic layers; 17 negative fixtures are each rejected for the expected reason. A machine-readable conformance report is committed.
- Tests: 24 canonical-schema tests pass, with no model, API or network. The standard `jsonschema` package (Draft 2020-12) is now a test dependency.
- Derived concepts (Relationship, Secret, StoryClaim, Alias, KNOWS, MISTAKEN, reader reveal, chronology) are not record types.
- Research proposal only; `DECISIONS.md` is unchanged.

M2-04-AS-OF-PROJECTION-AND-DERIVED-VIEWS — COMPLETED — Status: PENDING ORCHESTRATOR REVIEW

- Declared the Canonical Story tooling dependencies in `requirements-canonical-story.txt` (jsonschema ≥ 4.18 < 5, PyYAML ≥ 6 < 7). Tests now fail loudly, never skip, if they are missing.
- Added the reference projection `tools/canonical_story/view_v0.py`: `project_as_of(document, position)` returns a derived, disposable view. It reuses the shared availability calculator and never mutates its input.
- The view covers:
  - leak-free visibility, including referents and support paths;
  - delayed bound projection;
  - identity, mention and content resolution;
  - canonical commitment status (UNCOMMITTED, OPEN, AFFIRMED, NEGATED, CONTESTED, TIME_SCOPED);
  - KNOWS, MISTAKEN and UNRESOLVED_BELIEF verdicts;
  - reported claims and conflicts, relationship stages, and secrets;
  - reader reveal (valid only under DEFAULT_V0 reliable narration);
  - event occurrence, explicit temporal relations, and conservative functional-conflict diagnostics.
- Tests: 36 projection tests covering stress cases A–J, machine-readable M2-02 §21 snapshots (as of 5, 20 and 22), 10+ spoiler-leak cases, holder-relative safety, contradictions, negated belief content, immutability and determinism. With the 24 schema tests, 60/60 pass; the story_benchmark and story_ingestion regressions also pass.
- Schema v0 and the predicate registry are unchanged. Documentation: `docs/research/m2/M2_AS_OF_PROJECTION_V0.md`. `DECISIONS.md` is unchanged.

M2-05-SIGNED-INFORMATION-SEMANTICS-HARDENING — COMPLETED — Status: PENDING ORCHESTRATOR REVIEW

- **Reproduced first (RED).** Concealed P AFFIRMED with target believing P NEGATED, and the inverse, were reported as secret ENDED instead of ACTIVE. Cause: `Conceals` carried no polarity, so secret matching ignored sign.
- **Correction to the pre-freeze Schema v0** (schema version unchanged; the JSON Schema file needed no change):
  - `SignedInformation = Proposition + polarity`, composed from existing parts rather than a new record.
  - Registry: new `signed_polarity` vocabulary (AFFIRMED / NEGATED). `Conceals` gains `content_polarity`. `Conveys.content_polarity` is restricted to signed polarity. `REVEAL_RESULT` must preserve the Conveys content and polarity, enforced by a new small validator check.
  - `Says` and `Attitude` keep the full polarity vocabulary; OPEN there means an undetermined stance.
- **Projection:** secrets match signed content for holding, learning and UNAWARE. UNAWARE is interpreted as polarity-specific in V0. Reader fields are now signed (`reader_knows_signed_content`, `reader_knows_content_resolution`, `reader_signed_content_status`), replacing M2-04's polarity-unaware `reader_has_canonical_content`.
- **Tests:** 19 new signed-information tests and 2 new negative fixtures (OPEN concealed polarity; reveal flipping polarity). Canonical story suite 79/79; A–J behaviour intact. `DECISIONS.md` unchanged.

M2-06-REAL-SOURCE-CANONICAL-MAPPING-SPIKE — COMPLETED — Status: PENDING ORCHESTRATOR REVIEW

- **Method.** Mapped 10 real cases from the private 30-chapter corpus (identity verified; 3 simple, 4 medium, 3 difficult) by hand into Canonical Story Model v0.
  - Frozen Task Q gold was not used.
  - Schema, registry, validator and projection were unchanged.
  - An in-memory additive "extension probe" tested whether vocabulary gaps are additive.
- **Conformance.** Both private documents (v0 registry; v0 plus additive probe entries) pass the unchanged contract. As-of checks pass 36/36 and 41/41.
- **Fit.**
  - v0 registry as-is: NATURAL 1, ACCEPTABLE 4, AWKWARD 4, NOT_REPRESENTABLE 1.
  - With additive vocabulary: NATURAL 3, ACCEPTABLE 6, AWKWARD 1.
- **Findings.** No blocking model defect. Non-blocking findings:
  - setting-dependent address forms (AddressesAs `functional_on` wrong for real data);
  - duplicate-content propositions accepted (identity by content not enforced);
  - missing condition, emotion, ownership, intention and habitual vocabulary;
  - existential content, resolution propagation into embedding propositions, omission causation, focalization, non-assertive speech acts, and conditional bounds.
- **Recommendation.** READY_FOR_M2_FREEZE_REVIEW, conditional on an additive registry extension, the AddressesAs correction, and a duplicate-proposition conformance rule.
- **Artifacts.**
  - Private package `M2_06_REAL_MAPPING_V1.zip`, SHA-256 `1d3f4cc93965c916071b11a451c54b8adcc7886a4ec4f1086b2e302ea7312e93`; not committed.
  - Public sanitized result `benchmarks/m2_canonical_model/REAL_SOURCE_MAPPING_SPIKE_V1_RESULT.yaml` and `docs/research/m2/M2_REAL_SOURCE_MAPPING_SPIKE.md`.
- M2 is not closed. `DECISIONS.md` is unchanged.

M2-07-CANONICAL-STORY-PRE-FREEZE-HARDENING — COMPLETED — Status: M2_07_FREEZE_CANDIDATE_READY (PENDING ORCHESTRATOR REVIEW)

- **Context.** M2-06 was accepted with no blocking defect; freeze was not authorized until three conditions were met.
- **Registry `predicate_registry/v0.1`** (schema stays `canonical_story/v0`):
  - added `PhysicalCondition`, `EmotionToward`, `Intends` (holder-relative), `Owns`, `Habitually`;
  - `BEHAVIOUR_SUGGESTS_STATE` may conclude `EmotionToward`;
  - `AddressesAs` no longer declares `functional_on`. No `setting` argument was added; address context is a recorded limitation.
- **Validator.** Duplicate concrete proposition content is rejected (placeholders exempt). Negative fixture 20.
- **Real-source re-validation against the committed registry.** Same 10 cases, annotations unchanged apart from mechanical predicate migration. Conformance PASS; as-of checks 54/54.
  - Fit: NATURAL 3, ACCEPTABLE 6, AWKWARD 1, NOT_REPRESENTABLE 0. All three difficult cases ACCEPTABLE.
  - One rating (CASE_REAL_05) is a disclosed borderline judgement for the Orchestrator to confirm.
- **Tests.** Canonical story 99/99; story_benchmark 298/298; story_ingestion 20/20.
- **Not changed.** Schema, projection, and the known limitations listed in `docs/research/m2/M2_PRE_FREEZE_REVIEW.md` §8. Polarity-specific UNAWARE remains PROVISIONAL / NOT REAL-SOURCE VALIDATED.
- **Artifacts.**
  - `benchmarks/m2_canonical_model/CANONICAL_STORY_V0_FREEZE_CANDIDATE.yaml` (`freeze_status: CANDIDATE_PENDING_ORCHESTRATOR_REVIEW`; binds schema, registry, validator, projection and M2 documents by SHA-256).
  - `docs/research/m2/M2_PRE_FREEZE_REVIEW.md` (includes registry governance).
  - Private package `M2_07_PRE_FREEZE_V1.zip`, SHA-256 `2b1d65a9ea43f646be519577ec60cc43d3ae64108de97e3b9963670baadf5eaf`; not committed.
- Validation covers one 30-chapter story in one genre with one primary annotator. M2 is not frozen. `DECISIONS.md` is unchanged.

M2-08-FREEZE-CANONICAL-STORY-MODEL-V0 — COMPLETED — Status: M2_08_CANONICAL_STORY_V0_FROZEN

- **Authorization.** The Master Orchestrator accepted M2-07, confirmed CASE_REAL_05 as ACCEPTABLE, accepted the registry governance policy, and approved the freeze. The agent transcribed that authorization and did not originate it.
- **Canonical Story Model v0: FROZEN / ACCEPTED** (`DECISIONS.md` DEC-016).
  - Schema `canonical_story/v0`; registry `predicate_registry/v0.1`; authority policy `DEFAULT_V0`.
  - Freeze record: `benchmarks/m2_canonical_model/CANONICAL_STORY_V0_FROZEN.yaml`, SHA-256 `bde15f84b6e72a202a833622ff1fe0822d6d3b5a3e926c1195b437a348b9034e`.
  - Candidate commit `61ac00a8ff601af4b8f51a4815b3a6e1a095e6b9`. The candidate manifest is kept unchanged as history.
- **Freeze gate (re-run before the record was written).**
  - All 11 bound artifacts match the candidate hashes; none was edited.
  - Private package `M2_07_PRE_FREEZE_V1.zip` matches its SHA-256 and its internal manifest (18 entries).
  - Tests: canonical story 99/99, story_benchmark 298/298, story_ingestion 20/20.
  - Private real-source document against the committed contract: structural PASS, semantic PASS, as-of 54/54.
- **No model change.** Schema, registry, validator, projection and tests are untouched in this task.
- **Known limitations** are recorded in the freeze record and DEC-016 as accepted for V0, not solved.
- **Immutability.** Frozen artifacts are never silently modified in place. Additive registry changes create `predicate_registry/v0.2`; breaking changes need a new version, architecture review, migration implications and renewed conformance evidence.
- **Scope.** Validation covers one 30-chapter story in one genre with one primary annotator. The freeze is a V0 engineering contract, not universal ontology completeness.
- This is the final M2 research record. The M1 Formal Script Quality Contract remains OPEN. M3 has not started and the roadmap is unchanged.

M1-FORMAL-SCRIPT-QUALITY-CONTRACT-V0-CANDIDATE — COMPLETED — Status: M1_SCRIPT_QUALITY_V0_CANDIDATE_READY (PENDING ORCHESTRATOR REVIEW)

- **Purpose.** Formalize what a high-quality, grounded storytelling script must satisfy. The task defines the standard. It ran no model, proved nothing about the current Writer or critics, and did not freeze the contract.
- **Artifacts.**
  - `docs/contracts/SCRIPT_QUALITY_CONTRACT_V0.md` (candidate, 22 sections).
  - `benchmarks/m1_script_quality/SCRIPT_QUALITY_CONTRACT_V0_CANDIDATE.yaml` (`status: CANDIDATE_PENDING_ORCHESTRATOR_REVIEW`).
  - `benchmarks/m1_script_quality/evaluations/HUMAN_REVIEW_TEMPLATE.md` upgraded from provisional to candidate.
  - `tests/script_quality/` (25 deterministic consistency tests).
- **Contract shape.**
  - 17 hard invariants in 7 hard gates: factual grounding, epistemic integrity, temporal/state integrity, spoiler discipline, necessary coverage, output integrity, request compliance.
  - One failure taxonomy (parent/subtype) that keeps every provisional category and places all 8 H6b residual families as subtypes.
  - Four severity levels defined by narrative impact; "material" means HIGH or CRITICAL.
  - 8 soft narrative dimensions judged for appropriateness under a Narrative Profile, never averaged with gates.
  - Verdicts FAIL / REVIEW_REQUIRED / PASS / PASS_WITH_MINOR_EDITS, decided by gates first, then usability and edit cost.
  - Length, style, tone and spoiler mode are Narrative Profile or request constraints, not universal standards.
- **Validator evidence (history, not part of the standard).** H1, H2, H6: PARTIALLY_SUPPORTED. H6b: SUPPORTED as a narrow comparative claim, with 22 of 33 reference issues still missed. H7: Stage A development evidence only (RUN_0010 strict mechanical contract PASS); Stage B not executed; confirmatory verdict NOT_EVALUATED.
- **Consequence recorded in the contract.** In v0 the semantic gates need a human audit; absence of automated findings is not a pass.
- **Disclosed limitations.** One story and early controlled runs; Project Owner reviews still pending; the rubric has not yet been exercised by a human reviewer on a real script; no calibrated automatic thresholds; coverage is defined conceptually only.
- **Recommendation.** READY_FOR_M1_CONTRACT_FREEZE_REVIEW. The contract is not frozen. `DECISIONS.md`, `ROADMAP.md` and all frozen M2 artifacts are unchanged. M3 has not started.

## Next Candidate

Orchestrator review of the Script Quality Contract v0 candidate and a freeze decision. No M3 work before that, unless the roadmap dependency is explicitly amended by a future decision.
