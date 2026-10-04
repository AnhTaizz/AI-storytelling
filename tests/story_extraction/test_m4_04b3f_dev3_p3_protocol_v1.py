import json
from pathlib import Path
import tempfile
import unittest

import yaml

from tools.story_extraction.m4_04b3f_dev3_p3_protocol_v1 import (
    CASE_IDS,
    COMPILER_SHA256,
    DEV3_GOLD_SHA256,
    DEV3_INPUT_SHA256,
    DRAFT_SCHEMA_SHA256,
    DRAFT_VERSION,
    REPO_ROOT,
    Dev3ProtocolError,
    build_primary_spec,
    build_protocol,
    build_repair_spec,
    canonical_json_bytes,
    prompt_hashes,
    prompt_material,
    sanitize_all_blockers,
    sha256_bytes,
    validate_protocol,
    validate_protocol_file,
    validate_public_bindings,
    write_protocol,
)


class M404B3FDev3P3ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.prepared_input = {
            "draft_version": DRAFT_VERSION,
            "passages": [
                {"handle": "P1", "use": "EVIDENCE_ELIGIBLE", "text": "Public unit test."}
            ],
            "existing_context": {},
        }

    def test_public_bindings_are_exact_without_dev3_package_access(self):
        checks = validate_public_bindings()
        self.assertTrue(all(value == "PASS" for value in checks.values()))
        self.assertEqual("PASS", checks["draft_schema"])
        self.assertEqual("PASS", checks["compiler"])
        self.assertEqual("PASS", checks["snapshot_v2"])

    def test_protocol_binds_dev3_hashes_and_order(self):
        protocol = build_protocol()
        self.assertEqual(DEV3_INPUT_SHA256, protocol["dev3_input_sha256"])
        self.assertEqual(DEV3_GOLD_SHA256, protocol["dev3_gold_sha256"])
        self.assertEqual([f"DEV3_{index:02d}" for index in range(1, 11)], list(CASE_IDS))
        self.assertEqual(list(CASE_IDS), protocol["case_execution_order"])
        self.assertEqual("FORBIDDEN", protocol["access_policy"]["dev3_input_during_protocol_lock"])
        self.assertEqual("FORBIDDEN_UNTIL_PREDICTION_LOCK_COMMITTED_AND_PUSHED", protocol["access_policy"]["dev3_gold"])

    def test_generation_runtime_and_pacing_are_exact(self):
        protocol = build_protocol()
        generation = protocol["generation"]
        durable = protocol["durable_execution"]
        self.assertEqual("gemini-3.5-flash-lite", generation["model"])
        self.assertEqual("gemini_slot_3", generation["credential_slot"])
        self.assertEqual(0, generation["temperature"])
        self.assertTrue(generation["json_mode"])
        self.assertEqual(1, generation["concurrency"])
        self.assertEqual(6, durable["global_pacing_max_operations"])
        self.assertEqual(60, durable["global_pacing_rolling_window_seconds"])
        self.assertEqual("IMMUTABLE_LOCK", durable["first_success"])

    def test_prompt_enforces_v1_1_interface_and_semantics(self):
        system = prompt_material()["primary_system"]
        for required in (
            "P1, P2",
            "E_EXISTING_1",
            "E_NEW_1",
            "EVT1",
            "PROP1",
            "A1",
            "exact byte-for-byte",
            "1-based",
            "EVIDENCE_ELIGIBLE",
            "MUST NOT contain evidence_handle",
            "Never invent or approximate a predicate",
            "Preserve polarity exactly",
            "holder-relative",
            "Do not output hashes",
            "STORY_EXTRACTION_DRAFT_V1_1",
        ):
            self.assertIn(required, system)
        self.assertIn("canonical IDs", " ".join(system.split()))
        self.assertIn("registry_version: predicate_registry/v0.1", system)
        self.assertIn('"$schema"', system)

    def test_primary_spec_outputs_only_v1_1(self):
        first = build_primary_spec("DEV3_01", self.prepared_input)
        second = build_primary_spec("DEV3_01", self.prepared_input)
        self.assertEqual("M4B3F_P3_DEV3_01_PRIMARY", first.job_id)
        self.assertEqual("PROVIDER_JSON_MIME_STORY_EXTRACTION_DRAFT_V1_1", first.schema_response_mode)
        self.assertEqual({"temperature": 0, "max_output_tokens": 16384}, first.generation_config)
        self.assertEqual(first.request_fingerprint, second.request_fingerprint)
        self.assertIn("Return exactly one STORY_EXTRACTION_DRAFT_V1_1", first.user_prompt)

    def test_all_blocker_diagnostic_is_complete_sanitized_and_stable(self):
        raw = [
            {"phase": "COMPILER", "code": "BAD_HANDLE", "path": "$.assertions[0]", "quote": "private"},
            {"phase": "SCHEMA", "code": "DRAFT_SCHEMA_FAILURE", "path": "$.mentions[0]", "message": "private"},
            {"phase": "COMPILER", "code": "BAD_HANDLE", "path": "$.assertions[0]"},
        ]
        sanitized = sanitize_all_blockers(raw)
        self.assertEqual(2, len(sanitized))
        self.assertEqual({"phase", "code", "path"}, set(sanitized[0]))
        self.assertNotIn("private", json.dumps(sanitized))
        self.assertEqual(sorted(sanitized, key=lambda item: (item["phase"], item["code"], item["path"])), sanitized)

    def test_repair_is_one_structural_attempt_and_failure_is_terminal(self):
        blockers = [
            {"phase": "COMPILER", "code": "BAD_HANDLE", "path": "$.assertions[0]"},
            {"phase": "COMPILER", "code": "AMBIGUOUS_QUOTE", "path": "$.mentions[0]"},
        ]
        spec = build_repair_spec(
            "DEV3_01", self.prepared_input, "{}", "DRAFT_COMPILER_FAILURE", blockers
        )
        self.assertEqual("M4B3F_P3_DEV3_01_REPAIR_1", spec.job_id)
        self.assertIn("SANITIZED_ALL_BLOCKERS_JSON", spec.user_prompt)
        self.assertIn("BAD_HANDLE", spec.user_prompt)
        self.assertIn("AMBIGUOUS_QUOTE", spec.user_prompt)
        policy = build_protocol()["repair_policy"]
        self.assertEqual(1, policy["maximum_per_case"])
        self.assertTrue(policy["repair_failure_is_terminal"])
        with self.assertRaises(Dev3ProtocolError):
            build_repair_spec("DEV3_01", self.prepared_input, "{}", "LOW_QUALITY", blockers)

    def test_protocol_validation_fails_closed_on_mutation(self):
        protocol = build_protocol()
        protocol["generation"]["model"] = "different-model"
        with self.assertRaisesRegex(Dev3ProtocolError, "protocol.generation.model"):
            validate_protocol(protocol)

    def test_canonical_private_protocol_is_deterministic_and_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "protocol.json"
            _, digest = write_protocol(path)
            self.assertEqual(digest, sha256_bytes(canonical_json_bytes(build_protocol())))
            lock = validate_protocol_file(path, digest)
            lock.assert_unchanged()
            path.write_text("{}", encoding="utf-8")
            with self.assertRaises(Dev3ProtocolError):
                lock.assert_unchanged()

    def test_public_lock_matches_canonical_protocol(self):
        public = yaml.safe_load(
            (REPO_ROOT / "benchmarks/m4_extraction/M4_04B3F_DEV3_P3_PROTOCOL_LOCK.yaml").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(sha256_bytes(canonical_json_bytes(build_protocol())), public["private_canonical_protocol"]["sha256"])
        self.assertEqual(prompt_hashes(), public["materialized_prompt_hashes"])
        self.assertEqual(DRAFT_SCHEMA_SHA256, public["compiler_binding"]["draft_schema_sha256"])
        self.assertEqual(COMPILER_SHA256, public["compiler_binding"]["compiler_sha256"])
        self.assertFalse(public["boundaries"]["DEV3_input_opened"])
        self.assertFalse(public["boundaries"]["DEV3_gold_opened"])
        self.assertFalse(public["boundaries"]["holdout_accessed"])


if __name__ == "__main__":
    unittest.main()
