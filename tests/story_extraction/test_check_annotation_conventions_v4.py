"""Conventions V5 checker: R-EVR-02, a mention outside dialogue takes the role of its sentence."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from tests.story_extraction import fixture_builder as fx
from tools.story_extraction import check_annotation_conventions_v4 as v4

TEXT = "ミラは毎年門を磨いた。「ノアが来た」とミラは言った。"


def batch(mention_role="DEPICTION", sentence_role="NARRATION_SUMMARY", dialogue_role="DEPICTION",
          extra_depiction=False):
    ingestion, base = fx.ingest_text(TEXT)
    b = fx.Builder(ingestion, base)
    b.named(1, "ミラ", role=mention_role)
    event, _ = b.event("GENERIC")
    b.occurred(event, 1, "ミラは毎年門を磨いた", role=sentence_role)
    if extra_depiction:
        other, _ = b.event("GENERIC")
        b.occurred(other, 1, "門を磨いた", role="DEPICTION")
    b.named(1, "ノア", role=dialogue_role)
    said, _ = b.event("UTTERANCE")
    b.occurred(said, 1, "「ノアが来た」とミラは言った", role="DEPICTION")
    return b.batch(), [doc.source_bytes for doc in ingestion.documents], base


class ConventionsV4CheckerTests(unittest.TestCase):
    def test_mention_role_must_match_a_single_sentence_role_outside_dialogue(self):
        cases = (
            ("depicted mention in a summary sentence", {}, 1),
            ("mention takes the summary role", {"mention_role": "NARRATION_SUMMARY"}, 0),
            ("retrospective sentence", {"sentence_role": "RETROSPECTIVE"}, 1),
            ("depicted sentence", {"sentence_role": "DEPICTION"}, 0),
            ("mixed roles in the sentence", {"extra_depiction": True}, 0),
            ("dialogue mention is exempt", {"mention_role": "NARRATION_SUMMARY",
                                            "dialogue_role": "IN_WORLD_REPORT"}, 0),
        )
        for name, options, expected in cases:
            with self.subTest(name):
                gold, sources, base = batch(**options)
                report = v4.check_batch(gold, sources, base)
                self.assertEqual(report["counts"][v4.RULE], expected)
                self.assertEqual(sum(f["rule"] == v4.RULE for f in report["findings"]), expected)
                self.assertEqual(report["rules_checked"], list(v4.RULES))
                self.assertTrue(set(v4.v3.RULES) < set(v4.RULES))

    def test_cli_reports_and_refuses(self):
        gold, sources, _ = batch()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "b.json").write_text(json.dumps(gold), encoding="utf-8")
            (root / "s.txt").write_bytes(sources[0])
            self.assertEqual(v4.main(["--batch", str(root / "b.json"), "--source", str(root / "s.txt"),
                                      "--out", str(root / "r.json")]), 0)
            self.assertEqual(json.loads((root / "r.json").read_text(encoding="utf-8"))["counts"][v4.RULE], 1)
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(v4.main(["--batch", str(root / "b.json"), "--source", str(root / "s.txt")]), 0)
            self.assertIn(v4.RULE, out.getvalue())
            (root / "bad.txt").write_bytes(b"other")
            self.assertEqual(v4.main(["--batch", str(root / "b.json"), "--source", str(root / "bad.txt")]), 2)


if __name__ == "__main__":
    unittest.main()
