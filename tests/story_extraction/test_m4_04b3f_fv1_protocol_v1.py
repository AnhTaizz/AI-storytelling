"""Offline contract for the M4-04B3F lock (P3 Draft V1.1 extractor on Fresh Validation V1)."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import yaml

from tools.story_extraction import m4_04b3f_fv1_protocol_v1 as lock


class M404B3FProtocolTests(unittest.TestCase):
    def setUp(self):
        self.prepared_input = {
            "draft_version": lock.DRAFT_VERSION,
            "passages": [{"handle": "P1", "use": "EVIDENCE_ELIGIBLE", "text": "Synthetic public unit-test text."}],
            "existing_context": {},
        }

    def test_protocol_binds_the_locked_values_and_validates(self):
        protocol = lock.build_protocol()
        self.assertEqual(list(lock.CASE_IDS), protocol["case_execution_order"])
        self.assertEqual(("FV1_01", "FV1_10"), (lock.CASE_IDS[0], lock.CASE_IDS[-1]))
        self.assertEqual(lock.FV1_INPUT_SHA256, protocol["fv1_bindings"]["input_sha256"])
        generation = protocol["generation"]
        self.assertEqual(("gemini-3.5-flash-lite", 0, True, 1),
                         (generation["model"], generation["temperature"], generation["json_mode"],
                          generation["concurrency"]))
        self.assertEqual(20, protocol["stop_rules"]["maximum_semantic_jobs"])
        self.assertEqual(0, protocol["access_policy"]["provider_calls_during_protocol_lock"])
        self.assertTrue(all(v == "PASS" for v in lock.validate_protocol(protocol).values()))
        tampered = json.loads(json.dumps(protocol))
        tampered["generation"]["temperature"] = 1
        with self.assertRaisesRegex(lock.Fv1ProtocolError, "generation.temperature"):
            lock.validate_protocol(tampered)
        with self.assertRaises(lock.Fv1ProtocolError):
            lock.validate_protocol([])

    def test_public_lock_record_matches_the_canonical_protocol_and_prompts(self):
        public = yaml.safe_load((lock.REPO_ROOT / "benchmarks/m4_extraction/M4_04B3F_FV1_PROTOCOL_LOCK.yaml")
                                .read_text(encoding="utf-8"))
        self.assertEqual(lock.sha256_bytes(lock.canonical_json_bytes(lock.build_protocol())),
                         public["private_canonical_protocol"]["sha256"])
        hashes = {k: v for k, v in public["materialized_prompt_hashes"].items() if k != "materialization"}
        self.assertEqual(lock.prompt_hashes(), hashes)
        for key, source in public["prompt_sources"].items():
            if key != "differences_from_p2":
                self.assertEqual(lock.file_sha256(lock.REPO_ROOT / source["path"]), source["sha256"])
        self.assertEqual(list(lock.CASE_IDS), public["fv1_bindings"]["case_order"])
        self.assertEqual(lock.CREDENTIAL_SLOT, public["extractor"]["credential_slot"])

    def test_prompts_teach_the_v1_1_mention_contract_and_keep_p2_discipline(self):
        material = lock.prompt_material()
        system = material["primary_system"]
        for required in ("STORY_EXTRACTION_DRAFT_V1_1", "Never give a mention an evidence_handle",
                         "host binds each", "exact, byte-for-byte", "Preserve polarity exactly",
                         "REFERENCED STORY_EXTRACTION_DRAFT_V1 JSON SCHEMA", "EXACT PREDICATE REGISTRY"):
            self.assertIn(required, system)
        self.assertNotIn("DEV2", material["primary_user_template"] + material["repair_user_template"])
        self.assertIn("SANITIZED_STRUCTURAL_BLOCKERS_JSON", material["repair_user_template"])
        self.assertTrue(material["repair_system"].endswith("This is the only repair allowed for the case."))

    def test_requests_are_exact_and_only_structural_repairs_are_constructible(self):
        first = lock.build_primary_spec("FV1_01", self.prepared_input)
        self.assertEqual("M4B3F_P3_FV1_01_PRIMARY", first.job_id)
        self.assertEqual((lock.MODEL, lock.CREDENTIAL_SLOT), (first.model, first.credential_slot))
        self.assertEqual(first.request_fingerprint,
                         lock.build_primary_spec("FV1_01", self.prepared_input).request_fingerprint)
        self.assertIn("Synthetic public unit-test text.", first.user_prompt)
        blockers = [{"phase": "SCHEMA", "code": "DRAFT_SCHEMA_FAILURE", "path": "mentions/0"},
                    {"phase": "LOCATOR", "code": "AMBIGUOUS_QUOTE", "path": "evidence/1"}]
        repair = lock.build_repair_spec("FV1_01", self.prepared_input, "{broken",
                                        {"category": "DRAFT_SCHEMA_FAILURE", "blockers": blockers})
        self.assertEqual("M4B3F_P3_FV1_01_REPAIR_1", repair.job_id)
        self.assertLess(repair.user_prompt.index("LOCATOR"), repair.user_prompt.index('"SCHEMA"'))  # sorted
        bad = {
            "unknown case": ("DEV2_01", self.prepared_input, "{}", {"category": "DRAFT_SCHEMA_FAILURE", "blockers": blockers}),
            "quality category": ("FV1_01", self.prepared_input, "{}", {"category": "LOW_QUALITY", "blockers": blockers}),
            "gold signal": ("FV1_01", self.prepared_input, "{}", {"category": "DRAFT_SCHEMA_FAILURE",
                                                                   "blockers": blockers, "gold": 1}),
            "blocker with text": ("FV1_01", self.prepared_input, "{}", {"category": "DRAFT_SCHEMA_FAILURE", "blockers": [
                {"phase": "LOCATOR", "code": "X", "path": "p", "quote": "source text"}]}),
            "no blockers": ("FV1_01", self.prepared_input, "{}", {"category": "DRAFT_SCHEMA_FAILURE", "blockers": []}),
            "no primary response": ("FV1_01", self.prepared_input, "", {"category": "DRAFT_SCHEMA_FAILURE",
                                                                         "blockers": blockers}),
            "V1 input": ("FV1_01", {**self.prepared_input, "draft_version": "STORY_EXTRACTION_DRAFT_V1"}, "{}",
                         {"category": "DRAFT_SCHEMA_FAILURE", "blockers": blockers}),
            "mention evidence in context": ("FV1_01", {**self.prepared_input, "existing_context": {
                "M_EXISTING_1": {"evidence_handle": "EV_EXISTING_1"}}}, "{}",
                {"category": "DRAFT_SCHEMA_FAILURE", "blockers": blockers}),
        }
        for label, args in bad.items():
            with self.subTest(label), self.assertRaises(lock.Fv1ProtocolError):
                lock.build_repair_spec(*args)
        with self.assertRaises(lock.Fv1ProtocolError):
            lock._render("no markers", {"CASE_ID": "x"})
        with self.assertRaises(lock.Fv1ProtocolError):
            lock._render("{CASE_ID} {FAILURE_JSON}", {"CASE_ID": "x"})

    def test_bindings_packages_and_the_written_protocol_are_checked(self):
        self.assertTrue(all(v == "PASS" for v in lock.validate_public_bindings().values()))
        with mock.patch.object(lock, "COMPILER_SHA256", "0" * 64), self.assertRaisesRegex(lock.Fv1ProtocolError, "compiler"):
            lock.validate_public_bindings()
        with mock.patch.object(lock, "SNAPSHOT_V2_SHA256", "0" * 64), self.assertRaisesRegex(lock.Fv1ProtocolError, "Snapshot"):
            lock.validate_public_bindings()
        with mock.patch.object(lock, "FV1_GOLD_SHA256", "0" * 64), self.assertRaisesRegex(lock.Fv1ProtocolError, "seal"):
            lock.validate_public_bindings()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(lock.Fv1ProtocolError, "missing"):
                lock.verify_fv1_packages(root)
            (root / lock.FV1_INPUT_NAME).write_bytes(b"not the package")
            (root / lock.FV1_MANIFEST_NAME).write_bytes(b"{}")
            with self.assertRaisesRegex(lock.Fv1ProtocolError, "hash mismatch"):
                lock.verify_fv1_packages(root)
            with mock.patch.object(lock, "FV1_INPUT_SHA256", lock.sha256_bytes(b"not the package")), \
                    mock.patch.object(lock, "FV1_MANIFEST_SHA256", lock.sha256_bytes(b"{}")):
                self.assertEqual(set(lock.verify_fv1_packages(root).values()), {"PASS"})

            out = io.StringIO()
            args = ["--protocol", str(root / "p.json"), "--validation", str(root / "v.json"),
                    "--prompt-directory", str(root / "prompts")]
            with contextlib.redirect_stdout(out):
                self.assertEqual(lock.main(args), 0)
            sha = json.loads(out.getvalue())["protocol_sha256"]
            validated = lock.validate_protocol_file(root / "p.json", sha)
            validated.assert_unchanged()
            validation = json.loads((root / "v.json").read_text(encoding="utf-8"))
            self.assertEqual((validation["provider_calls"], validation["fv1_packages"]), (0, "NOT_CHECKED"))
            self.assertEqual(sorted(p.name for p in (root / "prompts").iterdir()),
                             ["primary_system.txt", "primary_user_template.txt", "repair_system.txt",
                              "repair_user_template.txt"])
            with self.assertRaisesRegex(lock.Fv1ProtocolError, "hash mismatch"):
                lock.validate_protocol_file(root / "p.json", "0" * 64)
            (root / "p.json").write_bytes(b"{}")
            with self.assertRaisesRegex(lock.Fv1ProtocolError, "mutated"):
                validated.assert_unchanged()
            (root / "p.json").unlink()
            with self.assertRaisesRegex(lock.Fv1ProtocolError, "unavailable"):
                validated.assert_unchanged()
            with self.assertRaisesRegex(lock.Fv1ProtocolError, "missing or invalid"):
                lock.validate_protocol_file(root / "p.json", sha)


if __name__ == "__main__":
    unittest.main()
