# H2 — Separate Story Brief

Status:
EVALUATED

Hypothesis:
Separating factual story understanding from creative storytelling may reduce factual/interpretive drift while preserving the narrative improvements observed in PROMPT_V2.

Evidence:
RUN_0003_H2_STORY_BRIEF vs RUN_0002_H1_PROMPT_V2

Story Brief result:
Successfully extracted a comparatively strong factual boundary in this run. Preserved `UNKNOWN` motives, physical scene states, and exact visual details (flaxen hair). Weakness: flattened hearsay into explicit facts and lost some epistemic distinctions.

Script result:
Improved specific fidelity markers (hair color, ending subtlety) but severely failed the compression contract (1648 words) and introduced new interpretive drift (exaggerated internal monologue).

Benefits:
- Restored hair color fidelity.
- Preserved physical scene state (sitting on swing).
- Ended with subtle implication rather than explicit future prediction.

Remaining failures:
- Writer adherence failure: The Script Writer invented elaborations not present in the Story Brief.

Regressions:
- Major length regression (1648 words vs 900-1100 target).
- Pacing became padded and slow.

Verdict:
PARTIALLY_SUPPORTED

Architecture implication:
A separate factual representation is empirically useful for establishing truth, but it is insufficient to constrain a creative Writer stage. The failure layers are distinct. Current evidence supports continuing to explore an explicit truth boundary, likely requiring enforcement.

Next hypothesis:
H6 — Factual Script Critic / Validation Loop (to test whether a post-generation factual critic can detect and/or reduce Writer deviations from the Story Brief)
