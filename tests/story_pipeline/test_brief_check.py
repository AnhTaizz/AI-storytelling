"""Tests for tools/story_pipeline/brief_check.py (M7: briefs checked against their source)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_story_pipeline_v0 import FakeModel, brief_json, test_profile  # noqa: E402  (shared fixtures)

from tools.story_pipeline import brief_check  # noqa: E402
from tools.story_pipeline.llm import CallLog, ScriptedLLMClient  # noqa: E402
from tools.story_pipeline.run_pipeline import DEFAULT_MANIFEST, run  # noqa: E402
from tools.story_pipeline.source import load_scope  # noqa: E402


def finding(ref, verdict="STRONGER_THAN_SOURCE", text="Amane đưa ô cho Mahiru", label=None):
    return {"ref": ref, "verdict": verdict, "explanation": "giải thích", "corrected_text": text,
            "corrected_label": label}


class BriefCheckTests(unittest.TestCase):
    def setUp(self):
        self.scope = load_scope(DEFAULT_MANIFEST, (1, 1))
        self.chapter = self.scope.chapters[0]
        self.brief = brief_json(1)

    def test_items_are_listed_with_refs_labels_and_evidence(self):
        lines = brief_check.item_lines(self.brief)
        self.assertIn("- c1.E1 [event, EXPLICIT, CORE] (cites 1.2): Amane thấy Mahiru trên xích đu", lines)
        self.assertIn("- c1.CH1.F1 [fact, EXPLICIT] (cites 1.2): Học sinh năm nhất", lines)
        self.assertIn("- c1.R1 [relationship, EXPLICIT] (cites 1.2): Hàng xóm", lines)

    def test_answers_are_validated(self):
        cases = [
            ("valid", [finding("c1.E2")], []),
            ("unknown ref", [finding("c1.E99")], ["no such item"]),
            ("twice", [finding("c1.E2"), finding("c1.E2")], ["once"]),
            ("label verdict without a label", [finding("c1.E2", "WRONG_LABEL", None)], ["needs corrected_label",
                                                                                      "give corrected_text"]),
            ("removal is for NOT_SUPPORTED only", [finding("c1.E2", "CONTRADICTS_SOURCE", None)], ["give corrected_text"]),
            ("NOT_SUPPORTED may remove", [finding("c1.E2", "NOT_SUPPORTED", None)], []),
        ]
        for label, findings, expected in cases:
            with self.subTest(label):
                errors = brief_check.brief_check_errors({"findings": findings}, self.brief)
                self.assertEqual(len(errors), len(expected), errors)
                for message, error in zip(expected, errors):
                    self.assertIn(message, error)

    def test_corrections_apply_only_when_the_brief_stays_valid(self):
        findings = [
            finding("c1.E2", text="Amane nhường ô cho Mahiru"),                        # applied
            finding("c1.R1", "WRONG_LABEL", None, "REPORTED"),                         # rejected: no hedge in text
            finding("c1.E1", "NOT_SUPPORTED", None),                                   # CORE: never removed
            finding("c1.CH1.F1", "NOT_SUPPORTED", None),                               # removed
            finding("c1.E3", "NOT_SUPPORTED", None),                                   # MINOR event: removed
            finding("c1.CH9.F1", text="x"),                                            # unknown
        ]
        fixed, applied, rejected = brief_check.apply_corrections(self.brief, findings, self.chapter, "ja", "vi")
        self.assertEqual([a["ref"] for a in applied], ["c1.E2", "c1.CH1.F1", "c1.E3"])
        self.assertEqual({r["ref"]: r["reason"].split()[0] for r in rejected},
                         {"c1.R1": "the", "c1.E1": "a", "c1.CH9.F1": "no"})
        self.assertEqual(fixed["events"][1]["summary"], "Amane nhường ô cho Mahiru")
        self.assertEqual(fixed["characters"][0]["facts"], [])
        self.assertNotIn("E3", [e["id"] for e in fixed["events"]])
        self.assertEqual(self.brief["events"][1]["summary"], "Amane đưa ô cho Mahiru")  # the input is untouched
        page = brief_check.report_markdown({"1": {"findings": 6, "applied": applied, "rejected": rejected},
                                            "2": {"failed": "boom"}})
        self.assertIn("[đã áp] c1.E2 (mạnh hơn nguồn)", page)
        self.assertIn("[CẦN XEM] c1.R1 (sai nhãn)", page)
        self.assertIn("Không kiểm được: boom", page)

    def test_the_stage_and_its_place_in_the_pipeline(self):
        class CheckingModel(FakeModel):
            def __call__(self, stage, system, user):
                if stage == "brief_check":
                    self.check_prompt = user
                    return json.dumps({"findings": [finding("c1.E2", text="Amane nhường ô cho Mahiru")]},
                                      ensure_ascii=False)
                return super().__call__(stage, system, user)

        model = CheckingModel()
        result = brief_check.run_brief_check(ScriptedLLMClient(model), self.chapter, self.brief, test_profile(),
                                             "ja", CallLog(), 1)
        self.assertEqual(result["findings"][0]["ref"], "c1.E2")
        self.assertIn("[1.2]", model.check_prompt)  # the chapter's source passages
        with tempfile.TemporaryDirectory() as tmp:
            prompts = []
            model = CheckingModel()
            client = ScriptedLLMClient(lambda stage, system, user: (prompts.append((stage, user)),
                                                                     model(stage, system, user))[1])
            manifest = run(client, self.scope, test_profile(), Path(tmp) / "run", stop_after="plan")
            self.assertEqual([a["ref"] for a in manifest["brief_check"]["1"]["applied"]], ["c1.E2"])
            plan_prompt = next(user for stage, user in prompts if stage == "plan")
            self.assertIn("Amane nhường ô cho Mahiru", plan_prompt)  # the plan sees the corrected brief
            stored = json.loads((Path(tmp) / "run" / "briefs" / "chapter_001.json").read_text(encoding="utf-8"))
            self.assertEqual(stored["events"][1]["summary"], "Amane đưa ô cho Mahiru")  # the model's brief is kept
            self.assertIn("[đã áp] c1.E2", (Path(tmp) / "run" / "brief_check.md").read_text(encoding="utf-8"))

            off = ScriptedLLMClient(FakeModel())
            manifest = run(off, self.scope, test_profile(), Path(tmp) / "off", stop_after="plan", check_briefs=False)
            self.assertNotIn("brief_check", [c["stage"] for c in off.calls])
            self.assertNotIn("brief_check", manifest)

            class BrokenModel(FakeModel):
                def __call__(self, stage, system, user):
                    return '{"findings": 1}' if stage == "brief_check" else super().__call__(stage, system, user)

            manifest = run(ScriptedLLMClient(BrokenModel()), self.scope, test_profile(), Path(tmp) / "broken",
                           stop_after="plan", max_repairs=0)
            self.assertEqual(manifest["status"], "STOPPED_AFTER_PLAN")
            self.assertIn("failed", manifest["brief_check"]["1"])

    def test_correcting_a_compound_fact_must_preserve_its_hedge(self):
        original = "Nghe nói Itsuki đã lo lắng cho Amane và gửi tin nhắn hỏi thăm cậu"
        fact = self.brief["characters"][0]["facts"][0]
        fact.update(text=original, epistemic="REPORTED")
        for text, accepted in (("Itsuki đã lo lắng cho Amane", False),
                               ("Nghe nói Itsuki đã lo lắng cho Amane", True)):
            with self.subTest(text=text):
                proposal = finding("c1.CH1.F1", text=text)
                fixed, applied, rejected = brief_check.apply_corrections(
                    self.brief, [proposal], self.chapter, "ja", "vi"
                )
                fixed_fact = fixed["characters"][0]["facts"][0]
                self.assertEqual(fixed_fact, {**fact, "text": text if accepted else original})
                self.assertEqual([item["ref"] for item in applied], [proposal["ref"]] if accepted else [])
                self.assertEqual([item["ref"] for item in rejected], [] if accepted else [proposal["ref"]])


if __name__ == "__main__":
    unittest.main()
