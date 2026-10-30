# M4 Draft V1.1 Independent Validation Protocol — Proposal V1

Status: `PROPOSED_PENDING_GATE_A`. Task: M4-04B4A (planning only).

Date: 2026-10-30. Branch `claude/hopeful-heisenberg-oq56ou`. Research base `6a9754e` (M4-04B3D). HEAD `e19101f` adds only a README / PROJECT_STATE summary sync. It is unpushed.

This document is a proposal. It approves nothing, creates no dataset, runs nothing and changes no frozen artifact. Every threshold in it is a recommendation until Gate A accepts it.

Labels used below:

- **[VERIFIED]**: checked in this task against repository bytes or by running offline tests.
- **[RECORDED]**: stated in a committed record. It cannot be re-checked here, because the private `.local/` artifacts are absent from this checkout.
- **[RECOMMENDATION]**: proposed by this document.
- **[OPEN]**: a decision for the approver.

Boundaries kept in this task:

- No benchmark, prediction, provider/API call or DEV2 rerun.
- No gold access and no holdout access.
- No change to prompts, schemas, compilers, evaluators or model settings.
- No dataset created, nothing pushed.

---

## 1. Verified project-state summary

### 1.1 Observations given in the task brief

| Observation | Finding | Source |
|---|---|---|
| P2 reached 2/10 structural validity on DEV2 | **[VERIFIED in records]** Terminal 2/10. All **10/10 primaries failed** (0/10 primary validity); both valid cases are repair outputs. | `benchmarks/m4_extraction/M4_04B3C_DEV2_PREDICTION_LOCK.yaml` (`terminal_counts`, `repair_policy_observation`); `M4_04B3CR_STRUCTURAL_FAILURE_FORENSICS.yaml` (`aggregate.primary.valid: 0`) |
| Offline migration to Draft V1.1 reached 6/10 | **[RECORDED]** 6/10 terminal. Primary-only is also 6/10, so repair added nothing after migration. | `M4_04B3D_DRAFT_V1_1_REMEDIATION_RESULT.yaml` (`migrated_v1_1_result`) |
| The migration is not a blind evaluation | **[VERIFIED in records]** `migrated_result_is_model_quality_score: false`. A further point is recorded in §2.4: the migration is counterfactual. | same |
| DEV1 and DEV2 are tuning data | **[VERIFIED in records]** DEV1: M4-04B3A. DEV2: `TUNING_DATA_AFTER_INTERFACE_REDESIGN`. | `M4_04B3A_EXTRACTION_FAILURE_FORENSICS_RESULT.yaml`; B3D `data_status` |
| Holdout V1 sealed | **[RECORDED]** 12 cases, same story, agent-drafted gold, never opened. Process-based; the private packages are not present here. | `docs/research/m4/M4_FRESH_HOLDOUT_PROTOCOL_V1.md`; `M4_03_FRESH_HOLDOUT_SEAL_RESULT.yaml` |
| No extractor approved or frozen | **[VERIFIED in records]** B2 ended `M4_04B2_DEVELOPMENT_LEADER_NOT_LOCKABLE`. P2 was locked only as the DEV2 protocol (`LOCKED_PENDING_ORCHESTRATOR_REVIEW`). No freeze record exists. | `M4_04B2_DEVELOPMENT_EXTRACTION_BENCHMARK_RESULT.yaml`; `M4_04B3B2_DEV2_BENCHMARK_PROTOCOL_LOCK.yaml` |

### 1.2 Discrepancies (reported, not reconciled)

**D1. Line-ending-dependent hashes.** [VERIFIED]

- On this LF checkout, two files no longer match their recorded hashes:
  - `schemas/story_extraction/story_extraction_draft_v1.schema.json` hashes to `7993db7b…`; the records say `498edf8d…`.
  - `tools/story_extraction/draft_compiler_v1.py` hashes to `281a2dfb…`; the records say `bcd15328…`.
- Converting each file to CRLF reproduces the recorded hash exactly. So the content is unchanged, but these two locks were taken on a CRLF working copy.
- Every other recorded path/hash pair matches LF bytes: 18 pairs in the M4 YAML records, plus both evaluation snapshots, the runtime and the durable executor.
- Effect on tests:
  - On LF, `tests/story_extraction` reports 362 run, 3 failures and 3 errors. All six come from this mismatch (`test_draft_compiler_v1_1.test_v1_history_is_byte_identical` and four tests in `test_m4_04b3b2_dev2_protocol_v1`).
  - A scratch clone with only these two files converted to CRLF passes all 362.
- The claims `bytes_unchanged: true` and "902/902" therefore hold only on the author's platform. This is a reproducibility defect in the locking convention, not evidence of tampering.

**D2. Pending reviews never recorded as accepted.** [VERIFIED]

- These statuses still read `*_PENDING_ORCHESTRATOR_REVIEW`:
  - M4-04B1D2: durable profile qualification
  - M4-04B3B1: DEV2 seal
  - M4-04B3B2: P2 protocol
  - M4-04B3C: prediction lock
- No acceptance record exists in the repository.
- The candidate would reuse the durable profile, which is formally only "qualified pending review".

**D3. Stale state summary.** [VERIFIED]

- The `PROJECT_STATE.md` header described DEV2 as "proposed, not executed". It was corrected in `e19101f`, which is unpushed because the push was refused with 403.

**D4. Suite totals not reproducible here.** [VERIFIED]

- Without `.local/` and some optional ML dependencies, the totals in this container are:
  - canonical_story: 99/99
  - script_quality: 64/64
  - story_ingestion: 78/79 (one test needs `.local/`)
  - story_benchmark: 193 run, with errors from missing private fixtures and dependencies
  - story_extraction: 356/362 (D1 only)
- No M4-relevant failure exists apart from D1.

**D5. Private artifacts unavailable.**

- `.local/` is absent from this checkout. That covers:
  - the DEV2 packages
  - the B3B2/B3C private protocols and predictions
  - the durable profile JSON
  - all holdout material
- Their hashes are taken as [RECORDED] only.

---

## 2. Draft V1.1 readiness assessment

### 2.1 Exact interface change [VERIFIED]

| | Draft V1 | Draft V1.1 |
|---|---|---|
| Schema | `story_extraction_draft_v1.schema.json` | `story_extraction_draft_v1_1.schema.json` (`6b526731…`) |
| `Mention` fields | `handle, passage_handle, quote, occurrence?, role, evidence_handle?, surface_form?` | same without `evidence_handle`; `additionalProperties: false` forbids it |
| Other definitions | own `$defs` | **`$ref` into the V1 schema** (`urn:ai-storytelling:story-extraction:draft:v1`) for Evidence, Entity, Event, TemporalAnchor, Proposition, Assertion |
| Mention → EvidenceRef | model-authored link | deterministic: reuse only on identical resolved span and role, else create (`draft_compiler_v1_1.bind_exact_mention_evidence_v1_1`) |
| Diagnostics | first failure | ordered aggregate of source-text-free blockers (`collect_draft_structural_blockers_v1_1`) |
| Canonical backend | `compile_story_extraction_draft_v1` | same function, imported unchanged |

### 2.2 Who is responsible for what

**LLM (model-owned):**

- Choosing passages and exact quotes, and the 1-based `occurrence` when a quote repeats.
- Choosing the evidence role.
- Local handles for entities, events, anchors, propositions and assertions.
- Reusing existing prior handles.
- Choosing predicates and typed arguments.
- Polarity, epistemic status and holder-relative framing.
- `RefersTo` / `SameAs` resolution, or deliberately leaving identity unresolved.
- Validity bounds, support sets (SUFFICIENT, PARTIAL, CORROBORATING), derivations and textual ambiguity.
- Coverage: deciding what to extract.

**Deterministic code:**

- The batch envelope.
- Passage and source hashes, byte offsets and locators.
- Mention EvidenceRef creation and reuse.
- Canonical ids and reference expansion.
- Process provenance and `UNREVIEWED` review state.
- Rejecting context-only or post-as-of evidence.
- Canonical validation (fail-closed).

The compiler infers no truth, predicate, identity, occurrence or relation.

### 2.3 Failures eliminated

- `MENTION_EVIDENCE_MISMATCH`: 17 stage-level failures in B3C, and the cause of all 8 terminal failures. It cannot be expressed in V1.1 (`MENTION_EVIDENCE_MISMATCH_blocker_count: 0` after migration).
- Broad assertion evidence being reused as a mention locator (`broad_evidence_reuse: 0`).
- Censoring of later blockers by fail-fast reporting, for the independently collectible families.

### 2.4 Failure classes still unresolved

| Class | Evidence | Status |
|---|---|---|
| `AMBIGUOUS_QUOTE` (omitted or wrong `occurrence`) | 7 blockers in 3 of 20 migrated attempts; terminal cause of DEV2_05 | Model-owned. **Not addressed by V1.1.** |
| `CANONICAL_CONFORMANCE_FAILURE` | 5 blockers, terminal cause of DEV2_03, 04 and 07 | **Not root-caused.** B3D records the code only. |
| Every semantic dimension (L1–L5) | Never measured on any model output. B2 semantics were censored by L0 (P1 2/14 source-exact). DEV2 was never scored. | Unknown |
| Counterfactual validity of the 6/10 | The migrated drafts were *generated under the V1 prompt and schema*. A model prompted with V1.1 may behave differently, for better or worse. | Unknown |
| Prompt for V1.1 | **None exists.** The P2 prompts target `STORY_EXTRACTION_DRAFT_V1` and hard-code `DEV2 CASE` (`tools/story_extraction/prompts/story_extraction_draft_p2_*_v1.txt`). | Blocker |

### 2.5 Readiness by dimension

Structural validity says nothing about semantic quality. None of the "unknown" rows below may be inferred from the structural rows.

| Dimension | Current evidence | Readiness |
|---|---|---|
| Structural validity | 6/10 counterfactual migration on tuning data | Hypothesis only |
| Semantic correctness | none | Unknown |
| Evidence grounding (L1) | source-exactness enforced by code; grounding choice never scored | Unknown |
| Entity and mention consistency | none on model output | Unknown |
| Relation and event correctness | none | Unknown |
| Provenance correctness | deterministic; synthetic tests pass (26/26 recorded) | Plausible, needs a pre-gold check |
| Compiler determinism | tested synthetically; no cross-platform determinism test exists (see D1) | Partially verified |

### 2.6 Available candidate configuration

| Component | Identity | State |
|---|---|---|
| Model | `gemini-3.5-flash-lite`, the only model qualified on the durable profile (B1Q found no stable alternative) | Qualified pending review (D2) |
| Credential | `gemini_slot_3`, topology `UNKNOWN` | Recorded |
| Generation | temperature 0, `max_output_tokens` 16384, JSON mode, `application/json`, concurrency 1, seed not supported | Recorded (B3B2) |
| Runtime and executor | `GEMINI_TRANSPORT_RESILIENCE_V1_1` `8b84804f…`; `DURABLE_RESEARCH_EXECUTOR_V1` `cc9bd7a8…`; profile `c6c789f0…` (private) | Runtime and executor [VERIFIED]; profile [RECORDED] |
| Pacing and transport | 6 operations per rolling 60 s; at most 3 windows × 3 attempts per job | Recorded |
| Draft schema | V1.1 `6b526731…` plus V1 `$defs` dependency (`7993db7b…` LF / `498edf8d…` CRLF) | [VERIFIED], D1 |
| Compiler | V1.1 `c41730be…` plus V1 backend (`281a2dfb…` LF / `bcd15328…` CRLF) | [VERIFIED], D1 |
| Predicate registry | `predicate_registry/v0.1` `44f3eafc…` | [VERIFIED] |
| Evaluator | `M4_EVALUATION_PROTOCOL_SNAPSHOT_V2`, identity `8dddbd0b…`, file `eef2db2f…` | [VERIFIED] |
| **Prompt (system, user, repair)** | **none for V1.1** | **Blocker** |
| **Runner and protocol builder** | **none for V1.1.** The B3C runner binds V1 and the DEV2 case ids. | **Blocker** |
| Commit | to be fixed by the candidate freeze task | Not frozen |

### 2.7 Verdict

Draft V1.1 is ready for **protocol approval** (Gate A). It is **not ready for blind execution** (Gate C).

Blockers:

- **B1**: there is no V1.1 prompt.
- **B2**: there is no V1.1 runner or protocol builder.
- **B3**: hashing depends on line endings (D1).
- **B4**: the V1.1 schema needs a bundled, dereferenced form to put in the prompt, with its own hash.
- **B5**: the derived metrics in §5 (entity, relation, event, mention, trap probes, provenance, determinism) do not exist in Snapshot V2.
- **B6**: the review statuses in D2 are unresolved.
- **B7**: the private artifacts must be verified where `.local/` exists.
- **B8**: `CANONICAL_CONFORMANCE_FAILURE` is not root-caused, and `AMBIGUOUS_QUOTE` is still model-owned.
- **B9**: model-version drift is not yet bound. The provider-reported model version must be locked.

### 2.8 What must be frozen before a blind evaluation [RECOMMENDATION]

A **candidate manifest** must be committed and pushed *before dataset construction starts*. It binds:

- The commit SHA.
- The git blob ids **and** LF-normalized SHA-256 of every bound file.
- The bundled V1.1 schema bytes.
- The prompt templates and every materialized prompt hash.
- Model id and generation configuration.
- The expected reported model version, if the provider exposes one.
- Credential slot, runtime, executor and profile.
- Pacing, repair policy and the repair-feedback format (aggregate V1.1 blockers).
- Compiler entrypoint, predicate registry and evaluator snapshot.
- The derived scorer (Snapshot V3, additive) and the determinism checker.
- Token and cost caps, and the stop rules (§6).

---

## 3. Independent validation dataset specification [RECOMMENDATION]

**Identity:** `M4_VALIDATION_DRAFT_V1_1_SET_V1` (VAL1).

**Purpose:** a one-shot, blind decision on whether the frozen V1.1 candidate may be proposed for the holdout run. It is not a production qualification and not a generalization claim.

### 3.1 Size

- **24 cases**: 12 capability strata × 2. Optionally 30, with 6 extra Japanese-phenomena cases [OPEN].
- Rationale:
  - One case is about 4.2 percentage points.
  - Wilson 95% intervals at this size: 22/24 → [0.74, 0.98]; 18/24 → [0.55, 0.88].
  - DEV2 averaged about 12 required assertions per case, so expect roughly 250–300 required assertions. That is enough for assertion-level intervals of about ±0.06–0.08 under case-cluster bootstrap.
  - Annotation runs twice independently, plus adjudication and human review. 24 is the largest set that is realistic to annotate well.
  - Each stratum has n = 2, so per-stratum results are descriptive only.

### 3.2 Capability strata (fixed at Gate A, before any text exists)

| # | Stratum | Representative predicates |
|---|---|---|
| S1 | Single character, event progression | Occurred, Participates, OccursAt |
| S2 | Several characters; multi-participant events | Participates (several roles), PartOf |
| S3 | Aliases, name variants, honorific address | NamedAs, AddressesAs, RefersTo, SameAs |
| S4 | Dialogue attribution without explicit speech tags (alternating 「」 lines, zero subject, role-language cues) | Says, RefersTo |
| S5 | Relationships and emotion; suggested vs explicit | Regard, EmotionToward, epistemic status |
| S6 | Speech, belief and intention with negated or embedded content | Says, Attitude, Intends, Conceals (holder-relative) |
| S7 | Ambiguous reference that must stay unresolved | placeholders, `textual_ambiguity`, no premature SameAs |
| S8 | Cross-sentence and cross-passage dependencies; multi-reference SUFFICIENT sets | support sets, derivations |
| S9 | Causality vs adjacency; affirmed and negated causes | Causes, Enables (NEGATED) |
| S10 | State histories with bounds (possession, location, condition) | Possesses, Owns, LocatedAt, validity |
| S11 | Hallucination traps: tempting unstated facts, CONTEXT_ONLY distractors, as-of cutoff, hypothetical, dream or counterfactual | trap probes (§4.4) |
| S12 | Japanese-specific: evidential らしい/ようだ/そうだ (SUGGESTED), inner monologue （…）, ruby, keigo-marked relations, rhetorical negation ～じゃないか, repeated short quotes (はい, うん) that require `occurrence` | mixed |

Each stratum contains one **standard** case and one **hard** case. Difficulty is assigned *before annotation* by a fixed rubric:

- number of entities;
- number of cross-sentence links;
- number of ambiguity points;
- number of repeated-quote spans.

The overall split targets 8 easy, 8 medium and 8 hard.

**Registry limit [VERIFIED].** `predicate_registry/v0.1` lists `RELATIONSHIP` as a forbidden stored verdict and has no static social-relation predicate (kinship, classmate and similar). Stated content of that kind is recorded as a `REGISTRY_GAP` and left out of gold, following the holdout §9 practice. Such gaps are counted and reported.

### 3.3 Source provenance [OPEN; recommendation given]

- **Excluded sources:**
  - the whole Otonari corpus, including tracked chapters 1–5, which keeps every holdout span out by construction;
  - all DEV1 sources;
  - the DEV2 namespace `ORIGINAL_JA_MINI_NARRATIVES_DEV2_V1`;
  - any text in prompts, tests or fixtures.
- **Family A, 16 cases (recommended):** newly authored light-novel-style Japanese prose, written by an author who has *not* written the prompt, compiler or evaluator. A Japanese-literate human is preferred; otherwise a separate agent session with no repository access. Each case is 5–9 segments, with an optional CONTEXT_ONLY passage and prior canonical context where the stratum requires them.
- **Family B, 8 cases (optional):** excerpts from public-domain modern Japanese prose (for example Aozora Bunko new-kana editions). This adds non-agent-authored natural text.
  - Risks: pretraining exposure to the source text, which mostly matters for S11 world-knowledge leakage, and a register different from light novels.
  - Aozora ruby and annotation markup must be handled by a recorded, hashed pre-ingestion transform, or kept verbatim if M3 accepts it [OPEN].
- Every case is ingested under `LIGHT_NOVEL_INGESTION/v0` (`source_language: ja`) in a new namespace `M4_VAL1_V1`.

### 3.4 Deduplication

Deduplication is mechanical only, under the holdout §3 mechanical-use exception:

- Character 8-gram overlap against DEV2 *input* text, tracked sample chapters 1–5, prompt and test strings, and the other VAL1 cases.
- A case is rejected if Jaccard ≥ 0.20, or if it shares any 20-character exact substring other than registered names or stock phrases.
- Rejection and replacement follow a pre-registered reason list in the style of holdout §7. Difficulty is never a rejection reason.

### 3.5 Contamination prevention

The temporal order is binding:

1. The candidate manifest is locked and pushed.
2. The strata and annotation guideline are hashed.
3. Text is authored.
4. Gold is annotated.
5. The set is sealed.
6. The seal is pushed.
7. Blind execution runs.

The candidate cannot be tuned to VAL1 because it predates VAL1.

---

## 4. Annotation and gold-sealing procedure [RECOMMENDATION]

1. **Guideline lock.** `M4_VAL1_ANNOTATION_GUIDELINE_V1` covers:
   - `STORY_UNDERSTANDING_CORE_V0`;
   - required vs acceptable-optional assertions;
   - SUFFICIENT alternatives;
   - literal variants;
   - registry gaps;
   - trap probes;
   - completeness notes.

   It is hashed and committed before any case text is read.
2. **Independent double annotation.**
   - Annotators A1 and A2 each produce canonical gold from the M3 source alone.
   - Neither sees the other, the candidate prompt or any model output.
   - At least one of them should be a Japanese-literate human. If both are agents, they must run in separate sessions, ideally with different model families from the extractor.
3. **Agreement.**
   - Score A2 against A1 with the frozen evaluator in gold-vs-gold mode.
   - Record assertion-level agreement and identity-class agreement before adjudication.
   - This is the noise ceiling. Any metric threshold above it is unattainable and must be flagged at Gate D.
4. **Adjudication.** An adjudicator merges the two annotations into final gold, logging each disagreement and its resolution.
5. **Human review.**
   - The Project Owner or a delegated Japanese-literate reviewer reviews:
     - every assertion whose error would be CRITICAL or HIGH;
     - every trap probe;
     - a stratified 50% sample of the rest.
   - Reviewed items are marked `CONFIRMED` or `CORRECTED` with a `human_review_record`.
   - If no human review happens, the gold stays `AGENT_DRAFT_GOLD` and Gate D can only produce `PROVISIONAL` outcomes.
6. **Completeness.** Every case must be `COMPLETE_FOR_PROFILE`, or kept as `GOLD_COMPLETENESS_UNRESOLVED`. An unresolved case is never swapped out.
7. **Representational gate.**
   - Path: gold → `canonical_gold_to_draft_v1` → `migrate_draft_v1_to_v1_1` → `compile_story_extraction_draft_v1_1` → alpha-equivalence.
   - A case that cannot be represented stops construction. It is never permission to patch.
8. **Trap probes.**
   - For S11 and S12, a sealed list of *prohibited propositions*: tempting but unsupported facts, each with a pre-assigned severity.
   - Kept in the gold package only.
9. **Seal.**
   - Three artifacts: input ZIP, gold ZIP, blindness manifest.
   - Member names are disjoint, and the input package is scanned for gold fields.
   - A deterministic rebuild must reproduce identical hashes.
   - The **gold ZIP is encrypted** with a key held by the Project Owner and released only after the prediction lock is pushed.
   - The public seal record holds hashes only.

---

## 5. Metrics and acceptance criteria [RECOMMENDATION]

### 5.1 Common rules

- **Evaluator.** The frozen Snapshot V2 evaluator runs unchanged on the compiled `STORY_EXTRACTION_BATCH/v0`.
- **Derived metrics.** These are computed by an additive module that is frozen before Gate C as `M4_EVALUATION_PROTOCOL_SNAPSHOT_V3`. Snapshot V2's behaviour is unchanged.
- **Primary analysis: intent-to-treat.** An L0-failed case contributes all of its required gold as missed and no predictions.
- **Secondary analysis.** The same metrics conditional on L0-valid cases, labelled as such.
- **Transport failures.** A case that never received a provider response is `NOT_EVALUATED_TRANSPORT`. It is excluded and counted against the infrastructure rule in §6.6. A sensitivity analysis also reports it as a failure.
- **Match tiers.**
  - *Content match*: predicate, aligned arguments and polarity (V0 §7).
  - *Strict match*: content plus epistemic status, validity, grounding and role (V0 §13).
  - No partial credit inside an assertion; partial correctness shows up as content-matched but not strict-matched.
- **Aggregation.**
  - Micro over units is primary; macro over cases is secondary.
  - Case-level proportions use a Wilson 95% interval.
  - Unit-level metrics use a case-cluster bootstrap 95% interval (10,000 resamples, seed fixed in the manifest).
  - Strata are descriptive only.
- **Adjudication.** Unmatched predictions are adjudicated (V0 §11). Precision and unsupported metrics are withheld while anything is pending.
- **F1.** F1 is reported as a *secondary diagnostic* only. V0 §12 forbids combined scores as endpoints, so F1 never gates [OPEN].

### 5.2 Metric definitions

| Metric | Unit | Match | Missing or invalid | Failure classes |
|---|---|---|---|---|
| Structural validity (primary and terminal) | case | V1.1 compile plus guarded canonical validation pass | transport → `NOT_EVALUATED_TRANSPORT` | JSON_PARSE, DRAFT_SCHEMA, QUOTE (AMBIGUOUS_QUOTE, QUOTE_NOT_FOUND), HANDLE, ASSERTION_EVIDENCE, DERIVATION_REFERENCE, TEMPORAL_REFERENCE, TEXTUAL_AMBIGUITY_REFERENCE, CANONICAL_COMPILER |
| Evidence grounding precision and recall; role accuracy | matched assertion / required assertion / matched EvidenceRef | V0 §6: containment within one segment, exact in narrow segments, one SUFFICIENT set matches one gold set | L0 fail → recall 0 for that case | WRONG_EVIDENCE_SPAN, INSUFFICIENT_SUPPORT_MARKED_SUFFICIENT, WRONG_EVIDENCE_ROLE |
| Entity P/R | gold identity class used by at least one required assertion (prior-context entities excluded: they are given) | aligned per V0 §5, same kind | unaligned gold → FN; a predicted entity whose assertions are all adjudicated UNSUPPORTED → FP; entities with VALID_ADDITIONAL or out-of-scope assertions leave the denominator | MERGE (two gold classes on one predicted), SPLIT (MISSING_ENTITY_RESOLUTION), WRONG_KIND |
| Mention consistency | gold mention with a required RefersTo | identical span, and the predicted affirmed RefersTo targets the aligned identity class | no span → missed span; wrong target → WRONG_ENTITY_RESOLUTION | also *premature merge* in S7: any RefersTo or SameAs that gold keeps unresolved |
| Event P/R | assertion with `classification` EVENT_OCCURRENCE or EVENT_PROPERTY (Occurred, Participates, OccursAt, Manner, PartOf, Conveys) | content match; granularity through V0 §8 adjudication | family membership by gold predicate for recall and by predicted predicate for precision | WRONG_EVENT_GRANULARITY, an event without an Occurred assertion where gold has one |
| Relation and state P/R | assertion with `classification` RELATION (Causes, Enables, Regard, EmotionToward, AddressesAs, TemporalRelation) or STATE (Possesses, Owns, LocatedAt, PhysicalCondition, Habitually, NamedAs, Attitude, Conceals, Intends) | content match | as above | INVENTED_CAUSALITY, WRONG_POLARITY, wrong validity |
| Dialogue attribution | gold `Says` assertion | aligned speaker, content and polarity | — | wrong speaker, HOLDER_RELATIVE_TRUTH_LEAK |
| Hallucination (unsupported) | predicted assertion | adjudicated UNSUPPORTED, with severity by downstream effect (V0 §11); any trap-probe match → UNSUPPORTED at its pre-assigned severity | — | the V0 hint classes plus TRAP_PROBE_HIT; material = HIGH or CRITICAL |
| Provenance | EvidenceRef and batch envelope | re-extracted bytes equal the quote; source hash matches the manifest; offsets lie within the segment; passage at or before as-of; not CONTEXT_ONLY; process provenance equals the candidate identity; `UNREVIEWED` | — | any violation is a deterministic-code defect |
| Compiler determinism | locked draft | three independent recompiles (fresh processes, different `PYTHONHASHSEED`, LF **and** CRLF checkouts, shuffled input key order) give identical canonical-JSON SHA-256; assertion and proposition counts preserved | — | NONDETERMINISM, SEMANTIC_ADDITION |

Provenance and determinism are checked **at prediction-lock time, before the gold is decrypted**.

- A defect found then stops the run. It is fixed under a new compiler version, and the locked drafts are recompiled before gold opens.
- A defect found after gold opens means NO-GO for VAL1.

### 5.3 Proposed Go / No-Go thresholds

These are not official gates until Gate A. No prior model result exists to calibrate them, because every earlier semantic result was censored by L0. They are deliberately asymmetric: missing facts are tolerable downstream, false facts in story memory are not.

**Hard conditions.** Any violation means NO-GO, or INVALID where noted.

| ID | Condition |
|---|---|
| H1 | Provenance violations = 0 |
| H2 | Determinism violations = 0 |
| H3 | CRITICAL unsupported = 0. Exactly 1 → CONDITIONAL. |
| H4 | Holder-relative truth leaks and premature identity merges that are material = 0 |
| H5 | Protocol deviation or contamination = 0. Otherwise the outcome is `INVALID`. |

**Quality conditions.** All must hold for GO. Each is reported with its interval.

| ID | Metric | Threshold |
|---|---|---|
| Q1 | Terminal structural validity | ≥ 22/24, and primary ≥ 18/24 |
| Q2 | Material unsupported rate (adjudicated) | ≤ 3% of predicted assertions |
| Q3 | Assertion precision (adjudicated) | ≥ 0.85 |
| Q4 | Required assertion content recall (ITT, micro) | ≥ 0.70 |
| Q5 | Grounding precision | ≥ 0.90; grounding recall ≥ 0.60 |
| Q6 | Epistemic accuracy | ≥ 0.85 |
| Q7 | Referent resolution accuracy | ≥ 0.75 |

**Reported without a threshold:**

- entity, relation and event P/R/F1;
- full case success rate (V0 §13);
- per-stratum results;
- inter-annotator agreement;
- registry-gap counts.

**Outcomes:**

| Outcome | Condition |
|---|---|
| `GO_ELIGIBLE_FOR_HOLDOUT_PROPOSAL` | All of H and Q pass |
| `CONDITIONAL` | H passes; at most two Q thresholds missed, each by no more than 0.10 |
| `NO_GO` | Anything else |
| `INCONCLUSIVE_INFRASTRUCTURE` | See §6.6 |
| `INVALID` | H5 fails |

If gold has no human review, each outcome carries the suffix `_PROVISIONAL`.

**Small-sample caveat.** N = 24 cannot separate, say, 0.70 from 0.80 recall with confidence. VAL1 is a screening decision, and the holdout is still needed for any confirmatory claim. When a point estimate passes but its lower 95% bound is more than 0.15 below the threshold, Gate D must say so explicitly.

---

## 6. Execution and reproducibility protocol [RECOMMENDATION]

### 6.1 Manifests

- **Candidate manifest** (§2.8): `benchmarks/m4_extraction/M4_04B4B_DRAFT_V1_1_CANDIDATE_LOCK.yaml`, plus a private canonical JSON.
- **Dataset manifest:**
  - input, gold and blindness hashes;
  - case ids `VAL1_01` to `VAL1_24` in a fixed order;
  - per-case source hash;
  - strata and difficulty labels (public, text-free);
  - committed in `M4_04B4C_VAL1_SEAL_RESULT.yaml`.

### 6.2 Command templates

The runner and scorer are to be written in M4-04B4B. They do not exist yet.

```text
python -m tools.story_extraction.run_m4_val1_draft_v1_1_predictions_v1 --mode preflight \
  --candidate-lock <private candidate JSON> --candidate-sha256 <sha> \
  --input-archive <VAL1 input ZIP> --input-sha256 <sha> \
  --checkpoint-root .local/m4/val1/checkpoints --artifact-root .local/m4/val1/artifacts
python -m tools.story_extraction.run_m4_val1_draft_v1_1_predictions_v1 --mode run  (same arguments)
python -m tools.story_extraction.lock_m4_val1_predictions_v1 ...   # hash, provenance, determinism checks; pre-gold
python -m tools.story_extraction.evaluate_m4_val1_v1 --gold-archive <decrypted> --gold-sha256 <sha> \
  --prediction-lock <sha> --snapshot M4_EVALUATION_PROTOCOL_SNAPSHOT_V3 ...
```

Preflight refuses to start if any of these holds:

- any hash differs;
- a gold path, holdout path or evaluator import is reachable;
- the prompt contains VAL1 text;
- the provider is not configured for the locked slot and model.

### 6.3 Model, retry and repair

**Model and generation:** exactly the candidate manifest. There is no per-case prompt change. Fixed case order; concurrency 1; 6 operations per 60 s.

**Transport (provider) failure:** handled by the durable profile only.

- At most 3 windows × 3 attempts per job, with an identical fingerprint.
- No credential or model switch.
- The first success is immutably locked.

**Semantic retry:** forbidden. That covers invalid output, quality, coverage and gold signals.

**Repair:**

- At most 1 per case.
- Only after a successful primary response that failed JSON, Draft V1.1 schema or compiler checks.
- The feedback is the sanitized aggregate V1.1 blocker list.
- A failed repair is terminal.
- Primary and terminal results are both reported.

**Model drift:** the reported model version is recorded for every job. If two jobs report different versions, the run is `INCONCLUSIVE_INFRASTRUCTURE`.

### 6.4 Checkpoints, preservation and accounting

**Checkpoint and resume** use durable executor semantics:

- Job states: `PENDING`, `IN_FLIGHT`, `DEFERRED_TRANSPORT`, `SUCCEEDED_LOCKED`, `TERMINAL_FAILED`.
- A crash that leaves a job ambiguously `IN_FLIGHT` stops the run for manual review. No automatic duplicate call is made.

**Preservation** is private and hash-listed:

- every raw response;
- every parsed draft;
- compiled batches and blocker lists;
- provider metadata and usage;
- checkpoints and the pacing log.

The public record holds hashes and counts only.

**Cost and tokens:**

- Prompt, completion and total tokens are recorded per job, with run totals.
- A hard cap of 48 semantic jobs and 432 provider attempts.
- A token cap equal to 3× the expected size, where the expected size is measured from the materialized prompt bytes at candidate freeze. Reaching the cap means stop with `INCONCLUSIVE_INFRASTRUCTURE`.
- Cost is computed afterwards from the provider price in effect on the run date.

### 6.5 Report structure

`M4_04B4D_VAL1_PREDICTION_LOCK.yaml` holds the pre-gold results:

- terminal states;
- the transport ledger;
- structural, provenance and determinism results;
- tokens and cost.

`M4_04B4E_VAL1_EVALUATION_RESULT.yaml` holds the post-gold results:

- every §5 metric with its interval;
- the adjudication log hash;
- the H and Q table;
- the outcome.

There is also a research note describing failure classes without source text.

### 6.6 Stop rules

| Situation | Action |
|---|---|
| Pre-run health check: N synthetic calls (same model and slot) fail the durable confirmation criteria | Postpone. VAL1 input is not opened. |
| 3 or more of 24 cases end `NOT_EVALUATED_TRANSPORT` | `INCONCLUSIVE_INFRASTRUCTURE`. Gold stays sealed. Any rerun of the transport-failed jobs, with identical fingerprints, needs a new authorization. VAL1 stays fresh, because nobody inspects quality. |
| Hash mismatch, a protocol violation or contamination is detected | Stop. `INVALID`. |

Provider-reliability failures are never counted as extractor-quality failures, and quality failures are never converted into transport retries.

---

## 7. Leakage and contamination risk analysis

| Risk | Vector | Mitigation | Residual |
|---|---|---|---|
| Gold visible to the runner | The same agent environment holds the gold | Encrypted gold, key held by the Project Owner, runner preflight has no evaluator | Process trust in key custody |
| Candidate tuned to VAL1 | Prompt edits after seeing the cases | Candidate lock pushed before authoring; hash-bound | None if the order holds |
| Dataset tuned to the candidate | Cases written against known weaknesses (occurrence, conformance) | Strata fixed at Gate A; difficulty rubric; the author does not see candidate outputs | S12 deliberately includes repeated quotes, a known risk. This is disclosed. |
| Shared-author bias | One AI family writes the text, gold and evaluator | Independent double annotation, a human reviewer, an external or human text author | High if no human is involved: results become `_PROVISIONAL` |
| Holdout leakage | Reuse of Otonari spans | The whole corpus is excluded; holdout paths are refused at preflight | None |
| DEV2 overlap | Similar miniature narratives | New namespace; n-gram deduplication | Low |
| Pretraining exposure (Family B) | Public-domain text known to the model | Limit to 8 cases; analyze Family B separately; S11 traps | Moderate for Family B |
| Post-hoc evaluator change | Scorer patched after results | Snapshot V3 frozen before Gate C; defects only through versioned correction plus impact analysis; Gate D uses the pre-registered version | Low |
| Adjudication bias | The adjudicator sees gold and output | Fixed rubric; a second reviewer for every HIGH or CRITICAL decision; adjudication log hashed before aggregate metrics are computed | Moderate |
| Repeated looks | Rerunning after gold opens | One shot; after gold opens, VAL1 is tuning data | None |
| Provider retention | Inputs sent to the API may be retained | Accept for one-shot use; record the API data-use terms | VAL1 must not be reused as fresh later |

---

## 8. Approval gates and explicit authorization requests

Approving one gate does not authorize the next.

**Gate A — protocol approval.**

- Approves this document, including the strata, metrics, thresholds and stop rules.
- Authorizes **M4-04B4B (offline candidate preparation and freeze)** only.
- Requests:
  - **A1**: accept or amend the thresholds in §5.3.
  - **A2**: decide the open questions O1–O9.
  - **A3**: record acceptance or rejection of the pending reviews in D2.
  - **A4**: authorize, separately, an optional structural smoke run of the new prompt on DEV1/DEV2 *inputs* (tuning data, no gold). This involves API calls.

**Candidate freeze acceptance.**

- The M4-04B4B candidate lock is reviewed and pushed.
- This is a precondition for Gate B.

**Gate B — dataset construction.**

- Authorizes authoring, double annotation, human review, the representational gate and the sealing of VAL1.
- Requests the named text author, annotators and human reviewer, and agreement to key custody.
- Gate B does not authorize any model run.

**Gate C — blind execution.**

- Authorizes the pre-run health check, opening VAL1 *input* only, the run, the pre-gold lock with provenance and determinism checks, and pushing the lock.
- Requests confirmation that Snapshot V3 is frozen and that all blockers B1–B9 are closed.

**Gate D — result review.**

- Authorizes gold decryption after the prediction lock is verified as pushed, then scoring, adjudication, and the outcome under §5.3.
- A GO here makes the candidate *eligible to be proposed* for the holdout run (M4-04C). It authorizes neither M4-04C nor M5.

**If validation fails:**

- VAL1 becomes tuning data.
- Offline forensics on locked VAL1 artifacts are allowed, in the style of B3C-R.
- Any revised candidate needs a new fresh set (VAL2). The holdout stays sealed regardless.
- Option [OPEN]: author 48 cases at Gate B and seal 24 of them as a separate reserve (VAL2) to shorten the next cycle.

---

## 9. Open questions and blockers

**Blockers** (from §2.7):

- **B1**: there is no V1.1 prompt.
- **B2**: there is no V1.1 runner.
- **B3**: hashing depends on CRLF vs LF. Proposal: a versioned record that adopts git blob ids plus LF-normalized SHA-256, with a `.gitattributes` `eol=lf` policy for locked files. Historical hashes stay as they are.
- **B4**: the V1.1 schema is not bundled.
- **B5**: the derived scorer, trap probes and determinism checker do not exist.
- **B6**: the D2 reviews are pending.
- **B7**: private artifacts must be verified in an environment with `.local/`.
- **B8**: `CANONICAL_CONFORMANCE_FAILURE` is not root-caused, and `AMBIGUOUS_QUOTE` is unaddressed.
- **B9**: model-version binding is missing.

**Open questions:**

- **O1**: Who is the Japanese-literate human reviewer, and how much can they review?
- **O2**: Family A only, or A plus B? How should Aozora markup be handled?
- **O3**: Are the §5.3 thresholds acceptable, and is F1 acceptable as a diagnostic?
- **O4**: Is the A4 smoke run authorized?
- **O5**: Should `gemini-3.5-flash-lite` remain the only candidate, or should a stronger model be qualified first? Qualifying another model would need a new provider qualification.
- **O6**: Should AMBIGUOUS_QUOTE be addressed by an interface change (V1.2, for example deterministic occurrence resolution from a short disambiguating context) *before* consuming VAL1? The decision should follow the B8 forensics.
- **O7**: After a VAL1 GO, is Holdout V1 (same story, 12 cases, agent gold) sufficient as the M4 confirmatory gate?
- **O8**: Which encryption and key-custody mechanism should be used?
- **O9**: 24 or 30 cases, and is a reserve set wanted?

---

## 10. Recommended next task

**M4-04B4B — Draft V1.1 candidate preparation and freeze (offline).** It starts only after Gate A.

1. Record the D2 review decisions.
2. Adopt the hash-normalization record (B3) without editing historical locks.
3. Run offline forensics of the 5 `CANONICAL_CONFORMANCE_FAILURE` and 7 `AMBIGUOUS_QUOTE` blockers on the locked DEV2 drafts. DEV2 is tuning data; gold stays closed. Then decide O6.
4. Author the P3 V1.1 prompt set and the bundled schema, with offline tests.
5. Write the V1.1 runner and protocol builder with fail-closed preflight.
6. Write the Snapshot V3 additive scorer (derived metrics, trap probes, determinism and provenance checks). Test it on synthetic fixtures and DEV1 gold (tuning).
7. Emit and push the candidate lock.

No provider calls are made unless A4 is separately authorized.
