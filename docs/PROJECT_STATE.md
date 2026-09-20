# Project State

## Current Milestone

M1 — Script Quality & Narrative Contract

## Current Status

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

Private chunk text, probes, and review sheets remain LOCAL_ONLY. No LLM / embedding / retrieval external API performed.

## Next Candidate

Human review of revised validation draft using `.local/story_integration/otonari_30ch/M1_30CH_P_REPAIR/revised_human_review_packet.md`, `revised_draft_probes.yaml`, and `revised_source_gold_audit.jsonl`. Sign off on primary probes and disposition auxiliary/deferred candidates before final fixture freeze. Do not start evaluation (Task Q) before human review approval is completed.


