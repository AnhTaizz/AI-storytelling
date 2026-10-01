# Script Quality Contract v0

Status: CANDIDATE — pending Orchestrator review. **Not frozen.** Not recorded in `DECISIONS.md`.

Contract identity: `SCRIPT_QUALITY_CONTRACT/v0`

Machine-readable companion: `benchmarks/m1_script_quality/SCRIPT_QUALITY_CONTRACT_V0_CANDIDATE.yaml`

## 1. Purpose

This contract answers one question: **what must a high-quality, grounded storytelling script satisfy?**

Three things are kept separate throughout:

| Thing | Meaning | Status in this document |
|---|---|---|
| Quality contract | What a good script must satisfy | Defined here (sections 3–16, 18) |
| Evaluation procedure | How people and tools measure it | Partly standardized (sections 17, 19) |
| Validator implementation | Whether a given critic actually detects violations | Evidence only (section 21). Not part of the standard |

The contract states desired quality. It does not describe what the current Writer or any current critic achieves. A requirement is not weakened because today's tools miss violations of it.

## 2. Scope

**In scope.** A narrated storytelling script (the first product output is a YouTube script) produced from long-form narrative source material, for a stated request.

**The request** is what the script is judged against. It consists of:

- `requested_scope`: the part of the story to be told, and the story point up to which information may be used;
- the **truth boundary** (defined below);
- the Narrative Profile, including target language, length target and spoiler policy (section 3).

**Truth boundary.** The authorized, evidence-grounded story understanding for the requested scope. In M1 experiments it was the source chapter or a Story Brief. Later it may be a view over the Canonical Story Model. The contract does not depend on which.

- Story truth is judged against the truth boundary, not against a reviewer's memory of the work and not against knowledge from outside the boundary.
- If the boundary itself misstates the source, that is an upstream defect (`SOURCE_GROUNDING_FAILURE`), recorded separately from Writer errors.

**Out of scope.** Visual production, voice, thumbnails, titles, SEO, and the quality of the story understanding pipeline itself.

## 3. Quality Contract vs Narrative Profile

The Quality Contract says presentation must be **grounded, coherent, natural and engaging**. It does not say in which style.

The Narrative Profile (a later decision) chooses, per channel or request:

- narration person and channel voice;
- tone and humor level;
- commentary intensity;
- compression level and target duration or length;
- hook style;
- spoiler policy;
- target language and audience.

Consequences:

- No channel style is part of this contract. The M1 runs used one style (casual spoken Vietnamese for a young audience, 900–1100 words). That is a profile, not a standard.
- Soft dimensions are judged for **appropriateness and effectiveness under the profile**, not for quantity. A script with no humor is not worse if the profile or the material does not call for humor.
- Where the profile sets a hard constraint (language, length, spoiler policy), compliance is part of this contract (sections 8, 11, 12).

## 4. Factual Grounding Contract

### 4.1 Claim types

Every sentence of a script is read as one or more claims. Each claim has one type:

| Claim type | Meaning | Acceptable? |
|---|---|---|
| `SUPPORTED_FACT` | States or paraphrases something the truth boundary establishes | Yes |
| `SUPPORTED_INFERENCE` | Follows from the boundary and is presented no more strongly than the boundary warrants | Yes |
| `ATTRIBUTED_REPORT` | Something a character or the story world says, believes or rumours, presented as theirs | Yes |
| `COMMENTARY_RHETORIC` | The narrator's own reaction, evaluation, joke, question or figure of speech, addressed to the audience | Yes |
| `UNSUPPORTED_STORY_CLAIM` | Asserts something about the story world that the boundary does not establish | No |
| `STRENGTHENED_STORY_CLAIM` | Asserts more certainty, frequency, degree or scope than the boundary establishes | No |
| `CONTRADICTED_STORY_CLAIM` | Conflicts with the boundary | No |
| `UNDETERMINED` | The reviewer cannot decide from the boundary | Triggers review (section 16) |

### 4.2 Story claim test

A sentence makes a **story claim** if it asserts any of the following, whatever its tone:

- that something happened, or how it happened;
- what a character did, said, perceived, felt, thought, wanted, intended, believed or knew;
- a property, state, location, possession or relationship of a character or thing;
- that one thing caused or led to another;
- how often, how much, or how certainly something is the case;
- what will happen later.

A sentence is **commentary or rhetoric** only if all of these hold:

1. it is the narrator speaking to the audience, not narrating the story world;
2. a listener would not take it as a literal story fact;
3. removing it would lose no story information.

Neutral examples:

| Sentence | Reading |
|---|---|
| "This was the moment everything changed." | Commentary. The narrator's framing. Acceptable if in-scope events support it |
| "He knew his life would change forever." | Story claim about a character's knowledge. Needs support |
| "Honestly, who lends an umbrella and just walks off?" | Commentary (rhetorical question about a supported event) |
| "She was always being bothered by classmates." | Story claim. "Always" asserts frequency. Needs support |
| "The rain was coming down like the sky had a grudge." | Rhetoric, if rain is supported. The figure adds no story fact |
| "She sat curled up, shivering." | Story claim about posture and physical state. Needs support |

Intensifiers and figures of speech are not automatically safe. If a figure changes the degree, frequency, scope or certainty of a story fact, it is a story claim.

### 4.3 Hard invariants: grounding

- `SQ-INV-01` **No unsupported story claim.** A script must not assert a story-world fact that the truth boundary does not support.
- `SQ-INV-02` **No contradiction.** A script must not contradict the truth boundary, including concrete details (appearance, names, places, quantities).
- `SQ-INV-03` **No invented causality.** A script must not assert a cause, reason or consequence the boundary does not establish, and must not alter an established causal chain.
- `SQ-INV-04` **No invented internal state.** Motives, intentions, emotions, thoughts and traits may be stated as fact only when the boundary establishes them. Observed behaviour does not license a stated motive or intention.

## 5. Epistemic Contract

A script must preserve the difference between what is established, what is inferred, what is only reported, and what is unknown.

### 5.1 Strength ordering

The following distinctions are meaningful and must not be collapsed upward:

| Kind | Weaker → stronger |
|---|---|
| Belief | appears / seems → suspects → believes → knows |
| Likelihood | might → probably → will → certainly |
| Volition | (behaves as if) → wants → intends |
| Frequency and scope | once / some → often / many → always / everyone |
| Source | rumoured / said → established |

**Rule.** The Writer may weaken certainty for natural language. The Writer must not strengthen source uncertainty without support.

### 5.2 Hard invariants: epistemic

- `SQ-INV-05` **No strengthening.** A script must not turn possibility into certainty, concern into prediction, some into all, or once into always. Choosing one branch of an either/or statement in the boundary is strengthening.
- `SQ-INV-06` **No knowledge overclaim.** A script must not present a character as knowing or perceiving something the story does not establish they know at that point. "Seemed troubled to him" does not support "he knew something was weighing on her".
- `SQ-INV-07` **Attribution preserved.** Hearsay, reputation, a character's self-report and a character's belief stay attributed. A script must not restate them as narrator fact. An unknown stays unknown.

### 5.3 Guidance

- **Self-report versus story truth.** What a character says about themselves is a report. It may be narrated as what they said. It becomes fact only if the boundary establishes it independently.
- **Inferred motive.** A hedged narrator inference ("maybe he just didn't want the hassle") is commentary if clearly the narrator's guess. Stated flatly ("he didn't want the hassle") it is a story claim.
- **Hidden intention.** Attributing an unstated plan or wish to a character from their behaviour is a story claim and needs support.
- **Conceptual alignment with Canonical Story Model v0.** The frozen model separates explicit, entailed and merely suggested content, and separates what is asserted from what a character says or holds. This contract uses the same distinctions at the script level: suggested content must be presented as suggested; said or believed content must stay attributed. The contract does not depend on that model's implementation.

## 6. Temporal / State Contract

Two orders are distinct:

- **Story chronology:** the order and timing of events in the story world.
- **Narrative presentation order:** the order in which the script tells them.

A script may reorder presentation (open with a hook, rewind, return). It may not rewrite story chronology.

Hard invariants:

- `SQ-INV-08` **Chronology preserved.** After any reordering, a listener must be able to recover the true order of events. A script must not state or imply a different order, duration or timing than the boundary establishes.
- `SQ-INV-09` **State as of the narrated point.** Location, possession, physical condition, emotional state and knowledge state must be correct for the story point being narrated, and consistent within a scene. A script must not describe an earlier point using a later state.
- `SQ-INV-10` **Identity and relationship as of the narrated point.** Who a character is, and how two characters stand to each other, must match what is established at that point. A later relationship state must not be projected backwards.

Retrospective narration (a narrator looking back) is allowed only within the limits of section 8.

## 7. Coverage Contract

Coverage is relative to the request. There is no universal percentage.

An item is **narratively necessary** for the requested scope if leaving it out would change what the audience understands. Factors:

- it is a cause of something the script does tell;
- it changes a character's state, knowledge or a relationship;
- it is a reveal within scope;
- it is setup that an in-scope payoff depends on;
- the request names it (a selected character, topic or arc).

Hard invariant:

- `SQ-INV-11` **Necessary information present.** A script must not omit narratively necessary information for the requested scope, and compression must not change the meaning of what remains.

**Intentional compression** drops or merges material that is not necessary, and leaves the audience's understanding intact. **Missing necessary information** leaves a later event unmotivated, a state change unexplained, or a character's behaviour misread. Only the second is a violation.

## 8. Spoiler Contract

Terms:

- `requested_scope`: the story range the script covers and the story point up to which information is authorized.
- `allowed_retrospective_narration`: whether the narrator may frame events with hindsight. Hindsight may only use information inside `requested_scope`.
- `spoiler_mode`: `NONE` by default. A request may explicitly authorize spoilers up to a stated point.

Default: **information beyond the requested story scope must not be introduced.**

Hard invariant:

- `SQ-INV-12` **No future-information leak.** A script must not state, imply or confirm story facts beyond `requested_scope` unless the request explicitly enables a spoiler mode that covers them.

Clarifications:

- A tease that asserts no specific future fact ("at least, that's how it looked then") is not a leak.
- A statement that asserts a future development ("this was the start of a long story between them") is a leak if that development lies beyond scope, and an unsupported claim if the boundary does not establish it.
- Knowledge about the work from outside the truth boundary counts as beyond scope.
- This is the script-level counterpart of as-of semantics in the Canonical Story Model. No specific implementation is required.

## 9. Safe Creative Freedom

The contract does not ask for dry source paraphrase. A script that is accurate and dull fails the product goal as surely as one that is lively and wrong.

> **Engagement may increase through presentation transformation, not through factual mutation.**

**Allowed creative transformation**, provided story truth is unchanged:

- reordering supported events;
- hooks, cold opens and rewinds;
- compression and merging of non-necessary material;
- transitions and signposting;
- humor and narrator reactions;
- commentary and evaluation by the narrator;
- analogy, metaphor and other figures recognisable as figures;
- emphasis and rhythm;
- rhetorical questions;
- callbacks to supported earlier material;
- spoken-language phrasing and paraphrase.

**Forbidden factual mutation:**

- inventing events;
- inventing motives, intentions or internal states;
- inventing physical action or staging as fact;
- inventing causality;
- inventing character knowledge;
- changing chronology;
- strengthening frequency, degree or certainty;
- restating reports as fact;
- spoiling future facts.

Hard invariant:

- `SQ-INV-13` **Commentary carries no story claim.** Commentary, humor and rhetoric must not be used to introduce story facts. Anything that passes the story claim test (section 4.2) is judged as a story claim.

**On the observed entertainment–fidelity tension.** In H1, the run with the stronger hook, commentary and conversational style also showed more exaggeration and drift (`OBSERVED_ENTERTAINMENT_FIDELITY_TENSION`). That was one run pair. It does not show that the two goals inherently trade off. The contract's position is that they are separable: the allowed list above is where engagement comes from.

## 10. Narrative Quality Dimensions

These are soft dimensions. Each is judged for appropriateness and effectiveness under the Narrative Profile, on the rubric in section 17. A dimension may be marked `NOT_APPLICABLE`.

| Dimension | What is judged | May be N/A |
|---|---|---|
| `HOOK_STRENGTH` | Does the opening give a reason to keep listening, in the profile's style, without misrepresenting the story? | No |
| `NARRATIVE_FLOW` | Is the script organized around beats rather than source order, with clear transitions and a recoverable timeline? | No |
| `PACING` | Does time spent match importance? Does the script reach the inciting situation without padding and without rushing payoffs? | No |
| `EMOTIONAL_IMPACT` | Do the emotional beats the material supports land, without being inflated? | Yes, if the material has none |
| `HUMOR_COMMENTARY_QUALITY` | Is commentary specific to the story, in voice, and at the intensity the profile asks for? | Yes |
| `CALLBACK_QUALITY` | Are setups and payoffs within scope connected? | Yes |
| `NARRATION_NATURALNESS` | Does it sound natural read aloud in the target language and register? | No |
| `OVERALL_USEFULNESS` | Could a creator use this as the script, given the editing it needs? | No |

Not every script needs humor, commentary in every passage, or a dramatic hook. More is not better.

## 11. Compression / Length Compliance

Length is a request constraint, not a universal standard. The 900–1100 word range in M1 runs belongs to those requests.

Hard invariant:

- `SQ-INV-14` **Length compliance.** The script must meet the requested length or duration target within the tolerance the request defines.

Rules:

- If the request gives a range, the range is the tolerance.
- If the request gives only a target, the default tolerance is ±10%. A Narrative Profile may override it.
- The counting method must be stated with the result. M1 recorded two different word counts for the same script under two methods.

**Mechanical length compliance is not good pacing.** M1 showed both directions: a script inside the range can still be padded early and rushed late, and a script that restores the range by trimming can improve pacing or damage it. Length is checked mechanically. Pacing is judged under section 10.

## 12. Output Integrity

Hard invariants:

- `SQ-INV-15` **Target-language integrity.** The script is in the requested target language and register, with no unexpected script contamination.
- `SQ-INV-16` **Clean deliverable.** The script contains only the deliverable: no meta-instructions, prompt echoes, analysis, debug text, placeholders, or malformed structure.

**Unexpected script contamination** means a token written in a writing system that the target language does not use, and that is not justified. Justified cases:

- proper nouns and titles kept in their original form by request or profile;
- quoted source terms that the script explains;
- loanwords and notation that are normal in the target language.

A mechanical detector can **flag** tokens in unexpected Unicode scripts. A flag is not a violation until the justified cases are ruled out. A rule of the form "only characters of language X" is not part of this contract.

M1 observed unjustified single-token contamination in two runs (two different foreign scripts in otherwise fluent output).

## 13. Failure Taxonomy

One hierarchy replaces the provisional list and the H6b residual families. A finding is recorded with the most specific applicable ID. Each ID appears once.

**Integrity categories**

| Category | Subtypes | Gate |
|---|---|---|
| `FACTUAL_ERROR` | — | `GATE_FACTUAL_GROUNDING` |
| `UNSUPPORTED_INVENTION` | `UNSUPPORTED_EVENT`, `UNSUPPORTED_ACTION_OR_STAGING`, `PHYSICAL_OR_EMOTIONAL_STATE_INVENTION`, `MOTIVE_OR_INTERNAL_STATE_INVENTION`, `HIDDEN_INTENTION_INFERENCE` | `GATE_FACTUAL_GROUNDING` |
| `CAUSALITY_ERROR` | `CAUSALITY_INVENTION`, `CAUSALITY_DISTORTION` | `GATE_FACTUAL_GROUNDING` |
| `SOURCE_GROUNDING_FAILURE` | `OUT_OF_BOUNDARY_KNOWLEDGE`, `BOUNDARY_FIDELITY_DEFECT`, `UNTRACEABLE_CLAIM` | `GATE_FACTUAL_GROUNDING` |
| `EPISTEMIC_ERROR` | `CERTAINTY_INFLATION`, `EPISTEMIC_KNOWLEDGE_OVERCLAIM`, `REPUTATION_OR_FREQUENCY_STRENGTHENING`, `ATTRIBUTION_LOSS` | `GATE_EPISTEMIC_INTEGRITY` |
| `TEMPORAL_ERROR` | `CHRONOLOGY_ERROR`, `ANACHRONISTIC_STATE` | `GATE_TEMPORAL_STATE_INTEGRITY` |
| `CHARACTER_STATE_ERROR` | `SCENE_STATE_INCONSISTENCY` | `GATE_TEMPORAL_STATE_INTEGRITY` |
| `RELATIONSHIP_ERROR` | — | `GATE_TEMPORAL_STATE_INTEGRITY` |
| `PREMATURE_SPOILER` | — | `GATE_SPOILER_DISCIPLINE` |
| `MISSING_IMPORTANT_EVENT` | — | `GATE_NECESSARY_COVERAGE` |
| `OUTPUT_INTEGRITY_FAILURE` | `OUTPUT_LANGUAGE_CORRUPTION`, `OUTPUT_ARTIFACT` | `GATE_OUTPUT_INTEGRITY` |
| `REQUEST_NONCOMPLIANCE` | `LENGTH_NONCOMPLIANCE`, `SCOPE_NONCOMPLIANCE` | `GATE_REQUEST_COMPLIANCE` |

**Narrative categories** (no gate; they inform soft dimensions and edit cost)

| Category | Subtypes |
|---|---|
| `WEAK_HOOK` | — |
| `NARRATIVE_STRUCTURE_WEAKNESS` | `MISSED_CALLBACK`, `MISSED_FORESHADOWING` |
| `POOR_PACING` | `OVER_COMPRESSION`, `UNDER_COMPRESSION` |
| `FLAT_EMOTIONAL_PAYOFF` | — |
| `GENERIC_COMMENTARY` | — |
| `STYLE_MISMATCH` | — |
| `OTHER` | — |

Notes on the unification:

- The eight H6b residual families are all subtypes here. Three sit under `EPISTEMIC_ERROR`, four under `UNSUPPORTED_INVENTION`, one under `CAUSALITY_ERROR`.
- `ATTRIBUTION_LOSS` is new. H2 observed hearsay flattened into fact, which no earlier category named.
- `SCENE_STATE_INCONSISTENCY` and `OUTPUT_LANGUAGE_CORRUPTION` were used in RUN_0001 but were missing from the provisional list.
- `SOURCE_GROUNDING_FAILURE` now means a defect in the evidence chain itself: a claim taken from outside the boundary, a boundary that misstates the source, or a claim that cannot be traced at all.
- `OVER_COMPRESSION` becomes `MISSING_IMPORTANT_EVENT` when what was lost is narratively necessary.

**Mapping from H6b claim classes.** `UNSUPPORTED` → `UNSUPPORTED_STORY_CLAIM`. `STRONGER_THAN_BRIEF` → `STRENGTHENED_STORY_CLAIM`. `CONTRADICTS_BRIEF` → `CONTRADICTED_STORY_CLAIM`. `QUESTIONABLE` → `UNDETERMINED`. `CREATIVE_BUT_SAFE` → `COMMENTARY_RHETORIC`, but only if it passes the test in section 4.2. H6b showed that the "creative but safe" label absorbed real staging and internal-state inventions.

## 14. Severity Model

Severity measures **narrative impact**: how much the audience's understanding of the story is changed, or how much the deliverable is damaged. It is not set by category alone.

| Level | Definition | Typical cases |
|---|---|---|
| `CRITICAL` | The audience leaves with a false plot-level belief, or the deliverable is unusable | Fabricated or missing major event; false identity or relationship; chronology reversal of plot events; leak of a major reveal; output largely in the wrong language |
| `HIGH` | The interpretation of a character, scene or causal chain is materially changed | Wrong cause for a key event; knowledge overclaim that changes who knows what; material state error; omitted setup that a payoff needs; leak of a lesser future fact |
| `MEDIUM` | A real but localized change to story truth, or a defect needing a deliberate edit | Unsupported motive or intention; certainty or frequency strengthening; lost attribution; local state slip; contamination token; length outside tolerance |
| `LOW` | Localized and does not change interpretation | Minor unsupported gesture or staging; small wording issue; slight style mismatch |

Rules:

- The reviewer assigns severity by impact and states the reason. Category gives a starting point, not the answer. An invented shrug is `LOW`. An invented action that the plot later depends on is not.
- **Cumulative escalation.** Many `MEDIUM` findings of one kind can together change how a character or scene is understood. The reviewer may escalate the set to `HIGH` with a stated reason. No numeric density threshold is fixed in v0.
- H6b severity labels are **not** inherited. H6b used three levels, and critic-versus-reference severity agreement was about half. Those labels were assigned per family under a different procedure.

## 15. Hard Gates

A hard gate is an integrity requirement that narrative quality cannot compensate for.

| Gate | Invariants | Fails on |
|---|---|---|
| `GATE_FACTUAL_GROUNDING` | `SQ-INV-01`–`SQ-INV-04`, `SQ-INV-13`, `SQ-INV-17` | Material unsupported, contradicted or causally wrong story claim |
| `GATE_EPISTEMIC_INTEGRITY` | `SQ-INV-05`–`SQ-INV-07` | Material strengthening, knowledge overclaim or lost attribution |
| `GATE_TEMPORAL_STATE_INTEGRITY` | `SQ-INV-08`–`SQ-INV-10` | Material chronology, state, identity or relationship error |
| `GATE_SPOILER_DISCIPLINE` | `SQ-INV-12` | Leak of information beyond requested scope |
| `GATE_NECESSARY_COVERAGE` | `SQ-INV-11` | Missing narratively necessary information |
| `GATE_OUTPUT_INTEGRITY` | `SQ-INV-15`, `SQ-INV-16` | Deliverable not usable as delivered |
| `GATE_REQUEST_COMPLIANCE` | `SQ-INV-14` | Requested length or scope not met |

**Material** means severity `HIGH` or `CRITICAL`.

Gate status:

| Status | Condition |
|---|---|
| `GATE_PASS` | No finding above `LOW` |
| `GATE_CONDITIONAL` | At least one `MEDIUM` finding, none material |
| `GATE_FAIL` | At least one material finding |
| `GATE_NOT_DETERMINED` | The gate could not be evaluated (no boundary, unresolved `UNDETERMINED` claims, required check not performed) |

A highly entertaining script with a material integrity violation does not pass. Soft scores are never averaged with gates.

## 16. Verdict Semantics

The verdict depends first on gates, then on narrative usability. There is no weighted average.

| Verdict | Condition |
|---|---|
| `FAIL` | Any gate is `GATE_FAIL`, **or** edit cost is `REWRITE` |
| `REVIEW_REQUIRED` | No gate fails, and any of: a gate is `GATE_NOT_DETERMINED`; a required human audit has not been done; an applicable soft dimension is rated 2 or lower; edit cost is `MAJOR` |
| `PASS` | All gates `GATE_PASS`; no applicable soft dimension below 3; `OVERALL_USEFULNESS` at least 4; edit cost `MINIMAL` |
| `PASS_WITH_MINOR_EDITS` | Everything else: every gate is `GATE_PASS` or `GATE_CONDITIONAL`; no applicable soft dimension below 3; edit cost `MINIMAL` or `MODERATE` |

Evaluate in the order shown. The first matching row is the verdict, so the four rows cover every case.

Under `PASS_WITH_MINOR_EDITS`, every open finding must have a local fix (soften, remove, reword). If one does not, the edit cost is `MAJOR` by definition and the verdict is `REVIEW_REQUIRED`.

Rules:

- **Absence of automated findings is not a pass.** In v0, the grounding, epistemic, temporal/state, spoiler and coverage gates require a human audit before they can be `GATE_PASS` or `GATE_CONDITIONAL`. Without it they are `GATE_NOT_DETERMINED`. Section 21 gives the reason.
- A finding raised by an automated check counts once a human confirms it, or immediately if the check is purely mechanical (length, parse, declared format).
- The rubric numbers above are human anchors. Numerical thresholds for automated metrics are not part of v0 and may be set separately.
- A verdict applies to one script against one request. It is not a claim about a pipeline.

## 17. Human Review Rubric

Template: `benchmarks/m1_script_quality/evaluations/HUMAN_REVIEW_TEMPLATE.md`.

**Part A — integrity.** The reviewer does not give a 1–5 score. For each gate the reviewer records findings (script passage, taxonomy ID, claim type, severity, boundary evidence or its absence, suggested fix) and a gate status.

**Part B — narrative.** Each applicable soft dimension gets a rating with these anchors:

| Rating | Meaning |
|---|---|
| 1 | Poor. The dimension fails; this part would have to be redone |
| 2 | Weak. Between 1 and 3 |
| 3 | Usable with noticeable editing |
| 4 | Good. Between 3 and 5; light touch-ups only |
| 5 | Strong. Publication-ready for this dimension |

Dimension anchors:

| Dimension | 1 | 3 | 5 |
|---|---|---|---|
| `HOOK_STRENGTH` | No reason to keep listening, or a misleading opening | A clear opening that works but is generic | Specific to this story, fits the profile, earns attention honestly |
| `NARRATIVE_FLOW` | Source-order retelling or confusing jumps | Understandable; some beats or transitions need rework | Deliberate structure; timeline always recoverable |
| `PACING` | Heavy padding or rushed payoffs | Uneven in places | Time spent matches importance throughout |
| `EMOTIONAL_IMPACT` | Beats fall flat or are inflated beyond the material | Beats register but do not land | Supported beats land without exaggeration |
| `HUMOR_COMMENTARY_QUALITY` | Generic, off-voice or intrusive | Present and acceptable; uneven | Specific, in voice, at the profile's intensity |
| `CALLBACK_QUALITY` | In-scope setups and payoffs left unconnected | Some connected | Connected naturally |
| `NARRATION_NATURALNESS` | Reads as translation or written prose | Mostly natural; some stiff or over-casual lines | Sounds natural read aloud in the target register |
| `OVERALL_USEFULNESS` | Not usable as a starting point | Usable draft with real editing | Could be recorded after a light pass |

Evidence requirement: every rating and every finding must cite at least one passage and say why. A rating without evidence is invalid. Ratings are ordinal judgements; they are not to be averaged across dimensions.

## 18. Edit Cost

The product goal is a usable script. Edit cost is a first-class result, recorded for every review.

| Level | Meaning |
|---|---|
| `MINIMAL` | Word-level fixes. No sentence needs rethinking |
| `MODERATE` | Several sentences rewritten, softened or removed. Structure stays |
| `MAJOR` | Sections restructured or re-narrated, or integrity fixes spread across the script |
| `REWRITE` | Faster to write again than to repair |

Edit cost counts the work to fix integrity findings as well as narrative ones. When comparing two scripts, "which needs less editing to publish" is answered with this scale plus the reason.

## 19. Evaluation Responsibilities

| Requirement | Mechanical | Model-assisted | Human |
|---|---|---|---|
| Length compliance (`SQ-INV-14`) | Decides | — | — |
| Unexpected-script tokens (`SQ-INV-15`) | Flags | — | Confirms (justified or not) |
| Meta text, malformed structure (`SQ-INV-16`) | Flags obvious cases | Flags | Confirms |
| Unsupported / contradicted claims (`SQ-INV-01`, `SQ-INV-02`) | — | Proposes findings | Audits and decides |
| Causality, internal state (`SQ-INV-03`, `SQ-INV-04`) | — | Proposes findings | Audits and decides |
| Strengthening, knowledge, attribution (`SQ-INV-05`–`SQ-INV-07`) | — | Proposes findings | Audits and decides |
| Chronology, state, relationship (`SQ-INV-08`–`SQ-INV-10`) | — | Proposes findings | Audits and decides |
| Necessary coverage (`SQ-INV-11`) | — | Proposes candidates | Decides |
| Spoiler leak (`SQ-INV-12`) | — | Proposes findings | Decides |
| Commentary versus story claim (`SQ-INV-13`) | — | Proposes | Decides |
| Traceability (`SQ-INV-17`) | Checks that findings cite evidence | — | Decides |
| Hook, flow, pacing, emotion, humor, callbacks, naturalness | — | May assist, advisory only | Decides |
| Overall usefulness, edit cost | — | — | Decides |
| Severity | — | Proposes | Decides |

Model-assisted checks are not assumed to be complete or correct. They are a source of candidate findings.

Auditability invariant:

- `SQ-INV-17` **Auditable.** Every material story claim in a script must be traceable by a reviewer to the truth boundary, and every recorded finding must cite the script passage and the boundary evidence (or state its absence). A script whose claims cannot be checked because no boundary is available cannot pass.

## 20. Known Limitations

1. **Narrow evidence base.** Script-generation evidence comes from one story, mostly one chapter, in early controlled runs with one model family and one language pair.
2. **Human preference review is incomplete.** Project Owner reviews of the M1 runs are still pending. The rubric in section 17 has not yet been exercised by a human reviewer on a real script.
3. **Subjective dimensions.** Hook, pacing, emotional impact and humor are partly subjective. Inter-reviewer agreement has not been measured.
4. **No calibrated automatic thresholds.** No numeric threshold for any automated metric is fixed.
5. **Validators are incomplete.** The current validator implementations do not guarantee detection (section 21).
6. **H7 Stage B has not been executed.** There is no confirmatory holdout evidence for the targeted epistemic pass.
7. **The contract defines desired quality, not current performance.** No current Writer or critic has been shown to satisfy it.
8. **Judgement remains.** Materiality, cumulative escalation, and the commentary/story-claim boundary rely on reviewer judgement guided by the tests above.
9. **Coverage is not operationalized.** "Narratively necessary" is defined conceptually. No procedure for listing necessary items exists yet.
10. **Long-range behaviour is untested at script level.** Multi-chapter scripts, long-range callbacks and spoiler discipline across volumes have not been observed in script runs.

## 21. Current Validation Implementation Evidence

This section is evidence and history. **It is not part of the quality standard.**

| Item | Status | Evidence |
|---|---|---|
| H1 stronger narrative instructions | `PARTIALLY_SUPPORTED` | Improved structure, pacing and voice; did not enforce fidelity or output integrity |
| H2 separate Story Brief | `PARTIALLY_SUPPORTED` | Useful truth boundary; Writer still drifted; brief flattened hearsay |
| H6 factual critic (V1) | `PARTIALLY_SUPPORTED` | Detected 2 of 33 reference issues; revision fixed those and introduced minor drift |
| H6b deterministic claim-level audit | `SUPPORTED` (narrow comparative claim) | Detected 11 of 33 (recall 0.3333, no mapped false positives); 22 missed; one schema violation |
| H6b residual analysis | Completed | 22 misses grouped into 8 semantic families (section 13) |
| H7 targeted epistemic/intent/certainty pass | Protocol approved; Stage A development only | See below |

H7 detail:

- `RUN_0010`: Stage A, exploratory development set. Strict mechanical output contract: **PASS**. One semantic attempt, no regeneration. No semantic scoring was performed in the run itself.
- A later exploratory mapping on the same development instance found 14 of 33 reference issues for the union of baseline and targeted pass (recall 0.4242, no mapped false positives). This is a development signal on data the protocol was developed against.
- Earlier Stage A runs (`RUN_0008`, `RUN_0009`) are preserved unchanged as history.
- Stage B (fresh controlled holdout) is **not authorized and not executed**.
- H7 confirmatory verdict: **`NOT_EVALUATED`**.

What this supports:

- A validation layer is useful as a source of findings.
- No current validator is sufficient as the sole integrity gate. The best observed recall on the development instance is below one half.
- No confirmatory claim can be made for the H7 targeted pass. Its Stage A result does not establish that it detects epistemic errors on unseen material.

This is why section 16 requires a human audit for the semantic gates in v0.

## 22. Versioning

Identity: `SCRIPT_QUALITY_CONTRACT/v0`. Until frozen, this document is a candidate and may be revised by review.

After freeze:

**Minor clarification** (same version, recorded in a change note):

- wording, examples, anchors made clearer;
- a new taxonomy subtype under an existing category that changes no gate assignment;
- additions to sections 20 and 21.

Acceptance semantics must not change: the same script against the same request gets the same gate statuses and verdict.

**Breaking revision** (new version, explicit review):

- adding, removing or redefining a hard invariant or a hard gate;
- changing what counts as a story claim or as factual correctness;
- changing severity definitions or the meaning of "material";
- changing verdict labels or conditions;
- changing which dimensions are soft.

Updating validator evidence never changes the contract. A better or worse critic changes section 21, not sections 3–18.
