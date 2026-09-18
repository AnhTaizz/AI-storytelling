# K_RANK_TRANSITION_DIAGNOSTIC_V1 Methodology

## Purpose
This is TASK M1-30CH-L. It is a diagnostic only: it adds no retrieval method, runs no model and
re-runs no F or K retrieval. It reads the frozen CUTOFF_FILTERED rankings of `DENSE_E5_SMALL_V1` (F)
and `DENSE_E5_LARGE_V1` (K) and explains K's mixed result: higher MRR and Full Evidence
Success@10, but lower Hit@10 and an almost unchanged Recall@10.

Question: **is the remaining failure mostly Top-10 ordering among candidates K already
retrieves, or is a significant population still deep under K?**

## Inputs and Integrity Gates
| Source | Integrity reference |
|---|---|
| `LONG_RANGE_PROBE_V1/probes.yaml` (gold) | freeze `probe_file_sha256`, status `FROZEN`, 15 probes |
| `PARAGRAPH_PACK_V1/chunks.jsonl` | freeze `chunks_jsonl_sha256` |
| F `DENSE_E5_SMALL_V1/cutoff_filtered_per_probe.jsonl` | `DENSE_E5_SMALL_V1_RESULT.yaml` `detailed_results_sha256` |
| K `DENSE_E5_LARGE_V1/cutoff_filtered_per_probe.jsonl` | `DENSE_E5_LARGE_V1_RESULT.yaml` `detailed_results_sha256` |

The population must be 15 probes and 35 required evidence units. The computed F and K Recall@10,
Hit@10 and Full Evidence Success@10 must reproduce the committed results. Any mismatch stops the analysis.

## Unit of Analysis
A unit is one pair of (probe, required evidence chunk); all 35 units are analyzed. Ranks are exact and 1-based in
each stored ranking; an absent chunk is `MISSING`, which is verified rather than assumed.

Buckets: `TOP_10` (1–10), `NEAR_11_20`, `MID_21_30`, `MID_31_50`, `DEEP_GT_50`, `MISSING`.

Transition types:
| Type | Rule |
|---|---|
| `STAY_TOP10` | F ≤ 10 and K ≤ 10 |
| `F_TOP10_LOST_BY_K` | F ≤ 10 and K > 10 |
| `K_TOP10_GAIN_FROM_F` | F > 10 and K ≤ 10 |
| `STAY_OUTSIDE_TOP10` | F > 10 and K > 10 (detailed buckets are kept) |

## Populations
- **F Top-10 lost** (F ≤ 10, K > 10): K destinations in 11–15, 16–20, 21–30, 31–50, >50 or missing;
  median F rank; median and mean K rank; fraction still within K Top-20, Top-30 and Top-50.
- **K Top-10 gain** (F > 10, K ≤ 10): F origins in 11–20, 21–30, 31–50, >50 or missing; median F and K rank.
- **Remaining deep under K**: units with K > 20, reported separately for K > 30 and K > 50. For each:
  count, F and K bucket distributions, median ranks and categories. Categories are descriptive only.

## Probe-Level Transitions
For each probe (kept locally): required count, required units in Top-10 under F and K, Hit@10,
Full Success@10 and worst required rank. Hit transitions are `HIT_STABLE`, `HIT_GAINED` or
`HIT_LOST`, and full-success transitions are `FULL_SUCCESS_STABLE`, `FULL_SUCCESS_GAINED` or `FULL_SUCCESS_LOST`.
"Stable" covers both stayed-true and stayed-false; both counts are reported. Only aggregate counts are published.

## Raw Unit Count vs Macro Recall
The analysis reports the raw number of required units in Top-10 for F and K, and macro Recall@10 computed
independently. The two statistics differ because each probe contributes equally to macro recall,
while probes require different numbers of units (2 or 3). This section is explanatory only.

## Candidate-Access Diagnostic
From the frozen K ranking (and F for reference), at depths N = 10, 20, 30, 50: probes with at least one
required unit in the Top-N, probes with all required units in the Top-N, Recall@N and Full Evidence
Success@N. This measures **candidate access** only. It is not the performance of any reranker, since none
is tested, and no downstream stage can recover evidence missing from its candidate pool.

## Descriptive Classification Rule
Two conditions are computed:
- **ORDERING condition**: more than 50% of the F Top-10-lost units are still within K Top-20, **and**
  K Full Evidence Success@30 ≥ 0.50.
- **DEEP condition**: units with K rank > 30 make up at least 10% of all required units (≥ 4 of 35).

| ORDERING | DEEP | Classification |
|---|---|---|
| true | false | `ORDERING_CONSISTENT` |
| false | true | `DEEP_RELEVANCE_CONSISTENT` |
| true | true | `MIXED` |
| false | false | `MIXED_INCONCLUSIVE` |

**Disclosure.** These thresholds were written after K's committed result (its completeness curve and
F-miss rank distribution) and the M1-30CH-K post-hoc Top-10 gain and loss counts had been seen.
They were not pre-registered blind, so the classification is **descriptive only**. The underlying
counts are published so readers can apply other thresholds. No SUPPORTED or NOT_SUPPORTED verdict is produced.

## Determinism and Privacy
The analysis runs twice. The public aggregate, the SHA-256 of both local tables and the source hashes must
all be identical; otherwise `determinism_status: FAIL`. The per-unit and per-probe tables stay in
`.local/story_integration/otonari_30ch/K_RANK_TRANSITION_DIAGNOSTIC_V1/`. The public result is
aggregate-only and is scanned for private strings, the chunk-ID pattern and probe-ID patterns before it is written.
