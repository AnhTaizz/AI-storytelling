"""The one quality gate: run before every commit/push and in CI.

    python -m tools.ci.check              # tests + test policy + repository guards
    python -m tools.ci.check --coverage   # also enforce coverage of changed lines (CI does this)
    python -m tools.ci.check --strict     # unmet environment gates fail (full local machine)

Exit code 0 means every gate passed.
"""

from __future__ import annotations

import argparse
import compileall
import sys
from pathlib import Path
from typing import List, Optional

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.ci import guards, run_tests, test_policy  # noqa: E402


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default=None, help="base ref for diff checks (default: origin/main, else main)")
    parser.add_argument("--coverage", action="store_true", help="collect coverage and check changed lines")
    parser.add_argument("--strict", action="store_true", help="unmet environment gates fail")
    args = parser.parse_args(argv)

    results = {}
    print("[1/4] Compile")
    results["compile"] = all(compileall.compile_dir(str(REPO / d), quiet=1, legacy=False, force=False)
                             for d in ("tools", "tests"))
    print("  OK" if results["compile"] else "  FAIL: syntax errors above")

    print("[2/4] Test policy")
    findings = test_policy.run_policy()
    for finding in findings:
        print(f"  {finding.code}: {finding.message}")
    results["test_policy"] = not findings
    print("  OK" if not findings else f"  FAIL ({len(findings)})")

    print("[3/4] Test suites")
    report = run_tests.run_all(strict=args.strict, coverage=args.coverage)
    run_tests.print_problems(report)
    results["tests"] = report["ok"]

    print("[4/4] Repository guards")
    coverage_file = run_tests.COVERAGE_DIR / ".coverage" if args.coverage else None
    findings, notes = guards.run_guards(args.base, coverage_file)
    for note in notes:
        print(f"  {note}")
    for finding in findings:
        print(f"  {finding.code}: {finding.message}")
    results["guards"] = not findings
    print("  OK" if not findings else f"  FAIL ({len(findings)})")

    failed = [name for name, ok in results.items() if not ok]
    print("\nQUALITY GATE:", "PASS" if not failed else f"FAIL ({', '.join(failed)})")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
