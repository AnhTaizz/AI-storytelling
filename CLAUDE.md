# Working in this repository (rules for coding agents)

This project is written mostly by agents. These rules exist so that each change is
verified, and so that tests stay a single, non-redundant description of behaviour.

## The quality gate

Run before every commit and before saying a task is done:

```
python -m tools.ci.check            # compile, test policy, all suites, repository guards
python -m tools.ci.check --coverage # what CI runs: also requires >= 80% coverage of changed tools/ lines
```

CI (`.github/workflows/ci.yml`) runs the same command on every pull request. A red gate
is never "done". Report failures with their output; never claim a pass you did not see.

Faster loops while working: `python -m tools.ci.run_tests --suite <suite>`.

## Writing tests without duplicating them

1. **Look before you write.** Open `tests/TEST_CATALOG.md` (generated) and search for the
   module and behaviour you are changing. If a test file already covers that module,
   extend that file; if a test already checks that behaviour, change it rather than
   adding a second one.
2. **One test file per module:** `tools/<area>/<module>.py` is tested in
   `tests/<area>/test_<module>.py` (or the existing file that already imports it). A new
   suite directory is only for a new `tools/<area>/` package.
3. **Variations of one behaviour are one test** with `self.subTest(...)` over cases, not
   copies with a different literal.
4. **Reuse fixtures/builders** that already exist in the suite (for example
   `fixture_builder.py`) instead of writing new ones.
5. **Behaviour, not implementation:** assert on inputs/outputs and documented contracts,
   so refactors do not require rewriting tests.
6. Regenerate the catalog after changing tests:
   `python -m tools.ci.test_policy --write-catalog` (CI fails if it is stale).

The test policy (`tools/ci/test_policy.py`) fails on: a test name defined twice in one
class (the first silently never runs), identical test bodies, a `tools/` module that no
test imports, a stale catalog, and environment gates that break the gate rules.

## Never

- Never skip, delete, weaken or `@skip` a failing test to get green. Fix the code, or
  stop and report. Tests may be skipped only through `tests/environment_gates.yaml`, and
  only for allow-listed heavy modules or git-ignored private data.
- Never add entries to `tools/ci/policy/*_baseline.txt`. Baselines only shrink.
- Never modify, delete or rename files under protected paths
  (`tools/ci/policy/protected_paths.txt`: frozen M1–M3 layers, locked M4 interfaces,
  `benchmarks/`, `data/sample/`, the gate rules). Add a new versioned file instead. A
  change to an existing protected file needs a decision recorded in `docs/DECISIONS.md`
  by the project owner.
- Never commit `.env`, API keys, `.local/`, or corpus chapters other than 1–5.
- Never push to `main` or force-push; work on a branch and open a pull request.
- Never merge a pull request unless the project owner explicitly asks.

## Project map

- `docs/PROJECT_STATE.md` — current status; `docs/ROADMAP.md`; `docs/DECISIONS.md`.
- `tools/canonical_story`, `tools/story_ingestion` — frozen M2/M3 reference code.
- `tools/story_extraction` — M4 research tooling (Gemini runtime, draft compiler).
- `tools/story_pipeline` — Brief → Plan → Script → Critic → Revision prototype.
- `tools/ci` — the quality gate. `docs/engineering/QUALITY_GATES.md` explains it.
- Python 3.13+, standard `unittest`; dependencies in `requirements-*.txt` (install all of
  them; CI does). A new third-party import needs a requirements entry in the same change,
  otherwise CI fails on import.
