# LONG_RANGE_PROBE_V1_SPEC

## Benchmark Purpose
The LONG_RANGE_PROBE_V1 benchmark evaluates the ability of retrieval and memory architectures to fetch correct evidence from a long narrative (30 chapters). It focuses on long-range dependencies rather than same-chapter local QA. The benchmark explicitly measures **RETRIEVAL EVALUATION** independently from answer generation.

## Corpus Identity
**Source:** Otonari no Tenshi-sama (Web Novel, JP) Chapters 1-30
**Corpus Fingerprint SHA-256:** `7f9bb8106d6d50acd2b3760738c0b8040f36ab547c2d2f7eade1ca0b9a827ff8`
**Passage Contract ID:** OTONARI_LOCAL_PASSAGE_V1
**Segmentation Version:** PARAGRAPH_PACK_V1
**Chunks SHA-256:** `10ef5681ad1b2db0882c150efa24804cd0fca56bb38e0ffb772d22494e1e40fb`

## Probe Categories
1. **CHRONOLOGY**: Ordering events occurring across separated chapters.
2. **RELATIONSHIP_PROGRESSION**: Finding evidence showing how a relationship changes over time.
3. **CALLBACK**: Connecting a later event to earlier evidence.
4. **TEMPORAL_STATE**: Determining a specific state or fact at a specific narrative point.
5. **SPOILER_BOUNDARY**: Avoiding information from chapters beyond a strict cutoff.

## Probe Schema
Each probe must specify:
- `probe_id`: Unique identifier
- `category`: One of the 5 categories
- `question`: The benchmark query
- `cutoff_chapter`: (1..30) The maximum allowed chapter index for retrieved evidence.
- `required_evidence_chunk_ids`: Minimal gold evidence chunks required to correctly answer the probe.
- `supporting_evidence_chunk_ids`: Additional acceptable chunks (optional).
- `expected_answer`: The expected correct answer.
- `expected_facts`: Key facts the response must include.
- `earliest_required_chapter`: Derived minimal chapter index in required evidence.
- `latest_required_chapter`: Derived maximal chapter index in required evidence.
- `chapter_span`: Derived (latest - earliest + 1).
- `requires_multi_chunk`: Boolean flag indicating if multiple chunks are required.
- `requires_multi_chapter`: Boolean flag indicating if the chunks span multiple chapters.
- `forbidden_future_chapters`: Explicit list of chapters that must not be retrieved (spoilers).
- `difficulty_notes`: Author's notes on why this is a difficult long-range query.

## Minimal-Gold-Evidence Rule
Gold evidence should be minimal and defensible. Do not mark huge portions of the corpus as gold. Only explicitly required chunks should be in `required_evidence_chunk_ids`.

## Spoiler Semantics
Retrieval is strictly prohibited from using evidence from chapters strictly greater than `cutoff_chapter`. A probe's answer and gold evidence must be answerable using only information available through the cutoff.

## Metrics
Evaluated at `K = 1, 3, 5, 10`:
- **Hit@K**: Whether at least one required evidence chunk appears in top K.
- **Required Evidence Recall@K**: Required chunks in top K / Total required chunks.
- **Full Evidence Success@K**: Whether ALL required evidence chunks appear in top K.
- **MRR**: Reciprocal rank of the first required evidence chunk.
- **Spoiler Violation@K**: Whether any retrieved chunk in top K belongs to chapter > N.
- **Spoiler Violation Rate@K**: Aggregate rate of spoiler violations across all probes.

## Privacy Rules
Raw chapters, chunk texts, character facts, questions, and answers remain LOCAL_PRIVATE. This public spec must not leak story content.

## Benchmark Freeze Procedure
Once the 15 probes are verified locally:
1. Run `validate_long_range_probe_v1.py`
2. Create `LONG_RANGE_PROBE_V1_FREEZE.yaml` recording counts and the probe file SHA-256.
3. Commit only the spec, freeze metadata, and validator code.

## What this benchmark does NOT measure
This benchmark does NOT measure reasoning ability, general LLM chat capabilities, or summarization of a single scene. It isolates the ability to recall specific, dispersed facts.
