"""Offline tests for the story pipeline prototype v0.

No model, API or network is used: a scripted client returns canned JSON. One test reads
the tracked sample chapter 1 through the frozen M3 adapter.
"""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

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
from tools.story_pipeline.run_pipeline import DEFAULT_MANIFEST, gate_report, run  # noqa: E402
from tools.story_pipeline.source import load_scope, parse_range  # noqa: E402

SECTION_1 = ("Một buổi chiều mưa, Amane đi ngang qua công viên và thấy Mahiru ngồi một mình "
             "trên xích đu, người ướt sũng.")
SECTION_2 = ("Cậu đưa chiếc ô của mình cho cô rồi đi thẳng về nhà, chẳng nói thêm gì nhiều. "
             "Bạn nghĩ sao về cách làm quen này?")


def brief_json(order, evidence=None):
    evidence = evidence or [f"{order}.2"]
    return {
        "chapter_order": order,
        "chapter_summary": "Amane gặp Mahiru trong công viên lúc trời mưa.",
        "characters": [
            {"id": "CH1", "name": "藤宮周", "romanized_name": "Amane", "aliases": [],
             "facts": [{"text": "Học sinh năm nhất", "evidence": evidence}]},
            {"id": "CH2", "name": "椎名真昼", "romanized_name": "Mahiru", "aliases": ["Thiên thần"],
             "facts": []},
        ],
        "relationships": [{"between": ["CH1", "CH2"], "state": "Hàng xóm", "evidence": evidence}],
        "events": [
            {"id": "E1", "summary": "Amane thấy Mahiru trên xích đu", "participants": ["CH1", "CH2"],
             "location": "công viên", "importance": "CORE",
             "motivation": {"text": None, "status": "UNKNOWN"}, "consequence": None,
             "evidence": evidence},
            {"id": "E2", "summary": "Amane đưa ô cho Mahiru", "participants": ["CH1", "CH2"],
             "location": "công viên", "importance": "SUPPORTING",
             "motivation": {"text": None, "status": "UNKNOWN"}, "consequence": None,
             "evidence": evidence},
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

    def __call__(self, stage, system, user):
        if stage == "brief":
            order = int(re.search(r"Chapter order: (\d+)", user).group(1))
            return json.dumps(brief_json(order), ensure_ascii=False)
        if stage == "plan":
            plan = json.loads(json.dumps(PLAN))
            for ref in sorted(set(re.findall(r'"ref": "(c[2-9]\.E\d+)"', user))):
                plan["beats"][1]["event_refs"].append(ref)
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

    def test_plan_requires_core_coverage_and_length(self):
        profile = test_profile()
        plan = json.loads(json.dumps(PLAN))
        plan["beats"][0]["event_refs"] = ["c1.E2"]
        plan["beats"][1]["target_words"] = 500
        errors = stages.plan_semantic_errors(plan, [brief_json(1)], profile)
        self.assertTrue(any("CORE events not covered" in e for e in errors))
        self.assertTrue(any("target_words sum" in e for e in errors))
        self.assertEqual(stages.plan_semantic_errors(PLAN, [brief_json(1)], profile), [])

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

            # Resume reuses every stage output: no new model calls.
            resumed_client = ScriptedLLMClient(FakeModel())
            resumed = run(resumed_client, scope, test_profile(), out, resume=True)
            self.assertEqual(resumed["status"], "COMPLETED")
            self.assertEqual(resumed_client.calls, [])

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


if __name__ == "__main__":
    unittest.main()
