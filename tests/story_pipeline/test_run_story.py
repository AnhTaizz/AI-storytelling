"""Tests for tools/story_pipeline/run_story.py (running a story episode by episode)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_story_pipeline_v0 import FakeModel, test_profile  # noqa: E402  (shared fixtures)

from tools.story_memory.memory_v0 import StoryMemory  # noqa: E402
from tools.story_pipeline import run_story  # noqa: E402
from tools.story_pipeline.llm import GeminiLLMClient, ScriptedLLMClient  # noqa: E402
from tools.story_pipeline.run_pipeline import DEFAULT_MANIFEST  # noqa: E402


class StubRun:
    """Stands in for run_pipeline.run: writes a manifest with a scripted status per episode."""

    def __init__(self, outcomes):
        self.outcomes = outcomes  # chapters start -> (status, error) or a list consumed in order
        self.calls = []

    def __call__(self, client, scope, profile, out_dir, **kwargs):
        start = scope.chapters[0].order
        self.calls.append({"start": start, "resume": kwargs["resume"],
                           "background": [c.order for c in kwargs["background"]]})
        outcome = self.outcomes.get(start, ("COMPLETED", None))
        if isinstance(outcome, list):
            outcome = outcome.pop(0)
        status, error = outcome
        manifest = {"status": status, "model_calls": 3, "seconds": 1.0,
                    "usage": {"total": {"total": 100}}}
        if error:
            manifest["error"] = error
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        if status == "COMPLETED":
            (out_dir / "script_final.txt").write_text(f"Lời dẫn tập bắt đầu ở chương {start}.\n", encoding="utf-8")
            (out_dir / "report.json").write_text(json.dumps({
                "gates": {"GATE_FACTUAL_GROUNDING": {"status": "FLAG"}, "GATE_SPOILER_DISCIPLINE": {"status": "PASS"}},
                "findings": [{"x": 1}], "final_check": {"word_count": 950}}), encoding="utf-8")
        return manifest


class PlanTests(unittest.TestCase):
    def test_episodes_cover_the_range_in_order(self):
        self.assertEqual(run_story.plan_episodes(1, 5, "1,2-3,4-5"), [(1, 1), (2, 3), (4, 5)])
        self.assertEqual(run_story.plan_episodes(1, 7, episode_size=3), [(1, 3), (4, 6), (7, 7)])
        self.assertEqual(run_story.plan_episodes(4, 5), [(4, 4), (5, 5)])
        for label, episodes in {"gap": "1,3-5", "overlap": "1-2,2-5", "short": "1,2-3", "backwards": "1,3-2"}.items():
            with self.subTest(label):
                with self.assertRaises(ValueError):
                    run_story.plan_episodes(1, 5, episodes)
        with self.assertRaises(ValueError):
            run_story.plan_episodes(1, 5, episode_size=0)


class SeasonTests(unittest.TestCase):
    def test_daily_quota_pauses_plan_and_resume_reuses_brief(self):
        class DailyLimit(Exception):
            code = 429
            details = {"details": [{"@type": "google.rpc.QuotaFailure",
                                    "violations": [{"quotaId": "RequestsPerDay"}]}]}

        class ExhaustedSDK:
            def generate(self, **kwargs):
                raise DailyLimit("test-key-not-real-1")

        self.enterContext(patch("tools.story_extraction.gemini_transport_v1.official_client_factory",
                                side_effect=AssertionError("unexpected SDK construction")))
        settings = {"GEMINI_API_KEY_1": "test-key-not-real-1"}
        gemini = GeminiLLMClient("gemini-3.8-flash", dotenv_path=self.season_dir / "absent", environ=settings,
                                 clock=lambda: 1000, sleep=self.fail, client_factory=lambda key: ExhaustedSDK())
        responder = FakeModel()

        def exhaust_at_plan(stage, system, user):
            if stage == "plan":
                return gemini.complete(system=system, user=user, request_id="plan")["raw_content"]
            return responder(stage, system, user)

        args = (DEFAULT_MANIFEST, [(1, 1)], test_profile(), self.season_dir)
        options = {"source_check": False}
        paused = run_story.run_season(ScriptedLLMClient(exhaust_at_plan), *args, memory=None, options=options)
        self.assertEqual(paused["status"], "PAUSED_QUOTA")
        self.assertIn("QUOTA_EXHAUSTED", str(paused))
        self.assertNotIn("test-key-not-real", str(paused) + str(gemini.attempt_failures))
        resumed = ScriptedLLMClient(responder)
        result = run_story.run_season(resumed, *args, memory=None, options=options)
        self.assertEqual(result["status"], "COMPLETED")
        stages = [call["stage"] for call in resumed.calls]
        self.assertEqual(stages[0], "plan")
        self.assertNotIn("brief", stages)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.season_dir = Path(self.tmp.name) / "season"
        self.ranges = [(1, 1), (2, 3), (4, 5)]

    def season(self, stub, **kwargs):
        return run_story.run_season(None, DEFAULT_MANIFEST, self.ranges, test_profile(), self.season_dir,
                                    memory=None, run=stub, **kwargs)

    def test_episodes_run_in_order_with_earlier_chapters_as_background(self):
        stub = StubRun({})
        season = self.season(stub)
        self.assertEqual(season["status"], "COMPLETED")
        self.assertEqual([c["background"] for c in stub.calls], [[], [1], [1, 2, 3]])
        self.assertEqual([r["dir"] for r in season["episodes"]], ["ep01_ch1", "ep02_ch2-3", "ep03_ch4-5"])
        self.assertEqual(season["episodes"][1]["gates_needing_review"], ["GATE_FACTUAL_GROUNDING"])
        self.assertEqual(season["totals"]["tokens"], 300)
        index = (self.season_dir / "season.md").read_text(encoding="utf-8")
        self.assertIn("[review](ep02_ch2-3/review.html)", index)
        page = (self.season_dir / "season.html").read_text(encoding="utf-8")
        self.assertIn("href='ep02_ch2-3/review.html'", page)
        self.assertIn("FACTUAL_GROUNDING", page)
        self.assertEqual(json.loads((self.season_dir / "season.json").read_text(encoding="utf-8")), season)
        script = (self.season_dir / "season_script.md").read_text(encoding="utf-8")
        self.assertIn("## Tập 2 (chương 2–3)\n\nLời dẫn tập bắt đầu ở chương 2.", script)

    def test_rerun_skips_completed_episodes_and_resumes_the_rest(self):
        self.season(StubRun({2: ("FAILED", "stage plan failed after 3 attempt(s): bad JSON")}))
        stub = StubRun({})
        season = self.season(stub)
        self.assertEqual([(c["start"], c["resume"]) for c in stub.calls], [(2, True), (4, False)])
        self.assertTrue(season["episodes"][0]["skipped_as_completed"])
        self.assertEqual(season["status"], "COMPLETED")

    def test_apply_review_resumes_completed_episodes_with_unapplied_errors(self):
        self.season(StubRun({}))
        form = self.season_dir / "ep02_ch2-3" / "review_form.md"
        form.write_text('Lỗi cụ thể (trích câu):\n\n- "câu sai" → vì sao\n\nKết luận: ☐ Sửa nhẹ\n', encoding="utf-8")
        stub = StubRun({})
        self.season(stub)
        self.assertEqual(stub.calls, [])  # without --apply-review nothing reruns
        self.season(stub, options={"owner_review": "review_form.md"})
        self.assertEqual([(c["start"], c["resume"]) for c in stub.calls], [(2, True)])

    def test_quota_pauses_and_failures_stop_unless_told_to_keep_going(self):
        cases = [
            ("quota", {2: ("FAILED", "TransientProviderError: 429 RESOURCE_EXHAUSTED")}, {}, "PAUSED_QUOTA", [1, 2]),
            ("failure stops", {2: ("FAILED", "stage brief failed")}, {}, "FAILED", [1, 2]),
            ("keep going", {2: ("FAILED", "stage brief failed")}, {"stop_on_failure": False},
             "COMPLETED_WITH_FAILURES", [1, 2, 4]),
        ]
        for label, outcomes, kwargs, status, started in cases:
            with self.subTest(label):
                season_dir = Path(self.tmp.name) / label.replace(" ", "_")
                stub = StubRun(outcomes)
                season = run_story.run_season(None, DEFAULT_MANIFEST, self.ranges, test_profile(), season_dir,
                                              memory=None, run=stub, **kwargs)
                self.assertEqual(season["status"], status)
                self.assertEqual([c["start"] for c in stub.calls], started)
                self.assertEqual(len(season["episodes"]), 3)  # episodes not reached are listed as NOT_RUN
                if status != "COMPLETED_WITH_FAILURES":
                    self.assertEqual(season["episodes"][2]["status"], "NOT_RUN")
                    self.assertIn("tập 2", season["stop_reason"])
                    self.assertIn("Dừng: tập 2", (season_dir / "season.html").read_text(encoding="utf-8"))

    def test_season_with_the_real_pipeline_and_shared_memory(self):
        client = ScriptedLLMClient(FakeModel())
        with tempfile.TemporaryDirectory() as tmp:
            memory = StoryMemory(Path(tmp) / "memory", "story-sample-0001")
            season = run_story.run_season(client, DEFAULT_MANIFEST, [(1, 1), (2, 2)], test_profile(),
                                          Path(tmp) / "season", memory=memory,
                                          options={"source_check": False})
            self.assertEqual(season["status"], "COMPLETED", season)
            # Episode 2 reuses chapter 1's brief from memory instead of asking the model again.
            briefs = [c for c in client.calls if c["stage"] == "brief"]
            self.assertEqual(len(briefs), 2)
            ep2 = json.loads((Path(tmp) / "season" / "ep02_ch2" / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(ep2["brief_sources"], {"1": "memory", "2": "model"})
            self.assertTrue((Path(tmp) / "season" / "ep02_ch2" / "review.html").is_file())
            self.assertGreater(ep2["usage"]["total"]["calls"], 0)

    def test_source_check_quota_saves_the_draft_and_resumes_before_next_episode(self):
        model = FakeModel()  # The first critic finds a problem that would normally trigger revision.

        def quota_on_second_chunk(stage, system, user):
            if stage == "source_check" and "<P002>" in user:
                raise RuntimeError("429 RESOURCE_EXHAUSTED")
            return model(stage, system, user)

        ranges = [(1, 1), (2, 2)]
        memory = StoryMemory(Path(self.tmp.name) / "memory", "story-sample-0001")
        client = ScriptedLLMClient(quota_on_second_chunk)
        options = {"source_check_chunk": 1}
        season = run_story.run_season(client, DEFAULT_MANIFEST, ranges, test_profile(), self.season_dir,
                                      memory=memory, stop_on_failure=False, options=options)
        self.assertEqual(season["status"], "PAUSED_QUOTA")
        self.assertIn("tập 1", season["stop_reason"])
        self.assertEqual([row["status"] for row in season["episodes"]], ["NEEDS_REVIEW", "NOT_RUN"])
        self.assertEqual(json.loads((self.season_dir / "season.json").read_text(encoding="utf-8")), season)
        self.assertFalse((self.season_dir / "ep02_ch2").exists())
        missing_check = "source_check:v1c2:attempt1"
        self.assertEqual(client.calls[-1]["request_id"], missing_check)

        episode = self.season_dir / "ep01_ch1"
        self.assertTrue((episode / "source_check_v1_c1.json").is_file())
        self.assertFalse((episode / "source_check_v1_c2.json").exists())
        draft = (episode / "script_final.txt").read_text(encoding="utf-8")
        self.assertIn("buổi chiều mưa", draft)
        report = json.loads((episode / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "NEEDS_REVIEW")
        self.assertIn("RESOURCE_EXHAUSTED", report["review_reasons"][0])

        resumed = ScriptedLLMClient(model)
        season = run_story.run_season(resumed, DEFAULT_MANIFEST, ranges, test_profile(), self.season_dir,
                                      memory=memory, stop_on_failure=False, options=options)
        self.assertEqual(season["status"], "COMPLETED")
        self.assertEqual([row["status"] for row in season["episodes"]], ["COMPLETED", "COMPLETED"])
        requests = [call["request_id"] for call in resumed.calls]
        ep2_start = requests.index("brief:ch2:attempt1")
        self.assertEqual(requests[:ep2_start], [missing_check, "revise:v2:attempt1", "critic:v2:attempt1",
                                                "source_check:v2:attempt1"])
        self.assertTrue((episode / "source_check_v1_c2.json").is_file())
        report = json.loads((episode / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["review_reasons"], [])


class CliTests(unittest.TestCase):
    def test_bad_episode_plan_is_rejected_before_any_call(self):
        self.assertEqual(run_story.main(["--chapters", "1-5", "--episodes", "1,3-5"]), 2)


if __name__ == "__main__":
    unittest.main()
