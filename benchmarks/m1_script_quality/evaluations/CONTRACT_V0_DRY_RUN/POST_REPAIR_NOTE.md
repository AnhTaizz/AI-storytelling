# Contract v0 Dry-Run — Post-Repair Note

Task: `M1-SCRIPT-QUALITY-V0-CANDIDATE-REPAIR`.

The first-pass files in this folder (`RUN_0003_REVIEW.md`, `RUN_0004_REVIEW.md`, `DRY_RUN_SUMMARY.yaml`) and the cross-check are **not rewritten**. They record how the candidate behaved before the repair. This note re-derives only the logic the repair changed. The semantic review was not redone.

Machine-readable form: `POST_REPAIR_REEVALUATION.yaml`.

## 1. What the repair changed

| Dry-run issue | Repair | Contract section |
|---|---|---|
| OP-01 length could never fail its gate | Severity now also measures impact on the requested deliverable. A request finding is `HIGH` when satisfying the request needs substantial changes across the deliverable | 14, 14.1, 15 |
| OP-02 no `HIGH` for request or output findings | Request and output severity tables | 14.1, 14.2 |
| OP-03 missing subtypes | `INVENTED_SPEECH`, `UNSUPPORTED_DESCRIPTIVE_ATTRIBUTE` under `UNSUPPORTED_INVENTION` | 13 |
| OP-04 reconstructed quotes | Dialogue is judged by meaning; paraphrase allowed, invented content not | 4.4 |
| OP-05 spoiler versus certainty inflation | One finding, several violation tags, one severity, all affected gates, counted once | 13.1 |
| OP-06 free indirect thought | One semantic assertion, one finding | 13.1 |
| OP-07 unclear speaker of a hedged guess | `UNDETERMINED` when nothing settles it | 5.3 |
| OP-08 escalation record | Separate record; members keep their severities | 14.4 |
| OP-09 request not in one place | Request record at the top of the template | 17, template §0 |
| OP-10 counting method | No contract change. The contract already requires the method to be stated; the gap is in the historical run artifact | 11 |
| OP-11 provisional versus contract verdict | `REVIEW_TRACE_VERDICT` and `OFFICIAL_CONTRACT_VERDICT` | 16, template §5 |
| OP-12 finding granularity | One finding per independently evidenced and corrected defect | 13.1 |

The four verdicts and their order are unchanged. Human audit of the semantic gates is still required. H7 Stage B is still not executed and the H7 confirmatory verdict is still `NOT_EVALUATED`.

## 2. RUN_0003 under the repaired contract

Only finding A29 (length) is re-rated.

| Item | Before repair | After repair |
|---|---|---|
| Taxonomy | `REQUEST_NONCOMPLIANCE` / `LENGTH_NONCOMPLIANCE` | Same |
| Severity | `MEDIUM` | `HIGH` |
| `GATE_REQUEST_COMPLIANCE` | `GATE_CONDITIONAL` | `GATE_FAIL` |

Reason, from the first-pass record itself: 1648 words against 900–1100; about one third must be removed; the cuts are spread across most paragraphs; edit cost `MAJOR`. The violation cannot be repaired locally, so it is material under section 14.1. The severity follows from that repair scope, not from the percentage.

Trace verdict:

```text
GATE_REQUEST_COMPLIANCE = GATE_FAIL
GATE_EPISTEMIC_INTEGRITY = GATE_FAIL (unchanged)
GATE_FACTUAL_GROUNDING = GATE_FAIL (unchanged, by escalation)
→ FAIL
```

The trace verdict was `FAIL` before the repair and is `FAIL` after it. The difference is that length alone is now enough: with every other gate passing, the script would still be `FAIL`, where before it was `REVIEW_REQUIRED` through edit cost only.

`OFFICIAL_CONTRACT_VERDICT`: `REVIEW_REQUIRED`. No human audited the semantic gates. Length is a mechanical fact, but its severity is a judgement, and this judgement was made by an AI reviewer.

**Escalation record** (section 14.4), restating the first-pass escalation in the new form:

| Field | Value |
|---|---|
| `escalation_id` | `ESC-A-01` |
| `member_findings` | A05, A06, A07, A12, A15, A18, A23, A24, A27 |
| `original_severities` | MEDIUM, MEDIUM, LOW, LOW, LOW, LOW, LOW, MEDIUM, LOW |
| `escalated_severity` | `HIGH` |
| `affected_gate` | `GATE_FACTUAL_GROUNDING` |
| `impact_rationale` | Nine invented motives or internal states of one character together change how that character is understood |

The first-pass review already kept the members at their own severities, so nothing is contradicted.

## 3. RUN_0004 under the repaired contract

Length is 1074 words recorded (1021 by whitespace recount), inside 900–1100. There is no request-compliance finding. `GATE_REQUEST_COMPLIANCE` stays `GATE_PASS`. All gate statuses, ratings and the trace verdict `PASS_WITH_MINOR_EDITS` are unchanged. `OFFICIAL_CONTRACT_VERDICT`: `REVIEW_REQUIRED`.

## 4. How other first-pass findings would be labelled now

These are relabellings only. Severities, gates and verdicts do not change.

| First-pass finding | Then | Now |
|---|---|---|
| A20, B12 (unrecorded lines of dialogue) | `UNSUPPORTED_INVENTION` at parent level | `INVENTED_SPEECH` |
| A02, A03, B02 (side of the apartment, facial features) | `UNSUPPORTED_INVENTION` at parent level | `UNSUPPORTED_DESCRIPTIVE_ATTRIBUTE` |
| A01, B01 (suggested continuation stated as fact) | `CERTAINTY_INFLATION` only | Primary `CERTAINTY_INFLATION`, additional tag `PREMATURE_SPOILER`; still one LOW finding, counted once; both gates receive it, and a LOW finding changes neither gate's status |
| Hedged guess in Script A (line 39) | `COMMENTARY_RHETORIC`, noted as borderline | `UNDETERMINED`; goes to review |
| Certainty inside a spoken line (reference issue G029, not flagged in the first pass) | Unclear | A story claim under section 4.4: stronger certainty inside dialogue is not allowed |

An unresolved `UNDETERMINED` claim leaves its gate undetermined only when the gate has no material finding. Script A's factual gate already fails, so its status and the trace verdict `FAIL` do not change.
