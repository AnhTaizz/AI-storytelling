# Contract v0 Dry-Run — Cross-Check and Findings

Task: `M1-SCRIPT-QUALITY-V0-OPERATIONAL-DRY-RUN`. Written **after** the first-pass reviews were locked.

Result: **`SCRIPT_QUALITY_V0_NEEDS_REPAIR`**. The rubric could be applied end to end to both scripts, but one issue (the length edge case) cannot be fixed without changing hard-gate or severity semantics. The candidate contract was not modified.

## 1. First-Pass Lock

The three first-pass files were committed on their own before any historical review was opened.

| File | SHA-256 (committed blob) |
|---|---|
| `RUN_0003_REVIEW.md` | `c707dbed0f67c46035e1d8df5a45968ca3195a38d2ded7bbd37a89e6b66cd139` |
| `RUN_0004_REVIEW.md` | `75d5eea18ce10e35d926a3c3d6a23151be06c643d0a3fc59520c0c47ef58f22e` |
| `DRY_RUN_SUMMARY.yaml` | `2404094e05ea99c1017dca3b6d28db6aa0e30bd5478f246e1c58852808a4f2bd` |

Lock commit: `8835b4b` ("research: lock script quality contract v0 dry-run first pass"). The files have not been edited since.

**Limit on what the cross-check can show.** The reviewer had read the H1/H2/H6 comparison documents and the H6b residual analysis (which lists 22 of the reference issues) earlier in the same session, for the contract-drafting task. Agreement with the historical record below is therefore **not independent confirmation**. It shows that the contract can express those findings, not that a naive reviewer would find them.

## 2. Historical Cross-Check

Read after the lock: `RUN_0002_VS_RUN_0003_H2.md`, `RUN_0003_VS_RUN_0004_H6.md`, `RUN_0004_H6_CRITIC/CRITIC_REVIEW.md`, `critic_report.yaml`, and the H6b reference (`H6B_RUN3_ADJUDICATION_CANDIDATE_V3.yaml`) for taxonomy alignment.

### 2.1 Script A against the H6b reference (34 issues: 33 robust, 1 questionable)

| Outcome | Count | Reference issues |
|---|---|---|
| Covered by a first-pass finding | 31 | G001–G016, G018–G021, G023–G028, G030–G034 |
| Not flagged in the first pass | 3 | G017, G022, G029 |

| Discrepancy | Classification | Note |
|---|---|---|
| G017 (second mention of pallor) not flagged | `REVIEWER_JUDGEMENT_DIFFERENCE` | The first pass flagged the first mention (A10) and missed the repeat. A reviewer miss |
| G022 (he assumes she thinks he is flirting) considered and not flagged | `CONTRACT_AMBIGUITY` | The first pass read the hedged guess as commentary. Read as the character's thought, it is a story claim. See OP-07 |
| G029 (certainty of illness inside a spoken line) not flagged | `CONTRACT_AMBIGUITY` | The contract does not say how strictly a reconstructed quote is held to the boundary. See OP-04 |
| First pass bundles several claims in one finding (A03, A10, A19, A24, A26, A27); the reference splits them | `EXPECTED_RUBRIC_DIFFERENCE` | The contract does not define finding granularity. See OP-12 |
| A01 (hook states a suggested continuation as fact) absent from the reference | `NEW_VALID_FINDING` | |
| A04 ("whole school") absent from the reference | `NEW_VALID_FINDING` | Minor |
| A20 (invented lines of dialogue); the reference has only the shrug | `OLD_REVIEW_GAP` | The reference audited claims, and treated the added lines as acceptable dialogue |
| A21, parts of A08 and A26 (minor staging) absent from the reference | `NEW_VALID_FINDING` | All LOW |
| A29 (length) absent from the reference | `EXPECTED_RUBRIC_DIFFERENCE` | The reference covers factual claims only |
| Severity: reference MEDIUM, first pass LOW for G015, G018, G025, G033 | `REVIEWER_JUDGEMENT_DIFFERENCE` | The contract does not inherit H6b severity. The only HIGH is the same issue in both (G024 = A22) |
| Critic V1 rated the inferiority motive HIGH; first pass rated A05 MEDIUM | `EXPECTED_RUBRIC_DIFFERENCE` | Under the contract HIGH needs a material change of interpretation. The first pass reached HIGH for the set, by cumulative escalation |

### 2.2 Script A against the H2 comparison

| Historical statement | First pass | Classification |
|---|---|---|
| Hair colour, seated posture, conservative ending preserved | No finding on any of them; temporal/state gate passes | Agreement |
| "Knows his place" invented by the Writer | A05 | Agreement |
| 1648 words; exposition padded and slow | A29; PACING = 2 | Agreement |
| Ending "more subtle" than RUN_0002 | Ending accepted; hook A01 flagged LOW | `NEW_VALID_FINDING` (the hook, not the ending) |

### 2.3 Script B against the H6 comparison and critic review

| Historical statement | First pass | Classification |
|---|---|---|
| Retained after revision: shrug, huddled posture, certainty of a cold, "no longer feels guilty" | B12, B15, B16, B14 | Agreement |
| Revision introduced "small park" and "after school" | B06, B05 | Agreement |
| Softened but intensified guilt language | B10 | Agreement |
| Narrator sign-off added | Accepted as commentary; counted against naturalness and callback | Agreement |
| Hook cleaner, pacing faster, no severe narrative degradation | HOOK, FLOW, PACING, EMOTION = 4 | Agreement |
| Not stated historically: loss of narrator voice | HUMOR_COMMENTARY_QUALITY 3 (A was 4); NATURALNESS 3 (A was 4) | `NEW_VALID_FINDING` |

## 3. Safe-Creativity Check

The contract did not treat every figure or aside as an invention.

- The two elements the historical critic called safe ("living doll", "fateful afternoon") were classified `COMMENTARY_RHETORIC` in the first pass, before the critic report was read.
- Script A: 11 passages considered and not flagged. Script B: 10. They include hooks, idioms, similes, rhetorical questions, jokes and one hedged inference.
- Weakening was recognised as allowed (abilities presented as rumour in Script A).
- One passage was borderline (the hedged guess, OP-07). That is one of 21, and it turns on who is guessing, not on the test itself.

Result: safe commentary can be classified consistently. `CONTRACT_FIX_REQUIRED` is **not** raised on this point.

## 4. Known-Error Check

| Historical failure mechanism | Taxonomy path | Gate / dimension | Observed |
|---|---|---|---|
| Invented internal state | `UNSUPPORTED_INVENTION` / `MOTIVE_OR_INTERNAL_STATE_INVENTION` | `GATE_FACTUAL_GROUNDING` | A05–A07, A12, A15, A18, A23, A24, A27; B04, B09, B14, B18 |
| Hidden intention | `UNSUPPORTED_INVENTION` / `HIDDEN_INTENTION_INFERENCE` | `GATE_FACTUAL_GROUNDING` | A09, B07 |
| Certainty inflation | `EPISTEMIC_ERROR` / `CERTAINTY_INFLATION` | `GATE_EPISTEMIC_INTEGRITY` | A11, A14, A28; B16 |
| Knowledge overclaim | `EPISTEMIC_ERROR` / `EPISTEMIC_KNOWLEDGE_OVERCLAIM` | `GATE_EPISTEMIC_INTEGRITY` | A22 |
| Unsupported staging | `UNSUPPORTED_INVENTION` / `UNSUPPORTED_ACTION_OR_STAGING` | `GATE_FACTUAL_GROUNDING` | A08, A13, A16, A25, A26; B06, B15, B17 |
| Invented causality | `CAUSALITY_ERROR` / `CAUSALITY_INVENTION` | `GATE_FACTUAL_GROUNDING` | A19, B03 |
| Writer drift from the Story Brief | All of the above, measured against the boundary | — | Both scripts |
| Revision-introduced drift | Same categories | — | B05, B06 |
| Under-compression | `POOR_PACING` / `UNDER_COMPRESSION`; `REQUEST_NONCOMPLIANCE` / `LENGTH_NONCOMPLIANCE` | PACING; `GATE_REQUEST_COMPLIANCE` | Script A |
| Over-compression | `POOR_PACING` / `OVER_COMPRESSION`; `MISSING_IMPORTANT_EVENT` if necessary information is lost | Soft dimensions; `GATE_NECESSARY_COVERAGE` | Script B, mild (voice and naturalness) |

Every historically important mechanism has a taxonomy and gate path. `CONTRACT_FIX_REQUIRED` is **not** raised on this point. The one path whose gate behaviour is unsound is length (section 6).

## 5. Verdict Sanity Matrix

`tests/script_quality/test_verdict_sanity_v0.py` encodes section 16 in a small test-only helper and checks eight synthetic states.

| Case | State | Expected | Result |
|---|---|---|---|
| V1 | All gates pass, soft ≥ 3, overall ≥ 4, `MINIMAL` | `PASS` | `PASS` |
| V2 | One MEDIUM local integrity finding, `MODERATE` | `PASS_WITH_MINOR_EDITS` | `PASS_WITH_MINOR_EDITS` |
| V3 | One HIGH factual finding | `FAIL` | `FAIL` |
| V4 | Semantic human audit missing | `REVIEW_REQUIRED` | `REVIEW_REQUIRED` |
| V5 | All gates pass, PACING = 2 | `REVIEW_REQUIRED` | `REVIEW_REQUIRED` |
| V6 | No failed gate, edit cost `MAJOR` | `REVIEW_REQUIRED` | `REVIEW_REQUIRED` |
| V7 | One gate fails, all narrative scores 5 | `FAIL` | `FAIL` |
| V8 | Edit cost `REWRITE` | `FAIL` | `FAIL` |

The test also checks that every combination of gate statuses, lowest soft rating, overall rating and edit cost yields exactly one verdict. The verdict logic is coherent and exhaustive. The helper is not a production evaluator.

## 6. Issues Found and Their Classification

| ID | Issue | Class | Repair changes acceptance semantics? |
|---|---|---|---|
| OP-01 | Section 15 says `GATE_REQUEST_COMPLIANCE` fails when the requested length is not met. Section 14 makes a length finding MEDIUM, and no definition lets it become material. The gate can never fail on length. A 1-word and a 500-word overrun get the same gate status | `VERDICT_SEMANTIC_GAP` | **Yes** — hard-gate and severity semantics |
| OP-02 | HIGH and CRITICAL are defined by story interpretation (plus "unusable"). Request and output findings have no described HIGH case | `SEVERITY_AMBIGUITY` | **Yes** — severity meaning. Same repair as OP-01 |
| OP-03 | No subtype for invented speech or invented descriptive attributes | `TAXONOMY_GAP` (minor) | No — additive subtype |
| OP-04 | No fidelity standard for reconstructed or translated direct quotes | `RUBRIC_USABILITY_GAP` | Possibly — it decides whether a certainty inside a quote is a violation |
| OP-05 | No tie-break when `PREMATURE_SPOILER` and `CERTAINTY_INFLATION` both apply | `DOCUMENTATION_CLARIFICATION` | Possibly — the two belong to different gates |
| OP-06 | Free indirect thought: one finding or two | `DOCUMENTATION_CLARIFICATION` | No |
| OP-07 | A hedged guess may be the narrator's or the character's | `DOCUMENTATION_CLARIFICATION` | No — an example would settle it |
| OP-08 | Cumulative escalation decided a gate; no guidance on recording the escalated set | `SEVERITY_AMBIGUITY` | No — already a disclosed limitation |
| OP-09 | Request and Narrative Profile had to be assembled from two files | `RUBRIC_USABILITY_GAP` | No — template |
| OP-10 | Counting method of the recorded word count is unstated | `NO_CONTRACT_GAP` | No — the contract already requires it |
| OP-11 | Template cannot distinguish a provisional AI trace from the contract verdict | `RUBRIC_USABILITY_GAP` | No — template |
| OP-12 | Finding granularity is undefined (one finding per claim, per sentence or per passage). It affects counts and cumulative escalation | `RUBRIC_USABILITY_GAP` | No |

Because OP-01 and OP-02 cannot be repaired without changing hard-gate or severity semantics, **nothing was repaired in this task**, including the items that would be safe to clarify. The candidate contract, the YAML and the review template are unchanged.

### Length edge case in full (RUN_0003: target 900–1100, recorded 1648)

1. Severity under the existing wording: **MEDIUM**.
2. Why: section 14 names "length outside tolerance" as MEDIUM, and neither HIGH nor CRITICAL fits a script that is too long but usable after cutting.
3. Required repair: **`MAJOR`** (about a third of the text, across most paragraphs).
4. Gate status: **`GATE_CONDITIONAL`**.
5. Verdict from length alone: **`REVIEW_REQUIRED`**, reached through edit cost, not through the gate.

Assessment: **`CONTRACT_SEMANTIC_GAP`**. The final outcome is defensible, but the contract's own description of the gate is contradicted, and overrun size has no effect on gate status.

Repair options for the Orchestrator (none applied):

- **(a) Make the text match the behaviour.** State that a length finding is at most MEDIUM, so the gate is conditional on length and gross overruns are caught by edit cost and pacing. Smallest change. Recommended by this reviewer, because the verdict already lands where it should.
- **(b) Make length able to fail the gate.** Define when a request-compliance finding is material, for example by bands relative to the tolerance or by a "strict" flag in the request. This gives the gate teeth but adds a numeric rule the contract has so far avoided.

Either choice also settles OP-02.

## 7. Human-Audit Requirement

The requirement is coherent with the evidence and should stay.

- Under section 16, both strict contract verdicts are `REVIEW_REQUIRED`, because no human audited the semantic gates. The rule behaves as written.
- The AI first pass was itself imperfect: against the adjudicated reference it left 3 of 34 issues unflagged and differed on severity for several, despite prior exposure to much of that reference.
- For Script A, `FAIL` versus `REVIEW_REQUIRED` rests on one severity judgement.
- Current critics are advisory sources of candidate findings. They are not sufficient to grant a semantic `GATE_PASS` on their own. An AI reviewer filling in the template does not change that.
- H7 Stage B is still not executed. H7 confirmatory verdict: `NOT_EVALUATED`. No H7 claim changes in this task.

## 8. Freeze Readiness

| Condition | Met? |
|---|---|
| Both real-script dry-runs completed | Yes |
| …without contract ambiguity | No — OP-01, OP-02; lesser ambiguities OP-04, OP-05, OP-07 |
| Severity, gate and verdict logic coherent | Verdict logic yes. Severity and gate: not for request compliance |
| Safe creativity distinguishable from factual mutation | Yes |
| Historical major failures map naturally | Yes |
| No breaking contract change needed | **No** |

Recommendation: **`SCRIPT_QUALITY_V0_NEEDS_REPAIR`**. The repair is narrow: decide the length question (section 6), then apply the non-breaking clarifications and template changes. A re-run of this dry-run is not needed for the clarifications; the length case should be re-derived after the repair.
