# H7 Stage A Exploratory Analysis

## Purpose
This Stage A analysis evaluated the semantic performance of the frozen H7 prediction union on the exploratory development set (`H6B_RUN3_REFERENCE_V1`). The goal was to determine if the H7 targeted prompt could improve robust recall and F1 without degrading precision.

## Baseline Metrics (RUN7)
* **Prediction Count:** 9
* **Precision:** 1.0000
* **Robust Recall:** 0.3333
* **F1 Score:** 0.5000

## H7 Final Union Metrics
* **Prediction Count:** 12
* **Precision:** 1.0000
* **Robust Recall:** 0.4242
* **F1 Score:** 0.5957

## Targeted Contribution
The targeted pass yielded 5 raw predictions, with 2 deduplicated to baseline predictions and 3 uniquely retained in the final union.
The H7 union detected **3 new robust gold issues** not found by the baseline:
* G006
* G008
* G024

## Semantic Signal Direction
The semantic direction is highly favorable. Robust recall increased by +0.0909 and F1 increased by +0.0957, with zero precision degradation (0.0000). H7 successfully detected complex robust gold issues without introducing any false positives.

## Protocol Status
**IMPORTANT**: While the semantic signal is strong, RUN_0009 failed the strictly frozen raw-YAML-only output contract by wrapping its payload in Markdown fencing. It retains its mechanical status of `PAYLOAD_VALID_BUT_RAW_FORMAT_INVALID`.

## Conclusion and Next Steps
This constitutes development-set evidence only. The H7 confirmatory verdict remains `NOT_EVALUATED`. 
Because the semantic performance was favorable but a raw-format protocol violation exists, Stage B cannot be authorized yet. 
The necessary next step is to decide the minimal pre-Stage-B protocol/prompt correction required to make the H7 targeted output fully frozen-contract compliant, without expanding H7's semantic scope.
