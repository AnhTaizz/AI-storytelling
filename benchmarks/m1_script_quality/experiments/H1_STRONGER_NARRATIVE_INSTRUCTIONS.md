# H1 — Stronger Narrative Instructions

Status:
EVALUATED

Evidence:
RUN_0001_BASELINE_A vs RUN_0002_H1_PROMPT_V2

Hypothesis:
Stronger narrative instructions can improve creator-oriented storytelling quality without adding architectural complexity.

Result:
Strong narrative prompting successfully reshaped the narrative structure, improved the hook, and achieved a more engaging conversational style. However, it introduced a tradeoff by increasing factual drift and creative exaggeration. Furthermore, it failed to prevent output language corruption.

Supported improvements:
- Time to inciting situation / Pacing (F004)
- Source-order retelling broken via a narrative hook (F005)
- Humor and conversational style (F007)
- Mechanical word count compliance

Remaining failures:
- Output language corruption (Cyrillic token generation) (F003)
- Unsupported inventions and exaggerations (F001)

Regressions:
- Fidelity regression (hair color changed from flaxen to chestnut)
- Introduced an `ENTERTAINMENT_FIDELITY_TRADEOFF` where increased dramatic flair led to slight spoilers or over-interpretations of the ending.

Verdict:
PARTIALLY_SUPPORTED
Strong narrative prompting is a valuable low-cost improvement and should remain part of the system, but it cannot by itself reliably enforce factual truth and output integrity.

Next implication:
The `ENTERTAINMENT_FIDELITY_TRADEOFF` justifies exploring H2 (Separate Story Brief) to separate "what is true" from "how to tell it". The persistent language corruption justifies exploring H5 (Output Validator).
