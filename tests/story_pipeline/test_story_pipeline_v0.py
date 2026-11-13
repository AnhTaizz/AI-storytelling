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
from tools.story_pipeline.source import StoryScope, load_scope, parse_range  # noqa: E402

SECTION_1 = ("Một buổi chiều mưa, Amane đi ngang qua công viên và thấy Mahiru ngồi một mình "
             "trên xích đu, người ướt sũng.")
SECTION_2 = ("Cậu đưa chiếc ô của mình cho cô rồi đi thẳng về nhà, chẳng nói thêm gì nhiều. "
             "Bạn nghĩ sao về cách làm quen này?")


_SAMPLE = load_scope(DEFAULT_MANIFEST, (1, 5))
PASSAGE_TEXT = {p.passage_id: p.text for c in _SAMPLE.chapters for p in c.passages}


PASSAGE_COUNT = {c.order: len(c.passages) for c in _SAMPLE.chapters}


def brief_json(order, evidence=None, quote=None):
    """A valid brief: two named events plus MINOR filler up to the chapter's event minimum."""
    brief = _base_brief(order, evidence, quote)
    template = brief["events"][-1]
    for n in range(len(brief["events"]) + 1, stages.min_events(PASSAGE_COUNT.get(order, 0)) + 1):
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
             "facts": [{"text": "Học sinh năm nhất", "evidence": evidence, "quote": quote}]},
            {"id": "CH2", "name": "椎名真昼", "romanized_name": "Mahiru", "aliases": ["Thiên thần"],
             "facts": []},
        ],
        "relationships": [{"between": ["CH1", "CH2"], "state": "Hàng xóm", "evidence": evidence,
                           "quote": quote}],
        "events": [
            {"id": "E1", "summary": "Amane thấy Mahiru trên xích đu", "participants": ["CH1", "CH2"],
             "location": "công viên", "importance": "CORE",
             "motivation": {"text": None, "status": "UNKNOWN"}, "consequence": None,
             "evidence": evidence, "quote": quote},
            {"id": "E2", "summary": "Amane đưa ô cho Mahiru", "participants": ["CH1", "CH2"],
             "location": "công viên", "importance": "SUPPORTING",
             "motivation": {"text": None, "status": "UNKNOWN"}, "consequence": None,
             "evidence": evidence, "quote": quote},
        ],
        "unknowns": ["Lý do Mahiru ngồi dưới mưa"],
        "forbidden_inferences": ["Mahiru thích Amane"],
        "ending_state": "Amane về nhà.",
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
}

SCRIPT = {"title_idea": "Chiếc ô", "sections": [{"beat_id": "B1", "text": SECTION_1},
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
        if stage in ("script", "revise"):
            return "```json\n" + json.dumps(SCRIPT, ensure_ascii=False) + "\n```"
        if stage == "critic":
            self.critic_calls += 1
            return json.dumps(critic_json(user, self.critic_calls == 1), ensure_ascii=False)
        raise AssertionError(stage)


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


class ChecksTests(unittest.TestCase):
    def test_word_count_and_language(self):
        report = checks.check_script(SCRIPT, 20, 200, "vi")
        self.assertTrue(report["length_ok"] and report["language_ok"] and report["clean_ok"])
        self.assertEqual(report["word_count"], checks.count_words(checks.script_text(SCRIPT)))

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
        self.assertEqual([stages.min_events(n) for n in (0, 15, 16, 61)], [2, 2, 2, 5])
        coarse = brief_json(1)
        coarse["events"] = coarse["events"][:2]  # the first live run: 61 passages in 2 events
        errors = stages.brief_semantic_errors(coarse, self.chapter)
        self.assertTrue(any("needs at least 5 events" in e and "you listed 2" in e for e in errors), errors)

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
                markers = [m for f in findings for m in stages.STRENGTH_MARKERS if m in f["explanation"]]
                self.assertEqual(sorted(markers), sorted(expected))
                for finding in findings:
                    self.assertEqual((finding["severity"], finding["source"]), ("MEDIUM", "strength_audit"))
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
            self.assertIn('"ref": "c1.E1"', plan_prompt)      # callback material from memory
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
                else:
                    with self.assertRaises(RuntimeError):
                        client.complete(system="s", user="u", request_id="t:1")
                if expected_calls is not None:
                    self.assertEqual(sdk.calls, expected_calls)


if __name__ == "__main__":
    unittest.main()
