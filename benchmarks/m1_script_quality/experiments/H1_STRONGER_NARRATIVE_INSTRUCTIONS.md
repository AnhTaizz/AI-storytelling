# H1 — Stronger Narrative Instructions

Status:
EVALUATED

Evidence:
RUN_0001_BASELINE_A vs RUN_0002_H1_PROMPT_V2

Hypothesis:
Stronger narrative instructions can improve creator-oriented storytelling quality without adding architectural complexity.

Result:
Strong narrative prompting improved narrative transformation in the observed experiment, but did not reliably enforce factual fidelity or output integrity.

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
- Introduced an `OBSERVED_ENTERTAINMENT_FIDELITY_TENSION` where increased dramatic flair coincided with slight spoilers or over-interpretations of the ending.

Verdict:
PARTIALLY_SUPPORTED
Strong narrative prompting is a valuable low-cost improvement and should remain part of the system, but it cannot by itself reliably enforce factual truth and output integrity.

Next implication:
The `OBSERVED_ENTERTAINMENT_FIDELITY_TENSION` justifies exploring H2 (Separate Story Brief) to TEST whether a separate factual stage can better separate "what is true" from "how to tell it". The persistent language corruption justifies exploring H5 (Output Validator) to flag mechanical violations.
