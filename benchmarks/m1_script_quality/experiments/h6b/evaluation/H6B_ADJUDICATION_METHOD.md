# H6b Adjudication Methodology

This candidate ground-truth reference set for the H6b factual critic evaluation was independently constructed using the following methodology:

- **Truth Boundary:** The frozen Story Brief (`RUN_0003_H2_STORY_BRIEF/story_brief.yaml`) acts as the absolute truth boundary.
- **Raw Source Excluded:** The original Japanese light novel source was deliberately excluded to isolate the evaluation to Story Brief adherence.
- **Segmentation:** Evaluation was performed deterministically on units `P001` through `P032` (PARAGRAPH_V1).
- **Atomic Issues:** Each candidate issue represents one atomic factual or epistemic problem. Multiple independent problems within a single sentence are separated.
- **Safe Creativity Rule:** Stylistic flourishes, humor, and rhetorical devices that do not alter material story truth, motivation, knowledge, or physical state are considered CREATIVE_BUT_SAFE and are excluded from the problem inventory.
- **Knowledge/Certainty Rule:** A character appearing a certain way does not grant another character factual knowledge. Possibility or risk is not treated as certainty.
- **Status:** This is currently a `CANDIDATE_PENDING_ORCHESTRATOR_REVIEW`.
- **No Critic Evidence:** The outputs from Critic V1 (RUN_0004), RUN_0005, RUN_0006, and RUN_0007 were NOT used to build this inventory. Comparison is deferred until after Orchestrator approval.

**Note:** The adjudication is model-assisted and will not become final gold until independently reviewed and accepted by the Orchestrator.
