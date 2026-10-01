# Human Review Template

**CANDIDATE — aligned with `SCRIPT_QUALITY_CONTRACT/v0` (repaired candidate). Not frozen.**

Contract: `docs/contracts/SCRIPT_QUALITY_CONTRACT_V0.md`. Section numbers below refer to it.

Rules for the reviewer:

- Judge story truth against the truth boundary given for the request, not from memory of the work.
- Every finding and every rating needs a cited passage and a reason. A rating without evidence is invalid.
- Do not average. Integrity is decided by gates; narrative dimensions are separate.

## 0. Request Record

Fill this in first. The review must be readable without opening other files.

- Script / run ID:
- Requested scope (story range, and the story point up to which information is authorized):
- Truth boundary (file or view used):
- Target language and register:
- Target length or duration:
- Length tolerance:
- Counting method (and the count obtained):
- Spoiler mode:
- Relevant Narrative Profile constraints (perspective, tone, humor level, hook style, other hard constraints):

## 1. Review Header

- Reviewer role:
- Reviewer kind: human / AI or model-assisted
- Human audit of the semantic gates done: yes / no
- Date:
- Contract version and commit:
- Automated checks consulted (if any):

## 2. Part A — Integrity (hard gates)

*Did the script keep the story true, and is it the deliverable that was requested?*

Record each finding once (section 13.1):

- One finding is one semantic defect that can be evidenced and corrected on its own. Bundle words that express the same error; split different propositions.
- If one claim breaks more than one invariant, keep one finding, give it a primary taxonomy ID and list the other violation tags. It counts once, and every affected gate receives it.
- Judge dialogue and unquoted thoughts by their meaning (sections 4.4 and 13.1).
- If a hedged guess could be the narrator's or a character's and nothing settles it, use claim type `UNDETERMINED` (section 5.3).

| # | Script passage | Primary taxonomy ID | Other violation tags | Claim type (§4.1) | Severity (§14) | Invariant(s) | Gate(s) | Boundary evidence, or "absent" | Reason | Suggested fix |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | | | | | | | | | | |

Severity is assigned by impact on the audience's understanding or on the requested deliverable. For length and other request findings it depends on the repair scope, not on a percentage (section 14.1).

**Cumulative escalations** (section 14.4). Member findings keep their own severities.

| `escalation_id` | `member_findings` | `original_severities` | `escalated_severity` | `affected_gate` | `impact_rationale` |
|---|---|---|---|---|---|
| | | | | | |

Then give each gate a status: `GATE_PASS` (nothing above LOW), `GATE_CONDITIONAL` (MEDIUM, none material), `GATE_FAIL` (any HIGH or CRITICAL, including an escalation), `GATE_NOT_DETERMINED` (could not be evaluated).

| Gate | Status | Finding numbers | Note |
|---|---|---|---|
| `GATE_FACTUAL_GROUNDING` | | | |
| `GATE_EPISTEMIC_INTEGRITY` | | | |
| `GATE_TEMPORAL_STATE_INTEGRITY` | | | |
| `GATE_SPOILER_DISCIPLINE` | | | |
| `GATE_NECESSARY_COVERAGE` | | | |
| `GATE_OUTPUT_INTEGRITY` | | | |
| `GATE_REQUEST_COMPLIANCE` | | | |

Prompts for the reviewer:

- Any event, action, posture, spoken line or detail the boundary does not contain?
- Any motive, intention, feeling or thought stated as fact without support?
- Any "might" turned into "will", "some" into "all", "seems" into "knows"?
- Any rumour or self-report restated as narrator fact?
- After reordering, is the true order of events still clear?
- Is anything from beyond the requested scope stated or implied?
- Is anything left out that the audience needs to understand what is told?
- Stray foreign-script tokens or meta text?
- Is the length inside tolerance? If not, can it be fixed locally, or does it need changes across the script?

## 3. Part B — Narrative (soft dimensions)

*Did the script tell the story effectively, for this profile?*

Rating anchors: **1** poor · **3** usable with noticeable editing · **5** strong, publication-ready for this dimension. Use 2 and 4 for in-between. Mark `N/A` where allowed. Dimension anchors are in section 17.

| Dimension | Rating (1–5 or N/A) | Evidence / example | Why |
|---|---|---|---|
| `HOOK_STRENGTH` | | | |
| `NARRATIVE_FLOW` | | | |
| `PACING` | | | |
| `EMOTIONAL_IMPACT` (N/A allowed) | | | |
| `HUMOR_COMMENTARY_QUALITY` (N/A allowed) | | | |
| `CALLBACK_QUALITY` (N/A allowed) | | | |
| `NARRATION_NATURALNESS` | | | |
| `OVERALL_USEFULNESS` | | | |

Judge appropriateness and effectiveness, not quantity. A script is not better for having more jokes.

## 4. Edit Cost

Choose one, list the concrete edits, and say why (section 18):

- `MINIMAL` — word-level fixes
- `MODERATE` — several sentences rewritten, softened or removed; structure stays
- `MAJOR` — sections restructured, or integrity fixes spread across the script
- `REWRITE` — faster to write again

Edit cost:
Concrete edits:
Reason:

## 5. Verdict

Apply section 16 in order:

1. `FAIL` — any gate `GATE_FAIL`, or edit cost `REWRITE`.
2. `REVIEW_REQUIRED` — any gate `GATE_NOT_DETERMINED`, or a soft dimension rated 2 or lower, or edit cost `MAJOR`.
3. `PASS` — all gates `GATE_PASS`, no soft dimension below 3, `OVERALL_USEFULNESS` at least 4, edit cost `MINIMAL`.
4. `PASS_WITH_MINOR_EDITS` — otherwise.

Record both verdicts:

- `REVIEW_TRACE_VERDICT` (from the states recorded above):
- Decision trace:
- `OFFICIAL_CONTRACT_VERDICT`:

If no human has audited the semantic gates (factual grounding, epistemic, temporal/state, spoiler, coverage), those gates are `GATE_NOT_DETERMINED` for the official verdict, and `OFFICIAL_CONTRACT_VERDICT` is `REVIEW_REQUIRED`. An AI or model-assisted review alone never gives an official `PASS` or `PASS_WITH_MINOR_EDITS`.

Single biggest remaining problem:

## 6. Comparison (only when reviewing two scripts)

- Which would you rather narrate, and why?
- Which needs less editing to publish (edit cost for each)?
- What from either script should be kept as a style reference?
