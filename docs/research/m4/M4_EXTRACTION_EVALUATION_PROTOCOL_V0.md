# M4 — Extraction Evaluation Protocol v0

Status: RESEARCH BASELINE — TASK M4-01. Pending Orchestrator review. **Not frozen.**

Companion to `M4_STORY_EXTRACTION_CONTRACT_V0.md`. Implemented, as far as it can be made deterministic, in `tools/story_extraction/evaluate_extraction_v0.py` (`evaluate_extraction_v0/0.1.0`).

## 1. Evaluation Goals

- Judge an extraction against a gold extraction of the same source passages.
- Separate **missing** information from **invented** information. A high-recall extractor that hallucinates story facts is not good.
- Never reward matching ids. Opaque ids differ between gold and prediction.
- Give one strict case-level endpoint next to the component metrics.
- State what the evaluator cannot decide, and leave that to human adjudication.

No extractor was evaluated in M4-01. The protocol was exercised only on synthetic fixtures.

## 2. Layers L0–L5

| Layer | Question | Checked by |
|---|---|---|
| L0 Structural validity | Is the batch a valid batch, and does the merged document pass the frozen validator? | Batch validator (mechanical) |
| L1 Evidence grounding | Right span, right role, sufficient support? | Evaluator, against gold evidence |
| L2 Atomic semantic correctness | Right predicate, arguments, polarity, epistemic status, validity? | Evaluator |
| L3 Referent and event structure | Mentions resolved correctly? Entities and events individuated as in gold? | Evaluator (alignment) |
| L4 Coverage | Are the required story-relevant commitments present? | Evaluator, against the gold required set |
| L5 Full case success | Everything required is right, and nothing material is invented | Derived from L0–L4 |

A prediction that fails L0 is not scored further. It counts as a failed case.

## 3. Semantic Alignment

Gold and prediction are built on the **same base canonical document**, so source segments are shared. Everything else is aligned by meaning.

| Record | Aligned by |
|---|---|
| Evidence reference | Exact source span: segment and character range |
| Mention | Its evidence span and surface form |
| Entity | The set of mentions resolved to it through `RefersTo`; same entity kind required |
| Event | Event kind, and overlapping evidence of the assertions that name the event, including inside reported or believed content |
| Temporal anchor | Through its event (event-time anchors) |
| Proposition | Predicate and aligned arguments (section 4) |
| Records from prior canonical context | Their ids, which are shared through the base document |

Alignment is greedy by largest shared evidence, injective, with ties broken by id so that it is deterministic. It is not general graph matching. Records that cannot be aligned are reported as unaligned and never guessed.

## 4. Assertion Matching

**Proposition content.** A proposition matches on:

- predicate;
- named arguments and their kinds;
- aligned referents (entity, event, anchor);
- literal values and token values;
- the content of embedded propositions, recursively.

Argument order in the file does not matter. Proposition ids do not matter. For a predicate the registry marks `SYMMETRIC` (`SameAs`), the order of its two arguments does not matter. This is the same content notion the frozen validator uses for proposition uniqueness, with referents translated through the alignment.

**Assertion.** A predicted assertion matches a gold assertion when proposition content and polarity are equal. On a matched pair the evaluator then compares:

- epistemic status (over- or understatement);
- validity bounds, with anchors aligned;
- grounding (section 5).

**Unmatched predictions** are classified, in this order:

1. same content as a gold assertion with the other polarity → `WRONG_POLARITY`;
2. content that gold holds only as said, believed or intended → `HOLDER_RELATIVE_TRUTH_LEAK`;
3. `Causes` or `Enables` → `INVENTED_CAUSALITY`;
4. a `RefersTo` for a mention gold resolves otherwise → `WRONG_ENTITY_RESOLUTION`;
5. otherwise → `UNSUPPORTED_ASSERTION`.

All five count as unsupported assertions.

**Required and acceptable.** Each gold assertion is required, unless the case lists it as acceptable (correct but optional). Matching an acceptable assertion is not an error; missing one is not an error either.

## 5. Evidence Matching

- **Grounding is valid** when a predicted `SUFFICIENT` set, as a set of spans, equals one of the gold assertion's `SUFFICIENT` sets; or when a predicted derivation has the same rule and the same premises as a gold derivation.
- A predicted sufficient set that is a strict subset of a gold sufficient set → `INSUFFICIENT_SUPPORT_MARKED_SUFFICIENT`.
- Any other mismatch → `WRONG_EVIDENCE_SPAN`.
- **Role.** For every predicted evidence reference whose span exists in gold, the role must be one that gold gives that span → otherwise `WRONG_EVIDENCE_ROLE`.

Span comparison is exact in v0. That is appropriate for synthetic fixtures. A tolerance rule for real text is an open question (section 12).

## 6. Entity and Event Alignment

- **Entity resolution** is scored on `RefersTo` assertions: of the required gold resolutions, how many the prediction recovers.
- Splitting one gold entity into two shows up as a missing resolution plus a wrong one.
- **Event granularity** is an evaluation concern, not a solved problem. Mechanically, a split or merged event appears as missed and unsupported assertions. A reviewer relabels it `WRONG_EVENT_GRANULARITY`.
- An event record alone earns nothing. Only assertions are scored.

## 7. Metrics

Per case, and micro-aggregated over cases:

| Metric | Definition |
|---|---|
| Assertion Precision | Predicted assertions matched to gold (required or acceptable) ÷ predicted assertions |
| Assertion Recall | Required gold assertions recovered ÷ required gold assertions |
| Evidence Grounding Precision | Matched predictions with valid grounding ÷ matched predictions |
| Evidence Grounding Recall | Required gold assertions recovered with valid grounding ÷ required gold assertions |
| Epistemic Accuracy | Matched predictions with the gold epistemic status ÷ matched predictions |
| Evidence Role Accuracy | Predicted evidence references with a gold role ÷ predicted evidence references whose span exists in gold |
| Entity / Referent Resolution Accuracy | Required gold `RefersTo` assertions recovered ÷ required gold `RefersTo` assertions |
| Unsupported Assertion Count and Rate | Section 9 |
| `FULL_CANONICAL_CASE_SUCCESS` | Section 8 |

A metric with an empty denominator is reported as not applicable, not as 0 or 1. No single "accuracy" figure is defined, and no weighted combination.

## 8. Full Case Success

`FULL_CANONICAL_CASE_SUCCESS` is true for a case only if:

1. the prediction passes L0;
2. every required canonical commitment is recovered with the right polarity, epistemic status and validity;
3. the required grounding is valid, with the right roles;
4. no material unsupported commitment is added.

In v0 every failure code is material except `DUPLICATE_ASSERTION`. The gold has no severity information that would let the evaluator treat some unsupported assertions as harmless, so it does not.

This is intended as a key M4 endpoint. It is strict by design: partial credit lives in the component metrics.

## 9. Unsupported-Assertion Metric

```text
UNSUPPORTED_ASSERTION_RATE = predicted assertions matched to no gold assertion ÷ predicted assertions
```

- It is reported next to recall, never folded into it.
- A prediction with full recall and one invented fact has recall 1.0 and a non-zero unsupported rate, and fails the case.
- **Caveat.** "Unsupported" here means "not in the gold". A correct fact the gold author did not record is counted as unsupported. For synthetic fixtures the gold is complete by construction. For real text, unmatched predictions need human adjudication before the rate is reported as a hallucination rate.

## 10. Dev / Holdout Discipline

- **The private M2 real-source mappings are development evidence.** They were seen while the Canonical Story Model was designed. They must not be called an independent M4 holdout. They may be used as M4 development or contract-validation cases.
- **Development population** may include the M2 real-source cases, known M1 material, and any case inspected during earlier work.
- **Fresh holdout population** must use newly selected source spans that were not used to tune the extraction protocol, prompt or model.
- Holdout gold stays sealed until the extraction baseline and the protocol are fixed.
- No holdout case and no holdout answer was selected in M4-01.
- The validated corpus is one story. A holdout from the same story tests unseen passages, not a new story. This limit must be stated with any result.

## 11. Human Review

| Gold state | Recorded as |
|---|---|
| Drafted by an AI agent | `HUMAN_ANNOTATION`, `review.state: UNREVIEWED` |
| Reviewed by a human or signed off by the Project Owner | `CONFIRMED` or `CORRECTED`, `reviewer_kind: HUMAN`, with `human_review_record` naming the review |

- An agent-authored fixture is never labelled human-confirmed.
- Model predictions are `AUTOMATED_EXTRACTION` and `UNREVIEWED`. Scoring does not change that.
- Results computed against unreviewed gold must say so.
- All 26 synthetic fixtures in M4-01 have agent-authored, unreviewed gold.

## 12. M4-02 Fixture Plan

**Planned real-source case categories.** Quotas are not forced where the corpus does not support them.

`SIMPLE_EVENT`, `ENTITY_RESOLUTION`, `STATE_CHANGE`, `RELATIONSHIP_STATE`, `KNOWLEDGE_OR_BELIEF`, `REPORTED_INFORMATION`, `CONCEALMENT_OR_REVEAL`, `CAUSALITY`, `TEMPORAL_RELATION`, `LONG_RANGE_OR_MULTI_EVIDENCE`, `AMBIGUITY`, `MIXED_PARATEXT_PROSE`.

**Recommended extraction unit for later model runs.** Not one segment per call. A unit holds one or more evidence-eligible passages, limited adjacent context marked context-only, and optional prior canonical context. No size is fixed here.

**Steps proposed for M4-02** (not started):

1. Build development cases from material already seen, with gold as extraction batches against the private M3 source layer.
2. Select fresh holdout spans by a stated rule, before any extractor is tuned. Seal their gold.
3. Obtain human review of gold, or report results as against unreviewed gold.
4. Settle the open questions below on development cases only.

**Unresolved evaluation questions.**

| # | Question | Why it matters |
|---|---|---|
| Q1 | Span tolerance on real text: exact, overlap, or containment? | Exact equality will fail correct extractions that cut a sentence differently |
| Q2 | Entities with no mention (implied referents) | They cannot be aligned by mentions |
| Q3 | Identity classes: one entity with two mentions versus two entities joined by `SameAs` | Equivalent understanding, different records |
| Q4 | Event granularity differences | Currently scored as missed plus unsupported |
| Q5 | Named-time anchors and placeholder propositions | Not aligned in v0 unless they come from prior context |
| Q6 | Free-text literals (`emotion`, `condition`, `activity`) | Two wordings of one fact do not match |
| Q7 | Materiality of unsupported assertions | v0 treats all as material |
| Q8 | Completeness of real gold | Decides whether "unsupported" means "hallucinated" |
| Q9 | Alternative acceptable groundings | Gold must list every sufficient set it accepts |

None of these was settled by a heuristic in M4-01. Each is left open on purpose.
