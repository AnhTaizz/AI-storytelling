# STORY_EXTRACTION_DRAFT_V1_1 Contract

Status: `M4_04B3D1_DRAFT_V1_1_SCHEMA_READY`

## Scope

`STORY_EXTRACTION_DRAFT_V1_1` is an additive model-output interface version. It removes the ambiguous model-owned link between a mention locator and assertion evidence while preserving every non-mention semantic field from Draft V1.

Draft V1 and its compiler remain frozen and byte-identical. This task defines only the V1.1 schema and migration contract; it does not implement compilation, inspect DEV2, or call a provider.

## Mention shape

A model-authored mention contains only:

- required `handle`;
- required `passage_handle`;
- required exact `quote`;
- optional one-based `occurrence` when required to disambiguate a repeated quote;
- required `role`; and
- optional `surface_form`.

`evidence_handle` is forbidden by `additionalProperties: false`.

The mention quote is its own exact locator. It is not a request to reuse broader assertion evidence. Assertion evidence continues to be authored independently in `evidence[]` and cited through assertion support.

## Machine-owned fields

The model does not emit source hashes, offsets, canonical identifiers, batch envelopes, process provenance, or review state. Exact quote resolution and all machine-owned fields remain deterministic compiler responsibilities.

## Fail-closed rules

Passage handle, quote, occurrence, and evidence role remain explicit. A missing quote, ambiguous repeated quote, invalid occurrence, context-only citation, or invalid role is a structural failure. The interface does not infer identity, truth, causality, predicates, events, or assertion support.

## Mechanical V1 to V1.1 migration

A future migration may perform exactly two changes after validating Draft V1:

1. change `draft_version` from `STORY_EXTRACTION_DRAFT_V1` to `STORY_EXTRACTION_DRAFT_V1_1`; and
2. remove `evidence_handle` from each mention when present.

No quote, occurrence, role, handle, predicate, argument, support set, polarity, epistemic status, temporal bound, or other semantic field may change. Compiler behavior is intentionally outside this schema-only task.
