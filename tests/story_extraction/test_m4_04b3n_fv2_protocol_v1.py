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
    def test_owner_binding_and_legacy_p4r4_protocol_bytes_unchanged(self):
        self.assertEqual((lock.PROMPT_VARIANT, lock.HOST_REPAIRS), ("P4R6", ("QR", "AM")))
        # Captured before Task H. Stable per-path hash inputs avoid self-binding
        # source edits (and checkout newline differences) changing this baseline.
        with mock.patch.object(lock, "file_sha256", side_effect=lambda p:
                lock.sha256_bytes(p.relative_to(lock.REPO_ROOT).as_posix().encode())),                 mock.patch.object(lock, "PROMPT_VARIANT", "P4R4"), mock.patch.object(lock, "HOST_REPAIRS", ()):
            value = lock.build_protocol()
            paths = lock.bound_paths()
        self.assertNotIn("host_repairs", value)
        self.assertEqual(lock.sha256_bytes(lock.canonical_json_bytes(value)),
                         "5c854d8609b9ce0f46db615b9039f66af9e66b0717024b8788fea8f2d2b33e25")
        self.assertEqual(list(paths), list(value["public_bindings"]))
        self.assertEqual(value["public_bindings"], {p: lock.sha256_bytes(p.encode()) for p in paths})

    def test_host_repair_bindings_variant_selection_and_legacy_empty_lock(self):
        with mock.patch.object(lock, "PROMPT_VARIANT", "P4R4"), mock.patch.object(lock, "HOST_REPAIRS", ()):
            original_paths = set(lock.bound_paths())
        modules = {"QR": "tools/story_extraction/draft_quote_resolution_v1.py",
                   "AM": "tools/story_extraction/draft_mention_anchoring_v1.py"}
        case, _ = synthetic_case("FV2_01")
        for variant in ("P4R4", "P3"):
            for repairs in ((), ("QR",), ("AM",), ("QR", "AM")):
                with self.subTest(variant=variant, repairs=repairs), \
                        mock.patch.object(lock, "PROMPT_VARIANT", variant), \
                        mock.patch.object(lock, "HOST_REPAIRS", repairs):
                    value = lock.build_protocol()
                    used = set(repairs) | ({"QR"} if "AM" in repairs else set())
                    self.assertEqual(value.get("host_repairs", []), list(repairs))
                    self.assertEqual(set(lock.bound_paths()) & set(modules.values()), {modules[r] for r in used})
                    if variant == "P4R4":
                        self.assertEqual(set(lock.bound_paths()), original_paths | {modules[r] for r in used})
                    for repair in used:
                        path = modules[repair]
                        self.assertEqual(value["public_bindings"][path], lock.file_sha256(lock.REPO_ROOT / path))
                    lock.validate_protocol(value)
                    self.assertEqual(lock.build_primary_spec(case.case_id, case.prepared_input).system_prompt,
                                     lock.dev.prompt_material(variant)["primary_system"])
                    if not repairs:
                        self.assertNotIn("host_repairs", value)
                        lock.validate_protocol({**value, "host_repairs": []})
                    else:
                        missing = deepcopy(value)
                        missing.pop("host_repairs")
                        with self.assertRaisesRegex(lock.Fv2ProtocolError, "semantic"):
                            lock.validate_protocol(missing)
                        for repair in used:
                            real_hash = lock.file_sha256
                            with mock.patch.object(lock, "file_sha256", side_effect=lambda p:
                                    "0" * 64 if p == lock.REPO_ROOT / modules[repair] else real_hash(p)):
                                with self.assertRaisesRegex(lock.Fv2ProtocolError, "binding mismatch"):
                                    lock.validate_protocol(value)
        for repairs in (("UNKNOWN",), ("AM", "QR"), ("QR", "QR")):
            with self.subTest(constant=repairs), mock.patch.object(lock, "HOST_REPAIRS", repairs):
                with self.assertRaisesRegex(lock.Fv2ProtocolError, "host_repairs"):
                    lock.build_protocol()
        value = lock.build_protocol()
        for repairs in (["UNKNOWN"], ["AM", "QR"], ["QR", "QR"], "QR", None, {}, ("QR",), [1]):
            with self.subTest(protocol=repairs), self.assertRaisesRegex(lock.Fv2ProtocolError, "host_repairs"):
                lock.validate_protocol({**value, "host_repairs": repairs})

    def test_determinism_exact_settings_requests_and_binding_drift(self):
        value = lock.build_protocol()
        self.assertEqual(value, lock.build_protocol())
        self.assertEqual(lock.CASE_IDS, tuple(f"FV2_{i:02d}" for i in range(1, 13)))
        self.assertEqual(value["generation"]["temperature"], 0)
        self.assertEqual(value["generation"]["credential_slot"], "gemini_slot_33")
        self.assertEqual(value["repair_policy"]["maximum_per_case"], 1)
        self.assertEqual(value["durable_execution"]["global_pacing_max_operations"], 6)
        self.assertIn("P4R6", value["extractor_id"])
        self.assertEqual(value["host_repairs"], ["QR", "AM"])
        self.assertTrue(any("p4r6_system" in name for name in value["public_bindings"]))
        lock.validate_protocol(value)
        real_hash = lock.file_sha256
        for changed in value["public_bindings"]:
            with self.subTest(changed), mock.patch.object(lock, "file_sha256", side_effect=lambda path:
                    "0" * 64 if path == lock.REPO_ROOT / changed else real_hash(path)):
                with self.assertRaisesRegex(lock.Fv2ProtocolError, "binding mismatch"):
                    lock.validate_protocol(value)
        case, _ = synthetic_case("FV2_01")
        spec = lock.build_primary_spec(case.case_id, case.prepared_input)
        self.assertEqual(spec.system_prompt, lock.dev.prompt_material("P4R6")["primary_system"])
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
