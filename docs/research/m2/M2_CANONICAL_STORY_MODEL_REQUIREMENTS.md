# M2 — Canonical Story Model: Domain Requirements and Invariants

Status: RESEARCH — TASK M2-01. Input to M2-02. Not a schema, and not an accepted decision.

## 1. Purpose

This document answers one question:

> What story concepts and constraints must a source-independent Canonical Story Model be able to represent so that later ingestion, extraction, memory, retrieval, Story Brief, narrative planning, and script validation can operate correctly?

It records requirements, invariants, and candidate concepts. It deliberately does not define the final schema, choose storage, or design extraction.

## 2. Authority and Scope

The accepted foundation takes precedence over this document:
- `PRODUCT_VISION.md`
- `MVP_SCOPE.md`
- `ARCHITECTURAL_PRINCIPLES.md`
- `ROADMAP.md`
- `DECISIONS.md`

`TARGET_ARCHITECTURE.md` is a candidate map and is used as supporting context only.

The requirements below are derived from:
- Principles 1, 2, 4, 7, 8, 10 and 11;
- DEC-001, DEC-002, DEC-006, DEC-008, DEC-010 and DEC-011;
- the empirical record of M1.

Where this document states "must", it proposes a requirement for M2-02 to adopt, refine, or reject. Nothing here is accepted until an explicit decision records it.

Examples are source-neutral ("Character A", "Chapter N"). No source text from the research corpus appears in this document.

## 3. Lessons Carried Forward from M1

### 3.1 What M1 established

M1 closed with the following verified facts:

- **Corpus.** A 30-chapter Japanese web-novel corpus was frozen with a fixed identity and a passage contract (`PARAGRAPH_PACK_V1`, 97 passages).
- **Development retrieval experiments.** These ran on a 15-probe development benchmark: lexical BM25, dense retrieval, windowing, MMR diversity, question decomposition, a larger encoder (K), a cross-encoder reranker (M), and rank-sum consensus (O), together with diagnostics.
- **Independent validation fixture.** A 16-probe primary fixture (14 single-gold, 2 multi-gold) was built. It was source-audited at proposition level, consistency-repaired, signed off by the Product Owner, and frozen.
- **Task Q.** Task Q executed once under a pre-registered protocol:
  - M and O both reached Full Evidence Success@10 = 11 / 16, and K reached 10 / 16.
  - O showed exploratory Recall@10 (+0.0208) and MRR (+0.0656) improvements over M, with no primary-endpoint improvement.
  - On the primary endpoint, discordant pairs were 1 / 1, and the exact McNemar and permutation p-values were both 1.0.
  - The outcome fell outside the four pre-registered descriptive classes and is recorded as such.
  - M1 does not show that O generalizes better than M, and it does not show that M and O are equivalent (N = 16, limited power).
- **Closed protocol.** The K/M/O protocol is closed for frozen fixture V1. No post-hoc tuning on that fixture is permitted.
- **Script-side experiments.** The script-side hypotheses (Story Brief, factual critic, claim-level critic) were partially supported. The claim-level critic still missed most robust issues on its controlled instance.

### 3.2 Findings that shape the Canonical Story Model

These are findings about the story domain, not about retrieval tuning.

1. **Multi-evidence truth.** Many narrative questions (chronology, relationship progression, callbacks) are answerable only by combining evidence from distant chapters. Even the best Task Q methods failed to assemble complete evidence for about a third of held-out probes (5 of 16), and 4 of 16 probes failed under both M and O. Passage retrieval alone does not represent how separate facts combine into one answer.
   - *Implication:* the model must represent atomic story assertions separately, each with its own evidence, and must allow composite answers (orderings, progressions, comparisons) to reference those assertions. It must not rely on a single passage carrying the whole truth. Whether this improves retrieval is a later empirical question (M6/M10); it is recorded here as a representational requirement, not a proven benefit.

2. **Multi-gold evidence.** Two probes were supported by more than one complete, independent evidence path, for example a direct scene and a later retrospective statement.
   - *Implication:* provenance must be set-structured. An assertion may have several independently sufficient evidence sets. A single "source pointer" is insufficient, and treating alternative paths as one path mis-scores and mis-validates.

3. **Retrospective and callback evidence.** Later passages frequently restate earlier events. In one probe, the retrospective restatement supported *that* an event happened but not a detail stated only in the original scene. In another, a later passage described being carried to a door without the original "on his back".
   - *Implication:* the model must distinguish an event's own story time from the time of any passage that mentions it. It must record whether evidence is an original depiction or a retrospective mention. It must not assume that a retrospective mention carries all of the original's details.

4. **Compound claims hide unsupported parts.** Proposition-level auditing repeatedly found answers where most parts were supported and one part was not: an unsupported location, an invented causal link, an unattributed statement, or a detail absent from an alternative path. Gold labels at passage level could not reveal this.
   - *Implication:* the unit of story truth must be atomic enough to be evidenced and validated independently.

5. **Hedged perception.** The source sometimes reports that a character *seemed* to perceive something ("he felt as if he heard a thank-you"). Reclassifying such claims from explicit to strongly entailed was necessary.
   - *Implication:* epistemic status and perspective must be representable per assertion, and hedging in the source must survive into the model.

6. **Temporal state.** Probes of the form "as of Chapter N, what was the state?" required the state at N, not the latest known state. Properties such as a lent item, a physical injury, or a form of address changed across the story.
   - *Implication:* no timeless character profiles.

7. **Relationship progression.** Relationships changed through distinct, evidenced milestones: boundaries set, forms of address changed, access granted. A single relationship label cannot answer progression questions.

8. **Spoiler boundaries.** Cutoff-filtered retrieval was a hard requirement. Unfiltered diagnostic runs on the development benchmark recorded Spoiler_Violation@10 of 26.7–40.0%.
   - *Implication:* every story-truth view must be computable "as of" a position without importing later knowledge. This includes derived or summarized facts.

9. **Identity versus mention.** Characters are referred to by family name, given name, honorifics, epithets and nicknames, and forms of address changed over time as story events. A change in how one character addresses another is itself a story fact.
   - *Implication:* identity must be separated from surface mention, and mentions carry information.

10. **Script-side failure families (H6b).** Unsupported claims clustered as invented motives or internal states, invented staging, certainty inflation, hidden-intention inference, knowledge overclaim, invented causality, and frequency or reputation strengthening.
    - *Implication:* the canonical model must be able to state what *is* supported about intentions, emotions, certainty, knowledge and causality, at a stated epistemic level. Downstream validation can then detect claims that exceed it. A model that cannot represent "unknown" or "only suggested" forces writers and validators to guess.

## 4. Required Narrative Capabilities

Each capability is stated as the narrative questions the model must be able to answer (subject to extraction quality), followed by the requirements that follow from them.

### 4.1 Identity
Questions:
- Who is this?
- Are these two names the same person?
- Who is the unnamed figure in Chapter 3?

Requirements:
- Represent entities independently of names.
- Represent aliases, name variants, titles, epithets and honorific forms as mentions or aliases of an entity.
- Represent anonymous or not-yet-identified entities, with later resolution recorded without erasing the earlier unresolved state.
- Record identity resolution itself as evidenced and time-scoped. A reader may learn at Chapter 20 that two figures are one person.

### 4.2 Events
Questions:
- What happened?
- Who took part, in what role?
- Where?
- In what order?
- What did it depend on or cause?

Requirements:
- Represent events with participants and roles.
- Record optional location, story-time placement, and evidence.
- Allow decomposition: a composite event made of sub-events.
- Allow dependencies (enables, causes, precedes, reveals) as assertions with their own epistemic status. Causality is a claim, never a default.

### 4.3 Time
Questions:
- What happened before what?
- What was true at Chapter N?
- Is this passage a flashback?

Requirements:
- Distinguish discourse order (source presentation) from story chronology.
- Support relative order without absolute dates.
- Support unknown or partial time.
- Support flashback and retrospective reference.
- Keep "when it was true" distinct from "when the reader could know it" (see §7).

### 4.4 Relationships
Questions:
- How do A and B relate at Chapter N?
- How did that change, and what evidences each stage?

Requirements:
- Represent relationships between entities, with type and directionality (A's regard for B may differ from B's for A).
- Allow multiple concurrent dimensions (neighbour, classmate, trust, address form).
- Represent change over time as successive evidenced states or transition events.

### 4.5 Entity state
Questions:
- Where is A?
- What does A possess?
- Is A injured?
- What does A want?
- What is A's social standing?

Requirements:
- Represent state as time-scoped, evidenced assertions.
- Do not force heterogeneous state kinds into one untyped field. Location, possession, physical condition, emotion, goal or intention, social status, and relationship state differ in how they are evidenced, how they change, and how easily they are over-claimed.
- Represent emotional and intentional states only at the epistemic level the source supports.

### 4.6 Information and knowledge
Questions:
- Who knows X at Chapter N?
- Who does not?
- When and how did A learn it?
- Does A wrongly believe Y?
- Is X a secret, and when is it revealed, and to whom?

Requirements:
- Represent pieces of information (propositions about the story world) separately from who holds them.
- Represent holder-relative epistemic states: knows, believes, suspects, unaware, mistaken.
- Represent the acquisition event or source.
- Represent secrecy (information deliberately withheld from specific holders) and reveal events, including reveals to the reader that differ from reveals to characters.

### 4.7 Claims and facts
Question: is "A lives next door to B" an event, a state, or something else?

Requirement: the model must represent standing facts and states that are not events. It must also represent claims made *within* the story (a character asserts X) separately from story truth. Whether this requires a distinct first-class "story claim" layer is open (§12).

### 4.8 Provenance
Question: why do we believe this, and where exactly does the source say it?

Requirements:
- Every grounded assertion traces to evidence: source document, segment, and exact span where available.
- Record how the assertion was produced (extraction provenance) and its epistemic status (§8, §9).

### 4.9 Narrative scope and spoiler boundary
Question: what was knowable, true, or revealed up to Chapter N?

Requirement: views of the story must be computable relative to a discourse position without leakage (§7).

### 4.10 Uncertainty and absence
Questions:
- What is not known in this scope?
- What is contested?

Requirements:
- "Unknown" must be representable and distinct from false and from absent.
- Contradictions between source claims must be preserved, not silently resolved.

## 5. Domain Invariants

These invariants are proposed as constraints any M2-02 schema must satisfy. Each gives the requirement and why it is needed.

- **INV-01 — Identity is independent of surface form.** A canonical entity's identity must not depend on any name, alias, honorific or epithet. Surface references are mentions linked to entities.
  *Why:* multiple names per entity, names that change, and unnamed figures (M1 finding 9).

- **INV-02 — Mentions are evidence, not identity.** Linking a mention to an entity is itself an evidenced, revisable assertion. A change in how an entity is referred to may be a story fact in its own right.
  *Why:* forms of address changed as relationship milestones; identity resolution can happen later in the story.

- **INV-03 — Grounded assertions carry provenance.** Every assertion presented as story truth must reference at least one evidence reference that resolves to a source segment. An assertion without evidence may exist only with an explicit non-grounded status (for example a hypothesis) and must never be presented as story truth.
  *Why:* DEC-010, Principle 4.

- **INV-04 — Provenance is set-structured.** An assertion may have several independent sufficient evidence sets. Sufficiency (this set alone supports the whole assertion) must be distinguishable from mere corroboration.
  *Why:* multi-gold evidence and partial retrospective support (M1 findings 2 and 3).

- **INV-05 — Assertions are atomic.** The unit of canonical story truth is a single proposition that can be independently evidenced and validated. Composite answers (orderings, progressions, comparisons) are built from references to atomic assertions, not stored as unanalysed prose.
  *Why:* compound claims hid unsupported parts (M1 finding 4).

- **INV-06 — Epistemic status is mandatory and not collapsible.** Every assertion carries an epistemic status that distinguishes at least:
  - stated explicitly;
  - reported by an in-world source;
  - strongly entailed;
  - interpretive or suggested;
  - unknown or open.

  These must not be merged into one "fact" state. Epistemic status is distinct from confidence in extraction accuracy.
  *Why:* the target architecture's epistemic example, H6b certainty inflation, and hedged perception (M1 finding 5).

- **INV-07 — Inference is traceable and cannot self-upgrade.** An inferred assertion references the assertions or evidence it depends on. Its status may not exceed what its premises support, and no process may promote it to "explicit" without new evidence.
  *Why:* prevents inference chains from laundering interpretation into fact (H6b invented causality and motives).

- **INV-08 — Perspective is explicit.** A proposition *held* by a character (belief, claim, perception, mistaken belief) is represented with its holder and is never stored as narrator-level story truth. Narrator statements and in-world character claims are distinguishable.
  *Why:* knowledge asymmetry, mistaken beliefs, and character assertions (Principle 7, DEC-011).

- **INV-09 — Two time axes are distinct.** Story chronology (when something happens or holds in the story world) and discourse order (where the source presents it) are separate dimensions. Either may be partial, relative, or unknown.
  *Why:* flashbacks and retrospective reference (M1 finding 3).

- **INV-10 — Temporal state is scoped, not overwritten.** State, relationship and knowledge assertions carry a story-time scope. A new state is added alongside earlier states, and history is never overwritten.
  *Why:* DEC-011, and the "as of Chapter N" probes (M1 finding 6).

- **INV-11 — Evidence position is not event time.** An evidence reference records the evidence's own role (original depiction, retrospective mention, report by a character, narrator summary) and discourse position. The story time of the thing evidenced is recorded separately.
  *Why:* retrospective evidence (M1 finding 3).

- **INV-12 — Scoped views are leak-free.** A view "as of discourse position N" must be derivable using only evidence at or before N. Anything derived (inferences, summaries, resolved identities, relationship stages) inherits the latest discourse position among its inputs and is excluded from views before that position.
  *Why:* spoiler boundaries (M1 finding 8), including leakage through derived facts.

- **INV-13 — Truth time and reveal time are distinct.** For any information item, when it is true in the story world, when a given character learns it, and when the reader can learn it are separate facts, each evidenced.
  *Why:* secrets and reveals, and the spoiler boundary for the reader versus characters (Principle 7).

- **INV-14 — Unknown is not false, and absence is not negation.** The model is open-world. Absence of an assertion does not assert its negation. Explicit "unknown in this scope" and explicit negation are both representable and distinct.
  *Why:* the target architecture's `unknowns`, and H6b over-claiming.

- **INV-15 — Contradictions are preserved.** Conflicting assertions (for example two characters' incompatible claims, or a later retcon) are retained with their evidence. Any resolution is itself an evidenced assertion, not a deletion.
  *Why:* unreliable claims and revisions must remain auditable (Principle 4).

- **INV-16 — Relationships are directional, multi-dimensional and temporal.** A relationship is never a single static label. Direction is preserved where the source is directional, and each dimension changes over story time with its own evidence.
  *Why:* relationship progression (M1 finding 7).

- **INV-17 — Source independence.** No concept's meaning depends on a source format. Text character offsets are one kind of evidence locator; other formats (for example manga panels) must be addable as locator kinds without changing story-level concepts.
  *Why:* DEC-002, DEC-003.

- **INV-18 — Storage independence and no storytelling contamination.** Canonical identifiers and relations are domain-defined, not storage-defined. The canonical model contains no presentation artifacts (ordering for effect, hooks, tone). Storytelling layers reference canonical items and never mutate them.
  *Why:* DEC-001, DEC-006, DEC-008, Principles 10 and 11.

## 6. Candidate Domain Concepts

"Assertion" below means a canonical, evidenced, epistemically-qualified proposition (see §12 on whether it becomes a named concept).

| Concept | Why it may be needed | Example question it enables | First-class? | Open concerns |
|---|---|---|---|---|
| Story | Scope root; one work across volumes | Which work and edition is this about? | Likely first-class | Relationship to series, editions, translations |
| SourceDocument | Identity of an ingested source (volume, chapter file) | Which chapter and version supports this? | Likely first-class | Versioning and re-ingestion; may belong to the ingestion layer with a stable reference |
| SourceSegment | Addressable unit of source (passage, panel) | Which passage is cited? | Likely first-class | Segmentation is a later implementation choice; the model needs stable references, not a chunking scheme |
| EvidenceRef | Link from an assertion to a source locator plus role | Where exactly, and is it original or retrospective? | Likely first-class | Locator kinds; span granularity; sufficiency versus corroboration grouping (INV-04) |
| Entity | Identity-bearing referent | Who is this, across names? | Likely first-class | Typing strategy (character, location, object, group) |
| Character | Entity kind with agency, knowledge, relationships | What does A know or want? | Uncertain: entity type or specialization | May be simply an Entity type |
| Alias | Known alternative names or titles | Are these names the same person? | Uncertain | Possibly derivable from Mentions; honorifics and address forms may be relational state |
| Mention | A surface reference in a segment | Which passages mention A, and how is A addressed? | Likely first-class | Volume; whether persisted versus derived |
| Event | Something happening in story time | What happened, and in what order? | Likely first-class | Granularity; decomposition; distinguishing an event from a state change |
| Participation | Entity-in-event with role | Who did what in the event? | Likely first-class (possibly embedded in Event) | Role vocabulary |
| Relationship | Persistent pairing of entities | How do A and B relate? | Uncertain | Entity plus temporal states versus only state assertions (§12) |
| RelationshipState | Time-scoped value of a relationship dimension | How did A and B relate at Chapter N? | Likely needed | May collapse into StateAssertion |
| StateAssertion | Time-scoped property of an entity | Was A injured at Chapter 14? | Likely first-class | Typed state kinds versus one generic form (§4.5) |
| Information | A proposition that can be known, withheld or revealed | Who knows X? | Likely first-class | Overlap with StoryClaim / assertion (§12) |
| KnowledgeState | Holder × information × epistemic attitude × time | Does A know X at Chapter N? | Likely first-class | Attitude vocabulary; evidence for absence of knowledge |
| Secret | Information withheld from specific holders | What is A hiding from B? | Uncertain | Possibly a pattern over Information and KnowledgeState, not its own concept |
| Reveal | Event transferring information to holders or the reader | When does B (or the reader) learn X? | Likely first-class (possibly an Event kind) | Reader-reveal versus character-reveal |
| TemporalAnchor | Placement in story time and discourse order | What came first; what was true at N? | Likely first-class | Minimal model for M4 (§7, §12) |
| StoryClaim | A proposition asserted within the story by a holder, or asserted canonically | Did A claim X, and is it true? | Uncertain | Whether distinct from Information and from a canonical assertion |
| Location | Place entity | Where did it happen? | Uncertain: entity type versus specialized | Nested places; approximate locations |
| Object | Item entity (possession, lending) | What did A lend B? | Uncertain: entity type | Only needed where objects carry story state |
| Dependency / Causal link | Evidenced relation between events | Why did this happen? | Uncertain | Must never be defaulted (INV-07); could be an assertion kind |
| Scope / View | "As of position N" projection | What was knowable at Chapter N? | Deferred as a concept (a query-side construct) | Must be supported by invariants, not stored |

Recommendation for M2-02:
- **Start with the smallest set that satisfies the invariants:** Entity (typed), Mention, Event (with Participation), a time-scoped evidenced assertion for states and relationships, Information with KnowledgeState, Reveal, TemporalAnchor, and EvidenceRef.
- **Treat as open:** Character, Location and Object specialization; Secret; Relationship as its own concept; StoryClaim.
- **Defer:** narrative-level constructs (arcs, themes, foreshadowing links) until extraction evidence shows need.

## 7. Temporal Requirements

- **T-1.** The model must represent discourse position (source order: volume, chapter, segment, offset) for every evidence reference.
- **T-2.** The model must represent story-time placement for events and state validity, as absolute (when stated), relative (before or after or during another anchor), or unknown.
- **T-3.** Relative order must be representable without absolute dates and must tolerate partial orders (not every pair of events is ordered).
- **T-4.** Flashbacks and retrospective references are handled by T-1 and T-2 being independent (INV-09, INV-11). A passage at Chapter 20 may evidence an event in story time before Chapter 1.
- **T-5.** State validity is an interval over story time with possibly unknown bounds. "True from the event at Chapter 13 until at least Chapter 15" must be expressible without claiming an end.
- **T-6.** Three positions are distinct for information: true-at (story time), learned-by-holder-at, and reader-revealed-at (discourse position) (INV-13).
- **T-7 (minimal model for M4).** The minimal viable temporal model is discourse position (exact) plus story-time relative ordering (partial) plus validity intervals with open bounds. Calendar or clock time is optional and should be captured only when stated.

## 8. Epistemic and Knowledge Requirements

### 8.1 Epistemic status of assertions
M2-02 must define a vocabulary that at minimum separates:

| Proposed status | Meaning | Relation to prior vocabularies |
|---|---|---|
| EXPLICIT | Directly stated by the narration or source | M1 `DIRECTLY_EXPLICIT`; target architecture `EXPLICIT` |
| REPORTED | Stated by an in-world holder; its truth is not established by narration | Target architecture `REPORTED`; requires a holder (INV-08) |
| ENTAILED | Follows necessarily or near-necessarily from explicit evidence | M1 `STRONGLY_ENTAILED`; target architecture `SUPPORTED_INFERENCE` (to reconcile) |
| SUGGESTED | A reasonable interpretation the source invites but does not entail | M1 `INTERPRETIVE_INFERENCE` |
| UNKNOWN | Explicitly open in the scope | Target architecture `unknowns` |

Status of a different kind, which M2-02 must keep apart from the above:
- **Contested or ambiguous.** M1 `AMBIGUOUS` marks disagreement or ambiguity, not a truth level; it may be orthogonal.
- **Hedged perception.** A holder "seemed to perceive" something. This is a perspective-plus-hedge combination, not a lower truth level.
- **Extraction confidence.** Confidence in the extraction's accuracy is orthogonal to epistemic status and must not replace it.
- **Rejected or unsupported.** M1 `UNSUPPORTED` is a validation outcome for a candidate claim; it is not a status for stored truth.

### 8.2 Knowledge and belief
- Knowledge states are holder-relative (INV-08) and time-scoped (INV-10). They cover at least: knows, believes (possibly mistaken), suspects, is unaware, and is deliberately kept unaware.
- A mistaken belief must be representable without asserting the believed content as story truth.
- Acquisition must be representable: the event, source holder, or observation through which knowledge was gained, with evidence.
- The reader is a distinguished holder for spoiler purposes (INV-13), not a story-world character.
- The model must support validators asking whether a claimed knowledge or intention exceeds the supported epistemic level (H6b `EPISTEMIC_KNOWLEDGE_OVERCLAIM`, `HIDDEN_INTENTION_INFERENCE`).

## 9. Provenance Requirements

- **P-1.** Evidence references resolve to a source document and segment. They resolve to an exact span when the source supports it, with a locator kind (INV-17).
- **P-2.** Evidence references carry a role: original depiction, retrospective mention, in-world report, or narrator summary (INV-11).
- **P-3.** An assertion's support is a set of evidence sets. Each set is labelled as independently sufficient or as corroborating (INV-04).
- **P-4.** Extraction provenance records how an assertion was produced (process, version, and whether it was human-reviewed). It is separate from source evidence.
- **P-5.** Evidence spans must be exact source slices. M1 found displayed excerpts that were truncated relative to their declared spans; the model should allow mechanical verification that a quoted span equals the source.
- **P-6.** Derived assertions (inference, identity resolution, composite answers) reference their premise assertions, forming an auditable chain to source (INV-07).
- **P-7.** Provenance must survive re-ingestion. If a source is re-segmented, references must be re-resolvable or detectably stale, never silently wrong.

## 10. Source Independence Requirements

- **S-1.** Story-level concepts (entities, events, assertions, knowledge, time) must contain no source-format fields.
- **S-2.** Source-specific detail is confined to evidence locators and adapter-owned source metadata.
- **S-3.** Discourse position must generalize beyond "chapter plus character offset": for example volume, chapter and page or panel for manga, or episode and timestamp. Only ordering and addressability are required at story level.
- **S-4.** Language-specific surface features (honorifics, scripts, readings) belong to mentions and aliases, not to entity identity (INV-01).
- **S-5.** The model must not encode assumptions of one genre (for example romance relationship stages). Relationship dimensions and state kinds must be extensible vocabularies.

## 11. Non-Goals for M2

M2 does not decide:
- relational versus graph storage (PostgreSQL versus Neo4j or others);
- a vector database or index;
- a graph database or query language;
- an embedding model;
- an LLM provider;
- extraction prompts or pipelines;
- chunking or segmentation implementation;
- retrieval algorithms, including any continuation of K/M/O;
- UI, API framework, or deployment.

M2-01 additionally does not produce Pydantic models, JSON Schema, SQL, graph schemas, or ORM code. A schema proposal is M2-02's responsibility, and freezing it requires an explicit decision.

## 12. Open Questions (Input to M2-02)

1. **StoryClaim.** Is a story claim a first-class concept, or is it an assertion with a holder and REPORTED status?
2. **Relationship.** Should a relationship be an entity with temporal states, or only a family of time-scoped state assertions between two entities?
3. **Information versus StoryClaim versus assertion.** Is "information that can be known" the same object as a canonical assertion, or a separate proposition that assertions and knowledge states both reference?
4. **Contradictions.** How are contradictory source claims represented and linked (INV-15)? What does a resolution record look like?
5. **Uncertainty.** How do extraction confidence, epistemic status, and contested status interact without collapsing into one score?
6. **Minimal temporal model.** Is T-7 sufficient for M4 extraction, or is interval reasoning over story time needed earlier?
7. **Location and Object.** Should these be entity types or specialized concepts with their own state semantics?
8. **Retrospective evidence.** How should a retrospective mention reference the original event and inherit or not inherit details (INV-11, M1 finding 3)?
9. **Assertion granularity.** What is the operational test for "atomic" (INV-05) that extraction can apply consistently?
10. **Composite answers.** Are orderings, progressions and comparisons stored, or computed at query time from atomic assertions?
11. **Reader as holder.** Is the reader modelled as a holder of knowledge states, or is reader-reveal purely a discourse-position property?
12. **Epistemic vocabulary reconciliation.** Reconcile M1 labels with the target architecture's `EXPLICIT` / `SUPPORTED_INFERENCE` / `REPORTED` without silently renaming history.
13. **Emotion and intention.** At what epistemic threshold may internal states be stored at all, given H6b failure families?

## 13. Acceptance Criteria for M2-02

M2-02 should be accepted only if it:

1. Proposes a concept set and structure that satisfies INV-01 to INV-18, or explicitly amends an invariant with justification.
2. Answers or explicitly defers each open question in §12, with a rationale.
3. Demonstrates, on source-neutral synthetic examples, that the proposed model can represent:
   - one entity with several names;
   - a flashback;
   - a state that changes;
   - a relationship progression;
   - a secret with a character reveal and a reader reveal at different positions;
   - a mistaken belief;
   - a reported (unverified) claim;
   - a multi-path evidenced assertion;
   - a retrospective mention that supports only part of an original event;
   - an explicit unknown.
4. Shows a leak-free "as of position N" projection for the examples above (INV-12).
5. Remains technology-neutral: no storage, index, provider, or extraction choice.
6. Keeps storytelling artifacts out of the canonical model (INV-18).
7. States which parts are proposed versus accepted, and routes any freeze through `DECISIONS.md`.
