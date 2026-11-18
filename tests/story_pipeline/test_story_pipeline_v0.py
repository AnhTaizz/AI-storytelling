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

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.story_pipeline import checks, episode_brief, stages  # noqa: E402
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
from tools.story_pipeline.run_pipeline import DEFAULT_MANIFEST, gate_report, pending_owner_errors, run  # noqa: E402
from tools.story_memory.memory_v0 import StoryMemory  # noqa: E402
from tools.story_pipeline.source import (  # noqa: E402
    Chapter, Passage, StoryScope, layout_warnings, load_scope, parse_range,
)

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
REVISED = {"title_idea": "Chiếc ô", "sections": [{"beat_id": "B1", "text": SECTION_1.replace("chiều", "tối")},
                                                  {"beat_id": "B2", "text": SECTION_2}]}


def claim(claim_type, severity=None, category=None):
    return {"claim": "x", "claim_type": claim_type, "failure_category": category, "severity": severity,
            "brief_refs": ["c1.E1"], "explanation": "y", "suggested_fix": "z" if severity else None}


def critic_json(user, with_problem):
    unit_ids = re.findall(r"^<(P\d{3})>$", user, re.MULTILINE)
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
            return json.dumps(brief_json(order), ensure_ascii=False)
        if stage == "plan":
            # Use exactly the event refs the prompt offers (episode briefs and recap memory).
            self.plan_prompts.append(user)
            refs = list(dict.fromkeys(re.findall(r'"ref": "(c\d+\.E\d+)"', user)))
            plan = json.loads(json.dumps(PLAN))
            plan["hook"]["event_refs"] = refs[:1]
            plan["beats"][0]["event_refs"] = refs[:1]
            plan["beats"][1]["event_refs"] = refs[1:]
            return json.dumps(plan, ensure_ascii=False)
        if stage == "script":
            return "```json\n" + json.dumps(SCRIPT, ensure_ascii=False) + "\n```"
        if stage == "revise":  # rewords the first paragraph, where the first critic found the problem
            return json.dumps(REVISED, ensure_ascii=False)
        if stage == "critic":
            self.critic_calls += 1
            return json.dumps(critic_json(user, self.critic_calls == 1), ensure_ascii=False)
        if stage == "source_check":
            units = list(dict.fromkeys(re.findall(r"<(P\d{3})>", user)))
            return json.dumps({"paragraphs": [{"unit_id": u, "findings": []} for u in units],
                               "critic_reviews": critic_reviews(user, self.flag_verdict)})
        if stage == "brief_check":
            return json.dumps({"findings": []})
        raise AssertionError(stage)

    flag_verdict = "NOT_IN_SOURCE"


def critic_reviews(user, verdict):
    """An answer for every critic statement the source-check prompt lists."""
    return [{"id": flag, "verdict": verdict, "passage_ids": ["1.2"] if verdict == "IN_SOURCE" else [],
             "explanation": "nguồn nói vậy" if verdict == "IN_SOURCE" else "nguồn không có"}
            for flag in re.findall(r"^(F\d+) \(", user, re.MULTILINE)]


def test_profile():
    return load_profile().with_length(20, 200)


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


    def test_chapter_packed_into_one_passage_is_reported(self):
        """A source with single line breaks reaches the pipeline as one huge passage."""
        packed = Chapter(2, "doc", "t", (Passage("2.1", "\n".join(f"문장 {n}." for n in range(8))),))
        normal = load_scope(DEFAULT_MANIFEST, (1, 1)).chapters[0]
        warnings = layout_warnings([normal, packed])
        self.assertEqual(len(warnings), 1)
        self.assertIn("chapter 2: 8 lines in 1 passage(s)", warnings[0])
        report = run_pipeline.report_markdown(
            {"run_id": "r", "scope": {"label": "chapter 2", "story_id": "s"}, "client": "c",
             "profile": {"profile_id": "p", "min_words": 1, "max_words": 2}, "model_calls": 0, "seconds": 0,
             "status": "COMPLETED", "source_warnings": warnings, "versions": []},
            {"gates": {}, "claim_counts": {}, "findings": [], "undetermined": []})
        self.assertIn("Cảnh báo nguồn", report)


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
            ("Korean appearance with a simile marker", "소연의 눈가가 조금 붉어진 것처럼 보였다.",
             "Vành mắt So-yeon có vẻ hơi đỏ", "APPEARANCE", "ko", "vi", []),
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

    def test_thought_or_narration_must_not_become_speech(self):
        """Live run 10: Amane's thought (4.18) was told as something he explains to Mahiru."""
        brief = brief_json(1)
        brief["characters"][0]["facts"] = [
            {"text": "Đã đưa ô vì bận tâm đến ánh mắt như đứa trẻ bị lạc của cô", "evidence": ["1.18"],
             "quote": "x", "epistemic": "FIGURATIVE"},
            {"text": "Nói dối rằng đã đưa ô cho một đứa trẻ bị lạc", "evidence": ["1.18"], "quote": "x",
             "epistemic": "EXPLICIT"},
            {"text": "Cho rằng sẽ không còn gặp lại Mahiru nữa", "evidence": ["1.30"], "quote": "x",
             "epistemic": "EXPLICIT"},
        ]
        passages = {"1.18": "彼女が気になったからこそ傘を押し付けたのだ。", "1.30": "「もう会わないだろ」と周は言った。"}

        def run_case(paragraph, refs):
            units = [{"unit_id": "P001", "sha256": "x", "text": paragraph}]
            critic = {"units": [{"unit_id": "P001", "no_claim_reason": None, "claims": [
                {"claim": "x", "claim_type": "SUPPORTED_FACT", "failure_category": None, "severity": None,
                 "brief_refs": refs, "explanation": "e", "suggested_fix": None}]}]}
            return stages.attribution_audit(critic, [brief], units, passages)

        cases = [
            ("thought told as speech",
             "Amane trấn an cô, giải thích rằng cậu bận tâm đến ánh mắt như đứa trẻ bị lạc của cô.", ["c1.CH1"], 1),
            ("same content as a thought", "Cậu đưa ô vì bận tâm đến ánh mắt như đứa trẻ bị lạc của cô.", ["c1.CH1"], 0),
            # The brief records that he said it, so telling it as speech is right.
            ("brief records the speech", "Amane nói rằng đã đưa ô cho một đứa trẻ bị lạc.", ["c1.CH1"], 0),
            # A cited passage has dialogue, so the brief may have summarised speech.
            ("cited passage has dialogue", "Amane nói rằng sẽ không còn gặp lại Mahiru nữa.", ["c1.CH1"], 0),
            ("hearsay is not speech", "Nghe nói rằng cậu bận tâm đến ánh mắt như đứa trẻ bị lạc của cô.", ["c1.CH1"], 0),
            ("paragraph cites nothing",
             "Amane giải thích rằng cậu bận tâm đến ánh mắt như đứa trẻ bị lạc của cô.", [], 0),
        ]
        for label, paragraph, refs, expected in cases:
            with self.subTest(label):
                findings = run_case(paragraph, refs)
                self.assertEqual(len(findings), expected, findings)
                for finding in findings:
                    self.assertEqual((finding["source"], finding["severity"]), ("attribution_audit", "MEDIUM"))
        self.assertEqual(stages.attribution_audit({"units": []}, [brief], None, passages), [])
        self.assertEqual(stages.attribution_audit({"units": []}, [brief], [], passages, "vi", "en"), [])
        self.assertTrue(stages.audit_coverage("vi", "vi", "ja")["attribution_audit"])
        self.assertFalse(stages.audit_coverage("ko", "ko", "ko")["attribution_audit"])  # no speech verbs yet

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
        # A labelled fact must be one statement (live run 14: the plain half became a rumour too).
        cases = [
            ("rumour joined to a plain action", "Nghe nói Itsuki đã lo lắng cho Amane và gửi tin nhắn hỏi thăm cậu",
             "REPORTED", 1),
            ("time clause stays with its statement", "Vành mắt có vẻ hơi ửng đỏ khi ngẩng đầu nhìn cậu",
             "APPEARANCE", 0),
            ("nouns joined by và", "Có lẽ cô chăm sóc cậu do tinh thần trách nhiệm và cảm giác tội lỗi",
             "SPECULATION", 0),
            ("plain fact may join two statements", "Itsuki đã lo lắng cho Amane và gửi tin nhắn hỏi thăm cậu",
             "EXPLICIT", 0),
        ]
        for label, text, epistemic, expected in cases:
            with self.subTest(label):
                brief["characters"][1]["facts"] = [{"text": text, "evidence": ["1.7"], "quote": "x",
                                                    "epistemic": epistemic}]
                errors = stages.brief_atomicity_errors(brief, "vi")
                self.assertEqual(len(errors), expected, errors)
                self.assertTrue(all("one statement" in e for e in errors))
        # Events too: an APPEARANCE event that also tells a plain action hedges the action as well.
        brief["characters"][1]["facts"] = []
        brief["events"][0].update(summary="So-yeon có vẻ khựng lại một chút khi chạm mắt rồi cúi đầu chào cậu bạn",
                                  epistemic="APPEARANCE")
        self.assertIn("event E1: is APPEARANCE but joins 2 statements", stages.brief_atomicity_errors(brief, "vi")[0])
        brief["events"][0]["epistemic"] = "EXPLICIT"
        self.assertEqual(stages.brief_atomicity_errors(brief, "vi"), [])
        self.assertEqual(stages.brief_atomicity_errors(brief, "xx"), [])  # no lexicon: not judged

    def test_brief_text_must_be_in_the_brief_language(self):
        """Runs 12-13 left 붉어, 面 and 廊 inside Vietnamese briefs; 廊 then reached a script."""
        def brief_with(**changes):
            brief = brief_json(1)
            for path, value in changes.items():
                if path == "fact":
                    brief["characters"][0]["facts"][0]["text"] = value
                elif path == "location":
                    brief["events"][0]["location"] = value
                elif path == "unknown":
                    brief["unknowns"] = [value]
            return brief

        cases = [
            ("kanji in a fact", brief_with(fact="Có vẻ rất khỏe mạnh và sắc面 tươi tắn"), ["'sắc面'"]),
            ("Hangul location", brief_with(location="편의점 처마 밑"), ["'편의점'", "'처마'", "'밑'"]),
            ("kana in an unknown", brief_with(unknown="Vì sao cô ở hành 廊"), ["'廊'"]),
            ("clean brief", brief_json(1), []),
        ]
        for label, brief, expected in cases:
            with self.subTest(label):
                errors = stages.brief_script_errors(brief, "vi")
                self.assertEqual(len(errors), 1 if expected else 0, errors)
                for word in expected:
                    self.assertIn(word, errors[0])
        quoted = brief_json(1)
        quoted["characters"][0]["name"] = "藤宮周"  # names and quotes keep the source script
        self.assertEqual(stages.brief_script_errors(quoted, "vi"), [])
        self.assertEqual(stages.brief_script_errors(brief_with(fact="面"), None), [])

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

    def test_source_strength_review_lists_briefs_stronger_than_their_source(self):
        """A brief that already overstates passes the script audits (live run 10: "dữ dội")."""
        chapter = Chapter(1, "doc", "t", (Passage("1.1", "学年問わず告白を受けているらしい。"),
                                          Passage("1.2", "恐らく警戒を緩める事はないだろう。"),
                                          Passage("1.3", "彼女の評判はよく聞く。")))
        brief = brief_json(1, ["1.1"], "告白")
        brief["characters"][1]["facts"] = [
            {"text": "Nghe nói cô thường xuyên được tỏ tình", "evidence": ["1.1"], "quote": "x"},
            {"text": "Cô nổi tiếng trong trường", "evidence": ["1.3"], "quote": "x"},  # 評判 backs it
            {"text": "Nghe nói cô được tỏ tình", "evidence": ["1.1"], "quote": "x"},
        ]
        brief["characters"][0]["facts"] = []
        brief["events"] = [dict(brief["events"][0], summary="Cô chắc chắn sẽ cảnh giác", consequence=None,
                                evidence=["1.2"])]
        review = stages.source_strength_review(brief, chapter, "ja", "vi")
        self.assertEqual([(r["ref"], r["phrases"]) for r in review],
                         [("c1.CH2", ["thường xuyên"]), ("c1.E1", ["chắc chắn"])])
        self.assertEqual(stages.source_strength_review(brief, chapter, "xx", "vi"), [])
        report = run_pipeline.report_markdown(
            {"run_id": "r", "scope": {"label": "chapter 1", "story_id": "s"}, "client": "c",
             "profile": {"profile_id": "p", "min_words": 1, "max_words": 2}, "model_calls": 0, "seconds": 0,
             "status": "COMPLETED", "versions": []},
            {"gates": {}, "claim_counts": {}, "findings": [], "undetermined": [], "source_strength_review": review})
        self.assertIn("brief có thể mạnh hơn nguồn", report)

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
        # "mọi người" addressing the viewers (live run 13) is not "everyone".
        units = [{"unit_id": "P001", "sha256": "x",
                  "text": "Cậu thấy vô cùng áy náy. Rồi cậu về nhà. Thương ghê, đúng không mọi người?"}]
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
        self.assertTrue(stages.critic_semantic_errors(critic, units))


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
            # One source-check call per four paragraphs by default (this script has two).
            # Each episode brief is checked against its chapter's source before planning (M7).
            self.assertEqual(stages_called, ["brief", "brief", "brief_check", "brief_check", "plan", "script",
                                             "critic", "source_check", "revise", "critic", "source_check"])
            self.assertTrue((out / "brief_check.md").is_file())
            for name in ("briefs/chapter_001.json", "briefs/chapter_002.json", "plan.json", "script_v1.json",
                         "critic_v1.json", "source_check_v1.json", "script_v2.json",
                         "critic_v2.json", "source_check_v2.json", "script_final.md", "script_final.txt",
                         "report.json", "report.md", "calls.jsonl", "run_manifest.json"):
                self.assertTrue((out / name).is_file(), name)
            report = json.loads((out / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["gates"]["GATE_FACTUAL_GROUNDING"]["status"], "PASS")
            self.assertEqual(report["gates"]["GATE_OUTPUT_INTEGRITY"]["status"], "PASS")
            self.assertEqual([v["problem_claims"] for v in manifest["versions"]], [1, 0])
            self.assertIn("ĐẠT", (out / "report.md").read_text(encoding="utf-8"))
            self.assertEqual((out / "script_final.txt").read_text(encoding="utf-8"),
                             checks.script_text(REVISED).strip() + "\n")
            self.assertTrue((out / "review_form.md").is_file())
            self.assertIn("<form id='review'", (out / "review.html").read_text(encoding="utf-8"))
            coverage = report["gates"]["GATE_NECESSARY_COVERAGE"]
            # The fake critic only cites c1.E1, so chapter 2's CORE event is reported as not cited.
            self.assertEqual((coverage["status"], coverage["not_cited"]), ("FLAG", ["c2.E1"]))

            # Resume reuses every stage output: no new model calls.
            resumed_client = ScriptedLLMClient(FakeModel())
            resumed = run(resumed_client, scope, test_profile(), out, resume=True)
            self.assertEqual(resumed["status"], "COMPLETED")
            self.assertEqual(resumed_client.calls, [])

    def test_source_check_findings_go_to_revision_and_the_report(self):
        """The second verifier reads the script against the source text (live run 10)."""
        scope = load_scope(DEFAULT_MANIFEST, (1, 1))

        class SourceCheckModel(FakeModel):
            """The first source check finds an invented detail; the critic finds nothing."""
            def __init__(self):
                super().__init__()
                self.checks = 0
                self.critic_calls = 1

            def __call__(self, stage, system, user):
                if stage != "source_check":
                    return super().__call__(stage, system, user)
                self.checks += 1
                units = list(dict.fromkeys(re.findall(r"<(P\d{3})>", user)))
                first = re.search(r"<P001>\n(.+?)\n</P001>", user, re.S)
                findings = [{"script_quote": first.group(1)[:12], "kind": "CONTRADICTS_SOURCE", "passage_ids": ["1.2"],
                             "explanation": "the source says otherwise"}] if self.checks == 1 and first else []
                return json.dumps({"paragraphs": [{"unit_id": u, "findings": findings if u == "P001" else []}
                                                  for u in units], "critic_reviews": []})

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            model = SourceCheckModel()
            prompts = []
            client = ScriptedLLMClient(lambda stage, system, user: (prompts.append((stage, user)),
                                                                     model(stage, system, user))[1])
            manifest = run(client, scope, test_profile(), out)
            self.assertEqual(manifest["status"], "COMPLETED", manifest.get("error"))
            revise_prompt = next(user for stage, user in prompts if stage == "revise")
            self.assertIn("the source says otherwise", revise_prompt)
            self.assertIn("[1.2]", revise_prompt)  # the reviser sees the source passage
            self.assertEqual([v["problem_claims"] for v in manifest["versions"]], [1, 0])

            # Smaller groups: one call per paragraph, each seeing only its own paragraph; pooled samples.
            prompts = []
            model = SourceCheckModel()
            client = ScriptedLLMClient(lambda stage, system, user: (prompts.append((stage, user)),
                                                                     model(stage, system, user))[1])
            manifest = run(client, scope, test_profile(), Path(tmp) / "chunked", source_check_chunk=1,
                           source_check_samples=2, stop_after="critic")
            checks_seen = [re.findall(r"^<(P\d{3})>$", user, re.M) for stage, user in prompts if stage == "source_check"]
            self.assertEqual(checks_seen, [["P001"], ["P001"], ["P002"], ["P002"]])
            self.assertTrue((Path(tmp) / "chunked" / "source_check_v1_c2_s2.json").is_file())
            self.assertEqual(manifest["versions"][0]["problem_claims"], 1)  # the first sample's finding on P001

    def test_incomplete_source_check_saves_the_draft_and_reports_why_it_needs_review(self):
        scope = load_scope(DEFAULT_MANIFEST, (1, 1))
        cases = (
            ("disabled", "--no-source-check"),
            ("too_long", "10 ký tự"),
            ("invalid_answer", "list every paragraph"),
            ("transport_error", "provider unavailable"),
        )
        for mode, expected_reason in cases:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                model = FakeModel()
                model.critic_calls = 1  # No critic findings to mask an incomplete source check.

                def respond(stage, system, user):
                    if stage == "source_check" and "<P001>" in user:
                        if mode == "invalid_answer":
                            return '{"paragraphs": []}'
                        if mode == "transport_error":
                            raise RuntimeError("provider unavailable")
                    return model(stage, system, user)

                out = Path(tmp) / "run"
                client = ScriptedLLMClient(respond)
                limit = 10 if mode == "too_long" else stages.SOURCE_CHECK_MAX_CHARS
                with mock.patch.object(stages, "SOURCE_CHECK_MAX_CHARS", limit):
                    manifest = run(client, scope, test_profile(), out, source_check=mode != "disabled",
                                   source_check_chunk=1)
                paths = [out / name for name in ("script_final.md", "script_final.txt",
                                                 "report.json", "report.md", "review.html")]
                self.assertEqual([p.name for p in paths if not p.is_file()], [])
                for path in paths[:2]:
                    self.assertIn(SECTION_1, path.read_text(encoding="utf-8"))
                self.assertEqual(manifest["status"], "NEEDS_REVIEW", manifest.get("error"))
                saved = json.loads((out / "run_manifest.json").read_text(encoding="utf-8"))
                report = json.loads((out / "report.json").read_text(encoding="utf-8"))
                self.assertEqual(saved["status"], report["status"])
                self.assertEqual(saved["review_reasons"], report["review_reasons"])
                self.assertEqual(report["gates"]["GATE_FACTUAL_GROUNDING"]["status"], "NEEDS_REVIEW")
                self.assertEqual(report["findings"], [])
                self.assertIn(expected_reason, report["review_reasons"][0])
                for path in paths[-2:]:
                    rendered = path.read_text(encoding="utf-8")
                    self.assertIn("Cần duyệt", rendered)
                    self.assertIn(expected_reason, rendered)
                if mode in ("disabled", "too_long"):
                    self.assertNotIn("source_check", [call["stage"] for call in client.calls])
                else:
                    self.assertEqual(manifest["source_check_failed"][0]["chunk"], 1)
                    self.assertTrue((out / "source_check_v1_c2.json").is_file())
                if mode == "transport_error":
                    recovered_client = ScriptedLLMClient(FakeModel())
                    recovered = run(recovered_client, scope, test_profile(), out, source_check_chunk=1, resume=True)
                    self.assertEqual(recovered["status"], "COMPLETED")
                    self.assertEqual([call["stage"] for call in recovered_client.calls], ["source_check"])
                    recovered_report = json.loads((out / "report.json").read_text(encoding="utf-8"))
                    self.assertEqual(recovered_report["review_reasons"], [])

    def test_later_versions_recheck_only_the_paragraphs_that_changed(self):
        """Patch rounds left 60-97% of paragraphs byte-identical in saved runs, yet every
        version sent all of them to the critic and the source check again."""
        scope = load_scope(DEFAULT_MANIFEST, (1, 1))

        class Model(FakeModel):
            """The first source check finds a problem in P002, which the revision leaves alone."""
            checks = 0

            def __call__(self, stage, system, user):
                if stage != "source_check":
                    return super().__call__(stage, system, user)
                self.checks += 1
                units = list(dict.fromkeys(re.findall(r"<(P\d{3})>", user)))
                findings = [{"script_quote": "chiếc ô", "kind": "NOT_IN_SOURCE", "passage_ids": ["1.2"],
                             "explanation": "không có trong nguồn"}] if self.checks == 1 else []
                return json.dumps({"paragraphs": [{"unit_id": u, "findings": findings if u == "P002" else []}
                                                  for u in units], "critic_reviews": critic_reviews(user, "NOT_IN_SOURCE")})

        for full_recheck, rechecked, problems in ((False, [2, 1], [2, 1]), (True, [2, 2], [2, 0])):
            with self.subTest(full_recheck=full_recheck), tempfile.TemporaryDirectory() as tmp:
                prompts = []
                model = Model()
                client = ScriptedLLMClient(lambda stage, system, user: (prompts.append((stage, user)),
                                                                         model(stage, system, user))[1])
                manifest = run(client, scope, test_profile(), Path(tmp) / "run", full_recheck=full_recheck)
                self.assertEqual(manifest["status"], "COMPLETED", manifest.get("error"))
                self.assertEqual([v["rechecked_units"] for v in manifest["versions"]], rechecked)
                self.assertEqual([v["problem_claims"] for v in manifest["versions"]], problems)
                second_critic = [user for stage, user in prompts if stage == "critic"][1]
                self.assertEqual("<P002>" in second_critic, full_recheck)
                # The carried critic verdicts still cover every paragraph.
                critic = json.loads((Path(tmp) / "run" / "critic_v2.json").read_text(encoding="utf-8"))
                self.assertEqual([u["unit_id"] for u in critic["units"]], ["P001", "P002"])
                report = json.loads((Path(tmp) / "run" / "report.json").read_text(encoding="utf-8"))
                self.assertEqual([(f["unit_id"], f["source"]) for f in report["findings"]],
                                 [] if full_recheck else [("P002", "source_check")])

        # Matching is by text, so paragraphs that move keep their verdicts under the new id.
        old = [{"unit_id": "P001", "sha256": "a", "text": "A"}, {"unit_id": "P002", "sha256": "b", "text": "B"},
               {"unit_id": "P003", "sha256": "c", "text": "C"}]
        new = [{"unit_id": "P001", "sha256": "z", "text": "Z"}, {"unit_id": "P002", "sha256": "a", "text": "A"},
               {"unit_id": "P003", "sha256": "c", "text": "C"}]
        carried = stages.unchanged_units(new, old)
        self.assertEqual(carried, {"P002": "P001", "P003": "P003"})
        previous = {"units": [{"unit_id": u, "claims": [claim("SUPPORTED_FACT")], "no_claim_reason": u}
                              for u in ("P001", "P002", "P003")]}
        fresh = {"units": [{"unit_id": "P001", "claims": [], "no_claim_reason": "fresh"}]}
        merged = stages.merge_critic(new, fresh, previous, carried)
        self.assertEqual([(u["unit_id"], u["no_claim_reason"]) for u in merged["units"]],
                         [("P001", "fresh"), ("P002", "P001"), ("P003", "P003")])
        findings = [{"unit_id": "P001", "claim": "A"}, {"unit_id": "P002", "claim": "B"}]
        self.assertEqual(stages.carry_findings(findings, carried), [{"unit_id": "P002", "claim": "A"}])

    def test_critic_findings_the_source_supports_become_brief_gaps(self):
        """Season S2 episode 2: the critic flagged four details that the brief had left out
        but the source does say. The source check adjudicates them; supported ones are not
        revised, do not count in the gates, and are listed as brief gaps."""
        scope = load_scope(DEFAULT_MANIFEST, (1, 1))
        model = FakeModel()
        model.flag_verdict = "IN_SOURCE"
        prompts = []
        client = ScriptedLLMClient(lambda stage, system, user: (prompts.append((stage, user)),
                                                                 model(stage, system, user))[1])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            manifest = run(client, scope, test_profile(), out)
            self.assertEqual(manifest["status"], "COMPLETED", manifest.get("error"))
            check_prompt = next(user for stage, user in prompts if stage == "source_check")
            self.assertIn("F1 (P001, not supported): x", check_prompt)
            self.assertNotIn("revise", [stage for stage, _ in prompts])
            self.assertEqual([(v["problem_claims"], v["critic_overturned"]) for v in manifest["versions"]], [(0, 1)])
            report = json.loads((out / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["findings"], [])
            self.assertEqual(report["gates"]["GATE_FACTUAL_GROUNDING"]["status"], "PASS")
            self.assertEqual([(g["unit_id"], g["claim"], g["passage_ids"]) for g in report["brief_gaps"]],
                             [("P001", "x", ["1.2"])])
            self.assertIn("SUPPORTED_FACT", report["claim_counts"])  # the critic's other claims stay
            self.assertIn("## Brief bỏ sót", (out / "report.md").read_text(encoding="utf-8"))
            self.assertIn("<h2>Brief bỏ sót</h2>", (out / "review.html").read_text(encoding="utf-8"))

    def test_source_check_answers_are_validated(self):
        units = [{"unit_id": "P001", "sha256": "x", "text": "Cô bưng bát cháo nghi ngút khói."},
                 {"unit_id": "P002", "sha256": "x", "text": "Cậu khen cháo ngon."}]
        ids = {"3.81", "3.96"}

        def answer(*paragraphs):
            return {"paragraphs": [{"unit_id": u, "findings": f} for u, f in paragraphs]}

        finding = {"script_quote": "nghi ngút  khói", "kind": "CONTRADICTS_SOURCE", "passage_ids": ["3.81"],
                   "explanation": "no steam"}
        cases = [
            ("valid (whitespace-insensitive quote)", answer(("P001", [finding]), ("P002", [])), []),
            ("tag brackets around ids are tolerated", answer(("<P001>", [finding]), ("<P002>", [])), []),
            ("paragraph missing", answer(("P001", [])), ["list every paragraph exactly once"]),
            ("paragraph twice", answer(("P001", []), ("P001", []), ("P002", [])), ["exactly once"]),
            ("quote not in paragraph", answer(("P001", [dict(finding, script_quote="bốc hơi")]), ("P002", [])),
             ["not copied exactly"]),
            ("passage outside the episode", answer(("P001", [dict(finding, passage_ids=["9.1"])]), ("P002", [])),
             ["not in this episode's source"]),
        ]
        for label, check, expected in cases:
            with self.subTest(label):
                errors = stages.source_check_errors(check, units, ids)
                self.assertEqual(len(errors), len(expected), errors)
                for message, error in zip(expected, errors):
                    self.assertIn(message, error)

        # Verdicts on the critic's flags: one per flag, and IN_SOURCE names its passages.
        critic = {"units": [{"unit_id": "P001", "claims": [claim("SUPPORTED_FACT"),
                                                           claim("UNSUPPORTED_STORY_CLAIM", "LOW", "UNSUPPORTED_INVENTION"),
                                                           claim("UNDETERMINED")]},
                            {"unit_id": "P002", "claims": [claim("STRENGTHENED_STORY_CLAIM", "LOW", "EPISTEMIC_ERROR")]}]}
        flags = stages.critic_flags(critic)
        self.assertEqual([(f["id"], f["unit_id"], f["claim_type"]) for f in flags],
                         [("F1", "P001", "UNSUPPORTED_STORY_CLAIM"), ("F2", "P002", "STRENGTHENED_STORY_CLAIM")])
        self.assertEqual(stages.flagged_text(flags).splitlines(),
                         ["F1 (P001, not supported): x", "F2 (P002, stated more strongly than the summary): x"])
        self.assertIn("empty critic_reviews", stages.flagged_text([]))

        def review(flag, verdict="IN_SOURCE", passage_ids=("3.81",)):
            return {"id": flag, "verdict": verdict, "passage_ids": list(passage_ids), "explanation": "e"}

        base = answer(("P001", []), ("P002", []))
        cases = [
            ("every flag answered", [review("F1"), review("F2", "NOT_IN_SOURCE", ())], []),
            ("a flag left unanswered", [review("F1")], ["answer each flagged statement exactly once"]),
            ("IN_SOURCE without passages", [review("F1", passage_ids=()), review("F2")], ["needs the passage ids"]),
            ("passage outside the episode", [review("F1", passage_ids=("9.1",)), review("F2")],
             ["not in this episode's source"]),
        ]
        for label, reviews, expected in cases:
            with self.subTest(label):
                errors = stages.source_check_errors(dict(base, critic_reviews=reviews), units, ids, flags)
                self.assertEqual(len(errors), len(expected), errors)
                for message, error in zip(expected, errors):
                    self.assertIn(message, error)

        # Overturned only when every sample that answered says IN_SOURCE.
        agree = dict(base, critic_reviews=[review("F1"), review("F2")])
        dissent = dict(base, critic_reviews=[review("F1", passage_ids=("3.96",)), review("F2", "NOT_IN_SOURCE", ())])
        overturned = stages.overturned_flags([agree, dissent, None, base], flags)
        self.assertEqual([(f["id"], f["passage_ids"]) for f in overturned], [("F1", ["3.81", "3.96"])])
        kept = stages.without_claims(critic, overturned)
        self.assertEqual([[c["claim_type"] for c in u["claims"]] for u in kept["units"]],
                         [["SUPPORTED_FACT", "UNDETERMINED"], ["STRENGTHENED_STORY_CLAIM"]])
        converted = stages.source_check_findings(answer(("P001", [finding]), ("P002", [])),
                                                 {"3.81": "湯気はたっていない"})
        self.assertEqual([(f["claim_type"], f["failure_category"], f["severity"], f["source"]) for f in converted],
                         [("CONTRADICTED_STORY_CLAIM", "FACTUAL_ERROR", "MEDIUM", "source_check")])
        self.assertIn("湯気はたっていない", converted[0]["suggested_fix"])

        # Pooled calls: the same defect quoted a little differently counts once.
        other = dict(finding, script_quote="nghi ngút", kind="STRENGTHENED")
        second = stages.source_check_findings(answer(("P001", [other]), ("P002", [dict(finding, script_quote="ngon")])), {})
        merged = stages.merge_source_findings([converted, second])
        self.assertEqual([(f["unit_id"], f["claim"]) for f in merged],
                         [("P001", "nghi ngút  khói"), ("P002", "ngon")])

    def test_later_revision_rounds_patch_only_the_sentences_at_fault(self):
        """Live run 13: a second full rewrite put new errors into correct text."""
        scope = load_scope(DEFAULT_MANIFEST, (1, 1))

        class PersistentProblemModel(FakeModel):
            """The critic flags the same sentence until it is patched."""
            def __init__(self):
                super().__init__()
                self.patched = False

            def __call__(self, stage, system, user):
                if stage == "critic":
                    return json.dumps(critic_json(user, not self.patched), ensure_ascii=False)
                if stage == "patch":
                    self.patched = True
                    first = re.search(r"<P001>\n(.+?)\n</P001>", user, re.S).group(1)
                    sentence = re.match(r"[^.!?]+[.!?]", first).group(0)
                    return json.dumps({"edits": [{"unit_id": "P001", "old": sentence, "new": "Câu đã sửa."}]})
                return super().__call__(stage, system, user)

        with tempfile.TemporaryDirectory() as tmp:
            client = ScriptedLLMClient(PersistentProblemModel())
            manifest = run(client, scope, test_profile(), Path(tmp) / "run", revision_rounds=2, source_check=False)
            self.assertEqual(manifest["status"], "NEEDS_REVIEW", manifest.get("error"))
            self.assertEqual([c["stage"] for c in client.calls if c["stage"] in ("revise", "patch")],
                             ["revise", "patch"])
            self.assertEqual([v["problem_claims"] for v in manifest["versions"]], [1, 1, 0])
            v2 = json.loads((Path(tmp) / "run" / "script_v2.json").read_text(encoding="utf-8"))
            v3 = json.loads((Path(tmp) / "run" / "script_v3.json").read_text(encoding="utf-8"))
            before, after = checks.split_units(checks.script_text(v2)), checks.split_units(checks.script_text(v3))
            self.assertTrue(after[0]["text"].startswith("Câu đã sửa."))
            self.assertEqual([u["text"] for u in before[1:]], [u["text"] for u in after[1:]])  # untouched

    def test_story_brief_is_written_for_review_and_owner_edits_reach_the_plan(self):
        """M7: the episode Story Brief is the reviewable boundary before planning."""
        scope = load_scope(DEFAULT_MANIFEST, (1, 1))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            manifest = run(ScriptedLLMClient(FakeModel()), scope, test_profile(), out, stop_after="brief")
            self.assertEqual(manifest["status"], "STOPPED_AFTER_BRIEF")
            for name in ("story_brief.json", "story_brief.md", "story_brief.html", "brief_review_form.md"):
                self.assertTrue((out / name).is_file(), name)
            self.assertEqual(json.loads((out / "story_brief.json").read_text(encoding="utf-8"))["format"],
                             "EPISODE_STORY_BRIEF/v1")
            form = (out / "brief_review_form.md").read_text(encoding="utf-8")
            filled = form.replace("- [ ] sai [ ] bỏ `c1.E2`", "- [ ] sai [x] bỏ `c1.E2`").replace(
                "- [ ] sai [ ] bỏ `c1.R1` (quan hệ Amane – Mahiru) Hàng xóm",
                "- [x] sai [ ] bỏ `c1.R1` (quan hệ Amane – Mahiru) Hàng xóm → Hàng xóm cạnh nhà")
            (out / "brief_review_form.md").write_text(filled, encoding="utf-8")

            model = FakeModel()
            manifest = run(ScriptedLLMClient(model), scope, test_profile(), out, resume=True, stop_after="plan")
            self.assertEqual(manifest["status"], "STOPPED_AFTER_PLAN", manifest.get("error"))
            plan_prompt = model.plan_prompts[0]
            self.assertIn("Hàng xóm cạnh nhà", plan_prompt)
            self.assertNotIn("Amane đưa ô cho Mahiru", plan_prompt)
            self.assertEqual([(c["ref"], c["action"]) for c in manifest["brief_review"]["changes"]],
                             [("c1.E2", "drop"), ("c1.R1", "correct")])
            self.assertFalse(manifest["brief_review"]["after_plan"])
            self.assertEqual((out / "brief_review_form_reviewed_1.md").read_text(encoding="utf-8"), filled)
            fresh = (out / "brief_review_form.md").read_text(encoding="utf-8")
            self.assertEqual(episode_brief.parse_brief_review(fresh), [])  # a blank form for the edited brief
            self.assertIn("Hàng xóm cạnh nhà", (out / "story_brief.md").read_text(encoding="utf-8"))
            # The stored briefs are not changed; a later resume replays the recorded round.
            self.assertIn("Amane đưa ô cho Mahiru", (out / "briefs" / "chapter_001.json").read_text(encoding="utf-8"))
            again = run(ScriptedLLMClient(FakeModel()), scope, test_profile(), out, resume=True, stop_after="plan")
            self.assertEqual(len(again["brief_review"]["changes"]), 2)
            self.assertFalse((out / "brief_review_form_reviewed_2.md").exists())

    def test_owner_review_errors_are_fixed_in_a_patch_round(self):
        """The owner's quoted errors in review_form.md become one patch round (--apply-review)."""
        scope = load_scope(DEFAULT_MANIFEST, (1, 1))

        class OwnerModel(FakeModel):
            """mode "fixed": the patch replaces the quote; "kept": it edits elsewhere; "flagged":
            the recheck finds the rewrite wrong too."""
            def __init__(self, mode="fixed"):
                super().__init__()
                self.mode = mode

            def __call__(self, stage, system, user):
                if stage == "patch":
                    self.patch_prompt = user
                    old, new = (("Bạn nghĩ sao", "Các bạn nghĩ sao") if self.mode == "kept"
                                else ("chẳng nói thêm gì nhiều", "không nói một lời"))
                    return json.dumps({"edits": [{"unit_id": "P002", "old": old, "new": new}]}, ensure_ascii=False)
                if stage == "source_check" and self.mode == "flagged" and "không nói một lời" in user:
                    return json.dumps({"paragraphs": [{"unit_id": "P002", "findings": [
                        {"script_quote": "không nói một lời", "kind": "CONTRADICTS_SOURCE", "passage_ids": ["1.2"],
                         "explanation": "vẫn sai"}]}], "critic_reviews": []})
                return super().__call__(stage, system, user)

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            model = OwnerModel()
            self.assertEqual(run(ScriptedLLMClient(model), scope, test_profile(), out)["status"], "COMPLETED")
            form = (out / "review_form.md").read_text(encoding="utf-8")
            filled = form.replace("- \n", (
                '- "chẳng nói thêm gì  nhiều" → nguồn: cậu không nói gì\n'
                '- "câu không có trong kịch bản" → x\n- nhịp hơi chậm\n'), 1).replace("☐ Sửa nhẹ", "☑ Sửa nhẹ")
            (out / "review_form.md").write_text(filled, encoding="utf-8")
            self.assertEqual(len(pending_owner_errors(out)), 2)

            client = ScriptedLLMClient(model)
            manifest = run(client, scope, test_profile(), out, resume=True, owner_review="review_form.md")
            self.assertEqual(manifest["status"], "COMPLETED", manifest.get("error"))
            self.assertEqual([c["stage"] for c in client.calls], ["patch", "critic", "source_check"])
            self.assertIn("nguồn: cậu không nói gì", model.patch_prompt)
            self.assertTrue((out / "script_v3.json").is_file())
            report = json.loads((out / "report.json").read_text(encoding="utf-8"))
            self.assertEqual([(o["status"], o["unit_id"]) for o in report["owner_review"]],
                             [("applied", "P002"), ("not_found", None)])
            self.assertEqual(manifest["owner_review"], {"rounds": 1, "applied": 1, "applied_but_flagged": 0,
                                                        "still_present": 0, "not_found": 1})
            self.assertIn("## Góp ý của người duyệt", (out / "report.md").read_text(encoding="utf-8"))
            # The filled form is kept; a fresh one is written for the corrected script.
            self.assertEqual((out / "review_form_reviewed_1.md").read_text(encoding="utf-8"), filled)
            self.assertNotIn("☑", (out / "review_form.md").read_text(encoding="utf-8"))
            self.assertEqual(pending_owner_errors(out), [])

            # A later resume replays the round from the saved files, with or without the flag.
            for flag in (None, "review_form.md"):
                again = ScriptedLLMClient(OwnerModel())
                replay = run(again, scope, test_profile(), out, resume=True, owner_review=flag)
                self.assertEqual((again.calls, replay["versions"][-1]["version"]), ([], 3))
            self.assertFalse((out / "review_form_reviewed_2.md").exists())

        for mode, status in (("kept", "still_present"), ("flagged", "applied_but_flagged")):
            with self.subTest(mode), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "run"
                run(ScriptedLLMClient(OwnerModel(mode)), scope, test_profile(), out)
                (out / "review_form.md").write_text('Lỗi cụ thể:\n- "chẳng nói thêm gì nhiều" → sai\n', encoding="utf-8")
                run(ScriptedLLMClient(OwnerModel(mode)), scope, test_profile(), out, resume=True,
                    owner_review="review_form.md")
                report = json.loads((out / "report.json").read_text(encoding="utf-8"))
                self.assertEqual([o["status"] for o in report["owner_review"]], [status])

    def test_plan_review_files_and_owner_beat_edits_before_the_script(self):
        """M8: plan checks and review page on --stop-after plan; a filled plan_review_form.md is
        applied on --resume before the script is written, and replayed afterwards."""
        scope = load_scope(DEFAULT_MANIFEST, (1, 1))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            manifest = run(ScriptedLLMClient(FakeModel()), scope, test_profile(), out, stop_after="plan")
            self.assertEqual(manifest["status"], "STOPPED_AFTER_PLAN")
            for name in ("plan.md", "plan_review.html", "plan_review_form.md"):
                self.assertTrue((out / name).is_file(), name)
            self.assertEqual(manifest["plan_checks"]["coverage"]["core_covered"], 1)
            form = (out / "plan_review_form.md").read_text(encoding="utf-8")
            filled = (form.replace("`B1` bỏ: [ ]", "`B1` bỏ: [x]")
                      .replace("vị trí: 2 | số từ: 30 | ghi chú: ", "vị trí: 2 | số từ: 60 | ghi chú: kể chậm lại"))
            (out / "plan_review_form.md").write_text(filled, encoding="utf-8")
            prompts = []
            model = FakeModel()
            client = ScriptedLLMClient(lambda stage, system, user: (prompts.append((stage, user)),
                                                                     model(stage, system, user))[1])
            manifest = run(client, scope, test_profile(), out, resume=True)
            self.assertEqual(manifest["status"], "COMPLETED", manifest.get("error"))
            script_prompt = next(user for stage, user in prompts if stage == "script")
            self.assertIn("Ghi chú người duyệt: kể chậm lại", script_prompt)
            self.assertIn("\"target_words\": 60", script_prompt)
            review = manifest["plan_review"]
            self.assertEqual(([c["change"] for c in review["changes"]], [r["beat"] for r in review["rejected"]]),
                             (["words", "note"], ["B1"]))  # B1 holds the CORE event
            self.assertEqual((out / "plan_review_form_reviewed_1.md").read_text(encoding="utf-8"), filled)
            self.assertNotIn("kể chậm lại", json.loads((out / "plan.json").read_text(encoding="utf-8"))["beats"][1]["purpose"])
            again = ScriptedLLMClient(FakeModel())
            replay = run(again, scope, test_profile(), out, resume=True)
            self.assertEqual((again.calls, replay["plan_review"]["rounds"]), ([], 1))

    def test_patch_edits_are_validated_and_applied_in_place(self):
        script = {"title_idea": "t", "sections": [
            {"beat_id": "B1", "text": "Cháo nghi ngút khói. Cậu ăn.\n\nCô cười."},
            {"beat_id": "B2", "text": "Cô về nhà. Cô về nhà."}]}
        units = checks.split_units(checks.script_text(script))
        cases = [
            ("valid", {"unit_id": "P001", "old": "Cháo nghi ngút khói.", "new": "Cháo đã nguội bớt."}, []),
            ("unknown paragraph", {"unit_id": "P009", "old": "x", "new": "y"}, ["no such paragraph"]),
            ("span not in paragraph", {"unit_id": "P002", "old": "Cậu ăn.", "new": "y"}, ["exactly once"]),
            ("span twice in paragraph", {"unit_id": "P003", "old": "Cô về nhà.", "new": "y"}, ["exactly once"]),
            ("no change", {"unit_id": "P002", "old": "Cô cười.", "new": "Cô cười."}, ["same as"]),
            ("foreign script", {"unit_id": "P002", "old": "Cô cười.", "new": "Cô 笑."}, ["another writing system"]),
        ]
        for label, edit, expected in cases:
            with self.subTest(label):
                errors = stages.patch_errors({"edits": [edit]}, units, "vi")
                self.assertEqual(len(errors), len(expected), errors)
                for message, error in zip(expected, errors):
                    self.assertIn(message, error)
        self.assertEqual(stages.patch_errors({"edits": [{"unit_id": "<P002>", "old": "Cô cười.", "new": "Cô cười nhẹ."}]},
                                             units, "vi"), [])  # tag brackets tolerated
        twice = {"unit_id": "P002", "old": "Cô cười.", "new": "Cô mỉm cười."}
        self.assertIn("edited twice", stages.patch_errors({"edits": [twice, twice]}, units, "vi")[-1])

        patched = stages.apply_patch(script, units, {"edits": [
            {"unit_id": "P001", "old": "Cháo nghi ngút khói.", "new": "Cháo đã nguội bớt."},
            {"unit_id": "P002", "old": "Cô cười.", "new": ""}]})  # empty "new" deletes the sentence
        self.assertEqual(patched["sections"][0]["text"], "Cháo đã nguội bớt. Cậu ăn.")
        self.assertEqual(patched["sections"][1], script["sections"][1])
        whole_beat = stages.apply_patch(script, units, {"edits": [{"unit_id": "P003", "old": "Cô về nhà. Cô về nhà.",
                                                                   "new": ""}]})
        self.assertEqual(whole_beat["sections"][1], script["sections"][1])  # a beat is never deleted
        self.assertEqual(script["sections"][0]["text"], "Cháo nghi ngút khói. Cậu ăn.\n\nCô cười.")  # not mutated

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
            # Brief retrieval adds earlier non-CORE events the episode recalls, with evidence.
            core = {e["ref"] for c in recap["chapters"] for e in c["core_events"]}
            self.assertTrue(manifest["callbacks"])
            self.assertEqual([c["ref"] for c in recap["callbacks"]], manifest["callbacks"])
            self.assertFalse(core & set(manifest["callbacks"]))
            self.assertTrue(all(c["evidence"] and int(c["ref"][1]) < 3 for c in recap["callbacks"]))
            plan_prompt = model.plan_prompts[0]
            self.assertIn('"ref": "c1.E1"', plan_prompt)      # callback material from memory
            self.assertIn(f'"ref": "{manifest["callbacks"][0]}"', plan_prompt)
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

            # Callbacks can be turned off, and a corpus that cannot be built never fails the episode.
            off = run(ScriptedLLMClient(FakeModel()), episode, test_profile(), Path(tmp) / "off",
                      background=background, memory=memory, source_check=False, callbacks=False)
            self.assertNotIn("callbacks", off)
            self.assertNotIn("callbacks", json.loads((Path(tmp) / "off" / "memory_recap.json").read_text(encoding="utf-8")))
            with mock.patch.object(run_pipeline, "build_brief_corpus", side_effect=ValueError("no brief for chapters [1]")):
                broken = run(ScriptedLLMClient(FakeModel()), episode, test_profile(), Path(tmp) / "broken",
                             background=background, memory=memory, source_check=False)
            self.assertEqual((broken["status"], broken["callbacks_skipped"]), ("NEEDS_REVIEW", "no brief for chapters [1]"))

            # The story's name glossary is kept with the memory; the owner's spelling is enforced.
            glossary_file = Path(tmp) / "memory" / full.story_id / "glossary.yaml"
            self.assertEqual(second["glossary"]["characters"], 2)
            data = yaml.safe_load(glossary_file.read_text(encoding="utf-8"))
            data["characters"][0].update(display="Chu", also_allowed=[], confirmed=True)
            glossary_file.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
            systems = []
            declaring = dict(SCRIPT, pronouns={"Mahiru": "cô", "Amane": "ông", "Ghost": "nó"})

            def renamed_model(stage, system, user):
                systems.append((stage, system))
                return json.dumps(declaring, ensure_ascii=False) if stage == "script" else FakeModel()(stage, system, user)
            renamed = ScriptedLLMClient(renamed_model)
            third = run(renamed, episode, test_profile(), Path(tmp) / "ep3", background=background,
                        memory=memory, source_check=False)
            self.assertIn("藤宮周 → Chu", next(s for stage, s in systems if stage == "script"))
            report = json.loads((Path(tmp) / "ep3" / "report.json").read_text(encoding="utf-8"))
            self.assertIn(("glossary", "Amane"), [(f.get("source"), f["claim"]) for f in report["findings"]])
            self.assertEqual(third["glossary"]["confirmed"], False)  # Mahiru is still a default
            # The writer's declared pronouns become the rule for later episodes: "ông" is not a
            # Vietnamese third-person pronoun in the lexicon, and nobody is called Ghost.
            self.assertEqual(third["glossary"]["pronouns_adopted"], {"Mahiru": "cô"})
            self.assertEqual(yaml.safe_load(glossary_file.read_text(encoding="utf-8"))["characters"][1]["pronoun"], "cô")

    def test_memory_brief_failing_current_checks_is_regenerated(self):
        scope = load_scope(DEFAULT_MANIFEST, (1, 1))
        chapter = scope.chapters[0]
        with tempfile.TemporaryDirectory() as tmp:
            memory = StoryMemory(Path(tmp) / "memory", scope.story_id)
            stale = brief_json(1)
            stale["events"] = stale["events"][:2]  # written before the granularity rule existed
            memory.put_brief(1, chapter.version, stages.brief_fingerprint(test_profile()), stale, "old-model")
            client = ScriptedLLMClient(FakeModel())
            manifest = run(client, scope, test_profile(), Path(tmp) / "run", memory=memory)
            self.assertEqual(manifest["status"], "COMPLETED", manifest.get("error"))
            self.assertEqual(manifest["brief_sources"], {"1": "model (memory stale)"})
            self.assertIn("needs at least 5 events", manifest["stale_memory"]["1"][0])
            self.assertEqual([c["stage"] for c in client.calls][0], "brief")
            again = ScriptedLLMClient(FakeModel())  # the regenerated brief is valid and reused
            reused = run(again, scope, test_profile(), Path(tmp) / "run2", memory=memory)
            self.assertEqual(reused["brief_sources"], {"1": "memory"})

    def test_chinese_names_use_sino_vietnamese_readings_without_touching_other_languages(self):
        """DEC-020: the profile's name reading reaches Chinese briefs only."""
        profile = load_profile()
        for language in ("ja", "ko"):
            with self.subTest(language):
                self.assertEqual(stages.brief_fingerprint(profile, language), stages.brief_fingerprint(profile))
                self.assertNotIn("Sino-Vietnamese", stages.brief_system_prompt(profile, language, "1.12", {}))
        self.assertNotEqual(stages.brief_fingerprint(profile, "zh"), stages.brief_fingerprint(profile))
        self.assertIn("林婉儿 → Lâm Uyển Nhi", stages.brief_system_prompt(profile, "zh", "1.12", {}))
        self.assertIn("Hán-Việt", profile.name_policy)

    def test_cli_episode_mode(self):
        clients = []

        def client(*args, **kwargs):
            clients.append(ScriptedLLMClient(FakeModel()))
            return clients[-1]

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("tools.story_pipeline.llm.GeminiLLMClient", client), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            code = run_pipeline.main(["--chapters", "2", "--recap", "--memory", str(Path(tmp) / "mem"),
                                      "--out", str(Path(tmp) / "run"), "--min-words", "20", "--max-words", "200",
                                      "--source-check-chunk", "1"])
            self.assertEqual(code, 0, out.getvalue())
            manifest_path = Path(tmp) / "run" / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual((manifest["scope"]["chapters"], manifest["background_chapters"]), ([2], [1]))
            self.assertTrue((Path(tmp) / "run" / "memory_recap.json").is_file())
            self.assertTrue(any((Path(tmp) / "mem").rglob("chapter_002.json")))
            self.assertEqual(manifest["invocation"]["source_check_chunk"], 1)
            self.assertFalse(run_pipeline.run_options(run_pipeline.build_parser().parse_args(["--no-callbacks"]))["callbacks"])

            # `--resume <dir>` alone takes the run's own options, so every saved stage is reused;
            # a run made before invocations were recorded is read from its scope and settings.
            for label in ("recorded", "legacy"):
                with self.subTest(label):
                    if label == "legacy":
                        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                        del manifest["invocation"]
                        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                    code = run_pipeline.main(["--resume", str(Path(tmp) / "run"), "--memory", str(Path(tmp) / "mem")])
                    self.assertEqual((code, clients[-1].calls), (0, []), out.getvalue())
                    self.assertIn("resume: using the run's own chapters, recap", out.getvalue())
            # An option given again wins over the recorded one.
            args = run_pipeline.build_parser().parse_args(["--resume", "x", "--chapters", "3"])
            restored = run_pipeline.restore_invocation(args, {"resume", "chapters"}, Path(tmp) / "run")
            self.assertEqual(args.chapters, "3")
            self.assertNotIn("chapters", restored)
            self.assertEqual(run_pipeline.restore_invocation(args, set(), Path(tmp) / "missing"), [])

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

        # Retrieved callbacks (M6 Phase 2) are citable earlier events that keep their own label.
        recap["callbacks"] = [{"ref": "c1.E4", "summary": "Nghe đồn Mahiru chưa từng thất bại",
                               "epistemic": "REPORTED", "evidence": ["1.3"]}]
        plan["beats"][1]["event_refs"] = ["c2.E1", "c1.E4"]
        self.assertEqual(stages.plan_semantic_errors(plan, [brief_json(2)], profile, recap), [])
        self.assertEqual(stages.labelled_statements([], recap)["c1.E4"],
                         [("Nghe đồn Mahiru chưa từng thất bại", "REPORTED")])
        self.assertEqual(stages.labelled_statements([], recap)["c1.E1"], [("x", "EXPLICIT")])
        self.assertEqual(stages.brief_item_texts([], recap)["c1.E4"], "Nghe đồn Mahiru chưa từng thất bại")

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
            candidates = ()

        class Reason:
            name = "MAX_TOKENS"

        class Candidate:
            finish_reason = Reason()

        class TruncatedResponse(FakeResponse):
            text = '{"n": '
            candidates = (Candidate(),)

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

    def test_model_fallback_chain(self):
        class ProviderError(Exception):
            def __init__(self, code):
                super().__init__(f"HTTP {code}")
                self.code = code

        class FakeResponse:
            text = '{"n": 1}'
            usage_metadata = None
            model_version = "fake"
            candidates = ()

        class Reason:
            name = "MAX_TOKENS"

        class Candidate:
            finish_reason = Reason()

        class TruncatedResponse(FakeResponse):
            text = '{"n": '
            candidates = (Candidate(),)

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
                if failure == "truncated":
                    return TruncatedResponse()
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
            # Season S2: a model that runs out of output tokens (thinking) cuts its JSON off.
            ("answer cut off by the token limit falls back", {"busy-model": "truncated"}, "ok",
             ["busy-model", "spare-model"]),
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
                    # Every earlier call failed in transport, except a cut-off answer, which arrived.
                    cut_off = sum(1 for f in record["fallback_from"] if f["code"] == "MAX_TOKENS")
                    self.assertEqual(len(record["attempt_failures"]), len(sdk.calls) - 1 - cut_off)
                else:
                    with self.assertRaises(RuntimeError) as raised:
                        client.complete(system="s", user="u", request_id="t:1")
                    self.assertIn("attempt errors:", str(raised.exception))
                    self.assertIn("ProviderError", str(raised.exception))
                if expected_calls is not None:
                    self.assertEqual(sdk.calls, expected_calls)


if __name__ == "__main__":
    unittest.main()
