"""Static policy over the test suite, designed to stop agents from piling up redundant tests.

Checks (all AST-based, no test is executed):
- SHADOWED_TEST: two test functions with the same name in one class/module. Python keeps
  only the last one, so the first silently never runs.
- DUPLICATE_TEST_BODY: two test functions with an identical (non-trivial) body. Extend or
  parametrize the existing test (`self.subTest`) instead of copying it.
- UNTESTED_MODULE: a module under tools/ that no test imports. Existing gaps are listed in
  tools/ci/policy/untested_modules_baseline.txt; the list may only shrink.
- GATE_POLICY: environment gates follow the rules in tests/environment_gates.yaml.
- CATALOG_STALE: tests/TEST_CATALOG.md is regenerated from the suite; agents read it
  before adding tests to find where a behaviour is already covered.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.ci.config import (  # noqa: E402
    OPTIONAL_HEAVY_MODULES,
    POLICY_DIR,
    TESTS,
    TOOLS,
    is_git_ignored,
    load_gates,
    suites,
)

CATALOG = TESTS / "TEST_CATALOG.md"
UNTESTED_BASELINE = POLICY_DIR / "untested_modules_baseline.txt"
DUPLICATE_BASELINE = POLICY_DIR / "duplicate_test_bodies_baseline.txt"
MIN_DUPLICATE_BODY_CHARS = 300  # bodies shorter than this (as AST dump) are too trivial to flag


@dataclass(frozen=True)
class Finding:
    code: str
    message: str


@dataclass(frozen=True)
class TestFunction:
    suite: str
    module: str
    cls: Optional[str]
    name: str
    line: int
    doc: str
    body_hash: str
    body_size: int

    @property
    def test_id(self) -> str:
        middle = f"{self.cls}." if self.cls else ""
        return f"{self.suite}/{self.module}.{middle}{self.name}"


# --------------------------------------------------------------------------- parsing


def test_files() -> List[Tuple[str, Path]]:
    return [(suite, path) for suite in suites() for path in sorted((TESTS / suite).glob("test_*.py"))]


def _body_fingerprint(node: ast.FunctionDef) -> Tuple[str, int]:
    body = list(node.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    dump = "".join(ast.dump(stmt, annotate_fields=False) for stmt in body)
    return hashlib.sha256(dump.encode("utf-8")).hexdigest()[:16], len(dump)


def collect_tests(files: Optional[List[Tuple[str, Path]]] = None) -> Tuple[List[TestFunction], List[Finding]]:
    tests: List[TestFunction] = []
    findings: List[Finding] = []
    for suite, path in files if files is not None else test_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        scopes: List[Tuple[Optional[str], Iterable[ast.stmt]]] = [(None, tree.body)]
        scopes += [(node.name, node.body) for node in tree.body if isinstance(node, ast.ClassDef)]
        for cls, body in scopes:
            seen: Dict[str, int] = {}
            for node in body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith("test"):
                    continue
                where = f"{suite}/{path.stem}" + (f".{cls}" if cls else "")
                if node.name in seen:
                    findings.append(Finding("SHADOWED_TEST",
                                            f"{where}.{node.name} is defined twice (lines {seen[node.name]} "
                                            f"and {node.lineno}); the first definition never runs"))
                seen[node.name] = node.lineno
                body_hash, size = _body_fingerprint(node)
                doc = (ast.get_docstring(node) or "").strip().splitlines()
                tests.append(TestFunction(suite, path.stem, cls, node.name, node.lineno,
                                          doc[0] if doc else "", body_hash, size))
    return tests, findings


def _read_list(path: Path) -> Set[str]:
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")}


# --------------------------------------------------------------------------- checks


def duplicate_body_groups(tests: List[TestFunction]) -> List[List[TestFunction]]:
    groups: Dict[str, List[TestFunction]] = defaultdict(list)
    for test in tests:
        if test.body_size >= MIN_DUPLICATE_BODY_CHARS:
            groups[test.body_hash].append(test)
    return [group for group in groups.values() if len(group) > 1]


def check_duplicates(tests: List[TestFunction]) -> List[Finding]:
    baseline = _read_list(DUPLICATE_BASELINE)
    findings = []
    for group in duplicate_body_groups(tests):
        ids = sorted(t.test_id for t in group)
        if all(test_id in baseline for test_id in ids):
            continue
        findings.append(Finding("DUPLICATE_TEST_BODY",
                                "identical test bodies: " + ", ".join(ids) +
                                " -- extend or parametrize one test (self.subTest) instead of copying it"))
    return findings


def tools_modules() -> List[str]:
    modules = []
    for path in sorted(TOOLS.rglob("*.py")):
        if path.name == "__init__.py" or "__pycache__" in path.parts:
            continue
        modules.append(".".join(path.relative_to(TOOLS.parent).with_suffix("").parts))
    return modules


def imported_modules(files: Optional[List[Tuple[str, Path]]] = None) -> Set[str]:
    """Dotted names imported by test files, plus bare names resolved against tools/ packages."""
    names: Set[str] = set()
    all_test_py = [p for _, p in (files if files is not None else test_files())]
    for suite in suites():
        all_test_py += [p for p in (TESTS / suite).glob("*.py") if not p.name.startswith("test_")]
    for path in all_test_py:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
                names.update(f"{node.module}.{alias.name}" for alias in node.names)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith("tools."):
                names.add(node.value)  # importlib.import_module("tools.x.y")
    return names


def untested_modules() -> List[str]:
    imported = imported_modules()
    bare = {name.rsplit(".", 1)[-1] for name in imported}
    out = []
    for module in tools_modules():
        if module in imported or module.rsplit(".", 1)[-1] in bare:
            continue
        out.append(module)
    return out


def check_untested() -> List[Finding]:
    baseline = _read_list(UNTESTED_BASELINE)
    current = set(untested_modules())
    findings = [Finding("UNTESTED_MODULE", f"{m} is not imported by any test; add tests in the suite "
                                           f"that owns it (see tests/TEST_CATALOG.md)")
                for m in sorted(current - baseline)]
    findings += [Finding("BASELINE_STALE", f"{m} is now tested or gone; remove it from "
                                           f"{UNTESTED_BASELINE.relative_to(REPO)}")
                 for m in sorted(baseline - current)]
    return findings


def check_gates(tests: List[TestFunction]) -> List[Finding]:
    findings = []
    module_ids = {f"{t.suite}/{t.module}" for t in tests}
    module_ids |= {f"{suite}/{path.stem}" for suite, path in test_files()}
    class_ids = {f"{t.suite}/{t.module}.{t.cls}" for t in tests if t.cls}
    test_ids = {t.test_id for t in tests}
    for gate in load_gates():
        for module in gate.requires_modules:
            if module not in OPTIONAL_HEAVY_MODULES:
                findings.append(Finding("GATE_POLICY", f"gate requires module {module!r}, which is not an "
                                                       f"allowed optional heavy module; install it instead"))
        for path in gate.requires_paths:
            if not is_git_ignored(path):
                findings.append(Finding("GATE_POLICY", f"gate requires path {path!r}, which is not git-ignored; "
                                                       f"tracked inputs must exist, not be gated"))
        for test_id in gate.tests:
            if test_id not in module_ids | class_ids | test_ids:
                findings.append(Finding("GATE_POLICY", f"gate names unknown test {test_id!r}"))
    return findings


# --------------------------------------------------------------------------- catalog


def render_catalog(tests: List[TestFunction]) -> str:
    by_file: Dict[Tuple[str, str], List[TestFunction]] = defaultdict(list)
    for test in tests:
        by_file[(test.suite, test.module)].append(test)
    targets = _module_targets()
    lines = [
        "# Test Catalog",
        "",
        "<!-- Generated by `python -m tools.ci.test_policy --write-catalog`. Do not edit by hand. -->",
        "",
        "Read this before writing a test: find the file that already covers the module or",
        "behaviour and extend it. New files are for new modules only.",
        "",
        f"Suites: {len(suites())} — test files: {len(by_file)} — test functions: {len(tests)}",
    ]
    for suite in suites():
        lines += ["", f"## {suite}"]
        for (s, module), items in sorted(by_file.items()):
            if s != suite:
                continue
            covered = ", ".join(f"`{t}`" for t in targets.get((suite, module), [])) or "—"
            lines += ["", f"### {module} ({len(items)})", f"Covers: {covered}", ""]
            for test in sorted(items, key=lambda t: t.line):
                owner = f"{test.cls}." if test.cls else ""
                doc = f" — {test.doc}" if test.doc else ""
                lines.append(f"- `{owner}{test.name}`{doc}")
    return "\n".join(lines) + "\n"


def _module_targets() -> Dict[Tuple[str, str], List[str]]:
    modules = set(tools_modules())
    by_bare = {m.rsplit(".", 1)[-1]: m for m in modules}
    out: Dict[Tuple[str, str], List[str]] = {}
    for suite, path in test_files():
        found = set(imported_modules([(suite, path)]))
        hits = {m for m in modules if m in found}
        hits |= {by_bare[n.rsplit(".", 1)[-1]] for n in found if n.rsplit(".", 1)[-1] in by_bare and "." not in n}
        out[(suite, path.stem)] = sorted(hits)
    return out


def check_catalog(tests: List[TestFunction]) -> List[Finding]:
    expected = render_catalog(tests)
    actual = CATALOG.read_text(encoding="utf-8") if CATALOG.exists() else ""
    if actual != expected:
        return [Finding("CATALOG_STALE", "tests/TEST_CATALOG.md is out of date; run "
                                         "`python -m tools.ci.test_policy --write-catalog`")]
    return []


# --------------------------------------------------------------------------- entry


def run_policy() -> List[Finding]:
    tests, findings = collect_tests()
    findings += check_duplicates(tests)
    findings += check_untested()
    findings += check_gates(tests)
    findings += check_catalog(tests)
    return findings


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write-catalog", action="store_true", help="regenerate tests/TEST_CATALOG.md")
    parser.add_argument("--write-baselines", action="store_true",
                        help="record current untested modules / duplicate bodies (use only when adopting the policy)")
    args = parser.parse_args(argv)
    tests, _ = collect_tests()
    if args.write_catalog:
        CATALOG.write_text(render_catalog(tests), encoding="utf-8")
        print(f"wrote {CATALOG.relative_to(REPO)}")
    if args.write_baselines:
        POLICY_DIR.mkdir(parents=True, exist_ok=True)
        header = "# Existing gaps when the policy was adopted. This list may only shrink.\n"
        UNTESTED_BASELINE.write_text(header + "".join(f"{m}\n" for m in untested_modules()), encoding="utf-8")
        dup_ids = sorted(t.test_id for g in duplicate_body_groups(tests) for t in g)
        DUPLICATE_BASELINE.write_text(header + "".join(f"{t}\n" for t in dup_ids), encoding="utf-8")
        print("wrote baselines")
    findings = run_policy()
    for finding in findings:
        print(f"  {finding.code}: {finding.message}")
    print("Test policy:", "PASS" if not findings else f"FAIL ({len(findings)} finding(s))")
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
