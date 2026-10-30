"""Offline tests for the P3 Draft V1.1 runner. Every provider call is scripted."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from p3_v1_1_offline_support import (  # noqa: E402
    FakeClock,
    ScriptedTransport,
    draft_json,
    oracle_case,
    write_candidate_lock,
    write_dataset,
)

from tools.story_extraction import run_m4_draft_v1_1_predictions_v1 as runner  # noqa: E402
from tools.story_extraction.m4_draft_v1_1_candidate_p3_v1 import (  # noqa: E402
    candidate_definition_sha256,
    canonical_json_bytes,
)

CASES = [("SYN_01", "c02_two_mentions_one_entity"), ("SYN_02", "c06_participant")]


def valid_raw(case_id: str, name: str) -> str:
    return draft_json(oracle_case(name, case_id)[1])


class RunnerHarness(unittest.TestCase):
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
        options = dict(
            candidate_lock=self.lock, candidate_lock_sha256=self.lock_sha,
            input_archive=self.archive, input_root=self.input_root,
            input_archive_sha256=self.archive_sha,
            checkpoint_root=self.root / "checkpoints", artifact_root=self.root / "artifacts",
            result_path=self.root / "result.json",
            prediction_manifest_path=self.root / "prediction_manifest.json",
            transport=transport, research_task_id="TEST-OFFLINE",
            max_provider_operations=100, max_total_tokens=1_000_000,
            clock=self.clock, sleep=self.clock.sleep,
        )
        options.update(overrides)
        return runner.execute(**options)

    def by_case(self, result):
        return {item["case_id"]: item for item in result["predictions"]}


class StructuralPathTests(RunnerHarness):
    def test_valid_primary_compiles_with_one_call_per_case(self):
        transport = ScriptedTransport({
            "P3V11_SYN_01_PRIMARY": [("ok", valid_raw("SYN_01", CASES[0][1]))],
            "P3V11_SYN_02_PRIMARY": [("ok", valid_raw("SYN_02", CASES[1][1]))],
        })
        result = self.run_with(transport)
        self.assertEqual(result["run_status"], "COMPLETE")
        self.assertEqual(result["terminal_status_counts"], {"STRUCTURAL_VALID": 2})
        self.assertEqual(result["primary_structural_valid_count"], 2)
        self.assertEqual(len(transport.calls), 2)
        for item in result["predictions"]:
            self.assertIsNotNone(item["compiled_batch_sha256"])
            self.assertEqual(item["primary"]["validation"]["advisories"], [])
        compiled = json.loads((self.root / "artifacts/compiled/SYN_01.json").read_text())
        self.assertEqual(compiled["process"]["process_id"],
                         "P3_STORY_EXTRACTION_DRAFT_V1_1_GEMINI_3_5_FLASH_LITE_V1")
        self.assertFalse(result["gold_opened"])
        self.assertFalse(result["scoring_performed"])

    def test_malformed_json_gets_one_repair_with_sanitized_feedback(self):
        transport = ScriptedTransport({
            "P3V11_SYN_01_PRIMARY": [("ok", "{not json")],
            "P3V11_SYN_01_REPAIR_1": [("ok", valid_raw("SYN_01", CASES[0][1]))],
            "P3V11_SYN_02_PRIMARY": [("ok", valid_raw("SYN_02", CASES[1][1]))],
        })
        result = self.run_with(transport)
        item = self.by_case(result)["SYN_01"]
        self.assertTrue(item["repair_used"])
        self.assertEqual(item["primary"]["validation"]["category"], "JSON_PARSE_FAILURE")
        self.assertEqual(item["terminal_status"], "STRUCTURAL_VALID")
        repair_prompt = transport.specs["P3V11_SYN_01_REPAIR_1"].user_prompt
        self.assertIn('"code": "INVALID_JSON"', repair_prompt)
        for forbidden in ('"gold"', '"score"', '"recall"'):
            self.assertNotIn(forbidden, repair_prompt)

    def test_reintroduced_evidence_handle_is_a_schema_failure_and_repair_is_terminal(self):
        _, draft = oracle_case(CASES[0][1], "SYN_01")
        bad = deepcopy(draft)
        bad["mentions"][0]["evidence_handle"] = "EV1"
        transport = ScriptedTransport({
            "P3V11_SYN_01_PRIMARY": [("ok", draft_json(bad))],
            "P3V11_SYN_01_REPAIR_1": [("ok", draft_json(bad))],
            "P3V11_SYN_02_PRIMARY": [("ok", valid_raw("SYN_02", CASES[1][1]))],
        })
        result = self.run_with(transport)
        item = self.by_case(result)["SYN_01"]
        self.assertEqual(item["primary"]["validation"]["category"], "DRAFT_SCHEMA_FAILURE")
        self.assertEqual(item["terminal_status"], "STRUCTURAL_FAILURE")
        self.assertEqual(transport.calls.count("P3V11_SYN_01_REPAIR_1"), 1)

    def test_missing_and_duplicate_handles_are_reported_together(self):
        _, draft = oracle_case(CASES[0][1], "SYN_01")
        bad = deepcopy(draft)
        bad["mentions"][0]["quote"] = "__absent__"
        bad["evidence"].append(dict(bad["evidence"][0]))
        transport = ScriptedTransport({
            "P3V11_SYN_01_PRIMARY": [("ok", draft_json(bad))],
            "P3V11_SYN_01_REPAIR_1": [("ok", valid_raw("SYN_01", CASES[0][1]))],
            "P3V11_SYN_02_PRIMARY": [("ok", valid_raw("SYN_02", CASES[1][1]))],
        })
        result = self.run_with(transport)
        codes = {item["code"] for item in
                 self.by_case(result)["SYN_01"]["primary"]["validation"]["blockers"]}
        self.assertIn("QUOTE_NOT_FOUND", codes)
        self.assertIn("DUPLICATE_HANDLE", codes)

    def test_canonical_failure_feedback_carries_issue_classes(self):
        _, draft = oracle_case(CASES[0][1], "SYN_01")
        bad = deepcopy(draft)
        bad["propositions"][0]["predicate"] = "Unregistered"
        transport = ScriptedTransport({
            "P3V11_SYN_01_PRIMARY": [("ok", draft_json(bad))],
            "P3V11_SYN_01_REPAIR_1": [("ok", draft_json(bad))],
            "P3V11_SYN_02_PRIMARY": [("ok", valid_raw("SYN_02", CASES[1][1]))],
        })
        result = self.run_with(transport)
        validation = self.by_case(result)["SYN_01"]["primary"]["validation"]
        self.assertEqual(validation["category"], "DRAFT_COMPILER_FAILURE")
        self.assertEqual(validation["blockers"][0]["code"], "CANONICAL_CONFORMANCE_FAILURE")
        self.assertIn("UNREGISTERED_PREDICATE",
                      {item["code"] for item in validation["canonical_issue_classes"]})
        self.assertIn("UNREGISTERED_PREDICATE",
                      transport.specs["P3V11_SYN_01_REPAIR_1"].user_prompt)

    def test_surface_form_advisory_is_reported_but_not_blocking(self):
        _, draft = oracle_case(CASES[0][1], "SYN_01")
        drifted = deepcopy(draft)
        drifted["mentions"][0]["surface_form"] = "a different name"
        transport = ScriptedTransport({
            "P3V11_SYN_01_PRIMARY": [("ok", draft_json(drifted))],
            "P3V11_SYN_02_PRIMARY": [("ok", valid_raw("SYN_02", CASES[1][1]))],
        })
        item = self.by_case(self.run_with(transport))["SYN_01"]
        self.assertEqual(item["terminal_status"], "STRUCTURAL_VALID")
        self.assertIn({"code": "SURFACE_FORM_DIFFERS_FROM_QUOTE",
                       "subject": drifted["mentions"][0]["handle"]},
                      item["primary"]["validation"]["advisories"])


class TransportAndResumeTests(RunnerHarness):
    def test_transport_failure_is_not_a_quality_failure(self):
        transport = ScriptedTransport({
            "P3V11_SYN_01_PRIMARY": [("fail", "SERVER_FAILURE")] * 3,
            "P3V11_SYN_02_PRIMARY": [("ok", valid_raw("SYN_02", CASES[1][1]))],
        })
        result = self.run_with(transport)
        item = self.by_case(result)["SYN_01"]
        self.assertEqual(item["terminal_status"], "NOT_EVALUATED_TRANSPORT")
        self.assertFalse(item["repair_used"])
        self.assertEqual(item["primary"]["transport"]["windows_used"], 3)
        self.assertEqual(item["primary"]["transport"]["deferred_count"], 2)
        self.assertEqual(transport.calls.count("P3V11_SYN_01_PRIMARY"), 3)

    def test_deferred_window_then_success_is_one_locked_response(self):
        transport = ScriptedTransport({
            "P3V11_SYN_01_PRIMARY": [("fail", "RATE_LIMIT"),
                                     ("ok", valid_raw("SYN_01", CASES[0][1]))],
            "P3V11_SYN_02_PRIMARY": [("ok", valid_raw("SYN_02", CASES[1][1]))],
        })
        item = self.by_case(self.run_with(transport))["SYN_01"]
        self.assertEqual(item["terminal_status"], "STRUCTURAL_VALID")
        self.assertEqual(item["primary"]["transport"]["success_lock_count"], 1)

    def test_rerun_is_idempotent_with_zero_new_provider_calls(self):
        script = {
            "P3V11_SYN_01_PRIMARY": [("ok", "{bad")],
            "P3V11_SYN_01_REPAIR_1": [("ok", valid_raw("SYN_01", CASES[0][1]))],
            "P3V11_SYN_02_PRIMARY": [("ok", valid_raw("SYN_02", CASES[1][1]))],
        }
        first = self.run_with(ScriptedTransport(script))
        second_transport = ScriptedTransport({})
        second = self.run_with(second_transport)
        self.assertEqual(second_transport.calls, [])
        self.assertEqual(first["prediction_set_sha256"], second["prediction_set_sha256"])
        self.assertEqual(first["accounting"], second["accounting"])

    def test_crash_mid_run_resumes_without_duplicate_success(self):
        crashing = ScriptedTransport({
            "P3V11_SYN_01_PRIMARY": [("ok", valid_raw("SYN_01", CASES[0][1]))],
            "P3V11_SYN_02_PRIMARY": [("crash",)],
        })
        with self.assertRaises(RuntimeError):
            self.run_with(crashing)
        resumed_transport = ScriptedTransport({})
        resumed = self.run_with(resumed_transport)
        self.assertEqual(resumed_transport.calls, [])
        statuses = {item["case_id"]: item["terminal_status"] for item in resumed["predictions"]}
        self.assertEqual(statuses, {"SYN_01": "STRUCTURAL_VALID",
                                    "SYN_02": "NOT_EVALUATED_TRANSPORT"})

    def test_token_accounting_and_operation_cap(self):
        transport = ScriptedTransport({
            "P3V11_SYN_01_PRIMARY": [("ok", valid_raw("SYN_01", CASES[0][1]),
                                      {"prompt_token_count": 7, "candidates_token_count": 3,
                                       "total_token_count": 10})],
            "P3V11_SYN_02_PRIMARY": [("ok", valid_raw("SYN_02", CASES[1][1]))],
        })
        # Worst case per job is 9 operations: 0+9 <= 9 starts SYN_01, 1+9 > 9 stops SYN_02.
        result = self.run_with(transport, max_provider_operations=9)
        self.assertEqual(result["run_status"],
                         "INCONCLUSIVE_INFRASTRUCTURE_PROVIDER_OPERATION_CAP")
        self.assertEqual(result["accounting"]["tokens"]["total_token_count"], 10)
        self.assertEqual(result["accounting"]["provider_operations"], 1)
        self.assertEqual(transport.calls, ["P3V11_SYN_01_PRIMARY"])

    def test_token_cap_stops_the_run(self):
        transport = ScriptedTransport({
            "P3V11_SYN_01_PRIMARY": [("ok", valid_raw("SYN_01", CASES[0][1]),
                                      {"total_token_count": 500})],
        })
        result = self.run_with(transport, max_total_tokens=400)
        self.assertEqual(result["run_status"], "INCONCLUSIVE_INFRASTRUCTURE_TOKEN_CAP")
        self.assertEqual(transport.calls, ["P3V11_SYN_01_PRIMARY"])

    def test_reported_model_version_drift_stops_the_run(self):
        transport = ScriptedTransport({
            "P3V11_SYN_01_PRIMARY": [("ok", valid_raw("SYN_01", CASES[0][1]),
                                      {"total_token_count": 1}, "version-a")],
            "P3V11_SYN_02_PRIMARY": [("ok", valid_raw("SYN_02", CASES[1][1]),
                                      {"total_token_count": 1}, "version-b")],
        })
        result = self.run_with(transport)
        self.assertEqual(
            result["run_status"],
            "INCONCLUSIVE_INFRASTRUCTURE_PROVIDER_REPORTED_MODEL_VERSION_CHANGED")


class AccessControlTests(RunnerHarness):
    def test_gold_and_holdout_output_paths_are_refused(self):
        for name in ("gold_outputs", "Holdout_run"):
            with self.subTest(name=name), self.assertRaises(runner.RunnerError):
                self.run_with(ScriptedTransport({}), artifact_root=self.root / name)

    def test_gold_member_in_input_archive_is_refused(self):
        other = self.root / "other"
        other.mkdir()
        archive, input_root, digest = write_dataset(
            other, CASES[:1], extra_members={"cases/SYN_01/gold_batch.json": b"{}"})
        with self.assertRaises(runner.RunnerError):
            runner.load_case_inputs(archive, input_root, digest)

    def test_sealed_archive_hashes_are_refused(self):
        with mock.patch.dict(runner.FORBIDDEN_ARCHIVE_SHA256, {self.archive_sha: "SEALED"}):
            with self.assertRaises(runner.RunnerError):
                runner.load_case_inputs(self.archive, self.input_root, self.archive_sha)

    def test_candidate_lock_must_match_current_definition(self):
        value = json.loads(self.lock.read_text())
        value["generation"]["temperature"] = 0.7
        changed = self.root / "changed_lock.json"
        changed.write_bytes(canonical_json_bytes(value))
        import hashlib
        with self.assertRaises(runner.RunnerError):
            runner.validate_candidate_lock(changed, hashlib.sha256(changed.read_bytes()).hexdigest())

    def test_live_mode_without_authorization_never_builds_a_transport(self):
        with mock.patch.object(runner, "_live_transport",
                               side_effect=AssertionError("live transport built")):
            code = runner.main([
                "--mode", "run-live", "--candidate-lock", str(self.lock),
                "--candidate-lock-sha256", self.lock_sha,
                "--input-archive", str(self.archive), "--input-root", str(self.input_root),
                "--input-archive-sha256", self.archive_sha,
            ])
        self.assertEqual(code, 2)

    def test_authorization_for_another_candidate_is_refused(self):
        record = {
            "authorization_id": "A", "research_task_id": "T", "dataset_id": "SYNTHETIC_P3_SET_V1",
            "input_archive_sha256": self.archive_sha, "case_ids": ["SYN_01", "SYN_02"],
            "candidate_definition_sha256": "0" * 64, "live_provider_calls_authorized": True,
            "max_provider_operations": 10, "max_total_tokens": 10,
            "approved_by": "nobody", "approved_at_utc": "2026-01-01T00:00:00Z",
        }
        path = self.root / "authorization.json"
        path.write_text(json.dumps(record))
        with self.assertRaises(runner.RunnerError):
            runner.load_authorization(path)
        record["candidate_definition_sha256"] = candidate_definition_sha256()
        path.write_text(json.dumps(record))
        self.assertEqual(runner.load_authorization(path).research_task_id, "T")

    def test_preflight_passes_offline(self):
        code = runner.main([
            "--mode", "preflight", "--candidate-lock", str(self.lock),
            "--candidate-lock-sha256", self.lock_sha,
            "--input-archive", str(self.archive), "--input-root", str(self.input_root),
            "--input-archive-sha256", self.archive_sha,
        ])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
