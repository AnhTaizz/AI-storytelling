# Product Vision

Status: ACCEPTED — TASK 000B.

## Product

The Story Intelligence Platform is an AI-powered Story Intelligence and Narrative Production Platform. Its long-term purpose is to help creators transform long-form narrative sources into grounded and engaging storytelling outputs.

The platform is not simply a summarization tool. Its goal is to understand complex narrative sources deeply enough to preserve underlying story truth and enable compelling, intentional narrative presentation.

Potential long-term source formats include:
- Light Novels;
- Manga;
- Web Novels;
- other long-form narrative media.

The first major product outcome is a high-quality grounded YouTube script.

## Core Problem

Long-form stories contain extensive, interconnected details distributed across many chapters or volumes. Creators face significant friction when trying to analyze and adapt these stories accurately.

Key story context easily lost or distorted includes:
- events, chronology, and causality;
- characters, relationships, and changing character states;
- information asymmetries, secrets, foreshadowing, and reveals;
- long-range story context and source evidence.

Creators need deep, accurate story understanding before they can shape material into clear, captivating storytelling. A useful platform must preserve source evidence and narrative continuity across the entire work.

## Conceptual Long-Term Pipeline

The conceptual long-term flow is:

```text
Source Story
→ Story Understanding
→ Persistent Story Memory
→ Retrieval
→ Story Brief
→ Narrative Planning
→ Script Generation
→ Validation
→ Later Production Automation
```

This represents the planned end-to-end architecture across future milestones; it does not imply that all stages are currently implemented.

## Story Understanding vs. Storytelling

The platform maintains a strict separation between two fundamental layers:

1. **Story Understanding** answers: *“What actually happened?”*
   - Establishes factual, temporal, causal, and contextual truth grounded directly in source evidence.
   - Tracks state changes, character knowledge, and canonical story events objectively.

2. **Storytelling** answers: *“How should we tell it effectively?”*
   - Governs selection, ordering, emphasis, pacing, tone, commentary, hooks, callbacks, and audience-facing presentation.
   - Tailors the delivery for a specific format, genre, or channel voice.

**Critical Rule:** Creative storytelling choices may shape how the story is presented, but must never alter or invent factual story truth.

## Multiple Storytelling Outputs

The platform is designed to support diverse narrative intents rather than a single fixed template:
- Recap
- Review
- Dramatic Storytelling
- Character Analysis
- Plot Explanation
- Lore Analysis

It must accommodate different genres, narrative structures, and channel voices. No single storytelling style fits every creator or output.

## Generality and Extensibility

The core platform must remain general and extensible across:
- **Source formats:** Light Novels are the initial MVP source, but the platform must remain source-agnostic (supporting Manga, Web Novels, etc.).
- **Genres:** Not limited to romance, romcom, fantasy, or action.
- **Channels & Voices:** Not built around a single YouTube channel, persona, or editorial style.

## Technology as an Enabler

Technologies such as RAG, GraphRAG, Neo4j, vector databases, and Large Language Models are enabling tools, not the product definition or goal.

The product goal is superior story understanding and grounded storytelling. Specific databases, retrieval frameworks, LLM providers, and infrastructure remain implementation decisions to be evaluated on merit in later milestones rather than frozen in the product vision.
