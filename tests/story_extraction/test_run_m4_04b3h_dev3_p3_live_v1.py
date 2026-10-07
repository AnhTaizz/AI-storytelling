"""Offline readiness tests for the DEV3 P3 live execution adapter (M4-04B3H1).

Synthetic story fixtures, synthetic archives and mocked transports only. No DEV3 package,
credential or provider is touched.
"""
import ast
import contextlib
import copy
from dataclasses import replace
import functools
import hashlib
import inspect
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

import yaml

from tests.story_extraction import fixture_builder as fx
from tools.story_extraction import m4_04b3h0_dev3_decision_lock_v1 as decision_lock
from tools.story_extraction import run_m4_04b3g_dev3_p3_predictions_v1 as runner_core
from tools.story_extraction import run_m4_04b3h_dev3_p3_live_v1 as live
from tools.story_extraction.dev3_seal_v1 import deterministic_zip_bytes
from tools.story_extraction.draft_compiler_v1 import DraftCompilerContext
from tools.story_extraction.draft_compiler_v1_1 import prepare_story_extraction_draft_v1_1
from tools.story_extraction.draft_coverage_v1_1 import canonical_gold_to_draft_v1_1
from tools.story_extraction.durable_research_executor_v1 import (
    CheckpointIntegrityError,
    DurableResearchExecutor,
    DurableTransportFailure,
    PersistentRollingOperationPacer,
)
from tools.story_extraction.gemini_key_pool_v1 import load_runtime_config
from tools.story_extraction.m4_04b3f_dev3_p3_protocol_v1 import (
    CASE_IDS,
    CREDENTIAL_SLOT,
    MODEL,
    REPO_ROOT,
    build_primary_spec,
    canonical_json_bytes,
    normalized_file_sha256,
    sha256_bytes,
    write_protocol,
)
from tools.story_extraction.run_m4_04b2_dev_predictions_v1 import GeminiDevWindowTransport


READINESS_RECORD = REPO_ROOT / "benchmarks/m4_extraction/M4_04B3H1_DEV3_LIVE_EXECUTION_READINESS.yaml"
ADAPTER_FILE = REPO_ROOT / live.ADAPTER_PATH
MANIFEST = live.SEALED_INPUT_CONTRACT["manifest_member"]
FIXTURES = (
    "c01_named_character", "c02_two_mentions_one_entity", "c05_event_occurred", "c06_participant",
    "c07_location", "c08_possession", "c09_ownership", "c10_relationship_state",
    "c11_explicit_emotion", "c25_negated_event",
)
SYNTHETIC_WORDS = ("Mira", "Joren", "lantern", "courtyard", "gate")


class _Kill(BaseException):
    """Simulates the process dying inside a provider window."""


@functools.lru_cache(maxsize=1)
def _synthetic():
    """Ten synthetic cases in the assumed sealed layout: (archive entries, valid drafts)."""
    entries, drafts, rows = {}, {}, []
    for case_id, name in zip(CASE_IDS, FIXTURES):
        text = fx.CASES[name][0].encode("utf-8")
        ingestion, base, gold = fx.build(name)
        scope = gold["scope"]
        context = DraftCompilerContext(
            base, scope["passage_inputs"], scope["as_of_position"], scope["profile_id"],
            live.PROCESS_ID, live.PROCESS_VERSION, f"P3_{case_id}", ingestion,
        )
        drafts[case_id] = canonical_gold_to_draft_v1_1(gold, context)[0]
        folder = f"cases/{case_id}"
        entries[f"{folder}/unit.txt"] = text
        entries[f"{folder}/m3_manifest.json"] = canonical_json_bytes({
            "contract_version": "LIGHT_NOVEL_INGESTION/v0", "story_id": "story-syn-m4",
            "stream_id": "stream-syn-m4", "source_language": "en",
            "documents": [{"document_id": "srcdoc-syn-m4", "order": 1, "path": "unit.txt",
                           "expected_sha256": hashlib.sha256(text).hexdigest()}],
        })
        entries[f"{folder}/base_document.json"] = canonical_json_bytes(base)
        entries[f"{folder}/prepared_draft_input.json"] = canonical_json_bytes(
            prepare_story_extraction_draft_v1_1(context)
        )
        entries[f"{folder}/ingestion_report.json"] = canonical_json_bytes(ingestion.ingestion_report())
        rows.append({
            "case_id": case_id,
            "base_document_member": f"{folder}/base_document.json",
            "prepared_input_member": f"{folder}/prepared_draft_input.json",
            "m3_manifest_member": f"{folder}/m3_manifest.json",
            "passage_inputs": scope["passage_inputs"],
            "as_of_position": scope["as_of_position"],
            "profile_id": scope["profile_id"],
        })
    entries[MANIFEST] = canonical_json_bytes({
        "artifact": live.SEALED_INPUT_CONTRACT["artifact"],
        "case_count": len(CASE_IDS),
        "draft_interface": live.SEALED_INPUT_CONTRACT["draft_interface"],
        "cases": rows,
    })
    return entries, drafts


def synthetic_entries():
    return dict(_synthetic()[0])


def valid_responses():
    return {f"M4B3F_P3_{case_id}_PRIMARY": json.dumps(draft, ensure_ascii=False)
            for case_id, draft in _synthetic()[1].items()}


def edit_manifest(entries, change):
    manifest = json.loads(entries[MANIFEST])
    change(manifest)
    entries[MANIFEST] = canonical_json_bytes(manifest)
    return entries


class MockTransport:
    """In-memory transport with the accepted window signature. Zero real operations."""

    def __init__(self, responses, pacer=None):
        self.responses = dict(responses)
        self.pacer = pacer
        self.calls = []

    def __call__(self, spec, window, request_id):
        self.calls.append(spec)
        outcome = self.responses[spec.job_id]
        if isinstance(outcome, BaseException):
            raise outcome
        if self.pacer is not None:
            self.pacer.acquire()
        return {
            "raw_content": outcome,
            "model_requested": spec.model,
            "slot_id": spec.credential_slot,
            "transport_attempts": [{"model": spec.model, "slot_id": spec.credential_slot}],
            "attempt_accounting": {"total_provider_attempts": 1},
        }

    @property
    def job_ids(self):
        return [spec.job_id for spec in self.calls]


class Workspace:
    """A temporary synthetic archive, the real canonical protocol and a private root."""

    def __init__(self, test, entries=None):
        directory = tempfile.TemporaryDirectory(prefix="m4b3h1_")
        test.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.archive = self.root / "synthetic_input.zip"
        self.archive.write_bytes(deterministic_zip_bytes(entries or synthetic_entries()))
        self.sha256 = sha256_bytes(self.archive.read_bytes())
        self.protocol = self.root / "protocol.json"
        write_protocol(self.protocol)
        self.private = self.root / "private"
        self.public_lock = self.root / "public_lock.yaml"

    def run(self, transport):
        with contextlib.redirect_stdout(io.StringIO()):
            return live.run(
                protocol_path=self.protocol, input_archive=self.archive, private_root=self.private,
                public_lock_path=self.public_lock, expected_input_sha256=self.sha256, transport=transport,
            )

    def load(self):
        return live.load_case_inputs(self.archive, self.private / "input", expected_input_sha256=self.sha256)

    def stack(self):
        validated = live.verify_locked_bindings(self.protocol)
        guard = live.build_guard(validated, self.archive, self.sha256)
        pacer, executor = live.build_durable_stack(self.private / "checkpoints")
        return guard, pacer, executor

    def provider(self, transport):
        guard, _, executor = self.stack()
        return live.DurableFirstSuccessProvider(executor, transport, guard, counts_real_provider_operations=False)


def first_success(provider, spec):
    with contextlib.redirect_stdout(io.StringIO()):
        return provider.first_success(spec)


class ExecutionEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.lf = b"line one\nline two\n"
        self.crlf_files = {}
        for path, pinned in live.CRLF_BOUND_HISTORICAL_FILES.items():
            self.crlf_files[path] = (path, live._blob_oid(self.lf), self.lf.replace(b"\n", b"\r\n"))

    def classify(self, extra):
        return live.classify_tracked_files(list(self.crlf_files.values()) + extra)

    def test_exactly_two_historical_files_may_differ_from_their_blobs(self):
        self.assertEqual(
            {
                "schemas/story_extraction/story_extraction_draft_v1.schema.json":
                    "498edf8dba8d45b80380a180d1383787f5c0e4ecea5060254883cc27c7d83e80",
                "tools/story_extraction/draft_compiler_v1.py":
                    "bcd15328cefafe86dd8e686fb35a155b2cb2c261b20017486ed106e85371d836",
            },
            live.CRLF_BOUND_HISTORICAL_FILES,
        )
        protected = set(decision_lock.PROTECTED_EXTRACTOR_STACK) | set(decision_lock.PROTECTED_EVALUATION_STACK)
        self.assertFalse(protected & set(live.CRLF_BOUND_HISTORICAL_FILES))

    def test_byte_identity_classification_fails_closed(self):
        pinned = {path: sha256_bytes(item[2]) for path, item in self.crlf_files.items()}
        with mock.patch.object(live, "CRLF_BOUND_HISTORICAL_FILES", pinned):
            clean = self.classify([("a.py", live._blob_oid(self.lf), self.lf)])
            self.assertEqual([], clean["violations"])
            self.assertEqual((3, 1), (clean["tracked_files"], clean["byte_identical_to_blob"]))
            crlf_elsewhere = self.classify([("a.py", live._blob_oid(self.lf), self.lf.replace(b"\n", b"\r\n"))])
            self.assertEqual(["a.py"], crlf_elsewhere["violations"])
            first = next(iter(self.crlf_files))
            self.crlf_files[first] = (first, live._blob_oid(self.lf), self.lf)
            self.assertEqual([first], self.classify([])["violations"])
            del self.crlf_files[first]
            self.assertEqual([first], self.classify([])["violations"])

    def test_committed_environment_record_is_valid_and_fully_green(self):
        record = yaml.safe_load(READINESS_RECORD.read_text(encoding="utf-8"))
        environment = record["execution_environment"]
        self.assertTrue(all(value == "PASS" for value in live.validate_environment_record(environment).values()))
        self.assertEqual(402, environment["byte_identical_to_blob"])
        self.assertTrue(record["historical_line_ending_failures"]["eliminated_in_execution_checkout"])
        self.assertEqual(normalized_file_sha256(ADAPTER_FILE), record["live_adapter"]["sha256"])
        self.assertEqual(normalized_file_sha256(Path(__file__)), record["live_adapter"]["focused_tests_sha256"])
        for name in ("provider_or_API_calls",):
            self.assertEqual(0, record["boundaries"][name])
        for name in ("DEV3_input_opened", "DEV3_gold_opened", "holdout_accessed", "prediction_started"):
            self.assertIs(False, record["boundaries"][name])

    def test_environment_record_validation_rejects_any_weakening(self):
        environment = yaml.safe_load(READINESS_RECORD.read_text(encoding="utf-8"))["execution_environment"]
        mutations = (
            lambda r: r.update(core_autocrlf="true"),
            lambda r: r.update(method="OTHER"),
            lambda r: r.update(violations=["x"]),
            lambda r: r.update(byte_identical_to_blob=r["tracked_files"]),
            lambda r: r["crlf_exception_files"].update({"extra.py": "0" * 64}),
            lambda r: r["full_offline_suites"]["story_extraction"].update(failures=5),
            lambda r: r["full_offline_suites"]["story_extraction"].update(result="PASS_WITH_TOLERATED_FAILURES"),
            lambda r: r["full_offline_suites"].pop("story_benchmark"),
        )
        for mutate in mutations:
            record = copy.deepcopy(environment)
            mutate(record)
            with self.assertRaises(live.LiveExecutionError):
                live.validate_environment_record(record)


class LockedBindingTests(unittest.TestCase):
    def test_exact_protocol_decision_record_and_input_bindings(self):
        self.assertEqual("f9cf1c25a21bb3bfc910b8e218c8dac9f032d67957f8d7cb58397134a0504bae", live.LOCKED_PROTOCOL_SHA256)
        self.assertEqual("5826854dfe6828ebea67e0d4c089fbda148fcc89da9efc80f1afb244aa329735", live.DECISION_RECORD_SHA256)
        self.assertEqual(decision_lock.DECISION_RECORD_SHA256, live.DECISION_RECORD_SHA256)
        self.assertEqual("47ae7c743065f8ff001f4db6a398df2edf1db094383b1fe2d0c3a05ab40c55c7", live.DEV3_INPUT_SHA256)
        self.assertEqual("b5b2258d46608015ff60de2c660fba521029ff4716c7c1cc3b3735c55dfd34a9", live.DEV3_GOLD_SHA256)
        self.assertEqual(
            "a07a26240c9d30d96bf455a4f88173a38a3b1538a8de2d32d3f09b7402be5087",
            normalized_file_sha256(Path(runner_core.__file__)),
        )
        self.assertIn(live.LOCKED_PROTOCOL_SHA256, live.EXECUTOR_PROTOCOL_ID)
        self.assertIn(live.DECISION_RECORD_SHA256, live.EXECUTOR_PROTOCOL_ID)
        self.assertEqual((MODEL, CREDENTIAL_SLOT), ("gemini-3.5-flash-lite", "gemini_slot_3"))

    def test_wrong_protocol_fails_before_input_or_provider(self):
        workspace = Workspace(self)
        workspace.protocol.write_text("{}\n", encoding="utf-8")
        transport = MockTransport(valid_responses())
        with mock.patch.object(live, "verify_archive_identity") as archive_gate:
            with self.assertRaisesRegex(live.LiveExecutionError, "protocol verification failed"):
                workspace.run(transport)
        archive_gate.assert_not_called()
        self.assertEqual([], transport.calls)

    def test_changed_decision_record_fails_closed(self):
        workspace = Workspace(self)
        transport = MockTransport(valid_responses())
        with mock.patch.object(decision_lock, "LABEL_SAFE_REVIEW", "DEV3_HOLDOUT_ELIGIBLE"):
            with self.assertRaisesRegex(live.LiveExecutionError, "H0 decision record"):
                workspace.run(transport)
        with mock.patch.object(live, "DECISION_RECORD_SHA256", "0" * 64):
            with self.assertRaisesRegex(live.LiveExecutionError, "identity mismatch"):
                workspace.run(transport)
        self.assertEqual([], transport.calls)

    def test_changed_protected_stack_fails_closed_before_and_during_execution(self):
        workspace = Workspace(self)
        transport = MockTransport(valid_responses())
        with mock.patch.object(decision_lock, "normalized_file_sha256", return_value="0" * 64):
            with self.assertRaisesRegex(live.LiveExecutionError, "protected stack"):
                workspace.run(transport)
        provider = workspace.provider(transport)
        spec = build_primary_spec("DEV3_01", workspace.load()[0].prepared_input)
        with mock.patch.object(decision_lock, "normalized_file_sha256", return_value="0" * 64):
            with self.assertRaises(CheckpointIntegrityError):
                first_success(provider, spec)
        self.assertEqual([], transport.calls)

    def test_adapter_reuses_the_accepted_runner_core(self):
        self.assertIs(runner_core.compile_raw_response, live.compile_raw_response)
        self.assertIs(runner_core.execute_case, live.execute_case)
        self.assertIs(runner_core.CaseInput, live.CaseInput)
        self.assertIs(runner_core.FirstSuccessLedger, live.FirstSuccessLedger)
        tree = ast.parse(ADAPTER_FILE.read_text(encoding="utf-8"))
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for alias in node.names}
        modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        for duplicated in ("validate_draft_v1_1", "compile_story_extraction_draft_v1_1", "sanitize_all_blockers",
                           "build_repair_spec", "REPAIR_ELIGIBLE_CATEGORIES", "DraftCompilationErrorV1_1"):
            self.assertNotIn(duplicated, imported)
        self.assertFalse(any("evaluate" in module for module in modules))

    def test_no_gold_or_evaluator_parameter_exists(self):
        for function in (live.preflight, live.run, live.load_case_inputs, live.execute_cases, live.main):
            names = set(inspect.signature(function).parameters)
            self.assertFalse(any("gold" in name.lower() or "evaluat" in name.lower() for name in names))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            live.main(["--mode", "run", "--protocol", "p", "--input-archive", "i", "--gold", "g"])


class InputLoaderTests(unittest.TestCase):
    def test_archive_is_hashed_before_it_is_opened(self):
        workspace = Workspace(self)
        with mock.patch.object(live.zipfile, "ZipFile", side_effect=AssertionError("opened")) as opened:
            with self.assertRaisesRegex(live.LiveExecutionError, "hash mismatch"):
                live.load_case_inputs(workspace.archive, workspace.private / "input")
            with self.assertRaisesRegex(live.LiveExecutionError, "hash mismatch"):
                live.load_case_inputs(workspace.archive, workspace.private / "input", expected_input_sha256="0" * 64)
        opened.assert_not_called()
        self.assertFalse((workspace.private / "input").exists())

    def test_gold_identity_is_rejected_even_when_it_is_the_expected_hash(self):
        workspace = Workspace(self)
        with mock.patch.object(live, "DEV3_GOLD_SHA256", workspace.sha256):
            with self.assertRaisesRegex(live.LiveExecutionError, "gold package is forbidden"):
                workspace.load()
        gold_named = workspace.root / "dev3_gold" / "input.zip"
        gold_named.parent.mkdir()
        gold_named.write_bytes(workspace.archive.read_bytes())
        with self.assertRaisesRegex(live.LiveExecutionError, "Gold-like input path"):
            live.verify_archive_identity(gold_named, workspace.sha256)

    def test_unsafe_archive_members_are_rejected(self):
        base = synthetic_entries()
        removable = "cases/DEV3_01/unit.txt"
        for bad in ("../escape.txt", "/absolute.txt", "cases\\DEV3_01\\unit.txt", "C:/drive.txt",
                    "cases/DEV3_01/gold_batch.json", "cases//double.txt"):
            entries = dict(base)
            entries[bad] = entries.pop(removable)
            buffer = io.BytesIO()
            with live.zipfile.ZipFile(buffer, "w") as archive:
                for name, data in entries.items():
                    info = live.zipfile.ZipInfo("placeholder")
                    info.filename = name  # stored verbatim, including separators zipfile would rewrite
                    archive.writestr(info, data)
            with self.subTest(member=bad), self.assertRaisesRegex(live.LiveExecutionError, "forbidden"):
                live.read_safe_inventory(buffer.getvalue())

    def test_duplicate_members_wrong_count_and_gold_markers_are_rejected(self):
        entries = synthetic_entries()
        buffer = io.BytesIO()
        with live.zipfile.ZipFile(buffer, "w") as archive, self.assertWarns(UserWarning):
            for name, data in entries.items():
                archive.writestr(name, data)
            archive.writestr(MANIFEST, entries[MANIFEST])
        with self.assertRaisesRegex(live.LiveExecutionError, "duplicate"):
            live.read_safe_inventory(buffer.getvalue())
        fewer = dict(entries)
        fewer.pop("cases/DEV3_10/unit.txt")
        with self.assertRaisesRegex(live.LiveExecutionError, "member count"):
            live.read_safe_inventory(deterministic_zip_bytes(fewer))
        marked = edit_manifest(dict(entries), lambda manifest: manifest.update(gold_status="AGENT_DRAFT_GOLD"))
        with self.assertRaisesRegex(live.LiveExecutionError, "Gold marker"):
            live.read_safe_inventory(deterministic_zip_bytes(marked))
        self.assertEqual(51, len(live.read_safe_inventory(deterministic_zip_bytes(entries))))

    def test_extracted_bytes_are_verified_against_the_archive(self):
        workspace = Workspace(self)
        cases = workspace.load()
        self.assertEqual(list(CASE_IDS), [case.case_id for case in cases])
        root = workspace.private / "input"
        self.assertEqual(51, sum(path.is_file() for path in root.rglob("*")))
        for name, data in synthetic_entries().items():
            self.assertEqual(data, (root / name).read_bytes())
        (root / "cases/DEV3_04/unit.txt").write_bytes(b"tampered")
        with self.assertRaisesRegex(live.LiveExecutionError, "byte mismatch"):
            workspace.load()
        (root / "cases/DEV3_04/unit.txt").unlink()
        with self.assertRaisesRegex(live.LiveExecutionError, "inventory mismatch"):
            workspace.load()

    def test_manifest_identity_case_count_and_order_are_exact(self):
        def swap(manifest):
            manifest["cases"][0], manifest["cases"][1] = manifest["cases"][1], manifest["cases"][0]

        failures = (
            (lambda m: m.update(artifact="M4_04B3_DEV2_INPUT_V1"), "manifest identity"),
            (lambda m: m.update(draft_interface="STORY_EXTRACTION_DRAFT_V1"), "manifest identity"),
            (lambda m: m.update(case_count=9), "manifest identity"),
            (swap, "order mismatch"),
            (lambda m: m["cases"].pop(), "order mismatch"),
            (lambda m: m["cases"][3].pop("profile_id"), "incomplete"),
            (lambda m: m["cases"][3].update(base_document_member="cases/DEV3_04/absent.json"), "unknown member"),
        )
        for change, message in failures:
            workspace = Workspace(self, edit_manifest(synthetic_entries(), change))
            with self.subTest(message=message), self.assertRaisesRegex(live.LiveExecutionError, message):
                workspace.load()

    def test_prepared_draft_v1_1_input_must_reproduce_exactly(self):
        workspace = Workspace(self)
        for case in workspace.load():
            self.assertEqual("STORY_EXTRACTION_DRAFT_V1_1", case.prepared_input["draft_version"])
            self.assertEqual(prepare_story_extraction_draft_v1_1(case.compiler_context), case.prepared_input)
            self.assertEqual((live.PROCESS_ID, f"P3_{case.case_id}"),
                             (case.compiler_context.process_id, case.compiler_context.run_id))
        entries = synthetic_entries()
        member = "cases/DEV3_07/prepared_draft_input.json"
        prepared = json.loads(entries[member])
        prepared["draft_version"] = "STORY_EXTRACTION_DRAFT_V1"
        entries[member] = canonical_json_bytes(prepared)
        with self.assertRaisesRegex(live.LiveExecutionError, "does not reproduce exactly"):
            Workspace(self, entries).load()

    def test_frozen_ingestion_binding_is_verified(self):
        entries = synthetic_entries()
        member = "cases/DEV3_02/ingestion_report.json"
        report = json.loads(entries[member])
        report["corpus_fingerprint_sha256"] = "0" * 64
        entries[member] = canonical_json_bytes(report)
        with self.assertRaisesRegex(live.LiveExecutionError, "ingestion binding"):
            Workspace(self, entries).load()
        entries = synthetic_entries()
        entries["cases/DEV3_02/unit.txt"] = b"Different synthetic text."
        with self.assertRaisesRegex(live.LiveExecutionError, "ingestion failed"):
            Workspace(self, entries).load()


class DurableProviderTests(unittest.TestCase):
    def setUp(self):
        self.workspace = Workspace(self)
        self.case = self.workspace.load()[0]
        self.spec = build_primary_spec("DEV3_01", self.case.prepared_input)

    def test_only_the_locked_credential_slot_is_selectable(self):
        keys = {f"GEMINI_API_KEY_{n}": f"synthetic-credential-{n}" for n in (1, 2, 3, 4)}
        config = load_runtime_config(self.workspace.root / "absent.env", keys)
        self.assertEqual("gemini_slot_3", live.select_locked_credential(config).slot_id)
        self.assertEqual(["config"], list(inspect.signature(live.select_locked_credential).parameters))
        del keys["GEMINI_API_KEY_3"]
        with self.assertRaisesRegex(live.LiveExecutionError, "credential slot"):
            live.select_locked_credential(load_runtime_config(self.workspace.root / "absent.env", keys))

    def test_accepted_transport_receives_the_exact_model_and_key(self):
        keys = {f"GEMINI_API_KEY_{n}": f"synthetic-credential-{n}" for n in (1, 2, 3)}
        config = load_runtime_config(self.workspace.root / "absent.env", keys)
        guard, pacer, _ = self.workspace.stack()
        _, executor = live.build_durable_stack(self.workspace.root / "second", forbidden_secrets=tuple(keys.values()))
        seen = {"keys": [], "requests": []}

        def fake_client_factory(api_key):
            seen["keys"].append(api_key)

            def generate(**kwargs):
                seen["requests"].append(kwargs)
                return types.SimpleNamespace(text='{"synthetic": true}', usage_metadata=None, model_version=MODEL)

            return types.SimpleNamespace(generate=generate)

        with mock.patch(
            "tools.story_extraction.run_m4_04b2_dev_predictions_v1.official_client_factory",
            side_effect=fake_client_factory,
        ):
            transport = GeminiDevWindowTransport(live.select_locked_credential(config), pacer, guard)
            provider = live.DurableFirstSuccessProvider(
                executor, transport, guard, counts_real_provider_operations=False
            )
            success = first_success(provider, self.spec)
        self.assertEqual('{"synthetic": true}', success.raw_response)
        self.assertEqual(["synthetic-credential-3"], seen["keys"])
        self.assertEqual(1, len(seen["requests"]))
        self.assertEqual(MODEL, seen["requests"][0]["model"])
        self.assertEqual({"temperature": 0, "max_output_tokens": 16384}, dict(seen["requests"][0]["generation_config"]))
        self.assertEqual(1, pacer.snapshot()["reservation_count"])
        self.assertEqual(0, provider.actual_provider_operations)
        with self.assertRaises(CheckpointIntegrityError):
            GeminiDevWindowTransport(config.credentials[0], pacer, guard)(self.spec, 1, "request")

    def test_durable_limits_and_pacing_are_the_locked_values(self):
        _, pacer, executor = self.workspace.stack()
        self.assertEqual((6, 60.0), (pacer.max_operations, pacer.window_seconds))
        self.assertEqual((3, 3), (executor.max_execution_windows, executor.max_provider_attempts_per_window))
        self.assertEqual(live.EXECUTOR_PROTOCOL_ID, executor.protocol_id)

    def test_pacing_state_survives_restart(self):
        _, pacer, _ = self.workspace.stack()
        pacer.acquire()
        pacer.acquire()
        _, restarted, _ = self.workspace.stack()
        self.assertEqual(2, restarted.snapshot()["reservation_count"])
        self.assertTrue(restarted.snapshot()["restart_persistent"])
        with self.assertRaises(CheckpointIntegrityError):
            PersistentRollingOperationPacer(pacer.checkpoint_path, max_operations=7, window_seconds=60.0)

    def test_first_success_is_immutable_across_restart(self):
        transport = MockTransport({self.spec.job_id: '{"first": true}'})
        first = first_success(self.workspace.provider(transport), self.spec)
        replacement = MockTransport({self.spec.job_id: '{"first": false}'})
        provider = self.workspace.provider(replacement)
        again = first_success(provider, self.spec)
        self.assertEqual(first, replace(again, provider_operations=first.provider_operations))
        self.assertEqual('{"first": true}', again.raw_response)
        self.assertEqual([], replacement.calls)
        self.assertEqual(1, len(transport.calls))

    def test_tampered_checkpoint_fails_closed(self):
        first_success(self.workspace.provider(MockTransport({self.spec.job_id: '{"first": true}'})), self.spec)
        checkpoint = self.workspace.private / "checkpoints" / "jobs" / f"{self.spec.job_id}.json"
        checkpoint.write_text(checkpoint.read_text(encoding="utf-8").replace("true}", "false}"), encoding="utf-8")
        with self.assertRaises(CheckpointIntegrityError):
            first_success(self.workspace.provider(MockTransport({})), self.spec)

    def test_changed_request_fingerprint_fails_closed(self):
        first_success(self.workspace.provider(MockTransport({self.spec.job_id: "{}"})), self.spec)
        transport = MockTransport({self.spec.job_id: "{}"})
        changed = replace(self.spec, user_prompt=self.spec.user_prompt + " changed")
        with self.assertRaisesRegex(CheckpointIntegrityError, "request_fingerprint"):
            first_success(self.workspace.provider(transport), changed)
        self.assertEqual([], transport.calls)

    def test_changed_protocol_identity_fails_closed(self):
        first_success(self.workspace.provider(MockTransport({self.spec.job_id: "{}"})), self.spec)
        transport = MockTransport({self.spec.job_id: "{}"})
        with mock.patch.object(live, "EXECUTOR_PROTOCOL_ID", "M4_04B3F_DEV3_P3_PROTOCOL_V1:" + "0" * 64):
            with self.assertRaisesRegex(CheckpointIntegrityError, "protocol_id"):
                first_success(self.workspace.provider(transport), self.spec)
        self.assertEqual([], transport.calls)

    def test_interrupted_window_requires_investigation_and_is_never_retried(self):
        with self.assertRaises(_Kill):
            first_success(self.workspace.provider(MockTransport({self.spec.job_id: _Kill()})), self.spec)
        transport = MockTransport({self.spec.job_id: "{}"})
        with self.assertRaisesRegex(CheckpointIntegrityError, "in-flight"):
            first_success(self.workspace.provider(transport), self.spec)
        self.assertEqual([], transport.calls)

    def test_transport_changing_model_or_credential_is_rejected(self):
        class SwitchingTransport(MockTransport):
            def __call__(self, spec, window, request_id):
                response = super().__call__(spec, window, request_id)
                response["slot_id"] = "gemini_slot_1"
                return response

        with self.assertRaisesRegex(CheckpointIntegrityError, "credential slot"):
            first_success(self.workspace.provider(SwitchingTransport({self.spec.job_id: "{}"})), self.spec)


class EndToEndMockedRunTests(unittest.TestCase):
    def broken(self, case_id, count=2):
        draft = copy.deepcopy(_synthetic()[1][case_id])
        for index in range(count):
            draft["assertions"][index]["proposition_handle"] = f"PROP99{index}"
        return json.dumps(draft, ensure_ascii=False)

    def test_full_mocked_run_is_blind_terminal_and_makes_zero_real_provider_operations(self):
        workspace = Workspace(self)
        transport = MockTransport(valid_responses())
        with mock.patch(
            "tools.story_extraction.run_m4_04b2_dev_predictions_v1.official_client_factory"
        ) as client, mock.patch.object(live, "load_runtime_config") as credentials:
            result = workspace.run(transport)
        client.assert_not_called()
        credentials.assert_not_called()
        self.assertEqual(0, result["real_provider_operations"])
        self.assertEqual(10, result["durable_provider_operations"])
        self.assertEqual([f"M4B3F_P3_{case_id}_PRIMARY" for case_id in CASE_IDS], transport.job_ids)
        self.assertEqual({"STRUCTURAL_VALID": 10, "STRUCTURAL_FAILURE": 0, "TRANSPORT_FAILURE": 0},
                         result["terminal_counts"])
        self.assertEqual(0, result["repair_count"])
        self.assertTrue(all((spec.model, spec.credential_slot) == (MODEL, CREDENTIAL_SLOT) for spec in transport.calls))
        for name in ("dev3_gold_opened", "holdout_opened", "scoring_performed"):
            self.assertIs(False, result[name])

    def test_sealed_input_and_mock_transport_are_mutually_exclusive(self):
        workspace = Workspace(self)
        with self.assertRaisesRegex(live.LiveExecutionError, "accepted transport"):
            live.run(protocol_path=workspace.protocol, input_archive=workspace.archive,
                     private_root=workspace.private, transport=MockTransport({}))
        with mock.patch.object(live, "load_runtime_config") as credentials:
            with self.assertRaisesRegex(live.LiveExecutionError, "accepted transport"):
                live.run(protocol_path=workspace.protocol, input_archive=workspace.archive,
                         private_root=workspace.private, expected_input_sha256=workspace.sha256)
        credentials.assert_not_called()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            status = live.main(["--mode", "run", "--protocol", str(workspace.protocol),
                                "--input-archive", str(workspace.archive)])
        self.assertEqual(2, status)
        self.assertIn("FAIL_CLOSED", output.getvalue())

    def test_all_blocker_repair_one_repair_maximum_and_no_quality_retry(self):
        responses = valid_responses()
        responses["M4B3F_P3_DEV3_02_PRIMARY"] = self.broken("DEV3_02")
        responses["M4B3F_P3_DEV3_02_REPAIR_1"] = valid_responses()["M4B3F_P3_DEV3_02_PRIMARY"]
        responses["M4B3F_P3_DEV3_05_PRIMARY"] = "{"
        responses["M4B3F_P3_DEV3_05_REPAIR_1"] = "{"
        workspace = Workspace(self)
        transport = MockTransport(responses)
        result = workspace.run(transport)
        by_case = {item["case_id"]: item for item in result["predictions"]}
        self.assertEqual(12, len(transport.calls))
        self.assertEqual(2, result["repair_count"])
        self.assertEqual("STRUCTURAL_VALID", by_case["DEV3_02"]["terminal_status"])
        self.assertEqual("STRUCTURAL_FAILURE", by_case["DEV3_05"]["terminal_status"])
        self.assertEqual("JSON_PARSE_FAILURE", by_case["DEV3_05"]["repair"]["validation"]["category"])
        self.assertEqual(2, transport.job_ids.count("M4B3F_P3_DEV3_05_PRIMARY") + transport.job_ids.count("M4B3F_P3_DEV3_05_REPAIR_1"))
        self.assertFalse(any("REPAIR_2" in job_id for job_id in transport.job_ids))
        blockers = by_case["DEV3_02"]["primary"]["validation"]["blockers"]
        self.assertEqual(2, len(blockers))
        self.assertTrue(all(set(item) == {"phase", "code", "path"} for item in blockers))
        repair_prompt = next(s for s in transport.calls if s.job_id == "M4B3F_P3_DEV3_02_REPAIR_1").user_prompt
        self.assertIn("SANITIZED_ALL_BLOCKERS_JSON", repair_prompt)
        for item in blockers:
            self.assertIn(item["path"], repair_prompt)
        for case_id in CASE_IDS:
            if case_id not in ("DEV3_02", "DEV3_05"):
                self.assertFalse(by_case[case_id]["repair_used"])
                self.assertEqual(1, by_case[case_id]["durable_provider_operations"])

    def test_terminal_transport_failure_is_recorded_without_structural_claim(self):
        responses = valid_responses()
        responses["M4B3F_P3_DEV3_03_PRIMARY"] = DurableTransportFailure("AUTH_FAILURE", provider_attempts=1)
        responses["M4B3F_P3_DEV3_06_PRIMARY"] = "{"
        responses["M4B3F_P3_DEV3_06_REPAIR_1"] = DurableTransportFailure("AUTH_FAILURE", provider_attempts=1)
        result = Workspace(self).run(MockTransport(responses))
        by_case = {item["case_id"]: item for item in result["predictions"]}
        self.assertEqual(2, result["terminal_counts"]["TRANSPORT_FAILURE"])
        self.assertEqual(10, result["terminal_case_count"])
        self.assertIsNone(by_case["DEV3_03"]["primary"]["raw_response_sha256"])
        self.assertIsNone(by_case["DEV3_03"]["compiled_batch_sha256"])
        self.assertEqual("REPAIR", by_case["DEV3_06"]["repair"]["validation"]["phase"])
        self.assertIsNotNone(by_case["DEV3_06"]["primary"]["raw_response_sha256"])

    def test_resume_never_calls_a_completed_job_or_terminal_case_again(self):
        responses = valid_responses()
        responses["M4B3F_P3_DEV3_01_PRIMARY"] = self.broken("DEV3_01", count=1)
        responses["M4B3F_P3_DEV3_01_REPAIR_1"] = valid_responses()["M4B3F_P3_DEV3_01_PRIMARY"]
        workspace = Workspace(self)
        spec = build_primary_spec("DEV3_01", workspace.load()[0].prepared_input)
        first_success(workspace.provider(MockTransport(responses)), spec)

        remaining = dict(responses)
        del remaining["M4B3F_P3_DEV3_01_PRIMARY"]
        resumed = MockTransport(remaining)
        result = workspace.run(resumed)
        self.assertNotIn("M4B3F_P3_DEV3_01_PRIMARY", resumed.job_ids)
        self.assertEqual("M4B3F_P3_DEV3_01_REPAIR_1", resumed.job_ids[0])
        self.assertEqual(10, len(resumed.calls))

        artifacts = {path: path.read_bytes() for path in workspace.private.rglob("*")
                     if path.is_file() and "checkpoints" not in path.parts}
        idle = MockTransport({})
        again = workspace.run(idle)
        self.assertEqual([], idle.calls)
        self.assertEqual(result["prediction_set_sha256"], again["prediction_set_sha256"])
        self.assertEqual(0, again["durable_provider_operations"] - result["durable_provider_operations"])
        self.assertEqual(artifacts, {path: path.read_bytes() for path in artifacts})

    def test_private_artifact_layout_and_immutability(self):
        workspace = Workspace(self)
        responses = valid_responses()
        responses["M4B3F_P3_DEV3_09_PRIMARY"] = "{"
        responses["M4B3F_P3_DEV3_09_REPAIR_1"] = "{"
        workspace.run(MockTransport(responses))
        for name in live.PRIVATE_DIRECTORIES:
            self.assertTrue((workspace.private / name).is_dir(), name)
        self.assertEqual(11, len(list((workspace.private / "raw").iterdir())))
        self.assertEqual(9, len(list((workspace.private / "drafts").iterdir())))
        self.assertEqual(9, len(list((workspace.private / "compiled").iterdir())))
        self.assertEqual(1, len(list((workspace.private / "failures").iterdir())))
        self.assertEqual(10, len(list((workspace.private / "case_results").iterdir())))
        self.assertEqual(11, len(list((workspace.private / "telemetry").iterdir())))
        self.assertEqual(11, len(list((workspace.private / "checkpoints" / "jobs").iterdir())))
        self.assertTrue((workspace.private / "checkpoints" / "global_pacing.json").is_file())
        (workspace.private / "raw" / "DEV3_01_primary.txt").write_bytes(b"tampered")
        with self.assertRaisesRegex(live.LiveExecutionError, "Immutable private artifact"):
            workspace.run(MockTransport({}))

    def test_private_root_inside_the_repository_must_be_ignored_storage(self):
        self.assertEqual(REPO_ROOT / ".local/m4_04b3h_dev3_predictions", live.DEFAULT_PRIVATE_ROOT)
        for forbidden in (REPO_ROOT, REPO_ROOT / "benchmarks" / "m4_extraction" / "predictions"):
            with self.assertRaisesRegex(live.LiveExecutionError, "ignored local storage"):
                live.private_layout(forbidden)
        ignore_rules = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn(".local/", ignore_rules)

    def test_public_lock_contains_identities_and_hashes_only(self):
        workspace = Workspace(self)
        responses = valid_responses()
        responses["M4B3F_P3_DEV3_04_PRIMARY"] = self.broken("DEV3_04", count=1)
        responses["M4B3F_P3_DEV3_04_REPAIR_1"] = "{"
        result = workspace.run(MockTransport(responses))
        text = workspace.public_lock.read_text(encoding="utf-8")
        lock = yaml.safe_load(text)
        self.assertEqual("M4_04B3H_DEV3_P3_PREDICTIONS_LOCKED", lock["status"])
        self.assertEqual(result["prediction_set_sha256"], lock["prediction_set_sha256"])
        self.assertEqual(live.LOCKED_PROTOCOL_SHA256, lock["protocol_sha256"])
        self.assertEqual(live.DECISION_RECORD_SHA256, lock["decision_record_sha256"])
        self.assertEqual(workspace.sha256, lock["dev3_input_sha256"])
        self.assertEqual(list(CASE_IDS), lock["case_order"])
        self.assertEqual("PASS", lock["pacing"]["invariant"])
        self.assertEqual((1, 9, 1), (lock["execution"]["repairs_used"], lock["execution"]["structural_valid_count"],
                                      lock["execution"]["structural_failure_count"]))
        for name in ("DEV3_gold_opened", "holdout_opened", "scoring_performed"):
            self.assertIs(False, lock[name])
        for word in SYNTHETIC_WORDS + ("PROP990", "proposition_handle", "synthetic-credential", "quote"):
            self.assertNotIn(word, text)
        for raw in (workspace.private / "raw").iterdir():
            self.assertNotIn(raw.read_text(encoding="utf-8"), text)

        def leaves(value):
            if isinstance(value, dict):
                return [leaf for child in value.values() for leaf in leaves(child)]
            if isinstance(value, list):
                return [leaf for child in value for leaf in leaves(child)]
            return [value]

        for leaf in leaves(lock):
            self.assertTrue(leaf is None or type(leaf) in (bool, int, float) or live._PUBLIC_TOKEN.fullmatch(leaf), leaf)
        for private in ("Mira opened the gate.", '{"draft_version": "x"}', "\u65e5\u672c\u8a9e"):
            unsafe = copy.deepcopy(lock)
            unsafe["cases"][0]["note"] = private
            with self.assertRaises(live.LiveExecutionError):
                live.write_public_prediction_lock(workspace.root / "unsafe.yaml", unsafe)
        tampered = copy.deepcopy(result)
        tampered["scoring_performed"] = True
        with self.assertRaises(live.LiveExecutionError):
            live.build_public_prediction_lock(tampered)

    def test_prediction_set_identity_is_deterministic_and_sensitive(self):
        result = Workspace(self).run(MockTransport(valid_responses()))
        other = Workspace(self).run(MockTransport(valid_responses()))
        self.assertEqual(result["prediction_set_sha256"], other["prediction_set_sha256"])
        identities, digest = live.prediction_set_identity(result["predictions"])
        self.assertEqual(result["prediction_set_sha256"], digest)
        self.assertEqual(sha256_bytes(canonical_json_bytes(identities)), digest)
        self.assertEqual(
            {"case_id", "primary_request_fingerprint", "primary_raw_response_sha256", "repair_used",
             "repair_request_fingerprint", "repair_raw_response_sha256", "terminal_status",
             "terminal_draft_sha256", "compiled_batch_sha256", "terminal_failure_sha256"},
            set(identities[0]),
        )
        changes = (
            lambda item: item["primary"].update(request_fingerprint="0" * 64),
            lambda item: item["primary"].update(raw_response_sha256="0" * 64),
            lambda item: item.update(terminal_draft_sha256="0" * 64),
            lambda item: item.update(compiled_batch_sha256="0" * 64),
            lambda item: item.update(terminal_status="STRUCTURAL_FAILURE"),
            lambda item: item.update(terminal_failure_sha256="0" * 64),
            lambda item: item.update(repair_used=True, repair={"request_fingerprint": "1" * 64,
                                                                "raw_response_sha256": "2" * 64}),
        )
        for change in changes:
            predictions = copy.deepcopy(result["predictions"])
            change(predictions[6])
            self.assertNotEqual(digest, live.prediction_set_identity(predictions)[1])
        reordered = copy.deepcopy(result["predictions"])
        reordered[0], reordered[1] = reordered[1], reordered[0]
        with self.assertRaisesRegex(live.LiveExecutionError, "locked order"):
            live.prediction_set_identity(reordered)
        unsafe = copy.deepcopy(result["predictions"])
        unsafe[0]["primary"]["raw_response_sha256"] = "Mira opened the gate."
        with self.assertRaisesRegex(live.LiveExecutionError, "SHA-256"):
            live.prediction_set_identity(unsafe)


if __name__ == "__main__":
    unittest.main()
