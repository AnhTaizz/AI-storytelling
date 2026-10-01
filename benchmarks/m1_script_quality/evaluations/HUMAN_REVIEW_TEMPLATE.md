# Human Review Template

**CANDIDATE — aligned with `SCRIPT_QUALITY_CONTRACT/v0` (candidate). Not frozen.**

Contract: `docs/contracts/SCRIPT_QUALITY_CONTRACT_V0.md`. Section numbers below refer to it.

Rules for the reviewer:

- Judge story truth against the truth boundary given for the request, not from memory of the work.
- Every finding and every rating needs a cited passage and a reason. A rating without evidence is invalid.
- Do not average. Integrity is decided by gates; narrative dimensions are separate.

## 0. Review Header

- Script / run ID:
- Reviewer role:
- Date:
- Requested scope:
- Truth boundary used:
- Narrative Profile (language, register, length target, spoiler mode):
- Automated checks consulted (if any):

## 1. Part A — Integrity (hard gates)

*Did the script keep the story true?*

Record each finding once, using the taxonomy in section 13.

| # | Script passage | Taxonomy ID | Claim type (§4.1) | Severity (§14) | Boundary evidence, or "absent" | Suggested fix |
|---|---|---|---|---|---|---|
| 1 | | | | | | |

Then give each gate a status: `GATE_PASS` (nothing above LOW), `GATE_CONDITIONAL` (MEDIUM, none material), `GATE_FAIL` (any HIGH or CRITICAL), `GATE_NOT_DETERMINED` (could not be evaluated).

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

- Any event, action, posture or detail the boundary does not contain?
- Any motive, intention, feeling or thought stated as fact without support?
- Any "might" turned into "will", "some" into "all", "seems" into "knows"?
- Any rumour or self-report restated as narrator fact?
- After reordering, is the true order of events still clear?
- Is anything from beyond the requested scope stated or implied?
- Is anything left out that the audience needs to understand what is told?
- Stray foreign-script tokens, meta text, or length outside the target (state the counting method)?

## 2. Part B — Narrative (soft dimensions)

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

## 3. Edit Cost

Choose one and say why (section 18):

- `MINIMAL` — word-level fixes
- `MODERATE` — several sentences rewritten, softened or removed; structure stays
- `MAJOR` — sections restructured, or integrity fixes spread across the script
- `REWRITE` — faster to write again

Edit cost:
Reason:

## 4. Verdict

Apply section 16 in order:

1. `FAIL` — any gate `GATE_FAIL`, or edit cost `REWRITE`.
2. `REVIEW_REQUIRED` — any gate `GATE_NOT_DETERMINED`, or a soft dimension rated 2 or lower, or edit cost `MAJOR`.
3. `PASS` — all gates `GATE_PASS`, no soft dimension below 3, `OVERALL_USEFULNESS` at least 4, edit cost `MINIMAL`.
4. `PASS_WITH_MINOR_EDITS` — otherwise.

Verdict:
Single biggest remaining problem:

## 5. Comparison (only when reviewing two scripts)

- Which would you rather narrate, and why?
- Which needs less editing to publish (edit cost for each)?
- What from either script should be kept as a style reference?
