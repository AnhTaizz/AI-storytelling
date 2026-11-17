# M4 Fresh Validation V2 Protocol

Date: 2026-11-17. Task: M4-04B3M. Base: `18bd37a9f2b71f0b9cae1e4ff66fa4b13fe001d6`.

This protocol records the offline construction and sealing of
`M4_04B3M_FRESH_VALIDATION_V2` under Annotation Conventions V2. It follows the
[FV1 method](M4_FRESH_VALIDATION_V1_PROTOCOL.md), using the unchanged
`tools/story_extraction/fresh_validation_seal_v1.py`. That module already
parameterizes the set identifier, family and case count; no V2 module is needed.

This task measures representability, not extraction quality. It produces no model
predictions and authorizes no provider run, prompt lock, holdout access, M4-04C or M5.

## 1. Boundaries and blindness

The source and gold author is separate from the P4 prompt developer. The P4
developer has not seen FV2 source text or gold. All private authoring material,
diagnostics, sources and packages are confined to the git-ignored
`.local/m4_fv2/` directory. Public records contain only aggregate metadata,
capability labels, hashes, methods and paths; they contain no narrative, names,
literals or gold identifiers.

No other `.local/` material, DEV1, DEV2, FV1 private package, sealed holdout,
prediction output, `.env`, or P4 prompt file was opened to author this set.
No network or model API was used, and no commit or push was made. The frozen
canonical schema, registry, M3 adapter, extraction interfaces, compilers and
evaluation snapshots remain unchanged.

The author may run `verify_sealed` before any prediction exists. That function
opens gold; a blind extractor or its developer must not run it before predictions
are terminally locked and hashed. A future extractor may read only the
`prepared_draft_input.json` members. Gold opened for prompt, model, repair,
selection, threshold or evaluation tuning before prediction lock makes the set
`CONTAMINATED`; its seal must not be silently rewritten.

## 2. Fresh source family and coverage

`ORIGINAL_JA_MINI_NARRATIVES_FV2` consists of twelve newly authored Japanese
miniature units, each with two to five short passages, in ordinary contemporary
settings. There are 28 source passages: 25 evidence eligible, two context only,
and one after the as-of cutoff. Each unit has its own M3 manifest.

Freshness is a process claim: no sentence, character or scene was copied from an
existing work or repository sample. No excluded private material was read or
byte-compared. Required public rules and tooling, including synthetic fixture
construction helpers, were inspected.

The twelve primary capability labels are:

1. `alias_multiple_mentions_honorifics_and_name_forms`
2. `adjectives_genitive_chains_and_excluded_relative_clause`
3. `giving_lending_transfer_roles_and_resulting_possession`
4. `taking_from_holder_versus_unheld_pickup`
5. `encounter_then_separate_conversation`
6. `arrival_location_versus_heading_destination`
7. `reveal_tell_conveys_versus_utterance`
8. `negated_speech_belief_repeated_speaker_without_truth_leak`
9. `inanimate_change_patient_versus_sound_light_theme`
10. `benefactive_recipient_and_deliberate_involuntary_perception`
11. `yearless_dates_time_of_day_and_explicit_temporal_order`
12. `prior_context_reuse_context_only_and_as_of_cutoff`

These labels describe coverage, not case content or gold identifiers.

## 3. Source binding and inputs

Each unit is ingested through `LIGHT_NOVEL_INGESTION/v0`, with `source_language:
ja` and an exact source SHA-256. The input package contains the base canonical
document, prepared Draft V1.1 input, scope and as-of position, exact source bytes,
M3 manifest and ingestion report. It contains no gold. The trusted host retains
the verification material; only prepared input members are extractor surfaces.

One case reuses records from a prior canonical extraction. Its earlier passages
are context only, its current eligible passage may refer to prior identities,
and its source continuation after the cutoff is absent from scope and prepared
input. Prior records are not copied into candidate records or counted as required
gold. The prior batch is preserved privately for audit.

## 4. Independent canonical annotation

Gold was hand-declared against the M3 source and frozen Canonical Story v0 before
any oracle draft existed. The compiler does not author or repair gold. The
annotation rules applied are recorded at the top of
`.local/m4_fv2/build_fv2.py`, which is included in the gold package.

The controlling document is
[M4 Annotation Conventions V2](M4_ANNOTATION_CONVENTIONS_V2.md), exact byte hash
`49fc5de9af46b861eb0ed70bd3bbc44948855576e0e0565fd9340777d26f5f7e`.
Its bytes and the checker report are included in the gold archive. This binds
the convention version through the gold package hash, in addition to the frozen
interface bindings in the blindness manifest.

All twelve cases are `COMPLETE_FOR_PROFILE` under
`STORY_UNDERSTANDING_CORE_V0`, following evaluation protocol sections 4 and 10:
194 required assertions, no optional assertions, and one coverage note for each
of the 25 eligible passages. Required assertion identifiers are enumerated only
in the private gold manifest. Coverage notes document exclusions and profile
boundaries. STRING values are verbatim source-language spans; no non-verbatim
literal variants are needed. Dates never gain an unstated component.

Gold labels are `AGENT_DRAFT_GOLD` / `NOT_HUMAN_CONFIRMED`; every assertion is
`UNREVIEWED`. `HUMAN_ANNOTATION` denotes the annotation path, not a claim of human
review. A later review finding a missing in-profile fact must withdraw that
case's completeness label and preserve the original seal.

## 5. Checks and offline gate

Before sealing, `check_annotation_conventions_v1.check_batch` checked every gold
batch against its exact source and base document. All ten MECHANICAL rule counts
were zero across 12/12 cases. The prior-context batch was also checked. The V1
checker is applicable unchanged to V2; judged rules remain the author's reading.

The unchanged seal tool then ran:

```text
canonical gold
  -> offline canonical_gold_to_draft_v1 oracle projection
  -> mechanical Draft V1 to V1.1 migration
  -> unchanged deterministic V1.1 compiler
  -> exact-source guarded canonical validation
  -> semantic/support graph comparison modulo machine-owned identifiers
```

Gold validity, draft compilation, compiled validity, graph equivalence and total
representability each passed 12/12. A failure would stop construction rather than
justify a schema or compiler patch. This gate is not an extraction prediction.

## 6. Packages and reproducibility

All artifacts are under `.local/m4_fv2/sealed/`:

| Artifact | SHA-256 |
| --- | --- |
| `M4_04B3M_FRESH_VALIDATION_V2_INPUT.zip` | `e9d4ec2462d00922a3cf075bbbc5bd650707a38425c94eff0b626f57eac46353` |
| `M4_04B3M_FRESH_VALIDATION_V2_GOLD.zip` | `ca82f09c599e8a5d4386cc23ce76a9e7eed902b0bb51a8ea8546fa63dcce1977` |
| `M4_04B3M_FRESH_VALIDATION_V2_BLINDNESS_MANIFEST.json` | `9595d44c4e41e50038d6f64466f2dd5415799321e86baea0878c9e3e89eda89d` |

The two archives share zero member names. The input package was recursively
scanned for gold-only keys and gold-named members. Archives store members without
compression, sorted by name, with fixed timestamps. Two builds produced identical
bytes for all three artifacts. `verify_sealed` then passed from the three sealed
files alone, checking hashes, frozen interface bindings, source binding, package
separation, completeness labels and the representational gate at 12/12.

The private authoring script and reports are retained for reproducibility.
The content-free aggregate record is
`benchmarks/m4_extraction/M4_04B3M_FRESH_VALIDATION_V2_SEAL_RESULT.yaml`.

Repository verification used Python 3.14.2 with `PYTHONUTF8=1` and
`PYTHONDONTWRITEBYTECODE=1`. The required `story_extraction` suite ran 407 tests
under a subprocess audit guard that refused repository `.env`, other private
directories, P4 prompt files and network access. It reported one known CRLF
protocol-lock hash failure and ten errors from forbidden P4 prompt reads in
`tests/story_extraction/test_run_m4_p4_dev_v1.py`; no tests were skipped or
weakened. Thus the requested suite pass cannot be claimed within the explicit
read boundary. The coverage quality gate also failed because `coverage` is
unavailable, and reported a pre-existing stale test catalog. Full diagnostics
remain under `.local/m4_fv2/`; none contains a public FV2 narrative disclosure.
The ordinary repository-wide quality gate completed ten suites and 1,164 tests
with 36 failures or errors, including blocked private-directory/P4 reads and
failures outside FV2; it also reported the stale catalog. Neither repository-wide
gate is claimed to pass.

## 7. Limits and next boundary

The FV2 lock can bind deterministic host repairs `QR` (quote resolution) and `AM`
(mention anchoring), in that order, including the selected repair modules' byte
hashes and dependencies. The prediction runner applies only the validated lock's selection before
validating primary and repair responses, and uses the resulting primary blockers
for the repair request; prediction identities and summaries record the selection.
The owner bound `P4R6` with `QR` and `AM` on 2026-11-18 (DEC-027). A protocol
without the `host_repairs` key is still read as having no host repairs.

Representability does not establish extraction accuracy, generalization,
unsupported-assertion safety or readiness for sealed holdout evaluation. The
gold is one agent's unreviewed annotation, and mechanical checks do not prove
semantic completeness. Twelve short authored units in one language do not
measure extraction on real chapters.

The next step is orchestrator review of this seal. Any prompt/runtime lock and
blind prediction run requires a separately authorized task. Gold remains closed
to the extractor and P4 developer until predictions are locked and hashed.
