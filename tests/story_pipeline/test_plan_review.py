"""Tests for tools/story_pipeline/plan_review.py (M8: plan checks and owner review)."""
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.story_pipeline import plan_review  # noqa: E402


def brief(n, events):
    return {"chapter_order": n, "chapter_summary": "Amane gặp Mahiru ở công viên.", "ending_state": "",
            "characters": [{"id": "CH1", "name": "周", "romanized_name": "Amane", "aliases": [], "facts": []}],
            "relationships": [],
            "events": [{"id": eid, "summary": text, "importance": imp, "location": None, "consequence": None,
                        "motivation": {"text": None, "status": "UNKNOWN"}, "evidence": [f"{n}.{i}"]}
                       for i, (eid, text, imp) in enumerate(events, start=1)]}


BRIEFS = [brief(2, [("E1", "Mahiru mang 3 hộp cháo tới", "CORE"), ("E2", "Amane ngủ", "SUPPORTING"),
                    ("E3", "Trời mưa", "MINOR"), ("E4", "Itsuki gọi điện", "MINOR")])]
RECAP = {"chapters": [{"core_events": [{"ref": "c1.E1", "summary": "Amane đưa ô"}]}],
         "callbacks": [{"ref": "c1.E4", "summary": "Mahiru ngồi trên xích đu", "importance": "MINOR",
                        "evidence": ["1.9"]}]}


def plan(beats, callbacks=(), hook="Mở bằng cơn mưa"):
    return {"logline": "Một bát cháo.", "hook": {"idea": hook, "event_refs": ["c2.E1"]},
            "beats": [{"id": bid, "purpose": f"mục đích {bid}", "event_refs": refs, "emotional_note": note,
                       "commentary_idea": comment, "target_words": words}
                      for bid, refs, words, note, comment in beats],
            "callbacks": [{"setup_ref": s, "payoff_ref": p, "note": "n"} for s, p in callbacks],
            "omitted_events": [], "closing_hook": None}


GOOD = plan([("B1", ["c2.E1"], 100, None, None), ("B2", ["c2.E2", "c2.E3"], 80, None, None),
             ("B3", ["c2.E4"], 40, None, None)], callbacks=[("c1.E4", "c2.E1")])


class PlanChecksTests(unittest.TestCase):
    def test_callbacks_must_set_up_before_they_pay_off(self):
        self.assertEqual(plan_review.plan_soft_errors(GOOD), [])
        for label, pair in {"later setup": ("c2.E3", "c2.E1"), "same event": ("c2.E1", "c2.E1"),
                            "later chapter": ("c3.E1", "c2.E9")}.items():
            with self.subTest(label):
                errors = plan_review.plan_soft_errors(plan([("B1", ["c2.E1"], 50, None, None)], callbacks=[pair]))
                self.assertEqual(len(errors), 1)
                self.assertIn("must come before the payoff", errors[0])

    def test_pacing_and_new_facts_are_advisory_findings(self):
        cases = [
            ("balanced", GOOD, []),
            ("thin CORE beat", plan([("B1", ["c2.E1", "c2.E2", "c2.E3"], 30, None, None),
                                     ("B2", ["c2.E4"], 200, None, None)]), ["pacing_core_thin", "pacing_minor_heavy"]),
            ("commentary beat too long", plan([("B1", ["c2.E1"], 100, None, None), ("B2", [], 100, None, None)]),
             ["pacing_minor_heavy"]),
            ("new name and number", plan([("B1", ["c2.E1"], 100, "Như Hinata lo lắng",
                                           "Cô mang 5 hộp cháo cho Amane")]), ["new_name", "new_number"]),
            ("known name, cited number, sentence start", plan([("B1", ["c2.E1"], 100, "Mahiru mang 3 hộp",
                                                                "Thật dễ thương. Amane vui")]), []),
        ]
        for label, candidate, kinds in cases:
            with self.subTest(label):
                found = plan_review.plan_checks(candidate, BRIEFS, RECAP)["findings"]
                self.assertEqual(sorted(f["kind"] for f in found), sorted(kinds), found)
        glossary = {"characters": [{"display": "Hinata", "also_allowed": []}]}
        named = plan([("B1", ["c2.E1"], 100, "Như Hinata lo lắng", None)])
        self.assertEqual(plan_review.plan_checks(named, BRIEFS, RECAP, glossary)["findings"], [])

    def test_coverage_counts_core_supporting_and_retrieved_callbacks(self):
        coverage = plan_review.plan_checks(GOOD, BRIEFS, RECAP)["coverage"]
        self.assertEqual(coverage, {"core": 1, "core_covered": 1, "supporting": 1, "supporting_used": 1,
                                    "callbacks": 1, "callbacks_from_retrieval": ["c1.E4"]})
        scanned = plan_review.scan([("run-a", GOOD, BRIEFS, RECAP),
                                    ("run-b", plan([("B1", ["c2.E1"], 50, None, None)], callbacks=[("c2.E3", "c2.E1")]),
                                     BRIEFS, None)])
        self.assertEqual(list(scanned), ["callback_order"])
        self.assertEqual(scanned["callback_order"][0][0], "run-b")


class PlanReviewTests(unittest.TestCase):
    def test_an_unchanged_form_is_no_review_and_edits_are_applied(self):
        form = plan_review.plan_review_form(GOOD)
        self.assertEqual(plan_review.plan_review_edits(GOOD, plan_review.parse_plan_review(form)), [])
        filled = (form.replace("`B3` bỏ: [ ]", "`B3` bỏ: [x]")
                  .replace("`B1` bỏ: [ ]", "`B1` bỏ: [x]")
                  .replace("vị trí: 2 | số từ: 80 | ghi chú: ", "vị trí: 1 | số từ: 120 | ghi chú: nhấn vào giấc ngủ"))
        edits = plan_review.plan_review_edits(GOOD, plan_review.parse_plan_review(filled))
        self.assertEqual([e["beat"] for e in edits], ["B1", "B2", "B3"])
        events = plan_review.event_texts(BRIEFS, RECAP)
        reviewed, report = plan_review.apply_plan_review(GOOD, edits + [{"beat": "B9", "drop": False, "position": 1,
                                                                          "words": 50, "note": None}], events)
        self.assertEqual([b["id"] for b in reviewed["beats"]], ["B2", "B1"])  # B3 dropped, B2 moved first
        self.assertEqual(reviewed["beats"][0]["target_words"], 120)
        self.assertIn("Ghi chú người duyệt: nhấn vào giấc ngủ", reviewed["beats"][0]["purpose"])
        self.assertEqual({r["beat"]: r["reason"].split()[0] for r in report["rejected"]}, {"B1": "the", "B9": "no"})
        self.assertEqual({c["change"] for c in report["changes"]}, {"dropped", "words", "note", "moved"})
        self.assertEqual(GOOD["beats"][0]["id"], "B1")  # the input plan is untouched
        short = plan_review.apply_plan_review(GOOD, [{"beat": "B2", "drop": False, "position": 2, "words": 5,
                                                       "note": None}], events)[1]
        self.assertIn("at least 20", short["rejected"][0]["reason"])

    def test_dropping_the_payoff_beat_drops_its_callback(self):
        with_cb = plan([("B1", ["c2.E1"], 100, None, None), ("B2", ["c2.E3"], 40, None, None)],
                       callbacks=[("c1.E4", "c2.E3"), ("c1.E1", "c2.E1")])
        reviewed, _ = plan_review.apply_plan_review(
            with_cb, [{"beat": "B2", "drop": True, "position": 2, "words": 40, "note": None}],
            plan_review.event_texts(BRIEFS, RECAP))
        self.assertEqual([c["payoff_ref"] for c in reviewed["callbacks"]], ["c2.E1"])

    def test_review_pages_show_beats_events_and_findings(self):
        events = plan_review.event_texts(BRIEFS, RECAP)
        flagged = plan([("B1", ["c2.E1"], 100, "Như Hinata lo lắng", None)], callbacks=[("c1.E4", "c2.E1")])
        checks = plan_review.plan_checks(flagged, BRIEFS, RECAP)
        page = plan_review.render_html(flagged, checks, events)
        self.assertIn("class='flag'", page)
        self.assertIn("Mahiru mang 3 hộp cháo tới", page)
        self.assertIn("[2.1]", page)
        text = plan_review.render_markdown(flagged, checks, events)
        self.assertIn("`c1.E4` → `c2.E1`", text)
        self.assertIn("\"Hinata\" is in no brief", text)
        self.assertIn("Không có.", plan_review.render_markdown(GOOD, plan_review.plan_checks(GOOD, BRIEFS, RECAP), events))


if __name__ == "__main__":
    unittest.main()
