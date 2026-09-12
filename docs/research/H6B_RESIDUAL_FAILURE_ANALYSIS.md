# H6b Residual Failure Analysis

## Purpose
Analyze the 22 robust false negatives systematically missed by RUN7 to identify semantic failure families, rigorously classify them, and design the next minimal validation experiment.

## Full 22-Issue Residual Inventory

| Issue ID | Unit | Claim Type | Gold Class | Severity | Normalized Issue | Primary Failure Family | Rationale |
|---|---|---|---|---|---|---|---|
| `G006` | `P006` | `INTERNAL_THOUGHT` | `UNSUPPORTED` | `LOW` | Amane only considers Mahiru as a piece of art to admire from afar. | `MOTIVE_OR_INTERNAL_STATE_INVENTION` | Invents an absolute limit/motive on Amane's feelings. |
| `G008` | `P011` | `INTENTION` | `STRONGER_THAN_BRIEF` | `MEDIUM` | Mahiru has no intention of finding shelter. | `HIDDEN_INTENTION_INFERENCE` | Infers hidden intention (no intention to find shelter). |
| `G009` | `P011` | `EMOTIONAL_STATE` | `STRONGER_THAN_BRIEF` | `LOW` | Mahiru looks with lifeless/soulless eyes. | `PHYSICAL_OR_EMOTIONAL_STATE_INVENTION` | Invents physical/emotional state (lifeless eyes). |
| `G011` | `P012` | `CERTAINTY_LEVEL` | `STRONGER_THAN_BRIEF` | `MEDIUM` | Amane is certain Mahiru will catch a cold. | `CERTAINTY_INFLATION` | Asserts absolute certainty (Amane is certain) rather than expectation. |
| `G012` | `P013` | `INTERNAL_THOUGHT` | `UNSUPPORTED` | `MEDIUM` | Amane assumes Mahiru wants to stay/get soaked in the rain. | `HIDDEN_INTENTION_INFERENCE` | Infers Mahiru wants to stay soaked (hidden intention). |
| `G013` | `P014` | `ACTION` | `UNSUPPORTED` | `LOW` | Amane scratches his head and pulls his ears in frustration. | `UNSUPPORTED_ACTION_OR_STAGING` | Invents specific physical staging (pulls ears). |
| `G014` | `P014` | `CERTAINTY_LEVEL` | `STRONGER_THAN_BRIEF` | `MEDIUM` | Amane is certain he will lose sleep tonight out of guilt. | `CERTAINTY_INFLATION` | Asserts absolute certainty regarding future sleep loss. |
| `G016` | `P017` | `EMOTIONAL_STATE` | `UNSUPPORTED` | `LOW` | Mahiru startles. | `UNSUPPORTED_ACTION_OR_STAGING` | Invents physical reaction (startles). |
| `G020` | `P020` | `REPUTATION_OR_HEARSAY` | `STRONGER_THAN_BRIEF` | `LOW` | Mahiru is always bothered by boys. | `REPUTATION_OR_FREQUENCY_STRENGTHENING` | Strengthens frequency (always). |
| `G021` | `P020` | `CAUSALITY` | `UNSUPPORTED` | `MEDIUM` | Mahiru's wariness is a natural consequence of frequently being bothered by boys. | `CAUSALITY_INVENTION` | Invents causality (natural consequence). |
| `G023` | `P021` | `ACTION` | `UNSUPPORTED` | `LOW` | Amane shrugs. | `UNSUPPORTED_ACTION_OR_STAGING` | Invents physical action (shrugs). |
| `G024` | `P024` | `KNOWLEDGE_STATE` | `UNSUPPORTED` | `HIGH` | Amane knows Mahiru has something heavy on her mind. | `EPISTEMIC_KNOWLEDGE_OVERCLAIM` | Amane is asserted to know something internal to Mahiru, overclaiming his epistemic bounds. |
| `G025` | `P025` | `CHARACTER_ATTRIBUTE` | `UNSUPPORTED` | `MEDIUM` | Amane is inherently someone who fears trouble. | `MOTIVE_OR_INTERNAL_STATE_INVENTION` | Invents an inherent trait/motive regarding fear of trouble. |
| `G026` | `P025` | `INTERNAL_THOUGHT` | `UNSUPPORTED` | `LOW` | Amane's conscience only compelled him to ask a single question as its maximum limit. | `MOTIVE_OR_INTERNAL_STATE_INVENTION` | Invents a strict limit on his conscience. |
| `G027` | `P025` | `EMOTIONAL_STATE` | `UNSUPPORTED` | `MEDIUM` | Amane can leave completely free of guilt after asking his question. | `MOTIVE_OR_INTERNAL_STATE_INVENTION` | Invents absolute freedom from guilt. |
| `G028` | `P026` | `PHYSICAL_STATE` | `UNSUPPORTED` | `LOW` | Mahiru is sitting huddled/curled up. | `UNSUPPORTED_ACTION_OR_STAGING` | Invents specific posture (curled up). |
| `G029` | `P027` | `CERTAINTY_LEVEL` | `STRONGER_THAN_BRIEF` | `MEDIUM` | Amane is certain she will get sick if she stays like this. | `CERTAINTY_INFLATION` | Asserts absolute certainty regarding future sickness. |
| `G030` | `P028` | `ACTION` | `UNSUPPORTED` | `LOW` | Amane leaves before Mahiru can open her mouth to object. | `UNSUPPORTED_ACTION_OR_STAGING` | Invents sequence/staging (before she can object). |
| `G031` | `P029` | `INTERNAL_THOUGHT` | `UNSUPPORTED` | `LOW` | Amane doesn't care what Mahiru says. | `MOTIVE_OR_INTERNAL_STATE_INVENTION` | Invents a lack of care as an internal state. |
| `G032` | `P030` | `INTERNAL_THOUGHT` | `UNSUPPORTED` | `LOW` | Amane believes he has done his best/utmost. | `MOTIVE_OR_INTERNAL_STATE_INVENTION` | Invents an internal belief about doing his best. |
| `G033` | `P030` | `EMOTIONAL_STATE` | `STRONGER_THAN_BRIEF` | `MEDIUM` | Giving the umbrella completely washed away all his guilt/troubled conscience. | `MOTIVE_OR_INTERNAL_STATE_INVENTION` | Invents the total washing away of guilt. |
| `G034` | `P031` | `INTENTION` | `UNSUPPORTED` | `MEDIUM` | Amane believes Mahiru generally does not want anything to do with him. | `HIDDEN_INTENTION_INFERENCE` | Infers Mahiru's general intentions toward Amane. |

## Ranked Failure Families

### MOTIVE_OR_INTERNAL_STATE_INVENTION
- **Count:** 7 misses
- **Severity Profile:** {"LOW": 4, "MEDIUM": 3}
- **Affected Units:** P006, P025, P029, P030

### UNSUPPORTED_ACTION_OR_STAGING
- **Count:** 5 misses
- **Severity Profile:** {"LOW": 5}
- **Affected Units:** P014, P017, P021, P026, P028

### CERTAINTY_INFLATION
- **Count:** 3 misses
- **Severity Profile:** {"MEDIUM": 3}
- **Affected Units:** P012, P014, P027

### HIDDEN_INTENTION_INFERENCE
- **Count:** 3 misses
- **Severity Profile:** {"MEDIUM": 3}
- **Affected Units:** P011, P013, P031

### EPISTEMIC_KNOWLEDGE_OVERCLAIM
- **Count:** 1 misses
- **Severity Profile:** {"HIGH": 1}
- **Affected Units:** P024

### CAUSALITY_INVENTION
- **Count:** 1 misses
- **Severity Profile:** {"MEDIUM": 1}
- **Affected Units:** P020

### PHYSICAL_OR_EMOTIONAL_STATE_INVENTION
- **Count:** 1 misses
- **Severity Profile:** {"LOW": 1}
- **Affected Units:** P011

### REPUTATION_OR_FREQUENCY_STRENGTHENING
- **Count:** 1 misses
- **Severity Profile:** {"LOW": 1}
- **Affected Units:** P020

## Candidate Interventions Comparison

### A. Explicit Motive/Internal State Audit Pass
- **Targeted Families:** MOTIVE_OR_INTERNAL_STATE_INVENTION
- **Exact Target IDs:** G006, G025, G026, G027, G031, G032, G033
- **Target Count:** 7 misses
- **Severity Profile:** 3 MEDIUM, 4 LOW
- **Affected Units:** P006, P025, P029, P030
- **Working Hypothesis:** The generic audit might insufficiently foreground internal-state verification, treating it as harmless creative narration.
- **Procedure Delta:** A targeted secondary pass focused on claims involving motives or internal feelings.
- **Relative Cost:** TARGETED_SECOND_PASS (Moderate API/token addition).
- **False Positive Risk:** Moderate. Risk of flagging benign internal transitions.
- **Confound Risk:** Low.
- **Architecture Change:** NO.
- **Expected Failure Mode:** Might ignore high-severity epistemic/certainty assertions.

### B. Epistemic, Intent, and Certainty Audit Pass
- **Targeted Families:** CERTAINTY_INFLATION, HIDDEN_INTENTION_INFERENCE, EPISTEMIC_KNOWLEDGE_OVERCLAIM
- **Exact Target IDs:** G011, G014, G029, G008, G012, G034, G024
- **Target Count:** 7 misses
- **Severity Profile:** 1 HIGH, 6 MEDIUM
- **Affected Units:** P011, P012, P013, P014, P024, P027, P031
- **Working Hypothesis:** LLMs may struggle to distinguish boundaries between reasonable expectation ('think') and absolute certainty ('know'). An explicit logical framing checklist may correct this.
- **Procedure Delta:** A targeted secondary pass focused specifically on words/claims asserting absolute certainty, knowing the unknowable, or deducing hidden intent.
- **Relative Cost:** TARGETED_SECOND_PASS (Moderate API/token addition).
- **False Positive Risk:** Moderate to High. Difficult prompt engineering required to avoid over-flagging.
- **Confound Risk:** Low.
- **Architecture Change:** NO.
- **Expected Failure Mode:** High FP rate if the LLM cannot parse nuance.

### C. Unsupported Action/Staging Checklist
- **Targeted Families:** UNSUPPORTED_ACTION_OR_STAGING
- **Exact Target IDs:** G013, G016, G023, G028, G030
- **Target Count:** 5 misses
- **Severity Profile:** 5 LOW
- **Affected Units:** P014, P017, P021, P026, P028
- **Working Hypothesis:** The LLM's `CREATIVE_BUT_SAFE` tolerance currently accepts unwritten minor physical movements.
- **Procedure Delta:** A secondary pass evaluating physical action.
- **Relative Cost:** TARGETED_SECOND_PASS.
- **False Positive Risk:** Extremely High.
- **Confound Risk:** High.
- **Architecture Change:** NO.
- **Expected Failure Mode:** Floods output with minor physical blocking flags, destroying precision.

## A-vs-B Trade-Off Evaluation
Candidate A (Internal State) targets the single largest homogenous family (7 misses). Candidate B (Epistemic/Certainty) targets a composite of three closely related epistemic failure mechanisms, also covering 7 misses, but with a significantly higher severity profile (1 HIGH, 6 MEDIUM vs 3 MEDIUM, 4 LOW). Candidate B represents a more critical risk class for factual integrity (e.g., asserting a character knows a secret). However, Candidate B is much harder to engineer as one coherent pass without severe false positives.

## Recommended Next Intervention
- **Name:** Epistemic, Intent, and Certainty Audit Pass
- **Target IDs:** G011, G014, G029, G008, G012, G034, G024
- **Target Count:** 7 misses
- **Severity Profile:** 1 HIGH, 6 MEDIUM
- **Why Selected:** Although Candidate A is a single neat category, Candidate B targets the same volume of misses but with vastly higher severity. Resolving epistemic overclaim is a higher-value architectural milestone for safety than policing internal monologues. It remains achievable as a targeted secondary pass without requiring Graph/RAG.
