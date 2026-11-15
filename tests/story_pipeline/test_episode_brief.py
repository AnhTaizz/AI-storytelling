"""Tests for tools/story_pipeline/episode_brief.py (the reviewable episode Story Brief, M7)."""
import copy
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_story_pipeline_v0 import brief_json  # noqa: E402  (shared fixture)

from tools.story_pipeline import episode_brief  # noqa: E402


class Scope:
    story_id = "story-x"

    @staticmethod
    def label():
        return "chapters 2-3"


def briefs():
    two, three = brief_json(2), brief_json(3)
    three["characters"][0]["facts"].append({"text": "Nghe nói anh sống một mình", "evidence": ["3.2"], "quote": "q",
                                            "epistemic": "REPORTED"})
    return [three, two]


RECAP = {"chapters": [{"chapter": 1, "core_events": [{"ref": "c1.E1", "summary": "Gặp nhau dưới mưa"}]}],
         "callbacks": [{"ref": "c1.E2", "summary": "Amane đưa ô", "evidence": ["1.2"]}],
         "relationships": []}
GLOSSARY = {"characters": [{"display": "Fujimiya Amane", "also_allowed": ["Amane"], "source_names": ["藤宮周"]}]}


class EpisodeBriefTests(unittest.TestCase):
    def test_the_episode_brief_keeps_refs_evidence_uncertainty_and_background(self):
        episode = episode_brief.build_episode_brief(Scope(), briefs(), RECAP, GLOSSARY)
        self.assertEqual(episode["format"], "EPISODE_STORY_BRIEF/v1")
        self.assertEqual(episode["scope"], {"story_id": "story-x", "label": "chapters 2-3", "chapters": [2, 3],
                                            "spoiler_cutoff": 3})
        self.assertEqual([c["chapter"] for c in episode["chapters"]], [2, 3])  # chapter order
        chapter = episode["chapters"][1]
        self.assertEqual(chapter["events"][0]["ref"], "c3.E1")
        self.assertEqual(chapter["characters"][0]["display"], "Fujimiya Amane")  # glossary name
        self.assertEqual(chapter["characters"][1]["display"], "Mahiru")          # not in the glossary
        self.assertEqual([f["ref"] for f in chapter["characters"][0]["facts"]], ["c3.CH1.F1", "c3.CH1.F2"])
        self.assertEqual(chapter["relationships"][0]["between"], ["Fujimiya Amane", "Mahiru"])
        self.assertEqual([(u["ref"], u["epistemic"]) for u in episode["uncertain"]], [("c3.CH1.F2", "REPORTED")])
        self.assertEqual(episode["background"]["callbacks"][0]["ref"], "c1.E2")
        self.assertEqual(episode["counts"]["uncertain"], 1)
        self.assertIsNone(episode_brief.build_episode_brief(Scope(), briefs(), None)["background"])

    def test_renderings_show_every_item_with_its_sources(self):
        episode = episode_brief.build_episode_brief(Scope(), briefs(), RECAP)
        markdown = episode_brief.render_markdown(episode)
        for expected in ("## Chương 2", "`c3.CH1.F2` Nghe nói anh sống một mình _[REPORTED]_",
                         "## Mục chưa chắc chắn", "## Bối cảnh từ các chương trước", "### Không được suy ra",
                         "Sự kiện cũ có thể gài lại"):
            with self.subTest(expected):
                self.assertIn(expected, markdown)
        page = episode_brief.render_html(episode, {"3.2": "<script>bad</script> nguồn"})
        self.assertIn("id='c3.CH1.F2'", page)
        self.assertIn("&lt;script&gt;bad&lt;/script&gt; nguồn", page)  # source text is escaped
        self.assertIn("class='uncertain'", page)
        self.assertIn("prefers-color-scheme: dark", page)

    def test_owner_edits_round_trip_through_the_form(self):
        episode = episode_brief.build_episode_brief(Scope(), briefs(), None)
        form = episode_brief.brief_review_form(episode)
        self.assertIn("- [ ] sai [ ] bỏ `c3.CH1.F2` (về Amane, REPORTED) Nghe nói anh sống một mình", form)
        self.assertEqual(episode_brief.parse_brief_review(form), [])  # blank form
        filled = (form.replace("- [ ] sai [ ] bỏ `c2.E1`", "- [x] sai [ ] bỏ `c2.E1`")
                  .replace("- [ ] sai [ ] bỏ `c3.CH1.F1` (về Amane) Học sinh năm nhất",
                           "- [ ] sai [X] bỏ `c3.CH1.F1` (về Amane) Học sinh năm nhất")
                  .replace("- [ ] sai [ ] bỏ `c2.R1` (quan hệ Amane – Mahiru) Hàng xóm",
                           "- [x] sai [ ] bỏ `c2.R1` (quan hệ Amane – Mahiru) Hàng xóm → Hàng xóm cạnh nhà"))
        edits = episode_brief.parse_brief_review(filled)
        self.assertEqual(edits, [{"ref": "c2.E1", "action": "correct", "text": None},
                                 {"ref": "c2.R1", "action": "correct", "text": "Hàng xóm cạnh nhà"},
                                 {"ref": "c3.CH1.F1", "action": "drop", "text": None}])

    def test_edits_apply_to_copies_and_every_change_is_recorded(self):
        original = briefs()
        frozen = copy.deepcopy(original)
        edits = [{"ref": "c3.CH1.F1", "action": "drop", "text": None},
                 {"ref": "c3.CH1.F2", "action": "correct", "text": "Nghe nói anh sống một mình từ năm nhất"},
                 {"ref": "c2.E1", "action": "drop", "text": None},
                 {"ref": "c2.R1", "action": "correct", "text": "Hàng xóm cạnh nhà"},
                 {"ref": "c2.E2", "action": "correct", "text": None},
                 {"ref": "c9.E1", "action": "drop", "text": None},
                 {"ref": "c2.CH1.F7", "action": "drop", "text": None},
                 {"ref": "c2.R4", "action": "drop", "text": None}]
        edited, report = episode_brief.apply_brief_review(original, edits)
        self.assertEqual(original, frozen)  # inputs untouched
        three = next(b for b in edited if b["chapter_order"] == 3)
        two = next(b for b in edited if b["chapter_order"] == 2)
        # Refs resolve against the unedited brief: dropping F1 does not shift F2.
        self.assertEqual([f["text"] for f in three["characters"][0]["facts"]], ["Nghe nói anh sống một mình từ năm nhất"])
        self.assertNotIn("E1", [e["id"] for e in two["events"]])
        self.assertEqual(two["relationships"][0]["state"], "Hàng xóm cạnh nhà")
        self.assertEqual([(c["ref"], c["action"]) for c in report["changes"]],
                         [("c3.CH1.F1", "drop"), ("c3.CH1.F2", "correct"), ("c2.E1", "drop"), ("c2.R1", "correct")])
        self.assertTrue(report["changes"][2]["core_event_dropped"])
        self.assertEqual(report["changes"][3]["old"], "Hàng xóm")
        self.assertEqual([(r["ref"], r["reason"][:10]) for r in report["rejected"]],
                         [("c2.E2", "marked wro"), ("c9.E1", "no such it"), ("c2.CH1.F7", "no such it"),
                          ("c2.R4", "no such it")])
        self.assertIn('"format"', episode_brief.dump({"format": 1}))


if __name__ == "__main__":
    unittest.main()
