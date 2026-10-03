# M4-04B3A — Extraction interface redesign V1

Date: 2026-10-03. Engineering prototype; not an extractor lock or a quality claim.
Historical result remains **M4_04B2_DEVELOPMENT_LEADER_NOT_LOCKABLE**.

## Evidence and scope

Base HEAD is `15b8af0357415f9edc9bf7661f0317b50bdcc04e`. A separate clean checkout
was used because the original working tree contains unrelated edits. B2's 28
terminal predictions, all 54 locked primary/repair responses and six final JSON
predictions were read offline and verified against their locked hashes. The
prediction manifest, final evaluation and DEV archive hashes match the public
records. M1/M2/M3 freeze bindings and Snapshot V1/V2 bindings remain byte-exact.

There were no provider requests, no regenerated P0/P1 outputs, no opening of M4
holdout input/gold, and no M4-04C or M5 work. Public freeze/lock metadata is not
private holdout data. Historical B2 selection, scores and safety gate are unchanged.

## Failure forensics

P0 had 0/14 runtime-structural and 0/14 source-exact L0-valid predictions. P1 had
6/14 runtime-structural and 2/14 source-exact L0-valid predictions. Both candidates
had zero full canonical case successes. Runtime validation did not check exact
source bytes; four of P1's six structural outputs failed when exact-source checks
were applied. A structurally plausible hash is not an authentic source hash.

The audit uses locked validation/evaluation reports plus independent shape,
source-span and graph diagnostics on unchanged terminal output. It does not
repair a prediction or replace the frozen evaluator. Counts below are numbers of
terminal candidate/case pairs with a diagnostic, not exclusive root causes.

| Failure family | Cases / 28 | Ownership and interpretation |
| --- | ---: | --- |
| Envelope/copy | 25 | MACHINE_OWNED: incorrect reproduction of trusted scope |
| Passage/span/source-exact | 26 | MACHINE_OWNED: malformed, stale or inaccurate locators/hashes |
| Evidence | 2 | SEMANTIC_MODEL_OWNED: support-path/role/epistemic invariants |
| Canonical schema | 2 | MACHINE_OWNED: representation shape/identifier syntax |
| Predicate/argument | 4 | Mixed: exact duplicate content is mechanical; predicate, rule and temporal choices are semantic |
| Entity/event | 0 diagnosed | Semantic identity/granularity is largely censored by L0 failure; zero is not evidence of correctness |
| Provenance/review | 1 | MACHINE_OWNED: direct audit found metadata that did not obey process/review discipline |
| ID/reference | 4 | MACHINE_OWNED for identifier encoding, collision and reference integrity; choosing the referent remains semantic |
| Semantic coverage | 2 | SEMANTIC_MODEL_OWNED: eleven required assertions missed across the two L0-valid cases |
| Unsupported | 0 observed | SEMANTIC_MODEL_OWNED; not assessable as a safety rate for 26 L0-failed cases |

Locked terminal validation contains 814 `MALFORMED_PASSAGE_INPUT` diagnostics,
three `SPAN_OUTSIDE_SEGMENT`, one `ID_COLLISION`, and canonical reference/predicate
diagnostics. One case can yield many messages; these are not 814 independent
failed predictions. Early guard rejection hides downstream problems. Independent
checks expose some such problems but do not establish semantic truth for malformed
batches. The result YAML provides all 28 sanitized per-case rows and ownership.

### Metadata-copy hypothesis

The hypothesis is **supported as an engineering diagnosis**. Every old response
must recreate the complete envelope and passage refs already present in trusted
input, then repeat offsets, hashes, canonical IDs and process/review metadata in
its records. Across 28 terminal cases the required envelopes alone occupy 482,184
UTF-8 bytes in the runner's deterministic serialization; the responses occupy
439,042 bytes. Envelopes range from 1,985 to 32,945 bytes, with 1–30 passage inputs
per case. These are serialization sizes, not tokenizer measurements or a claim
of expected token/cost savings. The frozen output quota was 16,384 tokens.

25/28 copied scopes are wrong and 26/28 cases have exact-source diagnostics.
Moving this duplication into code removes that opportunity for copy errors.
There was no randomized interface comparison and no new model execution, so the
audit does not prove the new interface improves semantic extraction. The two
L0-valid cases still have zero assertion recall and coverage failures. Those
failures need fresh model validation, not a compiler truth heuristic.

## Proposed interface

```text
trusted source/context -> model-friendly input handles
LLM -> STORY_EXTRACTION_DRAFT_V1
    -> deterministic compiler
    -> STORY_EXTRACTION_BATCH/v0
    -> unchanged Snapshot V2 validation/evaluation
```

Schema: `schemas/story_extraction/story_extraction_draft_v1.schema.json`.
Compiler: `tools/story_extraction/draft_compiler_v1.py`.

The draft's top-level keys are `draft_version`, `evidence`, `mentions`, `entities`,
`events`, `anchors`, `propositions`, and `assertions`. Empty arrays are explicit.
Every object is closed against extra fields; no canonical record is passed through.

| Kind | Example handle | Meaning |
| --- | --- | --- |
| Input passage | `P1`, `P2` | Fixed ordered host passage, with text and eligibility |
| New entity | `E_NEW_1` | A model-proposed identity-bearing referent |
| Existing entity | `E_EXISTING_1` | Host-mapped entity already in the base; never re-emitted |
| Evidence | `EV1` | Exact quotation selected by the model |
| Mention | `M1` | Located surface reference; no automatic resolution |
| Event | `EVT1` | Occurrence identity; does not assert `Occurred` |
| Anchor | `T1` | Explicitly proposed `EVENT_TIME` or `NAMED_TIME` |
| Proposition | `PROP1` | Truth-neutral predicate plus typed arguments, or placeholder |
| Assertion | `A1` | Explicit polarity, epistemic status and support |

Existing kinds also use `EVT_EXISTING_1`, `T_EXISTING_1`, `PROP_EXISTING_1`,
`M_EXISTING_1`, and `A_EXISTING_1`. Handle types are checked. Handles do not carry
names or global identity; the host allocates them afresh for a fixed input context.

The model-facing preparer exposes passage text/use and prior semantic records
through handles. It omits source locators, hashes, canonical IDs, provenance and
review metadata. A production caller must supply only authorized prior context
within its as-of boundary; this prototype does not select relevant prior records
or run retrieval. Prior context constrains interpretation but is never direct
evidence for a new assertion. Existing assertions may be selected as derivation
premises under the unchanged canonical rules.

### Quotes and mentions

Evidence and mention records require `passage_handle`, `quote` and semantic
`role`, with optional **1-based** `occurrence`. The compiler searches only the
specified passage and counts all exact matches, including overlapping ones.
A unique quote can omit occurrence. Repeated quotes require it. Missing quotes,
out-of-range occurrence, wrong Unicode/whitespace, context-only passages and
out-of-scope substrings fail closed. No fuzzy matching or normalization occurs.

A mention can cite a draft `evidence_handle`; its quote, role and resolved span
must match that evidence. Without one, the compiler materializes an evidence
record for the explicitly requested quote. `surface_form` is optional semantic
text, defaulting to the quote; it does not resolve an entity. Keeping it explicit
allows the existing canonical representation where a mention's supporting span
is longer than its surface form. It is not evidence of identity.

### Semantic content retained in the draft

The model chooses entity kind/placeholder, event kind and anchor pairing,
predicate and named argument roles, literal/token values, `RefersTo`/`SameAs`
relations, polarity and epistemic status. It also chooses evidence role,
SUFFICIENT/PARTIAL/CORROBORATING group membership, derivation rule and premises,
validity bounds and their support, textual ambiguity alternatives, and which
assertions to extract. Placeholder propositions, nested holder-relative content,
named anchors and supported temporal bounds are representable.

The compiler validates these choices under the frozen registry; it never picks a
predicate, merges identities, invents `Occurred` or `RefersTo`, fills missing
arguments, derives a causal relation, chooses truth, upgrades support/epistemic
status, or adds missing assertions. Duplicate concrete propositions fail canonical
validation; this prototype does not silently deduplicate semantic records.

### Deterministic ownership

The model must not emit hashes, offsets, byte ranges, source/process metadata,
provenance, review state, canonical IDs, source positions or a full envelope.
Nested metadata injection is rejected by the closed draft schema.

`DraftCompilerContext` supplies the trusted base, M3 ingestion result, ordered
passage refs, as-of position, profile and host process/run identity. The compiler:

1. Validates draft schema, base, passage authenticity, eligibility and boundary.
2. Builds typed handle maps; rejects duplicates, missing references and collisions.
3. Resolves quotes and invokes the frozen adapter to construct all exact locator
   fields, including Unicode character/byte offsets and source/text hashes.
4. Allocates canonical IDs deterministically from base identity + process/version
   + run and local handles. These are host-owned execution identities, not a
   cross-run semantic entity-resolution scheme.
5. Translates explicit draft graph/support/bounds without altering their meaning.
6. Creates one `AUTOMATED_EXTRACTION` provenance record and marks every assertion
   `UNREVIEWED`, with no self-certification or invented human sign-off.
7. Creates the scope, base hash and complete v0 envelope, then runs the unchanged
   guarded canonical validator with exact source ingestion.

Returns a canonical batch only if conformance passes; otherwise raises a coded
`DraftCompilationError` without a partial batch. Public error strings exclude
quotes, source text and literal arguments. Canonical conformance proves format
and declared invariants, not whether the story actually supports an assertion.
A synthetic regression deliberately compiles a structurally valid but false
polarity to prove that the compiler is not a hidden semantic extractor.

Example for an invented input `P1 = "The gate opened at dawn."`:

```json
{
  "draft_version": "STORY_EXTRACTION_DRAFT_V1",
  "evidence": [{"handle": "EV1", "passage_handle": "P1",
                "quote": "The gate opened at dawn.", "role": "DEPICTION"}],
  "mentions": [],
  "entities": [],
  "events": [{"handle": "EVT1", "event_kind": "GENERIC", "anchor_handle": "T1"}],
  "anchors": [{"handle": "T1", "anchor_kind": "EVENT_TIME", "event_handle": "EVT1"}],
  "propositions": [{"handle": "PROP1", "predicate": "Occurred",
                    "args": {"event": {"kind": "EVENT", "handle": "EVT1"}}}],
  "assertions": [{"handle": "A1", "proposition_handle": "PROP1", "polarity": "AFFIRMED",
                  "epistemic_status": "EXPLICIT",
                  "support": {"evidence_sets": [{"label": "SUFFICIENT", "evidence_handles": ["EV1"]}],
                              "derivations": []}}]
}
```

## DEV1 offline representational coverage

All 14 DEV1 canonical gold batches were projected mechanically to draft-like
objects and compiled back, with **no model call**. All pass draft schema,
source-exact v0 conformance and graph round-trip comparison. Covered totals:
121 evidence refs, 4 mentions, 9 entities, 25 events, 26 anchors, 109 propositions
and 102 assertions.

Comparison preserves predicate/arguments, typed graph links, quotes through exact
source spans/hashes, evidence roles, support grouping, rules/premises, polarity,
epistemic status, temporal bounds and ambiguity. It is alpha-equivalence of
record/support IDs, not byte identity: process, provenance, generated IDs and
review metadata are intentionally re-created by the automated compiler. No
gold review is transferred as a model/human approval. Source-layer base records
are unmodified.

`draft_coverage_v1.py` is an offline oracle adapter separate from the compiler.
It does not extract from text and must never be counted as a prediction. DEV1
gold contains known answers, so this check measures representational coverage
only. **DEV1 is now tuning data and is no longer fresh validation.** Any later
DEV1 model run would be exploratory/tuning, not confirmatory.

## Proposed fresh DEV2 — 10 cases, not selected or executed

Use newly authored, original Japanese miniature stories in a different source
namespace, prepared by an independent annotator who has not tuned the draft.
Use ten separate story units instead of new windows from the original 30-chapter
corpus. This avoids source-family overlap with DEV1 and sealed M4 holdout without
opening holdout input/gold. Source ownership and non-overlap still require an
independent recorded attestation before any future run.

| Case blueprint | Capability |
| --- | --- |
| DEV2_01 | Unicode names, aliases and two mentions of one referent |
| DEV2_02 | Two similarly named people; unresolved placeholder, no guessed merge |
| DEV2_03 | Later explicit `SameAs` and earlier unresolved identity |
| DEV2_04 | Repeated exact quotation requiring occurrence; partial input window |
| DEV2_05 | Report/belief with embedded negated content, no world-truth leakage |
| DEV2_06 | Suggested internal state versus explicit narration and self-report |
| DEV2_07 | State starts/ends, named time and bound evidence learned later |
| DEV2_08 | Multi-evidence sufficient path, partial/corroborating distractors |
| DEV2_09 | Explicit cause versus adjacent events; event granularity and participants |
| DEV2_10 | Existing context reuse, context-only distractor and forbidden after-as-of citation |

Future protocol should seal independently authored canonical gold, record
completeness labels and preregister draft/schema/compiler/prompt/runtime hashes,
repair budget, terminal handling and selection/safety rules before generating
predictions. Lock raw drafts and compiled batches before gold access. A compiler
failure is a terminal structural failure, not permission for heuristic repair.
Evaluate compiled batches with unchanged Snapshot V2 semantics. Report compiler
success separately from assertion/grounding recall, epistemic accuracy,
entity/event resolution, unsupported severity and full-case success. Gold should
not be generated by the compiler being tested. Prompt/model changes after DEV2
gold access make DEV2 tuning data and require a new fresh development set.

This task proposes DEV2 only. It does not authorize a future provider run,
holdout access, extractor lock, M4-04C or M5.

## Reproduction and verification

Synthetic tests (no private input):

```bash
python -B -m unittest discover -s tests/story_extraction -p 'test_draft_compiler_v1.py' -v
python -B -m unittest discover -s tests/story_extraction -p 'test_m4_04b3a_forensics_v1.py' -v
```

Offline forensics and coverage, from the specified base checkout:

```bash
python -B -m tools.story_extraction.analyze_m4_04b3a_v1 \
  --private-root <authorized-DEV1-and-B2-artifact-root> \
  --source-root <frozen-M3-source-root>
```

The script reads only allowlisted B2 paths and DEV1 ZIP members, verifies raw and
final hashes, verifies DEV member hashes/input copies, checks freeze bindings,
and rechecks read artifact hashes before returning sanitized counts. It never
opens a holdout path. Real source text and gold/draft instances remain private.
The public result records full-suite outcomes and the final privacy/secret scan.
