# H6b Residual Failure Analysis

## Purpose
Analyze the 22 robust false negatives systematically missed by RUN7 to identify semantic failure families and design the next minimal validation experiment.

## Residual False Negatives Taxonomy

### MOTIVE_OR_INTERNAL_STATE_INVENTION (7 misses, 31.82%)
- **Severities:** {"LOW": 4, "MEDIUM": 3}
- **Affected Units:** P006, P025, P029, P030
- **Issue IDs:** G006, G025, G026, G027, G031, G032, G033

### UNSUPPORTED_ACTION_OR_STAGING (5 misses, 22.73%)
- **Severities:** {"LOW": 5}
- **Affected Units:** P014, P017, P021, P026, P028
- **Issue IDs:** G013, G016, G023, G028, G030

### CERTAINTY_INFLATION (3 misses, 13.64%)
- **Severities:** {"MEDIUM": 3}
- **Affected Units:** P012, P014, P027
- **Issue IDs:** G011, G014, G029

### HIDDEN_INTENTION_INFERENCE (3 misses, 13.64%)
- **Severities:** {"MEDIUM": 3}
- **Affected Units:** P011, P013, P031
- **Issue IDs:** G008, G012, G034

### EPISTEMIC_KNOWLEDGE_OVERCLAIM (1 misses, 4.55%)
- **Severities:** {"HIGH": 1}
- **Affected Units:** P024
- **Issue IDs:** G024

### CAUSALITY_INVENTION (1 misses, 4.55%)
- **Severities:** {"MEDIUM": 1}
- **Affected Units:** P020
- **Issue IDs:** G021

### PHYSICAL_OR_EMOTIONAL_STATE_INVENTION (1 misses, 4.55%)
- **Severities:** {"LOW": 1}
- **Affected Units:** P011
- **Issue IDs:** G009

### REPUTATION_OR_FREQUENCY_STRENGTHENING (1 misses, 4.55%)
- **Severities:** {"LOW": 1}
- **Affected Units:** P020
- **Issue IDs:** G020

## Candidate Interventions

### 1. Explicit Motive/Internal State Audit Pass
- **Targeted Family:** MOTIVE_OR_INTERNAL_STATE_INVENTION (Largest cluster: 7 misses)
- **Why RUN7 missed it:** Current prompt audits 'claims' generally, which often biases LLMs toward physical facts or explicit dialogue. Nuanced internal monologue or limit-setting (e.g., 'maximum limit of his conscience') slips through if the LLM considers it 'creative narration' rather than a hard factual claim.
- **Expected Benefit:** Direct reduction in the largest semantic hallucination category in this dataset.
- **Added Complexity:** One additional deterministic LLM pass specifically querying whether the brief explicitly supports the character's internal motives/beliefs in each paragraph.
- **Risk / Cost:** Mildly increased prompt cost; risk of over-flagging safe internal monologue.
- **Requires Architecture Change:** No.

### 2. Unsupported Action/Staging Checklist
- **Targeted Family:** UNSUPPORTED_ACTION_OR_STAGING (5 misses)
- **Why RUN7 missed it:** Harmless-seeming staging elements (shrugging, sitting curled up, pulling ears) are often accepted as safe creative elements under the `CREATIVE_BUT_SAFE` policy by the LLM unless specifically warned about staging additions.
- **Expected Benefit:** Better alignment with strict screenplay staging fidelity.
- **Added Complexity:** Checklist item added to the existing prompt or a secondary pass for physical staging.
- **Risk / Cost:** Very high risk of false positives, as minor blocking (e.g., turning around) is usually safely implied.
- **Requires Architecture Change:** No.

### 3. Epistemic and Certainty Pass (Hidden Intent / Knowledge / Certainty)
- **Targeted Family:** CERTAINTY_INFLATION, HIDDEN_INTENTION_INFERENCE, EPISTEMIC_KNOWLEDGE_OVERCLAIM (7 misses combined)
- **Why RUN7 missed it:** LLMs struggle to distinguish between 'Amane thought she might be sad' and 'Amane knows she has something heavy on her mind'. Epistemic boundaries require specific logical framing to evaluate.
- **Expected Benefit:** Captures highest-severity structural inference errors.
- **Added Complexity:** A secondary audit pass focused purely on epistemic bounds and certainty qualifiers.
- **Risk / Cost:** High prompt design complexity; medium false positive risk.
- **Requires Architecture Change:** No.

## Recommended Next Intervention

- **Name:** Explicit Motive/Internal State Audit Pass
- **Targeted Failure Family:** MOTIVE_OR_INTERNAL_STATE_INVENTION
- **Why this is the smallest justified intervention:** It directly addresses the largest coherent cluster of false negatives (7 misses, >31% of all residual errors). It requires no new infrastructure, retrieval, or graph memory—only an additional deterministic prompt iteration scoped to internal states.
