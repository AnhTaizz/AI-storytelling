# Roadmap

Status: ACCEPTED — TASK 000E.

Each milestone is intentionally high-level. Detailed execution tasks are created just in time when reaching the relevant milestone, avoiding speculative task explosion.

## M0 — Product Foundation

- Purpose: Establish product vision, MVP boundary, architectural principles, and initial decisions.
- Expected capability: A shared conceptual and documented foundation for Story Intelligence work.
- Dependency: None.

## M1 — Script Quality & Narrative Contract

- Purpose: Define what a high-quality, grounded script must satisfy.
- Expected capability: An explicit narrative and quality contract establishing standards for the first major output.
- Dependency: M0.

## M2 — Canonical Story Model

- Purpose: Establish a source-independent domain model for story understanding.
- Expected capability: A common conceptual basis for downstream Story Intelligence, independent of source formats and storage technologies.
- Dependency: M1.

## M3 — Light Novel Ingestion

- Purpose: Support the initial source format.
- Expected capability: Controlled Light Novel text is ingested with preserved source passages and evidence references.
- Dependency: M2.

## M4 — Story Extraction

- Purpose: Transform ingested text into grounded story understanding.
- Expected capability: Key events, entities, relationships, information, and state changes are extracted and validated against source evidence.
- Dependency: M3.

## M5 — Persistent Story Memory

- Purpose: Retain story understanding across chapters and volumes using a baseline persistence architecture.
- Expected capability: Historical story context persists reliably across narrative progression without requiring an initial full-scale graph implementation.
- Dependency: M4.

## M6 — Retrieval Baseline

- Purpose: Provide relevant story context to downstream planning and generation stages.
- Expected capability: Context and evidence can be retrieved accurately for a requested story scope or inquiry.
- Dependency: M5.

## M7 — Story Brief

- Purpose: Produce a structured intermediate summary of the story and requested coverage.
- Expected capability: A factual, evidence-grounded Story Brief is generated and available for review before storytelling planning.
- Dependency: M6.

## M8 — Narrative Planning

- Purpose: Translate story understanding into deliberate storytelling and presentation choices.
- Expected capability: A Narrative Plan guides structure, tone, pacing, emphasis, commentary, hooks, and callbacks separate from factual extraction.
- Dependency: M7.

## M9 — Script Generation & Validation

- Purpose: Generate and verify the first major product output.
- Expected capability: A grounded YouTube script is generated following the Narrative Plan and validated for factual truth, temporal consistency, and evidence adherence.
- Dependency: M8.

---

## Script Quality Gate

M9 must establish verified script quality and factual reliability before production automation or format expansion begins. Downstream milestones build upon this verified storytelling foundation.

---

## M10 — Advanced Narrative Retrieval

- Purpose: Enhance retrieval precision for complex narrative dependencies.
- Expected capability: Targeted, context-aware retrieval supporting subtle narrative planning, reveals, and callbacks.
- Dependency: Script Quality Gate (M9).

## M11 — Temporal / Graph Story Memory

- Purpose: Extend persistent story memory with rich temporal and structural graph reasoning.
- Expected capability: Deeper structural traversal over evolving entity states, complex causality, foreshadowing, and information asymmetry, introduced based on observed retrieval needs.
- Dependency: M10.

## M12 — Manga Ingestion

- Purpose: Expand source ingestion beyond the initial Light Novel format.
- Expected capability: Manga visual and textual content is converted via dedicated adapters into the shared Canonical Story Representation.
- Dependency: M11.

## M13 — Visual Production

- Purpose: Bridge validated storytelling scripts to visual production workflows.
- Expected capability: Scene breakdowns, visual pacing cues, and asset planning aligned with script structure.
- Dependency: M12.

## M14 — Voice & Video Automation

- Purpose: Automate downstream voice and video generation workflows.
- Expected capability: Validated storytelling outputs drive automated voice synthesis and video editing pipelines.
- Dependency: M13.
