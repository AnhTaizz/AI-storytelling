"""Conventions V4 checker: R-TIME-03 and development alignment of event dates."""
from copy import deepcopy
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest

from tests.story_extraction.test_draft_date_anchor_v1 import SECOND, date_case
from tools.story_extraction import check_annotation_conventions_v3 as v3
from tools.story_extraction.evaluate_extraction_v0 import validate_batch


def findings(report, rule=v3.RULE):
    return [f for f in report["findings"] if f["rule"] == rule]


class ConventionsV3CheckerTests(unittest.TestCase):
    def setUp(self):
        _, case, self.gold = date_case()
        self.context = case.compiler_context
        self.sources = [doc.source_bytes for doc in self.context.ingestion.documents]

    def test_flags_only_a_date_in_the_sentence_of_exactly_one_event(self):
        cases = (("one event", {}, 1), ("no event", dict(date_sentence=SECOND, second_event_in_first=True), 0),
                 ("several events", dict(second_event_in_first=True), 0))
        for name, options, expected in cases:
            with self.subTest(name):
                _, case, gold = date_case(**options)
                report = v3.check_batch(gold, self.sources, case.compiler_context.base_document)
                self.assertEqual(report["counts"][v3.RULE], expected)
                self.assertEqual(len(findings(report)), expected)
                self.assertIn(v3.RULE, report["rules_checked"])
                self.assertEqual(set(v3.RULES) - {v3.RULE}, set(v3.v2.RULES))
        negated = deepcopy(self.gold)
        for assertion in negated["candidate_records"]["assertions"]:
            assertion["polarity"] = "NEGATED"
        self.assertEqual(v3.check_batch(negated, self.sources)["counts"][v3.RULE], 0)

    def test_alignment_moves_dates_bounds_and_relations_in_a_copy(self):
        before = deepcopy(self.gold)
        aligned, report = v3.align_date_anchors(self.gold, self.sources, self.context.base_document)
        self.assertEqual(self.gold, before)
        self.assertEqual(report, {"flagged": 1, "aligned": 1, "refused": {}, "relations_dropped": 1,
                                  "anchors_dropped": 1, "duplicates_dropped": 0})
        records = aligned["candidate_records"]
        self.assertEqual([t["anchor_kind"] for t in records["temporal_anchors"]], ["EVENT_TIME", "EVENT_TIME"])
        props = {p["id"]: p for p in records["propositions"]}
        self.assertNotIn("TemporalRelation", {p["predicate"] for p in props.values()})
        self.assertEqual(v3.check_batch(aligned, self.sources)["counts"][v3.RULE], 0)
        self.assertTrue(validate_batch(aligned, self.context.base_document, self.context.ingestion)["pass"])

        _, _, duplicate = date_case(event_date="--04-01")
        aligned, report = v3.align_date_anchors(duplicate, self.sources)
        self.assertEqual(report["duplicates_dropped"], 1)
        dates = [p for p in aligned["candidate_records"]["propositions"] if p["predicate"] == "AnchorDate"]
        self.assertEqual(len(dates), 1)

        moved_to_base = deepcopy(self.gold)
        named = next(t for t in moved_to_base["candidate_records"]["temporal_anchors"]
                     if t["anchor_kind"] == "NAMED_TIME")
        moved_to_base["candidate_records"]["temporal_anchors"].remove(named)
        base = {"temporal_anchors": [named]}
        aligned, report = v3.align_date_anchors(moved_to_base, self.sources, base)
        self.assertEqual((report["aligned"], report["refused"]), (0, {"REFUSED_BASE": 1}))
        self.assertEqual(aligned, moved_to_base)

    def test_cli_reports_and_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "b.json").write_text(json.dumps(self.gold), encoding="utf-8")
            (root / "s.txt").write_bytes(self.sources[0])
            self.assertEqual(v3.main(["--batch", str(root / "b.json"), "--source", str(root / "s.txt"),
                                      "--out", str(root / "r.json")]), 0)
            self.assertEqual(json.loads((root / "r.json").read_text(encoding="utf-8"))["counts"][v3.RULE], 1)
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(v3.main(["--batch", str(root / "b.json"), "--source", str(root / "s.txt")]), 0)
            self.assertIn(v3.RULE, out.getvalue())
            (root / "bad.txt").write_bytes(b"other")
            self.assertEqual(v3.main(["--batch", str(root / "b.json"), "--source", str(root / "bad.txt")]), 2)


if __name__ == "__main__":
    unittest.main()
