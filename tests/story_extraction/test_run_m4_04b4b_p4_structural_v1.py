import contextlib
import copy
from dataclasses import replace
import hashlib
import inspect
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import yaml

from tests.story_extraction import fixture_builder as fx
from tools.story_extraction import m4_04b3f_dev3_p3_protocol_v1 as p3_protocol
from tools.story_extraction import m4_04b4a_p4_output_contract_v1 as contract
from tools.story_extraction import m4_04b4b_p4_protocol_v1 as protocol
from tools.story_extraction import materialize_draft_v1_1_model_schema_v1 as materializer
from tools.story_extraction import run_m4_04b4b_p4_structural_v1 as runner
from tools.story_extraction.draft_compiler_v1 import DraftCompilerContext
from tools.story_extraction.draft_compiler_v1_1 import prepare_story_extraction_draft_v1_1
from tools.story_extraction.draft_coverage_v1_1 import canonical_gold_to_draft_v1_1
from tools.story_extraction.durable_research_executor_v1 import (
    CheckpointIntegrityError,
    DurableResearchExecutor,
    DurableTransportFailure,
    JobState,
)
from tools.story_extraction.run_m4_04b3g_dev3_p3_predictions_v1 import (
    CaseInput,
    Dev3RunnerError,
    FirstSuccessLedger,
    ProviderFirstSuccess,
    _assert_locked_job_spec as p3_assert_locked_job_spec,
)
from tools.story_extraction.run_m4_04b3h_dev3_p3_live_v1_1 import DurableFirstSuccessProvider


CASE_ID = "SYN_01"
PRIMARY = f"M4B4B_P4_{CASE_ID}_PRIMARY"
REPAIR = f"M4B4B_P4_{CASE_ID}_REPAIR_1"
MARKER = "ZZ_MODEL_WRITTEN_MARKER_ZZ"
SMOKE_PRIMARY = f"M4B4B_P4_{runner.SMOKE_CASE_ID}_PRIMARY"
SMOKE_DRAFT = {
    "draft_version": "STORY_EXTRACTION_DRAFT_V1_1",
    "evidence": [{"handle": "EV1", "passage_handle": "P1", "quote": "Tomas", "occurrence": 1, "role": "DEPICTION"}],
    "mentions": [{"handle": "M1", "passage_handle": "P1", "quote": "Tomas", "occurrence": 1, "role": "DEPICTION",
                  "surface_form": "Tomas"}],
    "entities": [{"handle": "E_NEW_1", "kind": "CHARACTER"}],
    "events": [],
    "anchors": [],
    "propositions": [{"handle": "PROP1", "predicate": "RefersTo",
                      "args": {"mention": {"kind": "MENTION", "handle": "M1"},
                               "entity": {"kind": "ENTITY", "handle": "E_NEW_1"}}}],
    "assertions": [{"handle": "A1", "proposition_handle": "PROP1", "polarity": "AFFIRMED",
                    "epistemic_status": "EXPLICIT",
                    "support": {"evidence_sets": [{"label": "SUFFICIENT", "evidence_handles": ["EV1"]}],
                                "derivations": []}}],
}


def synthetic_case(name="c02_two_mentions_one_entity"):
    ingestion, base, gold = fx.build(name)
    scope = gold["scope"]
    context = DraftCompilerContext(
        base, scope["passage_inputs"], scope["as_of_position"], scope["profile_id"],
        "M4_04B4B_P4_TEST", "v1", "P4_SYN_01_SYNTHETIC", ingestion,
    )
    draft, _ = canonical_gold_to_draft_v1_1(gold, context)
    return CaseInput(CASE_ID, prepare_story_extraction_draft_v1_1(context), context), draft


def encoded(value):
    return json.dumps(value, ensure_ascii=False)


def schema_invalid(draft):
    broken = copy.deepcopy(draft)
    del broken["assertions"][0]["proposition_handle"]
    broken["assertions"][0]["polarity"] = MARKER
    return broken


def compiler_invalid(draft):
    broken = copy.deepcopy(draft)
    broken["assertions"][0]["proposition_handle"] = "PROP998"
    return broken


def empty_draft(draft):
    return {key: ([] if isinstance(value, list) else value) for key, value in draft.items()}


class MockTransport:
    """In-memory transport with the accepted window signature. Zero real operations."""

    def __init__(self, responses):
        self.responses = dict(responses)
        self.calls = []

    def __call__(self, spec, window, request_id):
        self.calls.append(spec.job_id)
        return {
            "raw_content": self.responses[spec.job_id],
            "model_requested": spec.model,
            "slot_id": spec.credential_slot,
            "transport_attempts": [{"model": spec.model, "slot_id": spec.credential_slot}],
            "attempt_accounting": {"total_provider_attempts": 1},
        }


class P4ProtocolLockTests(unittest.TestCase):
    def test_protocol_reconstructs_exactly_and_deterministically(self):
        first, second = protocol.build_protocol(), protocol.build_protocol()
        self.assertEqual(first, second)
        self.assertEqual(protocol.canonical_json_bytes(first), protocol.canonical_json_bytes(second))
        self.assertEqual(protocol.PROTOCOL_SHA256, protocol.protocol_sha256())
        self.assertEqual(protocol.PROTOCOL_SHA256, hashlib.sha256(protocol.canonical_json_bytes(first)).hexdigest())
        self.assertEqual(first, protocol.locked_protocol())
        self.assertEqual("M4_P4_STRUCTURAL_TUNING_PROTOCOL_V1", first["protocol_id"])
        self.assertEqual("P4_STORY_EXTRACTION_DRAFT_V1_1_SELF_CONTAINED_V1", first["candidate"]["extractor_id"])

    def test_protocol_binds_the_exact_runtime_settings(self):
        locked = protocol.locked_protocol()
        generation = locked["generation"]
        self.assertEqual("gemini-3.5-flash-lite", generation["model"])
        self.assertEqual("gemini_slot_3", generation["credential_slot"])
        self.assertIs(0, generation["temperature"])
        self.assertEqual(16384, generation["max_output_tokens"])
        self.assertEqual("application/json", generation["response_mime_type"])
        self.assertTrue(generation["native_schema_enabled"])
        self.assertEqual("response_json_schema", generation["native_schema_parameter"])
        self.assertEqual(protocol.MODEL_SCHEMA_SHA256, generation["native_schema_sha256"])
        durable = locked["durable_execution"]
        self.assertEqual((6, 60), (durable["global_pacing_max_operations"],
                                   durable["global_pacing_rolling_window_seconds"]))
        self.assertEqual("IMMUTABLE_LOCK", durable["first_success"])
        self.assertEqual("FORBIDDEN", durable["model_switch"])
        self.assertEqual("FORBIDDEN", durable["credential_switch"])
        repair = locked["repair_policy"]
        self.assertEqual(1, repair["maximum_per_case"])
        self.assertEqual("M4_P4_STRUCTURAL_REPAIR_DIAGNOSTIC_V2", repair["diagnostic"])
        self.assertEqual("FORBIDDEN", repair["quality_signal"])
        self.assertEqual("FORBIDDEN", repair["missing_fact_or_coverage_retry"])
        self.assertFalse(locked["data"]["bound_to_a_fresh_benchmark"])
        self.assertEqual("TUNING_DATA_AFTER_P3_FAILURE", locked["data"]["DEV3_status"])

    def test_every_bound_file_hash_is_exact(self):
        self.assertEqual("PASS", protocol.validate_bound_files()["bound_files"])
        for relative, expected in protocol.BOUND_FILES.items():
            with self.subTest(path=relative):
                self.assertEqual(expected, protocol.normalized_file_sha256(protocol.REPO_ROOT / relative))
        required = {
            "schemas/story_extraction/story_extraction_draft_v1_1_model_schema_v1.schema.json",
            "schemas/story_extraction/story_extraction_draft_v1_1.schema.json",
            "schemas/canonical_story/predicate_registry_v0.yaml",
            "tools/story_extraction/draft_compiler_v1_1.py",
            "tools/story_extraction/prompts/story_extraction_draft_p4_v1_system.txt",
            "tools/story_extraction/prompts/story_extraction_draft_p4_v1_user.txt",
            "tools/story_extraction/prompts/story_extraction_draft_p4_v1_repair_user.txt",
            "tools/story_extraction/gemini_resilience_v1_1.py",
            "tools/story_extraction/durable_research_executor_v1.py",
        }
        self.assertLessEqual(required, set(protocol.BOUND_FILES))
        self.assertEqual(
            "5aa2ed6dde3791546ddd5e059648d8dac38df1571a6073b7abc31c89eb257f14", protocol.MODEL_SCHEMA_SHA256
        )
        self.assertEqual(protocol.MODEL_SCHEMA_SHA256, materializer.model_schema_sha256())

    def test_prompt_hashes_are_those_of_the_assembled_prompts(self):
        material = contract.prompt_material()
        hashes = protocol.prompt_hashes()
        self.assertEqual(hashes, protocol.locked_protocol()["prompt_hashes"])
        self.assertEqual(hashlib.sha256(material["primary_system"].encode("utf-8")).hexdigest(),
                         hashes["primary_system_sha256"])
        self.assertEqual(hashlib.sha256(material["repair_system"].encode("utf-8")).hexdigest(),
                         hashes["repair_system_sha256"])

    def test_changed_bound_file_fails_closed(self):
        for relative in protocol.BOUND_FILES:
            with self.subTest(path=relative), mock.patch.dict(protocol.BOUND_FILES, {relative: "0" * 64}):
                with self.assertRaises(protocol.P4ProtocolError):
                    protocol.locked_protocol()
                with self.assertRaises(CheckpointIntegrityError):
                    runner.build_guard()()

    def test_changed_binding_is_a_different_protocol(self):
        changes = (
            ("MODEL", "other-model"), ("CREDENTIAL_SLOT", "gemini_slot_2"), ("MAX_STRUCTURAL_REPAIRS_PER_CASE", 2),
            ("GLOBAL_MAX_PROVIDER_OPERATIONS", 7), ("RESPONSE_MIME_TYPE", "text/plain"),
            ("WINDOW_COOLDOWN_SECONDS", 1), ("REPAIR_ELIGIBLE_CATEGORIES", ("JSON_PARSE_FAILURE", "LOW_COVERAGE")),
        )
        for name, value in changes:
            with self.subTest(binding=name), mock.patch.object(protocol, name, value):
                self.assertNotEqual(protocol.PROTOCOL_SHA256, protocol.protocol_sha256())
                with self.assertRaises(protocol.P4ProtocolError):
                    protocol.locked_protocol()
        for name, value in (("TEMPERATURE", 1), ("MAX_OUTPUT_TOKENS", 8192)):
            with self.subTest(binding=name), mock.patch.object(protocol, name, value):
                with self.assertRaises(protocol.P4ProtocolError):
                    protocol.locked_protocol()

    def test_single_source_schema_gate(self):
        self.assertEqual({"PASS"}, set(protocol.single_source_schema_gate().values()))
        system = contract.prompt_material()["primary_system"]
        in_prompt = contract.extract_prompt_schema(
            system, contract.SCHEMA_SECTION_MARKER, contract.REGISTRY_SECTION_MARKER
        )
        native = protocol.generation_config()["response_json_schema"]
        self.assertEqual(in_prompt, native)
        self.assertEqual(native, materializer.load_tracked_model_schema())
        self.assertEqual(native, materializer.materialize_model_schema())
        self.assertEqual([], materializer.external_refs(native))
        self.assertEqual(0, materializer.assert_self_contained(native)["external_ref_count"])

    def test_generation_config_is_built_from_the_contract_and_is_exact(self):
        config = protocol.generation_config()
        self.assertEqual({"temperature", "max_output_tokens", "response_json_schema"}, set(config))
        self.assertIs(int, type(config["temperature"]))
        self.assertEqual((0, 16384), (config["temperature"], config["max_output_tokens"]))
        self.assertEqual(contract.generation_config(), config)
        self.assertEqual(protocol.generation_config_sha256(),
                         protocol.locked_protocol()["generation"]["generation_config_sha256"])

    def test_divergent_native_schema_fails_closed(self):
        weakened = contract.generation_config()
        weakened["response_json_schema"] = copy.deepcopy(weakened["response_json_schema"])
        del weakened["response_json_schema"]["properties"]["draft_version"]["const"]
        without = {key: value for key, value in contract.generation_config().items() if key != "response_json_schema"}
        for label, config in (("weakened", weakened), ("removed", without)):
            with self.subTest(config=label), mock.patch.object(contract, "generation_config", return_value=config):
                for call in (protocol.generation_config, protocol.single_source_schema_gate,
                             protocol.locked_protocol):
                    with self.assertRaises(protocol.P4ProtocolError):
                        call()

    def test_executor_identity_carries_the_protocol_hash(self):
        self.assertEqual(protocol.PROTOCOL_ID + ":" + protocol.PROTOCOL_SHA256, protocol.executor_protocol_id())
        self.assertNotIn("P3", protocol.executor_protocol_id())


class P4JobSpecTests(unittest.TestCase):
    def setUp(self):
        self.case, self.draft = synthetic_case()
        self.spec = protocol.build_primary_spec(self.case.case_id, self.case.prepared_input)

    def test_primary_spec_is_exact(self):
        protocol.assert_locked_job_spec(self.spec)
        material = contract.prompt_material()
        self.assertEqual(PRIMARY, self.spec.job_id)
        self.assertEqual(material["primary_system"], self.spec.system_prompt)
        self.assertEqual(contract.render_primary_user(CASE_ID, self.case.prepared_input), self.spec.user_prompt)
        self.assertEqual(protocol.generation_config(), dict(self.spec.generation_config))
        self.assertEqual(materializer.load_tracked_model_schema(),
                         self.spec.generation_config["response_json_schema"])
        self.assertEqual(protocol.PROTOCOL_ID, self.spec.research_task_id)

    def test_response_json_schema_is_mandatory(self):
        config = {key: value for key, value in self.spec.generation_config.items() if key != "response_json_schema"}
        with self.assertRaisesRegex(protocol.P4ProtocolError, "mandatory"):
            protocol.assert_locked_job_spec(replace(self.spec, generation_config=config))

    def test_altered_schema_is_rejected(self):
        def altered(change):
            config = copy.deepcopy(dict(self.spec.generation_config))
            change(config["response_json_schema"])
            return replace(self.spec, generation_config=config)

        def drop_const(schema):
            del schema["properties"]["draft_version"]["const"]

        def drop_definition(schema):
            del schema["$defs"]["Assertion"]["required"]

        def add_keyword(schema):
            schema["additionalProperties"] = True

        def empty(schema):
            schema.clear()

        for change in (drop_const, drop_definition, add_keyword, empty):
            with self.subTest(change=change.__name__), self.assertRaises(protocol.P4ProtocolError):
                protocol.assert_locked_job_spec(altered(change))

    def test_any_other_alteration_is_rejected(self):
        config = dict(self.spec.generation_config)
        mutations = {
            "model": replace(self.spec, model="gemini-3.5-flash"),
            "credential": replace(self.spec, credential_slot="gemini_slot_2"),
            "mode": replace(self.spec, schema_response_mode="PROVIDER_JSON_MIME_ONLY_V1"),
            "task": replace(self.spec, research_task_id="M4-04B3F"),
            "system_prompt": replace(self.spec, system_prompt=self.spec.system_prompt + " "),
            "repair_system_on_primary": replace(self.spec, system_prompt=contract.prompt_material()["repair_system"]),
            "temperature": replace(self.spec, generation_config={**config, "temperature": 1}),
            "temperature_type": replace(self.spec, generation_config={**config, "temperature": 0.0}),
            "max_tokens": replace(self.spec, generation_config={**config, "max_output_tokens": 8192}),
            "extra_setting": replace(self.spec, generation_config={**config, "top_p": 1}),
            "second_repair": replace(self.spec, job_id=f"M4B4B_P4_{CASE_ID}_REPAIR_2"),
            "p3_job_id": replace(self.spec, job_id="M4B3F_P3_DEV3_01_PRIMARY"),
            "quality_retry": replace(self.spec, job_id=f"M4B4B_P4_{CASE_ID}_QUALITY_RETRY_1"),
        }
        for label, mutated in mutations.items():
            with self.subTest(mutation=label), self.assertRaises(protocol.P4ProtocolError):
                protocol.assert_locked_job_spec(mutated)

    def test_p3_and_p4_checkers_are_separate(self):
        with self.assertRaises(Dev3RunnerError):
            p3_assert_locked_job_spec(self.spec)
        p3_spec = p3_protocol.build_primary_spec("DEV3_01", self.case.prepared_input)
        p3_assert_locked_job_spec(p3_spec)
        with self.assertRaises(protocol.P4ProtocolError):
            protocol.assert_locked_job_spec(p3_spec)
        self.assertNotIn("response_json_schema", p3_spec.generation_config)
        source = Path(runner.__file__).read_text(encoding="utf-8")
        self.assertNotIn("_assert_locked_job_spec", source.replace("protocol.assert_locked_job_spec", ""))
        self.assertNotIn("m4_04b3f", source)

    def test_repair_spec_is_exact_and_receives_only_three_inputs(self):
        raw = encoded(schema_invalid(self.draft))
        diagnostic = contract.structural_diagnostic_v2(raw)
        spec = protocol.build_repair_spec(CASE_ID, self.case.prepared_input, raw, diagnostic)
        protocol.assert_locked_job_spec(spec)
        self.assertEqual(REPAIR, spec.job_id)
        self.assertEqual(contract.prompt_material()["repair_system"], spec.system_prompt)
        self.assertEqual(contract.render_repair_user(CASE_ID, self.case.prepared_input, raw, diagnostic),
                         spec.user_prompt)
        self.assertEqual(dict(self.spec.generation_config), dict(spec.generation_config))
        self.assertEqual(["case_id", "prepared_input", "primary_response", "diagnostic"],
                         list(inspect.signature(protocol.build_repair_spec).parameters))

    def test_repair_requires_an_eligible_structural_diagnostic_v2(self):
        raw = encoded(schema_invalid(self.draft))
        diagnostic = contract.structural_diagnostic_v2(raw)
        rejected = {
            "wrong_identity": {**diagnostic, "diagnostic": "M4_P3_REPAIR_DIAGNOSTIC_V1"},
            "coverage_category": {**diagnostic, "category": "LOW_COVERAGE"},
            "quality_category": {**diagnostic, "category": "QUALITY_FAILURE"},
            "no_findings": {**diagnostic, "findings": [], "finding_count": 0},
            "not_a_mapping": "DRAFT_SCHEMA_FAILURE",
        }
        for label, value in rejected.items():
            with self.subTest(diagnostic=label), self.assertRaises(protocol.P4ProtocolError):
                protocol.build_repair_spec(CASE_ID, self.case.prepared_input, raw, value)

    def test_invalid_case_id_is_rejected(self):
        for case_id in ("", "syn_01", "SYN 01", "../X", "A" * 41, None):
            with self.subTest(case_id=case_id), self.assertRaises(protocol.P4ProtocolError):
                protocol.build_primary_spec(case_id, self.case.prepared_input)


class P4RunnerSyntheticTests(unittest.TestCase):
    def setUp(self):
        self.case, self.draft = synthetic_case()

    def run_case(self, responses, **kwargs):
        provider = runner.OfflineMockProvider(responses)
        return runner.execute_case(self.case, provider, **kwargs), provider

    def test_valid_primary_needs_no_repair(self):
        result, provider = self.run_case({PRIMARY: encoded(self.draft), REPAIR: encoded(self.draft)})
        self.assertEqual("STRUCTURAL_VALID", result["terminal_status"])
        self.assertEqual(0, result["repair_count"])
        self.assertEqual([PRIMARY], provider.calls)
        self.assertIsNotNone(result["compiled_batch"])
        self.assertEqual(0, result["actual_provider_operations"])
        self.assertEqual(0, provider.actual_provider_operations)

    def test_valid_draft_compiles_through_the_unchanged_path(self):
        parsed, batch, validation = runner.compile_raw_response(encoded(self.draft), self.case)
        self.assertEqual(self.draft, parsed)
        self.assertIsNotNone(batch)
        self.assertEqual({"pass": True, "category": None, "diagnostic": None}, validation)
        source = inspect.getsource(runner.compile_raw_response)
        self.assertIn("validate_draft_v1_1(draft)", source)
        self.assertIn("compile_story_extraction_draft_v1_1(draft, case.compiler_context)", source)

    def test_invalid_json_makes_one_repair_eligible(self):
        result, provider = self.run_case({PRIMARY: '{"draft_version": ', REPAIR: encoded(self.draft)})
        self.assertEqual([PRIMARY, REPAIR], provider.calls)
        primary = result["attempts"][0]["validation"]
        self.assertEqual("JSON_PARSE_FAILURE", primary["category"])
        self.assertEqual("M4_P4_STRUCTURAL_REPAIR_DIAGNOSTIC_V2", primary["diagnostic"]["diagnostic"])
        self.assertEqual("JSON_PARSE_FAILURE", primary["diagnostic"]["category"])
        self.assertTrue(primary["diagnostic"]["findings"])
        self.assertEqual("STRUCTURAL_VALID", result["terminal_status"])
        self.assertEqual(1, result["repair_count"])

    def test_schema_failure_gives_diagnostic_v2(self):
        raw = encoded(schema_invalid(self.draft))
        draft, batch, validation = runner.compile_raw_response(raw, self.case)
        self.assertIsNotNone(draft)
        self.assertIsNone(batch)
        self.assertEqual("DRAFT_SCHEMA_FAILURE", validation["category"])
        diagnostic = validation["diagnostic"]
        self.assertEqual(contract.structural_diagnostic_v2(raw), diagnostic)
        self.assertEqual(contract.REPAIR_DIAGNOSTIC_ID, diagnostic["diagnostic"])
        self.assertEqual(len(diagnostic["findings"]), diagnostic["finding_count"])
        text = encoded(diagnostic)
        self.assertIn("proposition_handle", text)
        self.assertNotIn(MARKER, text)

    def test_compiler_failure_gives_diagnostic_v2(self):
        raw = encoded(compiler_invalid(self.draft))
        draft, batch, validation = runner.compile_raw_response(raw, self.case)
        self.assertIsNotNone(draft)
        self.assertIsNone(batch)
        self.assertEqual("DRAFT_COMPILER_FAILURE", validation["category"])
        diagnostic = validation["diagnostic"]
        self.assertEqual(
            {"diagnostic", "model_schema", "category", "finding_count", "findings"}, set(diagnostic)
        )
        self.assertEqual(contract.REPAIR_DIAGNOSTIC_ID, diagnostic["diagnostic"])
        self.assertEqual("DRAFT_COMPILER_FAILURE", diagnostic["category"])
        self.assertGreaterEqual(diagnostic["finding_count"], 1)
        self.assertNotIn("PROP998", encoded(diagnostic))
        spec = protocol.build_repair_spec(CASE_ID, self.case.prepared_input, raw, diagnostic)
        protocol.assert_locked_job_spec(spec)

    def test_repair_request_carries_prepared_input_primary_response_and_diagnostic(self):
        raw = encoded(schema_invalid(self.draft))
        result, provider = self.run_case({PRIMARY: raw, REPAIR: encoded(self.draft)})
        repair_spec = provider.specs[1]
        diagnostic = result["attempts"][0]["validation"]["diagnostic"]
        self.assertEqual(contract.render_repair_user(CASE_ID, self.case.prepared_input, raw, diagnostic),
                         repair_spec.user_prompt)
        self.assertEqual(protocol.generation_config(), dict(repair_spec.generation_config))

    def test_valid_repair_is_structurally_valid(self):
        for broken in (schema_invalid(self.draft), compiler_invalid(self.draft)):
            result, provider = self.run_case({PRIMARY: encoded(broken), REPAIR: encoded(self.draft)})
            self.assertEqual("STRUCTURAL_VALID", result["terminal_status"])
            self.assertEqual(1, result["repair_count"])
            self.assertIsNotNone(result["compiled_batch"])
            self.assertEqual([PRIMARY, REPAIR], provider.calls)

    def test_invalid_repair_is_terminal_and_a_second_repair_is_impossible(self):
        responses = {PRIMARY: "{", REPAIR: encoded(schema_invalid(self.draft)),
                     f"M4B4B_P4_{CASE_ID}_REPAIR_2": encoded(self.draft)}
        result, provider = self.run_case(responses)
        self.assertEqual("STRUCTURAL_FAILURE", result["terminal_status"])
        self.assertEqual(1, result["repair_count"])
        self.assertEqual([PRIMARY, REPAIR], provider.calls)
        self.assertIsNone(result["compiled_batch"])
        self.assertEqual("DRAFT_SCHEMA_FAILURE", result["terminal_validation"]["category"])
        self.assertEqual(2, len(result["attempts"]))
        self.assertFalse(hasattr(protocol, "build_second_repair_spec"))
        self.assertEqual(1, protocol.MAX_STRUCTURAL_REPAIRS_PER_CASE)

    def test_quality_or_coverage_retry_is_impossible(self):
        result, provider = self.run_case({PRIMARY: encoded(empty_draft(self.draft)), REPAIR: encoded(self.draft)})
        self.assertEqual("STRUCTURAL_VALID", result["terminal_status"])
        self.assertEqual([PRIMARY], provider.calls)
        self.assertEqual(0, result["quality_or_coverage_retries"])
        names = set(inspect.signature(runner.execute_case).parameters)
        self.assertFalse(any(token in name.lower() for name in names
                             for token in ("gold", "quality", "coverage", "evaluat", "score")))
        with mock.patch.object(runner, "compile_raw_response", return_value=(
                {}, None, {"pass": False, "category": "LOW_COVERAGE", "diagnostic": None})):
            provider = runner.OfflineMockProvider({PRIMARY: encoded(self.draft), REPAIR: encoded(self.draft)})
            with self.assertRaisesRegex(runner.P4RunnerError, "forbidden"):
                runner.execute_case(self.case, provider)
            self.assertEqual([PRIMARY], provider.calls)

    def test_repair_can_be_withheld(self):
        result, provider = self.run_case({PRIMARY: "{", REPAIR: encoded(self.draft)}, allow_repair=False)
        self.assertEqual("STRUCTURAL_FAILURE", result["terminal_status"])
        self.assertEqual(0, result["repair_count"])
        self.assertEqual([PRIMARY], provider.calls)

    def test_first_success_is_immutable(self):
        ledger = FirstSuccessLedger()
        first = runner.OfflineMockProvider({PRIMARY: encoded(self.draft)})
        runner.execute_case(self.case, first, ledger=ledger)
        same = runner.OfflineMockProvider({PRIMARY: encoded(self.draft)})
        runner.execute_case(self.case, same, ledger=ledger)
        different = runner.OfflineMockProvider({PRIMARY: encoded(empty_draft(self.draft))})
        with self.assertRaisesRegex(runner.P4RunnerError, "Immutable first-success"):
            runner.execute_case(self.case, different, ledger=ledger)
        with self.assertRaisesRegex(runner.P4RunnerError, "invoked twice"):
            first.first_success(protocol.build_primary_spec(CASE_ID, self.case.prepared_input))

    def test_provider_rejects_any_request_that_is_not_the_locked_one(self):
        provider = runner.OfflineMockProvider({PRIMARY: encoded(self.draft)})
        spec = protocol.build_primary_spec(CASE_ID, self.case.prepared_input)
        config = dict(spec.generation_config)
        without = {key: value for key, value in config.items() if key != "response_json_schema"}
        changed = copy.deepcopy(config)
        del changed["response_json_schema"]["$defs"]["Mention"]["required"]
        for label, mutated in (
            ("schema_removed", replace(spec, generation_config=without)),
            ("schema_changed", replace(spec, generation_config=changed)),
            ("prompt_changed", replace(spec, system_prompt="Return JSON.")),
            ("model_switch", replace(spec, model="gemini-3.5-pro")),
            ("key_switch", replace(spec, credential_slot="gemini_slot_1")),
        ):
            with self.subTest(mutation=label), self.assertRaises(protocol.P4ProtocolError):
                provider.first_success(mutated)
        self.assertEqual([], provider.calls)

    def test_changed_prompt_or_schema_stops_execution_before_any_request(self):
        provider = runner.OfflineMockProvider({PRIMARY: encoded(self.draft)})
        material = dict(contract.prompt_material())
        material["primary_system"] = material["primary_system"] + "\nBe generous."
        spec = protocol.build_primary_spec(CASE_ID, self.case.prepared_input)
        with mock.patch.object(protocol, "build_primary_spec", return_value=replace(
                spec, system_prompt=material["primary_system"])):
            with self.assertRaises(protocol.P4ProtocolError):
                runner.execute_case(self.case, provider)
        self.assertEqual([], provider.calls)

    def test_offline_execution_forbids_provider_operations(self):
        class Spending(runner.OfflineMockProvider):
            def first_success(self, spec):
                success = super().first_success(spec)
                self.actual_provider_operations += 1
                return ProviderFirstSuccess(success.raw_response, 1, success.success_identity)

        with self.assertRaisesRegex(runner.P4RunnerError, "forbids provider operations"):
            runner.execute_case(self.case, Spending({PRIMARY: encoded(self.draft)}))

    def test_runner_takes_no_gold_or_evaluator_input(self):
        for function in (runner.execute_case, runner.compile_raw_response, runner.run_synthetic_smoke,
                         runner.synthetic_smoke_case):
            names = set(inspect.signature(function).parameters)
            self.assertFalse(any("gold" in name.lower() or "evaluat" in name.lower() for name in names))
        source = Path(runner.__file__).read_text(encoding="utf-8")
        self.assertNotIn("zipfile", source)
        self.assertNotIn("evaluate", source)


class P4DurableCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.case, self.draft = synthetic_case()
        directory = tempfile.TemporaryDirectory(prefix="m4b4b_")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def provider(self, transport):
        pacer, executor = runner.build_durable_stack(self.root / "checkpoints")
        return pacer, executor, DurableFirstSuccessProvider(
            executor, transport, runner.build_guard(), counts_real_provider_operations=False
        )

    def execute(self, provider):
        with contextlib.redirect_stdout(io.StringIO()):
            return runner.execute_case(self.case, provider)

    def test_checkpoint_carries_the_p4_identity_and_locked_limits(self):
        transport = MockTransport({PRIMARY: encoded(self.draft)})
        pacer, executor, provider = self.provider(transport)
        result = self.execute(provider)
        self.assertEqual("STRUCTURAL_VALID", result["terminal_status"])
        self.assertEqual(0, result["actual_provider_operations"])
        spec = protocol.build_primary_spec(CASE_ID, self.case.prepared_input)
        record = executor.load_job(spec)
        self.assertEqual(protocol.executor_protocol_id(), record["protocol_id"])
        self.assertEqual(JobState.SUCCEEDED_LOCKED.value, record["state"])
        self.assertEqual(spec.request_fingerprint, record["request_fingerprint"])
        self.assertEqual((6, 60), (pacer.max_operations, pacer.window_seconds))
        self.assertEqual(60, executor.window_cooldown_seconds)

    def test_restart_replays_the_locked_first_success_without_a_new_request(self):
        first = MockTransport({PRIMARY: "{", REPAIR: encoded(self.draft)})
        _, _, provider = self.provider(first)
        self.assertEqual("STRUCTURAL_VALID", self.execute(provider)["terminal_status"])
        self.assertEqual([PRIMARY, REPAIR], first.calls)
        second = MockTransport({PRIMARY: encoded(self.draft), REPAIR: "{"})
        _, _, restarted = self.provider(second)
        replay = self.execute(restarted)
        self.assertEqual([], second.calls)
        self.assertEqual("STRUCTURAL_VALID", replay["terminal_status"])
        self.assertEqual(1, replay["repair_count"])
        self.assertEqual("{", replay["attempts"][0]["raw"])

    def test_checkpoint_of_another_protocol_is_rejected(self):
        transport = MockTransport({PRIMARY: encoded(self.draft)})
        _, _, provider = self.provider(transport)
        self.execute(provider)
        foreign = DurableResearchExecutor(
            self.root / "checkpoints" / "jobs", protocol_id="M4_04B3F_DEV3_P3_PROTOCOL_V1",
            window_cooldown_seconds=protocol.WINDOW_COOLDOWN_SECONDS,
        )
        with self.assertRaises(CheckpointIntegrityError):
            foreign.load_job(protocol.build_primary_spec(CASE_ID, self.case.prepared_input))

    def test_changed_request_does_not_match_an_existing_checkpoint(self):
        transport = MockTransport({PRIMARY: encoded(self.draft)})
        _, executor, provider = self.provider(transport)
        self.execute(provider)
        spec = protocol.build_primary_spec(CASE_ID, self.case.prepared_input)
        with self.assertRaises(CheckpointIntegrityError):
            executor.load_job(replace(spec, user_prompt=spec.user_prompt + " "))

    def test_transport_that_switches_model_or_key_fails_closed(self):
        class Switching(MockTransport):
            def __init__(self, responses, **changed):
                super().__init__(responses)
                self.changed = changed

            def __call__(self, spec, window, request_id):
                return {**super().__call__(spec, window, request_id), **self.changed}

        for label, changed in (("model", {"model_requested": "gemini-3.5-pro"}), ("key", {"slot_id": "gemini_slot_1"})):
            with self.subTest(switch=label):
                directory = tempfile.TemporaryDirectory(prefix="m4b4b_switch_")
                self.addCleanup(directory.cleanup)
                _, executor = runner.build_durable_stack(Path(directory.name))
                spec = protocol.build_primary_spec(CASE_ID, self.case.prepared_input)
                with self.assertRaises(CheckpointIntegrityError):
                    executor.execute_window(spec, Switching({PRIMARY: encoded(self.draft)}, **changed))
                self.assertEqual(JobState.TERMINAL_FAILED.value, executor.load_job(spec)["state"])

    def test_only_the_locked_credential_slot_can_be_selected(self):
        def config(*slots):
            return SimpleNamespace(credentials=[SimpleNamespace(slot_id=slot) for slot in slots])

        chosen = runner.select_locked_credential(config("gemini_slot_1", "gemini_slot_3", "gemini_slot_2"))
        self.assertEqual("gemini_slot_3", chosen.slot_id)
        for slots in ((), ("gemini_slot_1", "gemini_slot_2"), ("gemini_slot_3", "gemini_slot_3")):
            with self.subTest(slots=slots), self.assertRaises(runner.P4RunnerError):
                runner.select_locked_credential(config(*slots))


class P4SyntheticSmokeMockedTests(unittest.TestCase):
    """The smoke path with an injected transport. No provider is constructed."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="m4b4b_smoke_")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "private"
        self.transport_calls = 0

    def factory(self, behaviour):
        def build(pacer, guard):
            def transport(spec, window, request_id):
                self.transport_calls += 1
                guard()
                return behaviour(pacer, spec)
            return transport
        return build

    @staticmethod
    def success(raw):
        def behaviour(pacer, spec):
            pacer.acquire()
            return {"raw_content": raw, "model_requested": spec.model, "slot_id": spec.credential_slot,
                    "transport_attempts": [{"model": spec.model, "slot_id": spec.credential_slot,
                                            "classified_result": "SUCCESS", "http_status": 200}],
                    "attempt_accounting": {"total_provider_attempts": 1}}
        return behaviour

    @staticmethod
    def failure(category, status, reason, attempts=1):
        def behaviour(pacer, spec):
            history = []
            for _ in range(attempts):
                try:
                    pacer.acquire()
                except runner.OperationBudgetExhausted:
                    raise CheckpointIntegrityError("Global pacing attempt accounting mismatch") from None
                history.append({"model": spec.model, "slot_id": spec.credential_slot, "classified_result": category,
                                "http_status": status, "provider_reason": reason})
            raise DurableTransportFailure(category, provider_attempts=len(history),
                                          fingerprint=f"{category}:{status}", attempts=history)
        return behaviour

    def smoke(self, behaviour, **kwargs):
        return runner.run_synthetic_smoke(private_root=self.root, transport_factory=self.factory(behaviour), **kwargs)

    def test_smoke_case_is_one_invented_sentence(self):
        case = runner.synthetic_smoke_case()
        self.assertEqual("SYNTHETIC_SMOKE_01", case.case_id)
        self.assertEqual(
            {"draft_version": "STORY_EXTRACTION_DRAFT_V1_1", "existing_context": {},
             "passages": [{"handle": "P1", "use": "EVIDENCE_ELIGIBLE", "text": runner.SMOKE_TEXT}]},
            case.prepared_input,
        )
        self.assertEqual(case.prepared_input, runner.synthetic_smoke_case().prepared_input)
        spec = protocol.build_primary_spec(case.case_id, case.prepared_input)
        protocol.assert_locked_job_spec(spec)
        self.assertEqual(SMOKE_PRIMARY, spec.job_id)
        _, batch, validation = runner.compile_raw_response(encoded(SMOKE_DRAFT), case)
        self.assertTrue(validation["pass"])
        self.assertIsNotNone(batch)

    def test_accepted_request_records_each_stage_independently(self):
        result = self.smoke(self.success(encoded(SMOKE_DRAFT)))
        self.assertTrue(result["synthetic_only"])
        self.assertIs(True, result["provider_schema_request_accepted"])
        self.assertIs(True, result["provider_response_received"])
        self.assertIs(True, result["json_parse"])
        self.assertIs(True, result["local_schema_validation"])
        self.assertIs(True, result["compiler"])
        self.assertFalse(result["repair_used"])
        self.assertEqual(1, result["provider_operations"])
        self.assertEqual(1, result["execution_windows"])
        self.assertEqual(1, self.transport_calls)
        self.assertEqual("INJECTED_MOCK", result["transport"])
        self.assertFalse(result["dataset_accessed"])
        self.assertEqual(protocol.PROTOCOL_SHA256, result["protocol_sha256"])
        stored = json.loads((self.root / f"{runner.SMOKE_RESULT_ID}.json").read_text(encoding="utf-8"))
        self.assertEqual(result, stored)
        self.assertTrue((self.root / "raw" / "SYNTHETIC_SMOKE_01_primary.txt").is_file())
        self.assertTrue((self.root / "compiled" / "SYNTHETIC_SMOKE_01.json").is_file())
        self.assertFalse((self.root / "failures").exists())

    def test_local_failures_after_acceptance_do_not_spend_a_repair(self):
        case = runner.synthetic_smoke_case()
        del case
        cases = (
            ('{"draft_version": ', (False, None, None), "JSON_PARSE_FAILURE"),
            (encoded(schema_invalid(SMOKE_DRAFT)), (True, False, None), "DRAFT_SCHEMA_FAILURE"),
            (encoded(compiler_invalid(SMOKE_DRAFT)), (True, True, False), "DRAFT_COMPILER_FAILURE"),
            ("", (False, None, None), "JSON_PARSE_FAILURE"),
        )
        for index, (raw, stages, category) in enumerate(cases):
            with self.subTest(category=category, index=index):
                self.root = self.root.parent / f"private_{index}"
                self.transport_calls = 0
                result = self.smoke(self.success(raw))
                self.assertIs(True, result["provider_schema_request_accepted"])
                self.assertIs(True, result["provider_response_received"])
                self.assertEqual(stages, (result["json_parse"], result["local_schema_validation"], result["compiler"]))
                self.assertEqual(category, result["structural_failure_category"])
                self.assertGreaterEqual(result["structural_finding_count"], 1)
                self.assertFalse(result["repair_used"])
                self.assertEqual(1, result["provider_operations"])
                self.assertEqual(1, self.transport_calls)
                self.assertFalse(any("REPAIR" in path.name for path in (self.root / "checkpoints" / "jobs").iterdir()))

    def test_provider_rejection_is_recorded_and_never_retried(self):
        result = self.smoke(self.failure("PROVIDER_FAILURE", 400, "INVALID_ARGUMENT"))
        self.assertIs(False, result["provider_schema_request_accepted"])
        self.assertEqual("PROVIDER_FAILURE:400:INVALID_ARGUMENT", result["provider_rejection_category"])
        self.assertIs(False, result["provider_response_received"])
        self.assertEqual((None, None, None),
                         (result["json_parse"], result["local_schema_validation"], result["compiler"]))
        self.assertEqual(1, result["provider_operations"])
        self.assertEqual(1, result["execution_windows"])
        self.assertEqual(1, self.transport_calls)
        self.assertEqual(JobState.DEFERRED_TRANSPORT.value, result["job_state"])
        self.assertFalse(result["repair_used"])

    def test_transient_failure_leaves_acceptance_undetermined(self):
        result = self.smoke(self.failure("SERVER_FAILURE", 503, "UNAVAILABLE", attempts=2))
        self.assertEqual("UNDETERMINED", result["provider_schema_request_accepted"])
        self.assertEqual("SERVER_FAILURE:503:UNAVAILABLE", result["provider_rejection_category"])
        self.assertEqual(2, result["provider_operations"])
        self.assertFalse(result["operation_budget_exhausted"])
        self.assertEqual(1, self.transport_calls)

    def test_a_third_provider_operation_is_refused_before_it_starts(self):
        result = self.smoke(self.failure("SERVER_FAILURE", 503, "UNAVAILABLE", attempts=3))
        self.assertTrue(result["operation_budget_exhausted"])
        self.assertEqual(2, result["provider_operations"])
        self.assertEqual("UNDETERMINED", result["provider_schema_request_accepted"])
        self.assertEqual("OPERATION_BUDGET_EXHAUSTED_BY_TRANSIENT_FAILURES", result["provider_rejection_category"])
        self.assertEqual(JobState.TERMINAL_FAILED.value, result["job_state"])
        self.assertIs(False, result["provider_response_received"])

    def test_budget_is_persistent_and_never_above_two(self):
        self.assertEqual(2, runner.SMOKE_OPERATION_BUDGET)
        with self.assertRaisesRegex(runner.P4RunnerError, "never exceeds two"):
            self.smoke(self.success(encoded(SMOKE_DRAFT)), operation_budget=3)
        self.assertEqual(0, self.transport_calls)
        pacer, _ = runner.build_durable_stack(self.root / "budget")
        for budget in (0, -1, True, 1.5):
            with self.subTest(budget=budget), self.assertRaises(runner.P4RunnerError):
                runner.BudgetedPacer(pacer, budget)
        first = runner.BudgetedPacer(pacer, 2)
        first.acquire()
        first.acquire()
        restarted = runner.BudgetedPacer(runner.build_durable_stack(self.root / "budget")[0], 2)
        with self.assertRaises(runner.OperationBudgetExhausted):
            restarted.acquire()
        self.assertEqual(2, restarted.snapshot()["reservation_count"])
        self.assertEqual(1, restarted.refusals)

    def test_unrelated_integrity_error_is_not_mistaken_for_budget_exhaustion(self):
        def behaviour(pacer, spec):
            raise CheckpointIntegrityError("Credential lock mismatch")

        with self.assertRaises(CheckpointIntegrityError):
            self.smoke(behaviour)
        self.assertFalse((self.root / f"{runner.SMOKE_RESULT_ID}.json").exists())

    def test_smoke_is_not_repeated(self):
        self.smoke(self.failure("PROVIDER_FAILURE", 400, "INVALID_ARGUMENT"))
        self.assertEqual(1, self.transport_calls)
        with self.assertRaisesRegex(runner.P4RunnerError, "not repeated"):
            self.smoke(self.success(encoded(SMOKE_DRAFT)))
        self.assertEqual(1, self.transport_calls)

    def test_private_root_inside_the_repository_must_be_ignored_storage(self):
        for root in (runner.REPO_ROOT, runner.REPO_ROOT / "benchmarks" / "smoke", runner.REPO_ROOT / "docs"):
            with self.subTest(root=root.name), self.assertRaises(runner.P4RunnerError):
                runner.run_synthetic_smoke(private_root=root, transport_factory=self.factory(self.success("{}")))
        self.assertEqual(0, self.transport_calls)
        self.assertEqual(".local", runner.DEFAULT_SMOKE_ROOT.relative_to(runner.REPO_ROOT).parts[0])

    def test_changed_protocol_stops_the_smoke_before_any_request(self):
        relative = "tools/story_extraction/prompts/story_extraction_draft_p4_v1_system.txt"
        with mock.patch.dict(protocol.BOUND_FILES, {relative: "0" * 64}):
            with self.assertRaises(protocol.P4ProtocolError):
                self.smoke(self.success(encoded(SMOKE_DRAFT)))
        self.assertEqual(0, self.transport_calls)

    def test_command_line_requires_the_explicit_authorization_token(self):
        for arguments in (["--mode", "synthetic-smoke"],
                          ["--mode", "synthetic-smoke", "--authorize-live-provider-operations", "yes"]):
            output = io.StringIO()
            with mock.patch.object(runner, "run_synthetic_smoke") as smoke, contextlib.redirect_stdout(output):
                self.assertEqual(2, runner.main(arguments))
            smoke.assert_not_called()
            self.assertIn("FAIL_CLOSED", output.getvalue())
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(0, runner.main(["--mode", "verify"]))
        self.assertEqual(0, json.loads(output.getvalue())["provider_operations"])


class FakeProviderError(Exception):
    """Shaped like an SDK API error: a status code, a structured status and a message."""

    def __init__(self, code, status):
        super().__init__(f"{code} {status}. {MARKER} provider message text")
        self.code = code
        self.status = status


class P4SyntheticSmokeAcceptedTransportTests(unittest.TestCase):
    """The live smoke path end to end, with the SDK client replaced. No network, no real key."""

    FAKE_KEY = "synthetic-credential-3-not-a-real-key"

    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="m4b4b_live_path_")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "private"
        self.env = Path(directory.name) / "absent.env"
        self.requests = []
        self.keys = []

    def smoke(self, respond, environ=None):
        from tools.story_extraction.gemini_key_pool_v1 import load_runtime_config

        environ = {"GEMINI_API_KEY_3": self.FAKE_KEY} if environ is None else environ

        def fake_client_factory(api_key):
            self.keys.append(api_key)

            def generate(**kwargs):
                self.requests.append(kwargs)
                return respond(len(self.requests))
            return SimpleNamespace(generate=generate)

        patches = (
            mock.patch.object(runner, "load_runtime_config", side_effect=lambda: load_runtime_config(self.env, environ)),
            mock.patch.object(runner, "verify_execution_environment",
                              return_value={"method": "SYNTHETIC_TEST_ENVIRONMENT", "source_commit": "0" * 40}),
            mock.patch("tools.story_extraction.run_m4_04b2_dev_predictions_v1.official_client_factory",
                       side_effect=fake_client_factory),
            mock.patch("time.sleep"),
        )
        with contextlib.ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            return runner.run_synthetic_smoke(private_root=self.root)

    def private_text(self):
        return "\n".join(path.read_text(encoding="utf-8") for path in self.root.rglob("*") if path.is_file())

    @staticmethod
    def answer(text):
        return lambda count: SimpleNamespace(text=text, usage_metadata=None, model_version="synthetic-model-version")

    @staticmethod
    def error(code, status):
        def respond(count):
            raise FakeProviderError(code, status)
        return respond

    def test_one_request_carries_the_locked_model_prompt_and_native_schema(self):
        result = self.smoke(self.answer(encoded(SMOKE_DRAFT)))
        self.assertEqual(1, len(self.requests))
        request = self.requests[0]
        material = contract.prompt_material()
        self.assertEqual("gemini-3.5-flash-lite", request["model"])
        self.assertEqual(material["primary_system"], request["system_instruction"])
        self.assertIn(runner.SMOKE_TEXT, request["user_content"])
        self.assertEqual(materializer.load_tracked_model_schema(),
                         request["generation_config"]["response_json_schema"])
        self.assertEqual({"temperature", "max_output_tokens", "response_json_schema"},
                         set(request["generation_config"]))
        self.assertEqual([self.FAKE_KEY], self.keys)
        self.assertEqual("ACCEPTED_GEMINI_DEV_WINDOW_TRANSPORT", result["transport"])
        self.assertEqual("SYNTHETIC_TEST_ENVIRONMENT", result["execution_environment"])
        self.assertEqual(protocol.normalized_file_sha256(Path(runner.__file__)), result["runner_sha256"])
        self.assertEqual(protocol.normalized_file_sha256(Path(protocol.__file__)), result["protocol_module_sha256"])
        self.assertEqual(
            (True, True, True, True, True),
            (result["provider_schema_request_accepted"], result["provider_response_received"],
             result["json_parse"], result["local_schema_validation"], result["compiler"]),
        )
        self.assertEqual((1, 1, 1), (result["provider_operations"], result["checkpointed_provider_operations"],
                                      result["execution_windows"]))
        self.assertEqual("gemini_slot_3", result["credential_slot"])
        self.assertEqual("PASS", result["pacing_invariant"])
        self.assertNotIn(self.FAKE_KEY, self.private_text())

    def test_request_rejected_with_400_is_one_operation_and_no_retry(self):
        result = self.smoke(self.error(400, "INVALID_ARGUMENT"))
        self.assertEqual(1, len(self.requests))
        self.assertIs(False, result["provider_schema_request_accepted"])
        self.assertEqual("PROVIDER_FAILURE:400:INVALID_ARGUMENT", result["provider_rejection_category"])
        self.assertIs(False, result["provider_response_received"])
        self.assertEqual((1, 1), (result["provider_operations"], result["execution_windows"]))
        self.assertEqual(JobState.DEFERRED_TRANSPORT.value, result["job_state"])
        self.assertEqual(materializer.load_tracked_model_schema(),
                         self.requests[0]["generation_config"]["response_json_schema"])
        text = self.private_text()
        self.assertNotIn(MARKER, text)
        self.assertNotIn(self.FAKE_KEY, text)
        with self.assertRaisesRegex(runner.P4RunnerError, "not repeated"):
            self.smoke(self.answer(encoded(SMOKE_DRAFT)))
        self.assertEqual(1, len(self.requests))

    def test_persistent_server_failure_stops_at_two_operations(self):
        result = self.smoke(self.error(503, "UNAVAILABLE"))
        self.assertEqual(2, len(self.requests))
        self.assertEqual(2, result["provider_operations"])
        self.assertTrue(result["operation_budget_exhausted"])
        self.assertEqual("UNDETERMINED", result["provider_schema_request_accepted"])
        self.assertIs(False, result["provider_response_received"])
        self.assertEqual(1, result["execution_windows"])

    def test_server_failure_then_success_uses_two_operations(self):
        def respond(count):
            if count == 1:
                raise FakeProviderError(503, "UNAVAILABLE")
            return SimpleNamespace(text=encoded(SMOKE_DRAFT), usage_metadata=None, model_version="synthetic")

        result = self.smoke(respond)
        self.assertEqual(2, len(self.requests))
        self.assertEqual(2, result["provider_operations"])
        self.assertFalse(result["operation_budget_exhausted"])
        self.assertIs(True, result["provider_schema_request_accepted"])
        self.assertIs(True, result["compiler"])

    def test_authentication_failure_is_not_reported_as_a_schema_rejection(self):
        result = self.smoke(self.error(403, "PERMISSION_DENIED"))
        self.assertEqual(1, len(self.requests))
        self.assertEqual("UNDETERMINED", result["provider_schema_request_accepted"])
        self.assertEqual("AUTH_FAILURE:403:PERMISSION_DENIED", result["provider_rejection_category"])
        self.assertEqual(1, result["provider_operations"])

    def test_missing_or_other_credential_slot_stops_before_any_client_exists(self):
        for environ in ({}, {"GEMINI_API_KEY_1": "synthetic-credential-1", "GEMINI_API_KEY_2": "synthetic-credential-2"}):
            with self.subTest(slots=sorted(environ)), self.assertRaises(runner.P4RunnerError):
                self.smoke(self.answer(encoded(SMOKE_DRAFT)), environ=environ)
        self.assertEqual([], self.keys)
        self.assertEqual([], self.requests)

    def test_other_configured_slots_are_never_used(self):
        environ = {"GEMINI_API_KEY_1": "synthetic-credential-1", "GEMINI_API_KEY_3": self.FAKE_KEY,
                   "GEMINI_API_KEY_5": "synthetic-credential-5"}
        result = self.smoke(self.error(503, "UNAVAILABLE"), environ=environ)
        self.assertEqual([self.FAKE_KEY, self.FAKE_KEY], self.keys)
        self.assertEqual(2, result["provider_operations"])


class P4PublicRecordTests(unittest.TestCase):
    """The public record of the protocol lock and of the one live synthetic smoke."""

    RECORD = protocol.REPO_ROOT / "benchmarks/m4_extraction/M4_04B4B_P4_RUNTIME_PROTOCOL_AND_NATIVE_SCHEMA_SMOKE.yaml"
    STATUSES = {
        "M4_04B4B_P4_RUNTIME_READY": "M4-04B4C — P4 STRUCTURAL TUNING RUN ON DEV3 INPUT",
        "M4_04B4B_NATIVE_SCHEMA_PROVIDER_REJECTED": "ORCHESTRATOR REVIEW OF PROVIDER-COMPATIBLE SCHEMA PROJECTION",
    }

    def setUp(self):
        self.text = self.RECORD.read_text(encoding="utf-8")
        self.record = yaml.safe_load(self.text)

    def test_record_identifies_the_locked_p4_candidate_and_protocol(self):
        record = self.record
        self.assertEqual("M4-04B4B", record["task"])
        self.assertEqual(protocol.EXPECTED_BASE_COMMIT, record["base_commit"])
        p4 = record["p4"]
        self.assertEqual(protocol.EXTRACTOR_ID, p4["extractor_id"])
        self.assertEqual(protocol.MODEL_SCHEMA_SHA256, p4["model_schema_sha256"])
        self.assertEqual(protocol.prompt_hashes(), p4["prompt_hashes"])
        self.assertEqual(contract.REPAIR_DIAGNOSTIC_ID, p4["repair_diagnostic"])
        self.assertEqual(protocol.BOUND_FILES["tools/story_extraction/draft_compiler_v1_1.py"],
                         p4["canonical_compiler"]["sha256"])
        locked = record["protocol"]
        self.assertEqual(protocol.PROTOCOL_ID, locked["identity"])
        self.assertEqual(protocol.PROTOCOL_SHA256, locked["canonical_protocol_sha256"])
        self.assertEqual(protocol.protocol_sha256(), locked["canonical_protocol_sha256"])
        self.assertEqual(("gemini-3.5-flash-lite", "gemini_slot_3"), (locked["model"], locked["credential_slot"]))
        self.assertEqual(protocol.RUNTIME_VERSION, locked["runtime"])
        self.assertEqual(protocol.generation_config_sha256(), locked["generation_config_sha256"])
        self.assertIs(True, locked["native_schema_enabled"])
        self.assertEqual(dict(protocol.BOUND_FILES), locked["bound_files"])
        self.assertIs(False, locked["bound_to_a_fresh_benchmark"])

    def test_the_code_that_ran_live_is_the_code_that_is_tracked(self):
        locked, smoke = self.record["protocol"], self.record["live_smoke"]
        runner_sha256 = protocol.normalized_file_sha256(Path(runner.__file__))
        module_sha256 = protocol.normalized_file_sha256(Path(protocol.__file__))
        self.assertEqual(runner_sha256, locked["runner"]["sha256"])
        self.assertEqual(module_sha256, locked["protocol_module"]["sha256"])
        self.assertEqual(runner_sha256, smoke["executed_runner_sha256"])
        self.assertEqual(module_sha256, smoke["executed_protocol_module_sha256"])
        self.assertEqual(protocol.PROTOCOL_SHA256, smoke["executed_protocol_sha256"])

    def test_live_smoke_stayed_inside_its_authorization(self):
        smoke = self.record["live_smoke"]
        self.assertIs(True, smoke["synthetic_only"])
        self.assertEqual(2, smoke["provider_operations_authorized_maximum"])
        self.assertIn(smoke["provider_operations"], (1, 2))
        self.assertEqual(1, smoke["jobs"])
        self.assertEqual(1, smoke["execution_windows"])
        self.assertIs(False, smoke["repair_used"])
        self.assertEqual("gemini_slot_3", smoke["credential"]["slot"])
        self.assertIs(False, smoke["credential"]["secret_value_in_any_artifact"])
        self.assertEqual("ACCEPTED_GEMINI_DEV_WINDOW_TRANSPORT", smoke["transport"])
        self.assertEqual(0, self.record["offline"]["provider_operations_before_smoke"])
        self.assertEqual({"PASS"}, set(self.record["offline"]["single_source_gate"].values()))

    def test_status_follows_from_the_recorded_stages(self):
        record, smoke = self.record, self.record["live_smoke"]
        self.assertIn(record["status"], self.STATUSES)
        self.assertEqual(self.STATUSES[record["status"]], record["decision"]["next_action"])
        stages = (smoke["json_parse"], smoke["local_schema_validation"], smoke["compiler"])
        if record["status"] == "M4_04B4B_NATIVE_SCHEMA_PROVIDER_REJECTED":
            self.assertIs(False, smoke["provider_schema_request_accepted"])
            self.assertIs(False, smoke["provider_response_received"])
            self.assertEqual(("NOT_REACHED",) * 3, stages)
            self.assertEqual(400, smoke["provider_rejection"]["http_status"])
            self.assertIs(False, smoke["provider_rejection"]["retried"])
            self.assertIs(False, record["decision"]["runtime_ready_for_DEV3_tuning"])
            self.assertIs(False, record["interpretation"]["schema_weakened_or_projected_in_this_task"])
        else:
            self.assertIs(True, smoke["provider_schema_request_accepted"])
            self.assertIs(True, smoke["provider_response_received"])
            self.assertIs(True, record["decision"]["runtime_ready_for_DEV3_tuning"])

    def test_boundaries_and_public_safety(self):
        boundaries = self.record["boundaries"]
        for name in ("DEV3_input_opened", "DEV3_gold_opened", "holdout_opened", "P3_modified"):
            self.assertIs(False, boundaries[name], name)
        self.assertTrue(all(value is False for value in boundaries.values()))
        self.assertNotRegex(self.text, r"AIza[0-9A-Za-z_\-]{10,}")
        self.assertNotIn("GEMINI_API_KEY", self.text)
        self.assertNotIn(runner.SMOKE_TEXT, self.text)

    def test_project_state_names_the_same_next_action(self):
        state = (protocol.REPO_ROOT / "docs/PROJECT_STATE.md").read_text(encoding="utf-8")
        tail = state.rsplit("## Next Candidate\n", 1)[1]
        self.assertTrue(tail.strip().startswith(self.record["decision"]["next_action"]))
        self.assertIn(f"Status: {self.record['status']}", state)


if __name__ == "__main__":
    unittest.main()
