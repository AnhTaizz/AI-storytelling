# BGE_RERANKER_V2_M3_TOP30_V1 Methodology

## Research Question
This is TASK M1-30CH-M. M1-30CH-L found the failure pattern of `DENSE_E5_LARGE_V1` (K) to be mostly
consistent with Top-10 ordering. Every required unit that K pushed out of F's Top-10 is still within
K Top-30, complete evidence is available within K Top-30 for 12 of 15 probes, and only 3 of 35 units
rank beyond 30.

**Question: can a multilingual cross-encoder reranker improve the ordering of the frozen K Top-30 candidate pool?**

This is not a candidate-generation experiment: the candidate set is frozen, and the reranker only reorders it.
This document was frozen **before** the first scored execution. A negative result is valid and will not be rescued.

## Candidate Source (frozen)
- **Source**: `DENSE_E5_LARGE_V1`, CUTOFF_FILTERED detailed ranking (LOCAL). Its SHA-256 must match
  `DENSE_E5_LARGE_V1_RESULT.yaml`. There is no re-retrieval and E5-large is not run again.
- **Candidate depth**: exactly **30**, fixed from the M1-30CH-L evidence. It is not a tunable
  hyperparameter, and no other depth (20, 50) is tested.
- **Per probe**: the first 30 chunk IDs of the verified K ranking. If a probe's eligible pool has fewer
  than 30 chunks, its whole pool is used, without padding or borrowing. The runner checks this
  mechanically; the smallest pool observed before scoring has exactly 30 chunks.
- **Candidate-set gate**: for every probe, `set(before_top30) == set(after_rerank)`, the count is
  `min(30, pool_size)` and there are no duplicates. A violation makes the result NOT_EVALUABLE.
- **Evaluated ranking**: the reranked Top-30 followed by the unchanged K ranking beyond 30 (used for MRR).
  Metrics at K ≤ 10 depend only on the reranked Top-30.

## Model Identity (immutable)
| Field | Value |
|---|---|
| model_id | `BAAI/bge-reranker-v2-m3` |
| model_revision (HF commit) | `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` |
| weight file | `model.safetensors` (2,271,071,852 bytes) |
| weight SHA-256 | `d9e3e081faff1eefb84019509b2f5558fd74c1a05a2c7db22f74174fcedb5286` |
| tokenizer file | `tokenizer.json` |
| tokenizer SHA-256 | `69564b696052886ed0ac63fa393e928384e0f8caada38c1f4864a9bfbf379c15` |
| architecture | `AutoModelForSequenceClassification`, 1 output logit (verified at load) |
| device / dtype | CPU / fp32 (no quantization, no GPU) |
| libraries | `transformers` and `torch` (versions recorded in the result); FlagEmbedding is not used |

The revision and hashes were resolved from the Hub before scoring. The runner recomputes SHA-256 over
the local snapshot files before loading and stops on any mismatch. No other reranker is used or compared.

## Pair Serialization (frozen)
- **Query**: the probe `question`, verbatim. **Passage**: the original parent chunk `text`, verbatim.
  Neither is summarized or translated. Gold labels, answers, categories and chapter numbers are never model input.
- **Token budgets**: the query is truncated to `query_max_length = 256` tokens and the passage to
  `passage_max_length = 512` tokens, independently, excluding special tokens.
- **Format**: the standard BGE / XLM-R cross-encoder pair `<s> query </s></s> passage </s>`, built
  explicitly as `[cls] + query_ids + [sep, sep] + passage_ids + [sep]` from the tokenizer's own special-token
  IDs. This follows the model card's `transformers` usage. The construction was verified to equal the
  tokenizer's native pair encoding on untruncated inputs before scoring. (Implementation note: an earlier
  launch used `prepare_for_model`, which transformers 5 no longer provides. It failed on the first pair
  and produced no scores; the token layout is unchanged.)
- **Scoring**: one pair per forward pass (batch size 1), so there is no padding and scores do not
  depend on batching. The score is the raw classification logit, with no sigmoid (sigmoid is monotonic
  and would not change the order).

## Tie-Break (frozen)
The primary order is reranker score descending. Exact score ties are broken by original K rank ascending,
then by `chunk_id` ascending.

## Metrics
The metric definitions are identical to F and K. For K = 1, 3, 5, 10 they are Hit@K, Required
Evidence Recall@K, Full Evidence Success@K and Spoiler Violation@K; MRR is also reported.
CUTOFF_FILTERED must keep zero spoiler violations.

The primary control is the **original K ranking**, whose metrics are recomputed and checked against the
committed K result before scoring. The primary comparison is reranked minus K on Hit@10, Recall@10,
Full Evidence Success@10 and MRR. F is historical context only.

## Candidate Ceiling (descriptive)
Computed from the frozen Top-30 pools: `candidate_complete_probes` are the probes with every required unit
in their pool. `candidate_complete_fraction` is that count over 15, and
`reranker_ceiling_utilization = reranked full-success probes / candidate-complete probes`.

## Transition Diagnostics
For every required unit, the transition from K Top-10 to reranked Top-10 is classified as `STAY_TOP10`,
`K_TOP10_LOST_BY_RERANK`, `RERANK_TOP10_GAIN_FROM_K` or `STAY_OUTSIDE_TOP10`.

L's `F_TOP10_LOST_BY_K` population (F ≤ 10, K > 10) is rebuilt from the F and K rankings and must
match L's committed count. The result reports how many of those units the reranker restores to Top-10.

Probe transitions are also reported: hit probes and full-success probes for K and for the reranked
ranking, with gained and lost counts. Per-unit detail stays local.

## Truncation Diagnostics
The result reports `query_truncation_count` (queries longer than 256 tokens) and
`passage_truncation_count` (passages longer than 512 tokens) over all scored pairs. Truncation is
recorded, not fixed.

## Frozen Verdict Rule
All deltas are reranked minus K, on CUTOFF_FILTERED at Top-10.
- **SUPPORTED**: ΔFull Evidence Success@10 > 0 **and** ΔRecall@10 > 0 **and** ΔHit@10 ≥ 0
  **and** more probes are full-successful at Top-10 than under K.
- **PARTIALLY_SUPPORTED**: not SUPPORTED, and at least one of ΔFull Evidence Success@10 > 0,
  ΔRecall@10 > 0 or ΔHit@10 > 0.
- **NOT_SUPPORTED**: ΔFull Evidence Success@10 ≤ 0 **and** ΔRecall@10 ≤ 0 **and** ΔHit@10 ≤ 0.
- **NOT_EVALUABLE**: any critical gate fails (input integrity, model identity, candidate equality,
  determinism, privacy).

The verdict is computed by `interpret_verdict()`, and the rule is not changed after scoring.

## Determinism
The complete experiment runs twice, and the model is loaded fresh each time. After runtime-only fields
are removed, the following must be identical: aggregate metrics, the reranked rankings and pair-score
file hashes, the transition-table hash, the source hashes and the model identity. Otherwise the verdict is NOT_EVALUABLE.

## Privacy
The following stay in `.local/story_integration/otonari_30ch/BGE_RERANKER_V2_M3_TOP30_V1/`: questions,
answers, story text, probe IDs, chunk IDs, pair scores, full rankings and per-unit transitions.
The public result is aggregate-only. The runner scans it for private strings, the chunk-ID pattern and
probe-ID patterns before writing it.

## Non-Goals
This experiment does not generate new candidates, run E5-large or any retriever again, compare
candidate depths, compare rerankers (gemma, MiniCPM, Jina, Cohere, LLM or API rerankers), rewrite
queries, window passages, fuse or hybridize rankings, add graph memory, tune parameters or change metrics.
