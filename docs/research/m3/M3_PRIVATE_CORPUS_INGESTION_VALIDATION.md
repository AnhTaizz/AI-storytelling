# M3 — Private Corpus Ingestion Validation

Status: VALIDATION RESULT — TASK M3-02. Pending Orchestrator review. **M3 is not frozen.** Not recorded in `DECISIONS.md`.

Machine-readable result: `benchmarks/m3_ingestion/M3_02_PRIVATE_CORPUS_VALIDATION_RESULT.yaml`.

This document is sanitized. It contains counts, hashes and classifications only. The source text, the private manifest and the trace table stay local.

## 1. Validation Purpose

M3-01 delivered `LIGHT_NOVEL_INGESTION/v0` and a baseline adapter, tested on synthetic input and five tracked sample documents. M3-02 asks three questions of the full controlled corpus:

1. Can the contract ingest all 30 documents exactly and deterministically?
2. Is `PARAGRAPH_SEGMENT_V0` reasonable on real long-form formatting?
3. Can every historical `PARAGRAPH_PACK_V1` retrieval chunk be traced mechanically to the M3 provenance layer?

The adapter, the manifest schema and the contract were **not modified**. No model, network or database was used. This is not M4 extraction and not retrieval tuning.

**Result: all three answers are yes, with one limitation that the Orchestrator should confirm (section 6).**

## 2. Corpus Identity Checks

| Check | Expected | Found |
|---|---|---|
| Documents | 30 | 30 |
| Source SHA-256 against the historical manifest | all match | 30 / 30 |
| Historical corpus fingerprint (recomputed) | `7f9bb810…a827ff8` | match |
| Historical chunk file SHA-256 | `10ef5681…e1e40fb` | match |
| Historical chunks | 97 | 97 |

A private manifest was created once: one story id, one stream id, and 30 opaque document ids. The ids are random and persisted; they encode no chapter number, filename or name.

## 3. Full-Ingestion Result

| Property | Result |
|---|---|
| Documents ingested | 30 |
| Segments | 1519 |
| Exact character and byte round-trip | verified for every segment |
| Text normalization | none |
| Non-blank characters outside segments | 0 |
| Segment ids unique | yes |
| Canonical structural conformance (`canonical_story/v0`) | PASS |
| Canonical semantic conformance | PASS |
| M3 corpus fingerprint | `ce0f4933…1c3ce370` |

The M3 fingerprint differs from the historical one, as expected. They are different identity contracts.

**Determinism.** The adapter was run twice in separate processes. The serialized source layer and the report are byte-identical. Document versions, fingerprint, segment ids, locators and discourse positions are the same.

## 4. Segmentation Statistics

| Measure | min | p50 | p90 | p95 | p99 | max | mean |
|---|---|---|---|---|---|---|---|
| Segments per document | 25 | 48 | 67 | 82 | 103 | 103 | 50.6 |
| Characters per segment | 3 | 52 | 111 | 128 | 191 | 299 | 60.1 |
| Bytes per segment | 9 | 156 | 326 | 377 | 553 | 873 | 177.4 |

| Measure | Value |
|---|---|
| Single-line segments | 938 |
| Multi-line segments | 581 |
| Lines per segment | 1: 938 · 2: 371 · 3: 87 · 4: 54 · 5: 36 · 6: 20 · 7: 11 · 8: 1 · 9: 1 |
| Documents with a byte-order mark | 0 |
| Line endings | LF 1187, CRLF 3365, CR 0 |
| Documents by line ending | 5 LF-only, 25 CRLF-only, 0 mixed |
| Documents with a leading blank region | 0 |
| Documents with a trailing blank region | 1 |
| Blank lines between consecutive segments | 1: 1232 · 2: 9 · 3: 240 · 4: 1 · 5: 2 · 7: 4 · 11: 1 |
| Segments over 1200 / 2000 / 4000 / 8000 characters | 0 / 0 / 0 / 0 |

The length buckets are diagnostics. No maximum segment length is introduced.

The count of 1519 segments equals the paragraph count recorded by the historical chunker, although the two use different blank-line rules.

## 5. Suspicious-Segment Audit Methodology

The AI agent read segments privately and classified each anomaly as `VALID_PARAGRAPH`, `SOURCE_FORMATTING_ARTIFACT`, `SEGMENTATION_DEFECT` or `AMBIGUOUS`. This is not an independent human review.

| Inspected set | Segments |
|---|---|
| Longest segments | 12 |
| Stratified random sample (fixed seed; short, medium, long) | 18 |
| Mechanical scan: author-note marker words, blocks mixing dialogue and narration, large blank gaps before a segment | 39 |
| First two and last two segments of every document | 120 |
| Documents with the fewest segments | 3 documents |
| Segments over 4000 characters | none exist |

About 1340 of the 1519 segments were not read individually. An author note in the middle of a document, with no marker word, would not have been found.

**What was observed.**

- **Two formatting styles.** Five documents use LF, one line per paragraph and extra blank lines at scene breaks. Twenty-five use CRLF and group lines into blocks separated by one blank line. Segment granularity is therefore line-level in the first group and block-level in the second.
- **Blocks are the source's own grouping.** A multi-line block is a run of dialogue lines (several turns) or a run of narration lines. Ten blocks mix the two. The longest block has 9 lines and 299 characters. All were judged `VALID_PARAGRAPH`.
- **Document size explains segment count.** The documents with the fewest segments are simply the shortest.
- **Sixteen segments join unrelated material.** In 16 documents the source has no blank line between a heading or an author note and the adjacent story line, so one segment holds both:

| Kind | Segments |
|---|---|
| Heading joined with the first story line | 2 |
| Author note before the first story line | 3 |
| Closing story line followed by an author note | 11 |

These are `SOURCE_FORMATTING_ARTIFACT`: the adapter did exactly what the contract says. `SEGMENTATION_DEFECT`: 0. `AMBIGUOUS`: 0. Elsewhere, 28 headings are separate segments of their own, and so are some author notes.

## 6. Segmentation Fitness Verdict

**`PARAGRAPH_SEGMENT_V0_ACCEPTABLE_WITH_LIMITATION`**

Blank-line boundaries suit this source: segments are short, follow the source's own grouping, and nothing collapses at document scale.

The limitation is the 16 mixed segments (1.05% of segments, in 16 of 30 documents). Why this was judged non-blocking:

- No source text is lost, and every locator is exact.
- Each line inside a mixed segment is addressable by an exact sub-span `SourcePassageRef`.
- In the frozen canonical model the evidence role belongs to an `EvidenceRef`, which may point at a span. A segment has no role. A mixed segment therefore forces no wrong label.
- Deciding that a line is an author note is an evidence-role decision. That is M4's, whichever way segments are cut. Author notes that are already separate segments need the same decision.

Why the Orchestrator should confirm it:

- Read strictly, "source formatting makes unrelated material collapse into one segment" describes these 16 cases. On that reading the verdict would be `PARAGRAPH_SEGMENT_V0_NEEDS_REPAIR`.
- The affected story lines are mostly the closing line of a document, which is often narratively important.
- A mechanical alternative exists: one segment per non-blank line. It would separate all 16 cases. It would also cut every narration paragraph and dialogue exchange in 25 documents into single lines, and it changes the accepted contract. It was not applied or tested here.

Consequence for M4, whichever way this is decided: **evidence roles must be assigned per span, never per segment.**

## 7. Legacy-Chunk Trace Methodology

The exact historical 97 chunks were loaded from the existing artifact (hash verified). They were not regenerated.

For each chunk:

1. **Source match.** The chunk text must equal the source text at the chunk's character range, and its recorded hashes must match.
2. **Segments.** Collect the M3 segments that overlap the range. Separate those wholly inside from those only partly inside.
3. **Classify.**

| Class | Condition |
|---|---|
| `EXACT_SINGLE_SEGMENT` | One segment wholly inside; the chunk starts where it starts and ends at most one line terminator after it |
| `MULTI_SEGMENT_SOURCE_RANGE` | Several segments wholly inside, none partly inside |
| `SUBSEGMENT_OF_SOURCE_SEGMENT` | The chunk lies inside one segment (historical hard split) |
| `OTHER_VALID_COMPOSITION` | Any other composition that still satisfies the coverage rule |
| `UNTRACEABLE` | Anything else |

4. **Coverage rule.** Inside the chunk range, all text outside the mapped segments must consist only of blank characters and line terminators. So the first segment starts at or after the chunk start, the last ends at or before the chunk end, and the range between them matches the chunk except for blank separators.
5. **Passage references.** Build a `SOURCE_PASSAGE_REF_V0` for every mapped segment (or sub-span) and verify it: character range, byte range and text hash.
6. **Corpus-level check.** Every M3 segment must be claimed by exactly one chunk.

Blank separators are source formatting. No segment is invented for them.

## 8. Mapping-Class Distribution

| Class | Chunks |
|---|---|
| `EXACT_SINGLE_SEGMENT` | 2 |
| `MULTI_SEGMENT_SOURCE_RANGE` | 95 |
| `SUBSEGMENT_OF_SOURCE_SEGMENT` | 0 |
| `OTHER_VALID_COMPOSITION` | 0 |
| `UNTRACEABLE` | **0** |

| Check | Result |
|---|---|
| Chunk text equals source range | 97 / 97 |
| Non-blank coverage complete | 97 / 97 |
| Segments crossing a chunk boundary | 0 |
| M3 segments claimed exactly once | 1519 / 1519 |
| M3 segments claimed twice or not at all | 0 |
| Segments per chunk | min 1, median 16, max 36 |

A historical retrieval chunk holds 16 provenance segments on average. This is the practical meaning of `SourceSegment != RetrievalChunk`.

**Oversized paragraphs.** The real corpus has no historical hard-split chunk, because no paragraph exceeds the old 1200-character limit. The sub-segment case was therefore shown on synthetic text: a 3100-character paragraph is one M3 segment and three historical hard-split chunks, and each chunk maps to an exact sub-span reference (character range 3/3, byte range 3/3, text hash 3/3).

## 9. Exact Provenance Guarantees

Established on the full corpus:

- Every segment is an exact substring of its source, by code-point range and by byte range, with a matching hash.
- All non-blank source text lies inside exactly one segment.
- Every historical chunk resolves to an ordered list of whole segments in one document.
- 1519 whole-segment passage references were built and verified. A real multi-byte sub-span reference was verified.
- No evidence role was assigned to any real passage. A mechanical shape check of `materialize_evidence_ref` used synthetic text and an explicitly supplied role; it makes no semantic claim.

## 10. Issues and Limitations

| ID | Finding | Class | Severity |
|---|---|---|---|
| I-01 | 16 segments join a heading or author note with adjacent story text | `KNOWN_LIMITATION` | NON_BLOCKING (to be confirmed) |
| I-02 | Two formatting styles; segment granularity differs between documents | `SOURCE_FORMAT_VARIATION` | NON_BLOCKING |
| I-03 | LF and CRLF documents coexist; both preserved exactly | `NO_ISSUE` | — |
| I-04 | No real hard-split chunk; sub-segment mapping shown synthetically | `LEGACY_TRACEABILITY_ONLY` | NON_BLOCKING |
| I-05 | A historical chunk ends after the last line terminator, an M3 segment before it | `LEGACY_TRACEABILITY_ONLY` | NON_BLOCKING |

Adapter implementation bugs: 0. Contract defects: 0. Blocking issues: 0.

Limits of this validation:

- one story, one source, one language;
- the audit was done by the AI agent, and most segments were not read individually;
- no real paragraph is long enough to exercise the no-split rule;
- no extraction was attempted, so the cost of assigning roles per span is not measured.

## 11. M3 Freeze-Readiness Recommendation

| Criterion | Met |
|---|---|
| 1. All 30 documents ingest | Yes |
| 2. Exact byte and character round-trip | Yes |
| 3. Canonical L1 skeleton conforms to frozen M2 | Yes |
| 4. Deterministic rerun | Yes |
| 5. No non-blank source text lost | Yes |
| 6. No unexpected duplicate evidence span | Yes |
| 7. `UNTRACEABLE = 0` for all 97 chunks | Yes |
| 8. Oversized hard-split chunks map to exact passage references | Yes on synthetic text; no real case exists |
| 9. No blocking segmentation defect | Yes, subject to confirmation of I-01 |
| 10. No M1 or M2 frozen artifact changed | Yes |

Recommendation: **`READY_FOR_M3_INGESTION_CONTRACT_FREEZE_REVIEW`**.

Two clarifications are recommended for the contract at freeze. They were not applied in this task:

1. A segment may contain both story text and paratext when the source does not separate them; roles are assigned per span.
2. Segment granularity follows source formatting and can differ between documents.

If the Orchestrator judges I-01 blocking, the outcome is `M3_INGESTION_CONTRACT_NEEDS_REPAIR`, and line-level segmentation is the candidate repair to evaluate.

M3 is not frozen. M4 has not started.
