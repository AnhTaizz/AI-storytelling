"""Repository guards that compare a branch with its base.

- PROTECTED_PATH: an existing file under a protected (append-only) path was modified,
  deleted or renamed without a recorded decision (docs/DECISIONS.md unchanged).
- SECRET: a tracked file contains something that looks like a credential.
- PRIVATE_DATA: a tracked file is local-only (.env, .local/, untracked corpus chapters).
- DIFF_COVERAGE: lines changed under tools/ are not exercised by the tests
  (needs a coverage run: `python -m tools.ci.run_tests --coverage`).
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.ci.config import POLICY_DIR, git  # noqa: E402
from tools.ci.test_policy import Finding  # noqa: E402

PROTECTED_FILE = POLICY_DIR / "protected_paths.txt"
DECISIONS = "docs/DECISIONS.md"
DIFF_COVERAGE_THRESHOLD = 80.0

SECRET_PATTERNS = [
    (re.compile(r"AIza[0-9A-Za-z_\-]{35}"), "Google API key"),
    (re.compile(r"sk-ant-[0-9A-Za-z_\-]{20,}"), "Anthropic API key"),
    (re.compile(r"sk-(proj-)?[0-9A-Za-z]{32,}"), "OpenAI-style API key"),
    (re.compile(r"gh[pousr]_[0-9A-Za-z]{36,}"), "GitHub token"),
    (re.compile(r"xox[baprs]-[0-9A-Za-z\-]{10,}"), "Slack token"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key id"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
]
PRIVATE_PATH_PATTERNS = [
    (re.compile(r"(^|/)\.env(\..+)?$"), "local credentials file"),
    (re.compile(r"^\.local/"), "local-only artifact directory"),
    (re.compile(r"^data/sample/otonari_no_tenshi/wn_jp/raw/chapter_(?!00[1-5]\.txt$)\d+\.txt$"),
     "untracked private corpus chapter"),
]
PRIVATE_PATH_ALLOW = {".env.example"}
SCAN_SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".gz"}


def read_patterns(path: Path = PROTECTED_FILE) -> List[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")]


def is_protected(path: str, patterns: List[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def changed_files(base: str) -> List[Tuple[str, str]]:
    """(status, path) for base...HEAD plus uncommitted changes; renames report the old path."""
    out: Dict[str, str] = {}
    for spec in ([f"{base}...HEAD"], ["HEAD"]):
        text = git("diff", "--name-status", "-M", *spec)
        for line in text.splitlines():
            parts = line.split("\t")
            status = parts[0][0]
            if status == "R":
                out[parts[1]] = "R"
                out.setdefault(parts[2], "A")
            else:
                out[parts[1]] = status if parts[1] not in out else out[parts[1]]
    return sorted((status, path) for path, status in out.items())


def check_protected(changes: List[Tuple[str, str]], patterns: Optional[List[str]] = None) -> List[Finding]:
    patterns = patterns if patterns is not None else read_patterns()
    touched = [(s, p) for s, p in changes if s in {"M", "D", "R", "T"} and is_protected(p, patterns)]
    if not touched or any(p == DECISIONS for _, p in changes):
        return []
    verbs = {"M": "modified", "D": "deleted", "R": "renamed", "T": "type-changed"}
    return [Finding("PROTECTED_PATH", f"{p} was {verbs[s]}; protected paths are append-only. Add a new "
                                      f"versioned file instead, or record the decision in {DECISIONS}")
            for s, p in touched]


def tracked_files() -> List[str]:
    return [p for p in git("ls-files", "-z").split("\0") if p]


def check_private_paths(paths: List[str]) -> List[Finding]:
    findings = []
    for path in paths:
        if path in PRIVATE_PATH_ALLOW:
            continue
        for pattern, label in PRIVATE_PATH_PATTERNS:
            if pattern.search(path):
                findings.append(Finding("PRIVATE_DATA", f"{path} is tracked but is a {label}"))
    return findings


def check_secrets(paths: List[str]) -> List[Finding]:
    findings = []
    for path in paths:
        full = REPO / path
        if full.suffix.lower() in SCAN_SKIP_SUFFIXES or not full.is_file():
            continue
        try:
            text = full.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pattern, label in SECRET_PATTERNS:
            match = pattern.search(text)
            if match:
                line = text.count("\n", 0, match.start()) + 1
                findings.append(Finding("SECRET", f"{path}:{line} looks like a {label}"))
    return findings


# --------------------------------------------------------------------------- diff coverage


def changed_lines(base: str, prefix: str = "tools/") -> Dict[str, Set[int]]:
    text = git("diff", "-U0", f"{base}...HEAD", "--", prefix)
    result: Dict[str, Set[int]] = {}
    current = None
    for line in text.splitlines():
        if line.startswith("+++ "):
            name = line[4:]
            current = name[2:] if name.startswith("b/") and name.endswith(".py") else None
        elif line.startswith("@@") and current:
            match = re.search(r"\+(\d+)(?:,(\d+))?", line)
            start, count = int(match.group(1)), int(match.group(2) or "1")
            result.setdefault(current, set()).update(range(start, start + count))
    return result


def coverage_data(coverage_file: Path) -> Optional[Dict[str, Dict[str, Set[int]]]]:
    if not coverage_file.exists():
        return None
    out_json = coverage_file.parent / "coverage.json"
    process = subprocess.run([sys.executable, "-m", "coverage", "json", "-q", "-o", str(out_json)],
                             cwd=REPO, env=dict(os.environ, COVERAGE_FILE=str(coverage_file)),
                             capture_output=True, text=True)
    if process.returncode != 0:
        return None
    data = json.loads(out_json.read_text(encoding="utf-8"))
    files = {}
    for name, info in data["files"].items():
        rel = os.path.relpath(name, REPO).replace(os.sep, "/") if os.path.isabs(name) else name
        files[rel] = {"executed": set(info["executed_lines"]), "missing": set(info["missing_lines"])}
    return files


def check_diff_coverage(base: str, coverage_file: Path,
                        threshold: float = DIFF_COVERAGE_THRESHOLD) -> Tuple[List[Finding], str]:
    changes = changed_lines(base)
    if not changes:
        return [], "diff coverage: no changed lines under tools/"
    data = coverage_data(coverage_file)
    if data is None:
        return [], "diff coverage: SKIPPED (no coverage data; run tests with --coverage)"
    return diff_coverage_findings(changes, data, threshold)


def diff_coverage_findings(changes: Dict[str, Set[int]], data: Dict[str, Dict[str, Set[int]]],
                           threshold: float = DIFF_COVERAGE_THRESHOLD) -> Tuple[List[Finding], str]:
    covered = total = 0
    uncovered: List[str] = []
    for path, lines in sorted(changes.items()):
        info = data.get(path)
        if info is None:
            executable = lines  # never imported by any test: every changed line counts as missing
            hit: Set[int] = set()
        else:
            executable = lines & (info["executed"] | info["missing"])
            hit = lines & info["executed"]
        covered += len(hit)
        total += len(executable)
        missing = sorted(executable - hit)
        if missing:
            uncovered.append(f"{path}: {_ranges(missing)}")
    if total == 0:
        return [], "diff coverage: no executable changed lines"
    percent = 100.0 * covered / total
    summary = f"diff coverage: {percent:.1f}% of {total} changed executable lines under tools/"
    if percent + 1e-9 < threshold:
        return [Finding("DIFF_COVERAGE", f"{summary} (< {threshold:.0f}%). Uncovered: " + "; ".join(uncovered))], summary
    return [], summary


def _ranges(lines: List[int]) -> str:
    out, start, prev = [], lines[0], lines[0]
    for n in lines[1:] + [None]:
        if n is not None and n == prev + 1:
            prev = n
            continue
        out.append(f"{start}-{prev}" if start != prev else str(start))
        if n is not None:
            start = prev = n
    return ",".join(out)


# --------------------------------------------------------------------------- entry


def resolve_base(base: Optional[str]) -> Optional[str]:
    candidates = [base] if base else ["origin/main", "main"]
    for candidate in candidates:
        if subprocess.run(["git", "rev-parse", "--verify", "-q", candidate], cwd=REPO,
                          capture_output=True).returncode == 0:
            return candidate
    return None


def run_guards(base: Optional[str], coverage_file: Optional[Path] = None) -> Tuple[List[Finding], List[str]]:
    notes: List[str] = []
    tracked = tracked_files()
    findings = check_private_paths(tracked) + check_secrets(tracked)
    resolved = resolve_base(base)
    if resolved is None:
        notes.append("protected paths / diff coverage: SKIPPED (no base branch found)")
        return findings, notes
    changes = changed_files(resolved)
    notes.append(f"base: {resolved} ({len(changes)} changed file(s))")
    findings += check_protected(changes)
    if coverage_file is not None:
        cov_findings, summary = check_diff_coverage(resolved, coverage_file)
        findings += cov_findings
        notes.append(summary)
    return findings, notes


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default=None, help="base ref (default: origin/main, else main)")
    parser.add_argument("--coverage-file", default=None, help="coverage data file for the diff-coverage check")
    args = parser.parse_args(argv)
    findings, notes = run_guards(args.base, Path(args.coverage_file) if args.coverage_file else None)
    for note in notes:
        print(f"  {note}")
    for finding in findings:
        print(f"  {finding.code}: {finding.message}")
    print("Repository guards:", "PASS" if not findings else f"FAIL ({len(findings)} finding(s))")
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
