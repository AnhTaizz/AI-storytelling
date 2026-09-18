# M_FAILURE_MODE_DIAGNOSTIC_V1 Methodology

## Purpose
This is TASK M1-30CH-N, a **diagnostic, not an intervention**. No model is loaded, BGE and E5 are
not run, nothing is reranked and no ranking changes. It reads only the artifacts that
M1-30CH-M (`BGE_RERANKER_V2_M3_TOP30_V1`) already produced.

M raised Hit@10, Recall@10 and MRR over K, but Full Evidence Success@10 stayed at 0.2667. Only some of the
candidate-complete probes (all required evidence inside frozen K Top-30) became fully successful.
Question: **why do candidate-complete probes still fail Full Evidence Success@10 after BGE reranking?**

The analysis separates four possible explanations: (1) required evidence sits just outside Top-10;
(2) it sits much lower in Top-30; (3) the reranker moved it down relative to K; (4) the required chunk
was exposed to the 512-token passage truncation contract.

This document was written before any diagnostic numbers were computed.

## Inputs and Integrity Gates
Only existing LOCAL artifacts are used:
- the frozen probes (`LONG_RANGE_PROBE_V1/probes.yaml`) and chunks (`PARAGRAPH_PACK_V1/chunks.jsonl`),
  both checked against the freeze file;
- K's CUTOFF_FILTERED ranking, checked against `DENSE_E5_LARGE_V1_RESULT.yaml`;
- M's `reranked_per_probe.jsonl`, `required_evidence_transitions.jsonl`, `probe_transitions.jsonl`
  and `pair_scores.jsonl`, each checked against `BGE_RERANKER_V2_M3_TOP30_V1_RESULT.yaml` `detailed_results_sha256`.

The analysis must mechanically reproduce the following; any mismatch stops it:
- 15 probes and 35 required units;
- M's `candidate_complete_probes` and reranked full-success probes;
- every M RERANKED overall metric, recomputed from `evaluated_ranking`;
- M's Top-10 transition counts;
- M's `passage_truncation_count`, recomputed from the recorded `passage_tokens`.

## Populations
- **Candidate-complete**: every required unit is in the probe's frozen K Top-30.
- **CANDIDATE_COMPLETE_FAILURE**: a candidate-complete probe whose required units are not all in M's reranked Top-10.
  The size of this population is derived from the data, not assumed.
- **Missing required units**: required units of failure probes with M rank > 10. Because these probes are
  candidate-complete, every missing unit should rank between 11 and 30. Any unit above 30 or absent
  indicates an artifact inconsistency and stops the analysis.
- **Promoted required units**: required units of failure probes with M rank ≤ 10. They are the comparison group.

## Per-Unit Quantities
- `k_rank` and `m_rank` are exact 1-based ranks; `rank_delta = m_rank − k_rank` (negative means the reranker moved the unit up).
- `m_score` is the unit's recorded M reranker logit. `m_rank10_score` is the logit of the unit ranked 10th by M
  in that probe.
- `score_gap_to_top10 = m_rank10_score − m_score`. It is ≥ 0 for missing units and may be ≤ 0 for promoted units.
  Logits have no calibrated meaning, so no semantic threshold is applied; only min, median, mean and max are reported.
- `passage_tokens` is read from `pair_scores.jsonl`, as recorded during M scoring, with no re-tokenization.
  **TRUNCATION_EXPOSED** means `passage_tokens > 512`, M's `passage_max_length`, so the scored pair saw only the
  first 512 passage tokens.

## Rank Buckets
Missing units are bucketed as 11–15, 16–20 or 21–30. Boundary tests cover ranks 10/11, 15/16, 20/21 and 30.

## Descriptive Probe Labels (not verdicts)
- `NEAR_BOUNDARY_ORDERING`: every missing unit ranks 11–15.
- `MID_POOL_ORDERING`: at least one missing unit ranks 16–30.
- Independent flag `TRUNCATION_EXPOSED`: at least one missing unit has `passage_tokens > 512`.

The label and the flag combine freely, and they are not a causal diagnosis.

## Descriptive Summary Rules (frozen before computing)
- **Near-boundary dominant**: at least two-thirds of missing units rank 11–15.
- **Truncation enrichment**: the missing units' truncation-exposed fraction is compared with the
  promoted units' fraction in the same probes. A difference of at least +0.20 is reported as
  "associated with truncation exposure", and anything smaller as "no clear enrichment in truncation exposure".
  The reference rate for all M pairs (367/450) is also reported. Sample sizes are small, so this is descriptive only.

## Interpretation Limit (mandatory)
The current benchmark labels the evidence-bearing **chunk**, not the exact evidence **token span**.
This diagnostic can therefore tell whether a failed required chunk was truncated by the M pair contract.
It **cannot** tell whether the gold evidence itself was in the truncated tail. The result uses the
term `TRUNCATION_EXPOSED` and never "truncation caused"; no evidence spans are invented.

## Determinism and Privacy
The analysis runs twice. The public aggregate, the SHA-256 of `missing_required_units.jsonl` and
`failure_probes.jsonl`, and the source hashes must all be identical; otherwise the diagnostic is invalid.
Per-unit and per-probe rows (probe IDs, chunk IDs, ranks, scores, token counts) stay in
`.local/story_integration/otonari_30ch/M_FAILURE_MODE_DIAGNOSTIC_V1/`. The public result is aggregate-only
and is scanned for private strings, chunk-ID patterns and probe-ID patterns before it is written.
