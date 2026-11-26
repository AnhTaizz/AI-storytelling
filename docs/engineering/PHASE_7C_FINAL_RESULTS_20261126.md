# Phase 7C · Final DEV results

26 November 2026 (Asia/Bangkok). The owner approved the C0/C4 and Source Check S0/S1 runs separately. PR #47 passed its required quality gate on a branch updated with #46. The live worktree verified the experiment code, source and gold hashes, and approved request fingerprints against the prepared plans. Groq Free `openai/gpt-oss-120b`, native JSON mode and temperature `0` were common. C0/C4 ran first, and S0/S1 carried the same provider quota state with its own dispatch ledger. M9 r2 stayed paused. The C0–C3 blinded owner semantic review remains pending. [C0–C3 readout](BRIEF_REPAIR_V2_PILOT_RESULTS_20261126.md) · [Approved execution plan](PHASE_7C_REVISED_DEV_PLAN.md)

## Quality · Brief Repair V2

All 12 case–arm runs completed. The clean control used zero calls. Both arms recovered all four initially hard-invalid Briefs and finished with zero remaining hard or soft findings. Eleven Groq responses returned HTTP 200 with a JSON object and `finish_reason=stop`. The comparison retains all proposals and every validator failure.

| Arm | Hard-invalid starts recovered | Hard-invalid or missing finals | Whole Brief exact | Events exact | Exact-evidence matches | Supported claims | Correct certainty | Source-backed required facts | Single-claim character facts |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C0 | 4/4 | 0/6 | 3/6 | 8/12 | 8/12 | 14/15 | 14/15 | 13/14 | 11/11 |
| C4 | 4/4 | 0/6 | 4/6 | 11/12 | 11/12 | 14/14 | 14/14 | 14/14 | 9/9 |

The exact scorer uses the frozen event and citation rules. The separate preliminary source review counts distinct propositions and requires a supporting passage and verbatim quotation for each required fact. It counts single-claim character-fact entries as atomic. The owner grades remain pending. In the radio case, C0 used the `REPORTED` label and placed “heard” after Maki's name in the cited event and character fact, assigning the hearing to Maki. C4 preserved the reported buyer and the uncertainty. Both arms' selections passed the existing validators. In the paper-tags case, both final selections cited all four distinct facts and split the three related actions. Phrasing, punctuation and citation span differences explain why the exact scorer and source review give different results.

## Quality · Source Check

All six requests returned HTTP 200, a JSON object and `finish_reason=stop`. Both passes had three validator-accepted groups and covered all nine units and three flags. The preliminary review preserves the false positives and classification errors.

| Pass | Defects detected | Gold defect types matched | False positives among supported units | Correct critic verdicts | Required positive defect passages | U9 absence checked across scope |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| S0 | 3/3 | 2/3 | 1/6 | 3/3 | 2/2 | 1/1 |
| S1 | 3/3 | 2/3 | 1/6 | 3/3 | 2/2 | 1/1 |

Both passes treated U3's paraphrase as unsupported and labeled U4 `CONTRADICTS_SOURCE` where the gold calls it `STRENGTHENED`. U4's 1.2 and U5's 1.3 appeared in both findings and their flag replies. For U9, 1.3 was relevant contrasting context. Review of the entire input scope supported the absence judgment. U8's two supporting passages were present in both passes. The current schema provides no explicit citation for U8 when it has no finding. S1 also cited 1.1 as context in F2, while retaining 1.3 as the evidence for the actor who replaced the bulb. [Source Check schema](../../schemas/story_pipeline/source_check_v0.schema.json)

## Efficiency and attribution

### Brief Repair

The extension used 11 of 24 allowed dispatches, bringing the existing ledger from 34/64 to **45/64**. There were zero retries or quota refusals. The dispatch journals retain the original 34 charges and append 35–45. All attempts reported token usage, including the rejected radio proposal and the additional paper-tags repair. Completion includes reasoning. Per-arm wall time includes validation and quota waits, and those waits reflect execution order.

| Arm | Calls | Input | Completion | Reasoning | Total | HTTP time | Quota wait | Wall time |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C0 | 7 | 23,921 | 4,819 | 2,184 | 28,740 | 15.61 s | 177.35 s | 193.64 s |
| C4 | 4 | 13,686 | 3,217 | 1,787 | 16,903 | 10.26 s | 121.14 s | 131.81 s |

| Case | C0 calls / total tokens | C4 calls / total tokens | Attribution |
| --- | ---: | ---: | --- |
| Kite | 0 / 0 | 0 / 0 | Both start and finish valid |
| Archive | 1 / 3,876 | 0 / 0 | Deterministic normalization produced the same exact Brief and avoided a call measured at 1.668 s HTTP time |
| Bridge | 1 / 4,175 | 1 / 4,069 | Identical first payloads produced different text and parsed Briefs |
| Orchard | 1 / 4,019 | 1 / 4,019 | Identical first payloads produced identical output |
| Radio | 2 / 8,139 | 1 / 4,242 | Normalization removed a schema error and exposed the certainty finding before the first call. Both arms used the model with different payloads |
| Paper tags | 2 / 8,531 | 1 / 4,573 | Identical first payloads diverged. C0's first proposal retained two language warnings and needed another repair |

C4 used **41.2%** fewer reported tokens over all six pairs. In the five pairs whose outputs both passed preliminary source checks, the difference was **38.5%** (20,601 to 12,661 tokens). The archive case establishes the deterministic saving of one call and 3,876 tokens. The radio difference combines normalization and model response. Bridge and paper-tags differences fall under variation on identical first requests. Groq reported two 2,560-token cache reads on C0's paper-tags requests, confirming prompt reuse on that case. Brief Repair's other nine responses omitted the counter. These observations measure distinct effects and provide no additive decomposition of latency.

### Source Check

Source Check used **6/6** on its own ledger with zero retries or quota refusals. The three repeat payloads matched S0 byte for byte and ran within the cache window. All six responses omitted `usage.prompt_tokens_details.cached_tokens`, leaving cache hits and cached share unknown. Both passes used 3,671 prompt tokens. S0 used 5,753 total tokens including 1,596 reasoning tokens, and S1 used 5,718 total including 1,539 reasoning tokens. The textual and parsed responses differed in all three pairs. [Groq cache counters](https://console.groq.com/docs/prompt-caching#tracking-cache-usage)

| Group | S0 HTTP | S1 HTTP | S1 − S0 | S0 prompt processing | S1 prompt processing |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 2,476 ms | 2,365 ms | −111 ms | 53.3 ms | 52.7 ms |
| 2 | 2,169 ms | 2,040 ms | −129 ms | 51.6 ms | 53.1 ms |
| 3 | 1,420 ms | 1,971 ms | +551 ms | 58.7 ms | 50.6 ms |
| Total | 6,065 ms | 6,376 ms | +311 ms | 163.6 ms | 156.4 ms |

The small reduction in prompt-processing time and the mixed HTTP timings do not establish an operational cache benefit. The repeated calls added a full pass of work. Preserve current Source Check grouping and prompts. The Source Check research closes at S0/S1.

## Production decision for owner review

The C0–C3 pilot favored C0 on hard-error recovery and required evidence. C4 retained recovery and evidence in the six-case comparison and demonstrated one fully deterministic saving. The minimal integration proposal is an opt-in lossless unwrap of single-string `text` wrappers in `unknowns` and `forbidden_inferences` at the existing Brief validation boundary. Preserve the original candidate in diagnostics, validate the whole normalized Brief and continue through the existing C0 full-repair path on any hard or soft finding. The owner can review the blinded outputs and decide on that isolated change. Production routing, provider and Source Check remain as they are. Phase 7C experiments are complete and the product pipeline can continue under the existing defaults.
