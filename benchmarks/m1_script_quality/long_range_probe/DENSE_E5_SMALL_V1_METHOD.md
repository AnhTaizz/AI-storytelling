# DENSE_E5_SMALL_V1 Methodology

## Purpose
This baseline evaluates a small multilingual dense embedding model (`intfloat/multilingual-e5-small`) against the frozen `LONG_RANGE_PROBE_V1` benchmark. It answers whether semantic retrieval materially improves evidence recovery over BM25 on the 30-chapter Japanese corpus.

## Model Contract
- **Model**: `intfloat/multilingual-e5-small` via `sentence-transformers`
- **Device**: CPU (local inference only)
- **Max Sequence Length**: 512 tokens (default truncation applied)
- **Formatting**:
  - Queries are prefixed with `query: `
  - Passages are prefixed with `passage: `
- **Similarity**: Cosine similarity (dot product of unit-normalized embeddings). No arbitrary thresholds or calibrations are applied.
- **Tie Break**: If cosine similarity is identical, tie break deterministically by `chunk_id` ascending.

## Retrieval Modes
1. **CUTOFF_FILTERED** (Primary): Candidates with `chapter_number > cutoff_chapter` are excluded prior to similarity ranking. Spoiler violations are expected to be 0.
2. **GLOBAL_DIAGNOSTIC** (Diagnostic): All 97 chunks are candidates. Used to measure natural future-chapter retrieval and spoiler leakage.

## Metrics
- Identical to `BM25_LEXICAL_V1` (Hit@K, Recall@K, Full Evidence Success@K, MRR, Spoiler Violation Rate@K).
- Aggregated via macro-averaging globally and across the 5 probe categories.

## Non-Goals
This baseline tests pure semantic embedding retrieval. It explicitly avoids:
- APIs (OpenAI, Gemini)
- Graph traversal / Neo4j
- Hybrid retrieval (Lexical + Semantic)
- Cross-encoder reranking
- Query rewriting / LLM interventions

## Privacy and Reproducibility
- Execution is fully deterministic (`model.eval()`, fixed seed). Two runs must yield exact binary/hash reproduction.
- Embeddings and detailed retrieval rankings remain strictly local. No private chunk text or questions are committed.

## Model Identity and Environment
- **Model Revision**: Frozen to exact Hugging Face snapshot SHA: `614241f622f53c4eeff9890bdc4f31cfecc418b3`
- **Model Weight Identity**: Verified by calculating SHA-256 over `model.safetensors` from the snapshot (`1a55775f53449dac10a2bcbc312469fac40b96d53198c407081a831f81c98477`).
- **Execution Target**: Explicitly `cpu` only (to eliminate CUDA-specific floating-point non-determinism).
- **Environment**: Tracked plain-string dependency versions for `sentence-transformers`, `transformers`, and `torch` in results yaml.
- **Reproducibility Contract**: Any reproduction attempt must run two back-to-back scoring passes on the local benchmark. Both runs must generate exactly identical detail and aggregate JSON/YAML structures (ignoring minor runtime measurements). Missing or differing hashes result in a mechanical FAIL.
