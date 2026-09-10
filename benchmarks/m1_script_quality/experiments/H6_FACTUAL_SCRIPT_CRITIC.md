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
Critic V1 detected the two explicit high-impact internal-state deviations recorded in its report and correctly diagnosed compression problems. Independent review also found several meaningful original-script deviations that Critic V1 did not flag, including unsupported/questionable staging actions, physical-state embellishment, certainty strengthening around catching cold, and unsupported guilt-resolution logic.

Revision result:
The revision removed or reduced the two Critic-flagged deviations and achieved the recorded 1074-word target-compliant output. No obvious severe narrative degradation was observed in the research review, while final creator preference remains pending Project Owner review.

Benefits:
- Targeted high-impact Writer drift was removed or reduced.
- Target-length compliance was restored.
- Creator-oriented narrative elements remained observable.

Misses:
- Sparse Critic coverage left minor factual drift untouched.

Regressions / revision risks:
- At least one minor revision-introduced physical detail was observed ("khu công viên nhỏ").
- The revision may also narrow an ambiguous time context ("放課後または夕方" → "sau giờ học").
- These were minor in this run but show that the Revision stage can itself introduce drift.

Verdict:
PARTIALLY_SUPPORTED. The validation loop showed useful effects on targeted Writer deviations and compression in this run, but Critic coverage was incomplete and Revision itself introduced minor drift.

Architecture implication:
Story Brief remains useful as a declared factual reference. Semantic Critic shows experimental utility. Critic V1 is not production-ready. One-pass Revision is not production-ready. H6b is motivated for another controlled experiment.

Next hypothesis:
H6b — Claim-Level Factual Critic (Testing whether explicit claim enumeration improves detection coverage).
