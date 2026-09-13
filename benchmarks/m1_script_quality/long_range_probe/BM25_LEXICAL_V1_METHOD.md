# BM25_LEXICAL_V1 Methodology

## Purpose
This baseline evaluates the raw performance of a deterministic lexical retriever against the `LONG_RANGE_PROBE_V1` benchmark. It answers the question: "How far can a simple deterministic lexical retriever go before we introduce embeddings, reranking, graph memory, or LLM-based retrieval?" 
It is a transparent, zero-cost, fully local baseline.

## Retriever Parameters
- **Algorithm**: Standard BM25
- **k1**: 1.2
- **b**: 0.75
- **IDF Formula**: `ln(1 + (N - df + 0.5) / (df + 0.5))`
- No parameter search or tuning against the benchmark was performed.

## Tokenizer: JP_SIMPLE_LEXICAL_V1
- Texts undergo Unicode NFKC normalization.
- Latin text is converted to lowercase (`casefold()`).
- Contiguous sequences of Latin letters and digits form word tokens.
- Japanese scripts (Hiragana, Katakana, CJK Unified Ideographs) emit character unigrams and bigrams.
- Whitespace and punctuation are ignored.
- No stopword lists, morphological analyzers (e.g. MeCab), synonym expansion, or stemming are used.

## Zero-Score Policy
A chunk is only retrievable if its BM25 score is strictly greater than `0`. If no candidate achieves a positive score, the retrieval list is empty.

## Deterministic Tie-Breaking
In the event of exactly equal positive scores, candidates are ranked deterministically by their `chunk_id` ascending.

## Retrieval Modes
1. **CUTOFF_FILTERED** (Primary Baseline): Only chunks with `chapter_number <= cutoff_chapter` are candidate for ranking. This ensures zero spoiler violations and correctly tests retrieval within the boundaries of the story's temporal progression.
2. **GLOBAL_DIAGNOSTIC** (Diagnostic Only): All chunks in the corpus are candidates, completely ignoring the temporal boundary. This helps identify if a "retrieval failure" in the filtered mode was actually just the retriever naturally finding future evidence that was excluded by the temporal safety filter.

## Metrics
- **K values**: 1, 3, 5, 10
- **Hit@K**: 1 if at least one required gold chunk is in the top K.
- **Required Evidence Recall@K**: Proportion of required gold chunks found in the top K.
- **Full Evidence Success@K**: 1 if all required gold chunks are in the top K.
- **MRR (Mean Reciprocal Rank)**: 1 / rank of the first required gold chunk (0 if not retrieved).
- **Spoiler Violation Rate@K**: Proportion of probes where the top K contains any chunk from `chapter_number > cutoff_chapter`.

Aggregation is performed using Macro-Averaging across the 15 probes globally, and also broken down by the 5 benchmark categories.

## Non-Goals
This baseline explicitly avoids:
- OpenAI / Gemini API calls
- LLM query rewriting or judging
- Dense embeddings or vector databases (e.g. FAISS)
- Graph traversal or Neo4j
- Entity extraction or Story Brief generation
- Prompt engineering

## Privacy
- Raw story text, questions, expected answers, and facts remain fully local.
- No private storyline content is included in the tracked methodology or aggregate metrics files.
