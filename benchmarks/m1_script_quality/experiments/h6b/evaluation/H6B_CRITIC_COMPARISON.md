# H6b Critic Comparison

## Frozen Reference
On this frozen RUN3 reference set, there are a total of 33 robust primary gold issues, spanning 20 units. There is 1 additional QUESTIONABLE issue used for sensitivity analysis, making a total of 34 candidate issues.

## Matching Policy
A prediction matches a gold issue only if it identifies substantially the same material factual/epistemic problem. If a prediction explicitly flags multiple independent atomic assertions correctly, it is mapped to multiple gold issues (counting as detected once for each unique gold issue). 

## Critic V1 Metrics
- **Total Problematic Predictions:** 2
- **TP Robust:** 2
- **FP:** 0
- **Primary Precision:** 1.0000
- **Primary Recall:** 0.0606
- **Primary F1:** 0.1143
- **Unit Recall:** 0.1000

## RUN7 Metrics
- **Total Problematic Predictions:** 9
- **TP Robust:** 9
- **FP:** 0
- **Primary Precision:** 1.0000
- **Primary Recall:** 0.3333
- **Primary F1:** 0.5000
- **Unit Recall:** 0.4000

## Observed Comparison
- **Recall absolute difference:** 0.2727
- **Recall ratio:** 5.5000
- **Precision difference:** 0.0000
- **F1 difference:** 0.3857

RUN7 detected more robust issues than Critic V1. Both achieved 1.0000 primary precision.

## Classification Agreement
For both Critic V1 and RUN7, the exact classification agreement for all matched robust gold issues was 1.0000. 

## False-Negative Counts
- **Critic V1:** 31 missed robust gold issues.
- **RUN7:** 22 missed robust gold issues.

### Missing Detections (RUN7 subset)
RUN7 successfully detected early physical description and immediate situational issues, but systematically missed internal state exaggerations, epistemic overclaims (e.g., Amane *knowing* Mahiru's heavy thoughts), causality inventions, and certainty inflations (e.g., Amane being certain Mahiru will catch a cold or that he will lose sleep).

## False-Positive Counts
- **Critic V1:** 0
- **RUN7:** 0

## Sensitivity Analysis
Including the 1 QUESTIONABLE issue (`G007`) in the gold denominator (N=34):
- **Critic V1 Sensitivity Recall:** 0.0588
- **RUN7 Sensitivity Recall:** 0.3235
Neither critic detected the questionable issue.

## Schema Violation Note and Protocol Limitations
### RUN7 Limitations
- Mechanical unit coverage confirmed at 32/32 units.
- Claim count confirmed at 49 claims.
- Schema conformance is `false`. One invalid claim type (`OBSERVATION`, id: `C025`) was produced, which is invalid under Prompt V3. 
- Strict machine context isolation is `NOT_VERIFIABLE`.
- Results are from one real semantic primary attempt with no quality-based regeneration.

### Critic V1 Limitations
- Critic V1 was not deterministic claim-by-claim. It produced a small free-form violation set.
- Strict machine context isolation was not independently enforced.
- It was part of the H6 critic + revision experiment. This comparison evaluates useful detection coverage, not identical output format.

## H6b Hypothesis Verdict
**PENDING_ORCHESTRATOR_REVIEW**
