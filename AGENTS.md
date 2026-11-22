# Working on AI-storytelling

Start with the current milestone and latest relevant entry in [Project State](docs/PROJECT_STATE.md). Follow [CLAUDE.md](CLAUDE.md) for repository policy and the [shared agent workflow](docs/engineering/AGENT_WORKFLOW.md) for taking a task through owner review.

- Identify the requested outcome, affected modules and acceptance criteria. Check the [decision register](docs/DECISIONS.md) and [roadmap](docs/ROADMAP.md) before choosing an implementation.
- Work on a dedicated branch from current `main`. Inspect existing code, callers and the [test catalog](tests/TEST_CATALOG.md) before adding anything. Prefer the smallest change that demonstrates the requested behavior.
- Preserve frozen contracts, research locks and benchmark history. Take changes to architecture, scope or success criteria to the owner.
- Run `python -m tools.ci.check` and `python -m tools.ci.check --coverage --base origin/main` before committing. Report failures, gated checks and uncertainty with the observed evidence.
- Push the feature branch and open a PR against `main`. Leave approval and merge to the owner.

For recap regressions, listening trials or model comparisons, use the [pipeline review guidance](docs/engineering/RECAP_REGRESSION_REVIEW.md).
