# M4 Fresh DEV3 Protocol V1

## Purpose

DEV3 is a fresh, sealed development-validation set for `STORY_EXTRACTION_DRAFT_V1_1` and its deterministic compiler. It is not a continuation of DEV2: DEV2 is tuning data after the interface redesign and no DEV2 source, gold, or raw prediction was used to author DEV3.

## Hard boundaries

- Construction is offline. No provider, model, or API call is permitted.
- The sealed holdout is not accessed.
- DEV3 cannot be used to patch Draft V1.1, its compiler, the canonical schema, predicate registry, or evaluation snapshots.
- Gold cannot be opened by an extractor or prediction runner. It becomes eligible for scoring only after a separately locked prediction package exists and is hashed.
- The input archive is the only DEV3 package available before prediction lock.

## Fresh source family

The source family is `ORIGINAL_JA_STARLIT_ARCHIVE_MINI_NARRATIVES_DEV3_V1`. It contains ten newly written Japanese miniature narratives in case order `DEV3_01` through `DEV3_10`. The cases cover:

1. aliases and multiple mentions;
2. unresolved identity;
3. later explicit `SameAs`;
4. repeated exact quotes with occurrence selection;
5. negated speech and holder-relative belief;
6. explicit versus behaviour-suggested state;
7. temporally bounded state validity;
8. sufficient, partial, and corroborating evidence;
9. explicit causality versus temporal adjacency; and
10. prior canonical context, context-only passages, and an as-of boundary.

All source units are ingested with frozen `LIGHT_NOVEL_INGESTION/v0`. Passage references and evidence spans must reproduce against exact source bytes.

## Gold-first construction

Canonical annotations are authored and validated before any Draft V1.1 projection. The private authoring lock binds all ten canonical batches at SHA-256 `c62049dd536dde3eb1fb2d49b98ee2540fbf43eeedf74986f577ffe428b37cae`.

Every case is marked:

- `AGENT_DRAFT_GOLD`;
- `NOT_HUMAN_CONFIRMED`;
- annotation method `HUMAN_ANNOTATION`;
- assertion review state `UNREVIEWED`; and
- `COMPLETE_FOR_PROFILE`, with all 76 annotated assertions required and none optional.

These labels do not claim human review. Narrative details outside the frozen profile are not silently promoted into assertions, and holder-relative content is not promoted to story truth.

## Offline representation gate

Only after the gold authoring lock is created, each case is projected by the offline oracle into `STORY_EXTRACTION_DRAFT_V1_1`, compiled by the unchanged deterministic V1.1 compiler, and compared with its authored canonical graph modulo machine-owned identifiers and provenance.

The seal requires all of the following:

- 10/10 Draft V1.1 schema-valid;
- 10/10 deterministic compilation success;
- 10/10 exact-source validation success;
- 10/10 canonical semantic/support graph round-trip; and
- zero changes to Draft V1.1, its compiler, frozen M3, the canonical schema/registry, or evaluation snapshots to fit DEV3.

All requirements passed.

## Private package separation

The private packages are:

- `M4_04B3_DEV3_INPUT_V1.zip`, SHA-256 `47ae7c743065f8ff001f4db6a398df2edf1db094383b1fe2d0c3a05ab40c55c7`;
- `M4_04B3_DEV3_GOLD_V1.zip`, SHA-256 `b5b2258d46608015ff60de2c660fba521029ff4716c7c1cc3b3735c55dfd34a9`; and
- `M4_04B3_DEV3_BLINDNESS_MANIFEST_V1.json`, SHA-256 `d63d2dd2a490add0cac6c0789e3a52f7da4c67ec72b88b37d8f5e2eb784651d4`.

The input archive contains 51 members and zero gold markers, gold labels, gold case specifications, or gold batches. The gold archive contains 32 members. The archives share zero member names. Each ZIP uses sorted paths, fixed metadata, deterministic compression, and member-level SHA-256 bindings. A complete rebuild reproduced all three artifact hashes.

## Required next lock

This seal does not authorize prediction, scoring, or gold access. A separate benchmark protocol must bind the exact input and gold hashes, case order, Draft V1.1 schema/compiler identities, prompt/runtime/model settings if any, repair policy, and prediction-lock-before-gold rule before DEV3 input is opened for prediction.
