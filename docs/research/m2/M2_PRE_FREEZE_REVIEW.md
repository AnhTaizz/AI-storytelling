# M2 — Canonical Story Model v0: Pre-Freeze Review

Status: FREEZE CANDIDATE — TASK M2-07. Pending Orchestrator review. **M2 is not frozen.** Not recorded in `DECISIONS.md`.

Candidate manifest: `benchmarks/m2_canonical_model/CANONICAL_STORY_V0_FREEZE_CANDIDATE.yaml`.

## 1. Purpose and Scope

M2-06 was accepted with no blocking model defect, but freeze was not authorized. Three conditions had to be met first:

1. promote the predicate vocabulary that real prose proved necessary;
2. correct `AddressesAs`;
3. enforce unique concrete Proposition content.

M2-07 implements exactly those three, re-validates the real-source panel against the **committed** contract, and prepares a hash-bound candidate. It does not freeze M2, does not start M3, and does not fix the known limitations in §8.

## 2. What Changed

| Area | Change | Kind |
|---|---|---|
| Schema `canonical_story/v0` | None | — |
| Registry | `predicate_registry/v0` → `predicate_registry/v0.1`; declares `compatible_schema_versions` | Version |
| Registry | Added `PhysicalCondition`, `EmotionToward`, `Intends`, `Owns`, `Habitually` | Additive |
| Registry | `Intends` added to holder-relative predicates | Additive |
| Registry | `BEHAVIOUR_SUGGESTS_STATE` may conclude `EmotionToward` | Additive |
| Registry | `AddressesAs` no longer declares `functional_on` | Correction |
| Validator | Duplicate concrete proposition content is rejected (`predicate_integrity`) | Stricter rule |
| Projection (`view_v0.py`) | None | — |

Predicate details are in `M2_CANONICAL_SCHEMA_V0.md` §4.

## 3. Promoted Vocabulary

Each predicate was needed by at least one real case in M2-06 and was shown to be additive there (in-memory probe). M2-07 commits the probe entries as they were tested, with one exception: the probe's setting-aware address predicate was **not** promoted (§4).

| Predicate | Real-source pressure | Gate |
|---|---|---|
| `PhysicalCondition` | A state with a late end bound was not representable at all | NONE |
| `EmotionToward` | Emotion evidence gradient (self-report, perception, behaviour, narration) did not fit `Regard` | INTERNAL_STATE |
| `Intends` | Intention is not belief; `Attitude` is doxastic | INTERNAL_STATE |
| `Owns` | Ownership and custody diverge when an item is lent; a lie about ownership could not be contradicted | NONE |
| `Habitually` | Recurring practice is a central fact that is neither one event nor a list of events | NONE |

No predicate was added beyond these five. No predicate was added to improve a rating during M2-07.

## 4. AddressesAs Correction

- **Problem.** `AddressesAs` was functional on (speaker, addressee). Real prose has two address forms for one pair that are both true, selected by social context. The view raised a false conflict diagnostic.
- **Decision (Orchestrator).** Remove `functional_on`. Do not add a `setting` argument.
- **Result.** Both forms are grounded assertions and appear as separate stages. No diagnostic is raised.
- **Recorded limitation.** The context that selects a form is not first-class in V0. The model states that each form is used; it does not state when.

## 5. Proposition Uniqueness

- **Problem (F-DUP-PROP).** Propositions have identity by content, but two records with the same content were accepted. Commitments on them were split, so one could be AFFIRMED while its twin stayed UNCOMMITTED.
- **Rule.** Within a document, two concrete Propositions must not share a content signature: predicate plus every named argument with kind and value. File order of arguments is irrelevant.
- **Exemptions.** Placeholders. Propositions that differ by stored id but refer to entities later joined by `SameAs` remain legal; the view merges them.
- **Evidence.** Negative fixture 20; seven uniqueness tests; the real-source document contains no duplicate, and an injected duplicate is rejected.

## 6. Validation Evidence

**Tests (no model, API or network).**

| Suite | Result |
|---|---|
| `tests/canonical_story` | 99 / 99 (79 before M2-07, 20 new) |
| `tests/story_benchmark` | 298 / 298 |
| `tests/story_ingestion` | 20 / 20 |

Synthetic cases A–J still pass. 20 negative fixtures are each rejected in the expected layer.

**Real-source panel, rebuilt against the committed registry v0.1.**

- 10 cases (3 simple, 4 medium, 3 difficult), same case inventory as M2-06. Source annotations were not changed to improve fit. The only migration was mechanical: committed predicate names replace probe names, and the probe's setting-aware address predicate is replaced by plain `AddressesAs`.
- Structural and semantic conformance: PASS.
- As-of checks: 54 / 54, including regression checks (no spoiler leak at four early positions, holder-relative content not canonical, multi-path availability, late end bound OPEN, signed secret unchanged).

| Rating | v0 registry (M2-06) | Committed v0.1 (M2-07) |
|---|---|---|
| NATURAL | 1 | 3 |
| ACCEPTABLE | 4 | 6 |
| AWKWARD | 4 | 1 |
| NOT_REPRESENTABLE | 1 | 0 |

| Case | Difficulty | v0 | v0.1 |
|---|---|---|---|
| CASE_REAL_01 | SIMPLE | NATURAL | NATURAL |
| CASE_REAL_02 | MEDIUM | AWKWARD | AWKWARD |
| CASE_REAL_03 | SIMPLE | NOT_REPRESENTABLE | NATURAL |
| CASE_REAL_04 | MEDIUM | ACCEPTABLE | ACCEPTABLE |
| CASE_REAL_05 | DIFFICULT | AWKWARD | ACCEPTABLE (borderline) |
| CASE_REAL_06 | MEDIUM | ACCEPTABLE | NATURAL |
| CASE_REAL_07 | DIFFICULT | AWKWARD | ACCEPTABLE |
| CASE_REAL_08 | DIFFICULT | ACCEPTABLE | ACCEPTABLE |
| CASE_REAL_09 | MEDIUM | AWKWARD | ACCEPTABLE |
| CASE_REAL_10 | SIMPLE | ACCEPTABLE | ACCEPTABLE |

Freeze-candidate gate: NOT_REPRESENTABLE = 0 and all three difficult cases NATURAL or ACCEPTABLE. **Both hold.**

**Judgement call to review: CASE_REAL_05.** The rating moved from AWKWARD to ACCEPTABLE because nothing false is asserted and no false diagnostic is raised. The model still omits which context selects each form, and an agreement to keep one form private. A stricter reader could rate it AWKWARD, which would fail the gate. The rating follows the precedent of CASE_REAL_04 (core facts natural, omissions recorded as known limitations). The same agent that built the mapping made this rating; it has not been independently reviewed.

CASE_REAL_02 stays AWKWARD. Its gaps (omission causation, focalization) are known limitations that this task was told not to fix.

## 7. Registry Governance

The schema and the registry are versioned separately. A frozen contract binds both versions and both hashes.

**Additive changes** (minor version, for example v0.1 → v0.2):
- a new predicate, vocabulary or vocabulary value;
- a new derivation rule;
- a new allowed conclusion predicate on an existing rule;
- adding a predicate to the holder-relative list at the moment it is introduced.

Documents valid under the old registry stay valid, and their views do not change.

**Breaking changes** (new major registry version, and an Orchestrator decision):
- removing or renaming a predicate, argument or vocabulary value;
- changing an argument's kind, entity kinds or vocabulary;
- changing classification, `stative`, `epistemic_gate`, or holder-relative status of an existing predicate;
- adding or widening `functional_on` on an existing predicate;
- raising a rule's `max_status` or relaxing its required premises;
- any change that makes a previously valid document invalid or changes a view of an unchanged document.

Removing `functional_on` (as done for `AddressesAs`) invalidates no document but does change diagnostics. It is treated as a **correction** and was allowed only because the contract is not yet frozen. After freeze it would count as breaking.

**Admission rule for a new predicate.** All of:
1. evidence from real source material that existing predicates cannot express the fact without distortion;
2. genre-neutral meaning;
3. a full declaration: arguments, classification, stative, directionality, `functional_on`, epistemic gate, and holder-relative status if it embeds a proposition;
4. at least one conformance test;
5. Orchestrator approval. Agents may propose, not approve.

Predicates must not be added to improve a benchmark rating.

## 8. Known Limitations (not fixed in V0)

| ID | Limitation |
|---|---|
| F-EXISTENTIAL-CONTENT | Vague or de dicto content fits only an unresolvable placeholder. Verdicts under-report safely. |
| F-RESOLUTION-PROPAGATION | `SameContent` resolution does not propagate into propositions that embed the placeholder. |
| F-CAUSATION-OMISSION | `Causes` takes events only; an omission or state cannot be a cause. |
| F-FOCALIZATION | Focalized narration forces a choice between narrator truth and the focal character's belief. |
| F-GATE-BY-ANNOTATION | The INTERNAL_STATE gate checks evidence roles and relies on annotation discipline; motives encoded as `Causes` are ungated. |
| F-SPEECH-ACTS | Requests, permissions and agreements are not propositions. Only assertive speech is modelled. |
| F-CONDITIONAL-BOUND | Conditional future end bounds are not expressible. |
| F-REPEATED-UTTERANCE | Repeated utterances of one claim collapse into one `Says` proposition. |
| Address context | The social context that selects an address form is not first-class (§4). |
| UNAWARE | Polarity-specific UNAWARE keeps its V0 semantics. **STATUS: PROVISIONAL / NOT REAL-SOURCE VALIDATED.** |
| Inherited | Single discourse stream; no story-time slicing of verdicts; no temporal closure; reliable-narration assumption; unreliable narration, hypotheticals, arcs and themes deferred. |

## 9. Validation Coverage

Validation currently covers one 30-chapter story in one genre and one primary human/agent annotator. Freeze means a stable V0 engineering contract, not universal narrative ontology completeness.

Further limits on the evidence:
- Fit ratings are judgements by the annotating agent, not independently reviewed.
- The panel has 10 cases. It never exercised UNAWARE, unreliable narration, or more than one discourse stream.
- Free-text literals (`condition`, `emotion`, `activity`) are not normalized, so two wordings of one fact are different propositions. The uniqueness rule cannot catch that.

## 10. Freeze Recommendation

**Recommendation: the candidate is ready for Orchestrator freeze review.**

- The three pre-freeze conditions are implemented and tested.
- The real-source gate passes against the committed contract, with one borderline rating disclosed in §6.
- No blocking model defect is known.

Decisions that remain with the Orchestrator:
1. accept or re-rate CASE_REAL_05;
2. accept the registry governance policy in §7;
3. decide whether to freeze `canonical_story/v0` with `predicate_registry/v0.1`, and record it in `DECISIONS.md`.

Until then M2 stays IN PROGRESS and M3 does not begin.
