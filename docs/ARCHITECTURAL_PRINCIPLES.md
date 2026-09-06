# Architectural Principles

Status: ACCEPTED — TASK 000D.

## Principles

### 1. Separate Story Understanding and Storytelling

Story Understanding determines what actually happened in the story based on evidence. Storytelling determines how that story should be presented effectively for an audience. Creative generation must never become the source of factual story truth.

### 2. Separate Source Adapters and Canonical Story Representation

Source-specific ingestion formats must be converted through dedicated adapters into a shared Canonical Story Representation. Downstream Story Intelligence must operate against the canonical representation rather than coupling to source-specific formats.

```text
Light Novel → Light Novel Adapter → Canonical Story Representation
Manga       → Manga Adapter       → Canonical Story Representation
```

### 3. Treat Persistent Story Memory as First-Class

The platform must support long-range story memory across chapters, volumes, and narrative arcs. Historical story context must persist reliably so that earlier narrative elements remain accessible and accurate during later processing.

### 4. Preserve Provenance

Important AI-derived facts and narrative understanding must remain traceable to source evidence whenever possible (e.g., Story Fact → Source Chapter → Source Passage). Downstream outputs should be justifiable by explicit references back to the original text.

### 5. Combine Structured and Unstructured Memory

Different narrative questions require different representations. The platform will utilize complementary memory forms, including raw source text, structured entity/event records, semantic/vector embeddings, graph relations, and temporal state histories. No single storage mechanism is assumed to satisfy all narrative needs.

### 6. Combine Graph and Vector Retrieval

Vector retrieval excels at semantic similarity and thematic matching, whereas graph retrieval excels at structural, causal, and relational traversal (e.g., event dependencies, relationship changes, secrets, foreshadowing, and reveals). Neither retrieval method is treated as a universal solution; they must function complementarily.

### 7. Model Events and Information as First-Class Concepts

A story model based solely on character profiles and text chunks is fundamentally insufficient. Core narrative modeling must treat Events, Information, Secrets, Reveals, and State Changes as first-class architectural concepts.

### 8. Represent Story State Over Time (Temporal Modeling)

Narrative truth evolves over story time. What a character knows, believes, or feels at Chapter 30 often differs dramatically from Chapter 10. The architecture must model the temporal dimension of narrative states, relationships, knowledge asymmetries, and goals.

### 9. Use Explicit Contracts and Validation for Structured LLM Outputs

LLMs must not be permitted to freely invent schema definitions or ad-hoc data structures. All structured extractions and intermediate artifacts must adhere to explicit contracts, schema validation, and evidence constraints.

### 10. Keep the Domain Model Independent of Storage Technology

The Canonical Story Model must be defined purely in domain terms, completely independent of specific storage technologies (such as Neo4j, PostgreSQL, or vector databases). Storage mechanisms implement the domain model; they must not define or dictate it.

### 11. Separate Narrative Truth and Narrative Presentation

Narrative presentation style may adjust ordering, emphasis, tone, pacing, commentary, hooks, callbacks, and scene compression. However, style choices must never invent events, alter factual chronology, misrepresent character knowledge, introduce unsupported relationships, or rewrite canonical story truth.

### 12. Support Configurable Narrative Behaviors

The architecture must support diverse storytelling configurations, allowing varied combinations of channel voice, video mode, genre profile, scene intent, and audience knowledge state. Storytelling logic must never be hard-coded into a single narrative template or voice.

### 13. Enable Human Control and Review Points

The system is not intended as an unguided black box. Key intermediate milestones—such as the Story Brief, Narrative Plan, and generated Script—must support human inspection, validation, and editorial control without breaking the automated pipeline.

### 14. Prioritize Quality and Groundedness Over Maximum Automation

Reliable story understanding, persistent memory, accurate retrieval, deliberate narrative planning, and verified script quality take precedence over end-to-end hands-free automation. Downstream production automation will proceed only when narrative groundedness and script quality are established.

### 15. Design for Growth and Implement Incrementally

Architectural abstractions should accommodate long-term goals without introducing premature infrastructure complexity. Implementations must remain simple and strictly justified by current milestones, avoiding premature microservices, Kubernetes clusters, distributed streaming platforms, or speculative abstractions.

## Technology Neutrality

References in these principles to technologies such as Neo4j, GraphRAG, vector retrieval, or Large Language Models serve strictly as illustrative architectural examples. 

No specific database, graph engine, vector index, LLM provider, web framework, or deployment infrastructure is frozen by this document. All technology choices will be evaluated and decided under dedicated technical decisions based on empirical requirements.

## Out of Scope

These principles define architectural rules and boundaries. They explicitly do not define:
- concrete database schemas or graph ontologies;
- the detailed Canonical Story Model specification;
- the Narrative Style Engine specification;
- technology stack selections;
- implementation source code.
