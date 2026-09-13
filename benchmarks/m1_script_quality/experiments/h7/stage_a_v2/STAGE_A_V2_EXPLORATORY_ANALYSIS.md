# H7 V2 Stage A Exploratory Analysis

## Purpose
This document presents the Stage A exploratory signal for the H7 V2 format-hardening rerun (RUN10). This analysis independently maps the corrected gold-blind candidate union against the frozen RUN3 reference to derive developmental metrics.

**CAUTION: Stage A exploratory signal only.**
- This is evaluated on the same RUN3 development instance used for prior iterations.
- This represents a single semantic attempt.
- Strict machine context isolation cannot be independently verified at this stage.
- There is NO holdout evidence presented here.
- Stage B is still required for confirmatory evaluation.

## Provenance
- **Reference**: `H6B_RUN3_REFERENCE_V1`
- **Candidate Union**: Corrected H7 V2 Stage A gold-blind union freeze
- **Candidate Commit**: `a21da38dfc644161ce58b651326f38820f393ef0`
- **Mechanical Validity**: RUN10 strictly passed the frozen V2 output contract.
- **Mapping Model**: No external semantic model was invoked for this mapping; it was performed deterministically using explicit, authorized reference alignment rules.
- **Reference Provenance Note**: Gold content itself was verified unchanged by Git blob identity. The historical freeze-declared SHA and canonical Git-byte SHA differ, but the exact cause/byte-domain of the historical SHA is not established. This fix does not alter mapping or metrics.

## Baseline Metrics (RUN7 subset)
- **Predictions**: 9
- **Robust Gold Detected**: 11 (out of 33)
- **Precision**: 1.0000
- **Recall**: 0.3333
- **F1**: 0.5000
- **Unit Recall**: 0.4000 (8 / 20)

## H7 V2 Final Union Metrics (Corrected)
- **Predictions**: 12
- **Robust Gold Detected**: 14 (out of 33)
- **Precision**: 1.0000
- **Recall**: 0.4242
- **F1**: 0.5957
- **Unit Recall**: 0.4500 (9 / 20)

## Targeted Contribution
- **Targeted Raw Predictions**: 5
- **Deduplicated to Baseline**: 2
- **Unique Retained**: 3 (`E001`, `E002`, `E005`)
- **New Robust Gold Detected**: 3 (`G006`, `G008`, `G024`)

## Metric Deltas
- **Recall Absolute**: +0.0909
- **Precision Absolute**: 0.0000
- **F1 Absolute**: +0.0957
- **Unit Recall Absolute**: +0.0500
- **Precision Degradation Absolute**: 0.0000

## Discussion
The exploratory mapping indicates that the format-hardened H7 V2 rerun successfully captured additional robust gold issues without introducing any false positives on this development instance. The targeted pass identified 3 new robust gold issues (`G006`, `G008`, `G024`) not found by the baseline.

All predictions in the final union successfully matched robust gold issues, meaning there were 0 FP, 0 Sensitivity Only, and 0 Unresolved predictions in this evaluation. 

## Limitations
This is purely developmental exploratory evidence. A fresh, fully blind Stage B holdout run is required to confirm whether the H7 V2 protocol generalizes safely to unseen material.
