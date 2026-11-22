"""Synthetic FV3 packages and scripted durable jobs."""
from contextlib import ExitStack, contextmanager
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tests.story_extraction.test_run_m4_04b3o_fv2_predictions_v1 import authored, FakeTransport, seal
from tools.story_extraction import m4_04b3z_fv3_protocol_v1 as lock
from tools.story_extraction import run_m4_04b3z_fv3_predictions_v1 as runner


@contextmanager
def synthetic_bundle(root):
    ids = ("synthetic-01", "synthetic-02")
    cases = [authored(ids[0], "c06_participant"), authored(ids[1], "c02_two_mentions_one_entity")]
    packages = root / "packages"
    metadata = seal.seal(cases, packages, lock.FV3_SET_ID, "SYNTHETIC")["packages"]
    # Replace the public record with a matching synthetic record for this run.
    record = lock.yaml.safe_load((lock.REPO_ROOT / lock.SEAL_RECORD).read_bytes())
    record.update(case_ids=list(ids), private_packages={k + "_sha256": v["sha256"] for k, v in metadata.items()})
    with ExitStack() as stack:
        record_path = root / "synthetic-seal.yaml"
        record_path.write_text(lock.yaml.safe_dump(record), encoding="utf-8")
        stack.enter_context(mock.patch.object(lock, "SEAL_RECORD", str(record_path)))
        stack.enter_context(mock.patch.object(lock, "CASE_IDS", ids))
        for key, label in (("input", "INPUT"), ("gold", "GOLD"), ("blindness_manifest", "MANIFEST")):
            stack.enter_context(mock.patch.object(lock, f"FV3_{label}_SHA256", metadata[key]["sha256"]))
        path = root / "protocol.json"
        _, digest = lock.write_protocol(path)
        draft = json.dumps(seal.representational_gate(cases[0])["oracle_draft"])
        prefix = "M4B3Z_P4R8_"
        transport = FakeTransport({runner.SMOKE_JOB_ID: ['{"status":"ok"}'],
            prefix + ids[0] + "_PRIMARY": ["{"], prefix + ids[0] + "_REPAIR_1": [draft],
            prefix + ids[1] + "_PRIMARY": ["{"], prefix + ids[1] + "_REPAIR_1": ["{"]})
        yield dict(protocol_path=path, protocol_sha256=digest, fv3_directory=packages,
                   output_root=root / "predictions"), transport


class RunnerTests(unittest.TestCase):
    def test_blind_lifecycle_and_ordered_repair_options(self):
        with tempfile.TemporaryDirectory() as tmp, synthetic_bundle(Path(tmp)) as (opts, transport):
            args = ["--protocol", str(opts["protocol_path"]), "--protocol-sha256", opts["protocol_sha256"],
                    "--fv3-dir", str(opts["fv3_directory"])]
            original_open = Path.open
            def blind(path, *args, **kwargs):
                if path.name == lock.FV3_GOLD_NAME:
                    self.fail("Runner accessed the gold package")
                return original_open(path, *args, **kwargs)

            requests = []
            def send(spec, window, request_id):
                if not requests:
                    with self.assertRaisesRegex(runner.Fv3PredictionError, "exclusive"):
                        runner.execute(**opts, transport=self.fail)
                requests.append(spec)
                return transport(spec, window, request_id)

            with mock.patch.object(Path, "open", blind), mock.patch.object(
                    lock.dev, "validate_attempt", wraps=lock.dev.validate_attempt) as validate:
                self.assertEqual(runner.main(["--mode", "preflight", *args]), 0)
                self.assertEqual(runner.main(["--mode", "run", *args]), 2)
                result = runner.execute(**opts, transport=send, wait=lambda _: None)
                with self.assertRaisesRegex(runner.Fv3PredictionError, "already locked"):
                    runner.execute(**opts, transport=send)
            self.assertEqual(len(requests), 5)
            for spec in requests:
                self.assertEqual((spec.credential_slot, spec.research_task_id), ("gemini_slot_40", lock.TASK_ID))
                self.assertTrue(spec.job_id.startswith("M4B3Z_P4R8_"))
            self.assertEqual(requests[0].job_id, runner.SMOKE_JOB_ID)
            expected = dict(quote_resolution=True, anchor_mentions=True, mention_evidence=True,
                            mention_evidence_predicates=("RefersTo", "NamedAs"), sentence_evidence=True,
                            transfer_bounds=True, date_anchor=True, vocabulary_guard=True)
            self.assertEqual([list(call.kwargs.items()) for call in validate.call_args_list],
                             [list(expected.items())] * 4)
            primary, repair = result["predictions"][0]["attempts"]
            self.assertEqual(primary["host_repairs"], [])
            self.assertEqual(repair["host_repairs"], list(lock.HOST_REPAIRS))
            path = opts["output_root"] / runner.PREDICTION_LOCK_NAME
            self.assertEqual(lock.file_sha256(path), result["prediction_lock_sha256"])
            self.assertEqual(Path(str(path) + ".sha256").read_text().strip(), result["prediction_lock_sha256"])

    def test_smoke_and_case_order_refusals(self):
        with tempfile.TemporaryDirectory() as tmp, synthetic_bundle(Path(tmp)) as (opts, transport):
            transport.script[runner.SMOKE_JOB_ID] = ["invalid"]
            with self.assertRaisesRegex(runner.Fv3PredictionError, "qualification"):
                runner.execute(**opts, transport=transport)
            self.assertEqual(len(transport.calls), 1)
            with mock.patch.object(runner, "load_input_cases", return_value=[]):
                with self.assertRaisesRegex(runner.Fv3PredictionError, "identity"):
                    runner.load_cases(opts["fv3_directory"])
