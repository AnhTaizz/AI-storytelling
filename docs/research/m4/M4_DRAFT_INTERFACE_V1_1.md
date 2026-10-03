# M4 Draft Interface V1.1

Status: `READY_FOR_FRESH_VALIDATION`

## Purpose

`STORY_EXTRACTION_DRAFT_V1_1` is an additive, offline remediation of the mention/evidence ambiguity identified in M4-04B3C-R. It does not modify Draft V1, the Draft V1 compiler, either evaluation snapshot, the extraction evaluator, or any locked prediction.

This change is structural only. It makes no new semantic inference and does not claim improved extraction quality.

## Model-facing contract

A V1.1 mention contains only:

- `handle`
- `passage_handle`
- `quote`
- optional `occurrence`
- `role`
- optional `surface_form`

`evidence_handle` is not permitted. The V1.1 schema has `additionalProperties: false`, so a model cannot express the ambiguous broad-support relationship that caused the systematic V1 failure.

Assertion evidence remains authored separately in `evidence[]` and referenced only through assertion support. The compiler never adds an implicit mention EvidenceRef to an assertion evidence set.

## Deterministic mention binding

For each mention, the compiler resolves the exact passage span using the existing source-exact quote and occurrence rules. It then:

1. reuses a model-authored `evidence[]` record only if resolved passage span and role are identical;
2. otherwise reuses an EvidenceRef created for an earlier mention only when that same exact identity matches; or
3. creates a new deterministic EvidenceRef for the mention locator.

Containment is not identity. A wider assertion-evidence span is never reused merely because it contains a mention quote. The binding step does not add `RefersTo`, `SameAs`, occurrence, causality, truth, predicate, argument, or support semantics.

The canonical batch is still produced through the unchanged Draft V1 canonical compiler after a private compiler-internal exact binding transformation. V1.1 therefore preserves the frozen canonical envelope, provenance, identifier, and validation behavior while removing the model-facing ambiguity.

## Structural diagnostics

V1.1 exposes an ordered collection of source-text-free blockers. When the remaining checks are independently feasible, diagnostics enumerate all schema, quote-locator, duplicate-handle, reference-type, assertion-evidence, derivation, temporal-bound, and ambiguity-reference blockers instead of returning only the first one.

Diagnostics contain only phase, code, and structural path. They never echo quotes or source text. Canonical validation remains fail-closed and is reported as a canonical compiler blocker if reached.

## Mechanical V1 migration

The migration is deliberately narrow:

1. validate the input as Draft V1;
2. change `draft_version` to `STORY_EXTRACTION_DRAFT_V1_1`;
3. remove `evidence_handle` from every mention; and
4. validate the result as Draft V1.1.

No other field is added, deleted, or changed. Migration does not repair quote occurrence, handles, predicates, assertions, support, or semantic content.

## Locked DEV2 tuning diagnostic

The 20 locked B3C parsed drafts—primary and repair for each case—were migrated in memory and compiled against the authorized, hash-locked DEV2 input. There was no model call, prediction rerun, gold access, holdout access, or scoring.

Results:

- old terminal structural result: 2/10 valid;
- migrated V1.1 terminal result: 6/10 valid;
- `MENTION_EVIDENCE_MISMATCH`: eliminated, zero remaining;
- primary attempts: 6/10 valid;
- repair attempts: 6/10 valid;
- 78 model-facing mention evidence links removed with zero other migration changes;
- 75 mention bindings were feasible before canonical compilation: 74 exact mention EvidenceRefs created and one exact model-authored EvidenceRef reused.

The four remaining terminal failures are deliberately preserved:

- `DEV2_03`: canonical conformance failure;
- `DEV2_04`: canonical conformance failure after its repair draft;
- `DEV2_05`: two repeated-quote occurrence blockers in its repair draft;
- `DEV2_07`: canonical conformance failure.

Across all 20 attempts, aggregate diagnostics found seven `AMBIGUOUS_QUOTE` blockers in three failed attempts and five canonical conformance failures. These are independent of the removed mention/evidence link and were previously censored by earlier fail-fast rejection. They were not repaired because that would alter locked model semantics or fit the interface to DEV2.

## Data status and next gate

DEV2 is now `TUNING_DATA_AFTER_INTERFACE_REDESIGN`. It is no longer eligible as fresh validation for V1.1. The 6/10 migration result is a tuning diagnostic, not a benchmark score and not evidence of model quality.

V1.1 may proceed only to a newly authored, independently sealed fresh validation set under a separately locked prompt/runtime protocol. DEV2 gold remains sealed and the holdout remains untouched.
