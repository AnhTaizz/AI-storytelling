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
