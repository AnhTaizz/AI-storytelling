"""Tests for tools/story_pipeline/prepare_source.py: preparing raw chapter files for M3."""
import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.story_pipeline import prepare_source  # noqa: E402
from tools.story_pipeline.source import load_scope  # noqa: E402

# An original Korean passage; every paragraph ends with a single line break.
KOREAN_LINES = [
    "1화 비 오는 날의 편의점",
    "서지우가 그 애를 처음 본 것은, 장대비가 쏟아지던 금요일 저녁이었다.",
    "편의점 처마 밑에 한 여학생이 우산도 없이 서 있었다.",
    "“거기서 뭐 해?”",
    "지우가 묻자 소연은 고개를 들었다.",
    "“버스를 놓쳤을 뿐이에요.”",
]
ONE_LINE_PER_PARAGRAPH = "\n".join(KOREAN_LINES) + "\n"
BLANK_LINE_PARAGRAPHS = "\n\n".join(KOREAN_LINES) + "\n"
HARD_WRAPPED = "\n".join(["The rain had been falling since the early", "morning and nobody on the street seemed",
                          "to mind it very much, least of all the", "girl who stood under the awning with",
                          "no umbrella and no hurry at all."]) + "\n"


class LayoutTests(unittest.TestCase):
    def test_layout_decision(self):
        cases = [
            ("blank lines between paragraphs", BLANK_LINE_PARAGRAPHS, "auto", "keep", False),
            ("one line per paragraph", ONE_LINE_PER_PARAGRAPH, "auto", "lines", True),
            ("hard-wrapped prose is not split", HARD_WRAPPED, "auto", "keep", True),
            ("forced split", HARD_WRAPPED, "lines", "lines", True),
            ("forced keep", ONE_LINE_PER_PARAGRAPH, "keep", "keep", True),
        ]
        for label, text, requested, expected, warned in cases:
            with self.subTest(label):
                stats = prepare_source.layout_stats(text)
                self.assertEqual(prepare_source.decide_layout(stats, requested), expected)
                self.assertEqual(prepare_source.layout_warning("chapter 1", text) is not None, warned)

    def test_split_keeps_every_line_as_its_own_paragraph(self):
        prepared = prepare_source.split_lines_into_paragraphs("　첫째 줄.\r\n\r\n둘째 줄.\n셋째 줄.")
        self.assertEqual(prepared, "　첫째 줄.\n\n둘째 줄.\n\n셋째 줄.\n")
        self.assertEqual(prepare_source.layout_stats(prepared)["paragraphs"], 3)


class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raw = Path(self.tmp.name) / "in"
        self.raw.mkdir()
        self.out = Path(self.tmp.name) / "out"

    def write(self, name, text):
        (self.raw / name).write_bytes(text.encode("utf-8"))
        return self.raw / name

    def test_prepared_korean_chapters_load_through_m3_as_separate_passages(self):
        # Natural order: "ep2" comes before "ep10"; a BOM in the original is dropped.
        second = self.write("ep10.txt", BLANK_LINE_PARAGRAPHS)
        first = self.write("ep2.txt", "﻿" + ONE_LINE_PER_PARAGRAPH)
        record = prepare_source.prepare([second, first], self.out, "story-ko-test", "ko")

        scope = load_scope(self.out / "manifest.yaml", (1, 2))
        self.assertEqual(scope.source_language, "ko")
        self.assertEqual([len(c.passages) for c in scope.chapters], [len(KOREAN_LINES)] * 2)
        self.assertEqual(scope.chapters[0].passages[3].text, "“거기서 뭐 해?”")
        self.assertEqual([d["original_name"] for d in record["documents"]], ["ep2.txt", "ep10.txt"])
        self.assertEqual([d["layout"] for d in record["documents"]], ["lines", "keep"])
        self.assertEqual(record["documents"][0]["original_sha256"],
                         hashlib.sha256(first.read_bytes()).hexdigest())
        self.assertIsNone(record["documents"][0]["warning"])
        saved = json.loads((self.out / "SOURCE_PREPARATION.json").read_text(encoding="utf-8"))
        self.assertEqual(saved, record)

    def test_invalid_input_is_rejected(self):
        chapter = self.write("a.txt", ONE_LINE_PER_PARAGRAPH)
        cases = [
            ("bad layout", dict(files=[chapter], story_id="s", layout="wrap"), "layout"),
            ("bad story id", dict(files=[chapter], story_id="truyện hàn"), "story id"),
            ("no files", dict(files=[], story_id="s"), "no chapter files"),
            ("empty chapter", dict(files=[self.write("empty.txt", " \n\n")], story_id="s"), "no text"),
        ]
        for label, kwargs, message in cases:
            with self.subTest(label):
                with self.assertRaisesRegex(ValueError, message):
                    prepare_source.prepare(kwargs["files"], self.out, kwargs["story_id"], "ko",
                                           kwargs.get("layout", "auto"))

    def test_cli_reports_each_chapter(self):
        self.write("ch1.txt", ONE_LINE_PER_PARAGRAPH)
        self.write("ch2.txt", HARD_WRAPPED)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = prepare_source.main(["--input-dir", str(self.raw), "--out", str(self.out),
                                        "--story-id", "story-ko-test", "--language", "ko"])
        self.assertEqual(code, 0)
        self.assertIn("ch1.txt -> chapter_001.txt  layout=lines  passages 1 -> 6", stdout.getvalue())
        self.assertIn("warning: chapter_002.txt", stdout.getvalue())  # hard-wrapped: kept, but flagged

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = prepare_source.main(["--input-dir", str(self.raw), "--out", str(self.out),
                                        "--story-id", "bad id", "--language", "ko"])
        self.assertEqual(code, 2)
        self.assertIn("story id", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
