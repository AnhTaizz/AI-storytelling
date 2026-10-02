"""Protocol, blindness, prompt, and structural-repair tests for M4-04B2."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.story_extraction.m4_04b2_dev_protocol_v1 import (  # noqa: E402
    CASE_IDS,
    DEV_PACKAGE_SHA256,
    FORBIDDEN_CASE_FIELDS,
    INPUT_MEMBERS,
    MODEL,
    DevBenchmarkProtocolError,
    build_protocol,
    extract_input_members_only,
    prompt_hashes,
    prompt_material,
    safe_case_projection,
    validate_protocol,
    validate_protocol_file,
    write_protocol,
)
from tools.story_extraction.run_m4_04b2_dev_predictions_v1 import (  # noqa: E402
    _validation,
    build_input_payload,
    execute,
)
from tests.story_extraction import fixture_builder  # noqa: E402


class FakeIngestion:
    fingerprint = "f" * 64

    def resolve_passage_text(self, ref):
        return "Invented source text."


class TestM4B2Protocol(unittest.TestCase):
    def test_exact_case_and_candidate_order(self):
        value = build_protocol()
        self.assertEqual(value["candidate_execution_order"], ["P0", "P1"])
        self.assertEqual(value["case_ids"], list(CASE_IDS))
        self.assertEqual(value["maximum_semantic_jobs"], 56)
        self.assertEqual(value["maximum_provider_attempts"], 504)

    def test_protocol_rejects_missing_unknown_and_semantic_change(self):
        for mutation in ("missing", "unknown", "model"):
            value = build_protocol()
            if mutation == "missing":
                del value["model"]
            elif mutation == "unknown":
                value["quality_retry"] = True
            else:
                value["model"] = "another-model"
            with self.assertRaises(DevBenchmarkProtocolError):
                validate_protocol(value)

    def test_protocol_file_mutation_fails_byte_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "protocol.json"
            locked = write_protocol(path)
            path.write_bytes(locked.locked_bytes + b" ")
            with self.assertRaises(DevBenchmarkProtocolError):
                locked.assert_unchanged()

    def test_prompt_hashes_are_deterministic_and_distinct(self):
        first = prompt_hashes()
        second = prompt_hashes()
        self.assertEqual(first, second)
        self.assertNotEqual(first["p0_prompt_sha256"], first["p1_prompt_sha256"])
        self.assertEqual(len(first["p1_fewshot_sha256"]), 64)

    def test_fewshot_is_synthetic_fixture_only(self):
        material = prompt_material()
        self.assertIn("c05_event_occurred", material["p1_fewshot"])
        self.assertNotIn("M4DEV_", material["p1_fewshot"])
        self.assertNotIn("M4_03_HOLDOUT", material["p1_fewshot"])


class TestDevelopmentBlindness(unittest.TestCase):
    def case(self):
        return {
            "case_id": CASE_IDS[0],
            "case_objective": "Invented objective",
            "category": "SIMPLE_EVENT",
            "secondary_categories": [],
            "extraction_profile": "STORY_UNDERSTANDING_CORE_V0",
            "out_of_scope_fact_classes": [],
            "as_of_position": {"stream_id": "stream", "key": [1]},
            "base_canonical_identity": {
                "schema_version": "canonical_story/v0",
                "base_document_sha256": "b" * 64,
            },
            "evidence_eligible_passages": ["segment-1"],
            "context_only_passages": [],
            "source_basis": "SYNTHETIC",
            "gold_batch": "forbidden.json",
            "required_assertions": ["secret-answer"],
            "acceptable_assertions": [],
            "gold_completeness": "COMPLETE_FOR_PROFILE",
            "gold_status": ["DRAFT"],
            "annotation_notes": "forbidden",
            "conversion_stats": {},
            "open_question_tags": [],
        }

    def test_safe_projection_removes_every_bound_gold_field(self):
        projected = safe_case_projection(self.case())
        self.assertFalse(set(projected) & FORBIDDEN_CASE_FIELDS)
        serialized = json.dumps(projected)
        self.assertNotIn("secret-answer", serialized)
        self.assertNotIn("forbidden.json", serialized)

    def test_input_payload_contains_no_gold_fields(self):
        _, base, _ = fixture_builder.build("c05_event_occurred")
        base["story"]["id"] = "story-syn-m4"
        case = safe_case_projection(self.case())
        ref = {
            "kind": "SOURCE_PASSAGE_REF_V0",
            "story_id": "story-syn-m4",
            "document_id": "doc",
            "document_version": "d" * 64,
            "segment_id": base["source_segments"][0]["id"],
            "position": base["source_segments"][0]["position"],
            "relative_char_start": 0,
            "relative_char_end_exclusive": 5,
            "span": {
                "kind": "TEXT_RANGE_V0",
                "source_sha256": "d" * 64,
                "char_start": 0,
                "char_end_exclusive": 5,
                "byte_start": 0,
                "byte_end_exclusive": 5,
                "span_text_sha256": "e" * 64,
            },
        }
        payload = build_input_payload(
            candidate="P0",
            case_id=CASE_IDS[0],
            case=case,
            refs=[{"use": "EVIDENCE_ELIGIBLE", "passage_ref": ref}],
            base=base,
            ingestion=FakeIngestion(),
        )
        serialized = json.dumps(payload)
        self.assertNotIn("gold_batch", serialized)
        self.assertNotIn("required_assertions", serialized)
        self.assertIn("Invented source text", serialized)

    def test_controlled_extraction_copies_only_three_allowlisted_members(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "dev.zip"
            with zipfile.ZipFile(package, "w") as archive:
                for member in INPUT_MEMBERS:
                    archive.writestr(member, "{}\n")
                archive.writestr("M4_02_DEV_CALIBRATION/gold_batches/M4DEV_01.json", "secret")
            with patch(
                "tools.story_extraction.m4_04b2_dev_protocol_v1.file_sha256",
                return_value=DEV_PACKAGE_SHA256,
            ):
                result = extract_input_members_only(package, root / "input")
            self.assertEqual(set(result["extracted_members"]), {Path(x).name for x in INPUT_MEMBERS})
            self.assertFalse((root / "input" / "M4DEV_01.json").exists())
            self.assertFalse(result["dev_gold_opened"])


class TestStructuralRepairBoundary(unittest.TestCase):
    def test_valid_synthetic_batch_passes_without_repair_signal(self):
        _, base, batch = fixture_builder.build(
            "c05_event_occurred", prefix="prediction", method="AUTOMATED_EXTRACTION"
        )
        parsed, report = _validation(json.dumps(batch), base)
        self.assertIsNotNone(parsed)
        self.assertTrue(report["pass"])

    def test_invalid_json_is_machine_repair_eligible(self):
        _, base, _ = fixture_builder.build("c05_event_occurred")
        parsed, report = _validation("{", base)
        self.assertIsNone(parsed)
        self.assertEqual(report["category"], "JSON_PARSE_FAILURE")

    def test_schema_invalid_is_machine_repair_eligible(self):
        _, base, batch = fixture_builder.build("c05_event_occurred")
        broken = copy.deepcopy(batch)
        del broken["batch_version"]
        parsed, report = _validation(json.dumps(broken), base)
        self.assertIsNone(parsed)
        self.assertEqual(report["category"], "STORY_EXTRACTION_BATCH_SCHEMA_FAILURE")

    def test_invalid_protocol_aborts_before_provider_client(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            protocol = root / "protocol.json"
            protocol.write_text("{", encoding="utf-8")
            with patch(
                "tools.story_extraction.run_m4_04b2_dev_predictions_v1.official_client_factory"
            ) as client:
                with self.assertRaises(DevBenchmarkProtocolError):
                    execute(
                        protocol_path=protocol,
                        protocol_validation_path=root / "validation.json",
                        expected_protocol_sha256="0" * 64,
                        lock_commit="lock",
                        access_manifest_path=root / "access.json",
                        input_directory=root / "input",
                        input_extraction_result_path=root / "input-result.json",
                        ingestion_manifest=root / "ingestion.yaml",
                        source_root=root,
                        checkpoint_directory=root / "checkpoints",
                        artifact_directory=root / "artifacts",
                        result_path=root / "result.json",
                        prediction_manifest_path=root / "manifest.json",
                    )
            client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
