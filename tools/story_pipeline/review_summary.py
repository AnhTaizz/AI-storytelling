"""Collect filled review forms into one table (evidence for the M1/M9 script-quality gate).

Every run writes review_form.md; the owner fills it (by hand or with review.html's copy
button) and the agent may fill one too. Only the owner's forms count as the human verdict
the Script Quality Contract asks for, so the two are kept apart.

    python -m tools.story_pipeline.review_summary [root ...] [--out review_summary.md]

The default roots are .local/story_pipeline_runs and .local/story_seasons.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional, Sequence

REPO = Path(__file__).resolve().parents[2]
DEFAULT_ROOTS = (REPO / ".local" / "story_pipeline_runs", REPO / ".local" / "story_seasons")
VERDICTS = ("Dùng được ngay", "Sửa nhẹ", "Sửa nhiều", "Không dùng được")
_ROW = re.compile(r"^\|\s*([a-z_]+)\s*\|[^|]*\|\s*([1-5])?\s*\|")


def parse_form(text: str) -> Dict[str, Any]:
    """Scores per question, the verdict and who scored, from one review_form.md."""
    scores: Dict[str, int] = {}
    for line in text.splitlines():
        match = _ROW.match(line)
        if match and match.group(2):
            scores[match.group(1)] = int(match.group(2))
    verdict = next((v for v in VERDICTS if f"☑ {v}" in text), None)
    if re.search(r"Người chấm:\s*Claude|agent AI", text):
        reviewer = "agent"
    elif scores or verdict:
        reviewer = "owner"
    else:
        reviewer = None
    return {"scores": scores, "verdict": verdict, "reviewer": reviewer}


_QUOTE = re.compile(r'["“”„«»]([^"“”„«»]+)["“”„«»]')
_ARROW = re.compile(r"\s*(?:→|->|=>)\s*")


def parse_errors(text: str) -> List[Dict[str, Optional[str]]]:
    """The reviewer's error list ("Lỗi cụ thể") from one review_form.md.

    Each line is `- "câu trong kịch bản" → vì sao sai`. The quote is what a correction round
    edits; a line without a quote is a general note (quote None) that no round can apply.
    """
    errors: List[Dict[str, Optional[str]]] = []
    inside = False
    for line in text.splitlines():
        if line.startswith("Lỗi cụ thể"):
            inside = True
            continue
        if not inside:
            continue
        if line.startswith("Kết luận"):
            break
        item = re.sub(r"^\s*[-*]\s*", "", line).strip()
        if not item:
            continue
        match = _QUOTE.search(item)
        quote = match.group(1).strip() if match else None
        rest = item[match.end():] if match else item
        why = _ARROW.sub("", rest, count=1).strip() if match else rest
        errors.append({"quote": quote or None, "why": why or None})
    return errors


def collect(roots: Sequence[Path]) -> List[Dict[str, Any]]:
    forms = []
    for root in roots:
        if not root.is_dir():
            continue
        # review_form_reviewed_N.md: a filled form kept when a later run rewrote the form.
        for path in sorted(root.rglob("review_form*.md")):
            parsed = parse_form(path.read_text(encoding="utf-8"))
            if parsed["reviewer"] is not None:
                run = path.parent.relative_to(root.parent).as_posix()  # same label on Windows and Linux
                forms.append({"run": run if path.name == "review_form.md" else f"{run} ({path.stem})", **parsed})
    return forms


def summary_markdown(forms: Sequence[Dict[str, Any]]) -> str:
    keys = sorted({k for f in forms for k in f["scores"]})
    lines = ["# Tổng hợp phiếu chấm kịch bản", ""]
    for reviewer, title in (("owner", "Chủ dự án (tính cho cổng chất lượng M1)"),
                            ("agent", "Agent (tham khảo, không tính)")):
        group = [f for f in forms if f["reviewer"] == reviewer]
        lines += [f"## {title}", ""]
        if not group:
            lines += ["Chưa có phiếu nào.", ""]
            continue
        lines += ["| Lần chạy | " + " | ".join(keys) + " | Kết luận |", "|---" * (len(keys) + 2) + "|"]
        for form in group:
            cells = [str(form["scores"].get(k, "")) for k in keys]
            lines.append(f"| {form['run']} | " + " | ".join(cells) + f" | {form['verdict'] or ''} |")
        averages = [_avg([f["scores"].get(k) for f in group]) for k in keys]
        lines.append("| **Trung bình** | " + " | ".join(averages) + " | |")
        counts = {v: sum(1 for f in group if f["verdict"] == v) for v in VERDICTS}
        lines += ["", "Kết luận: " + ", ".join(f"{v}: {n}" for v, n in counts.items()), ""]
    return "\n".join(lines)


def _avg(values: Sequence[Optional[int]]) -> str:
    present = [v for v in values if v is not None]
    return f"{mean(present):.1f}" if present else ""


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("roots", nargs="*", type=Path, default=list(DEFAULT_ROOTS))
    parser.add_argument("--out", type=Path, default=None, help="write the summary here instead of printing it")
    args = parser.parse_args(argv)
    text = summary_markdown(collect(args.roots))
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
