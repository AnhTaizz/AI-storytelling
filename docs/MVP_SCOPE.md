# MVP Scope

Status: ACCEPTED — TASK 000C.

## MVP Goal

The initial MVP exists to prove whether Story Intelligence can materially support producing a high-quality, grounded storytelling script. It demonstrates a complete, evidence-grounded workflow from a controlled Light Novel text source to a validated YouTube script:

```text
Light Novel text
→ structured ingestion
→ story understanding
→ persistent story memory
→ relevant context retrieval
→ Story Brief
→ Narrative Plan
→ grounded YouTube Script
→ validation
```

The MVP focuses strictly on story intelligence and script generation; it is not an automatic video production platform.

## In Scope

The MVP demonstrates that the system can:

- **Ingest controlled Light Novel text:** Ingest a controlled Light Novel source while preserving verbatim source evidence and provenance.
- **Story Understanding:** Identify key story entities, events, chronology, character states, and relationships grounded in source text.
- **Persistent Story Memory:** Retain historical story context across chapters and volumes.
- **Context Retrieval:** Retrieve relevant past context and evidence to inform downstream generation.
- **Story Brief:** Produce an intermediate, factual summary covering the story scope requested.
- **Narrative Plan:** Translate story understanding into deliberate presentation choices (structure, tone, pacing, emphasis, and hooks) separate from factual extraction.
- **Grounded Script Generation:** Generate a high-quality YouTube script adhering to the Narrative Plan.
- **Validation:** Validate factual accuracy, temporal consistency, and adherence to source evidence.

The first source format is **Light Novel text**. The first major product output is a **high-quality grounded YouTube script**.

## Out of Scope

The initial MVP explicitly defers:

- **Alternative source formats:** Manga ingestion, OCR, and manga panel understanding.
- **Downstream media production:** Text-to-Speech (TTS), voice generation, automatic video editing, thumbnail generation, and YouTube upload automation.
- **Creator tooling & analytics:** Creator dashboards, audience analytics, channel management, and mobile applications.
- **Premature infrastructure:** Kubernetes, distributed production clusters, and unnecessary microservices.

## Technology Neutrality

Specific databases, graph engines, vector stores, and LLM providers (including Neo4j, GraphRAG, or particular vector databases) are not frozen by this document. They will be evaluated and introduced only when justified by Story Model, persistence, and retrieval requirements in later milestones.

This document defines product scope and boundaries; it is not an implementation or architecture plan.
