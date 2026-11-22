# Task specification and Definition of Done

Fill this into the issue, task or PR before meaningful implementation. Resolve any uncertainty that changes the permitted scope or acceptance test with the owner.

| Field | Fill in |
| --- | --- |
| ID, objective, milestone | Task reference, observable result and relevant roadmap capability. |
| Authority | Accepted decision IDs, contract versions, research locks and any specific owner authorization. |
| Scope | Modules and behaviors allowed to change. Name adjacent components, contracts and data excluded from the task. |
| Inputs and outputs | Entry point, input and version, expected output or error, callers that rely on it. |
| Acceptance criteria | For each criterion, specify the input, the observable result and how to verify it. |
| Required tests | Existing suite, fixture and cases to reuse, new behavior or regression to demonstrate, applicable gates. |
| Data and evidence | Public fixture or synthetic example, provenance and spoiler boundary where relevant. Identify private/gated inputs and how to report results safely. |
| Risks and limits | Likely regressions, remaining uncertainty, owner decisions and any manual evaluation needed. |

**Short form for a small fix.** Record the task reference and objective, allowed change, expected result and verification in a few lines. Name any affected contract, data restriction or material risk. A larger redesign needs a separate scope decision.

### Definition of Done

- [ ] Demonstrate the requested behavior against each acceptance criterion at its normal entrypoint. Explain the evidence for a documentation-only change.
- [ ] Confirm the diff stays in scope and respects accepted architecture. Link the specific owner authorization for any change to a frozen contract.
- [ ] Relevant tests and appropriate quality gates pass. Existing tests retain their assertions and coverage. List skipped/gated checks and what remains unverified.
- [ ] Update relevant documentation and summarize observable changes, risks and unresolved limitations.
- [ ] Record the review and CI state accurately. A green CI check establishes only the checks it ran. Claims about story fidelity or listener experience need the evidence specified for that task.
