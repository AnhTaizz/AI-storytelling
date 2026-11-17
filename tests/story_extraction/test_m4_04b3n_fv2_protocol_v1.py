"""Offline public-byte lock and request tests. No private package or credentials."""
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import yaml

from tools.story_extraction import m4_04b3n_fv2_protocol_v1 as lock
from tests.story_extraction.test_run_m4_04b3g_fv1_predictions_v1 import synthetic_case


class ProtocolTests(unittest.TestCase):
    def test_determinism_exact_settings_requests_and_binding_drift(self):
        value = lock.build_protocol()
        self.assertEqual(value, lock.build_protocol())
        self.assertEqual(lock.CASE_IDS, tuple(f"FV2_{i:02d}" for i in range(1, 13)))
        self.assertEqual(value["generation"]["temperature"], 0)
        self.assertEqual(value["generation"]["credential_slot"], "gemini_slot_33")
        self.assertEqual(value["repair_policy"]["maximum_per_case"], 1)
        self.assertEqual(value["durable_execution"]["global_pacing_max_operations"], 6)
        self.assertIn("P4R4", value["extractor_id"])
        self.assertTrue(any("p4r4_system" in name for name in value["public_bindings"]))
        lock.validate_protocol(value)
        real_hash = lock.file_sha256
        for changed in value["public_bindings"]:
            with self.subTest(changed), mock.patch.object(lock, "file_sha256", side_effect=lambda path:
                    "0" * 64 if path == lock.REPO_ROOT / changed else real_hash(path)):
                with self.assertRaisesRegex(lock.Fv2ProtocolError, "binding mismatch"):
                    lock.validate_protocol(value)
        case, _ = synthetic_case("FV2_01")
        spec = lock.build_primary_spec(case.case_id, case.prepared_input)
        self.assertEqual(spec.system_prompt, lock.dev.prompt_material("P4R4")["primary_system"])
        self.assertEqual(spec.credential_slot, "gemini_slot_33")
        failure = {"category": "JSON_PARSE_FAILURE", "blockers": [{"code": "INVALID_JSON", "phase": "JSON", "path": ""}]}
        repair = lock.build_repair_spec(case.case_id, case.prepared_input, "{", failure)
        self.assertTrue(repair.job_id.endswith("REPAIR_1"))
        self.assertIn("INVALID_JSON", repair.user_prompt)

    def test_protocol_file_pinning_canonical_bytes_and_refusals(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "protocol.json"
            value, digest = lock.write_protocol(path)
            validated = lock.validate_protocol_file(path, digest)
            validated.assert_unchanged()
            with self.assertRaises(FileExistsError):
                lock.write_protocol(path)
            for payload, expected in ((b"{", "Invalid protocol"), (b"[]", "root"),
                                      (json.dumps(value).encode(), "canonical")):
                with self.subTest(expected):
                    path.write_bytes(payload)
                    with self.assertRaisesRegex(lock.Fv2ProtocolError, expected):
                        lock.validate_protocol_file(path, lock.sha256_bytes(payload))
            with self.assertRaisesRegex(lock.Fv2ProtocolError, "hash mismatch"):
                lock.validate_protocol_file(path, digest)
            with self.assertRaises(lock.Fv2ProtocolError):
                validated.assert_unchanged()
        for change, expected in ((lambda p: p.pop("public_bindings"), "inventory"),
                                 (lambda p: p["generation"].update(temperature=1), "semantic")):
            value = lock.build_protocol()
            change(value)
            with self.subTest(expected), self.assertRaisesRegex(lock.Fv2ProtocolError, expected):
                lock.validate_protocol(value)

    def test_seal_snapshot_and_request_policy_refusals(self):
        value = lock.build_protocol()
        snapshot = yaml.safe_load(lock.fv1.SNAPSHOT_V2_PATH.read_text(encoding="utf-8"))
        seal_path = lock.REPO_ROOT / "benchmarks/m4_extraction/M4_04B3M_FRESH_VALIDATION_V2_SEAL_RESULT.yaml"
        seal = yaml.safe_load(seal_path.read_text(encoding="utf-8"))
        variants = [({**snapshot, "snapshot_id": "wrong"}, "Snapshot"),
                    ({"private_packages": {**seal["private_packages"], "input": {"name": "wrong"}}}, "seal"),
                    (deepcopy(seal), "contains gold")]
        variants[-1][0]["private_packages"]["input"]["contains_gold"] = True
        for document, expected in variants:
            with self.subTest(expected), mock.patch.object(lock.yaml, "safe_load", side_effect=
                    [document] if expected == "Snapshot" else [snapshot, document]):
                with self.assertRaisesRegex(lock.Fv2ProtocolError, expected):
                    lock.validate_public_bindings(value)
        case, _ = synthetic_case("FV2_01")
        invalid_inputs = [("UNKNOWN", case.prepared_input), (case.case_id, {}),
                          (case.case_id, {**case.prepared_input, "existing_context": {"M1": {"evidence_handle": "E1"}}})]
        for cid, prepared in invalid_inputs:
            with self.subTest(cid=cid, prepared=prepared), self.assertRaises(lock.Fv2ProtocolError):
                lock.build_primary_spec(cid, prepared)
        for failure, raw in (({}, "{"), ({"category": "JSON_PARSE_FAILURE", "blockers": []}, "{"),
                             ({"category": "QUALITY", "blockers": []}, "{"),
                             ({"category": "JSON_PARSE_FAILURE", "blockers": []}, "")):
            with self.subTest(failure=failure), self.assertRaises(lock.Fv2ProtocolError):
                lock.build_repair_spec(case.case_id, case.prepared_input, raw, failure)

    def test_lock_cli_writes_validates_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.assertEqual(lock.main(["--directory", tmp]), 0)
            digest = json.loads(stdout.getvalue())["protocol_sha256"]
            lock.validate_protocol_file(Path(tmp) / lock.PROTOCOL_NAME, digest)
            self.assertEqual(json.loads((Path(tmp) / lock.VALIDATION_NAME).read_bytes())["protocol_sha256"], digest)
            self.assertEqual(lock.main(["--directory", tmp]), 2)


if __name__ == "__main__":
    unittest.main()
