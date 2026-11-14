"""Tests for tools/story_pipeline/lexicon.py and every lexicon file it loads.

Adding a language means adding tools/story_pipeline/lexicons/<code>.yaml; the
data-driven test below validates it automatically.
"""
import sys
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.story_pipeline import lexicon  # noqa: E402


class LexiconFileTests(unittest.TestCase):
    def test_every_lexicon_file_is_complete_and_loads(self):
        languages = lexicon.available_languages()
        self.assertTrue({"vi", "ja", "en", "ko"} <= set(languages))
        for language in languages:
            with self.subTest(language=language):
                data = yaml.safe_load((lexicon.LEXICON_DIR / f"{language}.yaml").read_text(encoding="utf-8"))
                self.assertEqual(lexicon.validate(data, language), [])
                loaded = lexicon.load(language)
                self.assertEqual(set(loaded.phrases["strength"]), set(lexicon.STRENGTH_CONCEPTS))
                self.assertEqual(set(loaded.phrases["hedge"]), set(lexicon.HEDGE_CONCEPTS))

    def test_validation_reports_each_kind_of_problem(self):
        good = yaml.safe_load((lexicon.LEXICON_DIR / "en.yaml").read_text(encoding="utf-8"))
        cases = {
            "wrong language": (lambda d: d.update(language="fr"), "language must be"),
            "missing concept": (lambda d: d["strength"].pop("firmness"), "missing concepts"),
            "unknown concept": (lambda d: d["hedge"].update(gossip=["x"]), "unknown concepts"),
            "uppercase phrase": (lambda d: d["strength"]["certainty"].append("Surely"), "lowercase"),
            "phrase in two concepts": (lambda d: d["hedge"]["speculation"].append("seems"), "appears in both"),
            "empty concept": (lambda d: d["hedge"].update(metaphor=[]), "at least one phrase"),
            "bad flag": (lambda d: d.update(word_boundaries="yes"), "word_boundaries"),
            "bad density": (lambda d: d.update(chars_per_event=0), "chars_per_event"),
            "bad clause markers": (lambda d: d.update(clause_markers=["and", ""]), "clause_markers"),
            "bad contrast openers": (lambda d: d.update(contrast_openers=["But"]), "contrast_openers"),
        }
        for label, (mutate, message) in cases.items():
            with self.subTest(label):
                data = yaml.safe_load(yaml.safe_dump(good, allow_unicode=True))
                mutate(data)
                problems = lexicon.validate(data, "en")
                self.assertTrue(any(message in p for p in problems), problems)

    def test_unknown_language_has_no_lexicon(self):
        self.assertIsNone(lexicon.load("xx"))
        self.assertEqual(lexicon.load("KO").language, "ko")          # tags are normalised
        self.assertEqual(lexicon.load("en-GB").language, "en")       # to their primary subtag
        self.assertEqual(lexicon.missing_languages("vi", "xx", "ja"), frozenset({"xx"}))


class MatchingTests(unittest.TestCase):
    def test_concepts_found_per_language(self):
        cases = [
            ("vi", "Cô VÔ CÙNG xinh đẹp, được mọi người ví như thiên thần", "strength",
             {"degree_extreme", "universality"}),
            ("vi", "được ví như thiên thần", "hedge", {"metaphor"}),
            ("vi", "đầy đủ thông tin, nổi tiếngx", "strength", set()),  # word boundaries respected
            ("ja", "告白やアプローチを受けているらしく", "hedge", {"reported"}),
            ("ja", "どこか泣きそうに歪んだように見えて", "hedge", {"appearance"}),  # no spaces: substrings
            ("en", "She was extremely wary, or so it seemed", "strength", {"degree_extreme"}),
            ("en", "She was extremely wary, or so it seemed", "hedge", {"appearance"}),
            # Korean particles attach to words, so phrases match inside eojeol.
            ("ko", "모두가 그녀를 천사라고 불렀다", "strength", {"universality"}),
            ("ko", "그녀는 고백을 자주 받는다고 한다", "hedge", {"reported"}),
            ("ko", "울 것 같았다", "hedge", {"appearance"}),
            ("ko", "마치 천사처럼 보였다", "hedge", {"metaphor", "appearance"}),
            ("ko", "그는 집으로 돌아갔다", "hedge", set()),
        ]
        for language, text, kind, expected in cases:
            with self.subTest(language=language, text=text, kind=kind):
                self.assertEqual(lexicon.load(language).concepts(text, kind), expected)


class ClauseTests(unittest.TestCase):
    def test_clauses_split_on_punctuation_and_conjunctions(self):
        cases = [
            ("vi", "Amane hỏi cô đang làm gì sau khi nhìn thấy nét mặt như sắp khóc",
             ["Amane hỏi cô đang làm gì", "nhìn thấy nét mặt như sắp khóc"]),
            ("vi", "Khiêm tốn, và nghe nói rất được tỏ tình", ["Khiêm tốn", "nghe nói rất được tỏ tình"]),
            ("vi", "Mahiru vàng", ["Mahiru vàng"]),  # "và" inside a word is not a conjunction
            ("en", "She smiled but he left", ["She smiled", "he left"]),
            ("ja", "雨が降った。しかし彼女はいた", ["雨が降った", "彼女はいた"]),
        ]
        for language, text, expected in cases:
            with self.subTest(language=language, text=text):
                self.assertEqual(lexicon.load(language).clauses(text), expected)

    def test_contrast_parts_split_only_at_a_contrast(self):
        cases = [
            ("ja", "周はクラスが違うので詳しくは知らないが、噂通りなら完璧超人だ。",
             ["周はクラスが違うので詳しくは知らないが、", "噂通りなら完璧超人だ。"]),
            ("ja", "真昼が、雨の中に座っていた。", ["真昼が、雨の中に座っていた。"]),  # subject が is no contrast
            ("en", "I don't know her, but rumour says she is perfect.",
             ["I don't know her,", " but rumour says she is perfect."]),
            ("en", "Butter, eggs, flour.", ["Butter, eggs, flour."]),  # "but" inside a word
            ("ko", "잘 모르지만, 소문으로는 완벽하다고 한다.", ["잘 모르지만,", " 소문으로는 완벽하다고 한다."]),
        ]
        for language, text, expected in cases:
            with self.subTest(language=language, text=text):
                self.assertEqual(lexicon.load(language).contrast_parts(text), expected)


if __name__ == "__main__":
    unittest.main()
