# M4-04B4C — Draft V1.2 Grounded Extraction: Implementation and Grounding Reliability

Status: `M4_04B4C_READY_FOR_ORCHESTRATOR_REVIEW`.

Date: 2026-10-30. Base: `45ef66a`. Authorization: AR1, AR2 and AR3 (conditional, offline). Option B is the implementation hypothesis; Option C is not implemented.

Every result below is offline and synthetic. No model was called. Nothing here measures extraction quality, approves independent validation or qualifies anything for production.

## 1. Starting state [VERIFIED]

- **Git:** branch clean at `45ef66a`, one commit ahead of the remote.
- **Hashes:** both the M4-04B4B manifest and the V1.1, registry, canonical and Snapshot V2 hashes matched before work began.
- **Proposal status:** the Draft V1.2 proposal was treated as a hypothesis, not as a frozen contract.

Contradictions with existing contracts, recorded rather than reconciled:

1. **Mention quote length.** The canonical schema caps `surface_form` at 200 code points. Because V1.2 derives the surface form from the quote, the V1.2 Mention `quote` carries `maxLength: 200`.
2. **Unresolved reasons.** The proposal's reason `REFERENT_UNCERTAIN` describes a linking doubt, not a location doubt. It is kept, as proposed, but counted separately and never treated as evidence that a locator is ambiguous.
3. **G5 in the prompt.** P4 tells the model to ground `RefersTo` on evidence that contains the mention text. That is the proposed G5 convention, which has not been checked against gold (AR4). The compiler reports G5 only as a non-blocking advisory.
4. **Correction to the R1 adversarial specification.** The spec said that 「はい」 repeated nine times yields identical 16-character contexts. It does not: within 36 characters the contexts reach a text boundary and disambiguate. The fixture now uses 25 repetitions.

## 2. Architecture

```text
model draft (quote + optional exact context, no positions)
  -> schema STORY_EXTRACTION_DRAFT_V1_2 (self-contained; shared definitions equal V1)
  -> contextual_anchor_resolver_v1: RESOLVED / NOT_FOUND / AMBIGUOUS / INVALID per locator
  -> any non-RESOLVED locator, or any reference to a declared-unresolved locator: case blocked
  -> host-computed occurrence -> internal V1.1-shaped draft -> unchanged V1.1/V1 backend
  -> canonical STORY_EXTRACTION_BATCH/v0 (Canonical Story Model unchanged)
  -> post-invariants G1/G4: every span and surface form equals the resolved source text
```

**Resolver** (`contextual_anchor_resolver_v1.py`):

- Matches exact code points, enumerating overlapping candidates.
- Contexts are 1–32 code points and must lie inside the passage.
- There is no normalization and no positional tie-break.
- Hints (`NORMALIZATION_VARIANT_PRESENT`, `COMPATIBILITY_VARIANT_PRESENT`) are reported for missing quotes but never resolve anything.
- Positions are code points into the passage. The M3 adapter derives UTF-8 byte offsets from the exact source bytes. A test confirms the raw source bytes at the compiled byte range equal the quote, including after an emoji.

**Compiler** (`draft_compiler_v1_2.py`):

- **All or nothing.** A case compiles completely or not at all; partial extraction is never produced.
- **Declared-unresolved locators** are not emitted. Any reference to one is the blocker `REFERENCE_TO_UNRESOLVED_LOCATOR`.
- **Declaration checks.** Each declaration is checked (`CONSISTENT`, `UNIQUE_WITHOUT_CONTEXT`, `UNIQUE_CONTEXT_AVAILABLE` or `QUOTE_ABSENT`), and unjustified declarations are counted. Marking text unresolved therefore cannot silently inflate validity.
- **Surface form** is always source-derived.
- **Advisories** (non-blocking): `REFERSTO_EVIDENCE_NOT_COLOCATED` (G5) and `MENTION_WITHOUT_REFERSTO`.

**Prompt P4:**

- Written fresh for V1.2, not copied from P3.
- States the top-level shape correctly: nine keys, namely `draft_version` and eight arrays (fixing R1).
- Forbids counting, offsets, surface forms and fabricated references.
- Explains context anchoring, ruby and punctuation fidelity, and the unresolved channel.
- Its schema section contains no obsolete V1 or V1.1 wording (tested).

**Runner** (`run_m4_draft_v1_2_predictions_v1.py`):

- **Live execution is disabled.** `execute` accepts only `OfflineTransport` subclasses. Any other callable, including a duck-typed object with `offline = True`, is refused before any work (fixes R2 for new code). The CLI offers `preflight` only.
- **Budget.** A job starts only if `operations + 9` and `tokens + estimate` fit, where the estimate is prompt code points plus the output cap. Otherwise the run stops before the call (fixes R3).
- **Interruptions.** Every started case writes a case-status artifact, including `INTERRUPTED_BUDGET_*`, `INTERRUPTED_PROVIDER_REPORTED_MODEL_VERSION_CHANGED` and `INTERRUPTED_RUNNER_ERROR`. Cases not started are listed (fixes R4).
- **Recorded per run:** the environment, the declared-unresolved rate and the locator totals.
- **Concurrency (R7).** The reused V1.1 observer is still a module-global swap, but it is locked. The V1.2 compiler and runner are serial by design, and this is documented. Frozen and legacy code was not changed.

**Manifest** (`M4_04B4C_DRAFT_V1_2_CANDIDATE_MANIFEST.yaml`, definition SHA-256 `556da499…`):

- Binds runtime, live-path and tooling files under the content-hash policy, including `gemini_errors_v1.py` and `m4_04b2_dev_protocol_v1.py` (fixes R5).
- An import-closure test proves every repository module loaded by the runtime, live and tooling paths is bound.
- Records Python and library versions (fixes R6).

## 3. Adversarial results (`M4_04B4C_ADVERSARIAL_RESULTS.yaml`)

There are 35 cases: ADV-01 to ADV-33 plus a positive and a negative control. **All 35 meet their pre-stated expectations.**

| Outcome | Count |
|---|---|
| VALID | 18 |
| INVALID (fail-closed) | 15 |
| EXPLICITLY UNRESOLVED | 2 |
| VALID at an unintended span (semantic residue: ADV-03, ADV-25, ADV-29) | 3 |
| False resolution by resolver logic | **0** |

The three residue cases have a unique anchor that is mechanically correct but points where the scenario did not intend: a wrong-occurrence context, a wrong passage, and a wrong dialogue attribution. **They are not fixed.** V1.2 removes counting as a cause; it cannot remove a wrong choice. Each record stores the expected outcome, actual outcome, resolver statuses, compiler status, intent match and an explanation.

## 4. K1–K7

| Criterion | Result | Evidence |
|---|---|---|
| K1 no counting field | **PASS** | No `occurrence`, `surface_form`, offset or URN field in the schema (test) |
| K2 adversarial suite | **PASS** | 35/35 |
| K3 identical context never VALID | **PASS** | ADV-04 is AMBIGUOUS; ADV-05 is EXPLICITLY UNRESOLVED |
| K4 ≥95% of repeated-quote locators unique within 16 characters | **PASS on synthetic text only** | 56/56 within 16 and within 32 (`M4_04B4C_GROUNDING_METRICS.yaml`). Six invented passages; not evidence about real prose. |
| K5 output overhead ≤15% | **PASS (character proxy)** | +10.7% per repeated locator against V1.1 without `surface_form`; −13.9% against V1.1 with it; whole synthetic drafts −3.9%. Tokenizer counts not measured. |
| K6 no new dependency, deterministic | **PASS** | Import closure is stdlib plus jsonschema, referencing and PyYAML. Identical output under record shuffles and CRLF schema copies. All 26 fixtures compile byte-identically to V1.1 and match the gold signature. |
| K7 tuning-data pilot | **NOT EVALUATED** | Needs separate API authorization (AR7) |

No architectural criterion failed, so Option C is not recommended at this point.

## 5. Other measurements

| Measure | Result |
|---|---|
| Exact-anchor resolution correctness | All VALID intent-known cases resolve at the intended span, except the three declared residue cases |
| Ambiguity detection | Every repeated-without-context and identical-context case is blocked |
| Unresolved rate | Reported per run; the runner test shows a non-zero rate surfaced separately |
| Representability coverage | 26/26 synthetic fixtures fully representable. Periodic text is a representability gap (L1). |
| Canonical conformance and provenance | Every compiled case passes `validate_batch_guarded` with exact-source checks; post-invariants hold |
| Regression | story_extraction 458/464 (6 pre-existing D1); canonical_story 99/99; script_quality 64/64; story_ingestion 78/79 (`.local/`); story_benchmark unchanged environment failures |
| Cross-platform | New tests and the manifest check pass on LF and on a simulated full-CRLF checkout. Source bytes stay evidence and are never normalized. |

## 6. V1.1 risks eliminated and remaining

**Eliminated (mechanical):**

- SC1: counting error (no counting field exists).
- SC2: overlap-convention mismatch (the host counts).
- SC5: fabricated surface form (source-derived).
- R1, R2, R3, R4, R5 and R6 for the V1.2 path.

**Remaining:**

- **Semantic residue.** SC3 (wrong passage), SC4 and ADV-29 (wrong dialogue attribution), a wrong-occurrence context (ADV-03), SC6 (ungrounded literals, ADV-33), SC7 (mention mislink) and SC8 (unsupported relation or event). Only gold evaluation can detect these.
- **L1.** Periodic or identical text cannot be anchored, even at a passage edge, because a context cannot express "start or end of passage". Such locators are blocked or declared, never guessed. A boundary-marker extension would be a new interface version.
- **R7.** Mitigated by serialization, not eliminated.
- **G5 and the surface-form convention.** Unverified against gold (AR4).
- **The historical D1 hash failures.** Awaiting the hash-migration task (AR5).
- **K7.** Not evaluated.

## 7. Boundaries

This task made no API call, no prediction and no VAL1. It did not access gold or holdout, did not change any frozen artifact, the Canonical Story Model or Snapshot V2, did not implement Option C, did not start M4-04C or M5, and did not push.
