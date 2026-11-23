"""Script Quality Gate review kit: form contents, verdicts per contract sections 15-16, and the
protocol's gate rule. Runs are synthetic; no model is called."""
import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from tools.story_pipeline import gate_review as gr

FINDING = {"claim": "Cô ấy nổi tiếng khắp trường.", "claim_type": "STRENGTHENED_STORY_CLAIM",
           "failure_category": "EPISTEMIC_ERROR", "severity": "MEDIUM", "brief_refs": ["c6.E1"],
           "explanation": "Brief không nói nổi tiếng.", "suggested_fix": "Bỏ từ nổi tiếng"}


def make_run(root: Path, name="ep1", findings=(FINDING,), check=None) -> Path:
    run = root / name
    run.mkdir(parents=True)
    profile = {"profile_id": "VI_YOUTUBE_CASUAL_V0", "target_language": "vi", "narration": "ngôi thứ ba",
               "tone": "gần gũi", "humor_level": "light", "commentary_intensity": "medium",
               "hook_style": "curiosity-first", "min_words": 900, "max_words": 1100}
    (run / "run_manifest.json").write_text(json.dumps({
        "run_id": name, "client": "gemini:test", "background_chapters": [1, 2, 3, 4, 5],
        "scope": {"label": "chapters 6-8", "chapters": [6, 7, 8]}, "profile": profile}), encoding="utf-8")
    final = {"word_count": 1000, "length_ok": True, "length_target": [900, 1100], "foreign_script_count": 0,
             "artifacts": []}
    final.update(check or {})
    (run / "report.json").write_text(json.dumps({"findings": list(findings), "undetermined": [],
                                                 "final_check": final}), encoding="utf-8")
    return run


def fill(text, *, kind="người", decisions=None, audit=True, ratings=None, cost="MINIMAL", local_fix="có",
         extra=None, evidence=True):
    """A filled copy of a generated form; arguments mirror what a reviewer writes."""
    text = text.replace("- Người chấm: ", "- Người chấm: Owner").replace(
        "- Loại người chấm (người/AI): ", f"- Loại người chấm (người/AI): {kind}")
    text = text.replace("- Chi phí sửa: ", f"- Chi phí sửa: {cost}").replace(
        "- Mọi lỗi còn lại đều sửa tại chỗ được (có/không): ",
        f"- Mọi lỗi còn lại đều sửa tại chỗ được (có/không): {local_fix}")
    for number, decision in (decisions or {}).items():
        text = re.sub(rf"^\| {number} \| (critic|máy) \|  \|", rf"| {number} | \1 | {decision} |", text, flags=re.M)
    if audit:
        text = re.sub(r"^\| (FACTUAL|EPISTEMIC|TEMPORAL|SPOILER|COVERAGE) \| ([^|]+) \|  \|",
                      r"| \1 | \2 | có |", text, flags=re.M)
    scores = {dim: 4 for dim in gr.DIMENSION_LABELS}
    scores.update(ratings or {})
    for dim, score in scores.items():
        quote, reason = ("“một câu”", "lý do") if evidence else ("", "")
        text = re.sub(rf"^\| ([^|]+) \| {dim} \| \| \| \|", rf"| \1 | {dim} | {score} | {quote} | {reason} |",
                      text, flags=re.M)
    if extra:
        text = re.sub(r"^\| (\d+) \| người chấm \| \| \| \| \| \| \| \| \|$",
                      lambda m: f"| {m[1]} | người chấm | có | {extra}", text, count=1, flags=re.M)
    return text


class FormWritingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_request_record_and_candidates_come_from_the_run(self):
        run = make_run(self.root, check={"length_ok": False, "word_count": 700, "foreign_script_count": 2,
                                         "foreign_script_sample": "天使"})
        text = (gr.write_forms([run])[0]).read_text(encoding="utf-8")
        for expected in ("thông tin được phép tới hết chương 8", "tóm tắt chương 1–5 từ story memory",
                         "900–1100 từ", "đếm được 700", "NONE: không gì sau chương 8", "gemini:test",
                         gr.FORM_VERSION):
            self.assertIn(expected, text)
        rows = [line for line in text.splitlines() if re.match(r"^\| \d+ \| (critic|máy) ", line)]
        self.assertEqual([row.split("|")[4].strip() for row in rows], ["EPISTEMIC", "REQUEST", "OUTPUT"])
        with self.assertRaises(FileExistsError):
            gr.write_forms([run])
        self.assertEqual(len(gr.write_forms([run], force=True)), 1)

    def test_a_season_expands_to_its_episodes(self):
        season = self.root / "season"
        for name in ("ep1", "ep2"):
            make_run(season, name)
        (season / "season.json").write_text(json.dumps({"episodes": [{"dir": "ep1"}, {"dir": "ep2"}, {}]}),
                                            encoding="utf-8")
        self.assertEqual([p.parent.name for p in gr.write_forms([season])], ["ep1", "ep2"])
        with self.assertRaisesRegex(ValueError, "not a run or season"):
            gr.write_forms([self.root / "nothing"])


class VerdictTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.form = gr.render_form(gr.request_record(make_run(Path(temporary.name))))

    def score(self, **options):
        return gr.score_review(gr.parse_form(fill(self.form, **options)))

    def test_verdicts_follow_the_contract_order(self):
        own_high = "FACTUAL | UNSUPPORTED_INVENTION | HIGH | “câu bịa” | absent | không có trong nguồn | bỏ |"
        own_critical = "SPOILER | PREMATURE_SPOILER | CRITICAL | “chương 30” | absent | lộ kết | bỏ |"
        cases = (
            ("clean", {"decisions": {1: "không"}}, "PASS", "PASS"),
            ("confirmed medium", {"decisions": {1: "có"}, "cost": "MODERATE"},
             "PASS_WITH_MINOR_EDITS", "PASS_WITH_MINOR_EDITS"),
            ("medium with minimal cost", {"decisions": {1: "có"}}, "PASS_WITH_MINOR_EDITS", "PASS_WITH_MINOR_EDITS"),
            ("own high finding", {"decisions": {1: "không"}, "extra": own_high}, "FAIL", "FAIL"),
            ("critical spoiler", {"decisions": {1: "không"}, "extra": own_critical}, "FAIL", "FAIL"),
            ("ai reviewer", {"decisions": {1: "không"}, "kind": "AI"}, "PASS", "REVIEW_REQUIRED"),
            ("ai reviewer high finding", {"decisions": {1: "không"}, "kind": "AI", "extra": own_high},
             "FAIL", "REVIEW_REQUIRED"),
            ("candidate left open", {}, "REVIEW_REQUIRED", "REVIEW_REQUIRED"),
            ("gates not audited", {"decisions": {1: "không"}, "audit": False}, "REVIEW_REQUIRED", "REVIEW_REQUIRED"),
            ("weak dimension", {"decisions": {1: "không"}, "ratings": {"PACING": 2}},
             "REVIEW_REQUIRED", "REVIEW_REQUIRED"),
            ("usefulness 3", {"decisions": {1: "không"}, "ratings": {"OVERALL_USEFULNESS": 3}},
             "PASS_WITH_MINOR_EDITS", "PASS_WITH_MINOR_EDITS"),
            ("not applicable humor", {"decisions": {1: "không"}, "ratings": {"HUMOR_COMMENTARY_QUALITY": "N/A"}},
             "PASS", "PASS"),
            ("no local fix", {"decisions": {1: "có"}, "cost": "MODERATE", "local_fix": "không"},
             "REVIEW_REQUIRED", "REVIEW_REQUIRED"),
            ("major cost", {"decisions": {1: "không"}, "cost": "MAJOR"}, "REVIEW_REQUIRED", "REVIEW_REQUIRED"),
            ("rewrite", {"decisions": {1: "không"}, "cost": "REWRITE"}, "FAIL", "FAIL"),
        )
        for name, options, trace, official in cases:
            with self.subTest(name):
                result = self.score(**options)
                self.assertEqual(result["errors"], [])
                self.assertEqual((result["trace_verdict"], result["official_verdict"]), (trace, official))

    def test_incomplete_forms_get_no_verdict(self):
        cases = (
            ("rating without evidence", {"evidence": False}, "needs a quoted passage"),
            ("callback-free hook", {"ratings": {"HOOK_STRENGTH": "N/A"}}, "HOOK_STRENGTH cannot be N/A"),
            ("unknown edit cost", {"cost": "SOME"}, "edit cost"),
            ("reviewer kind", {"kind": ""}, "reviewer kind"),
            ("finding without severity", {"extra": "FACTUAL | FACTUAL_ERROR | | “câu” | absent | sai | |"},
             "needs a severity"),
            ("finding without passage", {"extra": " | FACTUAL_ERROR | LOW | | absent | sai | |"}, "script passage"),
            ("finding with unknown gate", {"extra": "PLOT | | LOW | “câu” | absent | sai | |"}, "needs a gate"),
            ("local fix unanswered", {"decisions": {1: "có"}, "local_fix": ""}, "local fix"),
        )
        for name, options, message in cases:
            with self.subTest(name):
                result = self.score(**{"decisions": {1: "không"}, **options})
                self.assertEqual(result["status"], "INCOMPLETE")
                self.assertTrue(any(message in error for error in result["errors"]), result["errors"])
        self.assertEqual(gr.parse_form("# not a form").errors, [f"not a {gr.FORM_VERSION} form"])
        own_row = self.form.replace("| 2 | người chấm | | | | | | | | |",
                                    "| 2 | người chấm | ? | FACTUAL | FACTUAL_ERROR | LOW | “câu” | absent | sai | |")
        self.assertIn("finding 2: Xác nhận must be có or không", gr.parse_form(fill(own_row)).errors)


class GateRuleTests(unittest.TestCase):
    def result(self, verdict, kind="human", status="SCORED", severity=None):
        findings = [{"severity": severity}] if severity else []
        return {"form": "f", "status": status, "reviewer_kind": kind, "official_verdict": verdict,
                "findings": findings, "edit_cost": "MINIMAL"}

    def test_the_protocol_rule(self):
        p, m, r, f = "PASS", "PASS_WITH_MINOR_EDITS", "REVIEW_REQUIRED", "FAIL"
        cases = (
            ("all pass", [self.result(v) for v in (p, m, m, p)], "PASS"),
            ("three of four", [self.result(v) for v in (p, m, m, r)], "PASS"),
            ("two of four", [self.result(v) for v in (p, m, r, r)], "FAIL"),
            ("one fail", [self.result(v) for v in (p, p, p, f)], "FAIL"),
            ("critical finding", [self.result(p), self.result(p), self.result(p), self.result(m, severity="CRITICAL")],
             "FAIL"),
            ("sample too small", [self.result(p) for _ in range(3)], "NOT_EVALUATED"),
            ("incomplete form", [self.result(p) for _ in range(3)] + [self.result(None, status="INCOMPLETE")],
             "NOT_EVALUATED"),
            ("ai form", [self.result(p) for _ in range(3)] + [self.result(p, kind="ai")], "NOT_EVALUATED"),
        )
        for name, results, outcome in cases:
            with self.subTest(name):
                self.assertEqual(gr.gate_result(results)["outcome"], outcome)


class LockTests(unittest.TestCase):
    def test_lock_freezes_chapter_hashes_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for order in (1, 2, 3):
                (root / f"chapter_{order}.txt").write_text(f"chương {order}", encoding="utf-8")
            documents = [{"order": o, "path": f"chapter_{o}.txt"} for o in (3, 1, 2)]
            (root / "m.json").write_text(json.dumps({"documents": documents}), encoding="utf-8")
            (root / "m.yaml").write_text(json.dumps({"documents": documents}), encoding="utf-8")
            (root / "profile.yaml").write_text("profile_id: P", encoding="utf-8")
            base = ["--profile", str(root / "profile.yaml"), "--model", "gemini-x", "--run-command", "run_story ..."]
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(gr.main(["lock", str(root / "s1"), "--manifest", str(root / "m.json"),
                                          "--last-chapter", "2", *base]), 0)
                self.assertEqual(gr.main(["lock", str(root / "s1"), "--manifest", str(root / "m.json"),
                                          "--last-chapter", "2", *base]), 2)
                self.assertEqual(gr.main(["lock", str(root / "s2"), "--manifest", str(root / "m.yaml"),
                                          "--last-chapter", "4", *base]), 2)
                with self.assertRaises(SystemExit):
                    gr.main(["lock", str(root / "s3")])
            lock = json.loads((root / "s1/gate_lock.json").read_text(encoding="utf-8"))
            self.assertEqual(sorted(lock["chapter_sha256"]), ["1", "2"])
            self.assertEqual((lock["model"], lock["protocol"]), ("gemini-x", gr.PROTOCOL_ID))
            self.assertFalse((root / "s2/gate_lock.json").exists())


class CommandLineTests(unittest.TestCase):
    def test_form_score_and_summary_over_a_season(self):
        with tempfile.TemporaryDirectory() as directory:
            season = Path(directory) / "season"
            for name in ("ep1", "ep2", "ep3", "ep4"):
                make_run(season, name)
            (season / "season.json").write_text(json.dumps({"episodes": [{"dir": f"ep{i}"} for i in range(1, 5)]}),
                                                encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(gr.main(["form", str(season)]), 0)
                self.assertEqual(gr.main(["form", str(season)]), 2)
                self.assertEqual(gr.main(["score", str(season)]), 1)
                for i in range(1, 5):
                    form = season / f"ep{i}" / gr.FORM_NAME
                    form.write_text(fill(form.read_text(encoding="utf-8"), decisions={1: "không"}), encoding="utf-8")
                self.assertEqual(gr.main(["score", str(season)]), 0)
                self.assertEqual(gr.main(["summary", str(season), "--out", str(season / "gate")]), 0)
            summary = json.loads((season / "gate/gate_summary.json").read_text(encoding="utf-8"))
            self.assertEqual((summary["gate"]["outcome"], summary["gate"]["passed"]), ("PASS", 4))
            self.assertIn("Kết quả Script Quality Gate — PASS", (season / "gate/gate_summary.md").read_text(encoding="utf-8"))
            self.assertTrue((season / "ep1" / gr.RESULT_NAME).is_file())
            (season / "ep4" / gr.FORM_NAME).unlink()
            with contextlib.redirect_stdout(io.StringIO()):
                gr.main(["summary", str(season)])
            self.assertEqual(gr.score_forms([season])[-1]["status"], "MISSING")


if __name__ == "__main__":
    unittest.main()
