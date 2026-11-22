# Shared coding-agent workflow

[Claude's repository rules](../../CLAUDE.md) apply throughout. The steps below are required for implementation tasks. A small fix can use the short form in the [task specification](TASK_SPEC_TEMPLATE.md). Keep the record in the task or PR.

| Step | What to do | Evidence to keep |
| --- | --- | --- |
| 1. Intake | Identify the requested user-visible outcome, milestone, permitted scope and acceptance criteria. Clarify a material ambiguity before acting on it. | Agreed task or short form. |
| 2. Reconnaissance | Read [Project State](../PROJECT_STATE.md), including the current header and latest relevant entry. Fetch the default branch, check status, recent changes and overlapping open PRs. Use a dedicated branch from current main and preserve unrelated work. | Base revision, affected modules, existing work to reuse. |
| 3. Contracts | Read relevant [decisions](../DECISIONS.md), [principles](../ARCHITECTURAL_PRINCIPLES.md), [roadmap](../ROADMAP.md), schemas and [protected paths](../../tools/ci/policy/protected_paths.txt). The [target architecture](../TARGET_ARCHITECTURE.md) describes candidates. Read the [semantic invariants](STORY_SEMANTIC_INVARIANTS.md) for affected story stages. | Decision IDs, frozen versions, research locks, scope boundaries. |
| 4. Plan | Trace the existing entrypoint, callers and outputs. Choose the smallest compatible change. Explain any new dependency or abstraction by the requirement it serves. | Intended change and likely regressions. |
| 5. Test design | Search the [test catalog](../../tests/TEST_CATALOG.md), reuse the suite and fixtures, and specify how to observe the requested result. For a regression, reproduce the original failure where feasible. | Existing test or new case, inputs and expected outputs. |
| 6. Implement | Change only the agreed behavior. Preserve evidence, interface compatibility and test strength. Regenerate the catalog after test changes with `python -m tools.ci.test_policy --write-catalog`. | Reviewable diff and relevant documentation. |
| 7. Verify | Run targeted suites during development and both [quality gates](QUALITY_GATES.md) before committing. Run the coverage gate again on the committed branch for changes to tools. Run strict when its declared inputs are available. For docs, resolve links and check commands against their entrypoints. | Exact commands, base, results, skipped/gated checks and acceptance evidence. |
| 8. Review | Give the task, diff and evidence to a separate reviewer or the owner. Use the [review checklist](PR_REVIEW_CHECKLIST.md). If no reviewer is available, open the PR with review pending. | Actual reviewer, revision, findings and outcome when available. |
| 9. Submit | Inspect the staged paths and diff for private material. Push only the feature branch, open the PR against main, link overlapping work and report CI status. | PR with summary, scope, tests, risks and outstanding decisions. |
| 10. Close | Resolve findings within scope, rerun affected checks and submit the revised diff for review. The owner decides acceptance and merge. Record limitations alongside the outcome. | Final revision, checks and owner disposition. |

### Authority

Agents may choose implementation details, extend relevant tests, update in-scope docs and fix verification failures within the agreed task. A dated research entry or earlier task-specific delegation grants no standing authority for future work.

Get an explicit owner decision before changing accepted architecture, milestones, success criteria, locked protocols or existing protected files. For an authorized protected edit, the owner decision must be recorded in the [register](../DECISIONS.md) and cover the proposed change. A passing guard cannot establish consent. Append new versioned artifacts only within approved scope. Preserve earlier results, sealed data boundaries and baseline history. Keep local corpus, generated private results and credentials out of commits and PR evidence.

Repository settings, exceptions to established policy and merge are owner actions unless explicitly delegated for the specific task. Recommend an alternative or record an open question when a decision is pending. Continue independent work inside scope.
