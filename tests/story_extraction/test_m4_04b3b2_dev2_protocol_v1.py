import json
from pathlib import Path
import tempfile
import unittest

import yaml

from tools.story_extraction.m4_04b3b2_dev2_protocol_v1 import (
    CASE_IDS,
    COMPILER_SHA256,
    DEV2_GOLD_SHA256,
    DEV2_INPUT_SHA256,
    DRAFT_SCHEMA_SHA256,
    DRAFT_VERSION,
    REPO_ROOT,
    Dev2ProtocolError,
    build_primary_spec,
    build_protocol,
    build_repair_spec,
    canonical_json_bytes,
    prompt_hashes,
    prompt_material,
    sha256_bytes,
    validate_protocol,
    validate_protocol_file,
    validate_public_bindings,
    write_protocol,
)


class M404B3B2Dev2ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.prepared_input = {
            "draft_version": DRAFT_VERSION,
            "passages": [
                {
                    "handle": "P1",
                    "use": "EVIDENCE_ELIGIBLE",
                    "text": "Synthetic public unit-test text.",
                }
            ],
            "existing_context": {},
        }

    def test_public_bindings_are_exact(self):
        checks = validate_public_bindings()
        self.assertEqual("PASS", checks["draft_schema"])
        self.assertEqual("PASS", checks["compiler"])
        self.assertEqual("PASS", checks["snapshot_v2"])

    def test_protocol_binds_all_required_fixed_values(self):
        protocol = build_protocol()
        self.assertEqual(list(CASE_IDS), protocol["case_ids"])
        self.assertEqual(list(CASE_IDS), protocol["case_execution_order"])
        self.assertEqual(DEV2_INPUT_SHA256, protocol["dev2_input_sha256"])
        self.assertEqual(DEV2_GOLD_SHA256, protocol["dev2_gold_sha256"])
        self.assertEqual(DRAFT_SCHEMA_SHA256, protocol["compiler_binding"]["draft_schema_sha256"])
        self.assertEqual(COMPILER_SHA256, protocol["compiler_binding"]["compiler_sha256"])
        self.assertEqual("gemini-3.5-flash-lite", protocol["generation"]["model"])
        self.assertEqual("gemini_slot_3", protocol["generation"]["credential_slot"])
        self.assertEqual(0, protocol["generation"]["temperature"])
        self.assertTrue(protocol["generation"]["json_mode"])
        self.assertEqual("application/json", protocol["generation"]["response_mime_type"])
        self.assertEqual(1, protocol["generation"]["concurrency"])
        self.assertEqual(6, protocol["durable_execution"]["global_pacing_max_operations"])
        self.assertEqual(60, protocol["durable_execution"]["global_pacing_rolling_window_seconds"])
        self.assertEqual(1, protocol["repair_policy"]["maximum_per_case"])
        self.assertTrue(protocol["prediction_lock"]["lock_before_gold"])
        self.assertEqual("FORBIDDEN", protocol["access_policy"]["holdout_input"])
        self.assertEqual(0, protocol["access_policy"]["provider_calls_during_protocol_lock"])
        self.assertEqual(prompt_hashes(), protocol["prompt_hashes"])
        self.assertTrue(all(value == "PASS" for value in validate_protocol(protocol).values()))

    def test_public_lock_matches_canonical_protocol(self):
        path = REPO_ROOT / "benchmarks/m4_extraction/M4_04B3B2_DEV2_BENCHMARK_PROTOCOL_LOCK.yaml"
        public = yaml.safe_load(path.read_text(encoding="utf-8"))
        expected_sha = sha256_bytes(canonical_json_bytes(build_protocol()))
        self.assertEqual(expected_sha, public["private_canonical_protocol"]["sha256"])
        self.assertEqual(list(CASE_IDS), public["dev2_bindings"]["case_order"])
        self.assertEqual(DEV2_INPUT_SHA256, public["dev2_bindings"]["input_package"]["sha256"])
        self.assertEqual(DEV2_GOLD_SHA256, public["dev2_bindings"]["gold_package"]["sha256"])
        public_prompt_hashes = {
            key: value
            for key, value in public["materialized_prompt_hashes"].items()
            if key != "materialization"
        }
        self.assertEqual(prompt_hashes(), public_prompt_hashes)

    def test_sealed_dev2_checks_are_hash_bound_without_opening_packages(self):
        seal_path = (
            REPO_ROOT
            / "benchmarks/m4_extraction/M4_04B3B1_FRESH_DEV2_SEAL_RESULT.yaml"
        )
        seal = yaml.safe_load(seal_path.read_text(encoding="utf-8"))
        self.assertEqual(
            DEV2_INPUT_SHA256, seal["private_packages"]["input"]["sha256"]
        )
        self.assertEqual(
            DEV2_GOLD_SHA256, seal["private_packages"]["gold"]["sha256"]
        )
        self.assertFalse(seal["private_packages"]["input"]["contains_gold"])
        self.assertTrue(seal["private_packages"]["input_and_gold_member_names_disjoint"])
        self.assertEqual("PASS", seal["verification"]["package_separation"])
        self.assertEqual("PASS", seal["verification"]["source_exact_checks"])

    def test_prompt_teaches_required_draft_contract(self):
        system = prompt_material()["primary_system"]
        normalized = " ".join(system.split())
        for required in (
            "P1, P2",
            "E_EXISTING_1",
            "E_NEW_1",
            "EVT1",
            "PROP1",
            "A1",
            "exact, byte-for-byte",
            "1-based",
            "occurrence",
            "EVIDENCE_ELIGIBLE",
            "Never invent or approximate a predicate",
            "Preserve polarity exactly",
            "holder-relative",
            "Do not output hashes",
            "STORY_EXTRACTION_DRAFT_V1",
        ):
            self.assertIn(required, system)
        self.assertIn("canonical ids", normalized.lower())
        self.assertIn("registry_version: predicate_registry/v0.1", system)
        self.assertIn('"$schema"', system)

    def test_primary_spec_is_exact_and_fingerprint_is_stable(self):
        first = build_primary_spec("DEV2_01", self.prepared_input)
        second = build_primary_spec("DEV2_01", self.prepared_input)
        self.assertEqual("M4B3B2_P2_DEV2_01_PRIMARY", first.job_id)
        self.assertEqual("gemini-3.5-flash-lite", first.model)
        self.assertEqual("gemini_slot_3", first.credential_slot)
        self.assertEqual({"temperature": 0, "max_output_tokens": 16384}, first.generation_config)
        self.assertEqual("PROVIDER_JSON_MIME_STORY_EXTRACTION_DRAFT_V1", first.schema_response_mode)
        self.assertEqual(first.request_fingerprint, second.request_fingerprint)
        self.assertIn("Synthetic public unit-test text.", first.user_prompt)

    def test_only_preregistered_structural_repair_is_constructible(self):
        failure = {"category": "DRAFT_SCHEMA_FAILURE", "path": "$.assertions[0]"}
        spec = build_repair_spec("DEV2_01", self.prepared_input, "{broken-json", failure)
        self.assertEqual("M4B3B2_P2_DEV2_01_REPAIR_1", spec.job_id)
        self.assertIn("sole preregistered repair", spec.user_prompt)
        with self.assertRaises(Dev2ProtocolError):
            build_repair_spec(
                "DEV2_01", self.prepared_input, "{}", {"category": "LOW_QUALITY"}
            )
        with self.assertRaises(Dev2ProtocolError):
            build_repair_spec(
                "DEV2_01",
                self.prepared_input,
                "{}",
                {"category": "DRAFT_COMPILER_FAILURE", "score": 0.2},
            )

    def test_protocol_validation_fails_closed_on_mutation(self):
        protocol = build_protocol()
        protocol["generation"]["model"] = "different-model"
        with self.assertRaisesRegex(Dev2ProtocolError, "protocol.generation.model"):
            validate_protocol(protocol)

    def test_canonical_private_protocol_hash_and_bytes_are_locked(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "protocol.json"
            _, digest = write_protocol(path)
            lock = validate_protocol_file(path, digest)
            self.assertEqual(digest, lock.sha256)
            lock.assert_unchanged()
            value = json.loads(path.read_text(encoding="utf-8"))
            value["case_ids"].reverse()
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(Dev2ProtocolError):
                lock.assert_unchanged()

    def test_unknown_case_and_non_draft_input_are_rejected(self):
        with self.assertRaises(Dev2ProtocolError):
            build_primary_spec("DEV2_99", self.prepared_input)
        wrong = dict(self.prepared_input)
        wrong["draft_version"] = "OTHER"
        with self.assertRaises(Dev2ProtocolError):
            build_primary_spec("DEV2_01", wrong)


if __name__ == "__main__":
    unittest.main()
