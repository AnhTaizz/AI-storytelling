"""Run every test suite, each in its own process, applying only declared environment gates.

    python -m tools.ci.run_tests                 # all suites
    python -m tools.ci.run_tests --suite story_pipeline
    python -m tools.ci.run_tests --strict        # unmet gates fail (full local run)
    python -m tools.ci.run_tests --coverage      # also collect coverage of tools/

Why one process per suite: suites import helpers by bare name (for example two
different `fixture_builder` modules), so running them in one interpreter would mix them.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.ci.config import TESTS, Gate, gate_index, load_gates, suites  # noqa: E402

COVERAGE_DIR = REPO / ".local" / "ci" / "coverage"


# --------------------------------------------------------------------------- child side


class _Gated(unittest.TestCase):
    """Stands in for a test whose declared environment is missing."""

    def __init__(self, test_id: str, message: str, fail: bool) -> None:
        super().__init__("run_gate")
        self._test_id = test_id
        self._message = message
        self._fail = fail

    def id(self) -> str:  # noqa: A003 - unittest API
        return self._test_id

    def __str__(self) -> str:
        return self._test_id

    def run_gate(self) -> None:
        if self._fail:
            self.fail(f"STRICT: {self._message}")
        self.skipTest(f"GATED: {self._message}")


class _ImportFailure(unittest.TestCase):
    def __init__(self, test_id: str, error: str) -> None:
        super().__init__("run_import")
        self._test_id = test_id
        self._error = error

    def id(self) -> str:  # noqa: A003
        return self._test_id

    def run_import(self) -> None:
        raise ImportError(self._error)


def _iter_tests(suite: unittest.TestSuite) -> Iterable[unittest.TestCase]:
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _iter_tests(item)
        else:
            yield item


def _gate_message(gate: Gate, missing: List[str]) -> str:
    return f"{gate.reason} (missing: {', '.join(missing)})"


def build_suite(suite_name: str, strict: bool) -> unittest.TestSuite:
    suite_dir = TESTS / suite_name
    sys.path.insert(0, str(suite_dir))
    gates = gate_index(load_gates())
    loader = unittest.TestLoader()
    result = unittest.TestSuite()
    for test_file in sorted(suite_dir.glob("test_*.py")):
        module_id = f"{suite_name}/{test_file.stem}"
        gate = gates.get(module_id)
        if gate is not None and gate.unmet():
            result.addTest(_Gated(module_id, _gate_message(gate, gate.unmet()), strict))
            continue
        try:
            loaded = loader.loadTestsFromName(test_file.stem)
        except Exception as exc:  # noqa: BLE001 - report any import problem as an error
            result.addTest(_ImportFailure(module_id, f"{type(exc).__name__}: {exc}"))
            continue
        for test in _iter_tests(loaded):
            test_id = f"{suite_name}/{test.id()}"
            gate = gates.get(test_id)
            if gate is not None and gate.unmet():
                result.addTest(_Gated(test_id, _gate_message(gate, gate.unmet()), strict))
            else:
                result.addTest(test)
    return result


def run_child(suite_name: str, strict: bool, result_path: Path, verbosity: int) -> int:
    os.chdir(REPO)
    suite = build_suite(suite_name, strict)
    started = time.time()
    outcome = unittest.TextTestRunner(stream=sys.stderr, verbosity=verbosity).run(suite)

    def ids(pairs: List[Any]) -> List[Dict[str, str]]:
        return [{"test": str(test.id()), "detail": str(detail)[-4000:]} for test, detail in pairs]

    gated = [p for p in ids(outcome.skipped) if p["detail"].startswith("GATED:")]
    summary = {
        "suite": suite_name,
        "ran": outcome.testsRun,
        "failures": ids(outcome.failures),
        "errors": ids(outcome.errors),
        "skipped": len(outcome.skipped) - len(gated),
        "gated": gated,
        "unexpected_successes": len(outcome.unexpectedSuccesses),
        "seconds": round(time.time() - started, 2),
    }
    result_path.write_text(json.dumps(summary), encoding="utf-8")
    return 0 if outcome.wasSuccessful() else 1


# --------------------------------------------------------------------------- parent side


def run_suite_process(suite_name: str, *, strict: bool, coverage: bool, verbosity: int) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        result_path = Path(tmp) / "result.json"
        child = ["-m", "tools.ci.run_tests", "--child", suite_name, "--result", str(result_path),
                 "--verbosity", str(verbosity)] + (["--strict"] if strict else [])
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        if coverage:
            COVERAGE_DIR.mkdir(parents=True, exist_ok=True)
            env["COVERAGE_FILE"] = str(COVERAGE_DIR / ".coverage")
            command = [sys.executable, "-m", "coverage", "run", "--parallel-mode", "--branch",
                       f"--source={REPO / 'tools'}", *child]
        else:
            command = [sys.executable, *child]
        process = subprocess.run(command, cwd=REPO, env=env, capture_output=True, text=True)
        if result_path.exists():
            summary = json.loads(result_path.read_text(encoding="utf-8"))
        else:  # the child crashed before writing its result
            summary = {"suite": suite_name, "ran": 0, "failures": [],
                       "errors": [{"test": f"{suite_name}/<runner>", "detail": process.stderr[-4000:]}],
                       "skipped": 0, "gated": [], "unexpected_successes": 0, "seconds": 0}
        summary["output"] = process.stderr
        return summary


def run_all(selected: Optional[List[str]] = None, *, strict: bool = False, coverage: bool = False,
            verbosity: int = 1, echo=print) -> Dict[str, Any]:
    names = selected or suites()
    unknown = [n for n in names if n not in suites()]
    if unknown:
        raise SystemExit(f"unknown suite(s): {unknown}; available: {suites()}")
    if coverage:
        for stale in COVERAGE_DIR.glob(".coverage*"):
            stale.unlink()
    results = []
    for name in names:
        summary = run_suite_process(name, strict=strict, coverage=coverage, verbosity=verbosity)
        results.append(summary)
        bad = len(summary["failures"]) + len(summary["errors"])
        status = "OK  " if bad == 0 else "FAIL"
        echo(f"  {status} {name:<18} ran {summary['ran']:>4}  failed {bad:>3}  "
             f"skipped {summary['skipped']:>3}  gated {len(summary['gated']):>3}  {summary['seconds']}s")
    if coverage:
        subprocess.run([sys.executable, "-m", "coverage", "combine", "-q"], cwd=REPO,
                       env=dict(os.environ, COVERAGE_FILE=str(COVERAGE_DIR / ".coverage")),
                       capture_output=True, text=True)
    ok = all(not r["failures"] and not r["errors"] for r in results)
    return {"ok": ok, "suites": results}


def print_problems(report: Dict[str, Any], echo=print) -> None:
    for summary in report["suites"]:
        for kind in ("failures", "errors"):
            for item in summary[kind]:
                echo(f"\n--- {kind[:-1].upper()}: {item['test']}\n{item['detail']}")
    gated = [g for s in report["suites"] for g in s["gated"]]
    if gated:
        echo(f"\nGated (environment missing, declared in tests/environment_gates.yaml): {len(gated)}")
        for item in gated:
            echo(f"  - {item['test']}: {item['detail'][len('GATED: '):]}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--suite", action="append", help="run only this suite (repeatable)")
    parser.add_argument("--strict", action="store_true", help="unmet environment gates fail instead of skip")
    parser.add_argument("--coverage", action="store_true", help="collect coverage of tools/ into .local/ci")
    parser.add_argument("--verbosity", type=int, default=1)
    parser.add_argument("--json-out", default=None, help="write the summary JSON here")
    parser.add_argument("--child", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--result", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.child:
        return run_child(args.child, args.strict, Path(args.result), args.verbosity)
    print("Test suites:")
    report = run_all(args.suite, strict=args.strict, coverage=args.coverage, verbosity=args.verbosity)
    print_problems(report)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    print("\nRESULT:", "PASS" if report["ok"] else "FAIL")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
