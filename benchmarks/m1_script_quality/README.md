# M1 Script Quality Benchmark

## Purpose

Why this benchmark exists.

Primary question:
> Can the system produce a grounded and engaging YouTube storytelling script from long-form narrative source material?

Secondary question:
> Which additional Story Intelligence capabilities produce measurable improvements over simpler baselines?

## Experimental philosophy

Simple baseline first.
Complexity must earn its place.

The project should not assume:
* graph memory is necessary;
* vector RAG is necessary;
* structured extraction is necessary;
* multi-agent architecture is necessary.

Those capabilities must eventually justify themselves by solving observed failure modes.

## Research Questions

### RQ1
How good is direct long-context script generation without retrieval or structured Story Intelligence?

### RQ2
What failure modes appear consistently in the direct baseline?

### RQ3
Does simple retrieval materially improve factual grounding or important-event coverage?

### RQ4
Does separating Story Brief and Narrative Plan improve script quality?

### RQ5
Which failures actually justify more advanced Story Memory, graph retrieval, or temporal modeling?

## Quality Contract Status

Script Quality Contract:
NOT YET FROZEN

The intended process is:
Reference analysis
+ Golden Story
+ baseline outputs
+ human evaluation
+ failure analysis
↓
SCRIPT_QUALITY_SPEC v0
