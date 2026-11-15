"""Tests for tools/story_pipeline/review_summary.py (collecting filled review forms)."""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.story_pipeline import review_summary  # noqa: E402
from tools.story_pipeline.run_pipeline import review_form  # noqa: E402

MANIFEST = {"run_id": "r", "scope": {"label": "chapter 1"}, "client": "c"}


def filled(scores, verdict, reviewer_line=""):
    """review_form.md as the pipeline writes it, filled in."""
    text = review_form(MANIFEST)
    for key, score in scores.items():
        text = text.replace(f"| {key} |", f"| {key} |", 1)
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if line.startswith(f"| {key} |"):
                cells = line.split("|")
                cells[3] = f" {score} "
                lines[i] = "|".join(cells)
        text = "\n".join(lines)
    text = text.replace(f"☐ {verdict}", f"☑ {verdict}")
    return reviewer_line + "\n" + text


class ReviewSummaryTests(unittest.TestCase):
    def test_forms_are_parsed_and_owner_and_agent_kept_apart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runs"
            forms = {
                "run_a": filled({"factual": 4, "hook": 2}, "Sửa nhẹ"),                         # the owner
                "run_b": filled({"factual": 2, "hook": 4}, "Sửa nhiều"),                       # the owner
                "run_c": filled({"factual": 5}, "Dùng được ngay", "**Người chấm: Claude (agent AI)**"),
                "run_d": review_form(MANIFEST),                                                # not filled
            }
            for name, text in forms.items():
                (root / name).mkdir(parents=True)
                (root / name / "review_form.md").write_text(text, encoding="utf-8")
            collected = review_summary.collect([root, Path(tmp) / "missing"])
            self.assertEqual([(f["run"], f["reviewer"]) for f in collected],
                             [("runs/run_a", "owner"), ("runs/run_b", "owner"), ("runs/run_c", "agent")])
            self.assertEqual(collected[0]["scores"], {"factual": 4, "hook": 2})
            self.assertEqual(collected[1]["verdict"], "Sửa nhiều")

            summary = review_summary.summary_markdown(collected)
            owner = summary.split("## Agent")[0]
            self.assertIn("| **Trung bình** | 3.0 | 3.0 | |", owner)
            self.assertIn("Sửa nhẹ: 1, Sửa nhiều: 1", owner)
            self.assertIn("runs/run_c", summary.split("## Agent")[1])

            out = Path(tmp) / "summary.md"
            self.assertEqual(review_summary.main([str(root), "--out", str(out)]), 0)
            self.assertEqual(out.read_text(encoding="utf-8"), summary)
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                review_summary.main([str(Path(tmp) / "empty")])
            self.assertEqual(printed.getvalue().count("Chưa có phiếu nào."), 2)

    def test_quoted_errors_are_read_from_the_form(self):
        text = review_form(MANIFEST).replace(
            "- \n", '- "Cậu dán miếng hạ nhiệt lên trán" → Mahiru dán, lúc cậu ngủ\n'
                    '* “buổi chiều”->nguồn nói 7 giờ tối\n'
                    '- Nhịp đoạn cuối hơi chậm\n', 1)
        self.assertEqual(review_summary.parse_errors(text), [
            {"quote": "Cậu dán miếng hạ nhiệt lên trán", "why": "Mahiru dán, lúc cậu ngủ"},
            {"quote": "buổi chiều", "why": "nguồn nói 7 giờ tối"},
            {"quote": None, "why": "Nhịp đoạn cuối hơi chậm"}])
        self.assertEqual(review_summary.parse_errors(review_form(MANIFEST)), [])  # blank form
        self.assertEqual(review_summary.parse_errors("no section"), [])


if __name__ == "__main__":
    unittest.main()
