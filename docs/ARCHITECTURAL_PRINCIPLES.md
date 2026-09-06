# Architectural Principles

Status: Defined in TASK 000D.

## Principles

### 1. Separate Story Understanding and Storytelling

Story Understanding determines what happened. Storytelling determines how it should be presented. Creative generation must not become the source of factual story truth.

### 2. Separate Source Adapters and Canonical Story Representation

Each source format should be translated through its own adapter into a Canonical Story Representation. Downstream Story Intelligence should not depend heavily on source format.

```text
Light Novel → Light Novel Adapter → Canonical Story Representation
Manga       → Manga Adapter       → Canonical Story Representation
```

### 3. Treat Persistent Story Memory as First-Class

The platform must eventually support long-range memory across chapters and volumes.

### 4. Preserve Provenance

Important AI-derived knowledge should be traceable to source evidence whenever possible.

### 5. Combine Structured and Unstructured Memory

Raw source, structured records, semantic/vector memory, graph memory, and temporal information can complement one another. No single storage mechanism should be assumed to solve every memory need.

### 6. Combine Graph and Vector Retrieval

Semantic similarity and structural reasoning solve different retrieval problems and should be treated as complementary capabilities.

### 7. Model Events and Information

Character-only modeling is insufficient. Events and information are important narrative concepts.

### 8. Represent Story State Over Time

Story state changes over time, including character knowledge, relationships, goals, beliefs, and emotional state.

### 9. Use Explicit Contracts and Validation

LLMs must not freely invent production schemas. Prefer explicit structured contracts and validation.

### 10. Keep the Domain Model Independent of Databases

Technology choices must not define the Canonical Story Model. Neo4j may become important, but the domain model must remain conceptually independent of any database.

### 11. Separate Narrative Truth and Presentation

Style may modify order of presentation, emphasis, tone, pacing, commentary, hooks, and callbacks. Style must not modify factual story truth.

### 12. Design for Growth and Implement Incrementally

The platform should support growth while avoiding premature microservices, Kubernetes, distributed infrastructure, and unnecessary abstractions.

## Out of Scope

These principles do not define a database schema, Story Model, graph ontology, technology stack, LLM configuration, or implementation code.
