# M4 Fresh DEV2 Protocol V1

Date: 2026-10-03. Task: M4-04B3B1. Base: `870823ba509e0a07e380bb92985cf0d6592e2b14`.

This protocol records construction and sealing of `M4_04B3_DEV2_V1`, a fresh development set for the existing `STORY_EXTRACTION_DRAFT_V1` interface and deterministic compiler. It is an offline representational validation. It does not measure model quality and does not authorize a model run, extractor lock, holdout access, M4-04C, or M5.

## 1. Fixed boundaries

No Gemini or other provider/API was called. P0 and P1 were not rerun. The 30-chapter corpus, DEV1 text, and sealed holdout text were not read or reused. Snapshot V1, Snapshot V2, Draft V1, the compiler, canonical schema, predicate registry, and M3 adapter were not changed.

If any independently authored gold case had not been representable, construction would have stopped. A representational failure was not permission to patch the schema or compiler.

## 2. Fresh source family

The source family is `ORIGINAL_JA_MINI_NARRATIVES_DEV2_V1`: ten newly authored Japanese miniature story units in ten M3 manifests. No narrative sentence was copied. The non-use claim is process-based because sealed holdout text was not opened; it is not a claim that the new text was byte-compared with private holdout text.

The ten preregistered capabilities are:

1. alias plus multiple mentions of one referent;
2. similar names plus an unresolved identity without a guessed merge;
3. a later explicit `SameAs` while preserving the earlier placeholder;
4. a repeated exact quotation whose second match needs `occurrence`;
5. speech, belief, and negated embedded content without world-truth leakage;
6. a behaviour-suggested state and an explicitly narrated state;
7. named time and supported state start/end bounds;
8. a multi-reference sufficient path plus partial and corroborating evidence;
9. affirmed and negated explicit causality distinguished from adjacency;
10. reuse of prior canonical context, a context-only distractor, and an as-of cutoff.

## 3. M3 ingestion and case inputs

Every story unit is ingested independently under `LIGHT_NOVEL_INGESTION/v0` with `source_language: ja`, an exact expected source hash, opaque story/document/stream ids, and deterministic source segments. Each case records:

- a stable case id and one capability objective;
- the base canonical document;
- ordered passage inputs labelled `EVIDENCE_ELIGIBLE` or `CONTEXT_ONLY`;
- an explicit `as_of_position`;
- `STORY_UNDERSTANDING_CORE_V0` as the profile;
- a compiler-prepared Draft V1 input containing only passage handles/text/use and authorized prior semantic handles.

Raw source members exist only for trusted M3/source-exact verification. A future extractor surface is restricted to each case's prepared input member. In case 10, the source document contains material after the cutoff, but it is absent from the prepared input and passage scope. The compiler rejects any passage after the as-of boundary and rejects context-only evidence.

## 4. Independent canonical annotation

Canonical semantics were authored first against the M3 source and frozen Canonical Story v0. Draft-like objects were produced only afterward by the offline oracle projection. Thus the compiler did not generate or repair the gold semantics.

Gold is labelled `AGENT_DRAFT_GOLD` and `NOT_HUMAN_CONFIRMED`. The contract method is `HUMAN_ANNOTATION`, but this names the annotation path rather than asserting a human review. Every assertion is `UNREVIEWED`; `human_review_performed` is false. No human confirmation is claimed.

All ten cases are `COMPLETE_FOR_PROFILE`: their coverage records enumerate all required assertions for every evidence-eligible passage and identify only decorative, non-material wording as out of profile. The sealed set contains 119 required assertions and zero acceptable-optional assertions. If later review finds an omitted in-profile fact, the affected completeness label must be withdrawn; the seal must not be silently rewritten.

## 5. Offline representational gate

For each case, the fixed path is:

```text
independently authored canonical annotation
  -> offline canonical_gold_to_draft_v1 projection
  -> unchanged compile_story_extraction_draft_v1
  -> STORY_EXTRACTION_BATCH/v0
  -> exact-source guarded canonical validation
  -> graph signature comparison modulo machine-owned ids/review/provenance
```

The oracle projection is testing notation coverage; it is not a prediction. Equality preserves predicates and typed arguments, graph links, exact source spans and roles, support grouping, derivation rules/premises, polarity, epistemic status, temporal validity bounds, and ambiguity. Only compiler-owned ids, process provenance, and review metadata are alpha-renamed or excluded.

The gate passed 10/10 cases. Canonical gold validation, draft compilation, compiled source-exact validation, and semantic/support graph alpha-equivalence each passed 10/10. No gap was found and no schema/compiler change was made.

## 6. Private package separation

Three untracked private artifacts were created:

| Artifact | SHA-256 | Access |
| --- | --- | --- |
| `M4_04B3_DEV2_INPUT_V1.zip` | `e63937252e69820ff6f4b097537f860524ea9937e1e0bbd7187f2ae52cd812d5` | Prepared extractor inputs plus trusted M3 verification material; zero gold |
| `M4_04B3_DEV2_GOLD_V1.zip` | `77b9655b92b09c5b2c0d0ce749432ae12da342bbf07d62a01b16b37b1fce9939` | Canonical annotations, oracle projections, compiled round-trips, completeness metadata |
| `M4_04B3_DEV2_BLINDNESS_MANIFEST_V1.json` | `b040e960fbb1c9f663fa1565bba9058148c965905fc50df90058869af220998e` | Hash inventory, frozen bindings, separation and access attestations |

The ZIP member-name sets are disjoint. The input archive was scanned for gold-only filenames, fields, statuses, and required/optional assertion metadata; none were present. Private source text, gold, draft projections, compiled batches, and per-case identifiers beyond the sanitized capability ids are not committed.

DEV2 gold must remain closed for any future blind model execution until raw drafts and compiled predictions are terminally locked and hashed. Opening gold for prompt, model, repair, selection, threshold, or evaluation tuning converts DEV2 into tuning data.

## 7. Integrity and interpretation

The private manifest binds Draft V1, the deterministic compiler, its offline coverage adapter, both evaluation snapshots, M3 freeze, canonical schema, and predicate registry. Rebuilding produces the same package hashes. Source-exact checks re-ingest the exact UTF-8 bytes and validate every passage and evidence locator.

Representability does not establish extraction accuracy, unsupported-claim safety, generalization, or readiness for the sealed holdout. There were no model predictions. No extraction model or extractor is selected or locked. The only next action is orchestrator review of the fresh DEV2 seal; M4-04C and M5 remain out of scope.
