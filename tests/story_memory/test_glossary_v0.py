"""Tests for tools/story_memory/glossary_v0.py (one spelling per character)."""
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.story_memory import glossary_v0  # noqa: E402


def roster(*characters):
    return {"characters": [{"name": name, "romanized_name": romanized, "aliases": list(aliases), "first_chapter": 1}
                           for name, romanized, aliases in characters], "warnings": []}


LIN = ("林婉儿", "Lin Wan'er", ["Wan'er", "婉儿"])
AMANE = ("藤宮周", "Fujimiya Amane", ["Amane", "周"])


def units(*texts):
    return [{"unit_id": f"P{i:03d}", "sha256": "x", "text": text} for i, text in enumerate(texts, start=1)]


class GlossaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = glossary_v0.glossary_path(self.tmp.name, "story-x")

    def test_sync_adds_characters_and_never_overwrites_the_owners_choice(self):
        glossary = glossary_v0.sync(self.path, roster(LIN))
        self.assertEqual(glossary["characters"][0]["display"], "Lin Wan'er")
        self.assertEqual(glossary["characters"][0]["also_allowed"], ["Wan'er"])
        self.assertEqual(glossary["characters"][0]["source_names"], ["林婉儿", "婉儿"])
        self.assertFalse(glossary_v0.confirmed(glossary))

        # The owner chooses a Sino-Vietnamese name.
        data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        self.assertIsNone(data["characters"][0]["pronoun"])  # offered for the owner to fill
        data["characters"][0].update(display="Lâm Uyển Nhi", also_allowed=["Uyển Nhi"], pronoun="cô", confirmed=True)
        self.path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")

        later = roster(("林婉儿", "Lin Wan'er", ["婉儿", "小婉"]), AMANE)
        glossary = glossary_v0.sync(self.path, later)
        self.assertEqual([e["display"] for e in glossary["characters"]], ["Lâm Uyển Nhi", "Fujimiya Amane"])
        self.assertIn("小婉", glossary["characters"][0]["source_names"])  # new source name is learned
        self.assertEqual(glossary_v0.load(self.path), glossary)
        self.assertFalse(glossary_v0.confirmed(glossary))  # Amane is still a default
        self.assertIn('林婉儿, 婉儿, 小婉 → Lâm Uyển Nhi (also acceptable: Uyển Nhi); always refer to them as "cô"',
                      glossary_v0.rules(glossary))

    def test_other_spellings_of_a_character_are_flagged(self):
        glossary = {"format": glossary_v0.GLOSSARY_FORMAT, "characters": [
            {"display": "Lâm Uyển Nhi", "also_allowed": ["Uyển Nhi"], "source_names": ["林婉儿"]},
            {"display": "Fujimiya Amane", "also_allowed": [], "source_names": ["藤宮周"]}]}
        found = glossary_v0.check(units("Lin Wan'er mỉm cười với Amane.", "Lâm Uyển Nhi gật đầu.",
                                        "Wan'er bỏ đi."), glossary, roster(LIN, AMANE))
        self.assertEqual([(f["unit_id"], f["claim"]) for f in found], [("P001", "Lin Wan'er"), ("P003", "Wan'er")])
        self.assertIn("Lâm Uyển Nhi", found[0]["suggested_fix"])
        # "Amane" is part of the display name, so the short form is fine.
        defaults = glossary_v0.sync(self.path, roster(LIN, AMANE))
        self.assertEqual(glossary_v0.check(units("Lin Wan'er và Amane."), defaults, roster(LIN, AMANE)), [])

    def test_bad_files_and_ids_are_rejected(self):
        self.assertIsNone(glossary_v0.confirmed(glossary_v0.load(self.path)))  # missing file: empty glossary
        self.assertEqual(glossary_v0.rules(glossary_v0.load(self.path)), "")
        cases = {"wrong format": "format: other\ncharacters: []\n",
                 "empty display": f"format: {glossary_v0.GLOSSARY_FORMAT}\ncharacters:\n- display: ''\n"}
        for label, text in cases.items():
            with self.subTest(label):
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError):
                    glossary_v0.load(self.path)
        with self.assertRaises(ValueError):
            glossary_v0.glossary_path(self.tmp.name, "../x")


if __name__ == "__main__":
    unittest.main()
