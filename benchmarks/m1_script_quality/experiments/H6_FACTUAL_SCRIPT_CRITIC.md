# H6 — Factual Script Critic / Validation Loop

Status:
EVALUATED

Hypothesis:
A post-generation critic using the Story Brief as the declared factual boundary may detect Writer deviations and, when its findings are supplied to a controlled revision stage, may reduce those deviations without unacceptable narrative degradation.

Evidence:
- `benchmarks/m1_script_quality/runs/RUN_0004_H6_CRITIC/critic_report.yaml`
- `benchmarks/m1_script_quality/runs/RUN_0004_H6_CRITIC/revised_script.md`
- Compared against `RUN_0003_H2_STORY_BRIEF` inputs.

Critic result:
Detected major internal state deviations (Amane's sense of inferiority, excessive guilt) and diagnosed structural compression needs accurately. However, it missed several smaller factual and staging deviations (e.g., park size, character actions).

Revision result:
Successfully removed or softened the detected deviations without narrative degradation. The script was compressed from the canonical recorded 1648 words to 1074 words, meeting the target length while retaining strong pacing and emotional flow.

Benefits:
- Resolved the most jarring invented internal states.
- Reached the required word count.
- Maintained natural narrative quality.

Misses:
- Sparse Critic coverage left minor factual drift untouched.

Regressions / revision risks:
- At least one minor revision-introduced physical detail was observed ("khu công viên nhỏ").
- The revision may also narrow an ambiguous time context ("放課後または夕方" → "sau giờ học").
- These were minor in this run but show that the Revision stage can itself introduce drift.

Verdict:
PARTIALLY_SUPPORTED. The validation loop works well for major thematic issues and compression, but current Critic prompts lack comprehensive claim coverage.

Architecture implication:
The validation loop structure is promising. The Story Brief works well as a reference. However, the Critic stage requires more rigorous extraction mechanics to be production-ready.

Next hypothesis:
H6b — Claim-Level Factual Critic (Testing whether explicit claim enumeration improves detection coverage).
