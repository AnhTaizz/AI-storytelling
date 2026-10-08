"""Offline tests for the M4-04B4C DEV3 execution adapter.

Synthetic story fixtures in synthetic archives of the recorded DEV3 input layout, with
mocked transports or a fake SDK client. No DEV3 package, credential or provider is touched.
"""
import contextlib
import copy
from dataclasses import fields, replace
import inspect
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import yaml

from tests.story_extraction import test_run_m4_04b3h_dev3_p3_live_v1_1 as layout_tests
from tools.story_extraction import m4_04b4a_p4_output_contract_v1 as contract
from tools.story_extraction import m4_04b4b_p4_protocol_v1 as protocol_v1
from tools.story_extraction import m4_04b4br_p4_protocol_v2 as protocol
from tools.story_extraction import materialize_draft_v1_1_model_schema_v1 as materializer
from tools.story_extraction import project_draft_v1_1_model_schema_to_gemini_v1 as projection
from tools.story_extraction import run_m4_04b3h_dev3_p3_live_v1_1 as dev3_layout
from tools.story_extraction import run_m4_04b4b_p4_structural_v1 as runner_v1
from tools.story_extraction import run_m4_04b4c_p4_dev3_tuning_v1 as adapter
from tools.story_extraction.dev3_seal_v1 import deterministic_zip_bytes
from tools.story_extraction.draft_compiler_v1_1 import prepare_story_extraction_draft_v1_1
from tools.story_extraction.durable_research_executor_v1 import (
    CheckpointIntegrityError,
    DurableTransportFailure,
    JobState,
    PersistentRollingOperationPacer,
)
from tools.story_extraction.m4_04b3f_dev3_p3_protocol_v1 import canonical_json_bytes, sha256_bytes


CASE_IDS = adapter.CASE_IDS
LOCK_SHA = "a" * 64
MARKER = "ZZ_PROVIDER_MESSAGE_MARKER_ZZ"


def primary_job(case_id):
    return f"M4B4BR_P4V2_{case_id}_PRIMARY"


def repair_job(case_id):
    return f"M4B4BR_P4V2_{case_id}_REPAIR_1"


def valid_draft(case_id):
    return copy.deepcopy(layout_tests._synthetic()[1][case_id])


def valid_raw(case_id):
    return json.dumps(valid_draft(case_id), ensure_ascii=False)


def schema_invalid_raw(case_id):
    draft = valid_draft(case_id)
    draft["zz_unexpected"] = 1
    return json.dumps(draft)


def projection_valid_full_invalid_raw(case_id):
    draft = valid_draft(case_id)
    draft["evidence"][0]["handle"] = "X1"
    return json.dumps(draft)


def write_archive(test, entries=None, name="synthetic_input.zip"):
    directory = tempfile.TemporaryDirectory(prefix="m4b4c_")
    test.addCleanup(directory.cleanup)
    root = Path(directory.name)
    archive = root / name
    archive.write_bytes(deterministic_zip_bytes(entries or layout_tests.synthetic_entries()))
    return root, archive, sha256_bytes(archive.read_bytes())


def success(raw, operations=1):
    def behaviour(budget, spec):
        for _ in range(operations):
            try:
                budget.acquire()
            except runner_v1.OperationBudgetExhausted:
                raise CheckpointIntegrityError("Global pacing attempt accounting mismatch") from None
        return {"raw_content": raw, "model_requested": spec.model, "slot_id": spec.credential_slot,
                "transport_attempts": [{"model": spec.model, "slot_id": spec.credential_slot}] * operations,
                "attempt_accounting": {"total_provider_attempts": operations},
                "usage_metadata": {"prompt_token_count": 100, "candidates_token_count": 10, "total_token_count": 110}}
    return behaviour


def terminal_failure(category="AUTH_FAILURE", status=403, reason="PERMISSION_DENIED"):
    def behaviour(budget, spec):
        budget.acquire()
        raise DurableTransportFailure(
            category, provider_attempts=1, fingerprint=f"{category}:{status}",
            attempts=[{"model": spec.model, "slot_id": spec.credential_slot, "classified_result": category,
                       "http_status": status, "provider_reason": reason}],
        )
    return behaviour


class VirtualClock:
    """Time for the persistent pacer. Waiting for the rolling window advances it instantly."""

    def __init__(self):
        self.now = 1_800_000_000.0
        self.slept = 0.0

    def time(self):
        self.now += 0.001
        return self.now

    def sleep(self, seconds):
        self.slept += seconds
        self.now += seconds

    def pacer(self, path, **kwargs):
        return PersistentRollingOperationPacer(path, clock=self.time, sleep=self.sleep, **kwargs)

    def patched(self):
        return mock.patch.object(adapter, "PersistentRollingOperationPacer", side_effect=self.pacer)


class Workspace:
    """A synthetic archive, a private root and a scripted transport."""

    def __init__(self, test, entries=None):
        self.root, self.archive, self.sha256 = write_archive(test, entries)
        self.private = self.root / "private"
        self.calls = []
        self.specs = []
        self.clock = VirtualClock()

    def factory(self, script, operations=1):
        def build(budget, guard):
            def transport(spec, window, request_id):
                self.calls.append(spec.job_id)
                self.specs.append(spec)
                guard()
                behaviour = script.get(spec.job_id)
                if behaviour is None:
                    case_id = spec.job_id.split("_P4V2_")[1].rsplit("_PRIMARY", 1)[0].rsplit("_REPAIR_1", 1)[0]
                    behaviour = success(valid_raw(case_id), operations)
                return behaviour(budget, spec)
            return transport
        return build

    def run(self, script=None, operations=1, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()), self.clock.patched():
            return adapter.run(input_archive=self.archive, private_root=self.private, expected_input_sha256=self.sha256,
                               transport_factory=self.factory(script or {}, operations), **kwargs)

    def verify(self):
        with self.clock.patched():
            return adapter.verify_run(input_archive=self.archive, private_root=self.private,
                                      expected_input_sha256=self.sha256)

    def stack(self, lock_sha, **kwargs):
        with self.clock.patched():
            return adapter.build_durable_stack(self.private / "checkpoints", lock_sha, **kwargs)

    def private_text(self):
        return "\n".join(path.read_text(encoding="utf-8", errors="replace")
                         for path in self.private.rglob("*") if path.is_file() and "input" not in path.parts)


class P4ProvenanceInputTests(unittest.TestCase):
    def load(self, entries=None):
        root, archive, digest = write_archive(self, entries)
        return (adapter.load_p4_case_inputs(archive, root / "input", expected_input_sha256=digest),
                dev3_layout.load_case_inputs(archive, root / "input_p3", expected_input_sha256=digest))

    def test_dataset_identity_is_the_locked_dev3_input_and_never_the_gold(self):
        self.assertEqual("47ae7c743065f8ff001f4db6a398df2edf1db094383b1fe2d0c3a05ab40c55c7", adapter.DEV3_INPUT_SHA256)
        self.assertEqual("b5b2258d46608015ff60de2c660fba521029ff4716c7c1cc3b3735c55dfd34a9", adapter.DEV3_GOLD_SHA256)
        self.assertEqual(tuple(f"DEV3_{n:02d}" for n in range(1, 11)), adapter.CASE_IDS)
        self.assertEqual("TUNING_DATA_AFTER_P3_FAILURE", adapter.DEV3_STATUS_FOR_P4)
        self.assertEqual((adapter.DEV3_INPUT_SHA256, adapter.DEV3_GOLD_SHA256),
                         (dev3_layout.DEV3_INPUT_SHA256, dev3_layout.DEV3_GOLD_SHA256))

    def test_ten_cases_load_in_order_and_only_process_and_run_identity_differ(self):
        cases, p3_cases = self.load()
        self.assertEqual(list(CASE_IDS), [case.case_id for case in cases])
        self.assertEqual(("process_id", "run_id"), adapter.PROVENANCE_FIELDS)
        for case, p3_case in zip(cases, p3_cases):
            context, source = case.compiler_context, p3_case.compiler_context
            self.assertEqual(("M4_04B4C_P4", f"P4_{case.case_id}"), (context.process_id, context.run_id))
            self.assertEqual((dev3_layout.PROCESS_ID, f"P3_{case.case_id}"), (source.process_id, source.run_id))
            self.assertEqual(("v1.1", "v1.1"), (source.process_version, context.process_version))
            for field in fields(context):
                if field.name not in adapter.PROVENANCE_FIELDS and field.name != "ingestion":
                    self.assertEqual(getattr(source, field.name), getattr(context, field.name), field.name)
            self.assertEqual(source.passage_inputs, context.passage_inputs)
            self.assertEqual(source.ingestion.fingerprint, context.ingestion.fingerprint)
            self.assertEqual(p3_case.prepared_input, case.prepared_input)
            self.assertEqual(case.prepared_input, prepare_story_extraction_draft_v1_1(context))

    def test_prepared_input_is_exactly_the_archived_one_and_source_bytes_are_unchanged(self):
        entries = layout_tests.synthetic_entries()
        root, archive, digest = write_archive(self, entries)
        cases = adapter.load_p4_case_inputs(archive, root / "input", expected_input_sha256=digest)
        for case in cases:
            self.assertEqual(json.loads(entries[f"cases/{case.case_id}/prepared_draft_input.json"]), case.prepared_input)
            self.assertEqual(entries[f"cases/{case.case_id}/source/unit.txt"],
                             (root / "input" / "cases" / case.case_id / "source" / "unit.txt").read_bytes())
            self.assertEqual(json.loads(entries[f"cases/{case.case_id}/base_document.json"]),
                             case.compiler_context.base_document)

    def test_compiled_output_carries_p4_provenance_and_no_p3_identity(self):
        cases, p3_cases = self.load()
        for case, p3_case in zip(cases, p3_cases):
            raw = valid_raw(case.case_id)
            _, batch, validation = runner_v1.compile_raw_response(raw, case)
            self.assertTrue(validation["pass"], case.case_id)
            text = json.dumps(batch, ensure_ascii=False)
            self.assertIn(f"P4_{case.case_id}", text)
            self.assertIn("M4_04B4C_P4", text)
            for forbidden in (f"P3_{case.case_id}", "M4_04B3H_P3", dev3_layout.PROCESS_ID):
                self.assertNotIn(forbidden, text)
            _, p3_batch, _ = runner_v1.compile_raw_response(raw, p3_case)
            self.assertIn(f"P3_{case.case_id}", json.dumps(p3_batch, ensure_ascii=False))

    def test_rebinding_fails_closed_on_any_other_difference(self):
        cases, p3_cases = self.load()
        case = p3_cases[0]
        changed = type(case)(case.case_id, {**case.prepared_input, "existing_context": {"x": 1}}, case.compiler_context)
        with self.assertRaisesRegex(adapter.P4Dev3Error, "does not reproduce exactly"):
            adapter.rebind_to_p4(changed)
        other = type(case)(case.case_id, case.prepared_input,
                           replace(case.compiler_context, passage_inputs=p3_cases[1].compiler_context.passage_inputs))
        with self.assertRaises(adapter.P4Dev3Error):
            adapter.rebind_to_p4(other)
        versioned = type(case)(case.case_id, case.prepared_input, replace(case.compiler_context, process_version="v2"))
        with self.assertRaisesRegex(adapter.P4Dev3Error, "process version"):
            adapter.rebind_to_p4(versioned)
        rebound = adapter.rebind_to_p4(case).compiler_context
        self.assertEqual((cases[0].compiler_context.run_id, cases[0].compiler_context.process_id),
                         (rebound.run_id, rebound.process_id))
        self.assertIs(case.compiler_context.ingestion, rebound.ingestion)

    def test_archive_is_hashed_before_it_is_opened(self):
        root, archive, digest = write_archive(self)
        with mock.patch.object(dev3_layout.zipfile, "ZipFile", side_effect=AssertionError("opened")) as opened:
            with self.assertRaisesRegex(adapter.P4Dev3Error, "hash mismatch"):
                adapter.load_p4_case_inputs(archive, root / "input")
            with self.assertRaisesRegex(adapter.P4Dev3Error, "gold package is forbidden"):
                adapter.load_p4_case_inputs(archive, root / "input", expected_input_sha256=adapter.DEV3_GOLD_SHA256)
            with mock.patch.object(dev3_layout, "DEV3_GOLD_SHA256", digest), \
                    mock.patch.object(adapter, "DEV3_GOLD_SHA256", digest):
                with self.assertRaisesRegex(adapter.P4Dev3Error, "gold package is forbidden"):
                    adapter.load_p4_case_inputs(archive, root / "input", expected_input_sha256=digest)
        opened.assert_not_called()
        self.assertFalse((root / "input").exists())

    def test_gold_like_path_and_bad_layout_are_rejected(self):
        gold_root, gold_archive, gold_digest = write_archive(self, name="dev3_gold.zip")
        with self.assertRaisesRegex(adapter.P4Dev3Error, "Gold-like input path"):
            adapter.load_p4_case_inputs(gold_archive, gold_root / "input", expected_input_sha256=gold_digest)
        entries = layout_tests.synthetic_entries()
        entries["cases/DEV3_01/extra.json"] = b"{}"
        with self.assertRaises(adapter.P4Dev3Error):
            self.load(entries)
        entries = layout_tests.synthetic_entries()
        entries["cases/DEV3_02/gold.json"] = entries.pop("cases/DEV3_02/base_document.json")
        with self.assertRaises(adapter.P4Dev3Error):
            self.load(entries)
        entries = layout_tests.edit_manifest(
            layout_tests.synthetic_entries(), lambda m: m.__setitem__("case_order", list(reversed(m["case_order"])))
        )
        with self.assertRaises(adapter.P4Dev3Error):
            self.load(entries)
        entries = layout_tests.synthetic_entries()
        prepared = json.loads(entries["cases/DEV3_04/prepared_draft_input.json"])
        prepared["passages"] = prepared["passages"] + [{"handle": "P9"}]
        entries["cases/DEV3_04/prepared_draft_input.json"] = canonical_json_bytes(prepared)
        with self.assertRaisesRegex(adapter.P4Dev3Error, "does not reproduce exactly"):
            self.load(entries)

    def test_every_other_layout_defect_is_rejected(self):
        def members(change):
            return layout_tests.edit_manifest(layout_tests.synthetic_entries(), lambda m: change(m["cases"][0]["members"]))

        def fingerprint():
            entries = layout_tests.synthetic_entries()
            report = json.loads(entries["cases/DEV3_02/ingestion_report.json"])
            report["corpus_fingerprint_sha256"] = "0" * 64
            entries["cases/DEV3_02/ingestion_report.json"] = canonical_json_bytes(report)
            return entries

        def source_bytes():
            entries = layout_tests.synthetic_entries()
            entries["cases/DEV3_03/source/unit.txt"] += b" "
            return entries

        def without(member):
            entries = layout_tests.synthetic_entries()
            del entries[member]
            return entries

        defects = {
            "missing_member": without("cases/DEV3_03/source/unit.txt"),
            "missing_manifest": without("input_manifest.json"),
            "duplicate_member": members(lambda listed: listed.append(listed[0])),
            "cross_case_member": members(lambda listed: listed.append("cases/DEV3_02/base_document.json")),
            "path_traversal": members(lambda listed: listed.append("../escape.json")),
            "absolute_member": members(lambda listed: listed.append("/etc/passwd")),
            "gold_member_listed": members(lambda listed: listed.append("cases/DEV3_01/gold.json")),
            "wrong_artifact": layout_tests.edit_manifest(
                layout_tests.synthetic_entries(), lambda m: m.__setitem__("artifact", "M4_04B3_DEV3_GOLD_V1")),
            "wrong_case_count": layout_tests.edit_manifest(
                layout_tests.synthetic_entries(), lambda m: m.__setitem__("case_count", 9)),
            "m3_fingerprint_mismatch": fingerprint(),
            "source_bytes_changed": source_bytes(),
        }
        for label, entries in defects.items():
            with self.subTest(defect=label), self.assertRaises(adapter.P4Dev3Error):
                self.load(entries)


class ExperimentLockTests(unittest.TestCase):
    def test_tracked_lock_equals_what_the_code_rebuilds(self):
        lock, digest = adapter.locked_experiment()
        document = yaml.safe_load(adapter.EXPERIMENT_LOCK_PATH.read_text(encoding="utf-8"))
        self.assertEqual({"experiment_lock_sha256", "lock"}, set(document))
        self.assertEqual(lock, document["lock"])
        self.assertEqual(digest, document["experiment_lock_sha256"])
        self.assertEqual(digest, sha256_bytes(protocol.canonical_json_bytes(adapter.build_experiment_lock())))
        self.assertEqual(adapter.build_experiment_lock(), adapter.build_experiment_lock())
        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        adapter.locked_experiment(digest)
        with self.assertRaisesRegex(adapter.P4Dev3Error, "not the expected lock"):
            adapter.locked_experiment("0" * 64)

    def test_lock_binds_every_required_identity(self):
        lock = adapter.build_experiment_lock()
        self.assertEqual(("M4_04B4C_P4_DEV3_STRUCTURAL_TUNING_EXPERIMENT_V1", "M4_04B4C_EXPERIMENT_LOCK_SCHEMA_V1"),
                         (lock["experiment_id"], lock["experiment_schema_version"]))
        self.assertEqual("3ac509af4cb99a04ab4de806541bc4019f23bdca", lock["base_commit"])
        self.assertEqual("TUNING_EXPERIMENT_NOT_FRESH_BLIND_VALIDATION", lock["classification"])
        p4 = lock["p4"]
        self.assertEqual("P4_STORY_EXTRACTION_DRAFT_V1_1_SELF_CONTAINED_V1", p4["extractor_id"])
        self.assertEqual(("M4_P4_STRUCTURAL_TUNING_PROTOCOL_V2",
                          "24b2af927e07078da3a06fe329aa5378cdde92675e76e92e2c03d9ad82726025"),
                         (p4["protocol_id"], p4["protocol_sha256"]))
        self.assertEqual("5aa2ed6dde3791546ddd5e059648d8dac38df1571a6073b7abc31c89eb257f14", p4["full_model_schema_sha256"])
        self.assertEqual("89506defa4089b1449f7c80bbcf782d94065802ceae71aa86e1598a5a17ab9bd", p4["provider_projection_sha256"])
        self.assertEqual(protocol.prompt_hashes(), p4["prompt_hashes"])
        self.assertEqual("M4_P4_STRUCTURAL_REPAIR_DIAGNOSTIC_V2", p4["repair_diagnostic"])
        self.assertIs(False, p4["provider_projection_as_acceptance_criterion"])
        self.assertEqual(protocol.BOUND_FILES["tools/story_extraction/draft_compiler_v1_1.py"], p4["compiler_v1_1_sha256"])
        generation, runtime = lock["generation"], lock["runtime"]
        self.assertEqual(("gemini-3.5-flash-lite", "gemini_slot_3", 0, 16384, "application/json", 1),
                         (generation["model"], generation["credential_slot"], generation["temperature"],
                          generation["max_output_tokens"], generation["response_mime_type"], generation["concurrency"]))
        self.assertEqual(("GEMINI_TRANSPORT_RESILIENCE_V1_1", "DURABLE_RESEARCH_EXECUTOR_V1", 6, 60, "IMMUTABLE_LOCK"),
                         (runtime["runtime"], runtime["durable_executor"], runtime["global_pacing_max_operations"],
                          runtime["global_pacing_rolling_window_seconds"], runtime["first_success"]))
        dev3 = lock["dev3"]
        self.assertEqual((adapter.DEV3_INPUT_SHA256, adapter.DEV3_GOLD_SHA256, list(CASE_IDS)),
                         (dev3["input_sha256"], dev3["forbidden_gold_sha256"], dev3["case_order"]))
        self.assertEqual({"process_id": "M4_04B4C_P4", "process_version": "v1.1", "run_id_pattern": "P4_{CASE_ID}"},
                         {key: lock["p4_provenance"][key] for key in ("process_id", "process_version", "run_id_pattern")})
        self.assertEqual(1, lock["repair_policy"]["maximum_per_case"])
        self.assertEqual("FORBIDDEN", lock["repair_policy"]["quality_coverage_or_missing_fact_retry"])
        self.assertEqual(30, lock["operation_budget"]["maximum_real_provider_operations"])
        self.assertIs(False, lock["operation_budget"]["authorizes_quality_aware_retries"])
        self.assertEqual("FORBIDDEN", lock["stop_resume_policy"]["automatic_resume"])
        self.assertEqual("TRANSPORT_FAILURE", lock["transport_policy"]["job_without_successful_response"])
        self.assertEqual(list(adapter.PREDICTION_IDENTITY_FIELDS), lock["prediction_set"]["per_case_identity_fields"])
        self.assertEqual(list(adapter.PUBLIC_LOCK_FIELDS), lock["public_prediction_lock"]["top_level_fields"])
        self.assertEqual(list(adapter.PUBLIC_RESULT_FIELDS), lock["public_result_record"]["top_level_fields"])
        rules = lock["decision_rules"]
        self.assertEqual("M4_04B4C_P4_DEV3_TUNING_COMPLETE", rules["statuses"]["all_ten_cases_terminal"])
        self.assertIs(False, rules["success_requires_ten_structural_valid"])
        self.assertEqual("TUNING_COMPARISON_NOT_BLIND_VALIDATION", rules["comparison_with_p3"]["label"])
        self.assertEqual(8, rules["recommended_next_action"]["stable_if_structural_valid_at_least"])
        code = lock["code"]
        self.assertEqual(set(adapter.EXECUTION_PATH_FILES), set(code["execution_path_files"]))
        self.assertEqual(dict(protocol.BOUND_FILES), code["protocol_v2_bound_files"])
        self.assertEqual(protocol.normalized_file_sha256(Path(adapter.__file__)),
                         code["execution_path_files"][adapter.ADAPTER_PATH])

    def test_lock_has_no_self_reference(self):
        text = json.dumps(adapter.build_experiment_lock())
        self.assertNotIn(adapter.experiment_lock_sha256(), text)
        self.assertNotIn('"experiment_lock_sha256":', text)
        source = Path(adapter.__file__).read_text(encoding="utf-8")
        self.assertNotIn(adapter.experiment_lock_sha256(), source)

    def test_any_change_to_code_policy_or_protocol_breaks_the_lock(self):
        changed_policy = {**adapter.REPAIR_POLICY, "maximum_per_case": 2}
        changed_budget = {**adapter.OPERATION_BUDGET_POLICY, "maximum_real_provider_operations": 31}
        for name, value in (("OPERATION_BUDGET_POLICY", changed_budget), ("REPAIR_POLICY", changed_policy),
                            ("NEXT_IF_POOR", adapter.NEXT_IF_STABLE),
                            ("PROCESS_ID", "M4_04B3H_P3"), ("STABLE_MINIMUM_STRUCTURAL_VALID", 5),
                            ("DEV3_INPUT_SHA256", "0" * 64), ("LIMITATIONS", ())):
            with self.subTest(binding=name), mock.patch.object(adapter, name, value):
                with self.assertRaises(adapter.P4Dev3Error):
                    adapter.locked_experiment()
        with mock.patch.object(adapter, "execution_path_hashes",
                               return_value={path: "0" * 64 for path in adapter.EXECUTION_PATH_FILES}):
            with self.assertRaises(adapter.P4Dev3Error):
                adapter.locked_experiment()
        with mock.patch.dict(protocol.BOUND_FILES, {"tools/story_extraction/draft_compiler_v1_1.py": "0" * 64}):
            with self.assertRaisesRegex(adapter.P4Dev3Error, "Protocol V2 or a bound file changed"):
                adapter.locked_experiment()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lock.yaml"
            document = adapter.experiment_lock_document()
            document["lock"]["operation_budget"]["maximum_real_provider_operations"] = 300
            path.write_text(yaml.safe_dump(document), encoding="utf-8")
            with self.assertRaises(adapter.P4Dev3Error):
                adapter.locked_experiment(path=path)
            with self.assertRaises(adapter.P4Dev3Error):
                adapter.locked_experiment(path=Path(directory) / "absent.yaml")

    def test_protocol_v2_and_schema_roles_are_the_accepted_ones(self):
        self.assertEqual("24b2af927e07078da3a06fe329aa5378cdde92675e76e92e2c03d9ad82726025", protocol.protocol_sha256())
        self.assertEqual({"PASS"}, set(protocol.schema_lineage_gate().values()))
        self.assertEqual({"PASS"}, set(protocol.validate_bound_files().values()) - {str(len(protocol.BOUND_FILES))})
        self.assertNotEqual(adapter.executor_protocol_id(LOCK_SHA), protocol.executor_protocol_id())
        self.assertTrue(adapter.executor_protocol_id(LOCK_SHA).endswith(LOCK_SHA))

    def test_recommended_next_action_rule_is_fixed(self):
        self.assertEqual([adapter.NEXT_IF_POOR] * 8 + [adapter.NEXT_IF_STABLE] * 3,
                         [adapter.recommended_next_action(count) for count in range(11)])
        self.assertEqual("ORCHESTRATOR REVIEW FOR FRESH DEV4 DESIGN AND SEALING", adapter.NEXT_IF_STABLE)
        self.assertEqual("ORCHESTRATOR REVIEW FOR OFFLINE P4 STRUCTURAL FORENSICS", adapter.NEXT_IF_POOR)
        statuses = adapter.build_experiment_lock()["decision_rules"]["statuses"]
        self.assertEqual(
            {"M4_04B4C_P4_DEV3_TUNING_COMPLETE", "M4_04B4C_OFFLINE_IMPLEMENTATION_INCOMPLETE",
             "M4_04B4C_PRELIVE_LOCK_FAILED", "M4_04B4C_PRELIVE_READY_LIVE_NOT_STARTED",
             "M4_04B4C_DEV3_PREFLIGHT_FAILED", "M4_04B4C_INTERRUPTED_REQUIRES_CHECKPOINT_REVIEW",
             "M4_04B4C_BUDGET_EXHAUSTED", "M4_04B4C_RUN_STOPPED_FAIL_CLOSED", "M4_04B4C_PROTOCOL_VIOLATION"},
            set(statuses.values()),
        )

    def test_historical_p3_b4b_and_b4br_artifacts_are_unchanged(self):
        from tools.story_extraction import m4_04b3h0_dev3_decision_lock_v1 as decision_lock

        self.assertEqual({"PASS"}, set(decision_lock.validate_protected_stacks().values()))
        pinned = {
            "benchmarks/m4_extraction/M4_04B3H_DEV3_P3_PREDICTION_LOCK.yaml":
                "850b6ea557027b7c8777c5960df0654d2d265e9e041487445dfeb9fdcf6d59f2",
            "tools/story_extraction/run_m4_04b3h_dev3_p3_live_v1_1.py":
                "2cd6f40178fa5390171b83c8e2401ff691bd8555fd6efa2bfbceb23bf4fe311b",
            "tools/story_extraction/run_m4_04b3g_dev3_p3_predictions_v1.py":
                "a07a26240c9d30d96bf455a4f88173a38a3b1538a8de2d32d3f09b7402be5087",
            "benchmarks/m4_extraction/M4_04B4B_P4_RUNTIME_PROTOCOL_AND_NATIVE_SCHEMA_SMOKE.yaml":
                "62f753a7eda9c61a7f4dccedaa8a8a56176e1af43e29ac3fdd396934dd3aaf51",
            "tools/story_extraction/run_m4_04b4b_p4_structural_v1.py":
                "4104b6be780eb4d8611951dfd412fed6b7f19c4b55f6170f7c790b1f19207106",
            "benchmarks/m4_extraction/M4_04B4BR_PROVIDER_SCHEMA_PROJECTION_AND_SMOKE.yaml":
                "55ca8f0be70dcfeeefc8d5ce62250a4db28988ae00bf5672e044a65ea0e5d355",
            "tools/story_extraction/run_m4_04b4br_p4_projection_smoke_v1.py":
                "70dd4dd852399e184184c6e9188aa578dfdd32060fdd9e2f65a8e7768fdfed72",
            "tools/story_extraction/m4_04b4br_p4_protocol_v2.py":
                "7410fbc6778eb8d4fe6c64794f645553c380da667f3f774522c6461ab508a001",
            "tools/story_extraction/project_draft_v1_1_model_schema_to_gemini_v1.py":
                "3fcfd71c9129ecac6de7e1d5341911073dad5326a74ed60741733c1808d6a5c5",
        }
        for relative, expected in pinned.items():
            with self.subTest(path=relative):
                self.assertEqual(expected, protocol.normalized_file_sha256(adapter.REPO_ROOT / relative))
        lock = yaml.safe_load((adapter.REPO_ROOT / "benchmarks/m4_extraction/M4_04B3H_DEV3_P3_PREDICTION_LOCK.yaml")
                              .read_text(encoding="utf-8"))
        self.assertEqual(adapter.P3_PREDICTION_SET_SHA256, lock["prediction_set_sha256"])
        self.assertEqual(adapter.P3_STRUCTURAL_VALID, lock["execution"]["structural_valid_count"])
        self.assertEqual("e0c74be45bcfd7cdca4111ff6029358e668b68f0a94fa94cf52718614f75279a", protocol_v1.protocol_sha256())


class CompletedRunTests(unittest.TestCase):
    """One mocked run with every kind of case outcome, shared by the assertions below."""

    @classmethod
    def setUpClass(cls):
        cls.holder = unittest.TestCase()
        cls.workspace = Workspace(cls.holder)
        cls.script = {
            primary_job("DEV3_02"): success("{"),
            repair_job("DEV3_02"): success(valid_raw("DEV3_02")),
            primary_job("DEV3_03"): success(schema_invalid_raw("DEV3_03")),
            repair_job("DEV3_03"): success(schema_invalid_raw("DEV3_03")),
            primary_job("DEV3_04"): terminal_failure(),
            primary_job("DEV3_05"): success(projection_valid_full_invalid_raw("DEV3_05")),
            repair_job("DEV3_05"): terminal_failure(),
            primary_job("DEV3_06"): success(""),
            primary_job("DEV3_07"): success(valid_raw("DEV3_07"), operations=3),
        }
        cls.result = cls.workspace.run(cls.script)
        cls.by_case = {item["case_id"]: item for item in cls.result["predictions"]}

    @classmethod
    def tearDownClass(cls):
        cls.holder.doCleanups()

    def test_all_ten_cases_reach_a_terminal_state_in_order(self):
        self.assertEqual(adapter.STATUS_COMPLETE, self.result["status"])
        self.assertEqual(list(CASE_IDS), [item["case_id"] for item in self.result["predictions"]])
        self.assertEqual(
            {"DEV3_01": "STRUCTURAL_VALID", "DEV3_02": "STRUCTURAL_VALID", "DEV3_03": "STRUCTURAL_FAILURE",
             "DEV3_04": "TRANSPORT_FAILURE", "DEV3_05": "TRANSPORT_FAILURE", "DEV3_06": "STRUCTURAL_FAILURE",
             "DEV3_07": "STRUCTURAL_VALID", "DEV3_08": "STRUCTURAL_VALID", "DEV3_09": "STRUCTURAL_VALID",
             "DEV3_10": "STRUCTURAL_VALID"},
            {case_id: item["terminal_status"] for case_id, item in self.by_case.items()},
        )
        self.assertEqual(sorted(f"{case_id}.json" for case_id in CASE_IDS),
                         sorted(path.name for path in (self.workspace.private / "case_results").iterdir()))

    def test_every_request_is_a_locked_protocol_v2_request(self):
        full = materializer.load_tracked_model_schema()
        native = projection.load_tracked_projection()
        for spec in self.workspace.specs:
            protocol.assert_locked_job_spec(spec)
            with self.assertRaises(protocol_v1.P4ProtocolError):
                protocol_v1.assert_locked_job_spec(spec)
            self.assertEqual(native, spec.generation_config["response_json_schema"])
            self.assertNotEqual(full, spec.generation_config["response_json_schema"])
            self.assertEqual((0, 16384), (spec.generation_config["temperature"], spec.generation_config["max_output_tokens"]))
            self.assertEqual(("gemini-3.5-flash-lite", "gemini_slot_3"), (spec.model, spec.credential_slot))
            self.assertFalse(spec.job_id.startswith("M4B3F_P3_") or spec.job_id.startswith("M4B4B_P4_"))
        primary = self.workspace.specs[0]
        in_prompt = contract.extract_prompt_schema(
            primary.system_prompt, contract.SCHEMA_SECTION_MARKER, contract.REGISTRY_SECTION_MARKER
        )
        self.assertEqual(full, in_prompt)

    def test_at_most_one_repair_and_only_after_a_structural_failure_of_a_response(self):
        self.assertEqual(
            [primary_job("DEV3_01"), primary_job("DEV3_02"), repair_job("DEV3_02"), primary_job("DEV3_03"),
             repair_job("DEV3_03"), primary_job("DEV3_04"), primary_job("DEV3_05"), repair_job("DEV3_05"),
             primary_job("DEV3_06"), primary_job("DEV3_07"), primary_job("DEV3_08"), primary_job("DEV3_09"),
             primary_job("DEV3_10")],
            self.workspace.calls,
        )
        self.assertFalse(any("REPAIR_2" in job or "QUALITY" in job for job in self.workspace.calls))
        for case_id, item in self.by_case.items():
            if item["primary"]["compiler_success"]:
                self.assertFalse(item["repair_used"], case_id)
        jobs = sorted(path.name for path in (self.workspace.private / "checkpoints" / "jobs").glob("*.json"))
        self.assertEqual(sorted(f"{job}.json" for job in self.workspace.calls), jobs)

    def test_repair_receives_only_prepared_input_primary_response_and_diagnostic_v2(self):
        spec = next(spec for spec in self.workspace.specs if spec.job_id == repair_job("DEV3_03"))
        raw = schema_invalid_raw("DEV3_03")
        diagnostic = contract.structural_diagnostic_v2(raw)
        cases = adapter.load_p4_case_inputs(self.workspace.archive, self.workspace.private / "input",
                                            expected_input_sha256=self.workspace.sha256)
        prepared = cases[2].prepared_input
        self.assertEqual(contract.render_repair_user("DEV3_03", prepared, raw, diagnostic), spec.user_prompt)
        self.assertEqual(contract.prompt_material()["repair_system"], spec.system_prompt)
        stored = json.loads((self.workspace.private / "failures" / "DEV3_03_primary_diagnostic.json").read_text("utf-8"))
        self.assertEqual(diagnostic, stored)
        self.assertEqual(contract.REPAIR_DIAGNOSTIC_ID, stored["diagnostic"])

    def test_structural_and_transport_outcomes_are_kept_apart(self):
        transport_primary, transport_repair = self.by_case["DEV3_04"], self.by_case["DEV3_05"]
        self.assertEqual(("PRIMARY", False, None), (transport_primary["terminal_phase"], transport_primary["repair_used"],
                                                    transport_primary["primary"]["raw_response_sha256"]))
        self.assertFalse(transport_primary["primary"]["provider_success"])
        self.assertEqual("TRANSPORT_FAILURE", transport_primary["terminal_failure_category"])
        self.assertEqual(("REPAIR", True), (transport_repair["terminal_phase"], transport_repair["repair_used"]))
        self.assertTrue(transport_repair["primary"]["provider_success"])
        self.assertFalse(transport_repair["repair"]["provider_success"])
        self.assertIsNone(transport_repair["terminal_draft_sha256"])
        self.assertIsNone(transport_repair["compiled_batch_sha256"])
        failed = self.by_case["DEV3_03"]
        self.assertEqual(("STRUCTURAL_FAILURE", "REPAIR_1", "DRAFT_SCHEMA_FAILURE"),
                         (failed["terminal_status"], failed["terminal_phase"], failed["terminal_failure_category"]))
        self.assertFalse((self.workspace.private / "compiled" / "DEV3_03.json").exists())
        self.assertFalse((self.workspace.private / "compiled" / "DEV3_04.json").exists())

    def test_projection_is_measured_but_never_the_acceptance_criterion(self):
        primary = self.by_case["DEV3_05"]["primary"]
        self.assertEqual((True, True, False, False, "DRAFT_SCHEMA_FAILURE"),
                         (primary["json_parse"], primary["provider_projection_valid"], primary["full_schema_valid"],
                          primary["compiler_reached"], primary["structural_failure_category"]))
        self.assertTrue(self.by_case["DEV3_05"]["repair_used"])
        self.assertNotEqual("STRUCTURAL_VALID", self.by_case["DEV3_05"]["terminal_status"])

    def test_empty_primary_response_is_a_structural_failure_without_a_repair_request(self):
        item = self.by_case["DEV3_06"]
        self.assertEqual(("STRUCTURAL_FAILURE", "PRIMARY", "JSON_PARSE_FAILURE", False),
                         (item["terminal_status"], item["terminal_phase"], item["terminal_failure_category"],
                          item["repair_used"]))
        self.assertEqual(adapter.EMPTY_PRIMARY_NOT_REPAIRABLE, item["repair_skipped_reason"])
        self.assertNotIn(repair_job("DEV3_06"), self.workspace.calls)
        with self.assertRaises(protocol.P4ProtocolV2Error):
            protocol.build_repair_spec("DEV3_06", {}, "", contract.structural_diagnostic_v2(""))

    def test_metrics_are_exact_observed_counts(self):
        metrics = self.result["metrics"]
        self.assertEqual(
            {"requests": 10, "provider_success": 9, "valid_json": 7, "provider_projection_valid": 6,
             "full_draft_v1_1_schema_valid": 5, "compiler_reached": 5, "compiler_success": 5,
             "structural_failure_categories": {"DRAFT_SCHEMA_FAILURE": 2, "JSON_PARSE_FAILURE": 2}},
            metrics["primary_outcomes"],
        )
        self.assertEqual(
            {"repairs_eligible": 4, "repairs_skipped_empty_primary_response": 1,
             "requests": 3, "provider_success": 2, "valid_json": 2, "provider_projection_valid": 1,
             "full_draft_v1_1_schema_valid": 1, "compiler_reached": 1, "compiler_success": 1,
             "structural_failure_categories": {"DRAFT_SCHEMA_FAILURE": 1}},
            metrics["repair_outcomes"],
        )
        self.assertEqual(
            {"STRUCTURAL_VALID": 6, "STRUCTURAL_FAILURE": 2, "TRANSPORT_FAILURE": 2, "case_completion_count": 10,
             "terminal_structural_valid_rate": "6/10", "terminal_structural_valid_percent": 60.0},
            metrics["terminal_outcomes"],
        )
        self.assertEqual((runtime_wait := metrics["runtime_metrics"]["pacing_wait_count"]),
                         self.result["operations"]["wait_count"])
        self.assertGreaterEqual(runtime_wait, 1)
        self.assertLessEqual(metrics["runtime_metrics"]["max_rolling_reservations_observed"], 6)
        runtime = metrics["runtime_metrics"]
        self.assertEqual((13, 11, 3, 15, 15, 2, 2, "PASS", "15/30"),
                         (runtime["durable_jobs"], runtime["successful_first_response_jobs"],
                          runtime["structural_repair_jobs"], runtime["pacing_reservations"],
                          runtime["durable_recorded_provider_operations"], runtime["transport_retry_attempts"],
                          runtime["transport_terminal_jobs"], runtime["pacing_invariant"],
                          runtime["operation_budget_utilization"]))
        self.assertEqual(0, runtime["real_provider_operations"])
        self.assertEqual({"candidates_token_count": 110, "prompt_token_count": 1100, "total_token_count": 1210},
                         runtime["tokens_where_reported"])
        self.assertEqual(adapter.NEXT_IF_POOR, self.result["recommended_next_action"])
        self.assertEqual({"label": "TUNING_COMPARISON_NOT_BLIND_VALIDATION", "p3_structural_valid": "0/10",
                          "p4_structural_valid": "6/10"}, self.result["comparison_with_p3"])

    def test_private_artifacts_are_separate_and_write_once(self):
        private = self.workspace.private
        self.assertEqual(sorted(adapter.PRIVATE_DIRECTORIES), sorted(path.name for path in private.iterdir() if path.is_dir()))
        self.assertEqual(9, len(list((private / "raw_primary").iterdir())))
        self.assertEqual(2, len(list((private / "raw_repair").iterdir())))
        self.assertEqual(6, len(list((private / "compiled").iterdir())))
        self.assertEqual(13, len(list((private / "telemetry").iterdir())))
        self.assertTrue((private / "checkpoints" / "global_pacing.json").is_file())
        self.assertTrue((private / "checkpoints" / "operation_budget.json").is_file())
        self.assertTrue((private / f"{adapter.TUNING_RESULT_ID}.json").is_file())
        self.assertTrue((private / f"{adapter.PREDICTION_MANIFEST_ID}.json").is_file())
        raw = (private / "raw_primary" / "DEV3_01.txt").read_bytes()
        self.assertEqual(self.by_case["DEV3_01"]["primary"]["raw_response_sha256"], sha256_bytes(raw))
        with self.assertRaisesRegex(adapter.P4Dev3Error, "Immutable private artifact differs"):
            adapter._write_once(private / "raw_primary" / "DEV3_01.txt", raw + b" ")
        compiled = (private / "compiled" / "DEV3_02.json").read_text(encoding="utf-8")
        self.assertIn("P4_DEV3_02", compiled)
        self.assertNotIn("P3_DEV3_02", compiled)

    def test_post_run_verification_passes_and_makes_no_call(self):
        before = list(self.workspace.calls)
        report = self.workspace.verify()
        self.assertEqual("POST_RUN_INTEGRITY_PASS", report["status"])
        self.assertTrue(all(report["checks"].values()))
        self.assertEqual(self.result["prediction_set_sha256"], report["prediction_set_sha256"])
        self.assertEqual(before, self.workspace.calls)
        self.assertGreaterEqual(len(report["checks"]), 16)

    def test_a_finished_run_is_never_resumed_or_repeated(self):
        before = list(self.workspace.calls)
        with self.assertRaises(adapter.PriorExecutionState):
            self.workspace.run(self.script)
        self.assertEqual(before, self.workspace.calls)
        output = io.StringIO()
        with mock.patch.object(adapter, "run", side_effect=adapter.PriorExecutionState("state")), \
                contextlib.redirect_stdout(output):
            code = adapter.main(["--mode", "run", "--input-archive", str(self.workspace.archive),
                                 "--authorize-live-provider-operations", "M4-04B4C"])
        self.assertEqual((4, "M4_04B4C_INTERRUPTED_REQUIRES_CHECKPOINT_REVIEW"), (code, output.getvalue().strip()))

    def test_checkpoints_of_another_lock_or_budget_are_rejected(self):
        _, lock_sha = adapter.locked_experiment()
        _, _, executor = self.workspace.stack(lock_sha)
        spec = self.workspace.specs[0]
        self.assertEqual(JobState.SUCCEEDED_LOCKED.value, executor.load_job(spec)["state"])
        self.assertEqual(adapter.executor_protocol_id(lock_sha), executor.load_job(spec)["protocol_id"])
        with self.assertRaisesRegex(CheckpointIntegrityError, "budget identity"):
            self.workspace.stack("b" * 64)
        with self.assertRaisesRegex(CheckpointIntegrityError, "budget identity"):
            self.workspace.stack(lock_sha, maximum_operations=29)
        with self.assertRaises(CheckpointIntegrityError):
            executor.load_job(replace(spec, user_prompt=spec.user_prompt + " "))


class PredictionSetAndPublicRecordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.holder = unittest.TestCase()
        cls.workspace = Workspace(cls.holder)
        cls.result = cls.workspace.run({
            primary_job("DEV3_02"): success("{"),
            repair_job("DEV3_02"): success(valid_raw("DEV3_02")),
            primary_job("DEV3_09"): terminal_failure(),
        })
        cls.lock_sha = cls.result["experiment_lock_sha256"]

    @classmethod
    def tearDownClass(cls):
        cls.holder.doCleanups()

    def test_prediction_set_hash_is_deterministic(self):
        identities = self.result["prediction_identities"]
        digest = adapter.prediction_set_sha256(identities, self.lock_sha, self.workspace.sha256)
        self.assertEqual(self.result["prediction_set_sha256"], digest)
        self.assertEqual(digest, adapter.prediction_set_sha256(copy.deepcopy(identities), self.lock_sha, self.workspace.sha256))
        self.assertNotEqual(digest, adapter.prediction_set_sha256(identities, self.lock_sha))
        self.assertNotEqual(digest, adapter.prediction_set_sha256(identities, self.lock_sha, "9" * 64))
        self.assertEqual(identities, [adapter.case_identity(item, self.lock_sha) for item in self.result["predictions"]])
        manifest = json.loads((self.workspace.private / f"{adapter.PREDICTION_MANIFEST_ID}.json").read_text("utf-8"))
        self.assertEqual((digest, identities), (manifest["prediction_set_sha256"], manifest["entries"]))
        for identity in identities:
            self.assertEqual(adapter.PREDICTION_IDENTITY_FIELDS, tuple(identity))

    def test_changing_any_bound_identity_changes_the_prediction_set_hash(self):
        identities = self.result["prediction_identities"]
        baseline = adapter.prediction_set_sha256(identities, self.lock_sha)
        other = "c" * 64
        changes = {
            "primary_request_fingerprint": other, "primary_response_sha256": other, "terminal_draft_sha256": other,
            "compiled_batch_sha256": other,
        }
        seen = {baseline}
        for name, value in changes.items():
            mutated = copy.deepcopy(identities)
            mutated[0][name] = value
            digest = adapter.prediction_set_sha256(mutated, self.lock_sha)
            self.assertNotIn(digest, seen, name)
            seen.add(digest)
        repaired = copy.deepcopy(identities)
        repaired[1]["repair_request_fingerprint"] = other
        seen.add(adapter.prediction_set_sha256(repaired, self.lock_sha))
        repaired = copy.deepcopy(identities)
        repaired[1]["repair_response_sha256"] = other
        seen.add(adapter.prediction_set_sha256(repaired, self.lock_sha))
        success_identity = copy.deepcopy(identities)
        success_identity[0]["durable_job_success_identities"][0]["response_sha256"] = other
        seen.add(adapter.prediction_set_sha256(success_identity, self.lock_sha))
        success_job = copy.deepcopy(identities)
        success_job[0]["durable_job_success_identities"][0]["job_id"] = "OTHER_JOB"
        seen.add(adapter.prediction_set_sha256(success_job, self.lock_sha))
        failed = copy.deepcopy(identities)
        failed[8]["terminal_failure_sha256"] = other
        seen.add(adapter.prediction_set_sha256(failed, self.lock_sha))
        status = copy.deepcopy(identities)
        status[8]["terminal_status"] = "STRUCTURAL_FAILURE"
        seen.add(adapter.prediction_set_sha256(status, self.lock_sha))
        flag = copy.deepcopy(identities)
        flag[0].update(repair_used=True, repair_request_fingerprint=other)
        seen.add(adapter.prediction_set_sha256(flag, self.lock_sha))
        relocked = [{**item, "experiment_lock_sha256": other} for item in identities]
        seen.add(adapter.prediction_set_sha256(relocked, other))
        self.assertEqual(13, len(seen))
        with mock.patch.object(protocol, "PROTOCOL_SHA256", other):
            reprotocol = [{**item, "protocol_sha256": other} for item in identities]
            self.assertNotIn(adapter.prediction_set_sha256(reprotocol, self.lock_sha), seen)

    def test_incomplete_reordered_or_malformed_sets_are_rejected(self):
        identities = self.result["prediction_identities"]
        bad_sets = {
            "missing_case": identities[:-1],
            "reordered": list(reversed(identities)),
            "duplicated": identities[:-1] + [identities[0]],
            "other_lock": [{**item, "experiment_lock_sha256": "d" * 64} for item in identities],
        }
        for label, value in bad_sets.items():
            with self.subTest(case=label), self.assertRaises(adapter.P4Dev3Error):
                adapter.prediction_set_sha256(value, self.lock_sha)
        for label, change in {
            "not_a_hash": {"primary_response_sha256": "Tomas closed the window."},
            "bad_status": {"terminal_status": "MOSTLY_VALID"},
            "valid_without_batch": {"compiled_batch_sha256": None},
            "both_records": {"terminal_failure_sha256": "e" * 64},
            "repair_flag_only": {"repair_used": True},
        }.items():
            mutated = copy.deepcopy(identities)
            mutated[0].update(change)
            with self.subTest(case=label), self.assertRaises(adapter.P4Dev3Error):
                adapter.prediction_set_sha256(mutated, self.lock_sha)

    def test_public_prediction_lock_is_metadata_only_and_recomputable(self):
        lock = adapter.build_public_prediction_lock(self.result)
        self.assertEqual(adapter.PUBLIC_LOCK_FIELDS, tuple(lock))
        self.assertEqual(self.result["prediction_set_sha256"],
                         adapter.validate_public_prediction_lock(lock, input_sha256=self.workspace.sha256))
        with self.assertRaises(adapter.P4Dev3Error):
            adapter.validate_public_prediction_lock(lock)
        self.assertEqual((False, False, False), (lock["DEV3_gold_opened"], lock["holdout_opened"],
                                                 lock["semantic_scoring_performed"]))
        self.assertEqual((10, 9, 0, 1, 1), (lock["execution"]["terminal_case_count"],
                                             lock["execution"]["structural_valid_count"],
                                             lock["execution"]["structural_failure_count"],
                                             lock["execution"]["transport_failure_count"],
                                             lock["execution"]["repairs_used"]))
        self.assertEqual((30, 11, True), (lock["operation_accounting"]["operation_budget"],
                                          lock["operation_accounting"]["pacing_reservations"],
                                          lock["operation_accounting"]["within_budget"]))
        for case in lock["cases"]:
            self.assertEqual(adapter.PUBLIC_CASE_FIELDS, tuple(case))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lock.yaml"
            adapter.write_public_prediction_lock(lock, path)
            text = path.read_text(encoding="utf-8")
            self.assertEqual(json.loads(json.dumps(lock)), yaml.safe_load(text))
        private = "\n".join(
            (self.workspace.private / folder / name).read_text(encoding="utf-8")
            for folder, name in (("raw_primary", "DEV3_01.txt"), ("drafts", "DEV3_01_primary.json"))
        )
        for line in layout_tests.synthetic_entries()["cases/DEV3_01/source/unit.txt"].decode("utf-8").splitlines():
            if line.strip():
                self.assertIn(line.strip()[:12], private + json.dumps(self.workspace.specs[0].user_prompt))
                self.assertNotIn(line.strip()[:12], text)
        for forbidden in ("quote", "surface_form", "passages", "raw_response\"", "evidence_handles", "telemetry"):
            self.assertNotIn(forbidden, text)

    def test_public_prediction_lock_rejects_private_content_and_inconsistency(self):
        lock = adapter.build_public_prediction_lock(self.result)
        mutations = {
            "narrative_value": lambda d: d["cases"][0].__setitem__("terminal_failure_category", "Mira opened the gate."),
            "extra_top_level_field": lambda d: d.__setitem__("predictions", []),
            "extra_case_field": lambda d: d["cases"][0].__setitem__("quote", "x"),
            "gold_opened": lambda d: d.__setitem__("DEV3_gold_opened", True),
            "scoring": lambda d: d.__setitem__("semantic_scoring_performed", True),
            "hash_mismatch": lambda d: d["prediction_set"].__setitem__("prediction_set_sha256", "f" * 64),
            "count_mismatch": lambda d: d["execution"].__setitem__("structural_valid_count", 10),
            "over_budget": lambda d: d["operation_accounting"].__setitem__("pacing_reservations", 31),
            "pacing_failed": lambda d: d["pacing"].__setitem__("invariant", "FAIL"),
            "run_identity": lambda d: d["cases"][0].__setitem__("run_id", "P3_DEV3_01"),
            "case_order": lambda d: d["dev3"].__setitem__("case_order", list(reversed(CASE_IDS))),
        }
        for label, change in mutations.items():
            mutated = copy.deepcopy(lock)
            change(mutated)
            with self.subTest(mutation=label), self.assertRaises(adapter.P4Dev3Error):
                adapter.validate_public_prediction_lock(mutated, input_sha256=self.workspace.sha256)
        adapter.validate_public_prediction_lock(copy.deepcopy(lock), input_sha256=self.workspace.sha256)
        incomplete = copy.deepcopy(self.result)
        incomplete["predictions"] = incomplete["predictions"][:-1]
        with self.assertRaises(adapter.P4Dev3Error):
            adapter.build_public_prediction_lock(incomplete)
        scored = {**self.result, "semantic_scoring_performed": True}
        with self.assertRaises(adapter.P4Dev3Error):
            adapter.build_public_prediction_lock(scored)

    def test_public_result_record_is_fixed_format_and_claims_no_quality(self):
        report = self.workspace.verify()
        regression = {"focused_tests": {"count": 1, "result": "PASS"},
                      "full_offline_suites": {"canonical_story": 1, "story_ingestion": 1, "story_extraction": 1,
                                              "script_quality": 1, "story_benchmark": 1, "total": 5, "result": "PASS"}}
        record = adapter.build_public_result_record(self.result, report, regression, "a" * 64)
        self.assertEqual(adapter.PUBLIC_RESULT_FIELDS, tuple(record))
        self.assertEqual("M4_04B4C_P4_DEV3_TUNING_COMPLETE", record["status"])
        self.assertEqual(self.result["prediction_set_sha256"], record["prediction_set_sha256"])
        self.assertEqual("TUNING_COMPARISON_NOT_BLIND_VALIDATION", record["comparison_with_p3"]["label"])
        self.assertEqual(("0/10", "9/10"), (record["comparison_with_p3"]["p3_structural_valid"],
                                            record["comparison_with_p3"]["p4_structural_valid"]))
        self.assertIs(False, record["comparison_with_p3"]["cause_attributed_solely_to_schema_packaging"])
        self.assertIs(False, record["claims"]["semantic_quality_claim"])
        self.assertEqual(adapter.NEXT_IF_STABLE, record["recommended_next_action"]["action"])
        self.assertEqual(list(adapter.LIMITATIONS), record["limitations"])
        self.assertEqual({"DEV3_gold_opened": False, "holdout_opened": False, "semantic_scoring_performed": False,
                          "DEV4_created": False, "P3_predictions_modified": False,
                          "provider_calls_after_prediction_lock": 0}, record["boundaries"])
        text = yaml.safe_dump(record)
        for forbidden in ("quote", "raw_content", "surface_form", "predictions:", "GEMINI_API_KEY", "passages"):
            self.assertNotIn(forbidden, text)
        failed = {**report, "checks": {**report["checks"], "pacing_invariant": False}}
        with self.assertRaises(adapter.P4Dev3Error):
            adapter.build_public_result_record(self.result, failed, regression, "a" * 64)
        for bad in ({**regression, "extra": 1},
                    {**regression, "focused_tests": {"count": 1, "result": "FAIL"}},
                    {**regression, "full_offline_suites": {**regression["full_offline_suites"], "total": 6}}):
            with self.assertRaises(adapter.P4Dev3Error):
                adapter.build_public_result_record(self.result, report, bad, "a" * 64)

    def test_post_run_verification_detects_tampering(self):
        private = self.workspace.private
        self.assertEqual("POST_RUN_INTEGRITY_PASS", self.workspace.verify()["status"])
        targets = {
            "raw_response": private / "raw_primary" / "DEV3_03.txt",
            "compiled_batch": private / "compiled" / "DEV3_03.json",
            "case_result": private / "case_results" / "DEV3_03.json",
        }
        for label, path in targets.items():
            original = path.read_bytes()
            try:
                path.write_bytes(original.replace(b"DEV3_03", b"DEV3_3X") if label != "raw_response" else original + b" ")
                with self.subTest(tampered=label), self.assertRaisesRegex(adapter.P4Dev3Error, "integrity check failed"):
                    self.workspace.verify()
            finally:
                path.write_bytes(original)
        result_path = private / f"{adapter.TUNING_RESULT_ID}.json"
        original = result_path.read_bytes()
        try:
            changed = json.loads(original)
            changed["predictions"][0]["terminal_status"] = "STRUCTURAL_FAILURE"
            result_path.write_bytes(protocol.canonical_json_bytes(changed))
            with self.assertRaises(adapter.P4Dev3Error):
                self.workspace.verify()
        finally:
            result_path.write_bytes(original)
        extra = private / "checkpoints" / "jobs" / "M4B4BR_P4V2_DEV3_01_REPAIR_2.json"
        try:
            extra.write_bytes(b"{}")
            with self.assertRaisesRegex(adapter.P4Dev3Error, "integrity check failed"):
                self.workspace.verify()
        finally:
            extra.unlink()
        self.assertEqual("POST_RUN_INTEGRITY_PASS", self.workspace.verify()["status"])


class StructuralCategoryTests(unittest.TestCase):
    """Each kind of structural defect in a successful response, and what the repair is told."""

    SEMANTIC = "ZZ_MODEL_WRITTEN_VALUE_ZZ"

    @classmethod
    def setUpClass(cls):
        cls.holder = unittest.TestCase()
        cls.workspace = Workspace(cls.holder)

        def broken(case_id, change):
            draft = valid_draft(case_id)
            change(draft)
            return success(json.dumps(draft))

        def empty(case_id):
            draft = valid_draft(case_id)
            return success(json.dumps({key: ([] if isinstance(value, list) else value) for key, value in draft.items()}))

        cls.script = {
            primary_job("DEV3_01"): broken("DEV3_01", lambda d: d["evidence"][0].pop("passage_handle")),
            primary_job("DEV3_02"): broken("DEV3_02", lambda d: d["evidence"][0].__setitem__("role", cls.SEMANTIC)),
            primary_job("DEV3_03"): broken("DEV3_03", lambda d: d["assertions"][0].__setitem__("proposition_handle", "PROP998")),
            primary_job("DEV3_04"): empty("DEV3_04"),
            primary_job("DEV3_05"): broken("DEV3_05", lambda d: d["propositions"][0].__setitem__("args", [cls.SEMANTIC])),
            repair_job("DEV3_05"): success("not json " + cls.SEMANTIC),
            primary_job("DEV3_06"): broken("DEV3_06", lambda d: d.__setitem__(cls.SEMANTIC, 1)),
            primary_job("DEV3_07"): success("[1, 2, 3]"),
        }
        cls.result = cls.workspace.run(cls.script)
        cls.by_case = {item["case_id"]: item for item in cls.result["predictions"]}

    @classmethod
    def tearDownClass(cls):
        cls.holder.doCleanups()

    def test_each_defect_gets_its_category_and_one_repair(self):
        expected = {
            "DEV3_01": ("DRAFT_SCHEMA_FAILURE", True, "STRUCTURAL_VALID"),
            "DEV3_02": ("DRAFT_SCHEMA_FAILURE", True, "STRUCTURAL_VALID"),
            "DEV3_03": ("DRAFT_COMPILER_FAILURE", True, "STRUCTURAL_VALID"),
            "DEV3_04": (None, False, "STRUCTURAL_VALID"),
            "DEV3_05": ("DRAFT_SCHEMA_FAILURE", True, "STRUCTURAL_FAILURE"),
            "DEV3_06": ("DRAFT_SCHEMA_FAILURE", True, "STRUCTURAL_VALID"),
            "DEV3_07": ("DRAFT_SCHEMA_FAILURE", True, "STRUCTURAL_VALID"),
            "DEV3_08": (None, False, "STRUCTURAL_VALID"),
        }
        for case_id, (category, repaired, terminal) in expected.items():
            item = self.by_case[case_id]
            with self.subTest(case=case_id):
                self.assertEqual((category, repaired, terminal),
                                 (item["primary"]["structural_failure_category"], item["repair_used"],
                                  item["terminal_status"]))
        compiler_case = self.by_case["DEV3_03"]["primary"]
        self.assertEqual((True, True, True, False), (compiler_case["json_parse"], compiler_case["full_schema_valid"],
                                                    compiler_case["compiler_reached"], compiler_case["compiler_success"]))
        self.assertEqual("JSON_PARSE_FAILURE", self.by_case["DEV3_05"]["terminal_failure_category"])
        self.assertEqual(16, len(self.workspace.calls))
        self.assertEqual(6, self.result["metrics"]["repair_outcomes"]["repairs_eligible"])
        self.assertEqual(6, self.result["metrics"]["repair_outcomes"]["requests"])

    def test_diagnostics_and_public_records_carry_no_model_written_value(self):
        failures = self.workspace.private / "failures"
        diagnostics = sorted(failures.glob("*_diagnostic.json"))
        self.assertEqual(7, len(diagnostics))
        for path in list(failures.iterdir()):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(self.SEMANTIC, text, path.name)
            self.assertNotIn("PROP998", text, path.name)
        for path in diagnostics:
            diagnostic = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(contract.REPAIR_DIAGNOSTIC_ID, diagnostic["diagnostic"])
            self.assertEqual(len(diagnostic["findings"]), diagnostic["finding_count"])
            self.assertGreaterEqual(diagnostic["finding_count"], 1)
        raw = (self.workspace.private / "raw_primary" / "DEV3_02.txt").read_text(encoding="utf-8")
        self.assertIn(self.SEMANTIC, raw)
        repair_spec = next(spec for spec in self.workspace.specs if spec.job_id == repair_job("DEV3_02"))
        self.assertIn(raw, repair_spec.user_prompt)
        public = yaml.safe_dump(adapter.build_public_prediction_lock(self.result))
        self.assertNotIn(self.SEMANTIC, public)
        self.assertEqual("POST_RUN_INTEGRITY_PASS", self.workspace.verify()["status"])


class OperationBudgetTests(unittest.TestCase):
    def test_exactly_thirty_operations_complete_and_a_thirty_first_never_starts(self):
        workspace = Workspace(self)
        result = workspace.run(operations=3)
        self.assertEqual(adapter.STATUS_COMPLETE, result["status"])
        self.assertEqual((30, 30, True, 0), (result["operations"]["pacing_reservations"],
                                              result["operations"]["operation_budget"],
                                              result["operations"]["within_budget"],
                                              result["operations"]["budget_refusals"]))
        self.assertEqual(20, result["metrics"]["runtime_metrics"]["transport_retry_attempts"])
        _, lock_sha = adapter.locked_experiment()
        pacer, budget, _ = workspace.stack(lock_sha)
        self.assertEqual((30, 0), (budget.consumed(), budget.remaining()))
        self.assertGreater(result["operations"]["wait_count"], 0)
        self.assertLessEqual(result["operations"]["max_rolling_reservations_observed"], 6)
        self.assertGreaterEqual(workspace.clock.slept, 200)
        with self.assertRaises(runner_v1.OperationBudgetExhausted):
            budget.acquire()
        self.assertEqual(30, int(pacer.snapshot()["reservation_count"]))
        self.assertEqual(1, budget.refusals)

    def test_budget_exhausted_between_jobs_stops_before_the_next_operation(self):
        workspace = Workspace(self)
        script = {}
        for case_id in CASE_IDS:
            script[primary_job(case_id)] = success("{", operations=2)
            script[repair_job(case_id)] = success(valid_raw(case_id), operations=2)
        result = workspace.run(script)
        self.assertEqual(adapter.STATUS_BUDGET_EXHAUSTED, result["status"])
        self.assertEqual(("DEV3_08", "repair_1"), (result["stopped_at_case"], result["stopped_at_phase"]))
        self.assertEqual(list(CASE_IDS[:7]), result["completed_cases"])
        self.assertEqual(list(CASE_IDS[7:]), result["uncompleted_cases"])
        self.assertEqual(30, result["operations"]["pacing_reservations"])
        self.assertIs(False, result["prediction_lock_created"])
        self.assertIs(False, result["terminal_outcomes_fabricated"])
        self.assertNotIn(repair_job("DEV3_08"), workspace.calls)
        self.assertEqual(15, len(workspace.calls))
        private = workspace.private
        self.assertEqual(7, len(list((private / "case_results").iterdir())))
        self.assertTrue((private / "raw_primary" / "DEV3_08.txt").is_file())
        self.assertFalse((private / f"{adapter.TUNING_RESULT_ID}.json").exists())
        self.assertFalse((private / f"{adapter.PREDICTION_MANIFEST_ID}.json").exists())
        self.assertTrue((private / f"{adapter.INCOMPLETE_RECORD_ID}.json").is_file())
        with self.assertRaises(adapter.PriorExecutionState):
            workspace.run(script)
        self.assertEqual(15, len(workspace.calls))
        with self.assertRaises(adapter.P4Dev3Error):
            workspace.verify()

    def test_budget_exhausted_inside_a_job_refuses_the_call_and_fabricates_no_outcome(self):
        workspace = Workspace(self)
        result = workspace.run(operations=3, maximum_operations=29)
        self.assertEqual(adapter.STATUS_BUDGET_EXHAUSTED, result["status"])
        self.assertEqual(("DEV3_10", "primary"), (result["stopped_at_case"], result["stopped_at_phase"]))
        self.assertEqual(list(CASE_IDS[:9]), result["completed_cases"])
        self.assertEqual(["DEV3_10"], result["uncompleted_cases"])
        self.assertEqual((29, 29, 1), (result["operations"]["pacing_reservations"],
                                       result["operations"]["operation_budget"],
                                       result["operations"]["budget_refusals"]))
        self.assertFalse((workspace.private / "case_results" / "DEV3_10.json").exists())
        self.assertNotIn("DEV3_10", result["terminal_statuses_of_completed_cases"])

    def test_budget_is_restart_persistent_and_cannot_be_raised(self):
        root, _, _ = write_archive(self)
        checkpoints = root / "checkpoints"
        pacer, budget, _ = adapter.build_durable_stack(checkpoints, LOCK_SHA, maximum_operations=3)
        budget.acquire()
        budget.acquire()
        _, restarted, _ = adapter.build_durable_stack(checkpoints, LOCK_SHA, maximum_operations=3)
        self.assertEqual((2, 1), (restarted.consumed(), restarted.remaining()))
        restarted.acquire()
        _, again, _ = adapter.build_durable_stack(checkpoints, LOCK_SHA, maximum_operations=3)
        with self.assertRaises(runner_v1.OperationBudgetExhausted):
            again.acquire()
        self.assertEqual(3, again.consumed())
        self.assertEqual({"artifact", "experiment_lock_sha256", "maximum_real_provider_operations", "pacing_checkpoint",
                          "consumed", "remaining", "refusals", "within_budget"}, set(again.snapshot()))
        for maximum in (4, 30):
            with self.assertRaisesRegex(CheckpointIntegrityError, "budget identity"):
                adapter.build_durable_stack(checkpoints, LOCK_SHA, maximum_operations=maximum)
        for maximum in (31, 0, 30.0, True):
            with self.subTest(maximum=maximum), self.assertRaises(adapter.P4Dev3Error):
                adapter.build_durable_stack(root / f"other_{maximum}", LOCK_SHA, maximum_operations=maximum)
        self.assertEqual(30, adapter.MAX_REAL_PROVIDER_OPERATIONS)
        self.assertEqual((6, 60), (pacer.max_operations, pacer.window_seconds))


class GuardsAndEntryPointTests(unittest.TestCase):
    def test_preflight_makes_no_provider_credential_or_checkpoint(self):
        workspace = Workspace(self)
        with mock.patch.object(adapter, "load_runtime_config", side_effect=AssertionError("credentials")) as credentials, \
                mock.patch("tools.story_extraction.run_m4_04b2_dev_predictions_v1.official_client_factory",
                           side_effect=AssertionError("client")) as client, \
                mock.patch.object(adapter, "GeminiDevWindowTransport", side_effect=AssertionError("transport")) as transport, \
                mock.patch.object(adapter, "build_durable_stack", side_effect=AssertionError("executor")) as stack:
            checked = adapter.preflight(input_archive=workspace.archive, private_root=workspace.private,
                                        expected_input_sha256=workspace.sha256, check_environment=False)
            report = adapter.preflight_report(checked)
        for patched in (credentials, client, transport, stack):
            patched.assert_not_called()
        self.assertEqual(
            ("PREFLIGHT_PASS", 10, True, 10, 10, 10, 10, 0, 10, [], 0, False),
            (report["status"], report["cases"], report["case_order_exact"], report["m3_ingestion_and_report_binding"],
             report["p4_compiler_contexts"], report["p4_run_identities"], report["prepared_inputs_reproduced"],
             report["p3_provenance_in_p4_contexts"], report["primary_requests_pass_protocol_v2_checker"],
             report["existing_execution_state"], report["provider_operations"], report["credential_loaded"]),
        )
        self.assertEqual([], [path for path in (workspace.private / "checkpoints").rglob("*") if path.is_file()])
        self.assertEqual(51, sum(path.is_file() for path in (workspace.private / "input").rglob("*")))
        self.assertEqual([], adapter.existing_execution_state(checked["layout"]))

    def test_failed_preflight_stops_before_provider_construction(self):
        workspace = Workspace(self)
        with mock.patch.object(adapter, "build_durable_stack", side_effect=AssertionError("executor")) as stack:
            with self.assertRaises(adapter.PreflightFailure):
                adapter.run(input_archive=workspace.archive, private_root=workspace.private,
                            expected_input_sha256="1" * 64, transport_factory=workspace.factory({}))
            with self.assertRaises(adapter.PreflightFailure):
                adapter.run(input_archive=workspace.archive, private_root=workspace.private,
                            expected_input_sha256=workspace.sha256, expected_lock_sha256="0" * 64,
                            transport_factory=workspace.factory({}))
            with mock.patch.dict(protocol.BOUND_FILES, {"tools/story_extraction/draft_compiler_v1_1.py": "0" * 64}):
                with self.assertRaises(adapter.PreflightFailure):
                    workspace.run()
        stack.assert_not_called()
        self.assertEqual([], workspace.calls)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = adapter.main(["--mode", "preflight", "--input-archive", str(workspace.archive),
                                 "--private-root", str(workspace.private)])
        self.assertEqual(3, code)
        self.assertTrue(output.getvalue().startswith("M4_04B4C_DEV3_PREFLIGHT_FAILED"))

    def test_real_dev3_input_only_with_the_accepted_transport_and_a_named_lock(self):
        workspace = Workspace(self)
        with self.assertRaisesRegex(adapter.P4Dev3Error, "Only the accepted transport"):
            adapter.run(input_archive=workspace.archive, private_root=workspace.private,
                        transport_factory=workspace.factory({}))
        with self.assertRaisesRegex(adapter.P4Dev3Error, "Only the accepted transport"):
            adapter.run(input_archive=workspace.archive, private_root=workspace.private,
                        expected_input_sha256=workspace.sha256)
        with self.assertRaisesRegex(adapter.P4Dev3Error, "must name the committed experiment lock"):
            adapter.run(input_archive=workspace.archive, private_root=workspace.private)
        with self.assertRaisesRegex(adapter.P4Dev3Error, "one private root"):
            adapter.run(input_archive=workspace.archive, private_root=workspace.private, expected_lock_sha256="0" * 64)
        self.assertEqual([], workspace.calls)

    def test_existing_state_of_any_kind_blocks_a_run(self):
        for folder in ("checkpoints", "raw_primary", "case_results", "telemetry"):
            with self.subTest(state=folder):
                workspace = Workspace(self)
                (workspace.private / folder).mkdir(parents=True)
                (workspace.private / folder / "leftover.json").write_bytes(b"{}")
                with self.assertRaises(adapter.PriorExecutionState):
                    workspace.run()
                self.assertEqual([], workspace.calls)

    def test_integrity_error_during_a_run_stops_fail_closed_and_keeps_state(self):
        workspace = Workspace(self)

        def broken(budget, spec):
            budget.acquire()
            raise CheckpointIntegrityError("Credential lock mismatch")

        with self.assertRaises(CheckpointIntegrityError):
            workspace.run({primary_job("DEV3_03"): broken})
        private = workspace.private
        self.assertEqual(2, len(list((private / "case_results").iterdir())))
        self.assertFalse((private / f"{adapter.TUNING_RESULT_ID}.json").exists())
        self.assertFalse((private / f"{adapter.INCOMPLETE_RECORD_ID}.json").exists())
        with self.assertRaises(adapter.PriorExecutionState):
            workspace.run()
        self.assertEqual(3, len(workspace.calls))

    def test_changed_lock_during_a_run_stops_before_the_next_request(self):
        workspace = Workspace(self)

        def then_change(budget, spec):
            response = success(valid_raw("DEV3_02"))(budget, spec)
            patcher = mock.patch.object(adapter, "REPAIR_POLICY", {**adapter.REPAIR_POLICY, "maximum_per_case": 2})
            patcher.start()
            self.addCleanup(patcher.stop)
            return response

        with self.assertRaises(CheckpointIntegrityError):
            workspace.run({primary_job("DEV3_02"): then_change})
        self.assertEqual([primary_job("DEV3_01"), primary_job("DEV3_02")], workspace.calls)

    def test_private_root_must_be_new_ignored_storage(self):
        repository = adapter.REPO_ROOT
        for root in (repository, repository / "benchmarks" / "x", repository / ".local" / "m4_04b3h_dev3_predictions",
                     repository / ".local" / "m4_04b4br_p4_projection_smoke" / "x",
                     Path(tempfile.gettempdir()) / "dev3_gold" / "x", Path(tempfile.gettempdir()) / "holdout_run"):
            with self.subTest(root=root.name), self.assertRaises(adapter.P4Dev3Error):
                adapter.private_layout(root)
        self.assertEqual(".local", adapter.DEFAULT_PRIVATE_ROOT.relative_to(repository).parts[0])
        self.assertEqual("m4_04b4c_p4_dev3_tuning", adapter.DEFAULT_PRIVATE_ROOT.name)

    def test_command_line_needs_the_b4c_token_and_takes_no_gold(self):
        self.assertEqual("M4-04B4C", adapter.LIVE_AUTHORIZATION_TOKEN)
        self.assertNotEqual(dev3_layout.LIVE_AUTHORIZATION_TOKEN, adapter.LIVE_AUTHORIZATION_TOKEN)
        for token in ("", "M4-04B3H", "yes"):
            output = io.StringIO()
            with mock.patch.object(adapter, "run") as run, contextlib.redirect_stdout(output):
                code = adapter.main(["--mode", "run", "--input-archive", "x.zip",
                                     "--authorize-live-provider-operations", token])
            run.assert_not_called()
            self.assertEqual((2, "M4_04B4C_RUN_STOPPED_FAIL_CLOSED: P4Dev3Error"), (code, output.getvalue().strip()))
        for option in ("--gold", "--gold-archive", "--evaluate", "--protocol"):
            with self.subTest(option=option), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    adapter.main(["--mode", "verify-lock", option, "x"])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(0, adapter.main(["--mode", "verify-lock"]))
        self.assertEqual(0, json.loads(output.getvalue())["provider_operations"])

    def test_adapter_has_no_gold_evaluator_p3_builder_v1_protocol_or_direct_sdk_path(self):
        for function in (adapter.run, adapter.preflight, adapter.verify_run, adapter.execute_case,
                         adapter.load_p4_case_inputs):
            names = set(inspect.signature(function).parameters)
            self.assertFalse(any("gold" in name.lower() or "evaluat" in name.lower() or "score" in name.lower()
                                 for name in names))
        source = Path(adapter.__file__).read_text(encoding="utf-8")
        for forbidden in ("import google", "from google", "genai.", "official_client_factory", "generate_content",
                          "m4_04b4b_p4_protocol_v1 import", "run_m4_04b4br_p4_projection_smoke_v1",
                          "build_stage1_spec", "evaluate_case", "str(error.args", "traceback"):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("m4_04b3f_dev3_p3_protocol_v1 import", source)
        self.assertNotIn("dev3_layout.execute_case", source)
        self.assertNotIn("dev3_layout.run(", source)


class FakeProviderError(Exception):
    """Shaped like an SDK API error: a status code, a structured status and a message."""

    def __init__(self, code, status):
        super().__init__(f"{code} {status}. {MARKER} provider message text")
        self.code = code
        self.status = status


class AcceptedTransportRehearsalTests(unittest.TestCase):
    """The live path end to end with the SDK client replaced. No network, no real key."""

    FAKE_KEY = "synthetic-credential-3-not-a-real-key"

    def setUp(self):
        self.workspace = Workspace(self)
        self.env = self.workspace.root / "absent.env"
        self.requests = []
        self.keys = []
        _, self.lock_sha = adapter.locked_experiment()

    def run_live_path(self, respond, environ=None):
        from tools.story_extraction.gemini_key_pool_v1 import load_runtime_config

        environ = {"GEMINI_API_KEY_3": self.FAKE_KEY} if environ is None else environ
        workspace = self.workspace

        def fake_client_factory(api_key):
            self.keys.append(api_key)

            def generate(**kwargs):
                self.requests.append(kwargs)
                return respond(len(self.requests), kwargs)
            return SimpleNamespace(generate=generate)

        patches = self.identity_patches() + (
            mock.patch.object(adapter, "load_runtime_config", side_effect=lambda: load_runtime_config(self.env, environ)),
            mock.patch.object(dev3_layout, "verify_execution_environment",
                              return_value={"method": "SYNTHETIC_TEST_ENVIRONMENT", "source_commit": "0" * 40}),
            mock.patch.object(adapter, "_tracked", return_value=True),
            mock.patch("tools.story_extraction.run_m4_04b2_dev_predictions_v1.official_client_factory",
                       side_effect=fake_client_factory),
            mock.patch("time.sleep"),
        )
        with contextlib.ExitStack() as stack, contextlib.redirect_stdout(io.StringIO()):
            for patch in patches:
                stack.enter_context(patch)
            return adapter.run(input_archive=workspace.archive, private_root=workspace.private,
                               expected_input_sha256=workspace.sha256, expected_lock_sha256=self.lock_sha)

    def identity_patches(self):
        """The synthetic archive stands in for the DEV3 input, so its hash stands in for the locked one."""
        workspace = self.workspace
        return (
            mock.patch.object(adapter, "DEV3_INPUT_SHA256", workspace.sha256),
            mock.patch.object(dev3_layout, "DEV3_INPUT_SHA256", workspace.sha256),
            mock.patch.object(adapter, "DEFAULT_PRIVATE_ROOT", workspace.private),
            mock.patch.object(adapter, "locked_experiment", side_effect=lambda expected=None, **_: ({}, self.lock_sha)),
            workspace.clock.patched(),
        )

    def verify_live_path(self):
        with contextlib.ExitStack() as stack:
            for patch in self.identity_patches():
                stack.enter_context(patch)
            return adapter.verify_run(input_archive=self.workspace.archive, private_root=self.workspace.private,
                                      expected_input_sha256=self.workspace.sha256)

    @staticmethod
    def case_of(kwargs):
        return next(case_id for case_id in CASE_IDS if f"{case_id}" in kwargs["user_content"])

    def test_ten_cases_through_the_accepted_transport_with_one_repair(self):
        def respond(count, kwargs):
            case_id = self.case_of(kwargs)
            repairing = kwargs["system_instruction"] == contract.prompt_material()["repair_system"]
            text = "{" if case_id == "DEV3_04" and not repairing else valid_raw(case_id)
            return SimpleNamespace(text=text, usage_metadata=None, model_version="synthetic-model-version")

        result = self.run_live_path(respond)
        self.assertEqual(adapter.STATUS_COMPLETE, result["status"])
        self.assertEqual(11, len(self.requests))
        self.assertEqual((11, 11, 10), (result["operations"]["real_provider_operations"],
                                        result["operations"]["pacing_reservations"],
                                        result["metrics"]["terminal_outcomes"]["STRUCTURAL_VALID"]))
        self.assertEqual("ACCEPTED_GEMINI_DEV_WINDOW_TRANSPORT", result["transport"])
        native, full = projection.load_tracked_projection(), materializer.load_tracked_model_schema()
        for request in self.requests:
            self.assertEqual("gemini-3.5-flash-lite", request["model"])
            self.assertEqual(native, request["generation_config"]["response_json_schema"])
            self.assertEqual({"temperature", "max_output_tokens", "response_json_schema"}, set(request["generation_config"]))
            self.assertEqual((0, 16384), (request["generation_config"]["temperature"],
                                          request["generation_config"]["max_output_tokens"]))
            self.assertEqual(full, contract.extract_prompt_schema(
                request["system_instruction"], contract.SCHEMA_SECTION_MARKER, contract.REGISTRY_SECTION_MARKER))
        self.assertEqual({self.FAKE_KEY}, set(self.keys))
        self.assertNotIn(self.FAKE_KEY, self.workspace.private_text())
        self.assertEqual("0" * 40, result["source_commit"])
        self.assertEqual(self.lock_sha, result["experiment_lock_sha256"])
        self.assertEqual("POST_RUN_INTEGRITY_PASS", self.verify_live_path()["status"])
        self.assertEqual(11, len(self.requests))

    def test_rejected_and_unauthenticated_requests_end_as_transport_failures_without_repair(self):
        def respond(count, kwargs):
            case_id = self.case_of(kwargs)
            if case_id == "DEV3_02":
                raise FakeProviderError(403, "PERMISSION_DENIED")
            return SimpleNamespace(text=valid_raw(case_id), usage_metadata=None, model_version="synthetic")

        result = self.run_live_path(respond)
        by_case = {item["case_id"]: item for item in result["predictions"]}
        self.assertEqual("TRANSPORT_FAILURE", by_case["DEV3_02"]["terminal_status"])
        self.assertFalse(by_case["DEV3_02"]["repair_used"])
        self.assertEqual(10, len(self.requests))
        self.assertEqual({"STRUCTURAL_VALID": 9, "STRUCTURAL_FAILURE": 0, "TRANSPORT_FAILURE": 1},
                         {status: result["metrics"]["terminal_outcomes"][status] for status in adapter.TERMINAL_STATUSES})
        text = self.workspace.private_text()
        self.assertNotIn(MARKER, text)
        self.assertNotIn(self.FAKE_KEY, text)

    def test_only_the_locked_credential_slot_can_run(self):
        for environ in ({}, {"GEMINI_API_KEY_1": "synthetic-credential-1"}):
            with self.subTest(slots=sorted(environ)), self.assertRaises(adapter.P4Dev3Error):
                self.run_live_path(lambda count, kwargs: None, environ=environ)
        self.assertEqual(([], []), (self.keys, self.requests))
        self.assertEqual([], adapter.existing_execution_state(adapter.private_layout(self.workspace.private)))


class PublishedResultTests(unittest.TestCase):
    """Checks of the public result files. They exist only after the live run."""

    def setUp(self):
        if not adapter.PREDICTION_LOCK_PATH.exists() or not adapter.RESULT_RECORD_PATH.exists():
            self.skipTest("The M4-04B4C result has not been published")
        self.lock_text = adapter.PREDICTION_LOCK_PATH.read_text(encoding="utf-8")
        self.result_text = adapter.RESULT_RECORD_PATH.read_text(encoding="utf-8")
        self.lock = yaml.safe_load(self.lock_text)
        self.record = yaml.safe_load(self.result_text)

    def test_published_prediction_lock_is_valid_and_bound_to_the_committed_experiment(self):
        digest = adapter.validate_public_prediction_lock(self.lock)
        _, lock_sha = adapter.locked_experiment()
        self.assertEqual(lock_sha, self.lock["experiment"]["experiment_lock_sha256"])
        self.assertEqual(protocol.normalized_file_sha256(Path(adapter.__file__)), self.lock["experiment"]["adapter_sha256"])
        self.assertEqual(digest, self.record["prediction_set_sha256"])
        self.assertEqual(lock_sha, self.record["experiment"]["experiment_lock_sha256"])
        self.assertRegex(self.lock["experiment"]["prelive_commit"], r"^[0-9a-f]{40}$")
        self.assertEqual("ACCEPTED_GEMINI_DEV_WINDOW_TRANSPORT", self.record["experiment"]["transport"])
        self.assertEqual(sha256_bytes(adapter.PREDICTION_LOCK_PATH.read_bytes().replace(b"\r\n", b"\n")),
                         self.record["public_prediction_lock"]["file_sha256"])

    def test_published_result_is_a_labelled_tuning_result_with_no_quality_claim(self):
        record = self.record
        self.assertEqual(adapter.PUBLIC_RESULT_FIELDS, tuple(record))
        self.assertEqual("M4_04B4C_P4_DEV3_TUNING_COMPLETE", record["status"])
        self.assertEqual("TUNING_COMPARISON_NOT_BLIND_VALIDATION", record["comparison_with_p3"]["label"])
        self.assertIs(False, record["claims"]["semantic_quality_claim"])
        self.assertTrue(all(record["integrity"]["checks"].values()))
        self.assertEqual(list(adapter.LIMITATIONS), record["limitations"])
        terminal = record["structural_metrics"]["terminal_outcomes"]
        self.assertEqual(10, terminal["case_completion_count"])
        self.assertEqual(10, sum(terminal[status] for status in adapter.TERMINAL_STATUSES))
        self.assertEqual(adapter.recommended_next_action(terminal["STRUCTURAL_VALID"]),
                         record["recommended_next_action"]["action"])
        accounting = record["transport_and_accounting"]
        self.assertLessEqual(accounting["real_provider_operations"], 30)
        self.assertEqual("PASS", accounting["pacing_invariant"])
        self.assertEqual({"DEV3_gold_opened": False, "holdout_opened": False, "semantic_scoring_performed": False,
                          "DEV4_created": False, "P3_predictions_modified": False,
                          "provider_calls_after_prediction_lock": 0}, record["boundaries"])
        for text in (self.lock_text, self.result_text):
            self.assertNotRegex(text, r"AIza[0-9A-Za-z_\-]{10,}")
            self.assertNotIn("GEMINI_API_KEY", text)

    def test_project_state_records_the_result(self):
        state = (adapter.REPO_ROOT / "docs/PROJECT_STATE.md").read_text(encoding="utf-8")
        self.assertIn(f"Status: {self.record['status']}", state)
        self.assertIn(self.record["prediction_set_sha256"], state)
        self.assertIn(self.record["recommended_next_action"]["action"], state)


if __name__ == "__main__":
    unittest.main()
