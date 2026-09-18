# MISSING_EVIDENCE_RANK_DIAGNOSTIC_V1 Methodology

## Purpose
This is TASK M1-30CH-J. It is a diagnostic, not a retrieval experiment: it adds no retrieval method,
computes no new embeddings and re-runs no retrieval.

`DENSE_E5_SMALL_V1` (F) reaches Hit@10 ≈ 93%, Recall@10 ≈ 57% and Full Evidence Success@10 = 20%.
G (windowing), H (MMR) and I (multi-query RRF) did not raise Full Evidence Success. This
diagnostic measures where the required evidence that F misses in its Top-10 actually ranks.

- **Primary question**: are the required chunks that F misses in its Top-10 just outside the
  Top-10, moderately deep, or deep in the ranking?
- **Secondary question**: did any of I's individual subqueries rank that missing evidence higher,
  even though RRF fusion failed overall?

This document was frozen before any diagnostic numbers were computed.

## Source Artifacts (LOCAL_PRIVATE, read-only)
| Source | File | Integrity reference |
|---|---|---|
| Benchmark gold | `LONG_RANGE_PROBE_V1/probes.yaml` | `LONG_RANGE_PROBE_V1_FREEZE.yaml` `probe_file_sha256` |
| Chunks (chapter metadata only) | `PARAGRAPH_PACK_V1/chunks.jsonl` | freeze `chunks_jsonl_sha256` |
| F ranking | `DENSE_E5_SMALL_V1/cutoff_filtered_per_probe.jsonl` | `DENSE_E5_SMALL_V1_RESULT.yaml` `detailed_results_sha256` |
| I fused ranking | `DENSE_E5_MULTIQUERY_V1/multiquery_cutoff_per_probe.jsonl` | `DENSE_E5_MULTIQUERY_V1_RESULT.yaml` `detailed_results_sha256` |
| I per-query rankings | `DENSE_E5_MULTIQUERY_V1/per_query_rankings.jsonl` | same |

If any artifact is missing or its SHA-256 does not match, the analysis stops. Rankings are never
approximated or regenerated.

## Population
- **CUTOFF_FILTERED only**, all 15 frozen probes.
- A **required evidence unit** is one pair of (probe, required evidence chunk).
- Gold labels are used only to look up ranks in the frozen rankings. They never change a ranking.
- Categories are used only for post-hoc descriptive reporting. With 3 probes per category, the
  per-category numbers are **descriptive, not statistically conclusive**.

## Rank Extraction
Ranks are exact and 1-based: the chunk's position in the stored ordered ranking, plus one. A chunk that
is absent from a ranking is `MISSING`. Both F and I rank every eligible chunk, so `MISSING` is
expected to be 0; the analysis checks this rather than assuming it.

For each unit:
- `f_rank`: rank in the F Q0 dense ranking.
- `i_fused_rank`: rank in the I RRF-fused ranking.
- `i_query_ranks`: rank in each I per-query ranking (`mode == CUTOFF_FILTERED`).
- `i_best_query_rank = min(i_query_ranks)`, and `i_best_query_index` is the lowest query index
  that achieves that minimum.
- Local only: `f_score`, `f_top10_boundary_score` (the score at rank 10) and
  `f_score_gap_to_rank10 = f_top10_boundary_score - f_score`, read directly from the F artifact.

## Frozen Rank Buckets
| Bucket | Rule |
|---|---|
| `TOP_10` | 1 ≤ rank ≤ 10 |
| `NEAR_MISS` | 11 ≤ rank ≤ 20 |
| `MID_RANK` | 21 ≤ rank ≤ 50 |
| `DEEP_RANK` | rank > 50 |
| `MISSING` | not present |

## Candidate Reachability (frozen wording)
These terms apply to units that F misses in its Top-10 (`f_rank > 10`):
- `SMALL_CANDIDATE_REACHABLE`: 11 ≤ F rank ≤ 20.
- `MEDIUM_CANDIDATE_REACHABLE`: 21 ≤ F rank ≤ 50.
- `DEEP`: F rank > 50.

Reported values:
- the fraction of missed units within Top-20 and within Top-50;
- the number of probes whose required evidence is entirely within Top-20, and within Top-50.

Reachability means only that a reranker working on that candidate pool would **have access** to
the gold evidence ("candidate-reachable"). It does not mean a reranker would succeed.

## Probe Completeness
For each probe, the analysis computes `required_count`, `required_in_top10`, `best_required_rank`
and `worst_required_rank`. A probe reaches Full Evidence Success@K exactly when
`worst_required_rank ≤ K`.

The **oracle completeness curve** gives Required Evidence Recall@K and Full Evidence Success@K for
K ∈ {10, 20, 30, 50}, read from the frozen F ranking. These are diagnostic measurements of an
existing ranking, not a new baseline. For K = 10 they must reproduce F's committed Recall@10 and
Full Evidence Success@10 (a consistency gate).

A secondary context statistic is also reported, because eligible pools differ in size with the
cutoff: `f_rank / eligible_pool_size` for the missed units.

## Multi-Query Diagnostic
For each unit with `f_rank > 10`:
- whether `i_best_query_rank` is lower than, equal to, or higher than `f_rank`;
- `f_rank > 10 AND i_best_query_rank <= 10`;
- `f_rank > 20 AND i_best_query_rank <= 20`;
- the **fusion-bottleneck condition**: `f_rank > 10 AND i_best_query_rank <= 10 AND i_fused_rank > 10`.

This separates two explanations for I's failure: (A) no subquery surfaced the missing evidence,
or (B) some subquery surfaced it but RRF fusion diluted it. No fusion variant is tested here.

## Frozen Classification Rule
The denominator is the set of units that F misses in its Top-10.
- **A — `SHALLOW_RANKING_BOTTLENECK`**: at least 70% of missed units have 11 ≤ F rank ≤ 20.
- **C — `DEEP_RELEVANCE_BOTTLENECK`**: more than 50% of missed units have F rank > 20
  (MISSING counts as > 20).
- **B — `MIXED_REACHABILITY`**: neither A nor C applies. (A and C cannot both hold.)
- **Flag D**: `fusion_bottleneck_signal = true` when at least 3 units meet the
  fusion-bottleneck condition. This flag can accompany A, B or C.

This diagnostic produces no SUPPORTED / NOT_SUPPORTED verdict.

## Determinism
The analysis runs twice in one invocation. The public aggregate (excluding runtime-only fields),
the SHA-256 of the local required-evidence table and the source-artifact hashes must all be identical
across the two runs. Otherwise `determinism_status: FAIL` and the result is invalid.

## Privacy
The per-unit table stays in `.local/story_integration/otonari_30ch/MISSING_EVIDENCE_RANK_DIAGNOSTIC_V1/`.
The public result contains only aggregate counts, fractions and hashes. It contains no questions,
answers, subqueries, chunk IDs, probe IDs, ranking arrays, story text or embeddings. The analysis
scans the public payload before writing it and stops if any private string appears.
