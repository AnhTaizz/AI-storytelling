# Decisions

Status: ACTIVE — initially accepted in TASK 000F; amended in TASK 001A.

This register records decisions that are part of the project contract. Each decision documents what has been frozen, why, and what implementation constraints follow.

**Status semantics:**
- `ACCEPTED` — Explicitly approved as part of the project contract, either through the accepted foundation or through a later authorized project decision/task. Future implementation must respect it until superseded.
- `PROPOSED` — Reasonable direction but not yet authorized to freeze.
- `PROVISIONAL` — Preferred current direction; may proceed experimentally but requires validation before becoming permanent.
- `TO_BENCHMARK` — Must be empirically compared before selection.

---

## DEC-001 — Separate Story Understanding from Storytelling

STATUS: ACCEPTED

DECISION:
Story Understanding and Storytelling are separate conceptual and architectural responsibilities. Story Understanding establishes factual, temporal, causal, and contextual truth grounded in source evidence. Storytelling governs how that truth is selected, ordered, and presented to an audience.

CONTEXT:
A creative model that invents presentation details must never be treated as the source of canonical story facts. The two layers answer fundamentally different questions: "What actually happened?" vs. "How should we tell it?"

RATIONALE:
Established in PRODUCT_VISION.md (Story Understanding vs. Storytelling) and ARCHITECTURAL_PRINCIPLES.md (Principle 1 and Principle 11).

CONSEQUENCES:
- Future architecture must preserve an explicit boundary between Story Intelligence (understanding) and Narrative Intelligence (storytelling).
- Validation must confirm that generated scripts do not introduce factual claims unsupported by story understanding.
- Presentation choices (ordering, tone, pacing, commentary, hooks, callbacks, scene compression) remain in the storytelling layer and may be adjusted without altering story truth.

BOUNDARIES:
- Storytelling must not invent events, rewrite causal history, alter factual chronology, or introduce unsupported relationships.
- Narrative style variation is permitted; factual mutation is not.

RELATED: DEC-006, DEC-012

---

## DEC-002 — Canonical Story Representation is Source-Independent

STATUS: ACCEPTED

DECISION:
Source-specific ingestion formats must be normalized through dedicated adapters into a shared Canonical Story Representation. Downstream Story Intelligence operates against the canonical representation, not against raw source-specific structures.

CONTEXT:
The long-term platform must support multiple source formats (Light Novels, Manga, Web Novels). Coupling core intelligence to one format prevents extensibility.

RATIONALE:
Established in PRODUCT_VISION.md (Generality and Extensibility) and ARCHITECTURAL_PRINCIPLES.md (Principle 2).

Conceptual model:
```text
Light Novel → Light Novel Adapter → Canonical Story Representation
Manga       → Manga Adapter       → Canonical Story Representation
```

CONSEQUENCES:
- Core Story Intelligence must not depend on EPUB, TXT, PDF, manga pages, or any one parser.
- Each new source format requires its own adapter; the canonical model absorbs normalized output.
- This is foundational to multi-format extensibility.

BOUNDARIES:
- The Canonical Story Representation is a domain model; it is not defined by database structure (see DEC-008).

RELATED: DEC-003, DEC-008

---

## DEC-003 — Light Novel Text is the First Supported Source

STATUS: ACCEPTED

DECISION:
The initial MVP uses controlled Light Novel text as its first and only source format. Manga and other source formats are deferred.

CONTEXT:
The MVP must be bounded and achievable. Light Novel text provides a controlled, unambiguous textual input for the first implementation of the full ingestion-to-script pipeline.

RATIONALE:
Established in MVP_SCOPE.md (MVP Goal, Out of Scope) and ROADMAP.md (M3 — Light Novel Ingestion, M12 — Manga Ingestion).

CONSEQUENCES:
- The Light Novel Adapter is the only required source adapter in the MVP.
- Manga and Web Novel adapters are not in scope until M12+.
- The Canonical Story Representation must not be designed to be Light-Novel-specific.

BOUNDARIES:
- This decision bounds the MVP source, not the long-term architecture.
- The architecture must remain source-agnostic by design (DEC-002).

RELATED: DEC-002, DEC-004

---

## DEC-004 — High-Quality Grounded YouTube Script is the First Major Product Outcome

STATUS: ACCEPTED

DECISION:
The first important user-facing product outcome is a high-quality grounded YouTube script. The MVP is not primarily a chatbot, generic summarizer, graph visualization, RAG demo, or video editor.

CONTEXT:
All early milestones (M1–M9) exist to build and validate the story intelligence pipeline necessary to support this outcome.

RATIONALE:
Established in PRODUCT_VISION.md (first major product outcome) and MVP_SCOPE.md (MVP Goal, Grounded Script Generation).

CONSEQUENCES:
- Milestones are evaluated for their contribution toward improved script quality and narrative groundedness.
- The Script Quality Gate (post-M9) must be passed before the project pivots to production automation.
- Script quality and factual fidelity are primary success measures.

BOUNDARIES:
- This does not freeze the specific output format, word count, or channel style of the script.
- Those belong to M1 (Script Quality & Narrative Contract).

RELATED: DEC-001, DEC-009

---

## DEC-005 — Persistent Story Memory is a First-Class Capability

STATUS: ACCEPTED

DECISION:
Long-range narrative memory across chapters, volumes, and story arcs is a fundamental product capability. The architecture must eventually allow relevant historical story context to be retained and recovered during later processing.

CONTEXT:
Long-form stories contain interconnected details distributed across many chapters. Without memory, each processing session loses prior understanding.

RATIONALE:
Established in PRODUCT_VISION.md (Persistent Story Memory in the pipeline), MVP_SCOPE.md (Persistent Story Memory in scope), and ARCHITECTURAL_PRINCIPLES.md (Principle 3).

CONSEQUENCES:
- Architecture planning must account for historical context storage from the beginning.
- M5 (Persistent Story Memory) establishes a baseline implementation; M11 (Temporal / Graph Story Memory) extends it with richer graph and temporal capabilities after failure modes are observed.
- A single-session, stateless architecture is insufficient for this product.

BOUNDARIES:
- This decision freezes the capability requirement, not the implementation.
- Neo4j, PostgreSQL, vector databases, or any specific persistence technology is NOT frozen here (see DEC-008).
- M5 does not require a full advanced graph architecture; a baseline persistence layer is sufficient at that milestone.

RELATED: DEC-007, DEC-008, DEC-010

---

## DEC-006 — Narrative Style Cannot Change Story Truth

STATUS: ACCEPTED

DECISION:
Different storytelling styles may alter presentation choices but must not alter canonical story facts. This constraint holds across all channel voices, video modes, genres, and narrative formats.

CONTEXT:
The platform supports multiple output intents (recap, review, dramatic storytelling, character analysis, etc.) and different channel voices. Without this constraint, creative variance would corrupt factual reliability.

RATIONALE:
Established in PRODUCT_VISION.md (Critical Rule) and ARCHITECTURAL_PRINCIPLES.md (Principle 11).

CONSEQUENCES:
- Style layers are permitted to change: ordering, emphasis, tone, pacing, commentary, hooks, callbacks, scene compression.
- Style layers are forbidden from: inventing events, rewriting causal history, changing factual chronology, fabricating character knowledge, introducing unsupported relationships, or rewriting reveals.
- Validation (M9) must verify that scripts produced by any storytelling configuration remain factually grounded.

BOUNDARIES:
- This applies to final scripts and all intermediate storytelling artifacts.
- Story Understanding output (canonical facts) is upstream of and must not be mutated by Storytelling.

RELATED: DEC-001, DEC-012

---

## DEC-007 — Graph and Vector Retrieval are Complementary

STATUS: ACCEPTED

DECISION:
The architecture must not assume that semantic vector retrieval or structural graph retrieval alone is sufficient for all narrative retrieval problems. Both capabilities are required and serve different purposes.

CONTEXT:
Narrative queries span a wide range: thematic similarity, causal chain traversal, character state at a given chapter, foreshadow/reveal links, information asymmetries. No single retrieval method handles this breadth well.

RATIONALE:
Established in ARCHITECTURAL_PRINCIPLES.md (Principle 6).

CONSEQUENCES:
- Architecture must plan for both retrieval modalities as complementary capabilities.
- Vector retrieval handles: semantic similarity, thematic matching, paraphrased references.
- Graph retrieval handles: causality, event dependencies, relationships, changing narrative state, foreshadow/reveal chains.
- M6 establishes a retrieval baseline; M10 extends precision; M11 introduces richer graph/temporal traversal.

BOUNDARIES:
- This decision does NOT freeze a specific vector database, embedding model, or graph database.
- Implementation choices for both retrieval modalities remain open (see Open Technology Decisions).

RELATED: DEC-005, DEC-008

---

## DEC-008 — Technology Must Not Define the Canonical Story Model

STATUS: ACCEPTED

DECISION:
The Canonical Story Model must be defined in domain terms, independently of storage technology. Storage mechanisms implement the validated model; they do not define narrative truth.

CONTEXT:
Allowing a database's native abstractions (Neo4j nodes/relationships, PostgreSQL tables, vector store chunks) to drive the story domain model would corrupt the model with implementation concerns and make future technology migration or evolution extremely difficult.

RATIONALE:
Established in ARCHITECTURAL_PRINCIPLES.md (Principle 10).

Correct direction:
```text
Story Domain Model
  ↓
Persistence Mapping
  ↓
Database Representation
```

NOT:
```text
Database Schema → defines → Story Domain Model
```

CONSEQUENCES:
- Story Model design work (M2) must proceed from narrative domain concepts, not from database features.
- Persistence mapping is a separate concern that follows domain modeling.
- Future technology migrations should not require redesigning the Story Model.
- No specific database (Neo4j, PostgreSQL, pgvector, Qdrant, etc.) is frozen by this project foundation.

BOUNDARIES:
- Technology choices remain open and will be decided in dedicated technical decision records based on empirical requirements.

RELATED: DEC-005, DEC-007

---

## DEC-009 — Production Automation is Deferred Until Script Quality is Proven

STATUS: ACCEPTED

DECISION:
The project prioritizes story understanding, memory, retrieval, planning, script generation, and script validation before investing heavily in TTS, visual production, video editing, and YouTube automation. The Script Quality Gate after M9 must be passed before production automation becomes a major project priority.

CONTEXT:
Production automation built on unreliable or poorly grounded scripts would produce low-quality automated output at scale. Establishing script quality first protects investment in later automation.

RATIONALE:
Established in MVP_SCOPE.md (Out of Scope: Downstream media production) and ROADMAP.md (Script Quality Gate between M9 and M10).

CONSEQUENCES:
- M10–M14 (Advanced Retrieval, Graph Memory, Manga, Visual Production, Voice/Video Automation) are gated behind Script Quality Gate.
- Early resources and milestones focus on the intelligence and narrative planning pipeline.
- TTS, video editing, thumbnail generation, and YouTube upload automation are not in MVP scope.

BOUNDARIES:
- This is a sequencing decision, not a permanent deferral. Production automation is planned at M13–M14.

RELATED: DEC-004, DEC-014

---

## DEC-010 — Provenance is a Core Architectural Requirement

STATUS: ACCEPTED

DECISION:
Important AI-derived story knowledge must remain traceable to source evidence whenever possible. Story facts, extracted events, and AI-generated understanding must be justifiable by reference to source passages.

CONTEXT:
Without provenance, the system cannot validate its own outputs, cannot correct errors detected during validation, and cannot distinguish genuine story facts from model hallucinations.

RATIONALE:
Established in ARCHITECTURAL_PRINCIPLES.md (Principle 4: Preserve Provenance) and MVP_SCOPE.md (Ingest controlled Light Novel text with preserved verbatim source evidence and provenance).

Conceptual chain:
```text
Story Fact → Evidence → Source Passage → Chapter / Source
```

CONSEQUENCES:
- Ingestion must preserve raw source passages with sufficient metadata to reference them later.
- Extraction and understanding pipelines must annotate derived knowledge with evidence references.
- Validation (M9) can use evidence references to verify that script claims are source-grounded.
- Evidence schema design belongs to a later milestone; this decision only establishes the requirement.

BOUNDARIES:
- This decision does not define the Evidence schema or database structure.
- "Whenever possible" acknowledges that not all AI-derived understanding may carry full provenance; the requirement is directional, not absolute.

RELATED: DEC-001, DEC-005, DEC-008

---

## DEC-011 — Temporal Story State Must Be Representable

STATUS: ACCEPTED

DECISION:
The architecture must be capable of representing story state as changing over narrative time. What a character knows, believes, or intends at one chapter may differ from what they know at a different chapter. Relationships, knowledge, goals, beliefs, and emotional state may all evolve.

CONTEXT:
Failing to model temporal story state produces architecturally incorrect story understanding. A system that only captures static snapshots cannot correctly resolve knowledge asymmetries, foreshadowing, or retroactive reveals.

RATIONALE:
Established in ARCHITECTURAL_PRINCIPLES.md (Principle 8: Represent Story State Over Time).

Example:
```text
Character A does not know Secret X at Chapter 5
Character A suspects Secret X at Chapter 20
Character A knows Secret X at Chapter 31
```

CONSEQUENCES:
- The Canonical Story Model (M2) must accommodate temporal state representation as a design requirement.
- Baseline persistence (M5) must preserve enough temporal information to support later temporal queries.
- Advanced temporal traversal capabilities are planned for M11 (Temporal / Graph Story Memory), building on observed retrieval needs.
- Validation must be capable of detecting temporal consistency violations.

BOUNDARIES:
- This decision establishes the capability requirement; it does not define the temporal schema or storage mechanism.
- A lightweight baseline temporal representation at M5 is acceptable; full graph-based temporal traversal belongs to M11.

RELATED: DEC-005, DEC-007, DEC-010

---

## DEC-012 — Narrative Behavior Must Be Configurable

STATUS: ACCEPTED

DECISION:
Storytelling behavior must not be hard-coded into a single fixed narrative template or voice. The architecture must support diverse combinations of channel voice, video mode, genre profile, scene intent, and audience knowledge state.

CONTEXT:
The platform targets multiple output intents (recap, review, dramatic storytelling, character analysis, lore analysis) and must accommodate different editorial styles and channel voices. A single hardcoded style would make the platform unusable across these modes.

RATIONALE:
Established in PRODUCT_VISION.md (Multiple Storytelling Outputs, Generality and Extensibility) and ARCHITECTURAL_PRINCIPLES.md (Principle 12: Support Configurable Narrative Behaviors).

CONSEQUENCES:
- The Narrative Planning layer must be parameterized rather than fixed.
- Narrative Profile or equivalent configuration must be a distinct architectural concern.
- A single script output style must not be assumed in M8 (Narrative Planning) design.
- The Narrative Style Engine specification belongs to a later milestone; this decision establishes the architectural requirement.

BOUNDARIES:
- This does not define the Narrative Profile schema or specific configuration parameters.
- Those belong to M1 (Script Quality & Narrative Contract) and M8 (Narrative Planning).

RELATED: DEC-001, DEC-006

---

## DEC-013 — Human Review Points are a Valid Part of the Workflow

STATUS: ACCEPTED

DECISION:
The product is not required to be a fully automated black box. Intermediate artifacts — particularly the Story Brief, Narrative Plan, and Script — may expose meaningful human review and editing checkpoints without breaking the pipeline.

CONTEXT:
Creator workflows benefit from control and transparency. Allowing human review of intermediate artifacts improves output quality and protects creative intent, especially where automated judgement may be unreliable.

RATIONALE:
Established in ARCHITECTURAL_PRINCIPLES.md (Principle 13: Enable Human Control and Review Points).

CONSEQUENCES:
- Story Brief (M7), Narrative Plan (M8), and Script (M9) must be designed as inspectable, potentially editable artifacts.
- Automation must not be architected to eliminate these review checkpoints.
- The pipeline should degrade gracefully when a human reviews or adjusts an intermediate artifact.

BOUNDARIES:
- This decision does not require manual review on every run.
- This decision does not mandate automation as the default mode either. The appropriate degree of automation versus human intervention remains a later product and workflow decision.
- This decision protects the architectural affordance of human review; it does not prescribe how or how often that affordance is exercised.

RELATED: DEC-014

---

## DEC-014 — Quality and Groundedness Take Priority Over Maximum Automation

STATUS: ACCEPTED

DECISION:
Factual accuracy, temporal consistency, useful retrieval, deliberate narrative planning, and verified script quality take precedence over end-to-end hands-free automation depth. Automation investment must follow demonstrated quality, not precede it.

CONTEXT:
Building deep automation on top of unreliable story understanding would produce unreliable outputs at scale. Establishing strong foundational quality protects long-term product credibility.

RATIONALE:
Established in ARCHITECTURAL_PRINCIPLES.md (Principle 14: Prioritize Quality and Groundedness Over Maximum Automation).

CONSEQUENCES:
- Implementation milestones prioritize correctness and groundedness at each stage before increasing automation depth.
- The Script Quality Gate enforces this ordering at the roadmap level.
- Feature velocity must not come at the expense of verifiable output quality.

BOUNDARIES:
- This does not prevent automation; it sequences it correctly.
- DEC-009 captures the specific sequencing of production automation after the Script Quality Gate. DEC-014 captures the broader principle that applies across all milestones.

RELATED: DEC-009, DEC-013

---

## DEC-015 — Evidence-Driven Vertical Iteration

STATUS: ACCEPTED

DECISION:
Project execution uses evidence-driven vertical iteration. Small end-to-end prototypes, research spikes, and baseline experiments may cross future milestone boundaries when needed to obtain early feedback. Milestones remain capability gates, not strict implementation isolation boundaries.

RATIONALE:
AI systems are highly empirical. Individual components may appear sound while the combined system produces weak outputs. The project therefore requires short feedback loops using actual generated artifacts before investing deeply in architecture.

EXPECTED LOOP:
BASELINE → OBSERVATION → FAILURE MODE → HYPOTHESIS → MODIFICATION → EXPERIMENT → RESULT → CONCLUSION

CONSEQUENCES:
- Real output should be produced as early as practical.
- Architecture should be refined from observed failure modes.
- Complex components should require evidence-based justification.
- Research spikes may temporarily use simplified or disposable implementations.
- Experimental code must not be confused with production capability.
- Milestone completion remains governed by milestone-specific acceptance criteria.
- Documentation should evolve from empirical evidence rather than speculation alone.

BOUNDARIES:
- This decision does NOT change the M0–M14 roadmap sequence.
- This decision does NOT create a new M1.5 milestone.
- This decision does NOT mark future milestones complete.
- This decision does NOT authorize architectural shortcuts to become permanent without review.
- This decision does NOT remove quality gates.
- This decision does NOT remove provenance or grounding requirements.
- This decision does NOT weaken accepted M0 architectural principles.

---

## DEC-016 — Canonical Story Model v0 Freeze

STATUS: ACCEPTED (Master Orchestrator / Project Owner authorization, 2026-10-01, TASK M2-08)

DECISION:
Canonical Story Model V0 is accepted as the project's initial source-independent story-understanding contract.

1. The schema is `canonical_story/v0`.
2. The predicate registry is `predicate_registry/v0.1`. The authority policy is `DEFAULT_V0`.
3. The frozen identities are those in `benchmarks/m2_canonical_model/CANONICAL_STORY_V0_FROZEN.yaml`: exact paths and SHA-256 hashes of the schema, registry, conformance validator, reference projection and the M2 documents. That record, not this text, defines what is frozen.
4. Storage technology remains undecided.
5. JSON Schema is a contract notation. It is not a commitment to JSON storage.
6. Relationship, Secret, StoryClaim, KNOWS and MISTAKEN remain derived views. They are never stored.
7. Proposition and Assertion remain distinct. A Proposition is truth-neutral; only an Assertion carries canonical commitment.
8. Evidence provenance (support paths, availability) and as-of semantics are normative.
9. The registry governance policy from M2-07 is accepted (`docs/research/m2/M2_PRE_FREEZE_REVIEW.md` §7).
10. The known limitations listed below are explicitly accepted for V0.

EMPIRICAL BASIS:
- Synthetic stress and conformance tests: cases A–J, 20 negative fixtures, 99 canonical tests.
- Real-source 10-case mapping spike (M2-06): no blocking model defect.
- Pre-freeze rerun against the committed contract (M2-07): conformance PASS, as-of checks 54/54, fit NATURAL 3 / ACCEPTABLE 6 / AWKWARD 1 / NOT_REPRESENTABLE 0. One borderline rating was confirmed by the Orchestrator.
- Freeze gate (M2-08): every bound hash and the private evidence package were re-verified, and the tests were re-run, before the freeze record was written.

SCOPE OF THE CLAIM:
Validation covers one 30-chapter story in one genre with one primary human/agent annotator. The freeze is a stable V0 engineering contract. It is not a claim of universal narrative ontology completeness, and no generalization beyond the tested scope is claimed.

ACCEPTED KNOWN LIMITATIONS (not solved in V0):
- F-EXISTENTIAL-CONTENT, F-RESOLUTION-PROPAGATION, F-CAUSATION-OMISSION, F-FOCALIZATION, F-GATE-BY-ANNOTATION, F-SPEECH-ACTS, F-CONDITIONAL-BOUND, F-REPEATED-UTTERANCE.
- Address-selection context is not first-class.
- Polarity-specific UNAWARE is provisional and not real-source validated.
- Free-text literal normalization is absent.
- Single discourse stream.
- No full story-time verdict slicing.
- No temporal closure.
- `DEFAULT_V0` assumes reliable narration.

IMMUTABILITY:
Frozen `canonical_story/v0 + predicate_registry/v0.1` artifacts are never silently modified in place.
- Additive registry evolution may create `predicate_registry/v0.2` under the accepted governance policy.
- A breaking model change requires a new schema/registry version, explicit architecture review, stated migration implications, and renewed conformance evidence.
- Historical frozen hashes remain unchanged.

BOUNDARIES:
- This decision does NOT select a storage, graph or vector technology (see Open Technology Decisions).
- This decision does NOT start M3 and does NOT amend the roadmap. The M1 Formal Script Quality Contract remains open.
- This decision does NOT freeze extraction, ingestion or any production implementation.

RELATED: DEC-001, DEC-002, DEC-008, DEC-010, DEC-011, DEC-015

---

## DEC-017 — Script Quality Contract v0 Freeze

STATUS: ACCEPTED (Master Orchestrator / Project Owner authorization, 2026-10-01, TASK M1-FREEZE-SCRIPT-QUALITY-CONTRACT-V0)

DECISION:
`SCRIPT_QUALITY_CONTRACT/v0` is the project's initial formal script-quality standard.

1. The standard is `docs/contracts/SCRIPT_QUALITY_CONTRACT_V0.md`, with its machine-readable form and review template.
2. Hard integrity gates are separate from soft narrative dimensions.
3. Soft scores cannot compensate for a failed integrity gate. Nothing is averaged across the two.
4. Creative presentation is allowed; factual mutation is not. Engagement may increase through presentation transformation, not through factual mutation.
5. Claims are judged against the authorized truth boundary for the request, not against outside knowledge.
6. Epistemic strength, chronology and state, and spoiler boundaries must be preserved.
7. Material request non-compliance is a real hard-gate failure. Severity is judged by impact and repair scope, not by a percentage.
8. The Narrative Profile defines style, tone and target length. These are request constraints, not universal quality.
9. The semantic hard gates require a human audit before an official `PASS` or `PASS_WITH_MINOR_EDITS` under v0. An AI or model-assisted review may produce a `REVIEW_TRACE_VERDICT`; without the human audit the `OFFICIAL_CONTRACT_VERDICT` is `REVIEW_REQUIRED`.
10. Current validators are advisory sources of candidate findings.
11. The H7 confirmatory verdict remains `NOT_EVALUATED`. H7 Stage A is development evidence only; Stage B has not been executed.
12. The exact frozen identity is defined by `benchmarks/m1_script_quality/SCRIPT_QUALITY_CONTRACT_V0_FREEZE_RECORD.yaml` and the hashes it binds. That record, not this text, defines what is frozen.

EVIDENCE BASIS:
- Script experiments H1, H2, H6 and H6b.
- H7 Stage A, as development evidence only.
- Operational dry-run of the candidate on RUN_0003 and RUN_0004 (AI reviewer; not an independent human review).
- Post-dry-run repair of request-compliance and severity semantics.
- Deterministic contract consistency and verdict tests.

SCOPE OF THE CLAIM:
The contract defines desired quality. It is not a claim that any current Writer, critic or pipeline meets it, and freezing it does not validate H7.

ACCEPTED KNOWN LIMITATIONS:
- Narrow evidence base: one story, early controlled runs.
- Independent human use of the rubric is still pending.
- No inter-reviewer agreement measurement.
- No calibrated automatic semantic thresholds.
- Current critics have incomplete detection.
- H7 Stage B not executed.
- The procedure for identifying narratively necessary coverage is not operationalized.
- Long-range, multi-chapter script behaviour is untested.
- Materiality requires reviewer judgement.

IMMUTABILITY:
The frozen artifacts are not modified in place. A clarification that leaves acceptance semantics unchanged is recorded as a change note with a new freeze record. A change to hard invariants, hard gates, the meaning of a story claim, severity semantics or verdict semantics requires a new contract version and explicit review (contract section 22).

BOUNDARIES:
- This decision does NOT start M3 and does NOT amend the roadmap.
- This decision does NOT select a Writer, critic, model or validation implementation.
- This decision does NOT define a Narrative Profile.
- This decision does NOT evaluate the M9 Script Quality Gate.

RELATED: DEC-001, DEC-004, DEC-006, DEC-009, DEC-012, DEC-013, DEC-014, DEC-016

---

## DEC-018 — Light Novel Ingestion Contract v0 Freeze

STATUS: ACCEPTED (Master Orchestrator / Project Owner authorization, 2026-10-01, TASK M3-03)

DECISION:
`LIGHT_NOVEL_INGESTION/v0` is the project's initial contract for ingesting controlled Light Novel text.

1. The contract is `docs/research/m3/M3_LIGHT_NOVEL_INGESTION_CONTRACT_V0.md` with the source manifest schema.
2. Exact source bytes are authoritative for provenance.
3. Source text is never normalized before provenance is established.
4. `SourceDocument` identity and version are distinct. The version is the SHA-256 of the exact bytes.
5. The corpus fingerprint is deterministic and independent of filesystem location.
6. `PARAGRAPH_SEGMENT_V0` is a provenance segmentation strategy. It is not retrieval chunking.
7. `SourceSegment` boundaries follow source formatting and do not guarantee semantic homogeneity. A segment may hold story prose together with a heading, an author note or dialogue when the source does not separate them.
8. Exact character and byte locators (`TEXT_RANGE_V0`) are normative.
9. `SOURCE_PASSAGE_REF_V0` supports role-neutral references to exact sub-spans.
10. `EvidenceRole` is downstream semantic interpretation. It is assigned per `EvidenceRef` span, never inferred for a whole segment.
11. Retrieval chunks remain independent of segments but must trace to source provenance.
12. The reference adapter `light_novel_adapter_v0/0.1.0` is empirically validated. It is not the only implementation that may conform.
13. The known limitations below are accepted for V0.
14. The exact frozen identity is defined by `benchmarks/m3_ingestion/LIGHT_NOVEL_INGESTION_V0_FROZEN.yaml` and the hashes it binds. That record, not this text, defines what is frozen.

EMPIRICAL BASIS:
- Synthetic and public: 50 adapter tests; 20 historical story-ingestion tests preserved; a smoke test over five tracked sample documents.
- Private real source: 30 documents, 1519 segments; all 97 historical retrieval chunks traceable, none untraceable.
- Determinism: two independent runs byte-identical.
- Canonical compatibility: structural and semantic conformance to `canonical_story/v0`.

ACCEPTED ISSUE I-01:
16 mixed-content segments (a heading or author note joined with adjacent story text because the source has no blank separator). Classified KNOWN_LIMITATION / NON_BLOCKING and accepted for V0. A segment is provenance, not a semantically homogeneous unit; exact sub-span references remain available; roles belong to evidence spans. Mixed segments are accepted behaviour, not claimed to be ideal.

SCOPE OF THE CLAIM:
Validation covers one story, one source and one language. The freeze is a stable V0 ingestion contract for controlled plain text. It is not a claim about other formats or sources.

ACCEPTED KNOWN LIMITATIONS:
- Controlled plain-text UTF-8 only; no EPUB, HTML, ruby or furigana adapter.
- Segmentation depends on blank-line source formatting; granularity can differ between documents; mixed semantic material can share a segment.
- No automatic migration or alignment between versions of a document.
- A sub-span shares its segment's `DiscoursePosition`; one discourse stream per manifest.
- Whole documents are held in memory; a byte-order mark is preserved as source content.
- No paratext or evidence-role inference in M3.
- The real corpus has no paragraph over 1200 characters, so the no-split rule is stress-tested only synthetically.

IMMUTABILITY:
Frozen V0 artifacts are not modified in place. An implementation patch that preserves all externally observable semantics gets a new adapter version and a validation record. Any change to manifest, version, fingerprint, segmentation, segment identity, position mapping, locator or passage-reference meaning, source-preservation guarantees, or the M3/M4 evidence-role boundary requires a new contract version (contract section 20).

BOUNDARIES:
- This decision does NOT select a database, embedding model, extraction model or retrieval design.
- This decision does NOT start M4 and does NOT amend the roadmap.
- This decision does NOT change `PARAGRAPH_PACK_V1`, which remains historical benchmark infrastructure.

RELATED: DEC-002, DEC-003, DEC-007, DEC-008, DEC-010, DEC-016

---

## Proposed Research Protocol Decisions

### PROPOSED_PROTOCOL_REVISION_MULTI_GOLD_SCOPE

STATUS: SUPERSEDED_UNAPPROVED_BY_MULTIGOLD_IMPLEMENTATION

PROPOSAL:
A probe may participate in a frozen single-gold primary fixture only when the defined corpus-wide, cutoff-constrained evidence audit has found no complete alternative gold path. A probe with a confirmed complete alternative remains deferred until multi-gold representation and scoring are implemented and tested.

CONTEXT:
The published protocol currently makes multi-gold support an open prerequisite for fixture freeze. Final pre-freeze validation also found complete alternative paths inside the current primary population. Treating the narrower per-probe rule as if it had always applied would silently revise the protocol.

IMPACT:
This proposal changes eligibility of the evaluated population, not retrieval parameters, candidate depth, rank fusion, metric definitions, or thresholds. It was recorded before Task Q and before any validation retrieval result existed. Even if approved, the current primary population still requires repair or deferral of the affected probes.

APPROVAL BOUNDARY:
This entry records a historical proposal only. It was never accepted, does not authorize evaluation, and does not freeze the fixture.

RESOLUTION:
The project implemented the original stricter multi-gold prerequisite before Task Q. The evaluator now supports alternative complete minimal evidence sets with exact single-gold backward compatibility. Because the technical limitation was removed, this narrower relaxation is superseded without approval. Human sign-off and an explicit later freeze action remain required.

---

## Accepted Research Protocol Decisions

### INDEPENDENT_VALIDATION_FIXTURE_V1_FREEZE

STATUS: ACCEPTED (Product Owner sign-off, 2026-09-30)

DECISION:
`INDEPENDENT_VALIDATION_FIXTURE_V1` is frozen as fixture version 1 and is the sole held-out input for Task Q. The frozen package SHA-256 is `f07b2d4048f424d8e885221ff4b14f3d572a22bf2e5a405382782ad1672f1dc1`, derived from reviewed package `fcd147eb57c7b8ab9500c85ad633436524b96a014aa4ef8b68dfdfbf9d4515a6` and bound to human sign-off `03de5485c07ec84d5e8e32624db23e1e3f22d91ffc11828c4a458005513a9037`.

APPROVED POPULATION:
16 primary multi-evidence probes, all `APPROVED`: 14 single-gold and 2 multi-gold. Three auxiliary probes were `REJECTED` as source-hallucinated as written; six auxiliary or deferred probes were `DEFERRED`. None of these nine enter Task Q.

MULTI-GOLD SUPPORT:
Gold evidence uses `gold_evidence_sets` (schema v2). Each set is an independently complete minimal evidence path, and the sets must equal the minimal hitting sets of the per-proposition support model. Single-gold scoring is exactly backward compatible.

METRICS:
Full Evidence Success@10 (primary binary endpoint), Required Evidence Recall@10, Hit@10, and MRR, with the multi-gold definitions in the fixture specification. Primary comparison is Method O against Method M; Method K is a secondary historical baseline. Uncertainty uses paired bootstrap (B = 10,000, seed 42) plus exact McNemar and paired permutation tests on the primary endpoint.

ANTI-TUNING CONTRACT:
Candidate depth (30), consensus weights, rank tie-breakers, and thresholds are fixed as pre-registered. Any adjustment after observing validation results voids generalization claims and requires a new held-out fixture.

HOLDOUT INTEGRITY:
At freeze, no validation retrieval had been executed. The consensus method predates fixture creation, and the only later change to K/M/O code replaced the metric function with the proven-equivalent multi-gold implementation. Disclosed pre-existing limitation: the fixture author had prior exposure to the development probes (see fixture specification section 4).

HISTORY NOT ERASED:
An earlier (v2) package was declared ready for sign-off and was later found to show reviewers text that differed from the evaluated fixture. It was superseded before any sign-off; that correction is recorded in `PROJECT_STATE.md`.

IMMUTABILITY:
Frozen V1 is never mutated in place. Any change creates a new fixture version and requires new sign-off.

---

## Open Technology Decisions

The following technology choices are not frozen. They require dedicated technical decision records supported by empirical evidence or benchmarks before becoming project commitments.

**Graph Persistence (e.g., Neo4j):**
Neo4j is a strong candidate for narrative graph memory. It is NOT accepted as the implementation choice. Technology selection for graph persistence belongs to a future technical milestone, informed by Canonical Story Model requirements.

**Vector Storage (e.g., pgvector, Qdrant):**
Not frozen. Vector store selection follows embedding strategy decisions and retrieval benchmarks.

**Embedding Models:**
Not frozen. Embedding model selection must be benchmark-driven against narrative retrieval quality metrics.

**LLM Selection (extraction, planning, script generation):**
Not frozen. Model selection for each pipeline stage must be benchmark-driven. No specific provider (OpenAI, Anthropic, Google) is frozen.

**Application Framework (e.g., FastAPI, Next.js):**
Not frozen. Framework selection belongs to implementation planning once MVP architecture is established.

**Orchestration Framework (e.g., LangChain, LangGraph):**
Not frozen. Framework selection must be justified by observed pipeline complexity.

**Persistence Architecture (relational, graph, hybrid):**
Not frozen. Depends on Canonical Story Model requirements defined in M2 and observed M5 persistence needs.

**Evaluation Benchmark:**
Not frozen.

The Script Quality evaluation contract belongs to M1 — Script Quality & Narrative Contract.

Retrieval evaluation metrics remain an open design decision and must be defined by the relevant retrieval work no later than the milestone where they are needed for verification. They may be introduced earlier if an approved benchmark or research design requires them.

---

## DEC-019 — Automated Quality Gate for Agent-Written Changes

STATUS: ACCEPTED (Project Owner approval of the quality-gate plan, 2026-11-13)

DECISION:
Every change is verified by one command, `python -m tools.ci.check`, run locally by agents and in CI on every pull request (`.github/workflows/ci.yml`).

1. All test suites run, each in its own process. A test may be skipped for its environment only through `tests/environment_gates.yaml`, and only for allow-listed heavy modules (torch stack) or git-ignored private data. `--strict` turns every unmet gate into a failure for full local runs.
2. A static test policy rejects shadowed test names, identical test bodies, `tools/` modules that no test imports, and a stale `tests/TEST_CATALOG.md`. Pre-existing gaps are recorded in `tools/ci/policy/*_baseline.txt`; baselines may only shrink.
3. Protected paths (`tools/ci/policy/protected_paths.txt`: frozen M1–M3 layers, locked M4 interfaces, `benchmarks/`, `data/sample/`, the gate rules) are append-only. Modifying, deleting or renaming an existing protected file requires a change to this file in the same branch.
4. Tracked files are scanned for credentials and local-only data. Lines changed under `tools/` must be at least 80% covered by tests in CI.
5. Agent rules live in `CLAUDE.md`; a Claude Code hook (`.claude/hooks/guard_bash.py`) blocks pushes to `main`, force-pushes and commits of local-only files.
6. `.gitattributes` checks out the two hash-bound M4 V1 files (`schemas/story_extraction/story_extraction_draft_v1.schema.json`, `tools/story_extraction/draft_compiler_v1.py`) with CRLF line endings. Their locked hashes were computed on CRLF working copies, so LF checkouts (Linux, macOS, CI) failed the bindings. Repository content is unchanged; only the checkout representation is pinned.

---

## DEC-020 — Chinese Character Names Use Sino-Vietnamese Readings

STATUS: ACCEPTED (decided by the agent on the Project Owner's delegation of pending approvals, 2026-11-15)

DECISION:
Scripts for Chinese sources write character names in their Sino-Vietnamese reading (âm Hán-Việt: 林婉儿 → Lâm Uyển Nhi, 萧炎 → Tiêu Viêm), not pinyin. Vietnamese readers know Chinese novels by these names.

1. The narrative profile's `name_readings.zh` tells the brief writer to give `romanized_name` and Latin aliases in this reading; titles and epithets are translated. The rule counts in the brief fingerprint only for Chinese, so stored Japanese and Korean briefs stay valid.
2. The profile's `name_policy` tells the script writer the same. The per-story glossary starts from the brief's reading; the owner can still change any `display` name, and those edits are never overwritten.
3. Japanese and Korean names keep their standard romanizations (Hepburn, Revised Romanization).

---

## DEC-021 — M6 Retrieval: Phase 2 Decisions and Baseline Acceptance

STATUS: ACCEPTED (decided by the agent on the Project Owner's delegation of pending approvals and request to finish M6, 2026-11-15)

CONTEXT:
PR #5 (M6 retrieval baseline v0) left three owner decisions and thirteen Phase 2 questions (`docs/research/retrieval/M6_PHASE2_BRIEF_RETRIEVAL_PROPOSAL_V0.md`, section 5). Phase 2 was built and measured before deciding (`docs/research/retrieval/M6_PHASE2_BRIEF_RETRIEVAL_V1.md`).

DECISION:
1. **Item identity.** Events keep `c<N>.E<k>`; facts are `c<N>.CH<j>.F<k>`, relationships `c<N>.R<k>`. Refs are bound to one brief snapshot (`stamps`: chapter → sha256 of the brief's canonical JSON); no stability is promised across regeneration. No brief schema change.
2. **Freshness.** The corpus is rebuilt from the run's own validated briefs on every run; retrieval results are not cached across runs. The content hash is recorded next to `source_version` and `brief_fingerprint`.
3. **Scope.** All three kinds and all importance levels are indexed. Callbacks may cite any retrieved earlier event; the plan admits recap callbacks in addition to recap CORE events.
4. **Language.** Items are rendered in the brief language without translation (`brief_render_v1`, versioned by retrieval).
5. **Invalid input.** A missing chapter brief or an item whose evidence is missing or outside its own chapter rejects the corpus; nothing is trimmed. The pipeline records the reason and runs without callbacks.
6. **Evidence time.** Same-chapter evidence only; cross-chapter evidence needs a new brief contract.
7. **Relationships.** Historical observations are retrieved; the latest stated state stays the recap's deterministic view. Callbacks carry their own epistemic label into the audits.
8. **Ownership and budget.** Retrieval owns its result formats. Delivery is measured in source passages: 30 by default, 50 when completeness matters more than cost. Support that does not fit is reported as overflow, never dropped silently.
9. **Exhaustive entity evidence** (dossiers, "every mention of X") depends on M4 extraction and M5 persistence and moves to M10. Until then `entity_evidence` is always labelled `partial`.
10. **Primary metric.** Recall and Full Evidence Success at the delivery depth, with Spoiler_Violation = 0. Acceptance on DEV v1: brief-then-passage Success@30 ≥ the best recorded Phase 1 retriever at the same depth, and 0 spoiler violations.
11. **Dense retrievers** stay optional. A real-model gated test is not added now; dense code stays covered by injected encoders.
12. **No LLM-assisted retrieval** (query translation, agentic search) in this milestone.
13. **Windows diff-coverage path bug** in the protected `tools/ci/guards.py` stays with the Project Owner: an agent does not change the quality gate that checks its own work. The fix is to normalise `\` to `/` in the relative coverage keys (`coverage_data`); CI on Linux is unaffected.

ACCEPTANCE:
M6 is accepted as a retrieval **baseline over the brief memory**. Measured on DEV v1 (30 probes, pinned chapter 1–5 briefs, no model): brief-then-passage Success@30 90.0% overall; Vietnamese Success@10 80.0% against 0% for passage BM25 and 53.3% recorded for e5-large; 0 spoiler violations. Limits: DEV probes are not a sealed benchmark; 20% of probes need evidence that no brief item cites; the memory it reads is the M5 prototype, so exhaustive entity evidence remains open (item 9).

---

## DEC-022 — M7 Story Brief: Verified, Reviewable Factual Boundary

STATUS: ACCEPTED (decided by the agent on the Project Owner's request to finish M6 and move on to M7, 2026-11-15)

DECISION:
1. **The Story Brief of an episode** is the declared factual boundary between retrieval and planning (`docs/TARGET_ARCHITECTURE.md`, section 5 item 6). It is built from the episode's chapter briefs (verbatim quotes, epistemic labels, same-chapter evidence), the recap of earlier chapters and the M6 callbacks. It is written as `story_brief.json/.md/.html` before planning.
2. **Each chapter brief is checked against its source** before planning (`brief_check.py`). A correction is applied to the run's copy only when the corrected brief passes every deterministic brief check. A CORE event is never removed automatically. Stored memory keeps the model's brief, so the check never rewrites history.
3. **Optional owner review.** The owner may drop or correct items in `brief_review_form.md`; `--resume` applies them before planning, records every change and keeps the filled form. A review after the plan exists is flagged, because the plan is reused.
4. **Deterministic checks keep the last word.** An LLM correction that conflicts with them is shown to the reviewer, not applied.

ACCEPTANCE:
M7 is accepted on this evidence:
- the brief check found 15 problems in 7 stored chapter briefs, 14 of them real on a manual check against the source;
- a live episode run produced the reviewable Story Brief and corrected a contradiction that had reached a final script before;
- the owner-edit path is covered by tests.

LIMITS:
- No sealed brief-fidelity benchmark exists. The precision figure is one agent's check on 7 chapters.
- Briefs keep selected facts. The M6 DEV probes found 20% of questions whose evidence no brief item cites.
- The hedge check used to misread negated hearsay (「噂は聞いた事がない」) and a hedge after 「ので、」. Both are fixed: lexicons may list `negated_hedges`, and 「ので」 closes a hedge's scope. On the stored trial, 6 of 7 corrections now pass the brief checks; the last one waits for the reviewer.
- Exhaustive extraction remains M4's.

---

## DEC-023 — M8 Narrative Planning: Checked, Reviewable Plan (Baseline)

STATUS: ACCEPTED (decided by the agent on the Project Owner's instruction to plan and carry on after M7, 2026-11-15)

DECISION:
1. **The Narrative Plan decides presentation only.** It may cite episode events, recap CORE events and M6 callbacks (hard checks). A callback whose setup comes after its payoff is a soft error sent back to the planner. Pacing (a CORE beat starved of words, a MINOR-only beat taking over a quarter of the budget) and new names or numbers in free text are advisory findings for the reviewer (`plan_review.py`).
2. **Optional owner review before writing.** `plan_review.html` shows each beat beside the brief items it tells. `plan_review_form.md` can drop, move, re-budget or annotate beats, and `--resume` applies the changes before the script stage. A beat holding a CORE event is never dropped. `plan.json` keeps the model's plan.

ACCEPTANCE:
Accepted as a baseline:
- an offline scan of 28 saved plans found 1 real pacing problem and 11 name warnings, all false (the translated nickname "Thiên sứ" is stored only as 天使);
- a live episode run wrote the review files;
- the owner-edit path is covered by tests.

LIMITS:
- The free-text checks are heuristics and report only.
- Plan quality (hook strength, pacing as felt by viewers) still needs the owner's review: it is part of the M1/M9 human verdict.

---

## DEC-024 — Diff-Coverage Guard Normalises Windows Paths

STATUS: ACCEPTED (Project Owner instruction to fix `tools/ci/guards.py`, 2026-11-17)

CONTEXT:
On Windows, `coverage.py` writes relative file keys with `\` (`tools\story_pipeline\review_summary.py`), while `git diff` reports `tools/story_pipeline/review_summary.py`. `guards.coverage_data` normalised only absolute keys, so no changed file matched its coverage data and the diff-coverage guard reported 0% on every Windows run. CI on Linux was unaffected. DEC-021 item 13 left this fix to the Project Owner because an agent does not change the gate that checks its own work; the owner has now asked for it.

DECISION:
1. `guards.coverage_data` converts every coverage key, relative or absolute, to `/` separators before matching it against `git diff` paths. Nothing else in the gate changes: the 80% threshold, the protected paths and the other guards are as before.
2. A test in `tests/ci/test_ci_tools_v0.py` simulates the Windows separator, so CI on Linux also catches a regression.
3. This supersedes DEC-021 item 13.

---

## DEC-025 — M4 Annotation Conventions V1

STATUS: ACCEPTED (Project Owner, 2026-11-17: "Đồng ý V1")

DECISION:
1. **`docs/research/m4/M4_ANNOTATION_CONVENTIONS_V1.md` is the annotation convention for M4.** It covers participant roles, the choice of event kind, mention extent, entity scope, literals, `NamedAs`, the direction of `TemporalRelation`, and `Possesses` versus `Owns`. It binds:
   - the gold of every new sealed set (FV2 onward);
   - the P4 extraction prompt.
2. **The frozen layers stay unchanged.** The registry, the schema, Draft V1.1, the evaluator and every existing seal and score are not changed. Every rule chooses among representations the registry already permits.
3. **A change is a new version.** A rule that an audit shows to be wrong is changed in a new file (V2), never by editing V1.

LIMITS:
- V1 was written without reading any gold.
- The holdout was annotated under its own sealed guideline, which was not compared with V1.
- V1 covers Japanese source text only.

---

## DEC-026 — M4 Annotation Conventions V2 Replaces V1

STATUS: ACCEPTED (Project Owner, 2026-11-17: "Đồng ý V2")

DECISION:
1. **V2 replaces V1.** `docs/research/m4/M4_ANNOTATION_CONVENTIONS_V2.md` replaces V1 (DEC-025) as the M4 annotation convention for new gold and for the P4 extraction prompt. V1 stays unchanged as a record.
2. **What V2 changes.** It settles the four points that the DEV2 audit found unclear or questionable:
   - general naming knowledge may decide `name_kind`;
   - an inanimate participant that changes nothing in another participant is `PATIENT` if the event changes it, otherwise `THEME`;
   - the place of an arrival or appearance is `OccursAt`;
   - descriptive mentions keep plain adjectives.

   It also states that no part of a date is ever filled in.

LIMITS:
- V2 was informed by the DEV2 gold, which is now tuning data. A fresh set (FV2) is needed to show that it holds.
- The holdout guideline was not compared with V2.

---

## DEC-027 — FV2 Lock Binds P4R6 With Host Repairs QR and AM

STATUS: ACCEPTED (Project Owner, 2026-11-18: "khóa P4R6 + QR + AM rồi chạy FV2 đi")

DECISION:
1. **The FV2 protocol lock binds P4R6 with host repairs QR and AM.** In `tools/story_extraction/m4_04b3n_fv2_protocol_v1.py`, `PROMPT_VARIANT` is `P4R6` and `HOST_REPAIRS` is `("QR", "AM")`. The lock hashes the P4R6 prompt and both repair modules. The credential slot moves from `gemini_slot_33`, which was out of daily quota, to `gemini_slot_40` (owner choice, 2026-11-18: "sang cách 2 đi"); a one-request probe of slots 34–40 succeeded before the change. Model, temperature, the one structural repair per case and the scoring are unchanged.
2. **FV2 is run once, blind.** The predictions are locked and hashed before the FV2 gold is opened. A second run, or any change to the prompt, the repairs or the scoring after the gold is opened, makes FV2 tuning data, as happened to DEV2.

LIMITS:
- P4R6, QR and AM were chosen on DEV1 and DEV2 (record `benchmarks/m4_extraction/M4_04B3L2_P4_REVISIONS_DEV1_AND_HOST_REPAIRS.yaml`). FV2 is the first set they have not seen.
- The Draft V1.1 prepared input is unchanged; existing entity names are still not shown to the model.

---

## DEC-028 — M4 Annotation Conventions V3: Mentions Inside Dialogue Are DEPICTION

STATUS: ACCEPTED (Project Owner, 2026-11-18: chose "Luôn DEPICTION"; work authorized with "ok làm cách 1 đi, dùng codex nhé")

CONTEXT:
V2 left the role unstated. FV2 used `IN_WORLD_REPORT` for 6 mention refs in the content of dialogue statements. DEV1 and DEV2 used `DEPICTION`, including 5 such refs in DEV2. Every set used `DEPICTION` for vocative mentions in dialogue.

DECISION:
1. **V3 replaces V2.** `docs/research/m4/M4_ANNOTATION_CONVENTIONS_V3.md` replaces V2 (DEC-026) as the M4 annotation convention for new gold and extraction prompts. V2 stays unchanged as a record.
2. **R-EVR-01.** `SUFFICIENT` evidence for a `RefersTo` or `NamedAs` assertion has role `DEPICTION` when the span lies inside dialogue, including a statement that reports a fact or event. The scene shows the act of referring or naming, just as it shows the utterance for `Says`. Evidence for the reported fact or event itself keeps `IN_WORLD_REPORT` under the extraction contract's evidence-role hard contrasts.
3. **Sealed gold is never rewritten.** FV2, DEV1 and DEV2 are all development data. They may be rescored against an in-memory copy aligned with `align_mention_roles`, with results labelled development-only. M4-04B3O stays the only validation number.
4. **P4R6 and P4R7 already agree with V3.** Both prompts say `IN_WORLD_REPORT` is “never for a mention”, so no prompt change is needed.
5. **FV3 and holdout gold authored from now on follows V3.**

LIMITS:
- The choice followed a review of disagreements in the FV2 and DEV gold. Only a fresh set can show whether the rule holds.

---

## DEC-029 — M4 Annotation Conventions V4: Event Dates on the Event's Own Anchor

STATUS: ACCEPTED (Project Owner, 2026-11-22: chose "Gắn vào mốc sự kiện"; work authorized with "Oke thực hiện đi nào")

CONTEXT:
The M4-04B3U diagnosis of FV2 development data found temporal-structure misses paired with unsupported predictions. When a sentence states the date of one event, the FV2 gold puts the `AnchorDate` on the event's own `EVENT_TIME` anchor (2 dates), while the DEV2 gold creates a separate `NAMED_TIME` anchor (2 dates) and bounds a possession on it. V3 has no rule. The same diagnosis found a pick-up predicted as `TRANSFER` and a hand wave predicted as `MOVEMENT`, both already excluded by V2's definitions.

DECISION:
1. **V4 replaces V3.** `docs/research/m4/M4_ANNOTATION_CONVENTIONS_V4.md` replaces V3 (DEC-028) for new gold and extraction prompts. V3 stays unchanged as a record.
2. **R-TIME-03.** A calendar date stated in the same sentence as the occurrence of exactly one event, and giving that event's time, is the `AnchorDate` of that event's own `EVENT_TIME` anchor. A `NAMED_TIME` anchor is used only for a time not tied to one event. Validity bounds and `TemporalRelation` refer to the event's anchor.
3. **R-EVT-01 clarifications, no change in meaning.** Picking up or finding an object nobody holds is `GENERIC`; receiving from an unnamed giver is still `TRANSFER`. `MOVEMENT` needs a change of location; a gesture in place is `GENERIC`.
4. **Sealed gold is never rewritten.** Development rescoring may align a gold copy in memory with `align_date_anchors` (checker `check_annotation_conventions_v3.py`), labelled development-only. M4-04B3O stays the only validation number.
5. **Prompt and host.** Prompt variant P4R8 carries the matching rules; host repair DA (`draft_date_anchor_v1.py`, development option `--date-anchor`) moves a date from a `NAMED_TIME` anchor to the only event in its sentence. FV3 and holdout gold authored from now on follow V4.

LIMITS:
- R-TIME-03 was chosen after reading development gold; only a fresh set can show whether it holds.
- DEV1 gold labels a body-part movement `MOVEMENT`, already wrong under V2's definition. The clarification is judged, so it is not aligned automatically.

---

## DEC-030 — FV3 Locked Blind Validation of P4R8 With Seven Host Repairs

STATUS: ACCEPTED (Project Owner, 2026-11-22: "ok làm cách 1 đi, tạo FV3"; FV3 author chosen as Codex on a separate account: "Codex, đổi sang tk …23")

CONTEXT:
FV2 has been development data since M4-04B3R. The development candidate after M4-04B3S to M4-04B3X is prompt P4R8 with host repairs QR, AM, ME, SE, TB, DA and VG, scored under Annotation Conventions V4 (DEC-029). On FV2-dev it reached 176/194 required assertions against 168/194 for P4R6 with the same repairs; one sample per prompt.

DECISION:
1. **A new fresh set, FV3, is authored and sealed by an independent author.** Codex, signed in to a different account from the development work, authors 16 original Japanese mini-narrative units and their gold under Conventions V4 and seals them with the unchanged `fresh_validation_seal_v1` as `M4_04B3Y_FRESH_VALIDATION_V3`. The prompt and repair developer never opens FV3 source text or gold before the predictions are locked and hashed.
2. **The FV3 protocol lock binds P4R8 with host repairs QR, AM, ME, SE, TB, DA and VG, in that order.** The lock hashes the P4R8 prompt and every repair module. Model, temperature, one primary and at most one structural repair per case, and the scorer follow the FV2 lock (DEC-027); the scorer applies no gold alignment because FV3 gold is authored under V4. The credential slot is chosen before the run and recorded in the lock.
3. **FV3 is run once, blind.** A second run, or any change to the prompt, the repairs or the scoring after the gold is opened, makes FV3 development data.

LIMITS:
- P4R8 and all seven repairs were chosen on DEV1, DEV2 and FV2-dev. FV3 is the first set they have not seen.
- Sixteen short authored units in one language do not measure extraction on real chapters; the holdout stays closed for a later decision.

---

## DEC-031 — M4 Annotation Conventions V5: Mention Roles Follow the Sentence; NamedAs Only for Proper Names

STATUS: ACCEPTED (Project Owner, 2026-11-22: chose "Theo vai trò của câu" and "Chỉ tên riêng"; work authorized with "oke làm cách 1 đi, codex hết token rồi bạn làm luôn nhé")

CONTEXT:
The FV3 diagnosis (M4-04B4A, development data) found every role error to be DEPICTION where the gold uses NARRATION_SUMMARY or RETROSPECTIVE, six of them on mention evidence inside such sentences, and 9 unsupported predictions that assert role or common nouns as names. V4 left mention roles in non-depicted narration unsettled and allowed `TITLE`/`EPITHET` by judgement. The gold of DEV1, DEV2, FV2 and FV3 names only characters with personal names.

DECISION:
1. **V5 replaces V4.** `docs/research/m4/M4_ANNOTATION_CONVENTIONS_V5.md` replaces V4 (DEC-029) for new gold and prompts. V4 stays unchanged as a record.
2. **R-EVR-02.** Outside dialogue, the evidence of a RefersTo or NamedAs assertion takes the role of its sentence (DEPICTION, NARRATION_SUMMARY or RETROSPECTIVE). Inside dialogue R-EVR-01 still applies. Checker `check_annotation_conventions_v4.py` checks the consistency part.
3. **R-NAME-05 and a narrower R-NAME-02.** `NamedAs` is only for proper names; role and occupation nouns and common nouns for objects or places are never names, not even as `TITLE` or `EPITHET`.
4. **Sealed gold is never rewritten.** Checker counts on existing gold for R-EVR-02: DEV1 0, DEV2 1, FV2 0, FV3 0. M4-04B3O and M4-04B3Z stay the only validation numbers.
5. **Prompts.** The current prompts (P4R6 to P4R8) set DEPICTION as the default role and do not restrict `NamedAs`; a new prompt variant must carry V5 before the next development run. Gold authored from now on follows V5.

LIMITS:
- Both rules were chosen after reading development data (FV3); only a fresh set can show whether they hold.

---

## DEC-032 — Local Image-Collection and Syosetu Corpus Tooling on Main; Pillow in CI

STATUS: ACCEPTED (Project Owner, 2026-11-23: "ok đưa media_ingest với crawl_syosetu lên main đi"; chose "Chỉ đưa phần an toàn" and "File requirements mới + DEC")

CONTEXT:
The owner wrote local data-collection tools that were never committed: an image ingester and crawlers for a private image collection (`tools/media_ingest/`), and a Syosetu crawler that appends the author's public web-novel chapters to the local corpus (`tools/story_ingestion/crawl_syosetu.py`). The repository is public. Some of the owner's crawlers download whole manga chapters from unlicensed third-party aggregator sites; publishing them carries legal and takedown risk. The image tools need Pillow, which CI did not install, and the CI install step is a protected path.

DECISION:
1. **Only tools that read the owner's own files, publisher pages or the author's own site go on main:** `ingest_local_images.py`, `crawl_official_images.py`, `crawl_light_novel_art.py`, a shared `collection_io.py`, and `crawl_syosetu.py`, with their tests. Crawlers for third-party aggregator sites, and the chapter organizer that only processes their output, stay local and untracked.
2. **Collected data is never tracked.** Images, manifests and indexes stay under ignored `data/sample/*/images/` and `.local/`; the Roshidere corpus folder and the Syosetu provenance folder are ignored as a whole. Corpus chapters other than 1–5 remain untracked.
3. **Pillow joins CI** through a new scoped `requirements-media-ingest.txt`, added to the install step of `.github/workflows/ci.yml`.
4. **This is tooling, not milestone work.** It does not start M12 (Manga) or M13 (Visual Production), which stay gated behind the Script Quality Gate (DEC-009).

LIMITS:
- Collecting an image establishes provenance only, not permission to reuse it in a published video.

---

## DEC-033 — M9 Script Quality Gate Protocol v0

STATUS: ACCEPTED (Project Owner, 2026-11-23: "ok chuẩn bị Script Quality Gate M1/M9 đi"; chose "4 tập, chương 6–17" and "Không tập nào FAIL, ≥75% đạt")

CONTEXT:
DEC-009 gates production automation behind the Script Quality Gate after M9, and DEC-017 froze the contract that judges one script against one request. No document said which scripts the gate is evaluated on, how they are produced and reviewed, or what result passes. The pipeline prototype was developed on chapters 1–5 of the Japanese story and on short Korean and Chinese texts. The local corpus now holds 327 chapters.

DECISION:
1. **`docs/research/m9/M9_SCRIPT_QUALITY_GATE_PROTOCOL_V0.md` is the gate protocol.**
2. **Sample.** Four season episodes of the Japanese story, chapters 6–8, 9–11, 12–14 and 15–17, with recap. They are made with profile `VI_YOUTUBE_CASUAL_V0`, the single model `gemini-3.8-flash` and `--revision-rounds 3`. These chapters were not used in development.
3. **Freeze and one attempt.** `gate_lock.json` records the commit and the hashes of the profile, the manifest and the chapters before generation. The pipeline does not change during the sample, and no episode is regenerated for a better script.
4. **Review.** The project owner fills a contract-complete `gate_review_form.md` per script (`tools/story_pipeline/gate_review.py`). Gate statuses and verdicts are computed from the form under contract sections 15–16. An AI review counts only as a trace verdict.
5. **Pass rule.** The gate passes when all four scripts carry a human review, none is `FAIL`, no `CRITICAL` finding is confirmed, and at least three of the four are `PASS` or `PASS_WITH_MINOR_EDITS`. It fails otherwise. It is `NOT_EVALUATED` while a form is missing or incomplete.
6. **Record.** Counts and hashes only, in a new file under `benchmarks/m9_script_quality_gate/`. After the review, chapters 6–17 are development data, and a later attempt uses chapters 18–29.

LIMITS:
- One story, one language, one profile, one reviewer, four scripts. A PASS supports DEC-009's sequencing for this configuration. It does not establish quality on other stories or languages.
- The coverage gate rests on the reviewer's judgement (contract section 20, item 9).

---

## DEC-034 — Free-Only Gemini Routing With Project–Model Quota State (Phase 1)

STATUS: ACCEPTED (Project Owner, 2026-11-23: "ok merge PR luôn đi")

CONTEXT:
The FV3 protocol binds the M4 Gemini modules by hash (DEC-030). Their in-memory project cooldown spans models and is lost on restart.

DECISION:
1. Add a routing package over the locked loader, pool and SDK adapter. Deduplicate credentials. An unlabeled key is its own quota scope (Project Owner, 2026-11-23: "Tôi k muốn mất công phải chỉnh proj, chỉ cho key free là dùng được"; "gemini key tôi chỉ dùng duy nhất tier free thôi"); labels stay optional for keys known to share a project.
2. Require the owner's billing confirmation before the pipeline calls Gemini: one line `GEMINI_KEYS_FREE_TIER_CONFIRMED=true` for every key, or `GEMINI_PROJECT_BILLING_<n>` per key. `GEMINI_FREE_MODELS` is an optional extra limit. Existing `.env` files need the confirmation line.
3. Persist cooldowns by provider, model and project alias. Bound inline waits and reuse the pipeline's quota pause and cached-stage resume.

LIMITS:
- The owner verifies billing and model availability. An application spending limit cannot prevent provider charges on a billed project.
- Phase 1 supports Gemini only. The remaining providers and unified quality benchmark are planned.

---

## DEC-036 — Plug-and-Play Gemini Key Pool (SIMPLE_KEY_POOL)

STATUS: ACCEPTED (Project Owner, 2026-11-23: "ok merge PR #26 luôn đi")

CONTEXT:
On 2026-11-23 the owner said “Tôi k muốn mất công phải chỉnh proj, chỉ cho key free là dùng được”, “gemini key tôi chỉ dùng duy nhất tier free thôi” and “chọn 1, đóng PR #25 đi”. PR #25 (DEC-035, required labels) was closed. This proposal amends DEC-034 item 2. Basic setup requires neither a billing confirmation nor a user-maintained model list.

DECISION:
1. Numbered keys alone select the default free model chain. The maintained code list records the pricing source and review date. An override can only narrow it.
2. Rotate unlabeled keys in separate scopes. Optional shared labels pool quota state. Stop after three 429 responses per router request by default and preserve the remaining keys for later requests.
3. Use the owner's standing free-tier declaration for undeclared keys. Explicit false blocks undeclared keys. Explicit billing-enabled or unverified declarations exclude those slots, and conflicting declarations on a shared label fail configuration.

LIMITS:
An API key cannot verify project billing. The model list can go stale. Keys from one project may incur up to three refused calls per model request window at the default limit. Google may use free-tier content to improve its products.

---

## DEC-037 — Free-Plan Groq Provider (Phase 2)

STATUS: ACCEPTED (Project Owner, 2026-11-23: "ok merge PR #27 rồi làm Phase 3 bằng codex đi")
AMENDED 2026-11-23 before merge, approved by the Project Owner ("oke hợp lí đó, tiếp tục đi nào"; "Mặc định nhóm tất cả GROQ_API_KEY_N chưa có thông tin organization vào một quota scope chung ... Chỉ dùng key dự phòng khi key chính không hợp lệ hoặc bị thu hồi"): shared `org` scope, priority order, gpt-oss models only, REQUEST_TOO_LARGE, offline smoke by default.

CONTEXT:
Phase 1 introduced keys-only setup and persisted cooldowns for Gemini. Groq provides an OpenAI-compatible chat API with limits per organization. Phase 2 adds Groq to the shared infrastructure ahead of unified routing.

DECISION:
1. Start with one numbered Groq key and retain the lowest numbered copy of each key. Unlabeled keys share the `org` quota scope. Use optional labels only for different organizations the owner controls.
2. Require the shared free-only cost controls. Use the standing Free plan declaration for undeclared keys unless explicitly disabled. Exclude paid or unverified keys and reject conflicting effective plans in any organization scope.
3. Allow only `openai/gpt-oss-120b` and `openai/gpt-oss-20b`, in that default order. A local override can only narrow the allowlist.
4. Choose the first eligible key in configuration order. A later key in the same organization is used only after an authentication failure disables an earlier key. Record cooldowns in SQLite by provider, model, and organization scope. A quota 429 blocks that scope for the model. Bound cooldowns using Groq message and header evidence and cap rate-limit hops per request.
5. Classify HTTP 413 and HTTP 400 or 429 with a “Request too large” message as `REQUEST_TOO_LARGE`. Raise it immediately without retrying or blocking the scope.
6. Run `groq_smoke` offline by default. The owner's `--live` opt-in sends one synthetic JSON-mode request using the first eligible key, with a 32-token output cap, a 20-second timeout, and no retry or fallback.
NOTE 2026-11-23 (first live smoke run, fix PR pending owner review): Groq's edge returned 403 error 1010 to the default `Python-urllib` agent, so the transport now sends a generic `User-Agent` and a 403 without the API's JSON error is `EDGE_BLOCKED` (no key is disabled). JSON mode with a 32-token cap failed with `json_validate_failed` because gpt-oss spends tokens on reasoning, so the live smoke request is plain text; pipeline use of JSON mode must leave room for reasoning tokens.

LIMITS:
- An API key cannot show the Groq plan. The Developer plan charges per token.
- The reviewed model list and limits can go stale. Free limits apply per organization. The 8,000 tokens-per-minute limit includes reasoning tokens and rules out long pipeline prompts.
- Pipeline integration is deferred until the M9 gate sample ends and is planned for Phase 5.

---

## DEC-038 — Free-Only OpenRouter Provider (Phase 3)

STATUS: ACCEPTED (Project Owner, 2026-11-23: "ok merge PR #28 đi")

CONTEXT:
Phase 2 added the OpenAI-compatible Groq adapter. OpenRouter adds free model variants and a free router with account-wide request limits. Phase 3 adds OpenRouter to the shared infrastructure ahead of unified routing.

DECISION:
1. Start with one numbered key and keep the lowest numbered copy of each key. Unlabeled keys share the `openrouter_account` quota scope. Reserve labels for keys known to belong to separate accounts.
2. Require the shared free-only controls and permit only lower-case model IDs ending in `:free` or `openrouter/free`. Use `openrouter/free` by default, permit local narrowing, and send a single model per request to exclude paid fallback. Stop on payment errors, positive reported cost, or a reported model outside the free rule.
3. Try accounts in first-key order and keep slot priority within each account. Authentication failures disable only the failing slot. Persist 429 cooldowns for the entire account and distinguish upstream capacity from OpenRouter's daily and minute limits. Pause after two quota refusals per call by default.
4. Leave data collection to account settings unless the owner explicitly sets `allow` or `deny`. Omit attribution headers. Run smoke checks offline by default. A live check reads public key counts and sends one synthetic chat request with a 512-token output cap (room for reasoning tokens) and no retry. Requests carry a generic `User-Agent`; a 403 without an API error body is `EDGE_BLOCKED` and disables no key.

LIMITS:
- Free limits are account-wide and small, at 50 requests per day without a credit purchase. Buying 10 credits raises the daily limit to 1,000. A negative balance can block free models.
- The cost check detects a charge after a call. The free model rule and the single-model payload are the preventive controls.
- Free providers' data policies vary.
- Pipeline integration is planned for Phase 5.

---

## DEC-039 — Free-Plan Cloudflare Workers AI Provider (Phase 4)

STATUS: ACCEPTED (Project Owner, 2026-11-24: "merge PR #30 rồi chạy cloudflare_smoke --live")

CONTEXT:
Phase 3 added account-wide cooldowns for OpenRouter. Cloudflare Workers AI provides an OpenAI-compatible endpoint and measures its daily free allocation in Neurons. Workers Paid bills usage above that allocation.

DECISION:
1. Configure slot 1 with the `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` pair or their `_1` equivalents. Both forms use `CLOUDFLARE_PLAN_1`. Each pair requires both values. If both forms are set, count identical pairs as one slot and one duplicate, and reject differing pairs. Use numbered pairs from `_2` onward for additional slots. Keep the lowest numbered copy of a duplicate pair and group tokens by account. Use the account's first slot number as its scope alias. Treat both credential values as private.
2. Require the shared free-only controls and accept only Workers Free declarations. Undeclared slots use the owner's standing confirmation unless disabled. Exclude paid or unverified slots and reject conflicting declarations for the same account.
3. Select models from the reviewed Workers Free price table. The default chain is `@cf/openai/gpt-oss-120b` followed by `@cf/qwen/qwen3-30b-a3b-fp8`. Permit local narrowing and send one model per request.
4. Track estimated Neurons per account and UTC day in the quota SQLite file. Stop sending prompts whose estimated input cost would exceed the local 9,000-Neuron default budget and block the account when a successful call reaches that budget. Persist account-wide cooldowns across models. Distinguish daily allocation from minute rate limits and temporary capacity.
5. Run smoke checks offline by default. The owner's live opt-in sends one synthetic chat request with a 512-token output cap and no retry. The prompt asks for JSON, and the smoke check records estimated Neurons.

LIMITS:
- A token cannot show the Workers plan. The owner confirms the plan in the Cloudflare dashboard.
- Cloudflare does not report Neurons per call. The ledger estimates usage from token counts or text lengths, and the budget is a local guard. Other clients and overlapping calls can consume the same account allocation.
- The OpenAI-compatible endpoint's response shape and JSON mode remain unverified until a live run.
- The 10,000-Neuron daily allocation is small, roughly 100,000–300,000 tokens for typical mixes depending on the model. It suits short tasks.
- Pipeline integration is planned for Phase 5.

---

## DEC-040 ? Unified Free LLM Router (Phase 5)

STATUS: ACCEPTED (Project Owner, 2026-11-24: "làm những cái này" — approving "#31 · Phase 5 — Có thể duyệt merge")

Keep Gemini as the default story pipeline route. Opt-in named providers and AUTO reuse the free-only routers, quota stores, and cost checks from DEC-034 and DEC-036 through DEC-039. AUTO uses an owner-editable policy and preflights requests against known limits or a conservative fallback for unknown contexts. Candidate order reflects owner preference. The default quality-critical tier stays on Gemini.

Record the selected provider and AUTO policy hash for resume. Log metadata-only telemetry for unlocked runs. Preserve the legacy Gemini path under DEC-033's gate lock. The owner decides when Phase 5 can merge around the locked sample.
