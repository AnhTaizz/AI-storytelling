# Roadmap

Status: Defined in TASK 000E.

Each milestone is intentionally high-level. Detailed implementation tasks are generated just in time.

## M0 — Product Foundation

- Purpose: Establish the product direction, MVP boundary, principles, and initial decisions.
- Expected capability: A shared foundation for planning Story Intelligence work.
- Dependency: None.

## M1 — Script Quality & Narrative Contract

- Purpose: Define what a high-quality grounded script must satisfy.
- Expected capability: An explicit narrative and quality contract for the first major output.
- Dependency: M0.

## M2 — Canonical Story Model

- Purpose: Establish a source-independent representation for story understanding.
- Expected capability: A common conceptual basis for downstream Story Intelligence.
- Dependency: M1.

## M3 — Light Novel Ingestion

- Purpose: Support the first source format.
- Expected capability: Controlled Light Novel text can enter the story workflow with source evidence.
- Dependency: M2.

## M4 — Story Extraction

- Purpose: Turn source material into useful story understanding.
- Expected capability: Important events, information, entities, and state changes can be identified.
- Dependency: M3.

## M5 — Persistent Story Memory

- Purpose: Retain story understanding across chapters and volumes.
- Expected capability: Historical story context can persist for later use.
- Dependency: M4.

## M6 — Retrieval Baseline

- Purpose: Make relevant story context available to downstream work.
- Expected capability: Past information and evidence can be retrieved for a given need.
- Dependency: M5.

## M7 — Story Brief

- Purpose: Establish an intermediate summary of the story and the requested coverage.
- Expected capability: A structured, evidence-grounded Story Brief can be produced.
- Dependency: M6.

## M8 — Narrative Planning

- Purpose: Translate story understanding into deliberate presentation choices.
- Expected capability: A Narrative Plan can guide the structure, emphasis, tone, and pacing of an output.
- Dependency: M7.

## M9 — Script Generation & Validation

- Purpose: Produce and check the first major product output.
- Expected capability: A grounded YouTube script can be generated and validated against important factual and temporal properties.
- Dependency: M8.

## Script Quality Gate

M9 must establish sufficient script quality before production automation work proceeds.

## M10 — Advanced Narrative Retrieval

- Purpose: Improve retrieval for complex narrative needs.
- Expected capability: More precise and context-aware support for narrative planning and writing.
- Dependency: Script Quality Gate.

## M11 — Temporal / Graph Story Memory

- Purpose: Extend story memory for temporal and structural reasoning.
- Expected capability: Richer reasoning over events, relationships, and changing story state.
- Dependency: M10.

## M12 — Manga Ingestion

- Purpose: Expand beyond the initial Light Novel source.
- Expected capability: Manga can be translated into the shared story workflow.
- Dependency: M11.

## M13 — Visual Production

- Purpose: Extend validated scripts toward visual outputs.
- Expected capability: Storytelling outputs can support visual production workflows.
- Dependency: M12.

## M14 — Voice & Video Automation

- Purpose: Automate later voice and video production activities.
- Expected capability: Validated storytelling outputs can move through voice and video automation.
- Dependency: M13.
