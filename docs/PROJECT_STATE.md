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
- Diversity diagnostics: mean_unique_chapters_top10 = 7.66, mean_pairwise_similarity_top10 = 0.906, mean_query_relevance_top10 = 0.781
- Interpretation: MMR effectively diversified the retrieved evidence set, but this diversity-aware selection did not improve evidence-set recovery. In particular, Full Evidence Success@10 remained 20% and Hit/Recall actually dropped compared to ordinary dense scoring. This negative result suggests that redundancy alone is unlikely to explain the missing evidence. The bottleneck requires richer query intent matching rather than just diversifying the single-query candidate space.

Private chunk text, probes, and embeddings remain LOCAL_ONLY. No LLM / embedding / retrieval external API performed.

## Next Candidate

Review DENSE_E5_MMR_V1 evidence. Since redundancy removal did not solve evidence coverage, the likely next experiment is deterministic query decomposition / multi-query retrieval.
