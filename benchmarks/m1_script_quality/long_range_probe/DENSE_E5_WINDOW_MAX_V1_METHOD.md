# DENSE_E5_WINDOW_MAX_V1 Methodology

## Purpose
This baseline evaluates if evidence recovery improves over `DENSE_E5_SMALL_V1` by removing passage truncation entirely. Parent chunks are deterministically chunked into overlapping windows of 448 tokens (with 64 token overlap), and parent-level relevance is aggregated via max-pooling over the windows.

## Model Identity and Environment
- **Model Revision**: Frozen to exact Hugging Face snapshot SHA: `614241f622f53c4eeff9890bdc4f31cfecc418b3`
- **Model Weight Identity**: Verified by calculating SHA-256 over `model.safetensors` from the snapshot (`1a55775f53449dac10a2bcbc312469fac40b96d53198c407081a831f81c98477`).
- **Execution Target**: Explicitly `cpu` only (to eliminate CUDA-specific floating-point non-determinism).
- **Environment**: Tracked plain-string dependency versions for `sentence-transformers`, `transformers`, and `torch` in results yaml.

## Window Contract
- **Max Model Tokens**: 512
- **Content Window Tokens**: 448
- **Content Overlap Tokens**: 64
- **Stride**: 384
- **Offset Generation**: Uses precise character offsets mapping token sequences back to the exact source string to prevent mid-character breakages.
- **Child Naming**: `[parent_chunk_id]_wXXXX` (1-indexed).

## Coverage Contract and Zero-Truncation
- Short parents yield a single window.
- Long parents yield overlapping sequential windows until full text coverage is achieved.
- All windows are explicitly verified to generate `<= 512` tokens inclusive of special tokens. Model truncation is strictly not relied upon.
- `window_truncation_count = 0` is a strict requirement for a successful run.

## Parent Max Aggregation
- **Query**: Prefixed with `query: `
- **Passage**: Each individual window text is prefixed with `passage: `
- Cosine similarity is computed between the query and all candidate windows.
- Each parent's final score is the `MAX` similarity across all of its child windows (`parent_score = max(score(window_i, q))`).
- **Tie Break**: If cosine similarity is identical, tie break deterministically by `parent_chunk_id` ascending.
- Ranking produces a list of unique parent chunks exactly comparable with earlier parent-level baselines.

## Cutoff Semantics
1. **CUTOFF_FILTERED**: Only parent candidates where `chapter_number <= cutoff_chapter` are allowed into the candidate pool. No child window of a forbidden parent participates. Spoiler leakage is zero.
2. **GLOBAL_DIAGNOSTIC**: All 97 original chunks are candidates. Used to measure natural future-chapter retrieval and spoiler leakage.

## Metrics
- Hit@K, Required Evidence Recall@K, Full Evidence Success@K, MRR, Spoiler Violation Rate@K (for K=1, 3, 5, 10).
- Metrics remain exactly parent-level to allow fair comparison against `DENSE_E5_SMALL_V1`.

## Reproducibility Contract
- Execution is fully deterministic.
- Any reproduction attempt must run two back-to-back scoring passes on the local benchmark. Both runs must generate exactly identical detailed window manifests and aggregate YAML structures (ignoring minor runtime measurements). Missing or differing hashes result in a mechanical FAIL.

## Privacy and Non-Goals
- Embeddings, window text, and detailed rankings remain strictly local. No private chunk text or questions are committed.
- **Non-Goals**: This experiment isolates passage truncation as the single variable. No graph databases (Neo4j), hybrid reranking (BM25+Dense), cross-encoders, LLMs, or multi-query expansions are introduced.
