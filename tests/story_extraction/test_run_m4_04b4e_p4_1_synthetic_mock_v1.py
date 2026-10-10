"""Offline tests for the P4.1 synthetic mock harness (M4-04B4E).

SYNTHETIC_MOCK_ONLY_NOT_PROVIDER_EVIDENCE. Every run uses the injected fake transport, a
virtual clock, the invented sentence and hand-written drafts, in a temporary private
root. No provider, credential, dataset, gold or holdout is touched.
"""
import contextlib
import inspect
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import yaml

from tools.story_extraction import m4_04b4a_p4_output_contract_v1 as p4_contract
from tools.story_extraction import m4_04b4br_p4_protocol_v2 as protocol_v2
from tools.story_extraction import m4_04b4d_f1_structural_diagnostic_v3_1 as v31
from tools.story_extraction import m4_04b4d_structural_diagnostic_v3 as v3
from tools.story_extraction import m4_04b4e_p4_1_retention_metrics_v1 as retention
from tools.story_extraction import m4_04b4e_p4_1_runtime_protocol_candidate_v1 as protocol
from tools.story_extraction import run_m4_04b4e_p4_1_synthetic_mock_v1 as harness
from tools.story_extraction.durable_research_executor_v1 import (
    AtomicIntegrityJsonStore,
    CheckpointIntegrityError,
    JobState,
)


REPO_ROOT = harness.REPO_ROOT
LABEL = "SYNTHETIC_MOCK_ONLY_NOT_PROVIDER_EVIDENCE"
PREVIOUS_ACCEPTED_TOTAL = 1370
# Words of the invented sentence and of the hand-written drafts. None may reach a public artifact.
SEMANTIC_VALUES = ("Oren", "Lysa", "the mill", "barred the gate", "resentment", "did not greet")
_STATE = {}


def setUpModule():
    _STATE["directory"] = tempfile.mkdtemp(prefix="m4_04b4e_synthetic_mock_")
    _STATE["sweep"] = harness.run_all(Path(_STATE["directory"]) / "sweep")


def tearDownModule():
    shutil.rmtree(_STATE["directory"], ignore_errors=True)


def sweep():
    return _STATE["sweep"]


def scenario(scenario_id):
    return next(item for item in sweep()["scenarios"] if item["scenario_id"] == scenario_id)


def only_case(scenario_id):
    cases = scenario(scenario_id)["cases"]
    assert len(cases) == 1
    return cases[0]


def sweep_root(scenario_id):
    return Path(_STATE["directory"]) / "sweep" / scenario_id.lower()


def new_root(name):
    return Path(tempfile.mkdtemp(prefix="m4_04b4e_synthetic_mock_", dir=_STATE["directory"])) / name


def checkpoint(scenario_id, job):
    return AtomicIntegrityJsonStore().read(sweep_root(scenario_id) / "checkpoints" / "jobs" / f"{job}.json")


def private_result(scenario_id, case_id):
    return json.loads((sweep_root(scenario_id) / "case_results" / f"{case_id}.json").read_text(encoding="utf-8"))


def tree(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


class ScenarioOutcomeTests(unittest.TestCase):
    def test_all_twenty_required_simulations_ran_and_every_artifact_says_mock(self):
        result = sweep()
        self.assertEqual((21, True, 0, 0, 0, LABEL), (result["scenario_count"], result["required_simulations_covered"],
                                                     result["real_provider_operations"], result["model_calls"],
                                                     result["credentials_loaded"], result["evidence"]))
        self.assertEqual([
            "VALID_PRIMARY_RESPONSE", "INVALID_JSON_PRIMARY", "FULL_SCHEMA_INVALID_PRIMARY",
            "PROJECTION_VALID_BUT_FULL_SCHEMA_INVALID_PRIMARY", "COMPILER_INVALID_QUOTE_OCCURRENCE",
            "COMPILER_INVALID_ENTITY_KIND_REFERENCE", "COMPILER_INVALID_DERIVATION_CONCLUSION",
            "DUPLICATE_CONCRETE_PROPOSITION", "SUCCESSFUL_REPAIR_OF_SEVERAL_BLOCKERS", "BYTE_IDENTICAL_INEFFECTIVE_REPAIR",
            "REPAIR_THAT_CHANGES_THE_BLOCKER_BUT_STILL_FAILS", "TRANSPORT_RETRY_FOLLOWED_BY_SUCCESS",
            "TERMINAL_TRANSPORT_FAILURE", "INTERRUPTED_CHECKPOINT", "DUPLICATE_TERMINAL_JOB_ATTEMPT",
            "BUDGET_EXHAUSTION_UNDER_A_SYNTHETIC_LIMIT", "PACING_WINDOW_SATURATION", "EMPTY_BUT_COMPILER_VALID_OUTPUT",
            "REPAIR_THAT_REMOVES_OTHERWISE_SUPPORTED_RECORDS", "UNKNOWN_CANONICAL_ERROR_WITH_AN_INCOMPLETE_DIAGNOSTIC",
        ], [item["simulates"] for item in result["scenarios"]][:20])
        self.assertEqual(list(harness.REQUIRED_SIMULATIONS), [item["simulates"] for item in result["scenarios"]][:20])
        for item in result["scenarios"]:
            self.assertEqual((LABEL, protocol.PROTOCOL_SHA256, harness.FIXTURE_SET_SHA256, 0, LABEL),
                             (item["evidence"], item["protocol_sha256"], item["fixture_set_sha256"],
                              item["operations"]["real_provider_operations"], item["operations"]["evidence"]))
            manifest = json.loads((sweep_root(item["scenario_id"]) / f"{harness.RUN_MANIFEST_ID}.json")
                                  .read_text(encoding="utf-8"))
            self.assertEqual((LABEL, protocol.PROTOCOL_SHA256, f"MOCK_{item['scenario_id']}"),
                             (manifest["evidence"], manifest["protocol_sha256"], manifest["run_id"]))

    def test_terminal_classification_of_every_scenario(self):
        complete, valid, failure = harness.STATUS_COMPLETE, "STRUCTURAL_VALID", "STRUCTURAL_FAILURE"
        expected = {
            # scenario: (run status, terminal statuses, repair used, primary failure category, mock operations)
            "S01": (complete, [valid], False, None, 1),
            "S02": (complete, [valid], True, "JSON_PARSE_FAILURE", 2),
            "S03": (complete, [valid], True, "DRAFT_SCHEMA_FAILURE", 2),
            "S04": (complete, [valid], True, "DRAFT_SCHEMA_FAILURE", 2),
            "S05": (complete, [valid], True, "DRAFT_COMPILER_FAILURE", 2),
            "S06": (complete, [valid], True, "DRAFT_COMPILER_FAILURE", 2),
            "S07": (complete, [valid], True, "DRAFT_COMPILER_FAILURE", 2),
            "S08": (complete, [valid], True, "DRAFT_COMPILER_FAILURE", 2),
            "S09": (complete, [valid], True, "DRAFT_COMPILER_FAILURE", 2),
            "S10": (complete, [failure], True, "DRAFT_COMPILER_FAILURE", 2),
            "S11": (complete, [failure], True, "DRAFT_COMPILER_FAILURE", 2),
            "S12": (complete, [valid], False, None, 5),
            "S13": (complete, ["TRANSPORT_FAILURE"], False, None, 9),
            "S14": (harness.STATUS_INTERRUPTED, [], None, None, 1),
            "S15": (complete, [valid], False, None, 1),
            "S16": (harness.STATUS_BUDGET_EXHAUSTED, [], None, None, 2),
            "S17": (complete, [valid] * 4, False, None, 8),
            "S18": (complete, [valid], False, None, 1),
            "S19": (complete, [valid], True, "DRAFT_COMPILER_FAILURE", 2),
            "S20": (complete, [failure], False, "DRAFT_COMPILER_FAILURE", 1),
            "S21": (complete, [valid], True, "DRAFT_COMPILER_FAILURE", 2),
        }
        self.assertEqual(set(expected), {item["scenario_id"] for item in sweep()["scenarios"]})
        for scenario_id, (status, terminal, repair_used, category, operations) in expected.items():
            item = scenario(scenario_id)
            with self.subTest(scenario=scenario_id):
                self.assertEqual((status, terminal, operations),
                                 (item["run_status"], [case["terminal_status"] for case in item["cases"]],
                                  item["operations"]["mock_operations_started"]))
                for case in item["cases"]:
                    self.assertIn(case["terminal_status"], protocol.TERMINAL_STATUSES)
                    self.assertEqual(repair_used, case["repair_used"])
                    self.assertEqual(category, case["primary"]["structural_failure_category"])
                    self.assertLessEqual(case["durable_jobs"], 2)

    def test_parser_projection_full_schema_and_compiler_are_told_apart(self):
        expected = {
            # scenario: json parse, projection valid, full schema valid, compiler reached, compiler success
            "S01": (True, True, True, True, True),
            "S02": (False, None, None, False, None),
            "S03": (True, False, False, False, None),
            "S04": (True, True, False, False, None),
            "S05": (True, True, True, True, False),
            "S06": (True, True, True, True, False),
            "S18": (True, True, True, True, True),
        }
        for scenario_id, flags in expected.items():
            primary = only_case(scenario_id)["primary"]
            with self.subTest(scenario=scenario_id):
                self.assertEqual(flags, tuple(primary[name] for name in (
                    "json_parse", "provider_projection_valid", "full_schema_valid", "compiler_reached",
                    "compiler_success")))
        # The projection is measured and never decides: S04 passes it and is still rejected and repaired.
        self.assertEqual(("DRAFT_SCHEMA_FAILURE", False), (only_case("S04")["primary"]["structural_failure_category"],
                                                           only_case("S04")["primary"]["structurally_valid"]))


class DiagnosticIntegrationTests(unittest.TestCase):
    def test_every_rejected_primary_has_a_safe_diagnostic_v3_1_built_from_the_exact_response(self):
        seen = 0
        for item in sweep()["scenarios"]:
            for case in item["cases"]:
                if case["primary"]["structurally_valid"] is not False:
                    continue
                seen += 1
                case_id, root = case["case_id"], sweep_root(item["scenario_id"])
                raw = (root / "raw_primary" / f"{case_id}.txt").read_text(encoding="utf-8")
                stored = json.loads((root / "diagnostics" / f"{case_id}_primary.json").read_text(encoding="utf-8"))
                context = harness.synthetic_case(case_id).compiler_context
                rebuilt = v31.structural_diagnostic_v3_1(raw, context)
                with self.subTest(case=case_id):
                    self.assertEqual(v31.canonical_json_bytes(rebuilt), v31.canonical_json_bytes(stored))
                    self.assertEqual((v31.DIAGNOSTIC_ID, v31.DIAGNOSTIC_FORMAT), (rebuilt["diagnostic"], rebuilt["format"]))
                    parsed, draft = retention.parse_response(raw)
                    v31.assert_diagnostic_safe(rebuilt, v31.build_identity_index(draft if parsed else None, context))
                    self.assertEqual(case["primary"]["structural_failure_category"], rebuilt["category"])
                    self.assertFalse(rebuilt["complete"])
                    self.assertEqual(rebuilt["finding_count"], case["primary"]["diagnostic"]["finding_count"])
                    self.assertTrue(case["primary"]["diagnostic_safe"])
        self.assertEqual(13, seen)

    def test_the_repair_request_is_the_one_the_protocol_builds_from_the_locked_primary_and_its_diagnostic(self):
        checked = 0
        for item in sweep()["scenarios"]:
            for case in item["cases"]:
                if not case["repair_used"]:
                    continue
                checked += 1
                case_id, root = case["case_id"], sweep_root(item["scenario_id"])
                synthetic = harness.synthetic_case(case_id)
                raw = (root / "raw_primary" / f"{case_id}.txt").read_text(encoding="utf-8")
                diagnostic = json.loads((root / "diagnostics" / f"{case_id}_primary.json").read_text(encoding="utf-8"))
                policy = case["partially_described_policy_applied"]
                spec = protocol.build_repair_spec(case_id, synthetic.prepared_input, raw, diagnostic,
                                                  synthetic.compiler_context, partially_described_policy=policy)
                record = checkpoint(item["scenario_id"], spec.job_id)
                primary = protocol.build_primary_spec(case_id, synthetic.prepared_input)
                with self.subTest(case=case_id):
                    self.assertEqual(spec.request_fingerprint, record["request_fingerprint"])
                    self.assertEqual(primary.request_fingerprint,
                                     checkpoint(item["scenario_id"], primary.job_id)["request_fingerprint"])
                    self.assertIn(raw, spec.user_prompt)
                    self.assertIn(p4_contract.canonical_json(diagnostic), spec.user_prompt)
                    self.assertEqual(protocol.DECISION_REPAIR, case["repair_decision"])
                    self.assertTrue(record["protocol_id"].startswith(protocol.executor_protocol_id()))
        self.assertEqual(12, checked)

    def test_the_host_never_edits_a_draft_or_chooses_an_occurrence(self):
        for item in sweep()["scenarios"]:
            root = sweep_root(item["scenario_id"])
            script = harness.scenario_script(harness.scenario_by_id(item["scenario_id"]))
            for path in sorted((root / "drafts").glob("*.json")):
                case_id, phase = path.stem.rsplit("_", 1) if path.stem.endswith("_primary") else (
                    path.stem[: -len("_repair_1")], "repair_1")
                directory = "raw_primary" if phase == "primary" else "raw_repair"
                raw = (root / directory / f"{case_id}.txt").read_text(encoding="utf-8")
                job = (protocol.PRIMARY_JOB_ID if phase == "primary" else protocol.REPAIR_JOB_ID).format(CASE_ID=case_id)
                with self.subTest(draft=path.name):
                    self.assertEqual(json.loads(raw), json.loads(path.read_text(encoding="utf-8")))
                    self.assertEqual(script[job].response, raw)
        primary = json.loads((sweep_root("S10") / "drafts" / "SYN_10_primary.json").read_text(encoding="utf-8"))
        repair = json.loads((sweep_root("S10") / "drafts" / "SYN_10_repair_1.json").read_text(encoding="utf-8"))
        for draft in (primary, repair):
            self.assertNotIn("occurrence", next(m for m in draft["mentions"] if m["handle"] == "M1"))
        self.assertEqual("STRUCTURAL_FAILURE", only_case("S10")["terminal_status"])
        source = Path(harness.__file__).read_text(encoding="utf-8")
        runtime = source.split("# Response evaluation", 1)[1]
        for forbidden in ('["occurrence"]', '["quote"]', '["kind"] =', '["rule_id"] =', "draft["):
            self.assertNotIn(forbidden, runtime)

    def test_the_compiler_verdict_is_final_and_a_disagreeing_or_unsafe_diagnostic_changes_nothing(self):
        real = v31.structural_diagnostic_v3_1

        def claims_rejection(raw, context):
            return {**real(harness.mock_response("AMBIGUOUS_QUOTE"), context)}

        with mock.patch.object(v31, "structural_diagnostic_v3_1", side_effect=claims_rejection):
            with self.assertRaisesRegex(harness.MockHarnessError, "disagrees with the compiler"):
                harness.run_scenario("S01", new_root("s01"))

        def unsafe(raw, context):
            raise v31.DiagnosticV31Error("simulated")

        with mock.patch.object(v31, "structural_diagnostic_v3_1", side_effect=unsafe):
            accepted = harness.run_scenario("S01", new_root("s01"))["cases"][0]
            rejected = harness.run_scenario("S05", new_root("s05"))["cases"][0]
        self.assertEqual(("STRUCTURAL_VALID", False), (accepted["terminal_status"], accepted["primary"]["diagnostic_safe"]))
        self.assertEqual(("STRUCTURAL_FAILURE", False, protocol.ACTION_INVALID, protocol.DECISION_NO_REPAIR,
                          protocol.ACTION_INVALID),
                         (rejected["terminal_status"], rejected["repair_used"], rejected["repair_actionability"]["class"],
                          rejected["repair_decision"], rejected["repair_skipped_reason"]))

    def test_the_superseded_diagnostics_are_never_called(self):
        def forbidden(*_, **__):
            raise AssertionError("a superseded diagnostic was called")

        with mock.patch.object(v3, "structural_diagnostic_v3", side_effect=forbidden), \
                mock.patch.object(p4_contract, "structural_diagnostic_v2", side_effect=forbidden):
            result = harness.run_scenario("S09", new_root("s09"))
        self.assertEqual(scenario("S09")["summary_sha256"], result["summary_sha256"])
        for module in (harness, protocol, retention):
            source = Path(module.__file__).read_text(encoding="utf-8")
            self.assertNotIn("structural_diagnostic_v3(", source)
            self.assertNotIn("structural_diagnostic_v2(", source)

    def test_repair_actionability_decides_whether_the_single_repair_is_spent(self):
        for scenario_id in ("S02", "S03", "S04", "S05", "S06", "S07", "S08", "S09", "S10", "S11", "S19"):
            case = only_case(scenario_id)
            with self.subTest(scenario=scenario_id):
                self.assertEqual((protocol.ACTION_ACTIONABLE, [], protocol.DECISION_REPAIR, None, True),
                                 (case["repair_actionability"]["class"], case["repair_actionability"]["reasons"],
                                  case["repair_decision"], case["repair_skipped_reason"], case["repair_used"]))
                self.assertFalse(case["primary"]["diagnostic"]["complete"])
        refused, allowed = only_case("S20"), only_case("S21")
        for case in (refused, allowed):
            self.assertEqual((protocol.ACTION_PARTIAL, [protocol.REASON_UNATTRIBUTED]),
                             (case["repair_actionability"]["class"], case["repair_actionability"]["reasons"]))
            self.assertFalse(case["primary"]["diagnostic"]["completeness"]["observed_blockers_attributed"])
            self.assertEqual({"CANONICAL_CONFORMANCE_FAILURE": 1}, case["primary"]["diagnostic"]["findings_by_code"])
        self.assertEqual((protocol.PARTIAL_POLICY_REFUSE, protocol.DECISION_NO_REPAIR, False, "STRUCTURAL_FAILURE",
                          harness.SKIP_POLICY_UNRESOLVED, 1),
                         (refused["partially_described_policy_applied"], refused["repair_decision"],
                          refused["repair_used"], refused["terminal_status"], refused["repair_skipped_reason"],
                          refused["durable_jobs"]))
        self.assertEqual((protocol.PARTIAL_POLICY_ALLOW, protocol.DECISION_REPAIR, True, "STRUCTURAL_VALID", 2),
                         (allowed["partially_described_policy_applied"], allowed["repair_decision"],
                          allowed["repair_used"], allowed["terminal_status"], allowed["durable_jobs"]))
        for case in (only_case("S01"), only_case("S18"), only_case("S13")):
            self.assertEqual((None, None, False), (case["repair_actionability"], case["repair_decision"], case["repair_used"]))


class ExactlyOnceAndDurabilityTests(unittest.TestCase):
    def test_first_success_is_locked_and_the_raw_response_is_immutable(self):
        for item in sweep()["scenarios"]:
            root = sweep_root(item["scenario_id"])
            for case in item["cases"]:
                result = private_result(item["scenario_id"], case["case_id"])
                for phase, directory in (("primary", "raw_primary"), ("repair", "raw_repair")):
                    attempt = result[phase]
                    if not attempt or not attempt["provider_success"]:
                        continue
                    record = checkpoint(item["scenario_id"], attempt["job_id"])
                    raw = (root / directory / f"{case['case_id']}.txt").read_bytes()
                    with self.subTest(job=attempt["job_id"]):
                        self.assertEqual(JobState.SUCCEEDED_LOCKED.value, record["state"])
                        self.assertEqual(protocol_v2.sha256_bytes(raw), record["first_success"]["response_sha256"])
                        self.assertEqual(record["first_success"]["response_sha256"], attempt["raw_response_sha256"])
                        self.assertEqual(raw.decode("utf-8"), record["first_success"]["raw_response"])
                        self.assertEqual(1, attempt["success_lock_count"])
                        self.assertEqual(attempt["request_fingerprint"], record["request_fingerprint"])
        self.assertEqual(sorted(path.name for path in (sweep_root("S05") / "checkpoints" / "jobs").glob("*.json")),
                         ["M4B4E_P41_SYN_05_PRIMARY.json", "M4B4E_P41_SYN_05_REPAIR_1.json"])

    def test_a_terminal_case_and_a_locked_job_are_never_executed_again(self):
        follow_up = scenario("S15")["follow_up"]
        self.assertEqual({"kind": harness.FOLLOW_UP_REEXECUTE, "terminal_case_executed_again": "REFUSED",
                          "locked_job_returned_without_a_transport_call": True, "locked_response_unchanged": True,
                          "success_lock_count": 1, "a_new_run_on_existing_state": "REFUSED"}, follow_up)
        self.assertEqual(1, scenario("S15")["operations"]["mock_operations_started"])
        root = new_root("s10")
        first = harness.run_scenario("S10", root)
        before = tree(root)
        with self.assertRaises(harness.PriorExecutionState):
            harness.run_scenario("S10", root)
        with self.assertRaises(harness.PriorExecutionState):
            harness.MockRun(harness.scenario_by_id("S10"), root)
        self.assertEqual(before, tree(root))
        resumed = harness.MockRun(harness.scenario_by_id("S10"), root, resume=True)
        outcome = resumed.execute()
        self.assertEqual((harness.STATUS_COMPLETE, [], 0, 2),
                         (outcome["run_status"], resumed.results, resumed.transport.operations,
                          outcome["operations"]["mock_operations_started"]))
        with self.assertRaisesRegex(harness.MockHarnessError, "never executed again"):
            resumed.execute_case(harness.scenario_by_id("S10").cases[0])
        self.assertEqual(before, tree(root))
        self.assertEqual("STRUCTURAL_FAILURE", first["cases"][0]["terminal_status"])

    def test_there_is_no_second_repair_and_no_retry_of_a_structurally_invalid_response(self):
        for scenario_id in ("S10", "S11"):
            case = only_case(scenario_id)
            jobs = sorted(path.stem for path in (sweep_root(scenario_id) / "checkpoints" / "jobs").glob("*.json"))
            with self.subTest(scenario=scenario_id):
                self.assertEqual(("STRUCTURAL_FAILURE", 2, 2, True), (case["terminal_status"], case["durable_jobs"],
                                                                     len(jobs), case["repair_used"]))
                self.assertEqual((1, 1), (case["primary"]["windows_used"], case["repair"]["windows_used"]))
                self.assertFalse(any("REPAIR_2" in job for job in jobs))
        self.assertTrue(only_case("S10")["retention"]["effect"]["identical_bytes"])
        self.assertEqual(1, protocol.MAX_STRUCTURAL_REPAIRS_PER_CASE)
        # A valid response is never retried either: one window, one lock, no repair.
        self.assertEqual((1, 1, False), (only_case("S01")["primary"]["windows_used"],
                                         only_case("S01")["primary"]["success_lock_count"], only_case("S01")["repair_used"]))

    def test_transport_retry_then_success_and_terminal_transport_failure(self):
        retried = only_case("S12")["primary"]
        self.assertEqual((True, 2, 5, 1, "STRUCTURAL_VALID"),
                         (retried["provider_success"], retried["windows_used"], retried["checkpointed_operations"],
                          retried["deferred_count"], only_case("S12")["terminal_status"]))
        record = checkpoint("S12", "M4B4E_P41_SYN_12_PRIMARY")
        self.assertEqual([3, 2], record["provider_attempts_per_window"])
        self.assertEqual(["TRANSPORT_FAILURE", "SUCCESS_LOCKED"], [window["outcome"] for window in record["windows"]])
        failed = only_case("S13")
        self.assertEqual(("TRANSPORT_FAILURE", "PRIMARY", False, 3, 9, 2, "WINDOW_LIMIT_EXHAUSTED", False),
                         (failed["terminal_status"], failed["terminal_phase"], failed["primary"]["provider_success"],
                          failed["primary"]["windows_used"], failed["primary"]["checkpointed_operations"],
                          failed["primary"]["deferred_count"], failed["primary"]["transport_terminal_reason"],
                          failed["repair_used"]))
        self.assertEqual(JobState.TERMINAL_FAILED.value, checkpoint("S13", "M4B4E_P41_SYN_13_PRIMARY")["state"])
        self.assertFalse((sweep_root("S13") / "raw_primary" / "SYN_13.txt").exists())
        self.assertIsNone(failed["primary"]["json_parse"])

    def test_an_interrupted_window_fails_closed_and_is_never_retried(self):
        item = scenario("S14")
        self.assertEqual((harness.STATUS_INTERRUPTED, [], "SYN_14"), (item["run_status"], item["cases"], item["stopped_at_case"]))
        self.assertEqual({"kind": harness.FOLLOW_UP_RESTART, "process_died_inside_a_window": True,
                          "a_new_run_on_existing_state": "REFUSED", "resume_with_a_larger_budget": "REFUSED",
                          "resume_run_status": harness.STATUS_INTERRUPTED, "operations_started_by_the_resume": 0,
                          "operations_persisted_across_restart": 1, "cases_made_terminal_by_the_resume": 0},
                         item["follow_up"])
        record = checkpoint("S14", "M4B4E_P41_SYN_14_PRIMARY")
        self.assertEqual((JobState.IN_FLIGHT.value, 1, [0], None),
                         (record["state"], record["window_count"], record["provider_attempts_per_window"],
                          record["first_success"]))
        self.assertFalse((sweep_root("S14") / "case_results" / "SYN_14.json").exists())
        resumed = harness.MockRun(harness.scenario_by_id("S14"), sweep_root("S14"), resume=True)
        with self.assertRaisesRegex(CheckpointIntegrityError, "in-flight"):
            resumed.execute_case(harness.scenario_by_id("S14").cases[0])
        self.assertEqual(0, resumed.transport.operations)

    def test_the_synthetic_budget_is_hard_persistent_and_cannot_be_reset(self):
        item = scenario("S16")
        self.assertEqual((harness.STATUS_BUDGET_EXHAUSTED, [], 2), (item["run_status"], item["cases"],
                                                                    item["operations"]["mock_operations_started"]))
        budget = item["operations"]["synthetic_budget"]
        self.assertEqual((2, 2, 0, True), (budget["synthetic_maximum_operations"], budget["consumed"], budget["remaining"],
                                           budget["within_budget"]))
        self.assertGreaterEqual(budget["refusals"], 1)
        self.assertEqual({"kind": harness.FOLLOW_UP_RESTART, "a_new_run_on_existing_state": "REFUSED",
                          "resume_with_a_larger_budget": "REFUSED",
                          "resume_run_status": harness.STATUS_BUDGET_EXHAUSTED, "operations_started_by_the_resume": 0,
                          "operations_persisted_across_restart": 2, "cases_made_terminal_by_the_resume": 0},
                         item["follow_up"])
        identity = json.loads((sweep_root("S16") / "checkpoints" / "synthetic_operation_budget.json").read_text("utf-8"))
        self.assertEqual((LABEL, 2, "REQUIRES_ORCHESTRATOR_AUTHORIZATION", protocol.PROTOCOL_SHA256),
                         (identity["evidence"], identity["synthetic_maximum_operations"],
                          identity["live_operation_budget"], identity["protocol_sha256"]))
        for maximum in (1, 3, 30):
            with self.assertRaises(CheckpointIntegrityError):
                harness.MockRun(harness.scenario_by_id("S16"), sweep_root("S16"), resume=True, synthetic_budget=maximum)
        again = harness.MockRun(harness.scenario_by_id("S16"), sweep_root("S16"), resume=True)
        self.assertEqual((0, 2), (again.budget.remaining(), again.budget.consumed()))
        with self.assertRaises(harness.SyntheticBudgetExhausted):
            again.budget.acquire()
        self.assertEqual(2, again.budget.consumed())
        for maximum in (0, -1, 65, 2.0, True, None):
            with self.assertRaises(harness.MockHarnessError):
                harness.SyntheticOperationBudget(again.pacer, sweep_root("S16") / "x.json", run_id="X", maximum=maximum)

    def test_operation_accounting_is_the_persisted_pacer_count(self):
        """The pacer counts every operation that started; a window that ended abnormally records none of its own."""
        for scenario_id, started, checkpointed in (("S14", 1, 0), ("S16", 2, 0)):
            job = f"M4B4E_P41_SYN_{scenario_id[1:]}_PRIMARY"
            record = checkpoint(scenario_id, job)
            pacing = AtomicIntegrityJsonStore().read(sweep_root(scenario_id) / "checkpoints" / "global_pacing.json")
            with self.subTest(scenario=scenario_id):
                self.assertEqual((started, checkpointed), (pacing["total_reservations"], record["total_provider_operations"]))
                self.assertEqual(started, scenario(scenario_id)["operations"]["mock_operations_started"])
        self.assertEqual((JobState.TERMINAL_FAILED.value, "UNCAUGHT_EXCEPTION"),
                         (checkpoint("S16", "M4B4E_P41_SYN_16_PRIMARY")["state"],
                          checkpoint("S16", "M4B4E_P41_SYN_16_PRIMARY")["transitions"][-1]["reason"]))
        for item in sweep()["scenarios"]:
            if item["scenario_id"] in ("S14", "S16"):
                continue
            with self.subTest(scenario=item["scenario_id"]):
                self.assertEqual(item["operations"]["mock_operations_started"],
                                 sum(case["checkpointed_operations"] for case in item["cases"]))
                self.assertEqual(item["operations"]["mock_operations_started"],
                                 item["operations"]["synthetic_budget"]["consumed"])
                self.assertTrue(item["operations"]["synthetic_budget"]["within_budget"])

    def test_pacing_is_persistent_and_saturates_at_the_proposed_window(self):
        operations = scenario("S17")["operations"]
        self.assertEqual((8, 6, 60.0, 6, "PASS", True),
                         (operations["mock_operations_started"], operations["pacing_max_operations"],
                          operations["pacing_rolling_window_seconds"], operations["max_rolling_operations_observed"],
                          operations["pacing_invariant"], operations["restart_persistent"]))
        self.assertGreaterEqual(operations["pacing_waits"], 1)
        for item in sweep()["scenarios"]:
            self.assertLessEqual(item["operations"]["max_rolling_operations_observed"], 6)
            self.assertEqual("PASS", item["operations"]["pacing_invariant"])
        self.assertEqual(0, scenario("S05")["operations"]["pacing_waits"])
        pacing = AtomicIntegrityJsonStore().read(sweep_root("S17") / "checkpoints" / "global_pacing.json")
        self.assertEqual((6, 60.0, 8), (pacing["max_operations"], pacing["window_seconds"], pacing["total_reservations"]))
        resumed = harness.MockRun(harness.scenario_by_id("S17"), sweep_root("S17"), resume=True)
        self.assertEqual(8, resumed.operations()["mock_operations_started"])
        self.assertGreater(resumed.clock.now(), harness.VIRTUAL_EPOCH)

    def test_restart_rejects_state_that_is_not_its_own(self):
        root = new_root("s05")
        harness.run_scenario("S05", root)
        with self.assertRaises(harness.PriorExecutionState):
            harness.MockRun(harness.scenario_by_id("S06"), root, resume=True)
        manifest = root / f"{harness.RUN_MANIFEST_ID}.json"
        original = manifest.read_bytes()
        manifest.write_bytes(original.replace(b"MOCK_S05", b"MOCK_S99"))
        with self.assertRaises(harness.PriorExecutionState):
            harness.MockRun(harness.scenario_by_id("S05"), root, resume=True)
        manifest.write_bytes(original)
        harness.MockRun(harness.scenario_by_id("S05"), root, resume=True)
        with self.assertRaises(harness.PriorExecutionState):
            harness.MockRun(harness.scenario_by_id("S05"), new_root("empty"), resume=True)
        raw = root / "raw_primary" / "SYN_05.txt"
        with self.assertRaisesRegex(harness.MockHarnessError, "Immutable private artifact differs"):
            harness._write_once(raw, raw.read_bytes() + b" ")
        job = root / "checkpoints" / "jobs" / "M4B4E_P41_SYN_05_PRIMARY.json"
        job.write_bytes(job.read_bytes().replace(b"SUCCEEDED_LOCKED", b"PENDING"))
        tampered = harness.MockRun(harness.scenario_by_id("S05"), root, resume=True)
        spec = protocol.build_primary_spec("SYN_05", harness.synthetic_case("SYN_05").prepared_input)
        with self.assertRaises(CheckpointIntegrityError):
            tampered.run_job(spec)

    def test_a_changed_protocol_or_fixture_stops_a_run_before_it_starts(self):
        with mock.patch.object(harness, "FIXTURE_SET_SHA256", "0" * 64):
            with self.assertRaisesRegex(harness.MockHarnessError, "fixture"):
                harness.run_scenario("S01", new_root("s01"))
        with mock.patch.object(harness, "SYNTHETIC_TEXT", "Another invented sentence about Oren."):
            with self.assertRaises(harness.MockHarnessError):
                harness.run_scenario("S01", new_root("s01"))
        with mock.patch.object(protocol, "MODEL", "another-model"):
            with self.assertRaisesRegex(harness.MockHarnessError, "protocol candidate"):
                harness.run_scenario("S01", new_root("s01"))
        with mock.patch.dict(protocol.BOUND_FILES, {v31.DIAGNOSTIC_PATH: "0" * 64}):
            with self.assertRaises(harness.MockHarnessError):
                harness.run_scenario("S01", new_root("s01"))
        root = new_root("s05")
        run = harness.MockRun(harness.scenario_by_id("S05"), root)
        with mock.patch.dict(protocol.BOUND_FILES, {v31.DIAGNOSTIC_PATH: "0" * 64}):
            with self.assertRaises(CheckpointIntegrityError):
                run.guard()
            outcome = run.execute()
        self.assertEqual((harness.STATUS_FAIL_CLOSED, 0), (outcome["run_status"], run.transport.operations))
        self.assertEqual([], run._in_flight_jobs())


class RetentionAndAntiVacuityTests(unittest.TestCase):
    def test_an_empty_draft_is_structurally_valid_and_flagged(self):
        case = only_case("S18")
        self.assertEqual(("STRUCTURAL_VALID", True, 0, [retention.WARNING_EMPTY_OUTPUT], False),
                         (case["terminal_status"], case["primary"]["empty_output"], case["primary"]["total_records"],
                          case["warnings"], case["repair_used"]))
        self.assertEqual({name: 0 for name in retention.COLLECTIONS}, case["primary"]["record_counts"])
        self.assertEqual((False, 26), (only_case("S01")["primary"]["empty_output"], only_case("S01")["primary"]["total_records"]))
        self.assertEqual({"evidence": 4, "mentions": 3, "entities": 3, "events": 1, "anchors": 1, "propositions": 7,
                          "assertions": 7}, only_case("S01")["primary"]["record_counts"])
        self.assertEqual([], only_case("S01")["warnings"])

    def test_a_repair_that_deletes_records_is_valid_and_visibly_smaller(self):
        case = only_case("S19")
        effect, comparison = case["retention"]["effect"], case["retention"]["comparison"]
        self.assertEqual(("STRUCTURAL_VALID", True, True, True, 1, 0, 1),
                         (case["terminal_status"], effect["structural_validity_increased"],
                          effect["structural_validity_increased_while_record_count_decreased"],
                          effect["all_primary_findings_cleared"], effect["primary_findings"],
                          effect["cleared_with_the_record_kept"], effect["cleared_with_the_record_removed"]))
        self.assertEqual({"NAMED_BY_A_PRIMARY_FINDING": 1, "DEPENDS_ON_A_NAMED_RECORD": 2,
                          "NOT_EXPLAINED_BY_ANY_FINDING": 7}, effect["removed_records_by_explanation"])
        self.assertEqual((26, 16, -10, 16, 10, 0), tuple(comparison["totals"][name] for name in (
            "primary_records", "repair_records", "count_difference", "retained", "removed", "added")))
        self.assertEqual({"evidence": -1, "mentions": -2, "entities": -1, "events": 0, "anchors": 0, "propositions": -3,
                          "assertions": -3},
                         {name: item["count_difference"] for name, item in comparison["by_collection"].items()})
        self.assertEqual(sorted([retention.WARNING_CLEARED_BY_REMOVAL, retention.WARNING_UNEXPLAINED_REMOVAL,
                                 retention.WARNING_VALID_WITH_FEWER_RECORDS]), case["warnings"])
        private = private_result("S19", "SYN_19")["retention"]
        self.assertEqual(["M1"], private["removals"]["NAMED_BY_A_PRIMARY_FINDING"])
        self.assertEqual(["A1", "PROP1"], private["removals"]["DEPENDS_ON_A_NAMED_RECORD"])
        self.assertEqual(["M1", "M3"], private["comparison"]["by_collection"]["mentions"]["removed_handles"])

    def test_a_corrected_draft_and_a_deleting_draft_are_told_apart_structurally(self):
        corrected, deleted = only_case("S05")["retention"], only_case("S19")["retention"]
        self.assertEqual((1, 0, 0, False), (corrected["effect"]["cleared_with_the_record_kept"],
                                            corrected["effect"]["cleared_with_the_record_removed"],
                                            corrected["comparison"]["totals"]["removed"],
                                            corrected["comparison"]["record_count_decreased"]))
        self.assertEqual((0, 1, 10, True), (deleted["effect"]["cleared_with_the_record_kept"],
                                            deleted["effect"]["cleared_with_the_record_removed"],
                                            deleted["comparison"]["totals"]["removed"],
                                            deleted["comparison"]["record_count_decreased"]))
        self.assertEqual((25, 1), (corrected["comparison"]["totals"]["unchanged"],
                                   corrected["comparison"]["totals"]["changed_in_place"]))
        self.assertEqual([retention.WARNING_CONTENT_CHANGED_COUNTS_SAME], only_case("S05")["warnings"])
        # Both ended STRUCTURAL_VALID. Structural validity alone does not separate them.
        self.assertEqual(only_case("S05")["terminal_status"], only_case("S19")["terminal_status"])

    def test_removing_a_duplicate_is_a_removal_that_a_finding_explains(self):
        effect = only_case("S08")["retention"]["effect"]
        self.assertEqual(({"NAMED_BY_A_PRIMARY_FINDING": 1, "DEPENDS_ON_A_NAMED_RECORD": 0,
                           "NOT_EXPLAINED_BY_ANY_FINDING": 0}, 1, True),
                         (effect["removed_records_by_explanation"], effect["cleared_with_the_record_removed"],
                          effect["structural_validity_increased_while_record_count_decreased"]))
        self.assertNotIn(retention.WARNING_UNEXPLAINED_REMOVAL, only_case("S08")["warnings"])
        self.assertIn(retention.WARNING_VALID_WITH_FEWER_RECORDS, only_case("S08")["warnings"])
        self.assertEqual(-1, only_case("S08")["retention"]["comparison"]["by_collection"]["propositions"]["count_difference"])

    def test_identical_repairs_changed_blockers_and_unnamed_changes_are_reported(self):
        identical = only_case("S10")["retention"]
        self.assertEqual((True, 0, 1, 0, False, [retention.WARNING_IDENTICAL]),
                         (identical["effect"]["identical_bytes"], identical["effect"]["primary_findings_cleared"],
                          identical["effect"]["primary_findings_remaining"], identical["effect"]["new_findings"],
                          identical["effect"]["structural_validity_increased"], only_case("S10")["warnings"]))
        self.assertEqual(26, identical["comparison"]["totals"]["unchanged"])
        changed = only_case("S11")["retention"]["effect"]
        self.assertEqual((True, True, 2, False, 1),
                         (changed["all_primary_findings_cleared"], changed["new_findings_appeared"], changed["new_findings"],
                          changed["structural_validity_increased"], changed["changed_records_not_named_by_a_finding"]))
        self.assertIn(retention.WARNING_UNEXPLAINED_CHANGE, only_case("S11")["warnings"])
        self.assertEqual(0, only_case("S06")["retention"]["effect"]["changed_records_not_named_by_a_finding"])
        several = only_case("S09")["retention"]["effect"]
        self.assertEqual((3, 3, 2, 1), (several["primary_findings"], several["primary_findings_cleared"],
                                        several["cleared_with_the_record_kept"], several["cleared_with_the_record_removed"]))
        self.assertEqual([retention.WARNING_NOT_COMPARABLE], only_case("S02")["warnings"])

    def test_metrics_are_warnings_without_a_threshold_and_never_change_an_outcome(self):
        text = json.dumps(sweep())
        for forbidden in ("threshold_passed", "retention_score", "retention_ratio", "quality_score", "semantic_error"):
            self.assertNotIn(forbidden, text)
        self.assertEqual("NONE_DEFINED", protocol.build_protocol()["result"]["acceptance_threshold"])
        for item in sweep()["scenarios"]:
            for case in item["cases"]:
                final = case["repair"] if case["repair_used"] and case["repair"]["provider_success"] else case["primary"]
                if case["terminal_status"] != "TRANSPORT_FAILURE":
                    self.assertEqual(case["terminal_status"] == "STRUCTURAL_VALID", final["structurally_valid"])
        self.assertEqual("STRUCTURAL_VALID", only_case("S18")["terminal_status"])
        self.assertEqual(json.loads((sweep_root("S18") / "raw_primary" / "SYN_18.txt").read_text("utf-8")),
                         json.loads(harness.mock_response("EMPTY")))


class ReproducibilityTests(unittest.TestCase):
    def test_a_second_run_reproduces_every_private_file_byte_for_byte(self):
        for scenario_id in ("S05", "S12", "S19"):
            root = new_root(scenario_id.lower())
            again = harness.run_scenario(scenario_id, root)
            with self.subTest(scenario=scenario_id):
                self.assertEqual(scenario(scenario_id), again)
                self.assertEqual(tree(sweep_root(scenario_id)), tree(root))
                self.assertEqual(again["summary_sha256"], json.loads(
                    (root / "summaries" / f"{scenario_id}.json").read_text(encoding="utf-8"))["summary_sha256"])
        text = json.dumps(sweep())
        self.assertNotIn(_STATE["directory"].replace("\\", "/"), text.replace("\\\\", "/"))
        self.assertNotIn("2026", (sweep_root("S05") / "checkpoints" / "jobs" / "M4B4E_P41_SYN_05_PRIMARY.json").read_text("utf-8"))

    def test_summaries_are_the_same_in_fresh_processes_with_other_hash_seeds(self):
        script = (
            "import json, tempfile\n"
            "from pathlib import Path\n"
            "from tools.story_extraction import run_m4_04b4e_p4_1_synthetic_mock_v1 as r\n"
            "with tempfile.TemporaryDirectory(prefix='m4_04b4e_synthetic_mock_') as d:\n"
            "    print(json.dumps({s: r.run_scenario(s, Path(d) / s.lower())['summary_sha256']"
            " for s in ('S09', 'S16', 'S17', 'S19', 'S20')}))\n"
        )
        expected = {name: scenario(name)["summary_sha256"] for name in ("S09", "S16", "S17", "S19", "S20")}
        for seed in ("0", "424242"):
            environment = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(REPO_ROOT),
                           "PYTHONDONTWRITEBYTECODE": "1"}
            done = subprocess.run([sys.executable, "-c", script], cwd=REPO_ROOT, env=environment, capture_output=True,
                                  text=True, timeout=600)
            self.assertEqual(0, done.returncode, done.stderr[-2000:])
            self.assertEqual(expected, json.loads(done.stdout.strip().splitlines()[-1]))

    def test_fixtures_are_pinned_and_invented(self):
        self.assertEqual(harness.FIXTURE_SET_SHA256, harness.fixture_set_sha256())
        case = harness.synthetic_case("SYN_X")
        self.assertEqual([harness.SYNTHETIC_TEXT], [passage["text"] for passage in case.prepared_input["passages"]])
        self.assertEqual(("M4_04B4E_P4_1_MOCK", "P41MOCK_SYN_X"), (case.compiler_context.process_id, case.compiler_context.run_id))
        self.assertEqual(json.loads(harness.mock_response("VALID")), harness.valid_draft())
        with self.assertRaises(json.JSONDecodeError):
            json.loads(harness.mock_response("INVALID_JSON"))
        with self.assertRaises(harness.MockHarnessError):
            harness.mock_response("DEV3_01")
        for name in ("run_scenario", "run_all", "synthetic_case", "mock_response"):
            parameters = set(inspect.signature(getattr(harness, name)).parameters)
            self.assertFalse(parameters & {"input_archive", "input_path", "dataset", "gold", "archive", "credential",
                                           "api_key", "transport", "transport_factory", "client"}, name)
        for bad in ((), ((),), (("SUCCESS",) * 4,), (("MAYBE",),)):
            with self.assertRaises(harness.MockHarnessError):
                harness.MockJob(bad, "x")
        with self.assertRaises(harness.MockHarnessError):
            harness.MockJob((("SUCCESS",),), None)
        with self.assertRaises(harness.MockHarnessError):
            harness.MockJob((("TIMEOUT",),), "a response that could never be returned")


class SecurityTests(unittest.TestCase):
    def test_a_process_holding_provider_credentials_is_refused(self):
        for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY_3", "google_application_credentials",
                     "GOOGLE_GENAI_USE_VERTEXAI", "VERTEX_PROJECT"):
            with self.subTest(variable=name), self.assertRaisesRegex(harness.MockHarnessError, "credential"):
                harness.run_scenario("S01", new_root("s01"), environment={name: "not-a-real-key"})
        try:
            harness.assert_no_provider_credentials({"GEMINI_API_KEY": "not-a-real-key"})
        except harness.MockHarnessError as error:
            self.assertNotIn("not-a-real-key", str(error))
            self.assertNotIn("GEMINI_API_KEY", str(error))
        harness.assert_no_provider_credentials({"GEMINI_API_KEY": "", "PATH": "x", "PYTHONPATH": "y", "HOME": "z"})
        harness.assert_no_provider_credentials(os.environ)
        source = Path(harness.__file__).read_text(encoding="utf-8")
        for forbidden in ("load_runtime_config", "GeminiDevWindowTransport", "official_client_factory", "genai",
                          "import google", "dotenv", '".env"', "/.env", "api_key", "getenv", "gemini_key_pool", "gemini_transport",
                          "gemini_resilience", "requests", "urllib", "import socket", "http.client", "DEV3_INPUT",
                          "gold_archive", "zipfile", "evaluate_case", "time.sleep", "time.time", "datetime"):
            self.assertNotIn(forbidden, source, forbidden)
        self.assertEqual(1, source.count("os.environ"))

    def test_only_the_offline_mock_transport_can_run_a_job(self):
        class GeminiDevWindowTransport:
            def __call__(self, spec, window, request_id):
                raise AssertionError("a real transport was called")

        class Lookalike(harness.OfflineMockTransport):
            pass

        run = harness.MockRun(harness.scenario_by_id("S01"), new_root("s01"))
        spec = protocol.build_primary_spec("SYN_01", harness.synthetic_case("SYN_01").prepared_input)
        real = run.transport
        for replacement in (GeminiDevWindowTransport(), lambda spec, window, request_id: {},
                            Lookalike({}, run.budget, run.guard, run.clock), None):
            run.transport = replacement
            with self.assertRaisesRegex(harness.MockHarnessError, "offline mock transport"):
                run.run_job(spec)
        self.assertEqual(0, run.budget.consumed())
        run.transport = real
        self.assertEqual("NONE_NO_CLIENT_NO_CREDENTIAL_NO_SOCKET", real.NETWORK_ACCESS)
        self.assertEqual({"_script", "_budget", "_guard", "_clock", "window_calls", "operations"}, set(vars(real)))
        with self.assertRaises(harness.MockHarnessError):
            run.run_job(protocol_v2.build_primary_spec("SYN_01", harness.synthetic_case("SYN_01").prepared_input))

    def test_no_network_and_no_wall_clock_wait_is_used_by_a_run(self):
        def refuse(*_, **__):
            raise AssertionError("the mock run tried to use the network or to wait")

        with mock.patch.object(socket, "socket", side_effect=refuse), \
                mock.patch.object(socket, "create_connection", side_effect=refuse), \
                mock.patch("time.sleep", side_effect=refuse):
            result = harness.run_scenario("S12", new_root("s12"))
        self.assertEqual(scenario("S12")["summary_sha256"], result["summary_sha256"])
        self.assertEqual(5, result["operations"]["mock_operations_started"])

    def test_private_roots_that_are_not_isolated_mock_storage_are_refused(self):
        refused = (
            REPO_ROOT, REPO_ROOT.parent, REPO_ROOT / "benchmarks" / "m4_extraction", REPO_ROOT / "docs",
            REPO_ROOT / ".local", REPO_ROOT / ".local" / "m4_04b4c_p4_dev3_tuning",
            REPO_ROOT / ".local" / "m4_04b3h_dev3_predictions", REPO_ROOT / ".local" / "m4_04b4b_p4_synthetic_smoke",
            REPO_ROOT / ".local" / "other_experiment",
            REPO_ROOT / ".local" / "m4_04b4e_synthetic_mock" / "dev3_input",
            Path(_STATE["directory"]) / "DEV3_gold", Path(_STATE["directory"]) / "holdout" / "s01",
            Path(_STATE["directory"]) / "m4_04b4c_p4_dev3_tuning", Path(_STATE["directory"]) / ("private" + "_authoring"),
            Path(_STATE["directory"]) / "predictions",
        )
        for root in refused:
            with self.subTest(root=root.name), self.assertRaises(harness.MockHarnessError):
                harness.assert_isolated_private_root(root)
            with self.assertRaises(harness.MockHarnessError):
                harness.run_scenario("S01", root)
        self.assertFalse((REPO_ROOT / ".local" / "other_experiment").exists())
        accepted = harness.assert_isolated_private_root(REPO_ROOT / ".local" / "m4_04b4e_synthetic_mock_review" / "s01")
        self.assertEqual("s01", accepted.name)
        harness.assert_isolated_private_root(new_root("s01"))

    def test_public_summaries_hold_no_story_text_semantic_value_or_record_handle(self):
        texts = [json.dumps(sweep(), ensure_ascii=False)]
        texts += [path.read_text(encoding="utf-8") for item in sweep()["scenarios"]
                  for path in (sweep_root(item["scenario_id"]) / "summaries").glob("*.json")]
        self.assertEqual(22, len(texts))
        for text in texts:
            for value in SEMANTIC_VALUES + (harness.SYNTHETIC_TEXT,):
                self.assertNotIn(value, text)
            for forbidden in ("record_handle", "removed_handles", "retained_handles", "added_handles", "raw_response",
                              "user_prompt", "system_prompt", "request_fingerprint", "schema_path"):
                self.assertNotIn(forbidden, text)
        strings = set()

        def walk(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    strings.add(key)
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)
            elif isinstance(node, str):
                strings.add(node)

        walk(sweep())
        self.assertEqual([], sorted(value for value in strings if v31.is_safe_handle(value)))
        self.assertTrue(all(value.isascii() for value in strings))
        # The private results do hold handles; that is why they stay private.
        self.assertIn("removed_handles", (sweep_root("S19") / "case_results" / "SYN_19.json").read_text("utf-8"))

    def test_no_provider_latency_token_usage_or_cost_is_invented(self):
        text = json.dumps(sweep())
        for forbidden in ("latency", "token_count", "prompt_token", "candidates_token", "cost", "usd", "wait_seconds"):
            self.assertNotIn(forbidden, text.lower())
        record = checkpoint("S05", "M4B4E_P41_SYN_05_PRIMARY")
        self.assertEqual((None, None, {"evidence": LABEL}),
                         (record["first_success"]["usage"], record["first_success"]["model_reported_version"],
                          record["first_success"]["provider_metadata"]))
        self.assertTrue(all(attempt["evidence"] == LABEL for attempt in record["first_success"]["attempt_history"]))

    def test_the_command_line_runs_only_the_mock_and_says_so(self):
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            self.assertEqual(0, harness.main(["--mode", "verify"]))
        verified = json.loads(printed.getvalue())
        self.assertEqual((LABEL, 0, protocol.PROTOCOL_SHA256), (verified["evidence"], verified["real_provider_operations"],
                                                                verified["protocol_sha256"]))
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            harness.main(["--mode", "live"])
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            harness.main(["--mode", "mock", "--private-root", "x"])


class PublicRecordTests(unittest.TestCase):
    RECORD = REPO_ROOT / "benchmarks/m4_extraction/M4_04B4E_P4_1_RUNTIME_PREPARATION_AND_SYNTHETIC_MOCK.yaml"
    NOTE = REPO_ROOT / "docs/research/m4/M4_P4_1_RUNTIME_PROTOCOL_CANDIDATE_V1.md"

    def setUp(self):
        self.text = self.RECORD.read_text(encoding="utf-8")
        self.record = yaml.safe_load(self.text)

    def test_record_binds_the_identities_the_protocol_and_the_mock_results(self):
        record = self.record
        # The task is reported as a protocol violation: a pre-commit secret scan read the local credential file.
        # Every offline gate passes; the READY status is not claimed.
        self.assertEqual(("M4-04B4E", "M4_04B4E_PROTOCOL_VIOLATION", protocol.EXPECTED_BASE_COMMIT),
                         (record["task"], record["status"], record["base_commit"]))
        violation = record["protocol_violation"]
        self.assertEqual((True, "LOCAL_CREDENTIAL_FILE_READ_BY_A_PRE_COMMIT_SECRET_SCAN", False, False, False, False,
                          False, True),
                         (violation["declared"], violation["kind"],
                          violation["credential_values_printed_stored_or_transmitted"],
                          violation["provider_client_created"], violation["provider_or_model_call_made"],
                          violation["credential_used_by_the_protocol_harness_or_tests"],
                          violation["earlier_records_rewritten"], violation["orchestrator_ruling_requested"]))
        self.assertEqual("EVERY_OFFLINE_SAFETY_MOCK_RUNTIME_AND_REGRESSION_GATE_PASSES", violation["offline_gates"])
        self.assertEqual((True, False), (record["decision"]["offline_gates_passed"],
                                         record["decision"]["ready_status_claimed"]))
        active = record["active_identities"]
        self.assertEqual((protocol.ACTIVE_CANDIDATE_ID, protocol.ACTIVE_CANDIDATE_SHA256, protocol.ACTIVE_DIAGNOSTIC_ID,
                          protocol.ACTIVE_DIAGNOSTIC_TOOL_SHA256),
                         (active["candidate"], active["candidate_sha256"], active["diagnostic"],
                          active["diagnostic_tool_sha256"]))
        candidate = record["protocol_candidate"]
        self.assertEqual((protocol.PROTOCOL_ID, protocol.PROTOCOL_SHA256, protocol.PROTOCOL_STANDING),
                         (candidate["identity"], candidate["sha256"], candidate["standing"]))
        self.assertEqual(protocol.build_protocol()["proposed_generation"], candidate["proposed_configuration"])
        self.assertEqual(list(protocol.OPEN_DECISIONS), candidate["open_decisions"])
        self.assertEqual("REQUIRES_ORCHESTRATOR_AUTHORIZATION", candidate["live_operation_budget"])
        for name, module in (("protocol_tool", protocol), ("mock_harness", harness), ("retention_metrics", retention)):
            self.assertEqual(protocol_v2.normalized_file_sha256(Path(module.__file__)), record["tools"][name]["sha256"])
        mock_run = record["synthetic_mock"]
        self.assertEqual((LABEL, sweep()["summary_sha256"], harness.FIXTURE_SET_SHA256, 21),
                         (mock_run["evidence"], mock_run["run_summary_sha256"], mock_run["fixture_set_sha256"],
                          mock_run["scenarios_run"]))
        published = {item["scenario_id"]: item for item in mock_run["scenarios"]}
        for item in sweep()["scenarios"]:
            entry = published[item["scenario_id"]]
            self.assertEqual((item["simulates"], item["run_status"], [case["terminal_status"] for case in item["cases"]],
                              item["operations"]["mock_operations_started"], item["summary_sha256"]),
                             (entry["simulates"], entry["run_status"], entry["terminal_statuses"],
                              entry["mock_operations"], entry["summary_sha256"]))

    def test_record_flags_counts_and_public_safety(self):
        record = self.record
        flags = record["boundaries"]
        self.assertEqual((0, 0, 0, True),
                         (flags["provider_calls"], flags["model_calls"],
                          flags["credentials_loaded_by_the_protocol_harness_or_tests"],
                          flags["credential_file_read_by_the_pre_commit_secret_scan"]))
        for name in ("DEV3_input_opened", "DEV3_gold_opened", "private_B4C_predictions_opened", "holdout_opened",
                     "fresh_DEV4_created"):
            self.assertIs(False, flags[name], name)
        self.assertEqual("UNAVAILABLE", flags["live_P4_1_result"])
        tests = record["offline_tests"]
        loader = unittest.defaultTestLoader
        counted = {module: loader.loadTestsFromName(f"tests.story_extraction.{module}").countTestCases()
                   for module in tests["focused"]["modules"]}
        self.assertEqual(counted, tests["focused"]["modules"])
        self.assertEqual(sum(counted.values()), tests["focused"]["tests"])
        regression = tests["complete_regression"]
        self.assertEqual((PREVIOUS_ACCEPTED_TOTAL, PREVIOUS_ACCEPTED_TOTAL + sum(counted.values()),
                          sum(regression["suites"].values())),
                         (regression["previous_total"], regression["total"], regression["total"]))
        self.assertTrue(self.text.isascii())
        self.assertNotRegex(self.text, r"AIza[0-9A-Za-z_\-]{10,}")
        note = self.NOTE.read_text(encoding="utf-8")
        for text in (self.text, note):
            for value in SEMANTIC_VALUES + (harness.SYNTHETIC_TEXT, "GEMINI_API_KEY", "C:\\", ".local/m4_04b4c"):
                self.assertNotIn(value, text)
        self.assertEqual([], [value for value in self._strings(record) if v31.is_safe_handle(value)])

    def _strings(self, node):
        if isinstance(node, dict):
            for key, value in node.items():
                yield key
                yield from self._strings(value)
        elif isinstance(node, list):
            for value in node:
                yield from self._strings(value)
        elif isinstance(node, str):
            yield node

    def test_note_answers_the_design_questions_and_project_state_records_the_task(self):
        note = self.NOTE.read_text(encoding="utf-8")
        for required in (protocol.PROTOCOL_ID, protocol.PROTOCOL_SHA256, LABEL, protocol.ACTIVE_CANDIDATE_SHA256,
                         "When is an incomplete Diagnostic V3.1 still actionable",
                         "When must the repair be refused for safety",
                         "Can the runtime distinguish a genuinely corrected draft",
                         "Which retention metrics are possible without gold",
                         "Does the runtime preserve all historical exactly-once guarantees",
                         "What must be locked before the first future P4.1 provider operation",
                         "What would a future synthetic live smoke actually prove",
                         "What evidence must exist before authorizing P4.1 tuning on DEV3"):
            self.assertIn(required, note)
        state = (REPO_ROOT / "docs/PROJECT_STATE.md").read_text(encoding="utf-8")
        for required in (f"Status: {self.record['status']}", "Status: M4_04B4D_F1_SAFE_LOCATOR_CORRECTION_READY",
                         protocol.PROTOCOL_SHA256, LABEL, "M4-04B4E", self.record["decision"]["next_action"]):
            self.assertIn(required, state)


if __name__ == "__main__":
    unittest.main()
