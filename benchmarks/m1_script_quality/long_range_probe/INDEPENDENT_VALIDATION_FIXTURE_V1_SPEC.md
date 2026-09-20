# INDEPENDENT_VALIDATION_FIXTURE_V1 Specification & Protocol

## Status
**PREPARED_PENDING_HUMAN_REVIEW**  
*(Drafted in TASK M1-30CH-P. Frozen evaluation protocol defined below. Retrieval execution prohibited until human review gate is passed).*

---

## 1. Purpose & Motivation
The original `LONG_RANGE_PROBE_V1` benchmark consists of 15 development probes across 35 required evidence units. Iterative experimentation on that development set produced the following trajectory:
- **K (`DENSE_E5_LARGE_V1`)**: Full Evidence Success@10 = 4 / 15 (0.2667), Hit@10 = 0.8000, Recall@10 = 0.5778
- **M (`BGE_RERANKER_V2_M3_TOP30_V1`)**: Full Evidence Success@10 = 4 / 15 (0.2667), Hit@10 = 0.9333, Recall@10 = 0.6444
- **O (`KM_CONSENSUS_RANK_SUM_V1`)**: Full Evidence Success@10 = 7 / 15 (0.4667), Hit@10 = 0.8667, Recall@10 = 0.6889

While equal-weight rank consensus (O) broke through the historical 26.7% multi-evidence plateau on the development set, it also registered a minor Hit@10 regression (-0.0667, 14 → 13 hit probes). Because these results stem from repeated diagnostic cycles on the same 15 probes, they represent **development-set tuning**, not verified generalization.

The purpose of `INDEPENDENT_VALIDATION_FIXTURE_V1` is to provide a held-out validation set to answer in a future task:
> **Does the frozen K+M consensus still improve complete multi-evidence retrieval on unseen questions, without an unacceptable Hit@10 regression?**

---

## 2. Corpus Identity & Scope Limitations
- **Source Corpus**: *Otonari no Tenshi-sama* (Web Novel, JP) Chapters 1–30
- **Corpus Fingerprint SHA-256**: `7f9bb8106d6d50acd2b3760738c0b8040f36ab547c2d2f7eade1ca0b9a827ff8`
- **Passage Contract**: `OTONARI_LOCAL_PASSAGE_V1`
- **Segmentation Version**: `PARAGRAPH_PACK_V1` (97 chunks)
- **Chunks JSONL SHA-256**: `10ef5681ad1b2db0882c150efa24804cd0fca56bb38e0ffb772d22494e1e40fb`

### Explicit Scope Boundary
This fixture is explicitly classified as **query-held-out validation on a shared 30-chapter narrative corpus**.  
It is **NOT** an independent cross-story or cross-volume evaluation. Performance improvements on this fixture demonstrate query robustness within the established narrative domain, but do not imply cross-story domain generalization.

---

## 3. Fixture Design & Schema
The validation fixture targets and establishes **25 distinct probes** partitioned equally across the 5 canonical narrative categories (5 probes per category):

1. **CHRONOLOGY (5 probes)**: Ordering multi-event narrative progressions occurring across separated chapters.
2. **RELATIONSHIP_PROGRESSION (5 probes)**: Tracing evolving interpersonal trust, boundary changes, and disclosure over time.
3. **CALLBACK (5 probes)**: Connecting later reveals or actions to specific, dispersed earlier observations.
4. **TEMPORAL_STATE (5 probes)**: Determining precise narrative facts or arrangements held at a specific story cutoff.
5. **SPOILER_BOUNDARY (5 probes)**: Answering inquiries under strict chapter cutoff constraints without leaking post-cutoff events.

### Probe Invariants
- **Multi-Chunk Requirement**: 100% of validation probes (25 / 25) require at least two distinct evidence chunks (`requires_multi_chunk: true`).
- **Multi-Chapter Span**: 88% of validation probes (22 / 25) span multiple chapters (`requires_multi_chapter: true`).
- **Minimal Gold Evidence**: Only the strictly necessary evidence chunks are designated as `required_evidence_chunk_ids`. Optional or redundant background passages are excluded.
- **Strict Spoiler Cutoff**: For probes with `cutoff_chapter < 30`, all required chunks must satisfy `chapter_number <= cutoff_chapter`. Future chapters are strictly forbidden.
- **Dedup / Independence**: Zero question overlap and zero identical required chunk sets relative to the original 15 `LONG_RANGE_PROBE_V1` probes.

---

## 4. Anti-Leakage & Provenance Contract
- **Authoring Provenance**: All 25 draft probes were authored directly from primary source chapters (Chapters 1–30), completely independent of previous model retrieval rankings, pair scores, or probe failure classifications.
- **Blinding Disclosure**: Because aggregate experiment results from prior iterations were present in the research context, the drafting process is disclosed as **model-assisted research drafting**, not fully blinded.
- **Draft Status**: All generated gold labels are strictly designated as **DRAFT / PENDING_REVIEW** until verified by a human annotator against the raw Japanese text.

---

## 5. Human-Review Gate
Prior to declaring this fixture `FROZEN` or running any retrieval evaluations:
1. Each probe must be independently audited using the private review sheet (`human_review.csv`).
2. Reviewers must verify:
   - Factuality and relevance of each required chunk against the source text;
   - Minimality (confirming no unnecessary chunk is marked mandatory);
   - Absence of temporal leakage or post-cutoff spoiler content.
3. Review statuses: `PENDING_REVIEW`, `APPROVED`, `NEEDS_REVISION`, `REJECTED`.
4. Final status remains `PREPARED_PENDING_HUMAN_REVIEW` until formal approval is committed.

---

## 6. Pre-Registered Future Evaluation Protocol
When human review is approved and evaluation commences, execution MUST adhere to the following frozen protocol:

### Frozen Candidate Methods
1. **Method K (`DENSE_E5_LARGE_V1`)**:
   - Model: `intfloat/multilingual-e5-large` @ `3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3`
   - CPU, fp32, parent chunks, `query: ` / `passage: `, normalized cosine ranking.
2. **Method M (`BGE_RERANKER_V2_M3_TOP30_V1`)**:
   - Model: `BAAI/bge-reranker-v2-m3` @ `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`
   - Candidate pool: Exactly K CUTOFF_FILTERED Top-30 (depth = 30).
   - Raw classification logits descending; tie-break: K rank ASC, chunk_id ASC.
3. **Method O (`KM_CONSENSUS_RANK_SUM_V1`)**:
   - Candidate pool: Exactly K/M Top-30.
   - Consensus rule: $\text{rank\_sum}(c) = k\_rank(c) + m\_rank(c) \text{ ASC}$.
   - Tie-break: $\max(k\_rank, m\_rank) \text{ ASC}$, $\min(k\_rank, m\_rank) \text{ ASC}$, $\text{chunk\_id ASC}$.
   - Evaluated ranking: Consensus Top-30 followed by unchanged K tail (> 30).

### Evaluation Rules
- **No Hyperparameter Tuning**: No testing of alternative weights, RRF parameters, depth variations, or post-hoc threshold adjustments on this validation set.
- **Primary Comparison**: Method O versus Method M. (K serves as secondary historical context).
- **Primary Metrics**:
  - Full Evidence Success@10
  - Required Evidence Recall@10
  - Hit@10
  - MRR
- **Pre-Registered Future Decision Rule**:
  - **SUPPORTED**: Consensus Full Evidence Success@10 > M AND Consensus Recall@10 >= M AND Consensus Hit@10 >= M AND full_success_gained > full_success_lost.
  - **PARTIALLY_SUPPORTED**: Not SUPPORTED, but at least one delta (Success, Recall, or Hit) > 0.
  - **NOT_SUPPORTED**: Consensus Success <= M AND Consensus Recall <= M AND Consensus Hit <= M.

---

## 7. Privacy Compliance
All private textual assets (probe questions, expected answers, chapter prose, individual probe IDs, chunk IDs, and review logs) remain strictly confined to `.local/story_integration/otonari_30ch/INDEPENDENT_VALIDATION_FIXTURE_V1/`.  
This specification contains only structural schemas, aggregate counts, and protocol definitions.
