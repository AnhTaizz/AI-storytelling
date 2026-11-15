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
        self.assertTrue({"vi", "ja", "en", "ko", "zh"} <= set(languages))
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
            "bad speech verbs": (lambda d: d.update(speech_verbs=["said", ""]), "speech_verbs"),
            "bad audience address": (lambda d: d.update(audience_address=["You Guys"]), "audience_address"),
            "bad coordinators": (lambda d: d.update(coordinators=[" and"]), "coordinators"),
            "bad pronouns": (lambda d: d.update(third_person_pronouns=["He"]), "third_person_pronouns"),
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
            # Chinese season: a character's own account, attributed to them, stays a report.
            ("vi", "Theo lời Thẩm Tri Ý nói, cuốn sách bị bán ba năm trước", "hedge", {"reported"}),
            ("vi", "Nghe Thẩm Tri Ý nói, cuốn sách bị bán ba năm trước", "hedge", {"reported"}),
            ("vi", "Nghe tiếng mưa rơi suốt đêm, cô không nói gì", "hedge", set()),  # gap of 4 words at most
            ("vi", "Thẩm Tri Ý cho biết cuốn sách bị bán", "hedge", {"reported"}),
            ("ja", "告白やアプローチを受けているらしく", "hedge", {"reported"}),
            ("ja", "どこか泣きそうに歪んだように見えて", "hedge", {"appearance"}),  # no spaces: substrings
            ("en", "She was extremely wary, or so it seemed", "strength", {"degree_extreme"}),
            ("en", "She was extremely wary, or so it seemed", "hedge", {"appearance"}),
            # Korean particles attach to words, so phrases match inside eojeol.
            ("ko", "모두가 그녀를 천사라고 불렀다", "strength", {"universality"}),
            ("ko", "그녀는 고백을 자주 받는다고 한다", "hedge", {"reported"}),
            ("ko", "울 것 같았다", "hedge", {"appearance"}),
            ("ko", "작은 목소리가 들린 것 같았지만", "hedge", {"appearance"}),  # inflected ending
            ("ko", "반에서는 늘 조용하다고들 한다", "hedge", {"reported"}),  # plural "they say"
            ("ko", "의심스럽다는 듯 눈을 가늘게 떴다", "hedge", {"appearance"}),
            ("ja", "熱はすこし引いたように思える", "hedge", {"appearance"}),
            ("ja", "会釈されるようになった程度であろうか", "hedge", {"speculation"}),
            ("ko", "마치 천사처럼 보였다", "hedge", {"metaphor", "appearance"}),
            ("ko", "그는 집으로 돌아갔다", "hedge", set()),
            # Chinese: simplified and traditional forms; no single-character phrases.
            # A denied rumour is not hearsay (the brief check's "no rumour" correction, chapter 3).
            ("ja", "失敗しただのなんだのそういう噂は聞いた事がないので", "hedge", set()),
            ("ja", "噂通りなら優等生らしい", "hedge", {"reported"}),
            ("zh", "我从没听说过她失败", "hedge", set()),
            ("vi", "Amane chưa từng nghe tin đồn Mahiru thất bại", "hedge", set()),
            ("zh", "据说她每次考试都是第一名", "hedge", {"reported"}),
            ("zh", "據說她每次考試都是第一名", "hedge", {"reported"}),
            ("zh", "她的眼睛似乎有点红", "hedge", {"appearance"}),
            ("zh", "她宛如天使般的美丽", "hedge", {"metaphor"}),
            ("zh", "他把图像挂在墙上", "hedge", set()),
            ("zh", "所有人都非常喜欢她", "strength", {"universality", "degree_extreme"}),
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
        coordinated = [
            # Only commas and coordinating conjunctions split; "khi" stays with its statement.
            ("vi", "Cô lo lắng và gửi tin nhắn khi cậu ốm", ["Cô lo lắng", "gửi tin nhắn khi cậu ốm"]),
            ("en", "She smiled but he left when it rained", ["She smiled", "he left when it rained"]),
            ("ja", "雨が降った、彼女はいた", ["雨が降った", "彼女はいた"]),  # no coordinators listed yet
        ]
        for language, text, expected in coordinated:
            with self.subTest(language=language, text=text, split="coordinated"):
                self.assertEqual(lexicon.load(language).coordinated_parts(text), expected)
        for language, text, expected in cases:
            with self.subTest(language=language, text=text):
                self.assertEqual(lexicon.load(language).clauses(text), expected)

    def test_contrast_parts_split_only_at_a_contrast(self):
        cases = [
            ("ja", "周はクラスが違うので詳しくは知らないが、噂通りなら完璧超人だ。",
             ["周はクラスが違うので詳しくは知らないが、", "噂通りなら完璧超人だ。"]),
            ("ja", "真昼が、雨の中に座っていた。", ["真昼が、雨の中に座っていた。"]),  # subject が is no contrast
            ("ja", "そういう噂は聞いた事がないので、ひどいという訳でもなさそうだ。",  # a cause clause closes a part
             ["そういう噂は聞いた事がないので、", "ひどいという訳でもなさそうだ。"]),
            ("en", "I don't know her, but rumour says she is perfect.",
             ["I don't know her,", " but rumour says she is perfect."]),
            ("en", "Butter, eggs, flour.", ["Butter, eggs, flour."]),  # "but" inside a word
            ("ko", "잘 모르지만, 소문으로는 완벽하다고 한다.", ["잘 모르지만,", " 소문으로는 완벽하다고 한다."]),
            ("zh", "我不太清楚，但据说她很完美。", ["我不太清楚，", "但据说她很完美。"]),
        ]
        for language, text, expected in cases:
            with self.subTest(language=language, text=text):
                self.assertEqual(lexicon.load(language).contrast_parts(text), expected)


class ReportedSpeechTests(unittest.TestCase):
    def test_reported_speech_content_starts_after_the_complementizer(self):
        cases = [
            ("vi", "Amane trấn an cô, giải thích rằng cậu tự nguyện", "cậu tự nguyện"),
            ("vi", "Cậu nói với Mahiru rằng không sao", "không sao"),
            ("vi", "Nghe nói rằng cô ấy giỏi", None),            # hearsay, not someone speaking
            ("vi", "Nói về Mahiru thì cô rất đẹp", None),         # no complementizer
            ("vi", "Cậu nói, rằng thì là mà", None),               # verb and complementizer in different clauses
            ("en", "He told her that it was fine", "it was fine"),
            ("ja", "彼はそう言った", None),                        # no speech verbs in this lexicon yet
        ]
        for language, text, expected in cases:
            with self.subTest(language=language, text=text):
                lex = lexicon.load(language)
                start = lex.reported_speech_start(text)
                self.assertEqual(text[start:].strip() if start is not None else None, expected)
        self.assertTrue(lexicon.load("vi").mentions_speech("Cậu đã nói dối"))
        self.assertFalse(lexicon.load("vi").mentions_speech("Nghe nói cô giỏi"))


if __name__ == "__main__":
    unittest.main()
