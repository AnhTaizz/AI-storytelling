# Brief Repair V2 · proposed paired DEV experiment

Owner review is pending. This plan uses independent fictional DEV chapters. M9 r2 stays paused. A future official evaluation of a changed pipeline requires an owner decision on protocol and a fresh sample outside development.

## Offline prototype

Run `python -m tools.story_benchmark.brief_repair_v2` from this checkout. It runs C0 through C3 on five starting Brief variants of a synthetic workshop chapter. The scripted responder returns known fixture answers. The JSON report includes input character counts, validation findings, recovery and rollback rates, exact synthetic event and evidence scores, and local time. Provider token values and blind human scores are unknown. A targeted repair supplies the current chapter as evidence and limits edits to the diagnosed fields. Unmapped or ambiguous findings use a full repair. C3 stops only on a single character-fact atomicity warning after all hard checks pass.

The fixture uses 4, 5, 3 and 2 scripted calls for C0 through C3 respectively. Each arm recovers all three initially hard-invalid cases under the existing validator. C1 needs an extra call for the combined-error case because schema validation must pass before the semantic check can identify the next issue. C3 retains an atomicity warning in the soft-only variant. The exact synthetic event score sits outside character-fact review, so a reviewer should assess that trade-off in the paired pilot.

## Comparison

Freeze the candidate commit, validators, model identifier, provider, prompt templates, decoding settings, case order, source hashes, reviewed gold claims and evidence before dispatch. Keep held-back DEV cases separate from examples used to implement the repair logic. Exclude M9 chapters 6–17 and their derivatives. Use the same starting Brief for every arm on a case. If generated, produce it once and report its cost separately. Keep model responses private and give the reviewer shuffled output IDs.

| Arm | Intervention |
| --- | --- |
| C0 | Existing full-object model repair and validator sequence |
| C1 | Model edits a bounded field using its supporting passages and dependencies. Reassemble and validate the complete Brief. |
| C2 | C1 plus lossless, unambiguous structural normalization before dispatch. Revalidate before deciding whether a model call is needed. |
| C3 | C2 plus the candidate's predeclared soft-only stop rule. Record each early stop and the outstanding findings. |

Use two model repair opportunities per arm at most. Compare the arms on identical source and initial error strata, including clean controls, structure-only, semantic, combined and soft-only cases. Record the best admissible checkpoint, rejected edits, final selection and all remaining findings. C0 should preserve the original selection behavior as a comparator. Blind review should include unchanged and rolled-back outputs.

## Proposed pilot budget and approval

Propose one free-tier Groq GPT-OSS 20B model for all four arms, subject to owner confirmation of eligibility and available quota. Schedule separately from Wave 1. For an initial eight held-back cases with fixed starting Briefs, one pass has a maximum of 64 repair dispatches (8 × 4 × 2). Use no transport retries in this pilot and stop on quota or ambiguous dispatch. Fix a common supported output cap after a context-size dry run. Present the actual source and gold hashes, input/output budget, provider scope, date and expiry to the owner before live execution. Log incomplete pairs separately. A scripted fixture response can verify mechanics only.

## Readout

- Report numerator and denominator for final hard-invalid or missing Briefs per attempted case, initially invalid Briefs recovered per initially invalid case, and rejected or rolled-back proposals per proposed edit. Separate soft warnings from hard failures. Show clean controls that regressed.
- Have a reviewer score each final factual claim against the source, including actor, polarity and epistemic certainty. Report supported claims over reviewed claims and separately count omitted required claims. Count each required gold fact with a valid supporting passage and exact quote once for evidence coverage. Predefine handling of empty outputs and missing measurements.
- Record per-case provider-reported input, visible output, reasoning and total tokens; indicate whether reasoning is included in output. Record model latency and end-to-end wall time separately, including failed or discarded edits. Preserve missing usage as unknown. Show per-arm totals, per-case paired deltas and the number of fully observed pairs.
- Shortlist an arm only if the owner reviews semantic disagreements and sees no new unsupported claim, missing required evidence or hard-error regression on the paired pilot. Report possible trade-offs in atomicity and downstream retrieval. A small pilot supports a larger DEV comparison, not a quality verdict.
