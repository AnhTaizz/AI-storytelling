# Quality Gates

DEC-019 establishes the gate. Use the [repository rules](../../CLAUDE.md) and the [shared agent workflow](AGENT_WORKFLOW.md) for local verification and PR evidence. The [governance audit](GOVERNANCE_AUDIT_V1.md) records the observed enforcement limits.

## One command

```
python -m tools.ci.check              # what agents run before committing
python -m tools.ci.check --coverage   # what CI runs on every pull request
python -m tools.ci.check --strict     # full local machine: unmet environment gates fail
```

| Step | Tool | Fails when |
|---|---|---|
| 1. Compile | `compileall` over `tools/`, `tests/` | any syntax error |
| 2. Test policy | `tools/ci/test_policy.py` | shadowed test name, identical test bodies, untested new `tools/` module, gate rule broken, stale `tests/TEST_CATALOG.md` |
| 3. Test suites | `tools/ci/run_tests.py` | any failure or error in any suite |
| 4. Repository guards | `tools/ci/guards.py` | protected file modified without a decision, credential or local-only file tracked, changed `tools/` lines < 80% covered (with `--coverage`) |

Useful pieces: `python -m tools.ci.run_tests --suite story_pipeline`,
`python -m tools.ci.test_policy --write-catalog`, `python -m tools.ci.guards --base origin/main`.

## How duplicated tests are prevented

Agents writing features one after another tend to re-test the same behaviour in new
files. The gate makes the existing coverage visible and makes copying detectable:

1. **Catalog.** `tests/TEST_CATALOG.md` lists every test file, the `tools/` modules it
   imports, and every test with its docstring. It is regenerated from the code and CI
   fails when it is stale, so it is always the current map. `CLAUDE.md` tells agents to
   search it first and extend the file that already covers a module.
2. **One file per module** convention, enforced socially by `CLAUDE.md` and visibly by the
   catalog's "Covers:" line.
3. **Exact duplicates fail.** Two test functions with the same non-trivial body (AST
   comparison, docstrings ignored) fail the policy. Variations belong in one test with
   `self.subTest`.
4. **Shadowed names fail.** A second `def test_x` in the same class silently replaces the
   first; the policy catches it.
5. **Untested modules fail.** A new `tools/` module that no test imports fails the policy.
   Existing gaps are listed in a baseline that may only shrink.

Near-duplicates with different wording are not detected automatically; the catalog and
review are the defence there.

## Environment gates

Some tests need the CPU torch stack, private artifacts under `.local/`, or private
corpus chapters. These cases are declared in `tests/environment_gates.yaml` and reported
as GATED with the reason, never silently skipped. The policy only accepts gates that wait
for an allow-listed heavy module or for a git-ignored path, so a gate cannot hide a test
whose inputs belong in the repository. On a machine with everything, run `--strict`.

## Protected paths

`tools/ci/policy/protected_paths.txt` lists append-only paths: frozen M1–M3 layers,
locked M4 interfaces, recorded results in `benchmarks/`, `data/sample/`, and the gate
rules themselves. New files may be added. Changing an existing one needs a decision in
`docs/DECISIONS.md` in the same branch, which the project owner approves in review.
The guard observes a change to that path. The reviewer must verify the owner decision
covers the specific files and behavior.

## Default-branch ruleset

On 22 November 2026 the active [Protect main ruleset](https://github.com/AnhTaizz/AI-storytelling/rules/27520620) required a PR and an up-to-date `quality-gate`, blocked deletion and force pushes, and had zero required approving reviews. Check the live ruleset when auditing a later revision.

## Claude Code hook

`.claude/settings.json` runs `.claude/hooks/guard_bash.py` before every Bash command an
agent runs through that tool in this repository. It denies recognized direct protected-branch
and force pushes and checks staged filenames on recognized commit commands. Other clients
rely on the repository workflow and GitHub controls.
