"""Tests for tools/story_pipeline/review_page.py (the owner's review.html)."""
import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tools.story_pipeline import review_page  # noqa: E402
from tools.story_pipeline.run_pipeline import REVIEW_QUESTIONS  # noqa: E402

BRIEF = {
    "chapter_order": 3,
    "characters": [{"id": "CH1", "name": "椎名真昼", "romanized_name": "Mahiru", "aliases": [],
                    "facts": [{"text": "Nấu cháo cho Amane", "evidence": ["3.79"], "quote": "x",
                               "epistemic": "EXPLICIT"}]}],
    "events": [{"id": "E1", "summary": "Mahiru mang cháo vào", "evidence": ["3.81", "3.72"], "quote": "x",
                "epistemic": "EXPLICIT"}],
}
UNITS = [{"unit_id": "P001", "sha256": "x", "text": "Mahiru bưng bát cháo nghi ngút khói <vào> phòng."},
         {"unit_id": "P002", "sha256": "x", "text": "Thật là một ngày dài!"}]
CRITIC = {"units": [
    {"unit_id": "P001", "claims": [{"brief_refs": ["c3.E1", "c3.CH1"], "claim_type": "SUPPORTED_FACT"}]},
    {"unit_id": "P002", "claims": [{"brief_refs": [], "claim_type": "COMMENTARY_RHETORIC"}]}]}
REPORT = {
    "gates": {"GATE_FACTUAL_GROUNDING": {"status": "FLAG"}, "GATE_SPOILER_DISCIPLINE": {"status": "PASS"}},
    "findings": [
        {"unit_id": "P001", "claim": "nghi ngút khói", "claim_type": "CONTRADICTED_STORY_CLAIM", "severity": "MEDIUM",
         "source": "source_check", "explanation": "Nguồn nói cháo không bốc hơi", "suggested_fix": "Sửa theo [3.81]",
         "passage_ids": ["3.81"]},
        {"unit_id": "P001", "claim": "vào phòng", "claim_type": "STRENGTHENED_STORY_CLAIM", "severity": "HIGH",
         "explanation": "x", "suggested_fix": None},
    ],
}
PASSAGES = {"3.72": "お盆を携えて入ってくる。", "3.79": "梅が入ったお粥。", "3.81": "湯気はたっていない<b>"}
MANIFEST = {"run_id": "run<1>", "status": "COMPLETED", "scope": {"label": "chapter 3", "story_id": "s"}}


class ReviewPageTests(unittest.TestCase):
    def setUp(self):
        self.page = review_page.render_review_page(MANIFEST, REPORT, UNITS, CRITIC, [BRIEF], PASSAGES,
                                                   REVIEW_QUESTIONS)

    def test_each_paragraph_sits_next_to_its_briefs_and_source(self):
        p001 = self.page.split("id='P001'")[1].split("</section>")[0]
        self.assertIn("Nấu cháo cho Amane", p001)
        self.assertIn("c3.E1", p001)
        # Cited passages appear once each, in story order.
        source = p001.split("<details")[1]
        positions = [source.index(f"[{pid}]") for pid in ("3.72", "3.79", "3.81")]
        self.assertEqual(positions, sorted(positions))
        p002 = self.page.split("id='P002'")[1].split("</section>")[0]
        self.assertIn("không trích mục brief nào", p002)

    def test_findings_are_marked_on_their_sentence_most_severe_first(self):
        p001 = self.page.split("id='P001'")[1].split("</section>")[0]
        self.assertIn("<mark>nghi ngút khói</mark>", p001)
        self.assertLess(p001.index("HIGH"), p001.index("MEDIUM"))
        self.assertIn("source_check", p001)

    def test_text_is_escaped_and_the_page_is_self_contained(self):
        self.assertIn("&lt;vào&gt;", self.page)
        self.assertIn("湯気はたっていない&lt;b&gt;", self.page)
        self.assertIn("run&lt;1&gt;", self.page)
        self.assertNotRegex(self.page, r"<(script|link|img)[^>]+(src|href)=")  # nothing loaded from outside

    def test_review_form_lists_every_question(self):
        form = self.page.split("<form")[1]
        for key, _ in REVIEW_QUESTIONS:
            self.assertEqual(len(re.findall(rf"name='{key}' value='\d'", form)), 5, key)
        self.assertIn("id='copy'", form)
        self.assertIn("Không dùng được", form)

    def test_page_without_a_critic_still_renders(self):
        page = review_page.render_review_page(MANIFEST, {"gates": {}, "findings": []}, UNITS, None, [BRIEF],
                                              PASSAGES, REVIEW_QUESTIONS)
        self.assertEqual(page.count("class='unit'"), 2)
        self.assertNotIn("<mark>", page)


if __name__ == "__main__":
    unittest.main()
