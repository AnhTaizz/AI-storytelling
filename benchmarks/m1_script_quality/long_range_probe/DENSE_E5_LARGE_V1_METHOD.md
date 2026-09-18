# DENSE_E5_LARGE_V1 Methodology

## Purpose
This is TASK M1-30CH-K, a controlled model-capacity experiment. M1-30CH-J classified the
remaining failure of `DENSE_E5_SMALL_V1` (F) as `DEEP_RELEVANCE_BOTTLENECK`. Of the 15 required
evidence units that F misses in Top-10, 9 (60%) rank beyond 20. G (windowing), H (MMR) and
I (multi-query RRF) did not raise Full Evidence Success@10.

This experiment replaces **only** the encoder with a larger model from the same family:
`intfloat/multilingual-e5-small` → `intfloat/multilingual-e5-large`.

It was frozen **before** the first scored execution. A negative result is valid and will not be rescued.

## Hypothesis
Increasing encoder capacity within the multilingual-E5 family improves the relevance ranking of
long-range required evidence. In particular, it moves some of the evidence that J found deep in
F's ranking (F rank > 20) into a Top-20 candidate pool, and raises Recall@10 and Full Evidence Success@10.

## Reference Baseline F
`DENSE_E5_SMALL_V1` is the primary scientific control:
- committed aggregates in `DENSE_E5_SMALL_V1_RESULT.yaml`;
- LOCAL detailed ranking `DENSE_E5_SMALL_V1/cutoff_filtered_per_probe.jsonl`. Its SHA-256 must
  match the result file. F is never reconstructed or approximated.

G, H and I are **not** comparison baselines, because they changed additional retrieval behavior.

## Frozen Corpus and Benchmark
The authoritative source is `LONG_RANGE_PROBE_V1_FREEZE.yaml`, and each value is verified mechanically before running:
- corpus fingerprint: `corpus_fingerprint_sha256`, checked against the chunk records;
- passage contract: `OTONARI_LOCAL_PASSAGE_V1 / PARAGRAPH_PACK_V1`, with `chunks_jsonl_sha256` checked;
- benchmark: `LONG_RANGE_PROBE_V1`, status `FROZEN`, `probe_count = 15`, with `probe_file_sha256` checked.

Any mismatch stops the experiment. No probe, gold label, cutoff or chunk is modified.

## Model Identity (immutable)
| Field | Value |
|---|---|
| model_id | `intfloat/multilingual-e5-large` |
| model_revision (HF commit) | `3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3` |
| weight file | `model.safetensors` (2,239,611,368 bytes) |
| weight SHA-256 | `020afdebf2762b29fcaf286629a96c3b3b65af241f6a08226b1cfee60a21def6` |
| tokenizer file | `tokenizer.json` (XLM-RoBERTa SentencePiece tokenizer) |
| tokenizer SHA-256 | `62c24cdc13d4c9952d63718d6c9fa4c287974249e16b7ade6d5a85e7bbb75626` |
| embedding dimension | 1024 (verified at load) |
| execution device | CPU, fp32 full precision |

The revision was resolved from the Hub once, before scoring. The weight and tokenizer hashes are
the Hub's LFS SHA-256 values for that revision. Before loading the model, the runner recomputes
SHA-256 over the local snapshot files and stops on any mismatch. Library versions
(`sentence-transformers`, `transformers`, `torch`) are recorded in the result.
No quantization and no reduced precision are used.

## Retrieval Contract (identical to F except the model)
- **Representation**: one embedding per original parent chunk (PARAGRAPH_PACK_V1, 97 chunks). No G windows.
- **Query**: `query: <question>`, encoded one query per call, as in F.
- **Passage**: `passage: <passage text>`.
- **Max sequence length**: 512 tokens. Longer inputs are truncated by the model's default behavior, as in F.
- **Pooling**: the model's standard sentence-transformers modules (E5 mean pooling), the same path F uses.
- **Normalization**: `normalize_embeddings=True` (unit vectors).
- **Similarity**: dot product of unit-normalized embeddings (cosine).
- **Tie-break**: `chunk_id` ascending.
- **Batching**: passages are encoded with `batch_size = 4` to fit memory. This is
  infrastructure only; retrieval semantics are unchanged.
- No MMR, query decomposition, RRF, reranking, hybrid, graph or LLM stages are used.

## Cutoff Semantics
1. **CUTOFF_FILTERED** (primary): candidates with `chapter_number > cutoff_chapter` are excluded before ranking.
2. **GLOBAL_DIAGNOSTIC** (secondary): all 97 chunks are candidates. This mode measures natural spoiler leakage.

## Metrics
The metric definitions are identical to F. For K = 1, 3, 5, 10 they are Hit@K, Required
Evidence Recall@K, Full Evidence Success@K and Spoiler Violation@K; MRR is also reported.
Values are macro-averaged overall and per category.

The primary comparison is K vs F on CUTOFF_FILTERED, with deltas computed as K − F. The primary
metrics are Hit@10, Recall@10, Full Evidence Success@10 and MRR. F values are read from the committed F result.

## J Rank-Shift Diagnostic
The failure population is rebuilt mechanically from frozen gold plus the verified F ranking;
no chunk IDs are hard-coded. It must reproduce the committed J values: 35 required units,
15 F Top-10 misses, a missed-rank distribution of 6 / 6 / 3 / 0 (11–20 / 21–50 / >50 / missing),
and J's F completeness curve. Otherwise the experiment stops.

For each of the 15 units, the diagnostic records `f_rank`, `k_rank`, `rank_delta = f_rank − k_rank`
(positive means improved), `f_bucket` and `k_bucket`. This table stays local. Published aggregates:
- the number of units whose rank improved, stayed the same or worsened;
- the counts for F > 10 → K ≤ 10, F > 20 → K ≤ 20 and F > 50 → K ≤ 50;
- median F rank and median K rank;
- the distribution of K ranks for the same 15 units: 1–10, 11–20, 21–50, >50, missing
  (the missing count is verified, not assumed).

## Completeness Diagnostic
Required Evidence Recall and Full Evidence Success are computed from the K ranking at depths 10,
20, 30 and 50. They are compared with the F curve read from the committed J result. These are
diagnostic depths, not new baselines.

## Truncation Diagnostic
The result reports `query_truncation_count` and `passage_truncation_count` (inputs longer than 512
tokens including special tokens) under the E5-large tokenizer, next to F's committed counts.
Truncation is recorded, not fixed; G already tested windowing.

## Frozen Interpretation Rule
All deltas are K − F on CUTOFF_FILTERED. "Deep rescues" is the number of J-population units with
F rank > 20 and K rank ≤ 20.
- **SUPPORTED**: Recall@10 improves **and** Full Evidence Success@10 improves **and**
  ΔHit@10 ≥ −0.10 **and** deep rescues ≥ 1.
- **PARTIALLY_SUPPORTED**: not SUPPORTED, but Recall@10 improves **or** Full Evidence Success@10
  improves **or** deep rescues ≥ 3.
- **NOT_SUPPORTED**: Recall@10 does not improve **and** Full Evidence Success@10 does not improve
  **and** deep rescues < 3.
- **NOT_EVALUABLE**: any critical gate fails (benchmark integrity, F artifact integrity, J
  population reconstruction, model identity, determinism, privacy).

The verdict is computed by `interpret_verdict()` in code. The rule does not change after results are known.

## Determinism
The complete experiment runs twice, and the model is loaded fresh for each run. After runtime-only
fields are removed, the following must be identical: the aggregate metrics, the CUTOFF and GLOBAL
ranking hashes, the rank-shift table hash, the source hashes and the model identity. Otherwise
`deterministic_reproduction_status: FAIL` and the verdict is `NOT_EVALUABLE`.

## Privacy
The following stay in `.local/story_integration/otonari_30ch/DENSE_E5_LARGE_V1/`: questions,
answers, chunk text, chunk IDs, probe IDs, embeddings, full rankings and the per-unit rank-shift table.
The public result holds only aggregates, model identity and hashes. The runner scans the public
payload for private strings, the chunk-ID pattern and probe-ID patterns before writing it.

## Non-Goals
This experiment does not try other models (E5-base, E5-large-instruct, BGE-M3, Jina, GTE,
E5-Mistral, API embeddings), windowing, MMR, multi-query, RRF, reranking, hybrid retrieval,
graph or structured memory, LLM query rewriting, parameter tuning or metric changes. It also does
not run a GPU execution.
