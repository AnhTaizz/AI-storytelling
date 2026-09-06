# MVP Scope

Status: Defined in TASK 000C.

## MVP Goal

The initial MVP demonstrates a grounded storytelling workflow for a controlled Light Novel text source:

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

## In Scope

The MVP should eventually demonstrate that the system can:

- ingest a controlled Light Novel source;
- preserve source evidence;
- identify important story information;
- retain useful historical context;
- retrieve relevant past information;
- produce a structured Story Brief;
- produce a deliberate Narrative Plan;
- generate a grounded script;
- validate important factual and temporal properties.

The first source format is Light Novel text. The first major output is a grounded YouTube script.

## Out of Scope

The initial MVP explicitly defers:

- Manga ingestion;
- OCR;
- manga panel understanding;
- TTS;
- automatic video editing;
- automatic YouTube upload;
- thumbnail generation;
- creator analytics;
- mobile application;
- production-scale distributed architecture;
- Kubernetes;
- unnecessary microservices.

Neo4j, GraphRAG, and any specific database are not required to be implemented in the earliest MVP tasks. They may be introduced later when justified by Story Model and retrieval requirements.

This document defines product scope; it is not an implementation plan.
