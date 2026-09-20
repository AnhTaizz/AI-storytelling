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
- **Authoring Provenance**: The 25 draft probes were authored targeting narrative arcs across Chapters 1–30.
- **Blinding & Prior Exposure Disclosure**: The authoring agent in TASK M1-30CH-P explicitly read and analyzed all 15 development probes from `LONG_RANGE_PROBE_V1/probes.yaml` prior to drafting. Furthermore, initial draft authoring relied on console chunk slice previews rather than full-text verification. Consequently, the fixture is disclosed as **model-assisted research drafting with prior dev-set exposure**, NOT independently verified or fully blinded.
- **Draft Status**: All generated gold labels remain strictly designated as **PREPARED_PENDING_HUMAN_REVIEW** until verified by a human annotator against the raw Japanese text.

---

## 5. Source-Grounded Gold Audit & Human-Review Gate
In TASK M1-30CH-P-AUDIT, an exhaustive source-grounded audit was executed across all 25 probes and 60 atomic propositions against the raw Japanese corpus (`PARAGRAPH_PACK_V1`, 97 chunks).
Detailed private audit logs are preserved in `.local/story_integration/otonari_30ch/M1_30CH_P_AUDIT/`.

### Audit Findings Summary
- **Audited Probes**: 25 / 25 (100% audited against full source text with exact character offsets).
- **Probes Flagged for Revision / Human Review**: 18 / 25 probes require revision or human judgment before freeze:
  - **4 Chunk Misassignments**: 4 probes had required evidence assigned to chunks that did not contain the factual event (e.g. event occurred in a different chunk of the chapter, or was recalled off-screen in a subsequent chapter).
  - **4 Factual Hallucinations in Expected Answers**: 4 probes asserted target facts that were factually incorrect or unsupported by the 30-chapter source text (e.g. claiming a private evening dinner in Chapter 30 that never occurred in the 30-chapter corpus, misattributing parent-child conversation topics, or misidentifying character clothing).
  - **4 Minimality Violations / Artificial Padding**: 4 probes included redundant evidence chunks that were not strictly necessary to answer the question, artificially inflated to satisfy the multi-chunk drafting quota.
  - **Critical Semantic Duplicate Blocker**: 1 pair of validation probes share the identical required chunk set and query the identical event under different categories. One probe must be replaced before freezing.
- **Concrete Proposed Revisions**: Documented in `.local/story_integration/otonari_30ch/M1_30CH_P_AUDIT/proposed_revisions.yaml`.
- **Human Review Packet**: Formatted for review in `.local/story_integration/otonari_30ch/M1_30CH_P_AUDIT/human_review_packet.md`.

Final fixture status remains `PREPARED_PENDING_HUMAN_REVIEW` until human annotators sign off on resolutions.

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

### Evaluation Rules & Pre-Registered Decision Protocol
- **Anti-Tuning Contract**: Strictly NO tuning of candidate depth ($30$), consensus weights, rank tie-breakers, or post-hoc score thresholds after observing validation set results. Any adjustment voids generalization claims and mandates a new held-out evaluation set.
- **Primary Comparison**: Method O versus Method M on Top-10 metrics. (K serves as secondary historical baseline).
- **Primary Metrics**:
  - Full Evidence Success@10 (Primary binary endpoint)
  - Required Evidence Recall@10
  - Hit@10
  - MRR (Reported alongside as ranking quality metric)

- **Protocol Revision History & Correction**:
  - *Previous Proposal (Unapproved)*: In the initial audit, a Hit@10 drop of at most 1 probe ($\Delta \ge -0.0400$) was proposed as an "acceptable trade-off". This rule is formally recorded as an **unapproved research proposal** and is discarded from pre-registered decision gating. No trade-off shall be termed "acceptable" in the absence of explicit product-level criteria.
  - *Conservative Descriptive Classifications*: Descriptive outcomes for Method O versus Method M are categorized strictly as:
    1. **DESCRIPTIVE_SUPPORT**: Full Evidence Success@10 increases ($\Delta > 0$), Recall@10 does not decrease ($\Delta \ge 0$), and Hit@10 does not decrease ($\Delta \ge 0$).
    2. **MIXED_TRADE_OFF**: At least one of the three primary metrics (Success, Recall, Hit) increases and at least one decreases. (Descriptive only; no value judgment of acceptability is attached).
    3. **NO_OBSERVED_GAIN**: None of the three primary metrics increases over Method M.
    4. **NOT_EVALUABLE**: Critical data integrity, human review sign-off, or evaluation pipeline gates fail.

- **Statistical Uncertainty & Inference Protocol (Separated from Descriptive Verdict)**:
  - **Paired Bootstrap Sampling**: Compute 95% paired bootstrap confidence intervals using $B = 10,000$ resamples with a fixed random seed ($42$) and identical resample probe indices for Method M and Method O. Macro metrics must be computed from per-probe contributions.
  - **Primary Binary Hypothesis Testing**: Compute exact McNemar's test and paired permutation test for the primary binary endpoint (Full Evidence Success@10).
  - **Secondary Exploratory Designations**: All uncertainty analyses for Recall@10, Hit@10, and MRR are explicitly designated as **exploratory**. Non-significant differences shall not be construed or reported as demonstrating "equivalence".
  - **Zero Retrieval Execution**: No retrieval evaluation or model scoring is conducted in this fixture repair task.

- **Evaluator Limitation Blocker**:
  - The current evaluation harness evaluates against a single gold set. In cases where alternative valid evidence exists in the corpus, single-gold scoring introduces artificial false negatives. Resolving multi-gold scoring representation is an open prerequisite before freezing.

---

## 7. Privacy Compliance
All private textual assets (probe questions, expected answers, chapter prose, individual probe IDs, chunk IDs, offset annotations, and review logs) remain strictly confined to:
- `.local/story_integration/otonari_30ch/INDEPENDENT_VALIDATION_FIXTURE_V1/`
- `.local/story_integration/otonari_30ch/M1_30CH_P_AUDIT/`
- `.local/story_integration/otonari_30ch/M1_30CH_P_REPAIR/`

This public specification contains only structural schemas, aggregate counts, audit findings, and protocol definitions.
