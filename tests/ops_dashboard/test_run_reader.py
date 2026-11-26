import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools.ops_dashboard.run_reader import read_runs


class RunReaderTests(unittest.TestCase):
    def write_manifest(self, directory, manifest, outputs=()):
        directory.mkdir(parents=True)
        (directory / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        for output in outputs:
            (directory / output).touch()

    def test_scan_reads_newest_fifty_manifests_and_ignores_corrupt_input(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(55):
                path = root / f"run-{index:02}" / "run_manifest.json"
                path.parent.mkdir()
                path.write_text('{"status": "COMPLETED"}', encoding="utf-8")
                os.utime(path, (1_700_000_000 + index,) * 2)
            corrupt = root / "corrupt" / "run_manifest.json"
            corrupt.parent.mkdir()
            corrupt.write_text("{", encoding="utf-8")
            runs = read_runs(root, root / "absent")
            self.assertEqual(len(runs), 49)
            self.assertEqual([run["id"] for run in runs], [f"run-{index:02}" for index in range(54, 5, -1)])

    def test_review_run_uses_outputs_and_totals_across_invocations(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / "review-run"
            self.write_manifest(run_dir, {
                "status": "NEEDS_REVIEW", "source_check_quota_exhausted": True,
                "review_reasons": ["Synthetic reason one", "Synthetic reason two"],
                "model_calls": 2, "seconds": 737, "usage": {"total": {"total": 19942}},
            }, ("story_brief.json", "plan.json", "script_v1.json", "critic_v1.json", "script_v2.json",
                "source_check_v1_c1.json", "script_final.md", "report.json", "review_form.md"))
            with (run_dir / "calls.jsonl").open("w", encoding="utf-8") as log:
                for count, call in (
                    (8, {"stage": "brief", "valid": False, "seconds": 2.5, "usage": {"total_token_count": 20}}),
                    (4, {"stage": "source_check", "seconds": 10, "usage": {"total_tokens": 100}}),
                    (1, {"stage": "critic", "seconds": 4, "usage": {"total_tokens": "999", "unlisted": 500}}),
                    (1, {"stage": "revise", "seconds": True, "usage": {"total_token_count": True}}),
                ):
                    for _ in range(count):
                        log.write(json.dumps({**call, "raw_content": "Synthetic response sentinel"}) + "\n")

            runs = read_runs(root, root / "absent")
            self.assertEqual(len(runs), 1)
            run = runs[0]
            self.assertEqual(run["status"], "NEEDS_REVIEW")
            self.assertEqual(run["note"], "Đối chiếu nguồn chưa xong một phần")
            self.assertEqual(run["review_reasons_count"], 2)
            self.assertIsNone(run["current"])
            self.assertEqual(run["completed"], ["brief", "plan", "script", "critic", "revise"])
            self.assertEqual(run["stages"]["brief"], {"status": "COMPLETED", "seconds": 20, "source": "reported"})
            self.assertEqual((run["calls"], run["seconds"], run["tokens"], run["totals_scope"]), (14, 64, 560, "callLog"))
            self.assertEqual(set(run["sources"].values()), {"reported"})
            payload = json.dumps(runs)
            for private in ("raw_content", "Synthetic response sentinel", "Synthetic reason"):
                self.assertNotIn(private, payload)

    def test_episode_status_and_latest_invocation_fallback(self):
        for manifest_status, error, status in (
            ("PAUSED_QUOTA", "QUOTA_EXHAUSTED", "PAUSED_QUOTA"),
            ("FAILED", "HTTP 429", "PAUSED_QUOTA"),
            ("FAILED", "AUTH_FAILURE", "FAILED"),
            ("COMPLETED", "QUOTA_EXHAUSTED", "COMPLETED"),
        ):
            with self.subTest(status=manifest_status, error=error), TemporaryDirectory() as directory:
                root = Path(directory)
                season = root / "season"
                self.write_manifest(season / "episode", {
                    "status": manifest_status, "error": error,
                    "source_check_failed": [{"error": "Synthetic source error"}],
                    "model_calls": 2, "seconds": 737, "usage": {"total": {"total": 19942}},
                }, ("story_brief.json",))
                (season / "season.json").write_text(json.dumps({
                    "status": "COMPLETED", "episodes": [{"dir": "episode", "status": "PAUSED_QUOTA"}],
                }), encoding="utf-8")

                runs = read_runs(root / "absent", root)
                episode = next(run for run in runs if run.get("id") == "episode")
                self.assertEqual(episode["status"], status)
                self.assertEqual(episode["note"], "Đối chiếu nguồn chưa xong một phần")
                self.assertNotIn("Synthetic source error", json.dumps(runs))
                self.assertEqual(episode["current"], None if status == "COMPLETED" else "plan")
                self.assertEqual(episode["completed"], ["brief"])
                self.assertEqual(episode["totals_scope"], "latestInvocation")
                self.assertEqual((episode["calls"], episode["seconds"], episode["tokens"]), (2, 737, 19942))
                self.assertEqual("tiếp tục" in (episode["hint"] or ""), status == "PAUSED_QUOTA")

                (season / "gate_lock.json").touch()
                self.assertEqual(read_runs(root / "absent", root), [
                    {"label": "đợt chạy đã khóa (M9)", "status": "COMPLETED"},
                ])

    def test_call_log_falls_back_to_manifest_per_total(self):
        for usage, tokens, token_scope, valid, scope in (
            ({}, 15, "latestInvocation", False, {}),
            ({}, 15, "latestInvocation", True, {"scope": {"chapters": [1, 2]}}),
            ({"total_tokens": 0}, 0, "callLog", False, {}),
        ):
            with self.subTest(usage=usage, valid=valid), TemporaryDirectory() as directory:
                root = Path(directory)
                run_dir = root / "run"
                self.write_manifest(run_dir, {
                    "status": "FAILED", "error": "QUOTA_EXHAUSTED", "model_calls": 5,
                    "seconds": 7, "usage": {"total": {"total": 15}}, **scope,
                })
                call = {"stage": "brief", "valid": valid, "seconds": 0, "usage": usage}
                (run_dir / "calls.jsonl").write_text(json.dumps(call) + "\n", encoding="utf-8")
                run, = read_runs(root, root / "absent")

                self.assertEqual(run["current"], "brief")
                self.assertEqual((run["calls"], run["seconds"], run["tokens"]), (1, 0, tokens))
                self.assertEqual(run["total_scopes"], {
                    "calls": "callLog", "seconds": "callLog", "tokens": token_scope,
                })
                self.assertEqual(run["totals_scope"], "callLog" if token_scope == "callLog" else None)

    def test_call_log_line_cap_marks_totals_partial(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / "run"
            self.write_manifest(run_dir, {"status": "RUNNING", "model_calls": 999})
            (run_dir / "calls.jsonl").write_text('{"seconds": 1, "usage": {"total_tokens": 2}}\n' * 3,
                                                encoding="utf-8")
            with patch("tools.ops_dashboard.run_reader._CALL_LINE_LIMIT", 2):
                run, = read_runs(root, root / "absent")
                with patch("tools.ops_dashboard.run_reader._DETAIL_CALL_LIMIT", 1):
                    detail, = read_runs(root, root / "absent", detail_ref=run["detail_ref"])
            self.assertEqual((run["calls"], run["seconds"], run["tokens"], run["totals_scope"]),
                             (2, 2, 4, "partialCallLog"))
            self.assertTrue(detail["attempts_truncated"])
            self.assertEqual(len(detail["attempts"]), 1)
