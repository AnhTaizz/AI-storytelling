from dataclasses import replace
import inspect
import json
from pathlib import Path
import tempfile
import unittest

from tests.story_extraction import fixture_builder as fx
from tools.story_extraction.draft_compiler_v1 import DraftCompilerContext
from tools.story_extraction.draft_compiler_v1_1 import prepare_story_extraction_draft_v1_1
from tools.story_extraction.draft_coverage_v1_1 import canonical_gold_to_draft_v1_1
from tools.story_extraction.m4_04b3f_dev3_p3_protocol_v1 import (
    build_primary_spec,
    sha256_bytes,
    write_protocol,
)
from tools.story_extraction.run_m4_04b3g_dev3_p3_predictions_v1 import (
    LOCKED_PROTOCOL_SHA256,
    CaseInput,
    Dev3RunnerError,
    FirstSuccessLedger,
    OfflineMockProvider,
    ProviderFirstSuccess,
    _assert_locked_job_spec,
    _validate_member_name,
    compile_raw_response,
    execute_case,
    execute_loaded_cases,
    preflight,
    verify_locked_protocol,
)


def synthetic_case(name="c02_two_mentions_one_entity"):
    ingestion, base, gold = fx.build(name)
    scope = gold["scope"]
    context = DraftCompilerContext(
        base,
        scope["passage_inputs"],
        scope["as_of_position"],
        scope["profile_id"],
        "M4_04B3G_P3_TEST",
        "v1.1",
        "P3_DEV3_01_SYNTHETIC",
        ingestion,
    )
    prepared = prepare_story_extraction_draft_v1_1(context)
    draft, _ = canonical_gold_to_draft_v1_1(gold, context)
    return CaseInput("DEV3_01", prepared, context), draft


def encoded(value):
    return json.dumps(value, ensure_ascii=False)


class M404B3GDev3P3RunnerReadinessTests(unittest.TestCase):
    def test_exact_protocol_sha_is_bound(self):
        self.assertEqual(
            "f9cf1c25a21bb3bfc910b8e218c8dac9f032d67957f8d7cb58397134a0504bae",
            LOCKED_PROTOCOL_SHA256,
        )

    def test_runner_has_no_gold_or_evaluator_parameter(self):
        for function in (preflight, execute_loaded_cases, execute_case):
            names = set(inspect.signature(function).parameters)
            self.assertFalse(any("gold" in name.lower() for name in names))
            self.assertFalse(any("evaluat" in name.lower() for name in names))

    def test_rejects_gold_markers_and_traversal(self):
        for member in ("../escape.json", "/absolute.json", "cases/dev3_gold.json"):
            with self.subTest(member=member), self.assertRaises(Dev3RunnerError):
                _validate_member_name(member)
        with tempfile.TemporaryDirectory(prefix="gold_forbidden_") as directory:
            with self.assertRaises(Dev3RunnerError):
                preflight(protocol_path=Path(directory) / "p.json", input_archive=Path(directory) / "input.zip")

    def test_protocol_hash_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "protocol.json"
            path.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(Dev3RunnerError, "protocol verification failed"):
                verify_locked_protocol(path)

    def test_input_hash_gate_precedes_provider_or_case_access(self):
        with tempfile.TemporaryDirectory() as directory:
            protocol = Path(directory) / "protocol.json"
            _, digest = write_protocol(protocol)
            self.assertEqual(LOCKED_PROTOCOL_SHA256, digest)
            archive = Path(directory) / "dev3_input.zip"
            archive.write_bytes(b"synthetic-not-authorized")
            provider = OfflineMockProvider({})
            with self.assertRaisesRegex(Dev3RunnerError, "input archive hash mismatch"):
                execute_loaded_cases(
                    protocol_path=protocol,
                    input_archive=archive,
                    cases=(),
                    provider=provider,
                )
            self.assertEqual([], provider.calls)
            self.assertEqual(0, provider.actual_provider_operations)

    def test_model_key_and_settings_are_fixed(self):
        case, _ = synthetic_case()
        spec = build_primary_spec(case.case_id, case.prepared_input)
        _assert_locked_job_spec(spec)
        mutations = (
            replace(spec, model="other-model"),
            replace(spec, credential_slot="gemini_slot_2"),
            replace(spec, generation_config={"temperature": 1, "max_output_tokens": 16384}),
            replace(spec, schema_response_mode="OTHER"),
        )
        for mutated in mutations:
            with self.assertRaises(Dev3RunnerError):
                _assert_locked_job_spec(mutated)

    def test_valid_v1_1_draft_compiles(self):
        case, draft = synthetic_case()
        parsed, batch, validation = compile_raw_response(encoded(draft), case)
        self.assertEqual(draft, parsed)
        self.assertIsNotNone(batch)
        self.assertTrue(validation["pass"])

    def test_multi_blocker_diagnostic_is_complete_and_sanitized(self):
        case, draft = synthetic_case()
        draft["assertions"][0]["proposition_handle"] = "PROP998"
        draft["assertions"][1]["proposition_handle"] = "PROP999"
        _, batch, validation = compile_raw_response(encoded(draft), case)
        self.assertIsNone(batch)
        self.assertEqual("DRAFT_COMPILER_FAILURE", validation["category"])
        self.assertEqual(2, len(validation["blockers"]))
        self.assertTrue(all(set(item) == {"phase", "code", "path"} for item in validation["blockers"]))
        diagnostic = json.dumps(validation, ensure_ascii=False)
        self.assertNotIn("Public unit test", diagnostic)
        self.assertNotIn("quote", diagnostic.lower())

    def test_maximum_one_repair_and_failure_is_terminal(self):
        case, _ = synthetic_case()
        provider = OfflineMockProvider({
            "M4B3F_P3_DEV3_01_PRIMARY": "{",
            "M4B3F_P3_DEV3_01_REPAIR_1": "{",
        })
        result = execute_case(case, provider)
        self.assertEqual(1, result["repair_count"])
        self.assertEqual("STRUCTURAL_FAILURE", result["terminal_status"])
        self.assertEqual(2, len(provider.calls))
        self.assertEqual(0, result["quality_or_coverage_retries"])

    def test_structurally_valid_result_has_no_quality_or_coverage_retry(self):
        case, draft = synthetic_case()
        provider = OfflineMockProvider({"M4B3F_P3_DEV3_01_PRIMARY": encoded(draft)})
        result = execute_case(case, provider)
        self.assertEqual("STRUCTURAL_VALID", result["terminal_status"])
        self.assertEqual(0, result["repair_count"])
        self.assertEqual(0, result["quality_or_coverage_retries"])
        self.assertEqual(["M4B3F_P3_DEV3_01_PRIMARY"], provider.calls)

    def test_first_success_is_immutable(self):
        case, _ = synthetic_case()
        spec = build_primary_spec(case.case_id, case.prepared_input)
        ledger = FirstSuccessLedger()
        first_raw = "{\"first\":true}"
        first = ProviderFirstSuccess(first_raw, 0, sha256_bytes(first_raw.encode("utf-8")))
        ledger.lock(spec, first)
        ledger.lock(spec, first)
        other_raw = "{\"first\":false}"
        other = ProviderFirstSuccess(other_raw, 0, sha256_bytes(other_raw.encode("utf-8")))
        with self.assertRaisesRegex(Dev3RunnerError, "Immutable first-success"):
            ledger.lock(spec, other)

    def test_mocked_execution_performs_zero_actual_provider_operations(self):
        case, draft = synthetic_case()
        provider = OfflineMockProvider({"M4B3F_P3_DEV3_01_PRIMARY": encoded(draft)})
        result = execute_case(case, provider, offline_only=True)
        self.assertEqual(0, provider.actual_provider_operations)
        self.assertEqual(0, result["actual_provider_operations"])


if __name__ == "__main__":
    unittest.main()
