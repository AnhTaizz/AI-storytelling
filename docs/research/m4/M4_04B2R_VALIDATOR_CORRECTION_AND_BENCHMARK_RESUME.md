# M4-04B2R — Validator correction and development benchmark resume

Status: **development benchmark complete; no lockable extractor**.

## Historical interruption

The original M4-04B2 protocol and Commit A remain valid historical evidence. The first live case exposed a robustness defect: malformed model-returned passage spans could pass the envelope schema and then make the frozen V1 contract validator raise `KeyError`. Both successful provider responses for `P0/M4DEV_01` remain immutable and were never regenerated.

## Versioned correction

Snapshot V1 was not edited. `M4_EXTRACTION_VALIDATION_GUARD_V1` performs only the minimum fail-closed shape checks needed before calling the frozen validator. It neither normalizes nor fills model output. Safe inputs are delegated unchanged; malformed inputs become explicit structural failures. Snapshot V2 binds V1 unchanged plus the guard, guarded evaluator and regression tests.

The V1-to-V2 impact analysis used synthetic/public calibration fixtures only. Results were identical wherever V1 completed normally. The known malformed fixture raises in V1 and deterministically fails structure in V2.

## Resume chronology

1. Commit A2 `1b3f8d31b9343798b26cbb5e38d1cb747e9a9eca` was pushed before any new provider request.
2. The historical primary and repair were revalidated offline as structural failures; their provider rerun count stayed zero.
3. Execution resumed at `P0/M4DEV_02`, then ran P1 from case 01.
4. All 28 candidate/case outcomes became terminal and Commit B `3e231cae20c0bd342ef75082c1dc36c667b88d42` was pushed.
5. Only then was M4-02 DEV gold opened. Provider operations after gold access were zero.

## Development outcome

P0 had 14/14 structural failures. P1 had six runtime-structural predictions, but source-exact evaluation left only two L0-valid cases. Neither candidate achieved a full canonical case success. Four unmatched P1 assertions in an UNCERTAIN case were adjudicated under the existing ontology as equivalent representations; no unsupported assertion was found and nothing remained pending.

The original lexicographic rule selects P1. The safety gate nevertheless fails because not all selected predictions satisfy L0 structural/canonical conformance. Consequently no `M4_EXTRACTION_BASELINE_V1.json` or extractor lock was created.

## Research boundary

This result is development-only. M4-04C and M5 were not started. Holdout input and holdout gold remain unopened, holdout predictions were not run, and contamination remains clean.

