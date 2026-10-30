# M4 Draft V1.2 Grounding — Architecture Decision Proposal

Status: `PROPOSED_PENDING_PROJECT_OWNER_APPROVAL`. Not accepted. Nothing here is implemented.

Task: M4-04B4B-R1. Evidence: `tests/story_extraction/test_m4_04b4b_r1_silent_grounding_v1.py` (synthetic text only). Labels as in the R1 review.

## 1. Question

Can the Draft V1.1 boundary between model and compiler support trustworthy source grounding? Or must the boundary move before fresh validation data is spent?

**Answer [RECOMMENDATION]:** move it. V1.1 lets a mechanical model error (miscounting a repeated quote) become a structurally valid, provenance-consistent canonical record that points at the wrong text. Only gold-based evaluation sees it.

## 2. Silent-corruption threat model

### 2.1 Proven mechanisms [VERIFIED, synthetic]

| ID | Mechanism | Conditions under which it passes every structural check | Detected by |
|---|---|---|---|
| SC1 | Wrong in-range `occurrence` on a mention or evidence | The quote occurs at least twice in the cited passage and `1 ≤ occurrence ≤ count`. The compiler resolves it, `validate_batch_guarded` re-derives the span from source bytes and finds it exact, and offsets, hashes and fingerprint are all internally consistent. | Gold evaluation only (`MISSING_ENTITY_RESOLUTION`, `UNSUPPORTED_ASSERTION`). The co-location check (SC1 note) catches it only when mention and evidence disagree. |
| SC2 | Counting-convention mismatch | A self-overlapping quote (はは in あははは, and similarly ーー or ……). The compiler counts overlapping matches (2); `str.count` and human intuition count 1. A model that counts "naturally" picks a different span or triggers out-of-range. | Not detected when the result is in range. |
| SC3 | Wrong passage | The same quote also exists in another evidence-eligible passage, and the model names that passage. | Gold evaluation only. |
| SC4 | Another speaker's identical line cited as evidence | Repeated dialogue (「はい」). Evidence for a claim about 遥 resolves to 真白's identical line. | Gold evaluation only. |
| SC5 | Fabricated `surface_form` | Any value of 1–200 characters is accepted, and the compiler never compares it with the quote. | Runner advisory (non-blocking); gold evaluation (mention alignment uses span **and** surface form). |
| SC6 | Ungrounded literal value | NamedAs or AddressesAs names, Manner and similar literals are free text and are not checked against any evidence quote. | Gold evaluation only. |

Notes:

- **SC1 and co-location.** Co-location means the `RefersTo` support span must contain the mention span. If the model is consistently wrong, using the same wrong occurrence for both the mention and its evidence, the check passes and the error is invisible.
- **Mislinking.** SC7 (a mention linked to the wrong entity) and SC8 (real but irrelevant evidence attached to an unsupported relation or event) are *semantic*. No locator design can remove them; only gold evaluation and adjudication can measure them.

**Fail-closed cases (safe) [VERIFIED]:**

- NFC versus NFD mismatch → `QUOTE_NOT_FOUND`.
- Ruby markup not copied (`｜真白《ましろ》`) → `QUOTE_NOT_FOUND`.

**Provenance is not grounding.** Under SC1, SC3 and SC4 every provenance invariant holds: exact span, source hash, offsets inside the segment, as-of boundary, `UNREVIEWED` state. Provenance integrity proves that *some* source text was cited exactly. It does not prove that the *intended* text was cited.

### 2.2 Which of the claimed records are affected

| Record | Locator? | Affected by |
|---|---|---|
| Mention position | yes | SC1, SC2, SC3, SC5 |
| Evidence and assertion support | yes | SC1, SC2, SC3, SC4 |
| Aliases (NamedAs, AddressesAs, SameAs) | through mentions, evidence and literals | SC1, SC3, SC4, SC6 |
| Events and relations | through evidence only | SC1, SC3, SC4 (wrong support), SC8 |

### 2.3 Can deterministic post-validation fix it without a contract change?

Partly. Options under the V1.1 contract:

| Check | Catches | Misses | Cost |
|---|---|---|---|
| A1 unique-only: refuse any locator whose quote repeats in its passage | SC1, SC2 entirely | SC3–SC6 | Repeated names and dialogue become unlocatable, so mention recall drops in exactly the cases that matter for identity. In effect this is an acceptance-semantics change. |
| A2 co-location: `RefersTo` SUFFICIENT evidence must contain the mention span | Inconsistent SC1 | Consistent SC1, SC3, SC4 | Must first be confirmed as a valid canonical convention (§6, G5). |
| A3 `surface_form` equals the quote | SC5 | — | Must first confirm that gold never uses a normalized surface form. |
| A4 name literal appears in cited evidence | some SC6 | translated or romanized literals | Evaluation Protocol V0 §9 records literals written in another language, so not general. |

Conclusion: A1 to A3 reduce risk. None of them removes the root cause, which is that the model is asked to count.

## 3. Options

- **A. Keep V1.1** with A1 to A3.
- **B. V1.2 contextual anchors.** The model gives the exact quote plus optional exact `context_before` and `context_after`. Code resolves positions. There is no `occurrence` field.
- **C. V1.2 deterministic candidate anchors.** The host pre-splits each passage into identified units and the model cites a unit id plus a quote.
  - **C-tok (tokens or morphemes):** needs a Japanese morphological analyzer.
  - **C-sent (sentences):** splitting on 。！？ and closing brackets; no new dependency.

**Comparison** (H = favourable, M = mixed, L = unfavourable for trustworthy grounding):

| Criterion | A | B | C-sent | C-tok |
|---|---|---|---|---|
| Structural reliability | H (strict but lossy) | M: context-copy errors fail closed | M: wrong-unit quotes fail closed | M |
| Grounding correctness | L: counting remains, or recall is lost | H: position set by content the model can see | M: position set by a label | M |
| Silent-corruption risk | L to M | **lowest mechanical risk**: needs a wrong context copied consistently | M: an off-by-one unit id is silent when the quote also exists in that unit | M |
| LLM workload | high: counting | low: copy neighbouring text | low: copy a label | low |
| Token overhead | none | output only, and only for repeated quotes (estimated < 10%; criterion K5) | input on every passage (unit markup) plus ids in output | input, large |
| Japanese compatibility | M | **H**: raw characters, no segmentation | M: dialogue and nested 「」 make splitting heuristic (only resolution scope is affected, not truth) | L: analyzer errors, ruby, names |
| Compiler complexity | low | low to medium: filter matches by context | medium: deterministic splitter plus ids | high |
| Migration complexity | low | medium: new schema, compiler, prompt and oracle projection; same canonical output | medium-high: input format changes too | high |
| Testability | H | **H**: pure string functions | H | M |
| Model independence | M | **H**: no model-specific indexing skill | M: label-tracking skill | M |

**Identical surroundings [VERIFIED].** Contextual anchors do **not** always identify a span. In `「はい」` repeated nine times, the middle occurrences have identical context at every bounded length. Under Option B this must yield `LOCATOR_AMBIGUOUS` or a model-declared unresolved locator, **never** a first-match default. Option C-sent hits the same wall inside one unit, for example `「はい」「はい」` within one sentence.

## 4. Recommendation and falsifiable criteria

**[RECOMMENDATION] Option B.** Contextual anchors with no `occurrence` field, a compiler-derived `surface_form`, and an explicit model-declared unresolved channel.

**Fallback:** Option C-sent, if K4 or K7 below fail.

**Interim if V1.2 is rejected:** Option A with A1 to A3, accepting the recall loss, and with no fresh validation until the loss is measured.

The criteria are measurable. Option B is rejected if any fails:

| ID | Criterion | How measured |
|---|---|---|
| K1 | The model cannot express a position by count | The V1.2 schema has no `occurrence` (static check) |
| K2 | 100% expected outcomes on the adversarial suite | `M4_DRAFT_V1_2_ADVERSARIAL_TEST_SPEC.md` |
| K3 | Identical-context cases are never VALID | adversarial cases ADV-04 and ADV-05 |
| K4 | At least 95% of repeated-quote locators resolve uniquely with context of 16 characters or less on synthetic Japanese narrative fixtures; the remainder are explicitly ambiguous | offline resolver statistics |
| K5 | Output-token overhead of 15% or less against V1.1 drafts of the same content | oracle-projected drafts, character-proxy count |
| K6 | No new third-party dependency; compiler total and deterministic | review plus double-compile tests |
| K7 | Tuning-data pilot (needs separate API authorization): `LOCATOR_*` blockers plus declared-unresolved locators at 10% or less of locators; terminal structural validity no worse than a V1.1 P3 pilot on the same tuning inputs minus 1 case | pilot on DEV1/DEV2 inputs; no gold |

## 5. Proposed V1.2 contract (specification only)

### 5.1 Locator (used by Evidence and Mention)

```json
{"passage_handle": "P1", "quote": "<exact>", "context_before": "<exact, optional>", "context_after": "<exact, optional>"}
```

- `context_before` and `context_after` are each 1–32 characters when present, and must lie inside the same passage.
- `occurrence` does not exist.
- The model never outputs offsets, counts, hashes or ids.

### 5.2 Deterministic resolution

1. The passage exists and is `EVIDENCE_ELIGIBLE`. Otherwise use the existing codes.
2. Candidates are every start position of `quote` in the passage text, matched by exact code points, including overlapping matches, with no Unicode, width or whitespace normalization.
3. Keep only candidates whose immediately preceding and following text equal the supplied contexts exactly. A context that would cross the passage boundary does not match.
4. Outcome:
   - exactly one survivor → resolved;
   - zero survivors: `QUOTE_NOT_FOUND` if the quote has no candidates, otherwise `LOCATOR_CONTEXT_MISMATCH`;
   - more than one survivor → `LOCATOR_AMBIGUOUS`.
5. There is no first-match, nearest-match, fuzzy or order-based tie-break.
6. Hint only, never a resolution: when NFC(quote) occurs in NFC(text) but the exact quote does not, report `NORMALIZATION_VARIANT_PRESENT`.

### 5.3 Explicit model uncertainty

- New top-level array `unresolved_locators`, with items `{handle, passage_handle, quote, reason}`. `reason` is one of `REPEATED_IDENTICAL_CONTEXT`, `REFERENT_UNCERTAIN` or `OTHER_DECLARED`.
- A record whose locator is declared unresolved is not emitted. Any record that references it is a `HANDLE` blocker, so dependants must be omitted as well.
- The compiler reports declared-unresolved counts; it never prunes silently.

### 5.4 Separation of concerns

| Concern | V1.2 rule |
|---|---|
| Mention position grounding | §5.1 and §5.2 only. `surface_form` is no longer authored by the model; the compiler sets it to the exact resolved span text (G4). |
| Mention-to-entity linking | Unchanged semantics: a `RefersTo` proposition and assertion. Proposed G5 (co-location) applies. |
| Evidence-to-assertion support | Unchanged: SUFFICIENT, PARTIAL and CORROBORATING sets, plus registered derivations. Locators resolved by §5.2. |
| Semantic correctness | Not structural. Measured only against gold with adjudication (Snapshot V2 and the proposed V3). |

## 6. Proposed grounding invariants

These are proposed, not accepted.

- **G1.** Every canonical span comes from exactly one deterministic resolution. The model supplies no position.
- **G2.** Resolution is total and deterministic. Every input yields one span or one coded blocker.
- **G3.** Ambiguity is never resolved by a default; multiple survivors mean `LOCATOR_AMBIGUOUS`.
- **G4.** The mention `surface_form` equals the source text of its resolved span.
- **G5** (needs convention check). A `RefersTo` assertion's SUFFICIENT set contains at least one evidence span that contains its mention span. This must be confirmed against how gold represents `RefersTo` support; DEV1 gold is tuning data, and reading it needs permission. Until then, G5 is an advisory check.
- **G6.** No normalization of source or quote during resolution; source bytes stay the provenance.
- **G7.** Locator resolution never adds or removes semantic content (no inference, no pruning).
- **G8.** Structural validity is reported separately from grounding correctness. Every report states which one it measures.

## 7. Impact and migration

| Component | Effect of choosing V1.2 |
|---|---|
| Prompt P3 | Stays as the historical V1.1 candidate, never run. New P4 for V1.2, which also corrects R1. |
| V1.1 runner | Reused through a versioned runner that takes the draft version and compiler as bound parameters. Accounting, durable execution and access control are unchanged. |
| Deterministic compiler | New additive `draft_compiler_v1_2.py`. It resolves locators into an internal V1 draft, then calls the unchanged V1 backend, following the V1.1 pattern. V1 and V1.1 are untouched. |
| Canonical Story Model | **Unchanged.** The output is still exact `canonical_story/v0` spans. |
| Evaluator Snapshot V2 | **Unchanged.** It scores canonical batches, not drafts. |
| Proposed Snapshot V3 | Adds locator metrics: `LOCATOR_*` blocker rate, declared-unresolved rate, G4 and G5 violations. Grounding stays under V2 rules. |
| Independent validation protocol | VAL1 must be built for V1.2. Repeated-quote cases (stratum S12) now have an expected `EXPLICITLY_UNRESOLVED` outcome where contexts are identical. The structural metric splits into resolved, blocked and declared-unresolved. |
| Development benchmarks | B2, B3C and B3D stay historical. DEV1 and DEV2 remain tuning data and may serve a V1.2 pilot (K7) only with authorization. No result is rewritten. |
| Oracle projection | New `canonical_gold_to_draft_v1_2` derives the shortest unique context deterministically. A gold span with no unique bounded context is a **representability gap**: V1.2 trades that expressiveness for safety, and the gap must be counted. |
| Tests | M4-04B4B and R1 tests remain as V1.1 evidence. The R1 SC1 tests become V1.2 regression tests with the opposite expected outcome (unrepresentable or ambiguous, not VALID). |

## 8. Risks of the recommendation

- **Context copying.** Exact-copy errors fail closed (safe), but they raise the blocker rate (K7 measures this).
- **Gaming the unresolved channel.** A model may over-use it to avoid failure. Mitigation: report the declared-unresolved rate and recall together, with a threshold set before any run.
- **Surface-form convention.** G4 assumes gold mentions use exact span text. If gold uses normalized surface forms, the evaluator's mention alignment would need a versioned rule. This must be checked before V1.2 is frozen.
- **No elimination of semantic errors.** SC7 and SC8 remain. V1.2 removes the *mechanical* silent-corruption path only.

## 9. Approval requests

| ID | Decision requested |
|---|---|
| AR1 | M4-04B4B: CONDITIONAL ACCEPT as offline-verified infrastructure, with conditions R1, R2, R5 and R6. P3 / V1.1 not accepted as the validation candidate. |
| AR2 | Architecture direction: Option B (V1.2 contextual anchors), with Option C-sent as fallback under K4 or K7. Remains `PROPOSED` until approved. |
| AR3 | Authorize M4-04B4C (offline): V1.2 schema, compiler, oracle projection, P4 prompt, versioned runner and manifest, plus the adversarial suite. No API calls. |
| AR4 | Authorize a read-only offline check of DEV1 gold conventions (tuning data) for G4 (surface form), G5 (`RefersTo` evidence co-location) and literal wording. No DEV2 gold, no holdout. |
| AR5 | Authorize the hash-migration task (R1 review §6): `.gitattributes`, an entry-specific verification helper, test updates through a versioned change. |
| AR6 | Formal decisions on M4-04B1D2, M4-04B3B1, M4-04B3B2 and M4-04B3C. |
| AR7 | Later and separate: a K7 pilot on DEV1/DEV2 inputs with API calls. Gate A remains required before any VAL1 work. |
