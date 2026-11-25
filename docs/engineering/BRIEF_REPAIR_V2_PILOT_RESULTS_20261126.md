# Brief Repair V2 · Groq GPT-OSS 120B pilot

26 November 2026 (Asia/Bangkok). The Project Owner approved the paired pilot after the [calibration and first-case capacity probe](PHASE_7_GROQ_120B_CALIBRATION_RESULTS.md). The approved run binds the eight held-back synthetic DEV cases, their shared initial Briefs and golds, and the validator and prompt code at `4dc3b1a`. Every dispatch used Groq Free `openai/gpt-oss-120b`, native JSON object mode, temperature `0`, default reasoning effort, a 4,500-token estimated-input guard, and a 3,072-token completion cap. The pilot allowed two model repair opportunities per case and arm and zero transport retries. [Paired protocol](BRIEF_REPAIR_V2_EXPERIMENT.md) · [Groq quota headers](https://console.groq.com/docs/rate-limits)

## C0 and content failures

`lighthouse_clean` retained its frozen starting Brief in every arm with zero repair dispatches. `bakery_wrapped_text` was the first case that required repair. C0 sent one full-object repair at an estimated 4,072 input tokens. Groq returned HTTP 200 with `finish_reason=stop`, 3,991 total tokens, and a JSON Brief that matched the complete gold object and cleared every validator.

On both hearsay scenes, some targeted proposals set `REPORTED` and preserved the Japanese `らしい` marker in the event summary. The Vietnamese Brief required the corresponding hedge in Vietnamese. These HTTP 200 responses were content failures under the existing validator. They remained in the denominator, and the arms with no admissible checkpoint returned a missing Brief.

The first targeted payloads for C1, C2 and C3 on `market_hearsay` had identical hashes. Only C2 returned an admissible Brief in that case. On `theatre_combined`, C2 and C3 sent the same first payload after normalization, and only C3 succeeded. These within-pilot differences are observed variation on matching requests at temperature `0`. The C3 stop rule did not fire in either of these cases.

## Exact match and validation

All **32/32** case–arm runs completed. The pilot used **33 repair dispatches**, plus the earlier capacity probe, for **34/64** total. All 33 repair responses were HTTP 200 with `finish_reason=stop` and a JSON object. The largest input estimate was 4,134 tokens. The run stayed within the guard and Free quota, with zero quota refusals, integration or ambiguous transport errors, and retries. Start and finish were approximately 00:38 and 00:49 Bangkok time.

| Arm | Hard-invalid or missing Briefs | Initially hard-invalid Briefs recovered | Outputs with soft warnings | Hard-rejected proposals | Rollbacks | Entire Brief exact | Events exact / emitted | Evidence exact / required events |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C0 | 0/8 | 6/6 | 0/8 | 1/8 | 0/8 | 4/8 | 13/16 | 13/16 |
| C1 | 2/8 | 4/6 | 1/8 | 4/11 | 2/11 | 3/8 | 10/12 | 10/16 |
| C2 | 1/8 | 5/6 | 1/8 | 2/8 | 2/8 | 4/8 | 12/14 | 12/16 |
| C3 | 1/8 | 5/6 | 1/8 | 2/6 | 0/6 | 4/8 | 12/14 | 12/16 |

The frozen exact scorer requires equality across event fields before checking the citation. All four arms scored 0/2 by this rule on `river_missing_core`. They restored both actions with supported source quotes, but event summaries differed in punctuation or wording.

## Preliminary source review

The assistant inspected each distinct selected Brief against its Japanese source. Factual support and certainty count distinct selected claims. Coverage counts required gold facts with supporting passage IDs and verbatim source quotes, including the pottery facts. Atomicity counts single-claim character-fact entries. A missing Brief contributes zero required evidence and has no factual, certainty or atomicity denominator. The independent owner grades remain pending. The private review table contains 32 shuffled outputs with opaque IDs, including the retained and missing Briefs. It omits model and configuration identifiers.

| Arm | Supported facts / reviewed | Correct certainty / reviewed | Evidence-covered facts / required | Single-claim character facts / reviewed |
| --- | ---: | ---: | ---: | ---: |
| C0 | 18/18 | 18/18 | 18/18 | 12/12 |
| C1 | 14/14 | 14/14 | 14/18 | 6/7 |
| C2 | 16/16 | 16/16 | 16/18 | 8/9 |
| C3 | 16/16 | 16/16 | 16/18 | 8/9 |

- **Missing Briefs.** C1 missed both hearsay cases. C2 missed `theatre_combined`. C3 missed `market_hearsay`. Factual and certainty ratios are conditional on the content available to review.
- **Atomicity.** On `pottery_atomicity`, C0 split three supported actions into distinct facts. C1 and C2 each rolled back two proposals and retained the compound fact. C3's single soft-warning stop retained the same three-action fact with zero dispatches. All three retained the underlying actions and their evidence.
- **Uncertainty note.** C2 recovered both river actions and their citations but omitted the explicit note that the measured value remains unknown. That omission is visible in the review and excluded that pair from the quality-filtered token comparison.

## Measured token use and timing

The figures include unsuccessful and rolled-back proposals. Groq reported usage for every repair dispatch. Completion includes reasoning, and visible output is estimated by subtracting the reported reasoning count. HTTP latency is wall time around the provider call. Per-arm wall time also includes quota waits and local validation. The table excludes the capacity probe, which used 4,190 tokens separately.

| Arm | Dispatches | Input | Completion | Reasoning | Visible output estimate | Total | HTTP latency | Quota wait | Arm wall time |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C0 | 8 | 26,788 | 5,639 | 2,987 | 2,652 | 32,427 | 19.63 s | 182.67 s | 202.80 s |
| C1 | 11 | 15,849 | 6,148 | 4,401 | 1,747 | 21,997 | 22.13 s | 242.77 s | 265.55 s |
| C2 | 8 | 11,681 | 5,536 | 4,181 | 1,355 | 17,217 | 17.85 s | 61.95 s | 80.27 s |
| C3 | 6 | 10,157 | 4,018 | 2,901 | 1,117 | 14,175 | 14.37 s | 125.49 s | 140.35 s |

Each comparison with C0 had all eight case pairs observed, including the zero-call clean control. Token deltas below are candidate minus C0. An asterisk marks a pair with a missing Brief, compound fact or omitted uncertainty note in the preliminary review.

| Held-back case | C1 − C0 | C2 − C0 | C3 − C0 |
| --- | ---: | ---: | ---: |
| `lighthouse_clean` | 0 | 0 | 0 |
| `bakery_wrapped_text` | +497 | −3,991 | −3,991 |
| `market_hearsay` | −704* | −2,547 | −1,204* |
| `clock_quote` | −2,590 | −2,575 | −2,451 |
| `nursery_participant` | −91 | −14 | 0 |
| `theatre_combined` | −5,933* | −4,670* | −6,214 |
| `pottery_atomicity` | −1,703* | −1,483* | −4,486* |
| `river_missing_core` | +94 | +70* | +94 |

| Arm vs C0 | Reduction over all eight case pairs | Pairs passing preliminary checks on both outputs | Reduction within those pairs |
| --- | ---: | ---: | ---: |
| C1 | 32.16% | 5/8 | 13.27% |
| C2 | 46.91% | 5/8 | 56.78% |
| C3 | 56.29% | 6/8 | 52.96% |

The filtered pairs passed hard validation, source support, certainty, evidence and atomicity checks and retained the relevant uncertainty notes. Their case mixes differ across arms. C0 recovered all six hard-invalid starts and split the pottery fact. Each alternative had a missed repair and retained the compound fact. Candidate selection awaits owner review. M9 r2 stayed paused, and the run used only the pinned Groq Free route.
