"""Offline tests for the V1.2 runner. Every transport is an OfflineTransport script."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from p4_v1_2_offline_support import (  # noqa: E402
    FakeClock, ScriptedOfflineTransport, oracle_v1_2, write_candidate_lock, write_dataset,
)

from tools.story_extraction import run_m4_draft_v1_2_predictions_v1 as runner  # noqa: E402

CASES = [("SYN_01", "c02_two_mentions_one_entity"), ("SYN_02", "c06_participant")]


class Harness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "run"
        self.root.mkdir()
        self.archive, self.input_root, self.archive_sha = write_dataset(self.root, CASES)
        self.lock, self.lock_sha = write_candidate_lock(self.root)
        self.clock = FakeClock()

    def tearDown(self):
        self.tmp.cleanup()

    def run_with(self, transport, **overrides):
        options = dict(candidate_lock=self.lock, candidate_lock_sha256=self.lock_sha,
                       input_archive=self.archive, input_root=self.input_root,
                       input_archive_sha256=self.archive_sha,
                       checkpoint_root=self.root / "checkpoints", artifact_root=self.root / "artifacts",
                       result_path=self.root / "result.json",
                       prediction_manifest_path=self.root / "manifest.json", transport=transport,
                       research_task_id="TEST-OFFLINE", max_provider_operations=100,
                       max_total_tokens=10_000_000, clock=self.clock, sleep=self.clock.sleep)
        options.update(overrides)
        return runner.execute(**options)

    def valid(self, index):
        case_id, name = CASES[index]
        return ("ok", oracle_v1_2(name, case_id))

    def artifact(self, case_id):
        return json.loads((self.root / "artifacts/case_results" / f"{case_id}.json").read_text())


class RunnerTests(Harness):
    def test_valid_primaries(self):
        transport = ScriptedOfflineTransport({"P4V12_SYN_01_PRIMARY": [self.valid(0)],
                                              "P4V12_SYN_02_PRIMARY": [self.valid(1)]})
        result = self.run_with(transport)
        self.assertEqual(result["run_status"], "COMPLETE")
        self.assertEqual(result["terminal_status_counts"], {"STRUCTURAL_VALID": 2})
        self.assertEqual(result["declared_unresolved_rate"], 0.0)
        self.assertFalse(result["live_execution"])
        self.assertIn("python", result["environment"])

    def test_locator_failure_gets_one_repair_with_locator_feedback(self):
        bad = json.loads(self.valid(0)[1])
        bad["mentions"][0]["quote"] = "absent quote"
        transport = ScriptedOfflineTransport({
            "P4V12_SYN_01_PRIMARY": [("ok", json.dumps(bad))],
            "P4V12_SYN_01_REPAIR_1": [self.valid(0)],
            "P4V12_SYN_02_PRIMARY": [self.valid(1)]})
        result = self.run_with(transport)
        item = result["predictions"][0]
        self.assertEqual(item["primary"]["validation"]["category"], "DRAFT_COMPILER_FAILURE")
        self.assertIn("LOCATOR_QUOTE_NOT_FOUND", transport.specs["P4V12_SYN_01_REPAIR_1"].user_prompt)
        self.assertEqual(item["terminal_status"], "STRUCTURAL_VALID")

    def test_declared_unresolved_is_reported_separately(self):
        draft = json.loads(self.valid(0)[1])
        declared = deepcopy(draft)
        declared["unresolved_locators"] = [{"handle": "M99", "passage_handle": "P1",
                                            "quote": "Mira", "reason": "REFERENT_UNCERTAIN"}]
        transport = ScriptedOfflineTransport({"P4V12_SYN_01_PRIMARY": [("ok", json.dumps(declared))],
                                              "P4V12_SYN_02_PRIMARY": [self.valid(1)]})
        result = self.run_with(transport)
        self.assertEqual(result["predictions"][0]["terminal_status"],
                         "STRUCTURAL_VALID_WITH_DECLARED_UNRESOLVED")
        self.assertGreater(result["declared_unresolved_rate"], 0)
        self.assertEqual(result["locator_totals"]["declared_unresolved"], 1)

    def test_rerun_is_idempotent(self):
        script = {"P4V12_SYN_01_PRIMARY": [self.valid(0)], "P4V12_SYN_02_PRIMARY": [self.valid(1)]}
        first = self.run_with(ScriptedOfflineTransport(script))
        again = ScriptedOfflineTransport({})
        second = self.run_with(again)
        self.assertEqual(again.calls, [])
        self.assertEqual(first["prediction_set_sha256"], second["prediction_set_sha256"])

    def test_transport_failure_is_not_a_quality_failure(self):
        transport = ScriptedOfflineTransport({"P4V12_SYN_01_PRIMARY": [("fail", "SERVER_FAILURE")] * 3,
                                              "P4V12_SYN_02_PRIMARY": [self.valid(1)]})
        result = self.run_with(transport)
        self.assertEqual(result["predictions"][0]["terminal_status"], "NOT_EVALUATED_TRANSPORT")


class InterruptionTests(Harness):
    def test_insufficient_token_estimate_stops_before_any_call(self):
        transport = ScriptedOfflineTransport({})
        result = self.run_with(transport, max_total_tokens=1000)
        self.assertEqual(transport.calls, [])
        self.assertEqual(result["run_status"], "INCONCLUSIVE_INFRASTRUCTURE_BUDGET_INSUFFICIENT_TOKENS")
        self.assertEqual(self.artifact("SYN_01")["terminal_status"],
                         "INTERRUPTED_BUDGET_INSUFFICIENT_TOKENS")
        self.assertEqual(result["not_started_cases"], ["SYN_02"])

    def test_insufficient_operations_stop_at_repair_with_artifact(self):
        bad = json.loads(self.valid(0)[1])
        bad["mentions"][0]["quote"] = "absent quote"
        transport = ScriptedOfflineTransport({"P4V12_SYN_01_PRIMARY": [("ok", json.dumps(bad))]})
        result = self.run_with(transport, max_provider_operations=9)
        artifact = self.artifact("SYN_01")
        self.assertEqual(artifact["terminal_status"], "INTERRUPTED_BUDGET_INSUFFICIENT_PROVIDER_OPERATIONS")
        self.assertIsNotNone(artifact["primary"]["raw_response_sha256"])
        self.assertIsNone(artifact["repair"]["raw_response_sha256"])
        self.assertEqual(transport.calls, ["P4V12_SYN_01_PRIMARY"])
        self.assertEqual(result["predictions"][0]["case_id"], "SYN_01")

    def test_model_version_drift_leaves_a_case_artifact(self):
        transport = ScriptedOfflineTransport({
            "P4V12_SYN_01_PRIMARY": [self.valid(0) + ({"total_token_count": 1}, "a")],
            "P4V12_SYN_02_PRIMARY": [self.valid(1) + ({"total_token_count": 1}, "b")]})
        result = self.run_with(transport)
        self.assertEqual(result["run_status"],
                         "INCONCLUSIVE_INFRASTRUCTURE_PROVIDER_REPORTED_MODEL_VERSION_CHANGED")
        self.assertEqual(self.artifact("SYN_02")["terminal_status"],
                         "INTERRUPTED_PROVIDER_REPORTED_MODEL_VERSION_CHANGED")

    def test_runner_error_is_recorded_not_lost(self):
        transport = ScriptedOfflineTransport({"P4V12_SYN_01_PRIMARY": [self.valid(0)],
                                              "P4V12_SYN_02_PRIMARY": [("crash",)]})
        result = self.run_with(transport)
        self.assertEqual(result["run_status"], "INTERRUPTED_RUNNER_ERROR")
        self.assertEqual(self.artifact("SYN_02")["error_type"], "RuntimeError")
        self.assertEqual(result["terminal_status_counts"]["STRUCTURAL_VALID"], 1)


class AuthorizationTests(Harness):
    def test_non_offline_transport_is_refused_before_any_work(self):
        calls = []

        def live_like(spec, window, request_id):
            calls.append(spec.job_id)

        with self.assertRaises(runner.LiveExecutionNotEnabled):
            self.run_with(live_like)

        class Fake:
            offline = True

            def __call__(self, *args):
                calls.append("fake")

        with self.assertRaises(runner.LiveExecutionNotEnabled):
            self.run_with(Fake())
        self.assertEqual(calls, [])

    def test_cli_has_no_live_mode(self):
        with self.assertRaises(SystemExit):
            runner.main(["--mode", "run-live", "--candidate-lock", str(self.lock),
                         "--candidate-lock-sha256", self.lock_sha, "--input-archive",
                         str(self.archive), "--input-root", str(self.input_root),
                         "--input-archive-sha256", self.archive_sha])
        self.assertFalse(hasattr(runner, "_live_transport"))

    def test_gold_paths_are_refused(self):
        with self.assertRaises(Exception):
            self.run_with(ScriptedOfflineTransport({}), artifact_root=self.root / "gold_out")


if __name__ == "__main__":
    unittest.main()
