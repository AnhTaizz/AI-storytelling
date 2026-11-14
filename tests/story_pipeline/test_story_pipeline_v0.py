"""Offline tests for the story pipeline prototype v0.

No model, API or network is used: a scripted client returns canned JSON. One test reads
the tracked sample chapter 1 through the frozen M3 adapter.
"""
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.story_pipeline import checks, stages  # noqa: E402
from tools.story_pipeline.facts import FactsError, StoryFacts  # noqa: E402
from tools.story_pipeline.llm import (  # noqa: E402
    CallLog,
    GeminiLLMClient,
    ScriptedLLMClient,
    StageFailed,
    parse_json_object,
    run_json_stage,
)
from tools.story_pipeline.profile import load_profile  # noqa: E402
from tools.story_pipeline import run_pipeline  # noqa: E402
from tools.story_pipeline.run_pipeline import DEFAULT_MANIFEST, gate_report, run  # noqa: E402
from tools.story_memory.memory_v0 import StoryMemory  # noqa: E402
from tools.story_pipeline.source import Chapter, Passage, StoryScope, load_scope, parse_range  # noqa: E402

SECTION_1 = ("Một buổi chiều mưa, Amane đi ngang qua công viên và thấy Mahiru ngồi một mình "
             "trên xích đu, người ướt sũng.")
SECTION_2 = ("Cậu đưa chiếc ô của mình cho cô rồi đi thẳng về nhà, chẳng nói thêm gì nhiều. "
             "Bạn nghĩ sao về cách làm quen này?")


_SAMPLE = load_scope(DEFAULT_MANIFEST, (1, 5))
PASSAGE_TEXT = {p.passage_id: p.text for c in _SAMPLE.chapters for p in c.passages}


SAMPLE_CHAPTERS = {c.order: c for c in _SAMPLE.chapters}


def needed_events(order):
    """Events a valid fixture needs, with or without the source-language density rule."""
    chapter = SAMPLE_CHAPTERS.get(order)
    return max(stages.min_events(chapter), stages.min_events(chapter, "ja")) if chapter else 2


def brief_json(order, evidence=None, quote=None):
    """A valid brief: two named events plus MINOR filler up to the chapter's event minimum."""
    brief = _base_brief(order, evidence, quote)
    template = brief["events"][-1]
    for n in range(len(brief["events"]) + 1, needed_events(order) + 1):
        brief["events"].append({**template, "id": f"E{n}", "summary": f"Chi tiết phụ {n}", "importance": "MINOR"})
    return brief


def _base_brief(order, evidence=None, quote=None):
    evidence = evidence or [f"{order}.2"]
    if quote is None:
        quote = PASSAGE_TEXT.get(evidence[0], "xx")[:12]
    return {
        "chapter_order": order,
        "chapter_summary": "Amane gặp Mahiru trong công viên lúc trời mưa.",
        "characters": [
            {"id": "CH1", "name": "藤宮周", "romanized_name": "Amane", "aliases": [],
             "facts": [{"text": "Học sinh năm nhất", "evidence": evidence, "quote": quote,
                        "epistemic": "EXPLICIT"}]},
            {"id": "CH2", "name": "椎名真昼", "romanized_name": "Mahiru", "aliases": ["Thiên thần"],
             "facts": []},
        ],
        "relationships": [{"between": ["CH1", "CH2"], "state": "Hàng xóm", "evidence": evidence,
                           "quote": quote, "epistemic": "EXPLICIT"}],
        "events": [
            {"id": "E1", "summary": "Amane thấy Mahiru trên xích đu", "participants": ["CH1", "CH2"],
             "location": "công viên", "importance": "CORE",
             "motivation": {"text": None, "status": "UNKNOWN"}, "consequence": None,
             "evidence": evidence, "quote": quote, "epistemic": "EXPLICIT"},
            {"id": "E2", "summary": "Amane đưa ô cho Mahiru", "participants": ["CH1", "CH2"],
             "location": "công viên", "importance": "SUPPORTING",
             "motivation": {"text": None, "status": "UNKNOWN"}, "consequence": None,
             "evidence": evidence, "quote": quote, "epistemic": "EXPLICIT"},
        ],
        "unknowns": ["Lý do Mahiru ngồi dưới mưa"],
        "forbidden_inferences": ["Mahiru thích Amane"],
        "ending_state": "Amane về nhà.",
        "closing_hook": {"text": None, "quote": None, "evidence": []},
    }


PLAN = {
    "logline": "Một chiếc ô trong cơn mưa.",
    "hook": {"idea": "Mở bằng hình ảnh cô gái ngồi dưới mưa", "event_refs": ["c1.E1"]},
    "beats": [
        {"id": "B1", "purpose": "Gặp gỡ", "event_refs": ["c1.E1"], "emotional_note": None,
         "commentary_idea": None, "target_words": 30},
        {"id": "B2", "purpose": "Chiếc ô", "event_refs": ["c1.E2"], "emotional_note": None,
         "commentary_idea": "Hỏi khán giả", "target_words": 30},
    ],
    "callbacks": [],
    "omitted_events": [],
    "closing_hook": None,
}

SCRIPT = {"title_idea": "Chiếc ô", "sections": [{"beat_id": "B1", "text": SECTION_1},
                                                 {"beat_id": "B2", "text": SECTION_2}]}


def claim(claim_type, severity=None, category=None):
    return {"claim": "x", "claim_type": claim_type, "failure_category": category, "severity": severity,
            "brief_refs": ["c1.E1"], "source_evidence": [{"passage_id": "1.2", "quote": PASSAGE_TEXT["1.2"][:12]}],
            "explanation": "y", "suggested_fix": "z" if severity else None}


def critic_json(user, with_problem):
    unit_ids = re.findall(r"^<(TITLE|P\d{3})>$", user, re.MULTILINE)
    units = []
    for index, unit_id in enumerate(unit_ids):
        claims = [claim("SUPPORTED_FACT")]
        if with_problem and index == 0:
            claims.append(claim("UNSUPPORTED_STORY_CLAIM", "MEDIUM", "UNSUPPORTED_INVENTION"))
        units.append({"unit_id": unit_id, "claims": claims, "no_claim_reason": None})
    return {"units": units}


class FakeModel:
    """Valid responses for every stage; the first critic reports one MEDIUM problem."""

    def __init__(self):
        self.critic_calls = 0
        self.plan_prompts = []

    def __call__(self, stage, system, user):
        if stage == "brief":
            order = int(re.search(r"Chapter order: (\d+)", user).group(1))
            brief = brief_json(order)
            if "full_target_units_estimate" in system:
                brief["full_target_units_estimate"] = 120
            return json.dumps(brief, ensure_ascii=False)
        if stage == "plan":
            # Use exactly the event refs the prompt offers (episode briefs and recap memory).
            self.plan_prompts.append(user)
            refs = list(dict.fromkeys(re.findall(r'"ref":\s*"(c\d+\.E\d+)"', user)))
            plan = json.loads(json.dumps(PLAN))
            plan["hook"]["event_refs"] = refs[:1]
            plan["beats"][0]["event_refs"] = refs[:1]
            plan["beats"][1]["event_refs"] = refs[1:]
            return json.dumps(plan, ensure_ascii=False)
        if stage in ("script", "revise"):
            return "```json\n" + json.dumps(SCRIPT, ensure_ascii=False) + "\n```"
        if stage == "critic":
            self.critic_calls += 1
            return json.dumps(critic_json(user, self.critic_calls == 1), ensure_ascii=False)
        raise AssertionError(stage)


def test_profile():
    return load_profile(REPO / "tools/story_pipeline/profiles/vi_youtube_casual_v0.yaml").with_length(20, 200)


class SourceTests(unittest.TestCase):
    def test_parse_range(self):
        self.assertEqual(parse_range("3"), (3, 3))
        self.assertEqual(parse_range("1-5"), (1, 5))
        for bad in ("0", "5-1", "1-2-3"):
            with self.assertRaises(ValueError):
                parse_range(bad)

    def test_sample_chapter_scope(self):
        scope = load_scope(DEFAULT_MANIFEST, (1, 2))
        self.assertEqual([c.order for c in scope.chapters], [1, 2])
        self.assertIn("1.1", scope.chapters[0].passage_ids)
        self.assertTrue(all(p.passage_id.startswith("2.") for p in scope.chapters[1].passages))
        self.assertTrue(scope.chapters[0].render().startswith("[1.1] "))

    def test_chapters_outside_manifest_rejected(self):
        with self.assertRaises(ValueError):
            load_scope(DEFAULT_MANIFEST, (5, 6))


class ChecksTests(unittest.TestCase):
    def test_word_count_and_language(self):
        report = checks.check_script(SCRIPT, 20, 200, "vi")
        self.assertTrue(report["length_ok"] and report["language_ok"] and report["clean_ok"])
        self.assertEqual(report["word_count"], checks.count_words(checks.script_text(SCRIPT)))

    def test_foreign_script_depends_on_target_language(self):
        cases = [
            ("vi", "Amane gặp 마히루", ["마", "히", "루"]),       # Hangul in a Vietnamese script
            ("vi", "Amane (周) đi về", ["周"]),
            ("ko", "아마네는 周를 봤다", []),                      # Hangul and hanja are Korean
            ("ja", "周はアマネを見た", []),
            ("ja", "周は마히루を見た", ["마", "히", "루"]),
            ("en", "Привет Amane", list("Привет")),
            ("zh-Hant", "周看見了雨", []),                         # tag normalised to its base
        ]
        for language, text, expected in cases:
            with self.subTest(language=language, text=text):
                self.assertEqual(checks.foreign_script_characters(text, language), expected)
        self.assertEqual(checks.count_length("周は 雨の中", "ja"), 5)       # characters
        self.assertEqual(checks.count_length("Amane đi về", "vi"), 3)       # words

    def test_contamination_and_artifacts_detected(self):
        bad = {"title_idea": "t", "sections": [{"beat_id": "B1", "text": "## Mở đầu\nAmane (周) [nhạc nền]"}]}
        report = checks.check_script(bad, 1, 100, "vi")
        self.assertFalse(report["language_ok"])
        self.assertFalse(report["clean_ok"])
        errors = checks.script_check_errors(report)
        self.assertTrue(any(e.startswith("language") for e in errors))
        self.assertTrue(any("heading" in e for e in errors))

    def test_split_units(self):
        units = checks.split_units("a b\n\n\nc d\n \ne")
        self.assertEqual([u["unit_id"] for u in units], ["P001", "P002", "P003"])


class JsonLoopTests(unittest.TestCase):
    SCHEMA = {"type": "object", "required": ["n"], "properties": {"n": {"type": "integer"}}}

    def test_fenced_json(self):
        self.assertEqual(parse_json_object("```json\n{\"n\": 1}\n```"), {"n": 1})
        self.assertEqual(parse_json_object("Here: {\"n\": 2} done"), {"n": 2})

    def test_repair_with_error_feedback(self):
        replies = iter(["not json", '{"n": "x"}', '{"n": 3}'])
        prompts = []

        def responder(stage, system, user):
            prompts.append(user)
            return next(replies)

        log = CallLog()
        obj = run_json_stage(ScriptedLLMClient(responder), stage="t", system="s", user="u",
                             schema=self.SCHEMA, max_repairs=2, log=log)
        self.assertEqual(obj, {"n": 3})
        self.assertEqual(len(log.entries), 3)
        self.assertIn("VALIDATION ERRORS", prompts[2])
        self.assertIn("schema: at n", prompts[2])

    def test_exhausted_repairs_raise(self):
        client = ScriptedLLMClient(lambda *a: '{"n": "x"}')
        with self.assertRaises(StageFailed):
            run_json_stage(client, stage="t", system="s", user="u", schema=self.SCHEMA, max_repairs=1)
        self.assertEqual(len(client.calls), 2)

    def test_soft_errors_accepted_on_last_attempt(self):
        client = ScriptedLLMClient(lambda *a: '{"n": 1}')
        obj = run_json_stage(client, stage="t", system="s", user="u", schema=self.SCHEMA,
                             soft_check=lambda o: ["too short"], max_repairs=1)
        self.assertEqual(obj, {"n": 1})
        self.assertEqual(len(client.calls), 2)


    def test_regressed_repair_falls_back_to_last_soft_only_result(self):
        """Live run 8: a repair for a soft error introduced a hard one on the last attempt."""
        replies = iter(['{"n": 1}', '{"n": 2}', '{"n": "x"}'])
        client = ScriptedLLMClient(lambda *a: next(replies))
        obj = run_json_stage(client, stage="t", system="s", user="u", schema=self.SCHEMA,
                             soft_check=lambda o: ["too short"], max_repairs=2)
        self.assertEqual(obj, {"n": 2})
        self.assertEqual(len(client.calls), 3)


class SemanticValidationTests(unittest.TestCase):
    def setUp(self):
        self.chapter = load_scope(DEFAULT_MANIFEST, (1, 1)).chapters[0]

    def test_brief_rejects_out_of_scope_evidence(self):
        errors = stages.brief_semantic_errors(brief_json(1, ["2.5"]), self.chapter)
        self.assertTrue(any("not passages of chapter 1" in e for e in errors))
        self.assertEqual(stages.brief_semantic_errors(brief_json(1), self.chapter), [])

    def test_brief_quote_must_be_verbatim_in_cited_passages(self):
        passage = PASSAGE_TEXT["1.2"]
        cases = [
            (passage[3:15], True),                      # exact excerpt
            (" " + passage[3:9] + "\n" + passage[9:15], True),  # whitespace and line breaks ignored
            ("「" + passage[3:15] + "」", True),        # surrounding quote marks ignored
            ("invented words", False),
            (PASSAGE_TEXT["1.3"][:12], False),           # real text, but from a passage not cited
        ]
        for quote, ok in cases:
            with self.subTest(quote=quote):
                errors = stages.brief_semantic_errors(brief_json(1, ["1.2"], quote), self.chapter)
                self.assertEqual(not any("does not appear verbatim" in e for e in errors), ok, errors)

    def test_plan_requires_core_coverage_and_length(self):
        profile = test_profile()
        plan = json.loads(json.dumps(PLAN))
        plan["beats"][0]["event_refs"] = ["c1.E2"]
        plan["beats"][1]["target_words"] = 500
        errors = stages.plan_semantic_errors(plan, [brief_json(1)], profile)
        self.assertTrue(any("CORE events not covered" in e for e in errors))
        self.assertTrue(any("target_words sum" in e for e in errors))
        self.assertEqual(stages.plan_semantic_errors(PLAN, [brief_json(1)], profile), [])
        for hook_refs in ([], ["c1.E3"]):  # existing but omitted E3 cannot anchor a title promise
            with self.subTest(hook_refs=hook_refs):
                stranded = {**PLAN, "hook": {"idea": "opening", "event_refs": hook_refs}}
                errors = stages.plan_semantic_errors(stranded, [brief_json(1)], profile)
                self.assertTrue(any("anchor the opening" in e for e in errors))

    def test_brief_must_be_fine_grained_enough(self):
        def synthetic(passages, chars_each):
            return Chapter(9, "doc", "t", tuple(Passage(f"9.{i}", "가" * chars_each) for i in range(passages)))

        cases = [
            ("sample chapter 1, no language: per passage", self.chapter, None, 5),
            ("sample chapter 1, Japanese density", self.chapter, "ja", 5),
            ("tiny chapter", synthetic(3, 10), "ja", 2),
            # Korean web novels put each sentence on its own line: 200 short passages are one
            # ordinary chapter, not 14 events' worth.
            ("Korean one-sentence paragraphs", synthetic(200, 30), "ko", 9),
            ("same text, no lexicon: per passage", synthetic(200, 30), "xx", 14),
        ]
        for label, chapter, language, expected in cases:
            with self.subTest(label):
                self.assertEqual(stages.min_events(chapter, language), expected)
        coarse = brief_json(1)
        coarse["events"] = coarse["events"][:2]  # the first live run: 61 passages in 2 events
        errors = stages.brief_semantic_errors(coarse, self.chapter)
        self.assertTrue(any("needs at least 5 events" in e and "you listed 2" in e for e in errors), errors)

    def test_closing_hook_is_quoted_and_landed_by_the_plan(self):
        last = self.chapter.passages[-1]
        hooked = brief_json(1)
        hooked["closing_hook"] = {"text": "Cậu nghĩ vậy, vào lúc đó", "quote": last.text[-6:],
                                  "evidence": [last.passage_id]}
        self.assertEqual(stages.brief_semantic_errors(hooked, self.chapter), [])
        cases = {
            "quote not in passage": {"quote": "không có câu này", "evidence": [last.passage_id]},
            "missing quote": {"quote": None, "evidence": []},
        }
        for label, change in cases.items():
            with self.subTest(label):
                broken = json.loads(json.dumps(hooked))
                broken["closing_hook"].update(change)
                errors = stages.brief_semantic_errors(broken, self.chapter)
                self.assertTrue(any(e.startswith("closing_hook") for e in errors), errors)
        plan = json.loads(json.dumps(PLAN))
        errors = stages.plan_semantic_errors(plan, [hooked], test_profile())
        self.assertTrue(any("closing_hook" in e for e in errors), errors)
        plan["closing_hook"] = "Kết bằng câu: cậu đã nghĩ vậy, vào lúc đó."
        self.assertEqual(stages.plan_semantic_errors(plan, [hooked], test_profile()), [])

    def test_brief_keeps_source_hedging_in_any_language_pair(self):
        """Labels and text of a brief item must keep the hedging of what it quotes."""
        def chapter_with(text):
            return Chapter(1, "doc", "t", (Passage("1.1", text),))

        def brief_with(fact_text, quote, label):
            brief = brief_json(1, ["1.1"], quote)
            brief["characters"][0]["facts"] = [{"text": fact_text, "evidence": ["1.1"], "quote": quote,
                                                "epistemic": label}]
            brief["relationships"] = []
            brief["events"] = [dict(e, quote="x", evidence=["1.1"], summary="Gặp nhau") for e in brief["events"]]
            return brief

        hearsay = "彼女は学年問わず告白を受けているらしく、困っている。"
        dialogue = "「この雨の中なら気になるだろう」と彼は言った。"
        metaphor = "天使というのは勿論比喩である。"
        plain = "彼は傘を渡した。"
        korean = "그녀는 고백을 자주 받는다고 한다."
        # Live run 8: the rumour (噂) is on the far side of 「…知らないが、」.
        contrast = "周はクラスが違うので詳しくは知らないが、噂通りなら完璧超人なんじゃないかと思うほどである。"
        across = "噂では完璧らしいが、彼はクラスが違う。"
        cases = [
            # label, text hedge -> expected problems: label wrong / text unhedged
            ("hearsay as fact", hearsay, "Cô thường nhận lời tỏ tình", "EXPLICIT", "ja", "vi", ["label", "text"]),
            ("hearsay labelled but text plain", hearsay, "Cô thường nhận lời tỏ tình", "REPORTED", "ja", "vi", ["text"]),
            ("hearsay kept", hearsay, "Nghe nói cô nhận nhiều lời tỏ tình", "REPORTED", "ja", "vi", []),
            ("hearsay kept, English brief", hearsay, "She reportedly gets confessions", "REPORTED", "ja", "en", []),
            ("hedge only in dialogue", dialogue, "Amane nói ai cũng sẽ lo", "EXPLICIT", "ja", "vi", []),
            ("metaphor needs a metaphor", metaphor, "Cô có vẻ là thiên thần", "FIGURATIVE", "ja", "vi", ["text"]),
            ("metaphor kept", metaphor, "Cô được ví như thiên thần", "FIGURATIVE", "ja", "vi", []),
            # A hedge from an unquoted passage: the label carries it, the text must follow.
            ("label from another passage", plain, "Cô có vẻ đang chờ ai", "APPEARANCE", "ja", "vi", []),
            ("label without a text hedge", plain, "Cô đang chờ ai", "APPEARANCE", "ja", "vi", ["text"]),
            ("no source lexicon: label still binds text", hearsay, "Cô nhận lời tỏ tình", "REPORTED", "xx", "vi", ["text"]),
            ("no source lexicon, plain", hearsay, "Cô nhận lời tỏ tình", "EXPLICIT", "xx", "vi", []),
            ("Korean hearsay as fact", korean, "Cô thường nhận lời tỏ tình", "EXPLICIT", "ko", "vi", ["label", "text"]),
            ("hedge on the other side of a contrast", contrast, "Amane khác lớp", "EXPLICIT", "ja", "vi", []),
            ("quote spanning a contrast", across, "Cô hoàn hảo, cậu khác lớp", "EXPLICIT", "ja", "vi",
             ["label", "text"]),
            ("Korean hearsay kept", korean, "Nghe nói cô thường nhận lời tỏ tình", "REPORTED", "ko", "vi", []),
        ]
        for label_text, source, fact, label, src_lang, brief_lang, expected in cases:
            with self.subTest(label_text):
                quote = source[2:12]
                errors = stages.brief_hedge_errors(brief_with(fact, quote, label), chapter_with(source),
                                                   src_lang, brief_lang)
                fact_errors = [e for e in errors if e.startswith("characters")]
                kinds = sorted("label" if "epistemic is EXPLICIT" in e else "text" for e in fact_errors)
                self.assertEqual(kinds, expected, errors)
        self.assertEqual(stages.audit_coverage("vi", "vi", "xx")["missing_lexicons"], ["xx"])
        self.assertFalse(stages.audit_coverage("vi", "vi", "xx")["brief_hedge_check"])
        self.assertTrue(stages.audit_coverage("vi", "vi", "xx")["strength_audit"])

    def test_script_must_keep_the_hedges_of_the_brief_clause_it_retells(self):
        brief = brief_json(1)
        brief["characters"][1]["facts"] = [{"text": "Khiêm tốn, và nghe nói rất được các nam sinh tỏ tình",
                                            "evidence": ["1.39"], "quote": "x"}]
        brief["events"][0]["summary"] = "Amane hỏi cô đang làm gì sau khi nhìn thấy nét mặt như sắp khóc"
        brief["characters"][0]["facts"] = [{"text": "Cô không chờ một ai cả", "evidence": ["1.22"], "quote": "x",
                                            "epistemic": "APPEARANCE"}]  # run 7: narrator's 「なさそう」

        def run_case(paragraph, refs):
            units = [{"unit_id": "P001", "sha256": "x", "text": paragraph}]
            critic = {"units": [{"unit_id": "P001", "no_claim_reason": None, "claims": [
                {"claim": "x", "claim_type": "SUPPORTED_FACT", "failure_category": None, "severity": None,
                 "brief_refs": refs, "explanation": "e", "suggested_fix": None}]}]}
            return stages.hedge_audit(critic, [brief], None, units)

        cases = [
            ("hedge dropped", "Cô rất được các nam sinh tỏ tình.", ["c1.CH2"], 1),
            ("hedge kept", "Nghe nói cô rất được các nam sinh tỏ tình.", ["c1.CH2"], 0),
            ("unhedged clause of the same fact", "Cô rất khiêm tốn.", ["c1.CH2"], 0),
            # The brief splits at "sau khi": asking what she is doing is not the hedged part.
            ("other clause of a joined statement", "Amane hỏi cô đang làm gì.", ["c1.E1"], 0),
            ("appearance dropped", "Cậu nhìn thấy nét mặt cô sắp khóc.", ["c1.E1"], 1),
            ("paragraph cites nothing", "Cô rất được các nam sinh tỏ tình.", [], 0),
            # Labelled APPEARANCE in the brief: the label alone makes it hedged.
            ("labelled appearance told as fact", "Cô ngồi đó, không chờ một ai cả.", ["c1.CH1"], 1),
            ("labelled appearance kept", "Cô có vẻ không chờ một ai cả.", ["c1.CH1"], 0),
        ]
        for label, paragraph, refs, expected in cases:
            with self.subTest(label):
                findings = run_case(paragraph, refs)
                self.assertEqual(len(findings), expected, findings)
                for finding in findings:
                    self.assertEqual(finding["source"], "hedge_audit")
        units = [{"unit_id": "P001", "sha256": "x", "text": "Cô rất được các nam sinh tỏ tình."}]
        critic = {"units": [{"unit_id": "P001", "no_claim_reason": None, "claims": [
            {"claim": "x", "claim_type": "SUPPORTED_FACT", "failure_category": None, "severity": None,
             "brief_refs": ["c1.CH2"], "explanation": "e", "suggested_fix": None}]}]}
        self.assertEqual(stages.hedge_audit(critic, [brief], None, units, "vi", "en"), [])  # needs one language
        self.assertEqual(stages.hedge_audit(critic, [brief], None, None), [])
        self.assertFalse(stages.audit_coverage("vi", "en", "ja")["script_hedge_audit"])

    def test_brief_facts_should_be_atomic(self):
        brief = brief_json(1)
        brief["characters"][1]["facts"] = [
            {"text": "Luôn đứng đầu các kỳ thi, và nghe nói giỏi thể dục, và rất khiêm tốn",
             "evidence": ["1.7"], "quote": "x", "epistemic": "REPORTED"},
            {"text": "Luôn đứng đầu các kỳ thi", "evidence": ["1.7"], "quote": "x", "epistemic": "EXPLICIT"},
        ]
        errors = stages.brief_atomicity_errors(brief, "vi")
        self.assertEqual(len(errors), 1)
        self.assertIn("CH2 facts[0]: joins 3 clauses", errors[0])
        self.assertEqual(stages.brief_atomicity_errors(brief, "xx"), [])  # no lexicon: not judged

    def test_source_hedge_review_lists_items_for_a_person(self):
        chapter = Chapter(1, "doc", "t", (Passage("1.1", "彼女は告白を受けているらしい。"),
                                          Passage("1.2", "「雨だろう」と彼は言った。")))
        brief = brief_json(1, ["1.1"], "告白を受けている")
        brief["characters"][1]["facts"] = [
            {"text": "Cô được tỏ tình", "evidence": ["1.1"], "quote": "告白を受けている"},
            {"text": "Nghe nói cô được tỏ tình", "evidence": ["1.1"], "quote": "告白を受けている"},
            {"text": "Trời mưa", "evidence": ["1.2"], "quote": "雨"},  # hedge only inside dialogue
        ]
        brief["events"] = []
        brief["characters"][0]["facts"] = []
        review = stages.source_hedge_review(brief, chapter, "ja", "vi")
        self.assertEqual([(r["ref"], r["text"]) for r in review], [("c1.CH2", "Cô được tỏ tình")])
        self.assertEqual(review[0]["source_hedges"], [["reported", "らしい", "1.1"]])
        self.assertEqual(stages.source_hedge_review(brief, chapter, "xx", "vi"), [])

    def test_critic_must_extract_claims_at_paragraph_density(self):
        paragraph = " ".join(["từ"] * 95)  # 95 words -> at least 3 claims
        units = checks.split_units(paragraph + "\n\nNgắn thôi.")
        one_claim = {"claim": "x", "claim_type": "SUPPORTED_FACT", "failure_category": None, "severity": None,
                     "brief_refs": [], "explanation": "y", "suggested_fix": None}
        cases = [
            ([one_claim], None, 1),          # under-extracted
            ([one_claim] * 3, None, 0),      # dense enough
            ([], "pure narration", 0),       # explicit no-claim reason is respected
        ]
        for claims, reason, expected in cases:
            with self.subTest(claims=len(claims), reason=reason):
                critic = {"units": [{"unit_id": "P001", "claims": claims, "no_claim_reason": reason},
                                    {"unit_id": "P002", "claims": [], "no_claim_reason": None}]}
                errors = stages.critic_density_errors(critic, units)
                self.assertEqual(len(errors), expected, errors)
                if expected:
                    self.assertIn("P001: 95 words but only 1 claims", errors[0])

    def test_strength_audit_flags_intensifiers_missing_from_cited_brief(self):
        brief = brief_json(1)
        brief["events"][0]["consequence"] = "Amane bớt áy náy"
        brief["characters"][1]["facts"][:] = [{"text": "Được ví như thiên thần, vô cùng xinh đẹp",
                                               "evidence": ["1.4"], "quote": "x"}]
        recap = {"chapters": [{"core_events": [{"ref": "c0.E1", "summary": "Hai người chưa bao giờ nói chuyện"}]}]}

        def critic_with(claim_text, refs, claim_type="SUPPORTED_FACT"):
            return {"units": [{"unit_id": "P001", "no_claim_reason": None, "claims": [
                {"claim": claim_text, "claim_type": claim_type, "failure_category": None, "severity": None,
                 "brief_refs": refs, "explanation": "e", "suggested_fix": None}]}]}

        cases = [
            ("Sự áy náy vơi đi rất nhiều", ["c1.E1"], "SUPPORTED_FACT", ["rất nhiều"]),   # live run 3
            ("Mọi người gọi cô bằng biệt danh Thiên sứ", ["c1.CH2"], "SUPPORTED_FACT", ["mọi người", "biệt danh"]),
            ("Cô vô cùng xinh đẹp", ["c1.CH2"], "SUPPORTED_FACT", []),                    # brief has it too
            ("Họ chưa bao giờ nói chuyện", ["c0.E1"], "SUPPORTED_FACT", []),              # recap memory has it
            ("Cô vô cùng đau khổ", [], "SUPPORTED_FACT", []),                             # nothing cited: not judged
            ("Cô vô cùng đau khổ", ["c1.E1"], "UNSUPPORTED_STORY_CLAIM", []),             # critic already flagged it
        ]
        for text, refs, claim_type, expected in cases:
            with self.subTest(text=text, claim_type=claim_type):
                findings = stages.strength_audit(critic_with(text, refs, claim_type), [brief], recap)
                markers = [m for f in findings for m in f["phrases"]]
                self.assertEqual(sorted(markers), sorted(expected))
                for finding in findings:
                    self.assertEqual((finding["severity"], finding["source"]), ("MEDIUM", "strength_audit"))
        # The critic may paraphrase an intensifier away; the paragraph's own wording is checked too.
        units = [{"unit_id": "P001", "sha256": "x", "text": "Cậu thấy vô cùng áy náy. Rồi cậu về nhà."}]
        paraphrased = critic_with("Cậu thấy áy náy", ["c1.E1"])
        text_findings = stages.strength_audit(paraphrased, [brief], recap, units)
        self.assertEqual([(f["source"], f["claim"]) for f in text_findings],
                         [("strength_audit_text", "Cậu thấy vô cùng áy náy.")])
        self.assertEqual(stages.strength_audit(critic_with("Cậu thấy vô cùng áy náy", ["c1.E1"]), [brief],
                                               recap, units)[0]["source"], "strength_audit")  # no duplicate
        self.assertEqual(len(stages.strength_audit(critic_with("Cậu thấy vô cùng áy náy", ["c1.E1"]), [brief],
                                                   recap, units)), 1)
        english_brief = json.loads(json.dumps(brief))
        english_brief["events"][0]["summary"] = "Amane was extremely uneasy"
        cross = stages.strength_audit(critic_with("Amane vô cùng áy náy", ["c1.E1"]), [english_brief],
                                      script_language="vi", brief_language="en")
        self.assertEqual(cross, [])  # degree_extreme is in the English brief too
        self.assertEqual(stages.strength_audit(critic_with("Amane vô cùng áy náy", ["c1.E1"]), [brief],
                                               script_language="xx"), [])  # no lexicon: not judged
        commentary = critic_with("Bình luận", [])
        self.assertEqual(stages.strength_audit(commentary, [brief], recap, units), [])  # cites nothing
        audited = gate_report(critic_with("Sự áy náy vơi đi rất nhiều", ["c1.E1"]),
                              checks.check_script(SCRIPT, 20, 200, "vi"), [brief],
                              stages.strength_audit(critic_with("Sự áy náy vơi đi rất nhiều", ["c1.E1"]), [brief]))
        self.assertEqual(audited["gates"]["GATE_EPISTEMIC_INTEGRITY"]["status"], "FLAG")

    def test_critic_unit_mismatch(self):
        units = checks.split_units("a\n\nb")
        critic = {"units": [{"unit_id": "P001", "claims": [], "no_claim_reason": "none"}]}
        self.assertTrue(stages.critic_semantic_errors(critic, units, {}, {}))


    def test_source_citations_resolve_for_each_supported_brief_ref(self):
        refs = {"c1.E1": ["1.1"], "c1.CH1": ["1.2"]}
        passages = {"1.1": "a quiet day", "1.2": "it seemed to rain"}
        units = [{"unit_id": "TITLE", "text": "a quiet day"}]
        cases = [
            (["c1.E1"], [("1.1", "quiet day")], True),
            (["c1.E1", "c1.CH1"], [("1.1", "quiet day"), ("1.2", "seemed")], True),
            ([], [], False),
            (["c1.E1"], [], False),
            (["c1.E1"], [("1.1", "storm")], False),
            (["c1.E1"], [("1.2", "rain")], False),
            (["c1.E1", "c1.CH1"], [("1.1", "quiet day")], False),
            (["c2.E1"], [("2.1", "spoiler")], False),
        ]
        for brief_refs, excerpts, valid in cases:
            with self.subTest(brief_refs=brief_refs, excerpts=excerpts):
                c = {**claim("SUPPORTED_FACT"), "brief_refs": brief_refs, "source_evidence": [
                    {"passage_id": pid, "quote": quote} for pid, quote in excerpts]}
                audit = {"units": [{"unit_id": "TITLE", "claims": [c], "no_claim_reason": None}]}
                self.assertEqual(not stages.critic_semantic_errors(audit, units, refs, passages), valid)

    def test_evidence_packet_keeps_only_cited_episode_and_recap_passages(self):
        episode = StoryScope("s", "ja", (SAMPLE_CHAPTERS[2],))
        brief = brief_json(2)
        brief["events"][0]["evidence"] = ["2.3", "2.4"]
        brief["closing_hook"] = {"text": "open", "quote": "q", "evidence": ["2.5"]}
        recap = {"chapters": [{"chapter": 1, "core_events": [
            {"ref": "c1.E1", "summary": "earlier", "epistemic": "REPORTED", "evidence": ["1.2"]}]}]}
        refs, passages = stages.critic_evidence(episode, [brief], recap, [SAMPLE_CHAPTERS[1]])
        self.assertEqual(set(passages), {"1.2", "2.2", "2.3", "2.4", "2.5"})
        self.assertEqual(passages["2.3"], PASSAGE_TEXT["2.3"])
        self.assertEqual(refs["c2.R1"], ["2.2"])
        self.assertEqual(refs["c2.END"], ["2.5"])
        self.assertIn("2.4", refs["c2.CH2"])
        self.assertEqual(stages.labelled_statements([brief], recap)["c1.E1"], [("earlier", "REPORTED")])
        with self.assertRaisesRegex(ValueError, "precede"):
            run(ScriptedLLMClient(FakeModel()), episode, test_profile(), Path("unused"),
                background=[SAMPLE_CHAPTERS[3]])


class FactsTests(unittest.TestCase):
    def test_valid_and_invalid(self):
        facts = StoryFacts({"format": "story_facts/v0", "chapters": [{"chapter_order": 1, "facts": [
            {"text": "A gives B an umbrella", "kind": "EVENT", "epistemic": "EXPLICIT", "evidence": ["1.40"]}]}]})
        self.assertIn("EVENT/EXPLICIT", facts.render_for_chapter(1))
        self.assertEqual(facts.render_for_chapter(2), "")
        with self.assertRaises(FactsError):
            StoryFacts({"format": "story_facts/v0", "chapters": [{"chapter_order": 1}]})


class EndToEndTests(unittest.TestCase):
    def test_full_pipeline_with_revision(self):
        scope = load_scope(DEFAULT_MANIFEST, (1, 2))
        model = FakeModel()
        client = ScriptedLLMClient(model)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            manifest = run(client, scope, test_profile(), out)
            self.assertEqual(manifest["status"], "COMPLETED", manifest.get("error"))
            stages_called = [c["stage"] for c in client.calls]
            self.assertEqual(stages_called, ["brief", "brief", "plan", "script", "critic", "revise", "critic"])
            for name in ("briefs/chapter_001.json", "briefs/chapter_002.json", "plan.json", "script_v1.json",
                         "critic_v1.json", "script_v2.json", "critic_v2.json", "script_final.md",
                         "report.json", "report.md", "calls.jsonl", "run_manifest.json"):
                self.assertTrue((out / name).is_file(), name)
            report = json.loads((out / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["gates"]["GATE_FACTUAL_GROUNDING"]["status"], "PASS")
            self.assertEqual(report["gates"]["GATE_OUTPUT_INTEGRITY"]["status"], "PASS")
            self.assertEqual([v["problem_claims"] for v in manifest["versions"]], [1, 0])
            self.assertIn("ĐẠT", (out / "report.md").read_text(encoding="utf-8"))
            self.assertTrue((out / "review_form.md").is_file())
            coverage = report["gates"]["GATE_NECESSARY_COVERAGE"]
            # The fake critic only cites c1.E1, so chapter 2's CORE event is reported as not cited.
            self.assertEqual((coverage["status"], coverage["not_cited"]), ("FLAG", ["c2.E1"]))

            # Resume reuses every stage output: no new model calls.
            resumed_client = ScriptedLLMClient(FakeModel())
            resumed = run(resumed_client, scope, test_profile(), out, resume=True)
            self.assertEqual(resumed["status"], "COMPLETED")
            self.assertEqual(resumed_client.calls, [])

    def test_title_finding_reaches_revision_with_source_and_stays_out_of_coverage(self):
        scope = load_scope(DEFAULT_MANIFEST, (1, 1))
        fallback = FakeModel()
        fixed = {**SCRIPT, "title_idea": "Một chiếc ô giữa trời mưa"}
        title_prompts = []

        def respond(stage, system, user):
            if stage == "critic":
                self.assertIn(PASSAGE_TEXT["1.2"], user)
                self.assertNotIn(PASSAGE_TEXT["2.28"], user)
                audit = critic_json(user, False)
                title = audit["units"][0]
                self.assertEqual(title["unit_id"], "TITLE")
                title_prompts.append(user)
                for unit in audit["units"][1:]:
                    unit.update(claims=[], no_claim_reason="editorial aside")
                if len(title_prompts) == 1:
                    title["claims"] = [claim("STRENGTHENED_STORY_CLAIM", "MEDIUM", "EPISTEMIC_ERROR")]
                else:
                    self.assertIn(fixed["title_idea"], user)
                return json.dumps(audit)
            if stage == "script":
                return json.dumps({**SCRIPT, "title_idea": "Cơn bão định mệnh"})
            if stage == "revise":
                self.assertIn("in TITLE", user)
                self.assertIn(PASSAGE_TEXT["1.2"][:12], user)
                return json.dumps(fixed)
            return fallback(stage, system, user)

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            manifest = run(ScriptedLLMClient(respond), scope, test_profile(), out)
            self.assertEqual(manifest["status"], "COMPLETED", manifest.get("error"))
            self.assertEqual(len(title_prompts), 2)
            review = (out / "review_form.md").read_text(encoding="utf-8")
            self.assertIn(fixed["title_idea"], review)
            self.assertIn(SECTION_1, review)
            report = json.loads((out / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["gates"]["GATE_NECESSARY_COVERAGE"]["not_cited"], ["c1.E1"])
            self.assertEqual(manifest["versions"][1]["problem_claims"], 0)

    def test_resume_rechecks_legacy_critic_and_changed_upstream_artifacts(self):
        scope = load_scope(DEFAULT_MANIFEST, (1, 1))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            run(ScriptedLLMClient(FakeModel()), scope, test_profile(), out, stop_after="critic")
            (out / "critic_v1.cache.json").unlink()  # no receipt on an old audit
            (out / "critic_v1.json").write_text('{"units":[]}', encoding="utf-8")
            client = ScriptedLLMClient(FakeModel())
            run(client, scope, test_profile(), out, resume=True, stop_after="critic")
            self.assertEqual([c["stage"] for c in client.calls], ["critic"])
            (out / "script_v1.json").write_text("{broken", encoding="utf-8")
            client = ScriptedLLMClient(FakeModel())
            run(client, scope, test_profile(), out, resume=True, stop_after="critic")
            self.assertEqual([c["stage"] for c in client.calls], ["script"])
            client = ScriptedLLMClient(FakeModel())
            changed = test_profile().with_length(21, 201)
            run(client, scope, changed, out, resume=True, stop_after="critic")
            self.assertEqual([c["stage"] for c in client.calls], ["brief", "plan", "script", "critic"])

    def test_episode_with_memory_recap(self):
        full = load_scope(DEFAULT_MANIFEST, (1, 3))
        background = list(full.chapters[:2])
        episode = StoryScope(full.story_id, full.source_language, (full.chapters[2],))
        chapter_4_text = load_scope(DEFAULT_MANIFEST, (4, 4)).chapters[0].passages[3].text
        with tempfile.TemporaryDirectory() as tmp:
            memory = StoryMemory(Path(tmp) / "memory", full.story_id)
            model = FakeModel()
            client = ScriptedLLMClient(model)
            manifest = run(client, episode, test_profile(), Path(tmp) / "ep1", background=background,
                           memory=memory)
            self.assertEqual(manifest["status"], "COMPLETED", manifest.get("error"))
            self.assertEqual(manifest["background_chapters"], [1, 2])
            self.assertEqual(manifest["brief_sources"], {"1": "model", "2": "model", "3": "model"})
            self.assertEqual(memory.stored_chapters(), [1, 2, 3])
            recap = json.loads((Path(tmp) / "ep1" / "memory_recap.json").read_text(encoding="utf-8"))
            self.assertEqual(recap["covers_chapters"], [1, 2])
            plan_prompt = model.plan_prompts[0]
            self.assertRegex(plan_prompt, r'"ref":\s*"c1\.E1"')      # callback material from memory
            self.assertNotIn(chapter_4_text, plan_prompt)     # nothing past the episode
            report = json.loads((Path(tmp) / "ep1" / "report.json").read_text(encoding="utf-8"))
            # Coverage is required for the episode's chapter only, not for recapped chapters.
            self.assertEqual(report["gates"]["GATE_NECESSARY_COVERAGE"]["core_events"], 1)

            # A second run reuses every brief from memory: no brief calls at all.
            again = ScriptedLLMClient(FakeModel())
            second = run(again, episode, test_profile(), Path(tmp) / "ep2", background=background,
                         memory=memory)
            self.assertEqual(second["brief_sources"], {"1": "memory", "2": "memory", "3": "memory"})
            self.assertNotIn("brief", [c["stage"] for c in again.calls])

    def test_memory_brief_failing_current_checks_is_regenerated(self):
        scope = load_scope(DEFAULT_MANIFEST, (1, 1))
        chapter = scope.chapters[0]
        with tempfile.TemporaryDirectory() as tmp:
            memory = StoryMemory(Path(tmp) / "memory", scope.story_id)
            stale = brief_json(1)
            stale["events"] = stale["events"][:2]  # written before the granularity rule existed
            first = run(ScriptedLLMClient(FakeModel()), scope, test_profile(), Path(tmp) / "seed",
                        memory=memory, stop_after="brief")
            self.assertEqual(first["status"], "STOPPED_AFTER_BRIEF")
            record = json.loads(next(memory.directory.glob("chapter_*.json")).read_text(encoding="utf-8"))
            memory.put_brief(1, chapter.version, record["brief_fingerprint"], stale, "old-model")
            client = ScriptedLLMClient(FakeModel())
            manifest = run(client, scope, test_profile(), Path(tmp) / "run", memory=memory)
            self.assertEqual(manifest["status"], "COMPLETED", manifest.get("error"))
            self.assertEqual(manifest["brief_sources"], {"1": "model (memory stale)"})
            self.assertIn("needs at least 5 events", manifest["stale_memory"]["1"][0])
            self.assertEqual([c["stage"] for c in client.calls][0], "brief")
            again = ScriptedLLMClient(FakeModel())  # the regenerated brief is valid and reused
            reused = run(again, scope, test_profile(), Path(tmp) / "run2", memory=memory)
            self.assertEqual(reused["brief_sources"], {"1": "memory"})

    def test_recap_budget_and_missing_core_revision(self):
        scope = load_scope(DEFAULT_MANIFEST, (1, 1))
        fallback = FakeModel()
        repairs = []
        critic_calls = []

        def respond(stage, system, user):
            if stage in ("plan", "script", "revise"):
                self.assertIn("ngôi thứ ba", user.lower())
                self.assertNotIn('"evidence":', user)
            if stage == "critic":
                self.assertIn(PASSAGE_TEXT["1.2"], user)
                audit = critic_json(user, False)
                if not critic_calls:
                    for unit in audit["units"][1:]:
                        unit["claims"][0]["brief_refs"] = ["c1.E2"]
                critic_calls.append(user)
                return json.dumps(audit)
            if stage == "revise":
                repairs.append(user)
            return fallback(stage, system, user)

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            client = ScriptedLLMClient(respond)
            manifest = run(client, scope, load_profile(), out)
            self.assertEqual(manifest["status"], "COMPLETED", manifest.get("error"))
            self.assertEqual([c["stage"] for c in client.calls],
                             ["brief", "plan", "script", "critic", "revise", "critic"])
            self.assertIn("CORE coverage c1.E1", repairs[0])
            report = json.loads((out / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["final_check"]["length_target"], [48, 60])
            self.assertEqual(report["compression"]["basis"], "estimated_translation")
            self.assertAlmostEqual(report["compression"]["actual_ratio"], checks.count_words(checks.script_text(SCRIPT)) / 120)
            self.assertEqual(report["gates"]["GATE_NECESSARY_COVERAGE"]["status"], "PASS")
            self.assertEqual(manifest["usage_by_stage_model"]["critic"]["unknown"], {"calls": 2, "calls_with_total": 0})

    def test_ratio_uses_episode_only_and_preserves_absolute_override(self):
        scope = load_scope(DEFAULT_MANIFEST, (2, 2))
        cases = [
            (scope, None, "estimated_translation", 120),
            (scope, 2000, "user_supplied", 2000),
            (StoryScope(scope.story_id, "vi", scope.chapters), None, "source_count",
             sum(checks.count_length(p.text, "vi") for p in scope.chapters[0].passages)),
        ]
        for episode, units, basis, denominator in cases:
            with self.subTest(basis=basis), tempfile.TemporaryDirectory() as tmp:
                manifest = run(ScriptedLLMClient(FakeModel()), episode, load_profile(), Path(tmp),
                               background=[SAMPLE_CHAPTERS[1]], full_target_units=units, stop_after="brief")
                self.assertEqual(manifest["status"], "STOPPED_AFTER_BRIEF", manifest.get("error"))
                self.assertEqual(manifest["compression"]["basis"], basis)
                self.assertEqual(manifest["compression"]["full_target_units"], denominator)
        with self.assertRaises(ValueError):
            run(ScriptedLLMClient(FakeModel()), scope, test_profile(), Path("unused"), full_target_units=20)

    def test_cli_episode_mode(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("tools.story_pipeline.llm.GeminiLLMClient",
                           lambda *a, **k: ScriptedLLMClient(FakeModel())), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            code = run_pipeline.main(["--chapters", "2", "--recap", "--memory", str(Path(tmp) / "mem"),
                                      "--out", str(Path(tmp) / "run"), "--min-words", "20", "--max-words", "200"])
            self.assertEqual(code, 0, out.getvalue())
            manifest = json.loads((Path(tmp) / "run" / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual((manifest["scope"]["chapters"], manifest["background_chapters"]), ([2], [1]))
            self.assertTrue((Path(tmp) / "run" / "memory_recap.json").is_file())
            self.assertTrue(any((Path(tmp) / "mem").rglob("chapter_002.json")))

    def test_plan_may_call_back_to_recap_but_must_cover_episode(self):
        profile = test_profile()
        recap = {"chapters": [{"core_events": [{"ref": "c1.E1", "summary": "x"}]}]}
        plan = json.loads(json.dumps(PLAN))
        plan["beats"][0]["event_refs"] = ["c1.E1"]          # callback to an earlier chapter
        plan["beats"][1]["event_refs"] = ["c2.E1", "c2.E2"]
        plan["hook"]["event_refs"] = ["c2.E1"]
        self.assertEqual(stages.plan_semantic_errors(plan, [brief_json(2)], profile, recap), [])
        errors = stages.plan_semantic_errors(plan, [brief_json(2)], profile)
        self.assertTrue(any("unknown event refs ['c1.E1']" in e for e in errors))
        plan["beats"][1]["event_refs"] = ["c2.E2"]
        errors = stages.plan_semantic_errors(plan, [brief_json(2)], profile, recap)
        self.assertTrue(any("CORE events not covered" in e and "c2.E1" in e for e in errors))

    def test_stage_failure_is_recorded(self):
        scope = load_scope(DEFAULT_MANIFEST, (1, 1))
        client = ScriptedLLMClient(lambda stage, s, u: json.dumps(brief_json(1, ["9.9"])))
        with tempfile.TemporaryDirectory() as tmp:
            manifest = run(client, scope, test_profile(), Path(tmp) / "run", max_repairs=1)
            self.assertEqual(manifest["status"], "FAILED")
            self.assertIn("brief", manifest["error"])
            self.assertEqual(len(client.calls), 2)

    def test_gate_report_severity(self):
        critic = {"units": [{"unit_id": "P001", "no_claim_reason": None, "claims": [
            claim("CONTRADICTED_STORY_CLAIM", "HIGH", "FACTUAL_ERROR"),
            claim("STRENGTHENED_STORY_CLAIM", "LOW", "EPISTEMIC_ERROR"),
            claim("UNDETERMINED")]}]}
        report = gate_report(critic, checks.check_script(SCRIPT, 20, 200, "vi"))
        self.assertEqual(report["gates"]["GATE_FACTUAL_GROUNDING"]["status"], "FAIL")
        self.assertEqual(report["gates"]["GATE_EPISTEMIC_INTEGRITY"]["status"], "FLAG")
        self.assertEqual(len(report["undetermined"]), 1)
        unresolved = {"units": [{"unit_id": "TITLE", "claims": [claim("UNDETERMINED")]}]}
        flags = gate_report(unresolved, checks.check_script(SCRIPT, 20, 200, "vi"))
        self.assertEqual(flags["gates"]["GATE_FACTUAL_GROUNDING"]["status"], "FLAG")
        self.assertEqual(report["gates"]["GATE_NECESSARY_COVERAGE"]["status"], "PLAN_ONLY")
        brief = [brief_json(1)]
        uncited = gate_report(critic, checks.check_script(SCRIPT, 20, 200, "vi"), brief)
        # Problem claims do not count as narrating an event; only supported claims do.
        self.assertEqual(uncited["gates"]["GATE_NECESSARY_COVERAGE"]["not_cited"], ["c1.E1"])
        critic["units"][0]["claims"].append(claim("SUPPORTED_FACT"))
        covered = gate_report(critic, checks.check_script(SCRIPT, 20, 200, "vi"), brief)
        self.assertEqual(covered["gates"]["GATE_NECESSARY_COVERAGE"]["status"], "PASS")


class GeminiClientTests(unittest.TestCase):
    def test_uses_existing_transport_with_fake_sdk(self):
        class FakeResponse:
            text = '{"n": 1}'
            usage_metadata = None
            model_version = "fake"

        class FakeSDK:
            def generate(self, **kwargs):
                self.kwargs = kwargs
                return FakeResponse()

        sdk = FakeSDK()
        client = GeminiLLMClient("fake-model", dotenv_path=REPO / "does-not-exist.env",
                                 client_factory=lambda key: sdk,
                                 environ={"GEMINI_API_KEY_1": "test-key-not-real"})
        record = client.complete(system="s", user="u", request_id="t:1")
        self.assertEqual(record["raw_content"], '{"n": 1}')
        self.assertEqual(sdk.kwargs["model"], "fake-model")
        self.assertEqual(client.name, "gemini:fake-model")
        self.assertEqual(record["fallback_from"], [])
        routed = GeminiLLMClient("base", stage_models={"critic": "checker,backup"},
                                 client_factory=lambda key: sdk, dotenv_path=REPO / "unused",
                                 environ={"GEMINI_API_KEY_1": "test-key-not-real"})
        for stage, model in (("plan", "base"), ("critic", "checker"), ("revise", "base")):
            with self.subTest(stage=stage):
                record = routed.complete(system="s", user="u", request_id=f"{stage}:v1:attempt2")
                self.assertEqual(record["model_requested"], model)
        log = CallLog()
        for usage in ({"total_token_count": 8, "thoughts_token_count": 2}, {"total_token_count": 4}, None):
            log.add({"stage": "critic", "model": "checker", "usage": usage})
        self.assertEqual(log.usage_summary()["critic"]["checker"],
                         {"calls": 3, "calls_with_total": 2, "total_token_count": 12, "thoughts_token_count": 2})

    def test_model_fallback_chain(self):
        class ProviderError(Exception):
            def __init__(self, code):
                super().__init__(f"HTTP {code}")
                self.code = code

        class FakeResponse:
            text = '{"n": 1}'
            usage_metadata = None
            model_version = "fake"

        class FakeSDK:
            def __init__(self, failures):
                self.failures = failures  # model -> HTTP status it fails with
                self.calls = []

            def generate(self, **kwargs):
                self.calls.append(kwargs["model"])
                failure = self.failures.get(kwargs["model"])
                if isinstance(failure, list):  # a different status on each successive call
                    failure = failure.pop(0) if failure else None
                if failure == "timeout":
                    raise TimeoutError("read timed out")
                if failure:
                    raise ProviderError(failure)
                return FakeResponse()

        def client_for(sdk):
            now = [1000.0]  # simulated time: sleeping advances it, so key cooldowns expire

            def sleep(seconds):
                now[0] += seconds

            return GeminiLLMClient("busy-model, spare-model", dotenv_path=REPO / "does-not-exist.env",
                                   client_factory=lambda key: sdk, max_transport_retries=1,
                                   sleep=sleep, clock=lambda: now[0],
                                   environ={"GEMINI_API_KEY_1": "test-key-not-real"})

        cases = [
            ("overloaded first model falls back", {"busy-model": 503}, "ok",
             ["busy-model", "busy-model", "spare-model"]),
            ("quota on first model falls back", {"busy-model": 429}, "ok", None),
            ("rejected request does not fall back", {"busy-model": 400}, "raise", ["busy-model"]),
            ("unclassified error after a retry falls back", {"busy-model": [503, 400]}, "ok",
             ["busy-model", "busy-model", "spare-model"]),
            ("dropped connection is retried, then falls back", {"busy-model": ["timeout", "timeout"]}, "ok",
             ["busy-model", "busy-model", "spare-model"]),
            ("every model down raises", {"busy-model": 503, "spare-model": 503}, "raise", None),
        ]
        for label, failures, outcome, expected_calls in cases:
            with self.subTest(label):
                sdk = FakeSDK(failures)
                client = client_for(sdk)
                self.assertEqual(client.name, "gemini:busy-model,spare-model")
                if outcome == "ok":
                    record = client.complete(system="s", user="u", request_id="t:1")
                    self.assertEqual(record["model_requested"], "spare-model")
                    self.assertEqual(record["fallback_from"][0]["model"], "busy-model")
                    self.assertEqual(len(record["attempt_failures"]), len(sdk.calls) - 1)
                else:
                    with self.assertRaises(RuntimeError) as raised:
                        client.complete(system="s", user="u", request_id="t:1")
                    self.assertIn("attempt errors:", str(raised.exception))
                    self.assertIn("ProviderError", str(raised.exception))
                if expected_calls is not None:
                    self.assertEqual(sdk.calls, expected_calls)


if __name__ == "__main__":
    unittest.main()
