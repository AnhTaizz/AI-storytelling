# Pull request review

The owner or a separate agent can review. Start from the task and the base-to-head diff. Record the revision reviewed. Use only applicable questions. A prose correction usually needs a read of the diff, its referenced sources and the gate results.

| Area | Review questions |
| --- | --- |
| Task and architecture | Does the change meet each agreed criterion? Does it belong in this module? Check accepted decisions, freeze records, benchmark history and any required owner authorization. Does the canonical layer remain independent of adapters and storage? What requirement justifies each new abstraction? |
| Code and regressions | Trace inputs through the real caller, outputs and errors. Check interface stability, deterministic behavior where required, dependencies, retry or partial failure where applicable, and whether another maintainer can follow the change. |
| Tests | Inspect existing and changed tests. Are fixtures reused, new behavior and meaningful edge cases covered, and prior assertions intact? For bug fixes, what demonstrates the old failure? Check actual commands, failures, skips, environment gates and the changed-line coverage report. |
| Data and story quality | Use the [invariants](STORY_SEMANTIC_INVARIANTS.md). Trace a changed claim to in-scope source evidence. Check causality, event order, knowledge at the cutoff, omissions, unsupported motives and editorial effects. Does the claim need a human reading or listening trial? |
| Evidence and privacy | Inspect the diff and the test output, reproduce material claims where feasible, and check scope, limitations and private-data handling. For research, verify the split, protocol version and prediction lock supporting the conclusion. |

### Review outcome

Record reviewer, commit, evidence checked, findings with locations and one outcome. Use **APPROVE** when the reviewed diff satisfies the agreed criteria, **REQUEST_CHANGES** for a concrete defect or missing evidence, or **NEEDS_HUMAN_DECISION** when scope, a contract or a product judgment needs owner authority. Identify the owner decision or the smallest verifiable correction.

For a finding, describe the observed behavior, impact and expected behavior. Recheck affected findings after revisions. Until someone other than the implementer has reviewed, record *independent review pending*. An AI review is advisory. The owner controls merge and the frozen script contract assigns its official semantic verdict to a human audit.
