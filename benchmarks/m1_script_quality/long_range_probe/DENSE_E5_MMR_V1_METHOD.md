# DENSE_E5_MMR_V1 Methodology

## Purpose
This experiment tests whether deterministic diversity-aware selection (MMR) can improve retrieval of the complete evidence set without changing the embedding model, benchmark, chunking, or query. The research question is whether MMR over the existing dense candidate space improves Required Evidence Recall and Full Evidence Success by reducing redundant Top-K results.

## Model Identity and Environment
- **Model Revision**: Frozen to exact Hugging Face snapshot SHA: `614241f622f53c4eeff9890bdc4f31cfecc418b3`
- **Model Weight Identity**: Verified by calculating SHA-256 over `model.safetensors` from the snapshot (`1a55775f53449dac10a2bcbc312469fac40b96d53198c407081a831f81c98477`).
- **Execution Target**: Explicitly `cpu` only.
- **Parent Representation**: Identical to `DENSE_E5_SMALL_V1`. Queries prefixed with `query: `, passages prefixed with `passage: `. Chunk lengths up to 512 tokens.

## Relevance Control Gate
Before executing MMR, the pipeline strictly executes ordinary dense relevance scoring (pure cosine similarity, descending) to verify that the embeddings generated in this script reproduce the `DENSE_E5_SMALL_V1` benchmark exactly. If the metrics deviate, execution halts.

## MMR Contract
- **Formula**: `MMR_Score = lambda * relevance(d) - (1 - lambda) * redundancy(d, S)`
- **Relevance**: Cosine similarity between query and candidate.
- **Redundancy**: Maximum cosine similarity between candidate and any already-selected candidate in set S.
- **Lambda**: Frozen at `0.70`. No parameter sweeps or tuning allowed.
- **Selection**: Candidates are evaluated greedily. The candidate with the highest MMR score is added to the result set.
- **Tie Break**: Exact score ties are broken by `chunk_id` ascending.
- **Candidate Pool**: MMR operates over the complete eligible parent candidate set (not a prefiltered Top-N subset).

## Cutoff Semantics
1. **CUTOFF_FILTERED**: Only parent candidates where `chapter_number <= cutoff_chapter` are allowed into the candidate pool prior to relevance/MMR computation. Spoiler leakage is zero.
2. **GLOBAL_DIAGNOSTIC**: All 97 original chunks are candidates. Used to measure natural future-chapter retrieval and spoiler leakage.

## Metrics
- Hit@K, Required Evidence Recall@K, Full Evidence Success@K, MRR, Spoiler Violation Rate@K (for K=1, 3, 5, 10).
- **Diversity Diagnostics**:
  - Mean unique chapters in Top-3, Top-5, Top-10.
  - Mean pairwise cosine similarity among selected Top-10 documents.
  - Mean query relevance of Top-10 documents.

## Reproducibility Contract
- Execution is fully deterministic.
- Two consecutive executions are performed to verify exact binary reproducibility of all produced artifacts, rankings, and hash sums.

## Privacy and Non-Goals
- Embeddings and detailed rankings remain strictly local. No private chunk text or questions are committed.
- **Non-Goals**: This isolates single-query diversity selection. It explicitly excludes query rewriting, multiple generated queries, LLM calls, graph databases, BM25+Dense hybrid, or cross-encoders.
