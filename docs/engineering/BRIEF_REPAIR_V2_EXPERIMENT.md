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

## Held-back DEV set

The [eight synthetic cases](../../data/dev/brief_repair_v2/held_back.json) use separate fictional Japanese scenes. They cover a clean control, wrapped text, hearsay, wrong citation, unknown participant, a combined structure and certainty fault, a soft-only compound fact, and missing core events. Each case has source and gold, with explicit edits used to build the shared initial Brief. Run `python -m tools.story_benchmark.brief_repair_v2 --held-back-preflight` to print the dataset, gold, source and initial Brief hashes and the serialized C0 estimates. Offline tests check that all golds satisfy the original validator and that the intended initial error strata are present. The held-back set is for the owner-reviewed comparison. The workshop fixture remains the development example.

## Proposed pilot budget and approval

Select one model after reviewing Wave 1 for factual accuracy, certainty, JSON reliability and output completeness. Then confirm that the pinned route has enough context, per-minute tokens, free account quota, and output capacity for full C0. Compare the four arms on that model with the same temperature, profile, source, starting Brief, and unchanged validators. C2 is the first candidate for review. Any default change requires the paired live result and owner decision.

The offline preflight exercises both full-repair slots using the fixed initial Brief as a scripted echo. Its largest estimated input is 4,145 tokens including the optional JSON instruction. Propose a 4,500-token input-estimate guard and a 3,072-token completion reserve per dispatch, including reasoning where the provider counts it as completion. Together these use 7,572 planned tokens against the published 8,000 TPM for either Groq candidate. This establishes room by the repo's UTF-8 estimator. Confirm the tokenizer, wrapper overhead, remaining quota and full JSON output headroom on whichever route is actually selected. Check every rendered request, especially C0 after a long model response. Mark the arm budget-stopped if the next request exceeds an approved bound. Preserve the complete source and validator.

| Pilot bound | Proposed allocation |
| --- | ---: |
| Model dispatches including failures, 8 cases × 4 arms × up to 2 | 64 |
| Estimated input budget at cap | 288,000 |
| Reserved output at cap | 196,608 |
| Automatic transport retries | 0 |

Schedule separately from Wave 1. Count any probe against this pilot budget and prefer using the first planned case. Stop on quota or ambiguous dispatch and report incomplete pairs. Approve the selected model, per-case hashes, scope, budget, schedule and expiry before dispatch. Both time and token values from fixtures are planning estimates or local measurements. [Groq rate limits](https://console.groq.com/docs/rate-limits)

## Readout

- Report numerator and denominator for final hard-invalid or missing Briefs per attempted case, initially invalid Briefs recovered per initially invalid case, and rejected or rolled-back proposals per proposed edit. Separate soft warnings from hard failures. Show clean controls that regressed.
- Have a blinded reviewer count supported facts over reviewed claims, and separately count claims with correct epistemic certainty over reviewed claims. Record actor, polarity and certainty mismatches and omitted required facts. Count each required gold fact with a valid supporting passage and exact quote once for evidence coverage. Score atomicity as single-claim facts over reviewed facts, retaining any validator warnings separately. Missing Briefs count as hard invalid, with zero required evidence recovered and no claim accuracy denominator.
- Record per-case provider-reported input, visible output, reasoning and total tokens; indicate whether reasoning is included in output. Record model latency and end-to-end wall time separately, including failed or discarded edits. Preserve missing usage as unknown. Show per-arm totals, per-case paired deltas and the number of fully observed pairs.
- Shortlist an arm only if the owner reviews semantic disagreements and sees no new unsupported claim, missing required evidence or hard-error regression on the paired pilot. Report possible trade-offs in atomicity and downstream retrieval. A small pilot supports a larger DEV comparison, not a quality verdict.
