"""Offline tests for live adapter V1.1: the layout-only loader correction (M4-04B3H2R).

Synthetic story fixtures and synthetic archives in the recorded DEV3 input layout, with
mocked transports. No DEV3 package, credential or provider is touched.
"""
import ast
import contextlib
import copy
import functools
import hashlib
import inspect
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import yaml

from tests.story_extraction import fixture_builder as fx
from tools.story_extraction import run_m4_04b3g_dev3_p3_predictions_v1 as runner_core
from tools.story_extraction import run_m4_04b3h_dev3_p3_live_v1 as v1
from tools.story_extraction import run_m4_04b3h_dev3_p3_live_v1_1 as live
from tools.story_extraction.dev3_seal_v1 import deterministic_zip_bytes
from tools.story_extraction.draft_compiler_v1 import DraftCompilerContext
from tools.story_extraction.draft_compiler_v1_1 import prepare_story_extraction_draft_v1_1
from tools.story_extraction.draft_coverage_v1_1 import canonical_gold_to_draft_v1_1
from tools.story_extraction.m4_04b3f_dev3_p3_protocol_v1 import (
    CASE_IDS,
    CREDENTIAL_SLOT,
    MODEL,
    REPO_ROOT,
    canonical_json_bytes,
    normalized_file_sha256,
    sha256_bytes,
    write_protocol,
)


V1_FILE = REPO_ROOT / v1.ADAPTER_PATH
V1_1_FILE = REPO_ROOT / live.ADAPTER_PATH
V1_SHA256 = "c4815a8e2c253e44da8ed0c08b0b7b1ac830905d5af9efe816e6154ba9c5f0c2"
RESULT_RECORD = REPO_ROOT / "benchmarks/m4_extraction/M4_04B3H2R_DEV3_LAYOUT_ADAPTER_PREFLIGHT_RESULT.yaml"
MANIFEST = "input_manifest.json"
FIXTURES = (
    "c01_named_character", "c02_two_mentions_one_entity", "c05_event_occurred", "c06_participant",
    "c07_location", "c08_possession", "c09_ownership", "c10_relationship_state",
    "c11_explicit_emotion", "c25_negated_event",
)
# The only top-level names of the adapter that may differ between V1 and V1.1.
LAYOUT_ONLY_NAMES = {
    "RUNNER_ID", "ADAPTER_PATH", "SEALED_INPUT_CONTRACT",
    "case_member_paths", "validate_case_members", "load_case_inputs",
}


def fixed_members(case_id):
    return [
        f"cases/{case_id}/base_document.json",
        f"cases/{case_id}/ingestion_report.json",
        f"cases/{case_id}/prepared_draft_input.json",
        f"cases/{case_id}/source/unit.txt",
        f"cases/{case_id}/source_manifest.json",
    ]


@functools.lru_cache(maxsize=1)
def _synthetic():
    """Ten synthetic cases in the recorded DEV3 layout: (archive entries, valid drafts)."""
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
        entries[f"{folder}/source/unit.txt"] = text
        entries[f"{folder}/source_manifest.json"] = canonical_json_bytes({
            "contract_version": "LIGHT_NOVEL_INGESTION/v0", "story_id": "story-syn-m4",
            "stream_id": "stream-syn-m4", "source_language": "en",
            "documents": [{"document_id": "srcdoc-syn-m4", "order": 1, "path": "source/unit.txt",
                           "expected_sha256": hashlib.sha256(text).hexdigest()}],
        })
        entries[f"{folder}/base_document.json"] = canonical_json_bytes(base)
        entries[f"{folder}/prepared_draft_input.json"] = canonical_json_bytes(
            prepare_story_extraction_draft_v1_1(context)
        )
        entries[f"{folder}/ingestion_report.json"] = canonical_json_bytes(ingestion.ingestion_report())
        rows.append({
            "as_of_position": scope["as_of_position"],
            "case_id": case_id,
            "members": fixed_members(case_id),
            "passage_inputs": scope["passage_inputs"],
            "profile_id": scope["profile_id"],
        })
    entries[MANIFEST] = canonical_json_bytes({
        "artifact": "M4_04B3_DEV3_INPUT_V1",
        "case_count": len(CASE_IDS),
        "case_order": list(CASE_IDS),
        "cases": rows,
        "draft_interface": "STORY_EXTRACTION_DRAFT_V1_1",
        "extractor_surface": "SYNTHETIC",
        "files": {},
        "source_family": "SYNTHETIC",
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

    def __init__(self, responses):
        self.responses = dict(responses)
        self.calls = []

    def __call__(self, spec, window, request_id):
        self.calls.append(spec)
        return {
            "raw_content": self.responses[spec.job_id],
            "model_requested": spec.model,
            "slot_id": spec.credential_slot,
            "transport_attempts": [{"model": spec.model, "slot_id": spec.credential_slot}],
            "attempt_accounting": {"total_provider_attempts": 1},
        }

    @property
    def job_ids(self):
        return [spec.job_id for spec in self.calls]


class Workspace:
    def __init__(self, test, entries=None):
        directory = tempfile.TemporaryDirectory(prefix="m4b3h2r_")
        test.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.archive = self.root / "synthetic_input.zip"
        self.archive.write_bytes(deterministic_zip_bytes(entries or synthetic_entries()))
        self.sha256 = sha256_bytes(self.archive.read_bytes())
        self.protocol = self.root / "protocol.json"
        write_protocol(self.protocol)
        self.private = self.root / "private"
        self.public_lock = self.root / "public_lock.yaml"

    def load(self, module=live):
        return module.load_case_inputs(self.archive, self.private / "input", expected_input_sha256=self.sha256)

    def run(self, transport):
        with contextlib.redirect_stdout(io.StringIO()):
            return live.run(
                protocol_path=self.protocol, input_archive=self.archive, private_root=self.private,
                public_lock_path=self.public_lock, expected_input_sha256=self.sha256, transport=transport,
            )


def top_level(path):
    """Top-level functions, classes and assignments of a module, by name, as AST dumps."""
    nodes = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            nodes[node.name] = ast.dump(node)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                nodes[target.id] = ast.dump(node.value)
    return nodes


class LayoutOnlyDifferenceTests(unittest.TestCase):
    def test_historical_adapter_v1_is_preserved_unchanged(self):
        self.assertEqual(V1_SHA256, normalized_file_sha256(V1_FILE))
        self.assertEqual("M4_04B3_DEV3_INPUT_MANIFEST_V1.json", v1.SEALED_INPUT_CONTRACT["manifest_member"])
        self.assertNotEqual(normalized_file_sha256(V1_FILE), normalized_file_sha256(V1_1_FILE))

    def test_v1_1_differs_from_v1_only_in_identity_and_input_layout(self):
        old, new = top_level(V1_FILE), top_level(V1_1_FILE)
        changed = {name for name in set(old) | set(new) if old.get(name) != new.get(name)}
        self.assertEqual(LAYOUT_ONLY_NAMES, changed)
        self.assertEqual({"case_member_paths", "validate_case_members"}, set(new) - set(old))
        self.assertEqual(set(), set(old) - set(new))
        imports = lambda path: [ast.dump(node) for node in ast.parse(path.read_text(encoding="utf-8")).body
                                if isinstance(node, (ast.Import, ast.ImportFrom))]
        self.assertEqual(imports(V1_FILE), imports(V1_1_FILE))

    def test_execution_semantics_are_the_unchanged_v1_and_runner_core_objects(self):
        for name in ("EXECUTOR_PROTOCOL_ID", "PROCESS_ID", "PROCESS_VERSION", "TERMINAL_STATUSES",
                     "PRIVATE_DIRECTORIES", "LIVE_AUTHORIZATION_TOKEN", "PREDICTION_RESULT_ID",
                     "PREDICTION_MANIFEST_ID", "PUBLIC_LOCK_STATUS", "CRLF_BOUND_HISTORICAL_FILES",
                     "ENVIRONMENT_METHOD", "DECISION_RECORD_SHA256", "LOCKED_PROTOCOL_SHA256",
                     "DEV3_INPUT_SHA256", "DEV3_GOLD_SHA256"):
            self.assertEqual(getattr(v1, name), getattr(live, name), name)
        for name in ("compile_raw_response", "execute_case", "CaseInput", "FirstSuccessLedger",
                     "ProviderFirstSuccess", "_validate_member_name"):
            self.assertIs(getattr(runner_core, name), getattr(live, name), name)
        for name in ("GeminiDevWindowTransport", "_execute_to_terminal", "DurableResearchExecutor",
                     "PersistentRollingOperationPacer", "load_runtime_config", "ingest_manifest_file",
                     "prepare_story_extraction_draft_v1_1"):
            self.assertIs(getattr(v1, name), getattr(live, name), name)
        self.assertEqual("M4_04B3H_DEV3_P3_LIVE_EXECUTION_ADAPTER_V1_1", live.RUNNER_ID)
        self.assertEqual("tools/story_extraction/run_m4_04b3h_dev3_p3_live_v1_1.py", live.ADAPTER_PATH)

    def test_committed_result_record_binds_both_adapter_hashes(self):
        record = yaml.safe_load(RESULT_RECORD.read_text(encoding="utf-8"))
        self.assertEqual(V1_SHA256, record["historical_adapter"]["sha256"])
        self.assertTrue(record["historical_adapter"]["preserved_unchanged"])
        self.assertEqual(live.ADAPTER_PATH, record["corrected_adapter"]["path"])
        self.assertEqual(normalized_file_sha256(V1_1_FILE), record["corrected_adapter"]["sha256"])
        self.assertEqual("INPUT_LAYOUT_ONLY", record["corrected_adapter"]["change_scope"])
        self.assertEqual(sorted(LAYOUT_ONLY_NAMES), sorted(record["layout_only_review"]["changed_top_level_names"]))
        self.assertEqual(normalized_file_sha256(Path(__file__)), record["corrected_adapter"]["focused_tests_sha256"])
        self.assertEqual(0, record["execution"]["provider_operations"])
        self.assertEqual(0, record["execution"]["model_operations"])
        self.assertIs(False, record["blindness"]["dev3_gold_opened"])
        self.assertIs(False, record["decision"]["live_execution_authorized"])


class RecordedLayoutContractTests(unittest.TestCase):
    def test_contract_is_exactly_the_recorded_structure(self):
        contract = live.SEALED_INPUT_CONTRACT
        self.assertEqual("input_manifest.json", contract["manifest_member"])
        self.assertEqual(51, contract["member_count"])
        self.assertEqual(
            ("artifact", "case_count", "case_order", "cases", "draft_interface",
             "extractor_surface", "files", "source_family"),
            contract["manifest_keys"],
        )
        self.assertEqual(("as_of_position", "case_id", "members", "passage_inputs", "profile_id"),
                         contract["case_fields"])
        self.assertEqual(("M4_04B3_DEV3_INPUT_V1", "STORY_EXTRACTION_DRAFT_V1_1"),
                         (contract["artifact"], contract["draft_interface"]))
        self.assertEqual(1 + 5 * len(CASE_IDS), contract["member_count"])

    def test_fixed_member_paths_are_derived_exactly(self):
        for case_id in CASE_IDS:
            paths = live.case_member_paths(case_id)
            self.assertEqual(sorted(fixed_members(case_id)), sorted(paths.values()))
            self.assertEqual(f"cases/{case_id}/source_manifest.json", paths["m3_manifest"])
            self.assertEqual(f"cases/{case_id}/source/unit.txt", paths["source_unit"])
            self.assertEqual(f"cases/{case_id}/base_document.json", paths["base_document"])
            self.assertEqual(f"cases/{case_id}/prepared_draft_input.json", paths["prepared_input"])
            self.assertEqual(f"cases/{case_id}/ingestion_report.json", paths["ingestion_report"])
        self.assertEqual(["case_id"], list(inspect.signature(live.case_member_paths).parameters))

    def test_members_list_must_be_the_exact_fixed_set(self):
        good = fixed_members("DEV3_03")
        self.assertEqual(live.case_member_paths("DEV3_03"), live.validate_case_members("DEV3_03", good))
        self.assertEqual(live.case_member_paths("DEV3_03"),
                         live.validate_case_members("DEV3_03", list(reversed(good))))
        failures = (
            (good[:-1], "missing a fixed member"),
            (good + ["cases/DEV3_03/extra.json"], "unexpected member"),
            (good + ["notes.json"], "unexpected member"),
            (good + [good[0]], "duplicate"),
            (good[:-1] + ["cases/DEV3_04/source_manifest.json"], "another case"),
            (fixed_members("DEV3_04"), "another case"),
            (good[:-1] + ["cases/DEV3_03/../DEV3_03/source_manifest.json"], "forbidden"),
            (good + ["../escape.json"], "forbidden"),
            (good + ["/absolute.json"], "forbidden"),
            (good + ["cases/DEV3_03/gold_batch.json"], "forbidden"),
            (good[:-1] + [{"path": good[-1]}], "list of strings"),
            (tuple(good), "list of strings"),
            ({name: 1 for name in good}, "list of strings"),
            (None, "list of strings"),
        )
        for members, message in failures:
            with self.subTest(message=message), self.assertRaisesRegex(live.LiveExecutionError, message):
                live.validate_case_members("DEV3_03", members)


class LoaderV11Tests(unittest.TestCase):
    def test_recorded_layout_loads_ten_cases_and_reproduces_prepared_input(self):
        cases = Workspace(self).load()
        self.assertEqual(list(CASE_IDS), [case.case_id for case in cases])
        for case in cases:
            self.assertEqual("STORY_EXTRACTION_DRAFT_V1_1", case.prepared_input["draft_version"])
            self.assertEqual(prepare_story_extraction_draft_v1_1(case.compiler_context), case.prepared_input)
            self.assertEqual((v1.PROCESS_ID, v1.PROCESS_VERSION, f"P3_{case.case_id}"),
                             (case.compiler_context.process_id, case.compiler_context.process_version,
                              case.compiler_context.run_id))

    def test_historical_v1_still_fails_closed_on_the_recorded_layout(self):
        with self.assertRaisesRegex(v1.LiveExecutionError, "unknown member"):
            Workspace(self).load(module=v1)

    def test_manifest_identity_keys_count_and_order_are_exact(self):
        def swap(manifest):
            manifest["cases"][0], manifest["cases"][1] = manifest["cases"][1], manifest["cases"][0]

        failures = (
            (lambda m: m.update(artifact="M4_04B3_DEV2_INPUT_V1"), "manifest identity"),
            (lambda m: m.update(draft_interface="STORY_EXTRACTION_DRAFT_V1"), "manifest identity"),
            (lambda m: m.update(case_count=9), "manifest identity"),
            (lambda m: m.pop("source_family"), "manifest identity"),
            (lambda m: m.update(unexpected_key=1), "manifest identity"),
            (swap, "order mismatch"),
            (lambda m: m.update(case_order=list(reversed(CASE_IDS))), "order mismatch"),
            (lambda m: m.update(case_order=list(CASE_IDS[:-1])), "order mismatch"),
            (lambda m: m["cases"].pop(), "order mismatch"),
            (lambda m: m["cases"][3].pop("profile_id"), "case row keys"),
            (lambda m: m["cases"][3].update(base_document_member="cases/DEV3_04/base_document.json"), "case row keys"),
            (lambda m: m["cases"][3]["members"].pop(), "missing a fixed member"),
            (lambda m: m["cases"][3]["members"].append("cases/DEV3_05/base_document.json"), "another case"),
            (lambda m: m["cases"][3]["members"].append(m["cases"][3]["members"][0]), "duplicate"),
        )
        for change, message in failures:
            workspace = Workspace(self, edit_manifest(synthetic_entries(), change))
            with self.subTest(message=message), self.assertRaisesRegex(live.LiveExecutionError, message):
                workspace.load()

    def test_manifest_under_the_v1_assumed_name_is_not_discovered(self):
        entries = synthetic_entries()
        entries["M4_04B3_DEV3_INPUT_MANIFEST_V1.json"] = entries.pop(MANIFEST)
        with self.assertRaisesRegex(live.LiveExecutionError, "unknown member"):
            Workspace(self, entries).load()

    def test_archive_inventory_must_equal_the_fixed_layout(self):
        entries = synthetic_entries()
        entries["cases/DEV3_06/source/other.txt"] = entries.pop("cases/DEV3_06/source/unit.txt")
        with self.assertRaisesRegex(live.LiveExecutionError, "inventory differs from the fixed layout"):
            Workspace(self, entries).load()

    def test_gold_marker_in_a_member_list_is_rejected(self):
        entries = edit_manifest(
            synthetic_entries(),
            lambda m: m["cases"][0]["members"].append("cases/DEV3_01/gold_batch.json"),
        )
        with self.assertRaisesRegex(live.LiveExecutionError, "Gold marker"):
            Workspace(self, entries).load()

    def test_m3_manifest_is_the_one_fixed_path_with_no_fallback(self):
        workspace = Workspace(self)
        with mock.patch.object(live, "ingest_manifest_file", wraps=live.ingest_manifest_file) as ingest:
            workspace.load()
        expected = [workspace.private / "input" / "cases" / case_id / "source_manifest.json" for case_id in CASE_IDS]
        self.assertEqual(expected, [call.args[0] for call in ingest.call_args_list])
        self.assertEqual([path.parent for path in expected], [call.args[1] for call in ingest.call_args_list])

        entries = synthetic_entries()
        valid_m3 = entries["cases/DEV3_01/source_manifest.json"]
        entries["cases/DEV3_01/source_manifest.json"] = entries["cases/DEV3_01/ingestion_report.json"]
        entries["cases/DEV3_01/ingestion_report.json"] = valid_m3
        broken = Workspace(self, entries)
        with mock.patch.object(live, "ingest_manifest_file", wraps=live.ingest_manifest_file) as ingest:
            with self.assertRaisesRegex(live.LiveExecutionError, "Frozen M3 ingestion failed"):
                broken.load()
        self.assertEqual(1, ingest.call_count)
        self.assertEqual("source_manifest.json", ingest.call_args.args[0].name)
        source = inspect.getsource(live.load_case_inputs)
        for forbidden in ("glob", "listdir", "iterdir", "endswith", "startswith"):
            self.assertNotIn(forbidden, source)

    def test_ingestion_binding_and_prepared_input_must_match_exactly(self):
        entries = synthetic_entries()
        report = json.loads(entries["cases/DEV3_02/ingestion_report.json"])
        report["corpus_fingerprint_sha256"] = "0" * 64
        entries["cases/DEV3_02/ingestion_report.json"] = canonical_json_bytes(report)
        with self.assertRaisesRegex(live.LiveExecutionError, "ingestion binding"):
            Workspace(self, entries).load()
        entries = synthetic_entries()
        prepared = json.loads(entries["cases/DEV3_07/prepared_draft_input.json"])
        prepared["passages"] = list(reversed(prepared["passages"])) + [{"handle": "P9"}]
        entries["cases/DEV3_07/prepared_draft_input.json"] = canonical_json_bytes(prepared)
        with self.assertRaisesRegex(live.LiveExecutionError, "does not reproduce exactly"):
            Workspace(self, entries).load()

    def test_archive_hash_gate_and_gold_rejection_are_inherited(self):
        workspace = Workspace(self)
        with mock.patch.object(live.zipfile, "ZipFile", side_effect=AssertionError("opened")) as opened:
            with self.assertRaisesRegex(live.LiveExecutionError, "hash mismatch"):
                live.load_case_inputs(workspace.archive, workspace.private / "input")
        opened.assert_not_called()
        with mock.patch.object(live, "DEV3_GOLD_SHA256", workspace.sha256):
            with self.assertRaisesRegex(live.LiveExecutionError, "gold package is forbidden"):
                workspace.load()


class PreflightAndRunV11Tests(unittest.TestCase):
    def test_preflight_constructs_no_credential_client_or_checkpoint(self):
        workspace = Workspace(self)
        with mock.patch.object(live, "load_runtime_config", side_effect=AssertionError("credentials")) as credentials, \
                mock.patch("tools.story_extraction.run_m4_04b2_dev_predictions_v1.official_client_factory",
                           side_effect=AssertionError("client")) as client, \
                mock.patch.object(live, "GeminiDevWindowTransport", side_effect=AssertionError("transport")) as transport, \
                mock.patch.object(live, "build_durable_stack", side_effect=AssertionError("executor")) as stack:
            _, layout, cases, guard = live.preflight(
                protocol_path=workspace.protocol, input_archive=workspace.archive,
                private_root=workspace.private, expected_input_sha256=workspace.sha256,
                check_environment=False,
            )
            guard()
        for patched in (credentials, client, transport, stack):
            patched.assert_not_called()
        self.assertEqual(10, len(cases))
        self.assertEqual([], list((layout["checkpoints"]).iterdir()))
        self.assertEqual(51, sum(path.is_file() for path in layout["input"].rglob("*")))

    def test_mocked_run_inherits_one_repair_no_quality_retry_and_zero_real_operations(self):
        responses = valid_responses()
        broken = copy.deepcopy(_synthetic()[1]["DEV3_02"])
        broken["assertions"][0]["proposition_handle"] = "PROP990"
        broken["assertions"][1]["proposition_handle"] = "PROP991"
        responses["M4B3F_P3_DEV3_02_PRIMARY"] = json.dumps(broken)
        responses["M4B3F_P3_DEV3_02_REPAIR_1"] = valid_responses()["M4B3F_P3_DEV3_02_PRIMARY"]
        responses["M4B3F_P3_DEV3_05_PRIMARY"] = "{"
        responses["M4B3F_P3_DEV3_05_REPAIR_1"] = "{"
        workspace = Workspace(self)
        transport = MockTransport(responses)
        with mock.patch.object(live, "load_runtime_config") as credentials, mock.patch(
            "tools.story_extraction.run_m4_04b2_dev_predictions_v1.official_client_factory"
        ) as client:
            result = workspace.run(transport)
        credentials.assert_not_called()
        client.assert_not_called()
        by_case = {item["case_id"]: item for item in result["predictions"]}
        self.assertEqual(0, result["real_provider_operations"])
        self.assertEqual(12, len(transport.calls))
        self.assertEqual(2, result["repair_count"])
        self.assertFalse(any("REPAIR_2" in job_id for job_id in transport.job_ids))
        self.assertEqual("STRUCTURAL_VALID", by_case["DEV3_02"]["terminal_status"])
        self.assertEqual("STRUCTURAL_FAILURE", by_case["DEV3_05"]["terminal_status"])
        self.assertEqual(2, len(by_case["DEV3_02"]["primary"]["validation"]["blockers"]))
        for case_id in CASE_IDS:
            if case_id not in ("DEV3_02", "DEV3_05"):
                self.assertFalse(by_case[case_id]["repair_used"])
                self.assertEqual(1, by_case[case_id]["durable_provider_operations"])
        self.assertTrue(all((spec.model, spec.credential_slot) == (MODEL, CREDENTIAL_SLOT) for spec in transport.calls))
        self.assertEqual(normalized_file_sha256(V1_1_FILE), result["adapter_sha256"])
        self.assertEqual(live.RUNNER_ID, result["runner_id"])
        lock = yaml.safe_load(workspace.public_lock.read_text(encoding="utf-8"))
        self.assertEqual(live.ADAPTER_PATH, lock["adapter"]["path"])
        self.assertEqual(result["prediction_set_sha256"], lock["prediction_set_sha256"])
        idle = MockTransport({})
        self.assertEqual(result["prediction_set_sha256"], workspace.run(idle)["prediction_set_sha256"])
        self.assertEqual([], idle.calls)

    def test_sealed_input_and_mock_transport_remain_mutually_exclusive(self):
        workspace = Workspace(self)
        with self.assertRaisesRegex(live.LiveExecutionError, "accepted transport"):
            live.run(protocol_path=workspace.protocol, input_archive=workspace.archive,
                     private_root=workspace.private, transport=MockTransport({}))
        with contextlib.redirect_stdout(io.StringIO()) as output:
            status = live.main(["--mode", "run", "--protocol", str(workspace.protocol),
                                "--input-archive", str(workspace.archive)])
        self.assertEqual(2, status)
        self.assertIn("FAIL_CLOSED", output.getvalue())
        for function in (live.preflight, live.run, live.load_case_inputs, live.validate_case_members):
            names = set(inspect.signature(function).parameters)
            self.assertFalse(any("gold" in name.lower() or "evaluat" in name.lower() for name in names))


if __name__ == "__main__":
    unittest.main()
