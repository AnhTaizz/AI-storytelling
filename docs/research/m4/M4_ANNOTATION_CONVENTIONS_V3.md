# M4 Annotation Conventions V3

Status: `ACCEPTED` by the project owner on 2026-11-18 (DEC-028). Written by the agent in M4-04B3T. It replaces V2 (DEC-026). V2 stays unchanged as a record.

## 0. Changes from V2

| Rule | V2 | V3 | Evidence |
|---|---|---|---|
| **R-EVR-01** | Not stated. | See the dialogue mention rule in section 5. | FV2 uses `IN_WORLD_REPORT` for 6 refs in the content of dialogue statements. DEV1 and DEV2 use `DEPICTION`, including 5 refs in DEV2. |

**Caution about fitting.** The choice followed a review of disagreements in the FV2, DEV1 and DEV2 gold. All three are now development data. Only a fresh set can show whether the rule holds.

### Changes from V1 to V2 (kept for reference)

V2 settles the four points that the DEV2 gold audit (M4-04B3J) found unclear or questionable in V1. It also makes one rule explicit.

| Rule | V1 | V2 | DEV2 items |
|---|---|---|---|
| R-NAME-03 | The kind of a lone name is decided from the passages and prior context only. | General knowledge of naming in the source language may also decide it. Knowledge of the story may not. | 7 |
| R-ROLE-03 (new test 0) | Test 1 makes anything that "instigates" an event `AGENT`, so the role of an inanimate subject of an intransitive verb was unclear (a bell rings, a window closes). | An inanimate participant that changes nothing in another participant is `PATIENT` if the event changes it, otherwise `THEME`. | 1 |
| R-PLACE-01 (new id, section 4.2) | A movement's destination is never `OccursAt`. | The place of an arrival or appearance is `OccursAt`. The destination of going or heading somewhere is still not. | 1 |
| R-MEN-03 | Adjectives are left out of descriptive mentions. | Adjectives are kept; only modifiers containing a verb are left out. An adjective is often what tells two referents of one noun apart. | 3 |
| R-LIT-05 | Not stated. | A part of a date that the source does not state is never filled in. | (2 gold errors) |

**Caution about fitting.** Unlike V1, these changes were informed by reading the DEV2 gold, which is now tuning data. They are generalizations about the kind of case, not choices to make DEV2 score well: the 10 DEV2 items that are wrong under V1 stay wrong under V2. Only a fresh set (FV2) can show whether V2 holds.

## 1. Why this exists

M4-04B3I diagnosed the FV1 misses. 14 of the 41 missed required assertions, and all 13 missed resolutions, were disagreements about representation, not about facts:

- the registry lists participant roles and event kinds without defining them;
- the evaluator compares mention spans and literal values exactly (evaluation protocol, sections 5 and 9);
- the evaluator aligns events only when the event kind is the same.

So two annotators who agree on every fact can still disagree in the score. Each rule below picks one form where the registry allows several.

**Applies to:**

- the gold of every new sealed set (FV2 onward);
- the P4 extraction prompt (the next step);
- audits of existing gold that is already development data.

**Changes nothing in:**

- `canonical_story/v0` or `predicate_registry/v0.1`;
- Draft V1.1;
- evaluation snapshots V1 and V2, or the evaluator;
- any existing seal, locked prediction or recorded score.

It adds no predicate, vocabulary value or derivation rule, so the registry admission rule (`docs/research/m2/M2_PRE_FREEZE_REVIEW.md`, section 7) is not engaged. Every rule chooses among representations the registry already permits.

**How it was written.** The sources were:

- the registry;
- the Canonical Story documents (M2);
- the extraction contract and the evaluation protocol;
- the public B3I counts.

For V1, no gold was opened and no source text was read. This was deliberate: conventions fitted to one gold would hide that gold's errors. Where an existing gold disagrees, the audit in section 10 decides item by item whether the gold or the rule is wrong. V2 also used the DEV2 audit; see section 0.

**Language.** V2 is written for Japanese source text, which is the language of every M4 set so far. Other source languages need a later version.

## 2. Rule format

Each rule has an id and a check type:

- **MECHANICAL:** a program can verify it on a canonical batch together with its source text.
- **JUDGED:** it needs a reader.

## 3. Participant roles

### 3.1 Definitions

| Role | Meaning |
|---|---|
| `AGENT` | Performs or instigates the event, deliberately or not. An inanimate participant is `AGENT` only when it brings about a change in another participant (a lock that opens a door); see test 0 below. |
| `PATIENT` | An existing participant that the event acts on and changes: damaged, injured, healed, cleaned, cooked, woken, dressed, nursed. |
| `THEME` | Something the event transfers, moves, uses, creates, perceives or is about, without changing its state. |
| `SOURCE` | The previous holder in a `TRANSFER`, or the teller in a `REVEAL_TELL`. |
| `RECIPIENT` | Receives the object, the message, the information or the benefit: the new holder, the addressee, the learner, or the person something is done for. |
| `EXPERIENCER` | Perceives, feels or undergoes a mental state in the event without deliberately acting: notices, hears, is startled, feels pain. |
| `WITNESS` | Present and aware of the event, but takes no part in it. |

### 3.2 Rules

- **R-ROLE-01 (MECHANICAL).** One participant has at most one role in one event. Two `Participates` assertions for the same event and participant, with different roles, violate this rule.
- **R-ROLE-02 (MECHANICAL).** The role must be allowed by the frame of the event's kind (section 4.2).
- **R-ROLE-03 (JUDGED).** Where a frame allows several roles, take the first test that matches:
  0. is inanimate and changes nothing in another participant → `PATIENT` if the event changes it (a window closes, a lock opens), otherwise `THEME` (a bell rings, a light shines);
  1. instigates the event → `AGENT`;
  2. experiences it without acting → `EXPERIENCER`;
  3. is changed by it → `PATIENT`;
  4. receives something from it without being changed → `RECIPIENT`;
  5. is transferred, moved, used, created, perceived or talked about → `THEME`;
  6. is only present → `WITNESS`.
- **R-ROLE-04 (JUDGED).** Deliberate perception, such as looking or listening, is an act: the perceiver is `AGENT`. Perception that is not deliberate, such as seeing, hearing or noticing, makes the perceiver `EXPERIENCER`. In both cases the thing perceived is `THEME`.
- **R-ROLE-05 (JUDGED).** When an event is annotated, every participant that the cited evidence establishes is annotated as well. This includes a subject the passage leaves unspoken but makes clear. No participant is added from world knowledge.

## 4. Event kinds

### 4.1 Choosing the kind

- **R-EVT-01 (JUDGED).** Take the first kind that matches. Specific kinds come before general ones. The information kinds come first because the `REVEAL_RESULT` derivation depends on them.

  1. **`REVEAL_TELL`:** a character conveys a specific in-profile proposition to another character, and the annotation records that proposition with `Conveys`.
  2. **`REVEAL_DISCOVER`:** a character learns a proposition from story-world evidence (seeing, finding, reading something), with `Conveys`.
  3. **`REVEAL_INFER`:** a character works a proposition out by reasoning, with `Conveys`.
  4. **`ADDRESS_CHANGE`:** the source shows a character starting to use a different form of address for another character, either through the first use of the new form or a stated switch.
  5. **`TRANSFER`:** custody or ownership of an object passes from one holder to another: giving, lending, handing over, returning, receiving, or taking from someone. Picking up something nobody holds is not a transfer.
  6. **`ENCOUNTER`:** characters come into each other's presence, and the source presents that coming-together as the occurrence: meeting, running into someone, finding someone somewhere, someone appearing at the door.
     - What they then do together is a separate event.
     - Going somewhere together is not an encounter.
  7. **`UTTERANCE`:** a speech or writing act (saying, asking, calling out, writing a message) that is annotated without `Conveys`.
  8. **`MOVEMENT`:** a participant or an object changes location: going, coming, returning, entering, leaving, putting something somewhere.
  9. **`GENERIC`:** everything else.

- **R-EVT-02 (MECHANICAL).** `Conveys` is asserted only on `REVEAL_*` events. Every `REVEAL_*` event whose `Occurred` is asserted has at least one `Conveys`.
- **R-EVT-03 (JUDGED).** One speech act is one event. It is either `REVEAL_TELL` or `UTTERANCE`, never both.
- **R-EVT-04 (JUDGED).** An `ADDRESS_CHANGE` event is annotated together with the `AddressesAs` state it starts. That state's validity starts at the event's anchor.

### 4.2 Frames (allowed roles per kind)

| Event kind | Allowed roles | Notes |
|---|---|---|
| `GENERIC` | `AGENT`, `PATIENT`, `THEME`, `EXPERIENCER`, `RECIPIENT`, `WITNESS` | `RECIPIENT` here is the person something is done for. |
| `TRANSFER` | `SOURCE`, `RECIPIENT`, `THEME`, `AGENT`, `WITNESS` | The giver is `SOURCE`, never `AGENT`. `AGENT` is only a third party who makes the transfer happen between two others. The object is `THEME`. |
| `UTTERANCE` | `AGENT`, `RECIPIENT`, `WITNESS` | Speaker `AGENT`, addressee `RECIPIENT`, overhearer `WITNESS`. |
| `MOVEMENT` | `AGENT`, `THEME`, `WITNESS` | A self-mover is `AGENT`. When one participant moves another, the mover is `AGENT` and the moved person or object is `THEME`, including a carried person. |
| `ENCOUNTER` | `AGENT`, `THEME`, `WITNESS` | Whoever seeks out, approaches or arrives is `AGENT`. The person found or met without seeking it is `THEME`. When nobody seeks the meeting, every party is `AGENT`. |
| `ADDRESS_CHANGE` | `AGENT`, `RECIPIENT`, `WITNESS` | The speaker who changes the form is `AGENT`; the person addressed is `RECIPIENT`. |
| `REVEAL_TELL` | `SOURCE`, `RECIPIENT`, `WITNESS` | Teller `SOURCE`, learner `RECIPIENT`. |
| `REVEAL_DISCOVER` | `RECIPIENT`, `THEME`, `WITNESS` | Learner `RECIPIENT`; the object or trace that reveals the content is `THEME`. |
| `REVEAL_INFER` | `RECIPIENT` | The character who reasons it out is the learner, so `RECIPIENT`. |

In every `REVEAL_*` event, the character who comes to hold the content is `RECIPIENT`.

**Places of events (R-PLACE-01, JUDGED).** The location of an event, when stated, is `OccursAt`. For a `MOVEMENT`:

- **Arrival or appearance** (arriving at, reaching, appearing at, entering): the event happens at that place, so the place is `OccursAt`. Example: 駅に現れた gives `OccursAt` the station.
- **Going or heading somewhere** (going to, heading for, returning toward): the destination is not `OccursAt`. If the source also states that the mover got there, the destination is a `LocatedAt` state of the mover, starting at the movement.
- **Leaving** (leaving, going out of): the place left is `OccursAt`.

*Note.* An informal M2 example (`M2_CORE_CONCEPTS_AND_BOUNDARIES.md`, section 6) gives a carried person the role `patient`. That example states no event kind and predates these frames. Under these conventions, a carrying annotated as `MOVEMENT` gives the carried person `THEME`.

## 5. Mentions

The evaluator matches a mention by its exact span and surface form (evaluation protocol, section 5). These rules fix the span.

- **R-MEN-01 (MECHANICAL).** The surface form equals the quoted span. This is already enforced by Draft V1.1.
- **R-MEN-02 (MECHANICAL).** A name mention is the name as written, together with any honorific suffix attached to it (さん, くん, ちゃん, 様, 先輩, 先生 written as a suffix). Following particles are left out.
  - *Why the honorific stays:* M2 puts honorifics on mentions, not on identity (`M2_CANONICAL_STORY_MODEL_REQUIREMENTS.md`, S-4).
  - *Example:* in 山田さんが, the mention is 山田さん.
- **R-MEN-03 (JUDGED).** A descriptive mention is the noun phrase from its head noun back to its leftmost kept modifier.
  - **Kept:**
    - demonstratives (この, その, あの);
    - の-genitive chains and noun compounds;
    - adjectives in their plain attributive form (赤い, 古い), adjectival nouns with な (静かな), and prenominal adjectives (大きな, 小さな);
    - numerals with their counters (二人の, 三冊の).
  - **Left out:**
    - any modifier that contains a verb, or an adjective that is past or negative (昨日買った, 赤かった, 古くない);
    - everything to the left of such a modifier;
    - particles and the copula.
  - The span stays contiguous. If a left-out modifier stands between a kept modifier and the head, the span begins after the left-out modifier.
  - *Examples:*
    - 図書館の本を gives 図書館の本.
    - その古い本 gives その古い本.
    - 赤い鍵と青い鍵 gives 赤い鍵 and 青い鍵.
    - 昨日買った赤い本 gives 赤い本.
    - 彼の部屋の窓 gives 彼の部屋の窓.
- **R-MEN-04 (MECHANICAL).** A pronoun, or a kinship or role noun used to refer to someone (彼, 彼女, 俺, お前, 母), is the word itself plus any honorific attached to it.
- **R-MEN-05 (JUDGED).** A noun inside a longer mention, such as the possessor in a の-chain, gets its own mention only if its entity is an argument of an in-profile assertion of the case. No entity is created only for a nested noun.
- **R-MEN-06 (not settled).** V2 does not settle *which* expressions receive a mention. B3I found no disagreement there: every missed resolution was a disagreement about span.
- **R-EVR-01 (MECHANICAL).** The SUFFICIENT evidence of a RefersTo or NamedAs assertion whose span lies inside dialogue (inside a 「…」 region) has role DEPICTION, never IN_WORLD_REPORT, also when the sentence around it reports an event or fact. The mention records an act of referring that the scene shows, as the evidence for Says is DEPICTION of the utterance. The reported event or fact itself keeps IN_WORLD_REPORT (extraction contract, evidence-role hard contrasts).
  - *Example.* In 「銀鈴は物置にある」 (“The silver bell is in the storeroom”), the `RefersTo` evidence for both 銀鈴 and 物置 is `DEPICTION`. A `LocatedAt` assertion about the bell, if annotated as reported, has `IN_WORLD_REPORT` evidence.

## 6. Entity scope

- **R-SCOPE-01 (JUDGED).** The following are not entities:
  - body parts;
  - weather and other ambient conditions;
  - places that occur only inside a compound or a の-chain and play no role of their own.

  When such a thing matters to the profile, it is expressed as a literal about an in-scope entity or event: `PhysicalCondition` for an injured hand, `Manner` for walking in the rain. B3I adjudicated predictions of all three kinds as out of scope.

## 7. Literals

The literal arguments are:

| Predicate | Argument |
|---|---|
| `NamedAs` | `name` |
| `Manner` | `manner` |
| `PhysicalCondition` | `condition` |
| `EmotionToward` | `emotion` |
| `Habitually` | `activity` |
| `AnchorDate` | `date` |

- **R-LIT-01 (MECHANICAL).** A `STRING` literal is written in the source language and is never translated. Translation is a second wording decision and belongs downstream, in the pipeline.
- **R-LIT-02 (MECHANICAL).** A `STRING` literal is a verbatim substring of a `SUFFICIENT` evidence span of its own assertion. It uses the fewest whole words that express the value, inflected as written. There is no dictionary form and no lemmatization.
- **R-LIT-03 (JUDGED).** When no contiguous substring expresses the value, because it is implicit or split across the sentence:
  - the annotator writes the value in the source language, in dictionary form;
  - marks it `NON_VERBATIM` in the authoring notes;
  - declares the other accepted wordings as the case's `literal_variants` (evaluation protocol, section 9).

  The extractor is never shown the variants.
- **R-LIT-04 (MECHANICAL).** A `NamedAs` name is written exactly as in the source: same script, no honorific, no added or removed spaces.
- **R-LIT-05 (MECHANICAL).** A `DATE` literal uses ISO 8601:
  - `YYYY-MM-DD` for a full date;
  - `YYYY-MM` for a month;
  - `--MM-DD` when the year is not stated.

  A weekday alone, or a relative expression such as "the next day", is not a date. Such expressions are `TemporalRelation` between anchors.

  **No part of a date is ever filled in.** A year, month or day that the source does not state is not supplied from the story's setting, the current date or any other assumption. A checker can verify the format, but not this; it is checked by reading (JUDGED).

## 8. Names

- **R-NAME-01 (JUDGED).** Take each entity that is an argument of an in-profile assertion in the case. Each distinct name form of that entity written in an evidence-eligible passage gets one `NamedAs` assertion, supported by its first occurrence in the case. A `NamedAs` already asserted in prior context is not repeated.
- **R-NAME-02 (JUDGED).** Choose `name_kind` as follows:

  | `name_kind` | When |
  |---|---|
  | `FORMAL` | family and given name written together |
  | `FAMILY` | the family name alone |
  | `GIVEN` | the given name alone |
  | `NICKNAME` | an informal or shortened personal name |
  | `EPITHET` | a descriptive byname that the story uses as a name for the entity |
  | `TITLE` | a rank, office or title that the source uses as the standing name of one entity, not a one-off description |
- **R-NAME-03 (JUDGED).** Determine whether a lone name is `FAMILY` or `GIVEN` in this order:
  1. the case's passages and its prior context (for example, a full name given earlier);
  2. general knowledge of naming in the source language: a form that is clearly a given name (悠斗, 美月) or clearly a family name (佐藤, 高橋).

  Knowledge of the story itself is never used, even by an annotator who has it. If neither source decides, as with a form common as both a given and a family name, no `NamedAs` is emitted for that form.
- **R-NAME-04 (JUDGED).** Honorifics are not part of a name. How one character addresses another is `AddressesAs`, not `NamedAs`.

## 9. Time and possession

- **R-TIME-01 (JUDGED).** `TemporalRelation(subject, relation, object)` reads "subject relation object". Emit it only when the source states the order, through a temporal connective or explicit time words, never from discourse order (extraction contract, section 10).
- **R-TIME-02 (MECHANICAL).** The relation is never `AFTER`. Write `B BEFORE A` instead of `A AFTER B`, so that one fact has one form.
  - For `SIMULTANEOUS` and `OVERLAPS`, the subject is the anchor whose event the source mentions first.
  - For `DURING`, the subject is the shorter span, the one contained in the object.
- **R-POSS-01 (JUDGED).** The two possession predicates differ as follows:
  - `Possesses` is custody: the source says the holder holds, carries or has the object with them.
  - `Owns` is ownership: the object is presented as the holder's property.

  A possessive phrase alone (X の Y) can support `Owns`, but never `Possesses`.

## 10. Checking existing gold

The audit runs one check per rule type:

- **MECHANICAL rules** are checked on every gold record they apply to.
- **JUDGED rules** are checked first on the B3I disagreement items (14 convention misses, 13 resolutions), then on a fixed sample.

For each conflict, the audit records:

- the rule id;
- the gold item, which stays private;
- `GOLD_FOLLOWS` or `GOLD_DIFFERS`;
- a verdict: either the gold is wrong under the rule, or the rule is wrong for this case. A wrong rule leads to a new version of this document. It is never a silent edit.

Sealed gold is never rewritten. A rescoring of FV1 against aligned gold would be development-only and labelled that way; the M4-04B3H score stands. Development rescoring may use `align_mention_roles` to align a gold copy in memory and must be labelled development-only.

The MECHANICAL rules are V1's plus R-EVR-01. The checker is `tools/story_extraction/check_annotation_conventions_v2.py`.

**Current state of the existing sets:**

| Set | State |
|---|---|
| FV1 | Development data since M4-04B3H. Its private packages and the B3H/B3I outputs were produced in a cloud session and are not on the owner's machine, so they must be put back under a git-ignored directory first. |
| DEV2 | Gold opened and audited in M4-04B3J; it is tuning data. Under V2, 10 items are wrong and the 12 items that V1 left unclear or questionable conform. |
| Holdout | Annotated under its own sealed guideline (`annotation_guideline_sha256: 0340da09…`). The guideline was not read. Where V2 differs from it, a V2-guided extractor will lose points on the holdout for representation alone. This is a known risk and cannot be checked without touching sealed material. |

## 11. B3I causes and the rules that address them

| B3I cause (count) | Kind | Rules |
|---|---|---|
| `EVENT_NOT_ALIGNED` (7) | convention | R-EVT-01 (definition of `ENCOUNTER`) |
| `ROLE_LABEL` (5) | convention | R-ROLE-03, the frames in 4.2 (`TRANSFER` giver, `THEME` vs `PATIENT`) |
| `LITERAL_WORDING` (2) | convention | R-LIT-01 to R-LIT-03 |
| `MENTION_SPAN_DIFFERS` (13 resolutions) | convention | R-MEN-02 to R-MEN-05 |
| Out-of-scope predictions (7) | convention | R-SCOPE-01, R-MEN-05 |
| `NAMING_NOT_EMITTED` (12) | omission | R-NAME-01 to R-NAME-03; coverage itself is for P4 |
| `MISSING_PARTICIPANT` (3) | omission | R-ROLE-05 |
| `TEMPORAL_STRUCTURE` (5) | omission | R-TIME-01, R-LIT-05; coverage itself is for P4 |
| `OTHER_OMISSION` (7) | omission | none: a prompt and coverage matter |

## 12. Not settled by V3

- which expressions receive a mention (R-MEN-06);
- event granularity, which the extraction contract leaves open (section 9);
- choices among `Regard`, `Attitude` and `EmotionToward`;
- evidence roles of mentions in narration of an earlier time;
- source languages other than Japanese.

## 13. Versioning

After acceptance, any change goes in a new file (`..._V4.md`). When a sealed set's gold is authored under V3, the seal records this file's hash.
