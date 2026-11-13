#!/usr/bin/env python3
"""PreToolUse hook for Bash: stop the git actions an agent must never take on its own.

Blocks:
- pushing to main/master (work goes through pull requests);
- `git push --force` / `-f` (use --force-with-lease on your own branch if history must change);
- `git commit` while .env files, .local/ or untracked corpus chapters are staged.

Reads the hook payload (JSON) on stdin; prints a deny decision as JSON, or nothing to allow.
"""
import json
import re
import subprocess
import sys

PROTECTED_BRANCHES = ("main", "master")
SECRET_STAGED = re.compile(r"(^|/)\.env(\..+)?$|^\.local/|^data/sample/otonari_no_tenshi/wn_jp/raw/chapter_(?!00[1-5]\.txt$)")


def deny(reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}))
    sys.exit(0)


def current_branch() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True,
                              text=True, timeout=5).stdout.strip()
    except Exception:  # noqa: BLE001 - never break the session because of the hook
        return ""


def staged_files() -> list:
    try:
        out = subprocess.run(["git", "diff", "--cached", "--name-only"], capture_output=True,
                             text=True, timeout=5).stdout
        return [line for line in out.splitlines() if line and line != ".env.example"]
    except Exception:  # noqa: BLE001
        return []


def check(command: str) -> None:
    for segment in re.split(r"&&|\|\||;|\n", command):
        words = segment.strip().split()
        if len(words) < 2 or words[0] != "git":
            continue
        args = words[1:]
        # skip global options such as `git -C dir push`
        while args and args[0].startswith("-"):
            args = args[2:] if args[0] in ("-C", "-c") else args[1:]
        if not args:
            continue
        sub, rest = args[0], args[1:]
        if sub == "push":
            if any(a in ("--force", "-f") or (a.startswith("-") and not a.startswith("--") and "f" in a[1:])
                   for a in rest):
                deny("Force-push is blocked by .claude/hooks/guard_bash.py. Use --force-with-lease on your "
                     "own branch only if history must change.")
            targets = [a.split(":")[-1].removeprefix("refs/heads/").lstrip("+") for a in rest if not a.startswith("-")]
            refspecs = targets[1:] if len(targets) > 1 else []
            if any(t in PROTECTED_BRANCHES for t in refspecs) or (not refspecs and current_branch() in PROTECTED_BRANCHES):
                deny("Pushing to main/master is blocked. Push a branch and open a pull request; the "
                     "quality gate (python -m tools.ci.check) must pass in CI.")
        elif sub == "commit":
            bad = [f for f in staged_files() if SECRET_STAGED.search(f)]
            if bad:
                deny(f"Commit blocked: local-only or secret files are staged: {', '.join(bad[:5])}. "
                     f"Unstage them (git restore --staged <file>).")


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        return
    if payload.get("tool_name") == "Bash":
        check(str(payload.get("tool_input", {}).get("command", "")))


if __name__ == "__main__":
    main()
