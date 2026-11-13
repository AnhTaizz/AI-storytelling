# Quality Gates

Decision: DEC-019. Agent rules: `CLAUDE.md`. Code: `tools/ci/`.

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

Some tests need what CI does not have: the CPU torch stack, or the private 30-chapter
corpus under `.local/`. They are declared in `tests/environment_gates.yaml` and reported
as GATED with the reason, never silently skipped. The policy only accepts gates that wait
for an allow-listed heavy module or for a git-ignored path, so a gate cannot hide a test
whose inputs belong in the repository. On a machine with everything, run `--strict`.

## Protected paths

`tools/ci/policy/protected_paths.txt` lists append-only paths: frozen M1–M3 layers,
locked M4 interfaces, recorded results in `benchmarks/`, `data/sample/`, and the gate
rules themselves. New files may be added. Changing an existing one needs a decision in
`docs/DECISIONS.md` in the same branch, which the project owner approves in review.

## Branch protection (project owner, one-time, on GitHub)

The CI check only blocks merges once GitHub requires it:

1. Repository → Settings → Branches → Add branch ruleset (or "Add rule") for `main`.
2. Enable **Require a pull request before merging**.
3. Enable **Require status checks to pass**, and select `quality-gate` (it appears after
   the workflow has run once).
4. Enable **Block force pushes**, and leave deletions blocked.

## Claude Code hook

`.claude/settings.json` runs `.claude/hooks/guard_bash.py` before every Bash command an
agent runs in this repository. It denies pushes to `main`/`master`, `--force`/`-f`
pushes, and commits while `.env`, `.local/` or private corpus chapters are staged.
