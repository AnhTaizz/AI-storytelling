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
The validation fixture accounts for **25 distinct probes** partitioned into:
- **16 Primary Multi-Evidence Probes** partitioned across the 5 canonical narrative categories:
  1. **CHRONOLOGY (5 probes)**: Ordering multi-event narrative progressions occurring across separated chapters.
  2. **RELATIONSHIP_PROGRESSION (4 probes)**: Tracing evolving interpersonal trust, boundary changes, and disclosure over time.
  3. **CALLBACK (2 probes)**: Connecting later reveals or actions to specific, dispersed earlier observations.
  4. **TEMPORAL_STATE (2 probes)**: Determining precise narrative facts or arrangements held at a specific story cutoff.
  5. **SPOILER_BOUNDARY (3 probes)**: Answering inquiries under strict chapter cutoff constraints without leaking post-cutoff events.
- **6 Auxiliary Single-Chunk Probes**: Probes verified as solvable from a single comprehensive passage (e.g. self-contained retrospective recall). Segregated into an auxiliary pool to preserve multi-evidence benchmark integrity.
- **3 Deferred Probes**: Probes reserved due to intra-fixture duplicate evidence (1 probe), development-set overlap (1 probe), or multi-evidence ambiguity / evaluator single-gold limitations (1 probe).

### Probe Invariants
- **Multi-Chunk Requirement**: 100% of primary validation probes (16 / 16) require at least two distinct evidence chunks (`requires_multi_chunk: true`).
- **Multi-Chapter Span**: 100% of primary validation probes (16 / 16) span multiple chapters (`requires_multi_chapter: true`).
- **Minimal Gold Evidence**: Only strictly necessary evidence chunks are designated as `required_evidence_chunk_ids`. Redundant or narrative padding chunks are excluded.
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
Following audit review, TASK M1-30CH-P-REPAIR, TASK M1-30CH-P-CORRECTION, and TASK M1_30CH_P_SEMANTIC_FIX revised source-confirmed errors directly against `chunks.jsonl`.

### Audit & Correction Summary
- **Audited & Corrected Probes**: 25 / 25 accounted for (16 primary, 6 auxiliary, 3 deferred).
- **Key Source Error Corrections**:
  - *Key handoff & naming boundaries*: Separated emergency temporary key handoff (Ch 22) from ongoing key retention (Ch 25), with accurate private vs public naming forms.
  - *Parental discovery grounding*: Grounded maternal discovery in Ch 22 strictly on source facts (discovering Mahiru resting against the edge of the bed hugging a cushion; tableware discovery; avoiding ungrounded shoe claims or false Ch 23 dependencies).
  - *Relationship progression cleanups*: Removed over-interpreted balcony distancing and pre-packaged rhetorical conclusions; focused on concrete behavioral contrasts supported by verbatim text.
  - *Retrospective recall segregation*: Segregated probes where earlier events are fully recalled in a later single chunk into auxiliary pool.
  - *Multi-gold evaluator reservation*: Deferred probes with alternative valid corpus evidence sets until multi-gold evaluator capabilities are implemented.
  - *Semantic necessity repair*: Corrected an inability-to-walk claim, removed unsupported tree/laundering details, narrowed broad questions, replaced a one-sided boundary statement that had been presented as mutual, and rewrote two callback questions so every required chunk supplies an explicitly requested answer part.
- **Actual Primary Structure**: 16 / 16 primary probes are multi-chunk and 13 / 16 are multi-chapter. These figures are derived from the artifact rather than treated as quotas.
- **Verbatim Slice Verification**: 100% of character offset spans `[char_offset_start:char_offset_end)` in `source_gold_audit.jsonl` match raw text slices in `chunks.jsonl` with zero discrepancy.
- **Automated Regression Prevention**: Validator checks span bounds, proposition-chunk mappings, partition coverage, all-`PENDING_REVIEW` status, draft/audit/review-packet synchronization, derived statistics, and artifact hashes.
- **Deliverables Package**: The eight private review artifacts are packaged into `.local/story_integration/otonari_30ch/M1_30CH_P_SEMANTIC_FIX.zip` and the review gate package into `.local/story_integration/otonari_30ch/M1_30CH_P_REVIEW_GATE.zip`.
- **Review Gate Audit (TASK M1-30CH-P-REVIEW-GATE)**:
  - 16 primary probes verified 100% source-grounded with zero slice discrepancies, zero cutoff violations, and verified counterfactual necessity.
  - Comprehensive human review packet prepared in Vietnamese (`review_packet_vi.md`) and decision register (`review_decisions.csv`) with all 25 probes holding `PENDING_REVIEW` status.
  - 3 auxiliary probes (`V_TEMP_01`, `V_SPOIL_03`, `V_SPOIL_05`) flagged with critical factual hallucinations carried over from early drafts (rolled cabbage, pudding, light bulb - all completely absent from WN Ch 1-30).
  - Multi-gold evaluator blocker formally analyzed in `multi_gold_feasibility.md` with mathematical formulation and backwards compatibility proof.
  - 61 relevant tests passed (fixture validator 20, frozen long-range validator 21, ingestion/corpus 20).

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
- `.local/story_integration/otonari_30ch/M1_30CH_P_CORRECTION/`
- `.local/story_integration/otonari_30ch/M1_30CH_P_SEMANTIC_FIX/`
- `.local/story_integration/otonari_30ch/M1_30CH_P_REVIEW_GATE/`

This public specification contains only structural schemas, aggregate counts, audit findings, and protocol definitions.
