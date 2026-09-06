# Baseline Plan

These are conceptual baselines designed for comparison. All baseline runs should eventually use the same:
- Golden Story scope
- spoiler boundary
- target video mode
- approximate script-length target
- model where practical
- generation settings where practical
- evaluation process

When a variable differs, record it.

## BASELINE A — DIRECT / LONG CONTEXT

Concept:
Selected Source → LLM → Script

Purpose:
Establish the strongest simple baseline possible before adding retrieval or structured Story Intelligence.

Research question:
> How far can a capable LLM get using direct source context alone?

Expected failure categories (Hypotheses):
- context limits
- omitted details
- poor long-range recall
- chronology drift
- weak callbacks
- overly generic summaries
- poor narrative pacing

## BASELINE B — SIMPLE RETRIEVAL

Concept:
Source → simple chunks → retrieve relevant chunks → LLM → Script

Purpose:
Test whether naive retrieval improves source grounding over direct generation.
No vector database decision should be frozen. This baseline may later use a disposable implementation.

## BASELINE C — MINIMAL STRUCTURED PIPELINE

Concept:
Source → minimal structured understanding → crude Story Brief → crude Narrative Plan → Script

Purpose:
Test whether separating factual selection from storytelling improves quality.
This is NOT the final Canonical Story Model or M2 completion. It is experimental scaffolding.
