# Phase 7 closeout and Phase 7D operations review

26 November 2026 (Asia/Bangkok). Phase 7C experiments are closed by owner decision. The
blinded owner semantic review remains pending. [PR #48](https://github.com/AnhTaizz/AI-storytelling/pull/48) merged at 187cf8a after owner approval and CI. This review uses saved results, read-only
telemetry and offline regressions.

## Quality

| Measurement | Result | Decision |
| --- | --- | --- |
| Wave 1, 10 fixed DEV tasks per Groq model | 20B completed 5/10, mean 0.36 across 5 deterministically scored cases. 120B completed 6/10, mean 0.667 across 6 scored cases. | Keep GPT-OSS 120B as the preferred experimental model. The means are conditional on scored cases. |
| GPT-OSS 120B calibration | The 1,024-token cap yielded JSON on 2/3 previously failing cases. Strict schema at the same cap recovered the third. The two writing rubric scores remain provisional. | Calibration ends with 4 dispatches and zero retries. |
| Brief Repair C0–C3, eight held-back DEV cases | C0 recovered 6/6 hard-invalid starts and covered 18/18 required facts. C1/C2/C3 recovered 4/6, 5/6 and 5/6, and covered 14/18, 16/18 and 16/18 required facts. | Keep C0 for full repair. |
| Brief Repair C0/C4, six new DEV cases | Both recovered 4/4 hard-invalid starts. Whole-Brief exact match was 3/6 vs 4/6. Preliminary required-evidence coverage was 13/14 vs 14/14. Final hard and soft findings were zero in both arms. | Offer exact wrapper normalization as an opt-in. Keep it off by default while owner review is pending. |
| Source Check S0/S1 | Both detected 3/3 defects and each retained one false positive and one wrong defect category. | Keep current Source Check prompts and grouping. |

[Wave 1 plan](MODEL_BENCH_7B_PLAN.md) · [Calibration](PHASE_7_GROQ_120B_CALIBRATION_RESULTS.md) ·
[C0–C3 results](BRIEF_REPAIR_V2_PILOT_RESULTS_20261126.md) · [C0/C4 and S0/S1 evidence](PHASE_7C_FINAL_RESULTS_20261126.md)

## Efficiency, quota and failures

| Scope | Count, tokens and latency |
| --- | --- |
| Wave 1 | Groq baseline p50 was 1.926 s on 20B and 2.127 s on 120B, each across 10 attempts. Baseline checkpoint token totals were unavailable. The three recovered calibration outputs used 3,012 tokens in total, including 1,993 reasoning tokens. The failed calibration call has unknown usage. Wave 1 ledger closed at 27/160. Groq reported 1,000 RPD and 8,000 TPM without 429 during calibration. |
| C0–C3 | Ledger 34/64 including the capacity probe. The four arms used 32,427, 21,997, 17,217 and 14,175 tokens. HTTP times were 19.63, 22.13, 17.85 and 14.37 s. Counts include rejected and rolled-back proposals. |
| C0/C4 | 7 vs 4 dispatches, 28,740 vs 16,903 tokens, and 15.61 vs 10.26 s HTTP. Quota waits were 177.35 vs 121.14 s and depend on order. Ledger closed at 45/64, with zero retries or quota refusals in the extension. |
| S0/S1 | Separate ledger 6/6. Totals were 5,753 vs 5,718 tokens and 6.065 vs 6.376 s HTTP. All six responses omitted the cache counter. |

The observed 41.2% C0/C4 token difference includes several effects. The archive case
establishes the deterministic saving of one full repair, 3,876 tokens and 1.668 s of
that call's HTTP time. The radio case combined normalization and different repair prompt
feedback. Bridge and paper tags had variation on identical first payloads. Groq reported
two 2,560-token cache reads on the C0 paper-tags case. S0/S1 showed no operational cache
benefit. [Final paired measurements](PHASE_7C_FINAL_RESULTS_20261126.md#efficiency-and-attribution)

- The Groq Wave 1 baseline recorded four request failures per model. For the three shared
  format failures, HTTP 400 carried `json_validate_failed`. Cloudflare GLM stopped after one
  malformed response at 25.163 s. Its exact historical HTTP status and usage are unknown.
  A later Cloudflare Analytics access error left current Neurons unknown and blocked the
  supplemental dispatch. OpenRouter Gemma's initial request failed at 1.027 s and its
  supplemental request returned HTTP 400 without a parameter or usage record. Its free
  credit counter stayed at zero and the key reported 50 free requests available before and
  after the supplemental attempt. Neither completed a scored screening case.
- The local Phase 5 SQLite window from 24 November 09:27 UTC to 26 November 04:51 UTC contains
  79 observations across runs. Groq has 63 successes and eight failures, including six
  `json_validate_failed` and two `REQUEST_FAILURE`. Successful Groq rows report 112,052 input,
  36,797 completion and 24,612 reasoning tokens, with recorded latency 918–8,712 ms. Gemini
  has three successes and two `SERVER_FAILURE`, Cloudflare has one success, and OpenRouter
  has one success and one failure. These successes can be from different models or runs
  than Wave 1. Telemetry observations can overlap the experiment ledgers. The quota store
  has zero persisted cooldown rows and two estimated Neuron rows. Reported request headers
  provide the historical provider counter evidence.
- The consolidated read-only dashboard distinguishes reported, estimated and unknown values.
  Run detail separates per-attempt latency from manifest duration, counts validator findings
  and hides raw diagnostics and M9 locked-run detail. Saved result links open allowlisted
  pages in a sandbox over localhost. An offline probe against the saved data returned detail
  for three ordinary runs and status-only records for two locked seasons. Both SQLite files
  retained their pre-read hashes.

[Diagnostics PR #43](https://github.com/AnhTaizz/AI-storytelling/pull/43) ·
[Dashboard guide](../guides/OPS_DASHBOARD.md)

## Existing PRs

| PR | Review finding and disposition |
| --- | --- |
| [#36](https://github.com/AnhTaizz/AI-storytelling/pull/36) | Prioritize data integrity. Schema and semantic validation of memory Briefs and refusal of unreadable manifests are worthwhile. Its 12 season tests passed locally. A separate offline two-episode probe invoked episode 1 and wrote `season.json` before detecting a source mismatch on episode 2. Preflight every existing episode before any run or write. For a legacy manifest missing source versions, require independently established provenance or a fresh output directory. Keep locked M9 on its pinned implementation. |
| [#39](https://github.com/AnhTaizz/AI-storytelling/pull/39) | Preserve the historical owner-approved DEC-043 re-lock. Rebase it as a dated amendment. Refresh its old “generating” status to PAUSED, retain the original pass rule, and record the later content retry as a separate eligibility issue. |
| [#37](https://github.com/AnhTaizz/AI-storytelling/pull/37) and [#44](https://github.com/AnhTaizz/AI-storytelling/pull/44) | Both change the Pipeline cards, reader and server. The consolidated implementation uses one details view and one opaque run reference, retaining #44's call metadata and #37's allowlisted results. Gate locks and bounded reads apply to both routes. The originals can be closed after owner acceptance. |

## M9 r2 decision

**PAUSED. Gate NOT EVALUATED.** The saved lock points to `840b6a45a65367e4e4466bad0bf660547035a664`
and sole model `gemini-3.6-flash`. The recorded lock audit matched the profile,
source manifest, chapters 1–17, episode settings and prompt/schema fingerprints, and
observed no fallback. The current local lock hash matches that audit. Episode 1 (chapters
6–8) generated a 994-word candidate with automated checks passing. Episode 2 (chapters
9–11) stopped in the chapter-10 Brief, and episodes 3–4 have no script. Episode 1
recorded 41 responses, 61 observed provider attempts and 627,918 tokens. Episode 2
recorded 10 responses, 33 observed provider attempts and 124,834 tokens. These historical
observations include transport retries on the pinned pipeline.

The deviation log records one owner-authorized retry after a **hard content validation
failure** during episode 2's Brief. Protocol v0 allows resume after transport interruption.
The content retry requires an explicit ruling on r2's eligibility under the one-attempt
rule. Later attempts reached HTTP 503 and 403. Model and Free quota availability for this
account remain unverified. Resume only if the owner accepts the recorded episode eligibility,
the exact locked checkout and hashes still match, and a separately authorized entitlement
check confirms the exact model can continue on Free. Reuse only r2 artifacts and resume the
existing chapter-10 checkpoint. Keep the launcher paused while those prerequisites are open.

If eligibility fails or the model is unavailable, retain r2 as historical evidence and
submit a fresh protocol for owner approval. Define four non-overlapping unseen episode
ranges before generation. Verify independence from earlier reviews and development. Freeze
the revision, single model, profile, source, thresholds and attempt rule, and use separate
output, memory and blinded review. Screen chapters 18–29 against prior experiments. If any
were seen or used for development, pre-register new ranges from an independent source. The
existing pass rule requires owner reviews of all four, zero FAIL or confirmed CRITICAL
findings, and at least three PASS or PASS_WITH_MINOR_EDITS verdicts. Keep old and new
results separate.
[M9 gate protocol](../research/m9/M9_SCRIPT_QUALITY_GATE_PROTOCOL_V0.md)

## Shortest path to a script for video

1. Start with the saved non-M9 chapter 1 draft. It contains 1,032 words and passed
   output integrity and request compliance. Factual grounding is still `NEEDS_REVIEW`
   because Source Check v2 group 2 encountered transport failures. The saved v2 group 1
checkpoint, Brief and owner review form are available. The older chapter 5
   draft has factual and certainty flags. Prioritize chapter 1.
2. Review chapter 1 against the source and Brief offline. Read it aloud for the hook,
   transitions, spoiler boundary, attribution and uncertainty. Record corrections.
   When separately authorized, complete the missing Source Check and recheck edited
   paragraphs under the approved policy with C0. If the old checkpoint is incompatible,
   generate one episode in a new production directory with the current quality gates.
   Keep this run outside the M9 sample.
3. After the current gates pass and the owner accepts the read-through, hand off the
   final narration, scene beats, pronunciation notes and evidence-backed corrections
   to voice and video production.
