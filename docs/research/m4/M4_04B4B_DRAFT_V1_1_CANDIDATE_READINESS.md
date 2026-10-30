# M4-04B4B — Draft V1.1 Candidate Readiness (Offline)

Status: `M4_04B4B_CANDIDATE_PREPARED_READY_FOR_ORCHESTRATOR_REVIEW`.

Date: 2026-10-30. Branch: `claude/hopeful-heisenberg-oq56ou`. Base: `f60ae48`.

Authorization: limited offline preparation granted by the Project Owner. This is not Gate A, B, C or D.

Labels:

- **[VERIFIED]**: checked in this task by reading bytes or running offline tests.
- **[RECORDED]**: claimed by a committed record and not reproducible here, because `.local/` is absent.
- **[RECOMMENDATION]**: proposed by this document.

The P3 candidate is prepared and offline-testable. **It has never been run against a model.** Nothing here measures extraction quality, and the candidate is neither production-qualified nor approved for blind validation.

## 1. Verified initial state

**Git** [VERIFIED]:

- HEAD was `f60ae48`; the working tree was clean.
- `origin/claude/hopeful-heisenberg-oq56ou` points at `6a9754e`, so the two later local commits (`e19101f`, `f60ae48`) have **not** reached GitHub. Pushing was refused earlier with 403.

**Draft V1.1 schema and compiler** [VERIFIED]:

- Both match their B3D records under LF hashing: schema `6b526731…`, compiler `c41730be…`.
- The V1.1 schema `$ref`s six V1 definitions, and the V1.1 compiler calls the V1 compiler as its canonical backend.

**P2 prompt and runtime** [VERIFIED]:

- The P2 prompts are bound to `STORY_EXTRACTION_DRAFT_V1` and contain the literal `DEV2 CASE`. They cannot serve V1.1.
- Runtime `8b84804f…` and durable executor `cc9bd7a8…` match their records.

**Evaluator Snapshot V2** [VERIFIED]:

- All ten bound files match under LF hashing.
- The runner built in this task does not import any evaluator.

**Review statuses:** M4-04B1D2, B3B1, B3B2 and B3C remain `*_PENDING_ORCHESTRATOR_REVIEW`. The matrix is in §7.

**Hash manifests** [VERIFIED]:

- Every path/hash pair in the M4 YAML records matches LF bytes, except the two historical V1 locks, which match CRLF bytes (D1, §6).

**Missing artifacts:**

- `.local/` is absent from this checkout. That covers the DEV2 packages, the B3B2/B3C private protocols and predictions, the 20 locked DEV2 drafts, the durable profile JSON, and all holdout material.
- These were not needed for, and were not used by, this task.

## 2. Deliverables

| Deliverable | Path |
|---|---|
| P3 system preamble | `tools/story_extraction/prompts/story_extraction_draft_p3_system_v1_1.txt` |
| P3 primary user template | `tools/story_extraction/prompts/story_extraction_draft_p3_user_v1_1.txt` |
| P3 repair user template | `tools/story_extraction/prompts/story_extraction_draft_p3_repair_user_v1_1.txt` |
| Reference-free model-facing schema bundle | `tools/story_extraction/draft_v1_1_schema_bundle_v1.py` |
| Canonical-conformance observer and classifier | `tools/story_extraction/draft_v1_1_conformance_diagnostics_v1.py` |
| Candidate identity, prompt materialization, request builders | `tools/story_extraction/m4_draft_v1_1_candidate_p3_v1.py` |
| Offline-testable runner | `tools/story_extraction/run_m4_draft_v1_1_predictions_v1.py` |
| Manifest preparer | `tools/story_extraction/prepare_m4_04b4b_candidate_manifest_v1.py` |
| Candidate manifest | `benchmarks/m4_extraction/M4_04B4B_DRAFT_V1_1_CANDIDATE_MANIFEST.yaml` |
| Hash-normalization record (proposed) | `benchmarks/m4_extraction/M4_HASH_NORMALIZATION_RECORD_V1.yaml` |
| Result record | `benchmarks/m4_extraction/M4_04B4B_CANDIDATE_READINESS_RESULT.yaml` |
| Tests and offline support | `tests/story_extraction/test_m4_04b4b_candidate_prompt_bundle_v1.py`, `test_run_m4_draft_v1_1_predictions_v1.py`, `test_draft_v1_1_conformance_and_quotes_v1.py`, `test_m4_04b4b_line_endings_v1.py`, `p3_v1_1_offline_support.py` |

No existing file was modified apart from appending a section to `docs/PROJECT_STATE.md`.

### 2.1 The P3 prompt

**Carried over unchanged from P2:**

- model `gemini-3.5-flash-lite`, slot `gemini_slot_3`;
- temperature 0, `max_output_tokens` 16384, JSON mode, concurrency 1;
- durable profile V1 and 6/60 pacing;
- at most one structural repair.

**What differs from P2:**

- **Interface.** The prompt targets only `STORY_EXTRACTION_DRAFT_V1_1`. It never mentions the removed `mention.evidence_handle` and contains no DEV2 wording.
- **Ownership.** A "WHO OWNS WHAT" section separates model-owned semantic choices from host-owned deterministic fields.
- **Exact quotes.** The counting rule the compiler actually uses (`_occurrences`, every start position, overlapping matches included) is stated explicitly. P2 did not state it. When counting is uncertain, the rule is to extend evidence quotes until unique, and to *omit* a mention rather than guess its occurrence.
- **Mentions.** `surface_form` must equal the quote or be omitted. Mentions that no assertion uses must not be created.
- **No fabrication.** The prompt explicitly forbids invented characters, relations, events, speech, beliefs and evidence, including inferences from world knowledge and prior context.
- **Uncertainty.** OPEN polarity, SUGGESTED status (with the Japanese hedges らしい, ようだ, そうだ, みたい), holder-relative predicates, placeholders, `textual_ambiguity`, and OPEN bounds.
- **Schema.** The appended schema is a derived, reference-free bundle (`STORY_EXTRACTION_DRAFT_V1_1_MODEL_FACING_BUNDLE_V1`). The authoritative V1.1 schema is not changed and remains the validator.
  - The bundle overrides only the top-level `description`. The authoritative description names the removed field and the V1 history, so this was a real leak into the prompt, caught by a test.
  - A corpus of 26 synthetic drafts plus 12 interface violations gets identical verdicts from the bundle and from the authoritative validator.
- **Repair feedback.** The sanitized aggregate V1.1 blockers, plus classified canonical issue codes (§3.1), with no source text or model values. P2 sent only the first failure's code and path.
- **Template substitution** is single-pass. In P2, sequential `replace` let a marker inside inserted text (source or model output) be substituted, or crash the run. This is a latent P2 defect; P2 is not modified.

The materialized primary system prompt is 32,424 characters. All hashes are in the manifest.

### 2.2 The runner

`run_m4_draft_v1_1_predictions_v1.py` is dataset-agnostic.

**Inputs:**

- A hash-bound input archive, its extracted tree and an `INPUT_MANIFEST.json` (`draft_interface: STORY_EXTRACTION_DRAFT_V1_1`).
- For each case: the base document, M3 manifest, passage inputs, as-of position, profile and prepared input.
- The prepared input must reproduce exactly through `prepare_story_extraction_draft_v1_1`.

**Properties:**

- **Separation.** Provider jobs go through `DurableResearchExecutor`. Compilation goes only through the unchanged V1.1 compiler, wrapped by the observer.
- **No scoring possible.** The runner accepts no gold path and imports no evaluator.
- **Candidate identity.** A canonical JSON lock must equal the current candidate definition. The definition and the input archive are re-verified before and after every provider call.
- **Preservation.** Raw responses, parsed drafts, compiled batches, blockers, per-case results, the result record and the prediction manifest are written atomically.
- **Repair.** One repair per case, eligible only for `JSON_PARSE_FAILURE`, `DRAFT_SCHEMA_FAILURE` or `DRAFT_COMPILER_FAILURE`. Feedback containing gold or quality keys is rejected. An unexpected compiler exception is classified `COMPILER_INTERNAL_EXCEPTION`, is never repaired, and makes the case terminal `DETERMINISTIC_DEFECT_SUSPECTED`.
- **Provider failures are kept apart from quality failures.** They produce `NOT_EVALUATED_TRANSPORT` or `NOT_EVALUATED_TRANSPORT_AT_REPAIR`, never a structural failure.
- **Checkpoint, resume and idempotence.** First-success locks are reused, so a rerun makes zero provider calls and reproduces the same prediction-set hash. A crash during a call is resolved by the executor's fail-closed `UNCAUGHT_EXCEPTION` terminal state, with no duplicate call.
- **Determinism and provenance.** Each valid draft is compiled twice and must give identical canonical JSON. Process identity, passage scope, as-of position and `UNREVIEWED` review state are checked, and any violation stops the run.
- **Accounting and stop rules.**
  - Provider operations and tokens (prompt, candidates, total, thoughts, cached) are recorded per job.
  - A job starts only if `operations + 9` stays within the operation cap.
  - Exceeding the token cap, or a second distinct provider-reported model version, stops the run with `INCONCLUSIVE_INFRASTRUCTURE_*`.
- **Access control.**
  - Paths or archive members naming `gold` or `holdout` are refused.
  - The holdout input, holdout gold and DEV2 gold archive hashes are refused.
  - `run-live` requires an execution authorization record bound to this candidate definition, dataset, archive, case list and budget. No such record exists. Without one, the live transport is never constructed (tested).

## 3. Root-cause investigation

### 3.1 CANONICAL_CONFORMANCE_FAILURE (5 recorded blockers)

**Evidence available:**

- `M4_04B3D_DRAFT_V1_1_REMEDIATION_RESULT.yaml` records only the code and its counts: 5 blockers in 5 attempts, terminal for DEV2_03, DEV2_04 and DEV2_07.
- The underlying drafts are private and absent here.
- The B3D analyzer (`analyze_m4_04b3d_draft_v1_1.py`) keeps blocker paths, but the public YAML lists codes only.

**Mechanism** [VERIFIED by code reading and synthetic reproduction]:

- `draft_compiler_v1.compile_story_extraction_draft_v1` raises this code whenever `validate_batch_guarded` fails, with the path set to the failing check-section names.
- V1.1 pre-compilation checks cover schema, quotes, handles, support handles, derivation, temporal and ambiguity references. They do **not** cover:
  - predicate-registry conformance (predicate, arity, argument kind, vocabulary, entity kind, event kind);
  - support-path completeness;
  - epistemic gates (EXPLICIT without a direct path; internal state without DEPICTION or NARRATION_SUMMARY);
  - stativity of validity;
  - derivation-rule semantics;
  - duplicate proposition content.
- Every such violation therefore surfaces as one undifferentiated `CANONICAL_CONFORMANCE_FAILURE: canonical`.
- Seven classes were reproduced synthetically, each yielding exactly that blocker and a distinct classified code: `UNREGISTERED_PREDICATE`, `FORBIDDEN_VERDICT_PREDICATE`, `TOKEN_NOT_IN_VOCABULARY`, `NO_SUPPORT_PATH`, `INTERNAL_STATE_EXPLICIT_WITHOUT_DEPICTION`, `VALIDITY_ON_NON_STATIVE_PREDICATE`, `UNREGISTERED_EVENT_KIND`.

**Per-failure attribution:**

| Recorded failure | Symptom | Violated invariant | Reproduction evidence | Most likely origin | Confidence | Fixable without frozen-contract change |
|---|---|---|---|---|---|---|
| DEV2_03 primary and repair | `CANONICAL_CONFORMANCE_FAILURE` | unknown: one of the batch-validator sections, most likely `canonical` | none public | model-authored draft (registry, epistemic or support semantics) | **Low** for the class; **medium** that it is model-owned | yes, through prompt and diagnostics, if model-owned |
| DEV2_04 repair | same | same | none public | same | Low / medium | same |
| DEV2_07 primary and repair | same | same | none public | same | Low / medium | same |

The "model-owned" judgment rests on three points:

1. The compiler-owned sections (envelope, scope, ids, evidence spans, provenance) pass on all 26 synthetic graphs and on 6 of 10 migrated DEV2 drafts.
2. B3C-R found no machine or compiler defect.
3. Every invariant left unchecked before compilation is about semantic choices the model makes.

This is inference, not observation. **No failure is classified as resolved.**

**What was built:** `draft_v1_1_conformance_diagnostics_v1.compile_with_diagnostics_v1_1` observes the guarded report the frozen compiler already computes and classifies each issue into a stable code with a local handle.

- Messages and model values are discarded, so nothing source-derived leaks.
- Tests show the compile outcome is identical with and without the observer, and that the original validator is restored afterwards.

**To attribute the five failures:** rerun the B3D migration offline in the private environment through `compile_with_diagnostics_v1_1`. It needs only the locked DEV2 drafts and the authorized DEV2 input (tuning data), with no gold and no API. That run needs its own authorization.

### 3.2 AMBIGUOUS_QUOTE

**Mechanism** [VERIFIED]:

- `_quote_ref` counts every code-point match of the quote in one passage, including overlapping matches (`_occurrences("ははは", "はは") == [0, 1]`).
- With no `occurrence` and more than one match, the result is `AMBIGUOUS_QUOTE`. With `occurrence` beyond the number of matches, the result is `OCCURRENCE_OUT_OF_RANGE`.

**Reliability of the current interface:**

- **Evidence.** It can be made reliable without counting: an evidence quote may be extended to a longer unique span, and the span-containment grounding rule (Evaluation Protocol V0 §6) tolerates wider evidence. The P3 prompt says so.
- **Mentions.** These cannot be extended, because a mention must be exactly the referring expression. Short repeated names and pronouns are common in Japanese prose, so for mentions the model must count. Counting is the step LLMs do worst.
- **Silent mislocation (new finding).** A *wrong but in-range* occurrence compiles successfully and locates a different identical span. This was reproduced on `真白は笑った。真白は窓を開けた。`. The output is structurally valid and semantically mislocated. Structural validity cannot detect it; only grounding evaluation can.

**V1.2 design proposal** [RECOMMENDATION; not implemented; requires a separate decision]:

- Replace or supplement `occurrence` with a W3C-TextQuoteSelector-style locator: `quote` plus optional `prefix` and `suffix` (each an exact string, for example up to 16 characters, taken from directly before and after the quote).
- The compiler keeps only the matches whose surrounding text equals the prefix and suffix:
  - exactly one survivor → resolved;
  - none → `QUOTE_NOT_FOUND`;
  - more than one → `AMBIGUOUS_QUOTE`.
- If `occurrence` is also supplied, it must agree, otherwise `LOCATOR_CONFLICT`.
- The model then copies local text instead of counting, and an ambiguous locator still fails closed.
- This changes the draft interface, so it needs a new schema, compiler and prompt version, and a fresh validation set.

**Decision needed (O6):** freeze V1.1 as is, or design V1.2 before any fresh validation set is spent.

### 3.3 Mention grounding

**Binding behaviour** [VERIFIED]: `bind_exact_mention_evidence_v1_1` is well defined and tested.

- It reuses a model evidence record only when the resolved span **and** the role are identical. Changing only the role produces a new EvidenceRef.
- Otherwise it reuses a prior mention's EvidenceRef, or creates a new one.
- It is invariant to record order and never alters assertion support.

**What it does not guarantee** [VERIFIED by tests]:

- **Ungrounded `surface_form`.** `surface_form` is model-authored free text that the compiler never checks against the quote. A value such as `別人` compiles. The evaluator aligns mentions by span **and** surface form, so drift harms alignment silently.
- **Orphan mentions.** Mentions without any `RefersTo` compile.
- **Semantic correctness.** Whether the located expression actually refers to the asserted entity is semantic and is not checked structurally.

The runner reports `SURFACE_FORM_DIFFERS_FROM_QUOTE` and `MENTION_WITHOUT_REFERSTO` as non-blocking advisories. Making either one blocking would change acceptance semantics and is left to the approver.

## 4. Cross-platform reproducibility assessment

Each row is demonstrated with temporary CRLF copies in `test_m4_04b4b_line_endings_v1.py`.

| Check | LF vs CRLF sensitive? | Note |
|---|---|---|
| Raw file-byte SHA-256 (all historical locks) | **Yes** | History is mixed: two V1 locks are CRLF-form, every other lock is LF-form. |
| Content hash (`content_sha256_lf`) and git blob id | No | Adopted for the P3 manifest. The blob id equals the committed index blob. |
| Prompt materialization (P2 and P3) | No | Both normalize CRLF→LF before hashing. |
| Schema loading and validation | No | JSON parsing ignores line endings. |
| Compiler output | No | An identical batch was produced from CRLF schema copies. |
| Compiler determinism | No | Double compile is identical; record order is invariant. |
| M3 source text, fingerprints and offsets | **Yes, by design** | Source bytes are evidence. A CRLF copy of the same text has a different fingerprint and offsets, and M3 manifests pin LF hashes, so a CRLF checkout fails ingestion closed. |
| Frozen-artifact verification in existing tests | **Yes** | LF checkout: 6 failures (both V1 locks). Simulated full CRLF checkout: ≥5 failures (the LF-locked runtime, executor, registry and snapshot bindings). No single checkout passes all of them. |

**Proposed policy** (`M4_CROSS_PLATFORM_CONTENT_HASH_V1`):

- Locks verify `content_sha256_lf` and record the git blob id. Raw hashes are kept only as observations.
- Raw source text is never normalized.
- Historical records are not rewritten. `M4_HASH_NORMALIZATION_RECORD_V1.yaml` (status `PROPOSED`) maps the two CRLF-form locks to their unchanged LF content.

**Proposed patch** (for separate approval; not applied):

```gitattributes
# .gitattributes
* text=auto eol=lf
*.zip binary
# Source text is evidence: never convert line endings.
data/**/raw/** -text
```

```python
# tests/story_extraction/test_draft_compiler_v1_1.py and m4_04b3b2_dev2_protocol_v1.py:
# accept a historical raw lock only when it is the raw hash or the recorded CRLF form of the
# current LF content listed in M4_HASH_NORMALIZATION_RECORD_V1.yaml.
def matches_lock(path, recorded):
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return recorded in {sha256(data), sha256(data.replace(b"\n", b"\r\n"))}
```

## 5. Offline test results

**New tests: 53, all passing** [VERIFIED]:

- prompt, bundle and candidate: 16;
- runner: 20;
- conformance, repeated quotes and mention grounding: 12;
- line endings: 5.

**Full suites in this container:**

| Suite | Result | Failures, all pre-existing |
|---|---|---|
| story_extraction | 415 run | 3 failures and 3 errors from D1 (the six LF-checkout lock tests above). The manifest-consistency test passes after manifest generation; see the result record. |
| canonical_story | 99/99 | — |
| script_quality | 64/64 | — |
| story_ingestion | 78/79 | 1 test needs `.local/` |
| story_benchmark | 193 run | 2 failures and 14 errors from missing `.local/` fixtures and optional ML dependencies; 6 skipped |

No expected value in an existing test was changed. A test that assumes `.git` exists also fails in the no-`.git` CRLF simulation; that is environmental.

## 6. Pending-review matrix

None of these tasks is marked accepted here. Each needs a formal decision.

| Task | Recorded status | Supporting artifacts | Verifiable here | Unresolved before acceptance |
|---|---|---|---|---|
| M4-04B1D2 durable profile | `QUALIFIED_PENDING_ORCHESTRATOR_REVIEW` | `M4_04B1D2_DURABLE_CONFIRMATION_RESULT.yaml`, `M4_04B1D2_PROTOCOL_LOCK.yaml`, `docs/research/m4/M4_DURABLE_RESEARCH_EXECUTION_V1.md` | public records; executor and runtime hashes; its tests pass | private profile `c6c789f0…` absent; synthetic-only confirmation (12 jobs) after a history of unhealthy provider gates (B1, B1R, B1Q); credential topology `UNKNOWN` |
| M4-04B3B1 DEV2 seal | `SEALED_PENDING_ORCHESTRATOR_REVIEW` | `M4_04B3B1_FRESH_DEV2_SEAL_RESULT.yaml`, `M4_FRESH_DEV2_PROTOCOL_V1.md` | public hashes only | packages absent; gold `AGENT_DRAFT_GOLD`, not human-confirmed; DEV2 is now tuning data, so acceptance would cover it as a process record and tuning set only |
| M4-04B3B2 P2 protocol | `LOCKED_PENDING_ORCHESTRATOR_REVIEW` | `M4_04B3B2_DEV2_BENCHMARK_PROTOCOL_LOCK.yaml`, protocol module and tests | public bindings except D1 | four protocol tests fail on LF checkouts (D1); private protocol absent; P2 is V1-only and superseded by P3 for V1.1; latent single-pass substitution defect |
| M4-04B3C DEV2 predictions | `LOCKED_PENDING_ORCHESTRATOR_REVIEW` | `M4_04B3C_DEV2_PREDICTION_LOCK.yaml`; analyzed by B3C-R and B3D | public record; runner tests pass | 50 private artifact hashes not reproducible here; headline 2/10 hides 0/10 primary validity |

## 7. Updated validation readiness

| Blocker (from the M4-04B4A proposal) | Status now |
|---|---|
| B1 no V1.1 prompt | **Resolved offline.** P3 exists; it has never been run against a model. |
| B2 no V1.1 runner | **Resolved offline.** |
| B3 line-ending hashes | **Partially resolved.** The candidate uses the content-hash policy; historical D1 awaits approval of the §4 patch. |
| B4 schema bundle | **Resolved.** |
| B5 derived scorer (Snapshot V3) | **Open**; outside this task. |
| B6 pending reviews | **Open**; matrix prepared (§6). |
| B7 private-artifact verification | **Open.** |
| B8 conformance and ambiguity | **Partially resolved.** Mechanism and tooling are in place; the five failures are unattributed; O6 (V1.1 vs V1.2) is undecided. |
| B9 model-version binding | **Resolved** in the runner. The expected version is unknown until the first authorized call. |

**Verdict:** `READY_FOR_ORCHESTRATOR_REVIEW` as an offline, reproducible candidate. It is **not** approved for blind validation and **not** production-qualified.

Before any VAL1 construction, these still require decisions:

- B5, B6 and B7;
- O6 (V1.1 vs V1.2);
- the hash-normalization patch.

## 8. Boundaries kept

This task made:

- no provider or API call;
- no DEV1 or DEV2 prediction;
- no VAL1 creation;
- no access to gold or Holdout V1;
- no change to any frozen schema, compiler, evaluator, protocol, prompt or record;
- no start on M4-04C or M5;
- no push.
