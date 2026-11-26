"""Tests for tools/story_pipeline/run_story.py (running a story episode by episode)."""
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from io import StringIO
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

from tools.llm_infra import pipeline_clients  # noqa: E402
from tools.llm_infra.openrouter_router import OpenRouterQuotaPaused  # noqa: E402
from tools.llm_infra.quota_state import QuotaStateStore  # noqa: E402
from tools.story_memory.memory_v0 import StoryMemory  # noqa: E402
from tools.story_pipeline import run_pipeline, run_story  # noqa: E402
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

    def test_season_rejects_a_later_incompatible_brief_cache_before_any_call(self):
        later = run_story.episode_dir(self.season_dir, 3, self.ranges[2])
        later.mkdir(parents=True)
        saved = later / "run_manifest.json"
        saved.write_text(json.dumps({
            "status": "COMPLETED",
            "settings": {"brief_normalization": run_pipeline.stages.BRIEF_NORMALIZATION_VERSION},
            "brief_fingerprint": "old",
        }), encoding="utf-8")
        stamp = saved.read_bytes()
        stub = StubRun({})
        for enabled, message in ((False, "brief normalization differs"), (True, "Brief fingerprint differs")):
            with self.subTest(enabled=enabled), self.assertRaisesRegex(ValueError, message):
                self.season(stub, options={"brief_normalization": enabled})
        self.assertEqual(stub.calls, [])
        self.assertEqual(saved.read_bytes(), stamp)
        self.assertFalse((self.season_dir / "season.json").exists())
        saved.write_text("{", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Cannot read saved run manifest"):
            self.season(stub, options={"brief_normalization": True})
        saved.unlink()
        (later / "script_v1.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "requires a saved manifest"):
            self.season(stub, options={"brief_normalization": True})

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

    def test_rerun_refuses_to_skip_a_completed_episode_after_its_source_changes(self):
        ranges = [(1, 1)]
        args = (DEFAULT_MANIFEST, ranges, test_profile(), self.season_dir)
        first = run_story.run_season(ScriptedLLMClient(FakeModel()), *args, memory=None)
        self.assertEqual(first["episodes"][0]["status"], "COMPLETED")
        season_file = self.season_dir / "season.json"
        original = season_file.read_bytes()
        scope, background = run_story.run_pipeline.episode_scope(DEFAULT_MANIFEST, 1, 1)
        updated = replace(scope, chapters=(replace(scope.chapters[0], version="updated-source"),))
        client = ScriptedLLMClient(FakeModel())
        with patch.object(run_story.run_pipeline, "episode_scope", return_value=(updated, background)):
            with self.assertRaisesRegex(ValueError, "source changed"):
                run_story.run_season(client, *args, memory=None)
            with patch.object(run_story.run_pipeline, "make_client", return_value=client), \
                    redirect_stdout(StringIO()), redirect_stderr(StringIO()) as errors:
                self.assertEqual(run_story.main(["--chapters", "1", "--season-dir", str(self.season_dir),
                                                 "--no-memory"]), 2)
            self.assertIn("source changed", errors.getvalue())
        self.assertEqual(client.calls, [])
        self.assertEqual(season_file.read_bytes(), original)

    def test_later_source_mismatch_blocks_all_episodes_and_state_writes(self):
        ranges = [(1, 1), (2, 3)]
        scope, background = run_story.run_pipeline.episode_scope(DEFAULT_MANIFEST, 2, 3, recap=True)
        later = run_story.episode_dir(self.season_dir, 2, ranges[1])
        later.mkdir(parents=True)
        saved = later / "run_manifest.json"
        old_scope = replace(scope, chapters=(replace(scope.chapters[0], version="previous"), scope.chapters[1]))
        saved.write_text(json.dumps({
            "status": "COMPLETED",
            "source_identity": run_story.run_pipeline._source_identity(old_scope, background),
        }), encoding="utf-8")
        season_file = self.season_dir / "season.json"
        season_file.write_bytes(b"existing season index")
        original = saved.read_bytes()
        first = run_story.episode_dir(self.season_dir, 1, ranges[0])
        client = ScriptedLLMClient(FakeModel())

        with self.assertRaisesRegex(ValueError, "source changed"):
            run_story.run_season(client, DEFAULT_MANIFEST, ranges, test_profile(), self.season_dir, memory=None)
        with patch.object(run_story.run_pipeline, "make_client") as factory, \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()) as errors:
            self.assertEqual(run_story.main(["--chapters", "1-3", "--episodes", "1,2-3",
                                             "--season-dir", str(self.season_dir), "--no-memory"]), 2)
        factory.assert_not_called()
        self.assertIn("source changed", errors.getvalue())
        self.assertEqual(client.calls, [])
        self.assertFalse(first.exists())
        self.assertEqual(season_file.read_bytes(), b"existing season index")
        self.assertEqual(saved.read_bytes(), original)

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
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.season_dir = Path(self.tmp.name) / "season"

    def test_season_cli_restores_brief_normalization_and_rejects_an_explicit_change(self):
        client = ScriptedLLMClient(FakeModel())
        arguments = ["--chapters", "1", "--season-dir", str(self.season_dir), "--no-memory",
                     "--no-source-check", "--min-words", "20", "--max-words", "200"]
        with patch.object(run_pipeline, "make_client", return_value=client) as factory:
            self.assertEqual(run_story.main([*arguments, "--brief-normalization"]), 0)
            self.assertEqual(run_story.main(arguments), 0)
            self.assertEqual(run_story.main([*arguments, "--no-brief-normalization"]), 2)
        self.assertEqual(factory.call_count, 2)
        run_dir = run_story.episode_dir(self.season_dir, 1, (1, 1))
        saved = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(saved["invocation"]["brief_normalization"])

    def test_auto_quota_resumes_the_season_with_saved_policy_and_checkpoints(self):
        now = [1000.0]

        def clock():
            return now[0]

        store = QuotaStateStore(None, clock=clock)
        model = FakeModel()
        attempted = []

        def generate(system, user, requested, config, request_id):
            stage = request_id.split(":", 1)[0]
            attempted.append(stage)
            if stage == "plan" and clock() == 1000:
                store.block("openrouter", "*", "openrouter_account", 2000, "RPD", clock())
                raise OpenRouterQuotaPaused(1, 2000)
            return {"raw_content": model(stage, system, user), "model_requested": requested}

        def build(provider, settings, unused_store, **kwargs):
            adapter = real_builder(provider, settings, store, clock=clock, client_factory=self.fail, **kwargs)
            adapter.router.generate = generate
            return adapter

        real_builder = pipeline_clients.build_adapter
        policy = Path(self.tmp.name) / "policy.yaml"
        policy.write_text(
            "version: 1\nstages: {default: test}\ntiers:\n"
            "  test: {candidates: ['openrouter:*'], cross_provider_fallback: true, max_output_tokens: 4096}\n",
            encoding="utf-8",
        )
        settings = {"LLM_TELEMETRY_PATH": ":memory:", "LLM_QUOTA_STATE_PATH": ":memory:",
                    "OPENROUTER_API_KEY_1": "fake-openrouter-key"}
        cli = ["--season-dir", str(self.season_dir), "--dotenv", str(Path(self.tmp.name) / "absent"),
               "--no-memory", "--min-words", "20", "--max-words", "200", "--no-source-check", "--no-brief-check"]

        def read(name, root=self.season_dir):
            return json.loads((root / name).read_text(encoding="utf-8"))

        ep_dir = self.season_dir / "ep01_ch1"
        with patch.dict("os.environ", settings, clear=True), patch.object(pipeline_clients, "build_adapter", build), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(run_story.main([*cli, "--provider", "auto", "--routing-policy", str(policy)]), 0)
            self.assertEqual(read("season.json")["status"], "PAUSED_QUOTA")
            invocation = read("run_manifest.json", ep_dir)["invocation"]
            self.assertEqual(invocation["provider"], "auto")
            self.assertEqual(invocation["routing_policy_path"], str(policy))
            self.assertEqual((invocation["chapters"], invocation["recap"]), ("1-1", True))
            self.assertEqual(attempted, ["brief", "plan"])
            checkpoint = (ep_dir / "briefs" / "chapter_001.json").read_bytes()

            self.assertEqual(run_story.main([*cli, "--provider", "gemini"]), 2)
            old_policy = policy.read_text(encoding="utf-8")
            policy.write_text(old_policy + "# edited at resume\n", encoding="utf-8")
            self.assertEqual(run_story.main(cli), 2)
            self.assertEqual(attempted, ["brief", "plan"])
            policy.write_text(old_policy, encoding="utf-8")

            self.assertEqual(run_story.main(cli), 0)
            self.assertEqual(read("season.json")["status"], "PAUSED_QUOTA")
            self.assertEqual(attempted, ["brief", "plan"])
            now[0] = 2001
            self.assertEqual(run_story.main(cli), 0)
            self.assertEqual(read("season.json")["status"], "COMPLETED")
            self.assertEqual(read("run_manifest.json", ep_dir)["invocation"], invocation)
            self.assertEqual((ep_dir / "briefs" / "chapter_001.json").read_bytes(), checkpoint)
            self.assertEqual(attempted.count("brief"), 1)
            rows = [json.loads(line) for line in (ep_dir / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual({row["provider"] for row in rows}, {"openrouter"})

    def test_locked_season_refuses_new_providers_and_keeps_legacy_gemini(self):
        self.season_dir.mkdir()
        (self.season_dir / "gate_lock.json").write_text("{}", encoding="utf-8")
        cli = ["--season-dir", str(self.season_dir), "--dotenv", str(Path(self.tmp.name) / "absent"),
               "--no-memory", "--no-brief-check", "--stop-after", "brief", "--model", "gemini-3.8-flash"]
        gemini = ScriptedLLMClient(FakeModel(), name="gemini:gemini-3.8-flash")
        original = gemini.complete
        gemini.complete = lambda **kwargs: original(**kwargs) | {"provider": "Google Gemini API"}
        errors = StringIO()
        with patch.dict("os.environ", {}, clear=True), redirect_stdout(StringIO()), redirect_stderr(errors), \
                patch("tools.story_pipeline.llm.GeminiLLMClient", return_value=gemini) as factory:
            for provider in ("auto", "groq", "openrouter", "cloudflare"):
                with self.subTest(provider=provider):
                    self.assertEqual(run_story.main([*cli, "--provider", provider]), 2)
                    self.assertIn("Locked story runs require --provider gemini", errors.getvalue())
            factory.assert_not_called()
            self.assertEqual(run_story.main(cli), 0)
            factory.assert_called_once()
        episode = self.season_dir / "ep01_ch1"
        manifest = json.loads((episode / "run_manifest.json").read_text(encoding="utf-8"))
        self.assertIsNone(manifest["invocation"])
        rows = [json.loads(line) for line in (episode / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertTrue(rows)
        self.assertTrue(all("provider" not in row for row in rows))

    def test_bad_episode_plan_is_rejected_before_any_call(self):
        self.assertEqual(run_story.main(["--chapters", "1-5", "--episodes", "1,3-5"]), 2)


if __name__ == "__main__":
    unittest.main()
