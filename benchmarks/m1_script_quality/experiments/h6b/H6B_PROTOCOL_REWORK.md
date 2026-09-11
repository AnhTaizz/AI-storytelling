# H6B Protocol Rework (RUN_0006)

## Why RUN_0005 is Protocol-Incomplete
RUN_0005 allowed the Critic to control its own input segmentation, leading to it selecting only 14 regions of a 1648-word script. Full script coverage could not be proven mechanically. In addition, the Prompt V2 asked for YAML inside Markdown fences but also asked for "valid YAML only", causing a contradiction resulting in unparseable raw output.

## What is Preserved Unchanged
RUN_0005 and all its artifacts are preserved unchanged as historical evidence of the protocol failure. The hypothesis, the base Writer Script (RUN_0003), and the Story Brief remain the same.

## What V3 Changes
Prompt V3 removes model-controlled segmentation and replaces it with deterministic paragraph-level segmentation generated prior to invocation. V3 mandates that every input review unit must appear exactly once in the output, preventing silent omission. It strictly enforces outputting raw YAML without Markdown fences.

## What V3 Does NOT Change
V3 does not change the research hypothesis, the classification enums, the severity enums, or the action enums. It does not alter the underlying claim schema apart from mapping it to the mechanical unit structure.

## Why Deterministic Segmentation Matters
Without deterministic segmentation, the Critic can silently skip hard or long passages without detection. A deterministic map enables 1:1 mechanical validation of coverage.

## Why Mechanical Coverage != Semantic Recall
Proving that every paragraph was reviewed (mechanical coverage) does not prove that every factual error was found (semantic recall). A model might output a generic claim for every paragraph but still miss critical narrative drift.

## Why RUN_0006 is a Rerun rather than a Mutation
Modifying RUN_0005's artifacts would destroy the historical evidence of its failure modes. Running a fresh invocation (RUN_0006) allows independent assessment of the corrected methodology while preserving the earlier attempt.
