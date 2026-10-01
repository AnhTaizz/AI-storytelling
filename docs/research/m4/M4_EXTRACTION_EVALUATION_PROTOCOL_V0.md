# M4 — Extraction Evaluation Protocol v0

Status: **REAL-SOURCE DEVELOPMENT CALIBRATED — NOT FROZEN.** Baseline from M4-01; calibrated on real-source development cases in M4-02. Pending Orchestrator review.

Companion to `M4_STORY_EXTRACTION_CONTRACT_V0.md`. Implemented in `tools/story_extraction/evaluate_extraction_v0.py` (`evaluate_extraction_v0/0.2.0`).

Calibration result: `benchmarks/m4_extraction/M4_02_REAL_SOURCE_DEV_CALIBRATION_RESULT.yaml`.

## 1. Evaluation Goals

- Judge an extraction against a gold extraction of the same source passages.
- Separate **missing** information from **invented** information.
- Never call a prediction a hallucination only because it is not in the gold.
- Never reward matching ids. Opaque ids differ between gold and prediction.
- Give one strict case-level endpoint next to the component metrics.
- State what the evaluator cannot decide, and route that to human adjudication.

**What has been done.** The protocol was exercised on 26 synthetic fixtures (M4-01) and on 14 real-source development cases with agent-drafted gold (M4-02). No extractor or model has been evaluated. No holdout exists.

## 2. Layers L0–L5

| Layer | Question | Checked by |
|---|---|---|
| L0 Structural validity | Is the batch valid, and does the merged document pass the frozen validator? | Batch validator (mechanical) |
| L1 Evidence grounding | Acceptable span, right role, sufficient support? | Evaluator, against gold evidence |
| L2 Atomic semantic correctness | Right predicate, arguments, polarity, epistemic status, validity? | Evaluator |
| L3 Referent and event structure | Mentions resolved correctly? Referents individuated as in gold? | Evaluator (alignment), human adjudication for granularity |
| L4 Coverage | Are the required commitments present? | Evaluator, against the gold required set |
| L5 Full case success | Everything required is right, and nothing material is invented | Derived from L0–L4, after adjudication |

A prediction that fails L0 is not scored further. It counts as a failed case.

## 3. Case Definition and Evaluation Modes

A real-source case declares, besides its gold batch:

| Field | Meaning |
|---|---|
| Extraction profile | What kind of facts the gold aims to contain (section 4) |
| Case objective | The specific understanding the case tests |
| Out-of-scope fact classes | What the gold deliberately leaves out |
| Required assertions | Must be recovered |
| Acceptable optional assertions | Correct if predicted; not required |
| Gold completeness | `COMPLETE_FOR_PROFILE`, `INCOMPLETE` or `UNCERTAIN` (section 10) |
| Narrow-span segments | Segments where only the exact gold span is accepted (section 6) |
| Literal variants | Accepted wordings of a free-text literal (section 9) |
| Adjudications | Reviewer decisions on predictions that match no gold assertion (section 11) |

Two modes:

| Mode | Used for | Unmatched prediction is |
|---|---|---|
| `SYNTHETIC_COMPLETE` | Synthetic fixtures whose gold is complete by construction | Unsupported, material |
| `REAL_SOURCE` | Real text | Pending adjudication, unless gold is `COMPLETE_FOR_PROFILE` |

## 4. Development Extraction Profile

`STORY_UNDERSTANDING_CORE_V0` is the profile used to build the development gold. It is an M4 evaluation and extraction profile. It is **not** a Canonical Story record, and it is not claimed to be universal.

**Includes** facts relevant to:

- event progression;
- identity and reference resolution;
- participant roles;
- state changes;
- relationship changes;
- knowledge and information flow;
- causality;
- location, possession and ownership;
- material emotion and intention.

**Excludes:**

- decorative wording;
- trivial syntactic facts;
- purely stylistic description;
- facts with no plausible downstream story use.

## 5. Semantic Alignment

Gold and prediction are built on the **same base canonical document**, so source segments are shared. Everything else is aligned by meaning.

| Record | Aligned by |
|---|---|
| Evidence reference | Source span, under the span rule of section 6 |
| Mention | Exact evidence span and surface form |
| Entity | Step 1: shared id from prior canonical context. Step 2: mentions resolved to it. Step 3: structural role (below). Same entity kind required |
| Event | Structural role with overlapping evidence; same event kind required |
| Event-time anchor | Through its event |
| Named-time anchor | Structural role |
| Placeholder proposition | Structural role |
| Proposition | Predicate and aligned arguments (section 7) |

**Structural role.** For every referent the evaluator collects the roles it plays: the predicate of an assertion, the argument path down to the referent (through embedded content too), the token and literal values next to it, and the evidence of that assertion. Validity bounds count as roles of their anchors. Two referents are candidates for alignment when they share roles with overlapping evidence. Editorial labels are never used.

**Why this is needed (Q2).** In the real development gold, all 9 case-local entities have no mention at all. Recurring characters come from prior canonical context and keep their ids. So alignment by mentions alone would align almost nothing.

Alignment is greedy by highest score, one to one, with ties broken by id so that it is deterministic.

- When two gold candidates tie and are **not** in the same identity class, the evaluator reports an **alignment ambiguity**. An ambiguous case needs human adjudication; the evaluator's choice must not be trusted.
- A referent that plays no role in any assertion cannot be aligned.
- This is not general graph matching.

**An event named only by a validity bound** (it starts or ends a state but has no assertion of its own) is aligned through its anchor.

## 6. Evidence Matching (Q1, Q9)

**Evidence identity stays exact.** Every evidence reference is an exact M3 span. The rule below is only about when two different spans are accepted as the same evidence during evaluation.

**Span rule.** A predicted span is accepted for a gold span when:

1. both are in the same `SourceSegment`; and
2. the predicted span contains the gold span.

Exceptions and limits:

- In a **narrow-span segment** only the exact gold span is accepted. A segment is narrow when the gold uses more than one evidence role in it (mixed heading, author note and prose), or when the case declares it.
- A predicted span **narrower** than the gold span is not accepted. If a narrower span is also sufficient, the gold lists it as an alternative.
- A span never crosses a segment. Evidence over several segments is several references.
- No overlap percentage is used.
- Mentions are matched by their exact span: a mention locates a surface form.

**Why containment was necessary.** In the development gold, 50 of 121 evidence references are strict sub-spans of their segment. Of 59 annotated ranges carried over from the earlier mapping, 17 crossed segment boundaries and became several references. An extractor that cites whole segments is equally right. Listing every boundary variant as a separate alternative is not practical.

**Grounding of an assertion (Q9).**

- Each independently sufficient path is its own `SUFFICIENT` set in the gold. Several sets are alternatives.
- A prediction is grounded when **one** of its `SUFFICIENT` sets matches **one** gold `SUFFICIENT` set: every gold span of that set is covered by a predicted span, and every predicted span covers a gold span of that set.
- A derivation matches a gold derivation with the same registered rule and the same premises.
- Valid spans that leave part of a gold set uncovered → `INSUFFICIENT_SUPPORT_MARKED_SUFFICIENT`.
- Any other mismatch → `WRONG_EVIDENCE_SPAN`.
- Two corroborating passages are not two sufficient sets. The frozen labels keep their meaning.

Support audit of the 98 required development assertions: 79 have one sufficient set, 13 have several, 6 are grounded by derivation only, 2 also carry a partial set, 3 a corroborating set. 40 sufficient sets contain more than one reference.

**Role.** A predicted evidence reference that matches a gold span must carry a role the gold gives that span → otherwise `WRONG_EVIDENCE_ROLE`.

## 7. Assertion Matching

**Proposition content.** A proposition matches on predicate, named arguments and their kinds, aligned referents, literal and token values, and the content of embedded propositions. Argument order and proposition ids do not matter. For a `SYMMETRIC` predicate the order of its arguments does not matter.

**Assertion.** A predicted assertion matches a gold assertion when proposition content and polarity are equal.

**State histories.** One proposition may be asserted several times with different validity (held, given away, held again). A predicted assertion is matched to the gold assertion with the same validity first, then to any unmatched one. This was a real defect found on development cases (section 14).

On a matched pair the evaluator compares epistemic status, validity bounds (anchors aligned) and grounding.

**Unmatched predictions** receive a mechanical hint, in this order:

1. same content as a gold assertion with the other polarity → `WRONG_POLARITY`;
2. content that gold holds only as said, believed or intended → `HOLDER_RELATIVE_TRUTH_LEAK`;
3. `Causes` or `Enables` → `INVENTED_CAUSALITY`;
4. a `RefersTo` for a mention gold resolves otherwise → `WRONG_ENTITY_RESOLUTION`;
5. otherwise → `UNSUPPORTED_ASSERTION`.

The hint is a suggestion to the reviewer. What happens next depends on the mode (section 11).

## 8. Identity and Event Structure (Q3, Q4)

**Identity classes (Q3).** Within one case, entities joined by an affirmed `SameAs` form one identity class. Only `SameAs` assertions inside the scope count. The batch validator rejects evidence after the as-of boundary, so a later resolution cannot leak in.

| Gold | Prediction | Verdict |
|---|---|---|
| One entity, two mentions | Two entities + `SameAs`, both mentions resolved | Equivalent. The extra `SameAs` is `EQUIVALENT_REPRESENTATION` |
| One entity, two mentions | Two entities, no `SameAs` | Not equivalent. The prediction has not identified them: `MISSING_ENTITY_RESOLUTION` |
| Two entities + `SameAs` (unknown, then identified) | One merged entity | Not equivalent. The gold's `SameAs` is a required assertion and is missed. The history of uncertainty is lost |
| Two entities + `SameAs` marked acceptable optional | One merged entity | Accepted |

A later `SameAs` never rewrites what was unknown earlier: an as-of scope that ends before the resolution contains no `SameAs`, and there the two entities are different.

Real evidence for Q3 is thin: the development gold contains no `SameAs`. The rule was checked on one constructed variant of a real case and on synthetic fixtures.

**Event granularity (Q4).** The evaluator scores commitments, not event objects. It does not require the same event records when the same required commitments are present. It cannot decide by itself whether a split or a merge is acceptable. That goes to adjudication:

| Reviewer outcome | Recorded as | Effect |
|---|---|---|
| `EQUIVALENT_FOR_CASE` | `EQUIVALENT_REPRESENTATION` | No failure; not counted in precision |
| `ACCEPTABLE_VARIANT` | `VALID_ADDITIONAL_ASSERTION` | No failure; counts as correct |
| `WRONG_EVENT_GRANULARITY` | `UNSUPPORTED_ASSERTION` with that failure code and a severity | Fails if the severity is material |

The reviewer looks at downstream effects: participants, occurrence, location, time, causality and state transitions. Sentence counts are not a criterion.

**Open edge.** When a prediction **merges** two gold events, required assertions appear as missed, and the evaluator has no mechanical way to accept that. Such a case must be reviewed by hand. This is unresolved.

**Named-time anchors and placeholders (Q5).** Both are aligned by structural role. The development gold has one named-time anchor and two placeholder propositions, so this is operational but lightly validated.

## 9. Free-Text Literals (Q6)

- Literals are compared **exactly**.
- A case may declare accepted variants: for a predicate and an argument, a list of wordings that count as the same value.
- Anything else goes to human adjudication.
- No fuzzy string threshold, embedding similarity or model judge is used.
- No language-specific normalization is added to Canonical Story.

Exact matching alone is not enough in practice: the development gold has 9 free-text literal arguments, and each is one annotator's wording of a source expression in another language. Explicit variants are the chosen remedy.

## 10. Gold Completeness (Q8)

**Gold completeness means complete for the declared extraction profile and case objective. It does not mean every true fact in the passage.**

Each case records one of:

| State | Meaning |
|---|---|
| `COMPLETE_FOR_PROFILE` | If an extractor emitted another true, in-profile assertion from this scope, the gold would already contain it |
| `INCOMPLETE` | Known to lack in-profile facts |
| `UNCERTAIN` | Not audited to that standard |

Only `COMPLETE_FOR_PROFILE` cases read an unmatched prediction directly as unsupported. In the development set, 4 cases are `COMPLETE_FOR_PROFILE` and 10 are `UNCERTAIN`.

**Annotation cost.** The 10 uncertain cases were converted mechanically from an earlier mapping that targeted one modelling feature each. Making them complete would mean re-annotating 116 eligible segments under the profile. That was not done.

## 11. Adjudication of Unmatched Predictions (Q7, Q8)

In `REAL_SOURCE` mode, a prediction that matches no gold assertion is **`GOLD_UNMATCHED_PENDING_ADJUDICATION`** until a reviewer decides. It is not reported as a hallucination.

| After review | Meaning | Effect |
|---|---|---|
| `VALID_ADDITIONAL_ASSERTION` | True and in profile; the gold lacked it | Counts as correct |
| `OUT_OF_SCOPE_ASSERTION` | True but outside the profile or case objective | Ignored |
| `EQUIVALENT_REPRESENTATION` | Same understanding in another form | Ignored |
| `UNSUPPORTED_ASSERTION` | Not supported by the source | Counted, with a severity |

**Severity of an unsupported assertion** is decided from its downstream effect on story understanding. It is not taken from the failure code, and the mechanical hint does not set it.

| Severity | Extraction meaning |
|---|---|
| `CRITICAL` | Would put a false plot-level fact into story memory: an event that did not happen, a wrong identity, a reversed fact |
| `HIGH` | Would change how a character, relationship, causal chain or knowledge state is understood |
| `MEDIUM` | A local false detail that later stages could repeat but that changes no relationship, cause or state |
| `LOW` | A trivial unsupported detail with no plausible downstream use |

**Material = `HIGH` or `CRITICAL`.** These levels were defined for extraction; they are not copied from the Script Quality Contract.

While a case has pending predictions, assertion precision, the unsupported count and the unsupported rate are **not reported** for it. Recall and grounding metrics are.

## 12. Metrics

Per case, and micro-aggregated over cases:

| Metric | Definition |
|---|---|
| Assertion Precision | (matched + valid additional) ÷ (predicted − out of scope − equivalent representation) |
| Assertion Recall | Required gold assertions recovered ÷ required gold assertions |
| Evidence Grounding Precision | Matched predictions with valid grounding ÷ matched predictions |
| Evidence Grounding Recall | Required gold assertions recovered with valid grounding ÷ required gold assertions |
| Epistemic Accuracy | Matched predictions with the gold epistemic status ÷ matched predictions |
| Evidence Role Accuracy | Predicted evidence references with a gold role ÷ predicted references that match a gold span |
| Referent Resolution Accuracy | Required gold `RefersTo` recovered ÷ required gold `RefersTo` |
| Unsupported Assertion Count and Rate | Adjudicated unsupported ÷ predicted |
| Pending count | Unmatched predictions awaiting adjudication |

- An acceptable optional assertion adds nothing to the recall denominator, is not unsupported, and must still be correctly grounded if predicted.
- A metric with an empty denominator is reported as not applicable.
- No single "accuracy" and no weighted combination is defined.
- Aggregated precision, unsupported rate and success rate are withheld while any case is pending.

## 13. Full Case Success

`FULL_CANONICAL_CASE_SUCCESS` for a real case:

| Outcome | Condition |
|---|---|
| `FAIL` | L0 fails; or a required assertion is missed; or a matched assertion has the wrong epistemic status, validity, grounding or evidence role; or an adjudicated unsupported assertion is material |
| `PENDING_ADJUDICATION` | No failure above, but at least one unmatched prediction is not adjudicated |
| `SUCCESS` | L0 passes; all required assertions recovered with correct attributes and acceptable grounding; nothing pending; no material unsupported assertion |

- Acceptable optional predictions never cause failure by being present or absent.
- A non-material unsupported assertion (`MEDIUM`, `LOW`) is counted and reported but does not fail the case.
- `DUPLICATE_ASSERTION` is reported and is not material.
- A pending case is neither a success nor a failure. It is not counted in a success rate.

## 14. Alignment Safety

Greedy alignment was stressed on the real development cases:

- every case as a perfect prediction with different ids and shuffled record order: 14 of 14 succeed;
- the same with the recurring characters removed from prior context, so that all entities are aligned structurally with no mention: 14 of 14 succeed;
- no alignment ambiguity in 67 dry-evaluation runs.

The stress found two defects. Both were classified `EVALUATOR_ALIGNMENT_DEFECT` and repaired before any holdout work:

| Defect | Cause | Repair |
|---|---|---|
| AD-1 | One proposition asserted over several validity intervals collided on the match key | Match by validity first (section 7) |
| AD-2 | An event named only by a validity bound was never aligned | Align it through its anchor (section 5) |

Limits that remain: greedy matching can be wrong where referents play very similar roles with overlapping evidence; ties are reported, not solved.

## 15. Dev / Holdout Discipline

- **All 14 real cases are development material.** They come from the earlier real-source mapping and from spans audited during ingestion validation. They are not a holdout and give no generalization evidence.
- Evaluation rules were calibrated on them. They must not be reused as confirmatory evidence.
- **No holdout passage has been selected and no holdout gold exists.**
- A fresh holdout uses newly selected source spans, chosen before any extractor is tuned, with gold sealed until the baseline and this protocol are fixed.
- The corpus is one story. A holdout from the same story tests unseen passages, not a new story.

## 16. Human Review

| Gold state | Recorded as |
|---|---|
| Drafted by an AI agent | `HUMAN_ANNOTATION`, `review.state: UNREVIEWED` |
| Reviewed by a human or signed off by the Project Owner | `CONFIRMED` or `CORRECTED`, `reviewer_kind: HUMAN`, with `human_review_record` |

- All development gold is `AGENT_DRAFT_GOLD` / `NOT_HUMAN_CONFIRMED`.
- Every adjudication exercised in M4-02 was made by the AI agent on controlled variants of the gold, not on model output. None is a human decision.
- Results computed against unreviewed gold must say so.

## 17. Outcome of the Nine Questions

| # | Question | Outcome | Rule |
|---|---|---|---|
| Q1 | Span tolerance | `RESOLVED` | Containment inside one segment; exact in narrow segments (section 6) |
| Q2 | Entities with no mention | `RESOLVED` | Prior identity, mentions, then structural role; ambiguity goes to a human (section 5) |
| Q3 | Identity representation | `PARTIALLY_RESOLVED` | Identity classes inside the scope (section 8). Thin real evidence |
| Q4 | Event granularity | `PARTIALLY_RESOLVED` | Routed to human adjudication (section 8). Merged events remain an open edge |
| Q5 | Named-time anchors, placeholders | `PARTIALLY_RESOLVED` | Structural role (section 8). One anchor and two placeholders in real gold |
| Q6 | Free-text literals | `RESOLVED` | Exact, plus case-declared variants (section 9) |
| Q7 | Materiality of unsupported | `RESOLVED` | Severity by downstream effect; material = HIGH or CRITICAL (section 11) |
| Q8 | Gold completeness | `RESOLVED` | Complete for profile; pending state (sections 10–11) |
| Q9 | Alternative groundings | `RESOLVED` | Several `SUFFICIENT` sets (section 6) |

No question is `DEFERRED_WITH_LIMITATION`. The three partial ones are operational and have an explicit route to human adjudication; none hides a blocker.

## 18. Known Limitations

1. Development gold is agent-drafted and unreviewed. No human adjudicated anything.
2. Ten of fourteen cases have `UNCERTAIN` completeness.
3. One story, one source, one language.
4. No model output has been scored. Real predictions may fail in ways the controlled variants did not cover.
5. Merged-event predictions are not handled mechanically.
6. A narrower-than-gold span is rejected unless the gold lists it.
7. Bound support (the evidence for a validity bound) is used for alignment but not scored as grounding.
8. Greedy alignment is not optimal matching.
9. Free-text gold literals are in the annotator's wording; variants must be listed by hand.
