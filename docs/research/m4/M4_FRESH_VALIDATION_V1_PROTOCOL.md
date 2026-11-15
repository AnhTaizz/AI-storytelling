# M4 Fresh Validation V1 Protocol (for Draft V1.1)

Date: 2026-11-15. Task: M4-04B3E. Base: `d0869ed12ac407a25d3ee32b395720dd6639d445`.

This protocol records the construction and sealing of `M4_04B3E_FRESH_VALIDATION_V1`, the fresh validation set that `docs/research/m4/M4_DRAFT_INTERFACE_V1_1.md` requires before `STORY_EXTRACTION_DRAFT_V1_1` may be tested on a model. The project owner authorized it on 2026-11-14.

It is an offline representational validation. It does not measure model quality. It does not authorize a model run, a prompt or extractor lock, holdout access, M4-04C, or a start of M5.

## 1. Fixed boundaries

- No provider or API was called, and no prediction was produced.
- DEV1 text, DEV2 input, DEV2 gold and the sealed holdout were not opened. None of those private artifacts exists in the environment where this set was built.
- Draft V1, Draft V1.1, both compilers, both evaluation snapshots, the canonical schema, the predicate registry and the M3 adapter are unchanged.
- A gold case that could not be represented would have stopped the construction. It would not have been a reason to patch a schema or compiler. No such case occurred.

## 2. Fresh source family

The family is `ORIGINAL_JA_MINI_NARRATIVES_FV1`: ten Japanese miniature story units written for this set, each of one to five passages, in ten M3 manifests. No sentence is copied from any source.

The non-use claim is process-based. The author had read tracked sample chapters 1–5 of the 30-chapter corpus for pipeline work, and the public M4 records. No character, scene or sentence of the corpus is used, and nothing was byte-compared with sealed text.

The ten capabilities are the ones preregistered for DEV2, on new text:

1. alias plus multiple mentions of one referent;
2. similar names plus an unresolved identity without a guessed merge;
3. a later explicit `SameAs` while preserving the earlier placeholder;
4. a repeated exact quotation whose second match needs `occurrence`;
5. speech, belief and negated embedded content without world-truth leakage;
6. a behaviour-suggested state and an explicitly narrated state;
7. named time and supported state start and end bounds;
8. a multi-reference sufficient path plus partial and corroborating evidence;
9. affirmed and negated explicit causality distinguished from adjacency;
10. reuse of prior canonical context, a context-only distractor, and an as-of cutoff.

Keeping the capabilities lets a later Draft V1.1 result on fresh text be read against the DEV2 tuning diagnostic (6/10 structurally valid after migration). The cost is that this set does not probe failure classes outside those ten.

## 3. Inputs

Every unit is ingested on its own under `LIGHT_NOVEL_INGESTION/v0` with `source_language: ja` and an exact source hash. For each case the input package holds:

- the base canonical document (for case 10 it carries the records of an earlier extraction step);
- `prepared_draft_input.json`, the Draft V1.1 model surface: passage handles, text and use, plus authorized prior semantic handles;
- the passage scope, as-of position and profile for the trusted compiler context;
- the M3 manifest, the exact source bytes and the ingestion report, for source-exact verification.

A future extractor may read only the `prepared_draft_input.json` members. In case 10 the source continues after the cutoff; that passage is absent from the prepared input and from the passage scope.

## 4. Independent canonical annotation

Canonical semantics were written by hand against the M3 source and the frozen Canonical Story v0, before any draft-like object existed. The oracle projection ran afterwards, so the compiler neither produced nor repaired the gold.

Gold is `AGENT_DRAFT_GOLD` and `NOT_HUMAN_CONFIRMED`. The method label `HUMAN_ANNOTATION` names the annotation path; no human review is claimed. Every assertion is `UNREVIEWED`.

All ten cases are `COMPLETE_FOR_PROFILE` under `STORY_UNDERSTANDING_CORE_V0`: 168 required assertions and no optional ones. Each evidence-eligible passage has a coverage note that says what was annotated and what was left out as decorative. The annotation rules (which expressions are mentions, which name forms get `NamedAs`, how participant roles and event kinds are chosen) are written at the top of the private authoring script, which is stored inside the gold package. Texts were kept free of facts that have no registered predicate, such as occupation, kinship and duration.

If a later review finds an omitted in-profile fact, the affected completeness label must be withdrawn. The seal must not be silently rewritten.

## 5. Offline representational gate

```text
independently authored canonical annotation
  -> offline canonical_gold_to_draft_v1 projection, then the mechanical V1 -> V1.1 migration
  -> unchanged compile_story_extraction_draft_v1_1
  -> STORY_EXTRACTION_BATCH/v0
  -> exact-source guarded canonical validation
  -> graph signature comparison modulo machine-owned ids, review and provenance
```

The gate passed 10/10 at every step. Records of a base document are compared by identity, so case 10 also checks that prior context is referenced and not copied.

## 6. Private packages

| Artifact | SHA-256 | Content |
| --- | --- | --- |
| `M4_04B3E_FRESH_VALIDATION_V1_INPUT.zip` | `724041283cde55ccbce27844c9297cf66eed857c96cf18989dc97997fef55729` | Prepared inputs and trusted M3 verification material; no gold |
| `M4_04B3E_FRESH_VALIDATION_V1_GOLD.zip` | `732a3555717c6d3426e6e379e43061cd1fd6d11df8798ec859f37248202ddc73` | Gold batches, oracle drafts, compiled round-trips, completeness records, the authoring script |
| `M4_04B3E_FRESH_VALIDATION_V1_BLINDNESS_MANIFEST.json` | `cdb8c0dcc62d12e776b0061201f3ec984289007f6e11450266474cfe52a75ea8` | Both hashes, the hashes of the bound interface files, access rules |

The two archives share no member name. The input archive was scanned at every depth for gold-only keys and gold-named members. Members are stored uncompressed, in name order, with fixed timestamps, so a rebuild gives the same bytes on any machine; two builds were compared.

The packages were produced in a cloud session and handed to the project owner. They are not in the repository. Whoever runs a later step must place them under a git-ignored directory and check the three hashes first.

Gold must stay closed for any blind model run until raw drafts and compiled predictions are terminally locked and hashed. Opening gold earlier, for prompt, model, repair, selection, threshold or evaluation tuning, turns this set into tuning data. `verify_sealed` opens the gold package, so it is for the author before any prediction exists and for the evaluator after predictions are locked.

## 7. Tooling

`tools/story_extraction/fresh_validation_seal_v1.py` runs the gate, builds both packages and the manifest, and re-verifies a sealed set from its three files. It authors no semantics and has no provider integration. `tests/story_extraction/test_fresh_validation_seal_v1.py` exercises it on the synthetic fixture graphs only.

## 8. Interpretation and limits

- Representability does not establish extraction accuracy, unsupported-claim safety, generalization, or readiness for the sealed holdout.
- The gold is one agent's reading, and the same agent wrote the seal tool. The rules are recorded so that a reviewer can contest them.
- The units are miniatures. Nothing here measures extraction on real chapters.

The only next action is orchestrator review of this seal. Locking a Draft V1.1 prompt and runtime against the input hash, and running blind predictions, each need their own authorization.
