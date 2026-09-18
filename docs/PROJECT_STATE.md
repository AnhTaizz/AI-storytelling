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

Private chunk text, probes, and embeddings remain LOCAL_ONLY. No LLM / embedding / retrieval external API performed.

## Next Candidate

M1-30CH-L found the post-K failure pattern mostly consistent with Top-10 ordering: all of K's Top-10 losses are within K Top-30, and complete evidence is available within K Top-30 for 12 of 15 probes. A controlled reranking experiment over the frozen K Top-30 candidate pool is now a plausible next candidate. It would keep the K ranking, candidate set, benchmark and metrics fixed, and its method would be frozen before scoring. Its ceiling is set by candidate access: at most 12 of 15 probes can reach full evidence at Top-30. The 3 units beyond K rank 30 remain an unresolved relevance problem that reranking cannot address. Not implemented. Graph memory is not justified by this result.
