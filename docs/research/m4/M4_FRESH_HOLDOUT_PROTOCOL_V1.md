# M4 Fresh Holdout Protocol V1

Status: **SEALED** (`M4_FRESH_HOLDOUT_V1`). Not a freeze of `STORY_EXTRACTION/v0`.

This document describes how the extraction holdout was selected, annotated and sealed, and how it must be
used. It contains no holdout content: no source text, no locators, no identifiers and no expected answers.
The sanitized record is `benchmarks/m4_extraction/M4_03_FRESH_HOLDOUT_SEAL_RESULT.yaml`.

**What the holdout can support:** fresh source-span validation within the same story and corpus.
**What it cannot support:** generalization to a new story, genre or language, or agreement with an
independent human annotator.

## 1. Freshness

A source span is *fresh* if its meaning has not been read, annotated, queried or audited in any earlier
task of this project. Freshness is about semantic exposure of the span, not about the story: the annotator
knows the story as a whole.

## 2. Semantic exposure registry

Before any candidate was looked at, every segment of the corpus was classified against the private record
of earlier work. A segment is *semantically exposed* if it was part of:

- a development extraction case (M4-02);
- a canonical-model mapping case (M2);
- a benchmark probe, fixture, audit or diagnostic passage (M1);
- a passage read during ingestion audits (M3-02);
- the first document, which was read in full.

Result: 1519 segments, 1251 exposed, 88 in the halo of an exposed segment, 180 neither.

## 3. Mechanical-use exception

Processing that never interprets meaning does not expose a span: hashing, segmentation, counting,
indexing, embedding and structural checks. Only reading or annotating content counts. Without this
exception no span would be fresh, since the whole corpus was ingested.

## 4. Selection hashing

Each eligible anchor segment is ordered by
`SHA-256(protocol id + corpus fingerprint + segment id)`. The order is fixed by the corpus and the protocol
id. No random state and no human choice enter the order.

## 5. Document diversity

Anchors are taken in hash order with at most one per document in the first pass. A second pass may add
one more per document only if the target of 12 cases is not reached. All 12 cases were selected in the
first pass, from 12 documents.

## 6. Case window

A case is the anchor plus up to three segments before and three after, clipped at the document boundary
and at the first exposed or halo segment. The halo is two segments on each side of an exposed segment. A
window needs at least five segments; windows of selected cases do not overlap. 146 anchors were eligible.

Every case is self-contained: all window segments are evidence-eligible, there are no context-only
passages and no prior canonical context.

## 7. Rejection and replacement

A candidate may be rejected only for a reason registered before any candidate was read:

| Reason | Meaning |
|---|---|
| `NO_STORY_CONTENT` | the window states nothing about the story |
| `PURE_PARATEXT` | the window is headings or author notes only |
| `SOURCE_CORRUPTION` | the text is damaged |
| `WINDOW_HAS_NO_IN_PROFILE_ASSERTION` | nothing in the window belongs to the profile |
| `WINDOW_DEPENDS_ON_EXCLUDED_CONTEXT_TO_BE_INTERPRETABLE` | the window cannot be understood on its own |

Difficulty, ambiguity and rarity are not reasons. A rejected case is replaced by the next unused anchor in
hash order. In V1 no candidate was rejected and nothing was replaced.

## 8. Selection lock

Order of events:

1. Exposure registry, selection protocol, ordered anchor list and annotation guideline written and hashed.
2. The 12 candidate windows read once, against the rejection criteria only.
3. Selection lock written and hashed.
4. Lock hashes committed publicly (`M4_03_HOLDOUT_SELECTION_LOCK_PUBLIC.yaml`).
5. Gold annotation started.

The gold build refuses to run if the lock or guideline hash differs from the committed value.

## 9. Gold completeness

The profile is exactly `STORY_UNDERSTANDING_CORE_V0`. Every case must be `COMPLETE_FOR_PROFILE`: each
eligible segment has a coverage note saying which required or optional assertions cover it and which
registered out-of-scope class covers the rest. A case that cannot reach this is kept and marked
`GOLD_COMPLETENESS_UNRESOLVED`, which fails readiness; it is never swapped for an easier one.

Gold assertions are either required or acceptable-optional. Where several evidence spans each suffice,
all are recorded as alternatives. Free-text literals carry accepted variants. Where the profile or the
predicate registry could not express stated content, the gap is recorded as a `HOLDOUT_PROTOCOL_ISSUE`
and left out of gold instead of being forced into a predicate.

The gold is an **agent draft**: written by an AI agent, labelled `AGENT_DRAFT_SEALED_GOLD` and
`NOT_HUMAN_CONFIRMED`, every assertion `UNREVIEWED`. No human approval is claimed.

All 12 cases passed 12 integrity checks, including conformance to the frozen Canonical Story Model v0,
evidence inside the case scope, and no evidence after the as-of boundary.

## 10. Separate input and gold packages

| Package | May be read by an extractor task | Contents |
|---|---|---|
| Input | yes | case scopes, ordered passage inputs and their flags, as-of positions, base source-layer subset, profile id |
| Gold | **no**, until predictions are locked | gold batches, required/optional split, completeness records, support alternatives, literal variants, categories |

They are separate archives with separate hashes and share no member. A check rejects the input package if
any gold field appears in it. A private blindness manifest records both hashes, the selection lock hash and
the access rule.

## 11. Evaluator snapshot

The scorer is bound as `M4_EVALUATION_PROTOCOL_SNAPSHOT_V1`
(`benchmarks/m4_extraction/M4_EVALUATION_PROTOCOL_SNAPSHOT_V1.yaml`): hashes of the evaluation protocol,
the evaluator, the batch contract and schema, their tests, and the profile definition. A test fails if any
of them changes.

If a scorer defect is found later, the snapshot is not edited. The defect is reported and a versioned
correction is run with an impact analysis.

## 12. Use and contamination

Required sequence, with no deviation:

1. Select and freeze the extractor, prompt and model settings.
2. Open the input package only.
3. Run all holdout cases.
4. Save predictions.
5. Hash and lock the prediction package.
6. Only then open the gold package.
7. Evaluate with the snapshot scorer.
8. Adjudicate pending unmatched predictions.
9. Report metrics.

The gold may not be used for prompt tuning, few-shot examples, model selection, or tuning of thresholds,
alignment or evaluation rules. If the gold is opened before the prediction package is locked, the holdout
is `CONTAMINATED` and cannot support a confirmatory M4 claim.

## 13. Limitations

- Same story, corpus and language as the development data.
- Gold written by the same AI agent that wrote the contract and the evaluator; not reviewed by a human.
- The annotator knew the story, though not these spans.
- Only 180 of 1519 segments were unexposed, so windows are short (5–7 segments) and long-range evidence
  is nearly absent.
- Category coverage is whatever the hash order produced: no case shows state change, causality or mixed
  paratext.
- Some cases have little required gold, because the text states things the registry cannot express.
- The selection lock is evidenced by a public commit made before annotation, not by an external timestamp.
- 12 cases give coarse case-level rates; one case is about 8 percentage points.
