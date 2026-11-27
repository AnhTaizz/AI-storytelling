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

### Gemini DEV preflight

This workflow applies to owner-approved, one-shot Gemini DEV request sets. The run approval identifies the plan, the request lock, the model, and the dispatch and output budgets. Reuse standing declarations as input to preflight. Keep the approval for each run separate. For official benchmarks, M9 and sealed holdouts, use their own protocols.

Record project declarations in the git-ignored `.local/gemini-dev-owner-attestation.json` alongside the workspace's `.env` directory. Use only the following fields. The example uses fictional declarations.

```json
{
  "scope": "ai-storytelling:gemini-dev",
  "source": "owner_project_chat",
  "confirmed_on": "2025-06-01",
  "pool_revision": "1",
  "credential_access": "active",
  "free_tier": "active",
  "operator_eligibility": "unverified"
}
```

Use `owner_project_chat` or `owner_project_review` for the source category and the actual owner confirmation date. Set a claim to `active` when it is applicable and undisputed, `unverified` when its applicability is unresolved, or `revoked` when withdrawn. `operator_eligibility` records only the status of an internal declaration for the current operator. Keep API keys, personal documents, dates of birth and chat transcripts out of the record. Keep it out of commits and PRs.

Reuse an active record across sessions, agent handoffs and worktrees using the same project config. Review the affected declaration when usage rights, billing, credentials, the operator or relevant conditions change, or when evidence conflicts. The pool revision defaults to `1`. When editing the credential inventory or billing in `.env`, increment `GEMINI_DEV_POOL_REVISION` there and update the local record once the changed pool is covered. This revision is maintained with the configuration. The preflight also detects process overrides that would change the credential or billing inputs. It never saves a key or a credential fingerprint.

```powershell
python -m tools.llm_infra.dev_gemini_preflight <requests.lock.json> --requests-sha256 <approved-sha256> --model <approved-model> --dispatch-budget <approved-budget> --output-cap <approved-cap> --dotenv <workspace-dotenv>
```

Use the values from the owner-approved plan. The command verifies the lock and each payload, applies the existing zero-spend and free-model checks, and selects the lowest-numbered eligible credential from the deduplicated pool. It reports only the slot name. It checks known local quota blocks for that choice and stops if blocked. Provider headroom remains unknown unless independently established. Request dashboard, project ID or manual slot details only when required by the approved plan or to resolve a material discrepancy. Preflight sends zero requests.

| Finding | Meaning |
| --- | --- |
| `BLOCKED_OWNER_ATTESTATION` | The internal record is missing, invalid, inactive or stale for the current pool. Reuse the claims that still apply. |
| `BLOCKED_CREDENTIAL_OR_CONFIG` | A local credential, billing, endpoint, model or cost configuration prevented selection. Fix the relevant configuration. |
| `BLOCKED_PLAN` | The approved hash, request package or one-shot budget failed validation. Use the approved artifacts. |
| `BLOCKED_LOCAL_QUOTA` | The selected credential's scope has a known cooldown. Close or defer the run per its plan. |
| Provider rejection | A dispatched request received an actual provider refusal. Record the sanitized category and stop the run on access, billing, quota or terms rejection. |
| Execution environment restriction | The agent environment or provider's applicable usage terms prevent dispatch. Record this separately from local declarations and configuration. |

`PASSED_OFFLINE` describes only project checks. The report always marks provider contact and environment verification separately. An authorized live runner must independently satisfy provider terms and execution policy, including any stricter plan requirement. Pin the selected credential for the entire run. Reserve each scene once before its physical dispatch, count all attempts, and stop on transport failure or provider refusal. Record remaining scenes as not dispatched according to the plan. Sending a smoke request, retrying, invoking LLM repair, switching credentials and falling back are outside the one-shot budget. Lock predictions before giving a scorer access to gold.

When an approved internal preflight changes for a locked run, add a revision record with the parent lock hash and the changed rule. Keep the original lock, request payloads, scorer, criteria and denominators. Carry forward all unchanged conditions. An offline preflight result cannot supersede an approved plan or clear a provider or environment restriction.
