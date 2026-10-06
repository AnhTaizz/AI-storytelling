# M4 DEV3 P3 Evaluation Decision V1

Status: **LOCKED before any P3 DEV3 prediction exists** (M4-04B3H0).

Record: `benchmarks/m4_extraction/M4_04B3H0_DEV3_EVALUATION_DECISION_LOCK.yaml`.
Decision record SHA-256: `5826854dfe6828ebea67e0d4c089fbda148fcc89da9efc80f1afb244aa329735`.
Implementation: `tools/story_extraction/m4_04b3h0_dev3_decision_lock_v1.py`.

## Purpose

This note fixes how the blind DEV3 result of the locked P3 extractor will be judged. It was written before the DEV3 input was opened for prediction and before DEV3 gold was opened. Its only job is to prevent success criteria from being chosen after the result is known.

This task ran no prediction and no scoring. It opened no DEV3 package and no holdout artifact, and it made no provider call.

## What the record binds

| Item | Value |
|---|---|
| P3 canonical protocol SHA-256 | `f9cf1c25a21bb3bfc910b8e218c8dac9f032d67957f8d7cb58397134a0504bae` |
| DEV3 input SHA-256 | `47ae7c743065f8ff001f4db6a398df2edf1db094383b1fe2d0c3a05ab40c55c7` |
| DEV3 gold SHA-256 | `b5b2258d46608015ff60de2c660fba521029ff4716c7c1cc3b3735c55dfd34a9` |
| Cases | `DEV3_01` … `DEV3_10`, in that order, one candidate |
| Evaluation | `M4_EVALUATION_PROTOCOL_SNAPSHOT_V2`, entry point `evaluate_extraction_guarded_v1.py` |
| Protected extractor stack | P3 prompts, Draft V1.1 schema, compiler V1.1, predicate registry, runtime, durable executor, protocol builder, runner |

Case parameters come from the sealed gold package unchanged. The only permitted addition after gold opening is `adjudications`. Where a sealed case specification names no mode, `REAL_SOURCE` applies.

## Chronology

| Step | Requirement |
|---|---|
| A | P3 predictions run under the locked protocol |
| B | All 10 cases reach a terminal state |
| C | The prediction package and its SHA-256 are created |
| D | The public prediction lock is committed |
| E | The branch is pushed and the remote SHA is verified |
| F | Only then may DEV3 gold be opened |
| G | Zero provider or model calls after gold opening |

Any violated step gives **`PROTOCOL_INVALID`**. DEV3 then cannot support any progression claim.

## Safety gate

The gate is automatic. One failed check fails it and gives **`DEV3_SAFETY_FAIL`**, which bars holdout progression.

| Check | Origin |
|---|---|
| All 10 final predictions pass L0 with source-exact validation | B2 gate |
| `CRITICAL` unsupported count is 0 | B2 gate |
| `HIGH` unsupported count is 0 | B2 gate |
| `UNRATED` unsupported count is 0 | New, fail-closed |
| Pending adjudication count is 0 | New, fail-closed |
| No unresolved evaluation or protocol defect | B2 gate |
| No protocol violation | B2 gate |
| No provider or model call after gold opening | B2 gate |
| No holdout access | B2 gate |
| No change to the protected extractor stack after prediction lock | Task mandate |
| Transport execution invariants pass | B2 gate |

All eight conditions of the B2 gate are preserved. None is weakened.

**Why two checks were added.** All DEV3 gold is `COMPLETE_FOR_PROFILE`. For such gold the frozen evaluator records an unmatched prediction as `UNSUPPORTED_ASSERTION` with severity `UNRATED`, and treats it as material. The B2R gate counted only `CRITICAL` and `HIGH`, so an unrated claim could have passed it. The two added checks close that gap. They can turn a pass into a fail, never the reverse.

A terminal structural failure counts as an L0 failure for its case. Adjudication uses the existing Snapshot V2 states and severities, makes no provider or model call, and is published in full with the adjudicator kind.

## Decision labels

Rules apply in this order:

1. Any chronology step violated → `PROTOCOL_INVALID`.
2. Any safety check failed → `DEV3_SAFETY_FAIL`.
3. Otherwise → `DEV3_SAFE_BUT_COMPETENCE_REVIEW_REQUIRED`.

The scorer supplies observed facts only. `decide()` accepts no threshold, weight or policy, and it verifies the record hash on every call.

**`DEV3_HOLDOUT_ELIGIBLE` is never assigned automatically.** Only a separate, recorded Orchestrator decision may assign it. That decision needs a `DEV3_SAFE_BUT_COMPETENCE_REVIEW_REQUIRED` result first, may rely only on the metric table below, and must cite the decision record SHA-256.

## Competence: no numeric floor

The repository holds no prior normative competence threshold:

- The evaluation protocol defines "no single accuracy and no weighted combination".
- The extraction contract defines no threshold-based acceptance.
- The B2 selection rule only ranks two candidates against each other.
- The 10/10 gate of M4-04B3D3 was a structural gate of a migration diagnostic. DEV2 was never quality-scored.

No new floor is introduced either (`NEW_PRE_REGISTERED_DEV3_THRESHOLD: NOT_INTRODUCED`). No locked model output has yet been scored with non-zero recall, DEV3 has ten cases, and its gold is agent-drafted and not human-confirmed. A number chosen now would be arbitrary.

## Metric table to be published

Every case is published, in the locked order, with every metric. A metric that does not apply is reported as null. Nothing may be hidden or excluded.

| Group | Names (as in the repository) |
|---|---|
| Primary indicators | `full_canonical_case_success_count`, `full_canonical_case_success_rate`, `assertion_recall`, `assertion_recall_mean`, `evidence_grounding_recall_mean` |
| Per case | `assertion_precision`, `assertion_recall`, `evidence_grounding_precision`, `evidence_grounding_recall`, `epistemic_accuracy`, `evidence_role_accuracy`, `referent_resolution_accuracy`, `unsupported_assertion_count`, `unsupported_assertion_rate`, `gold_unmatched_pending_adjudication` |
| Per case, other | `l0_structural_validity`, `case_outcome`, `full_canonical_case_success`, `failure_codes`, `counts`, `alignment_ambiguities` |
| Aggregate | `cases`, `cases_structurally_invalid`, `cases_pending_adjudication`, `assertion_precision`, `unsupported_assertion_rate`, and the seven `*_mean` values |
| Severity | `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, `UNRATED` |
| Layers | `L0_structural_valid` … `L5_full_case_success` |

A `*_mean` value is the arithmetic mean over the cases whose per-case metric is not null. The number of contributing cases is published with it.

## Forbidden after gold opening

- a new threshold, metric, weighting or composite score;
- a prediction retry or rerun;
- excluding a case, or hiding a case or metric;
- changing the evaluator, Snapshot V2, the gold, or a case specification (other than `adjudications`);
- changing this decision record.

A changed policy is a new task. It is never an edit of this record.

## Limits

- The gate needs severity ratings that are assigned after gold opening. They are published in full, but they remain a judgement.
- DEV3 gold is `AGENT_DRAFT_GOLD` / `NOT_HUMAN_CONFIRMED`. Results must say so.
- Ten cases give little statistical power. A safe result is not evidence of competence by itself.
