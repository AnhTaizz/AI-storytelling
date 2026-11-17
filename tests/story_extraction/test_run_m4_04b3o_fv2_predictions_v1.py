"""Synthetic sealed zips and fake durable transports for the FV2 blind runner."""
from contextlib import ExitStack, contextmanager
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tests.story_extraction.test_fresh_validation_seal_v1 import authored
from tests.story_extraction.test_run_m4_04b3g_fv1_predictions_v1 import FakeTransport, Clock, executor
from tools.story_extraction import fresh_validation_seal_v1 as seal
from tools.story_extraction import m4_04b3n_fv2_protocol_v1 as lock
from tools.story_extraction import run_m4_04b3o_fv2_predictions_v1 as runner


@contextmanager
def synthetic_bundle(root):
    """Inject only seal identities/digests; exercise real zip loading and lock validation.

    Public binding validation still uses the actual public seal; package verification
    uses the independent tiny synthetic seal. No private inputs are consulted.
    """
    packages = root / "packages"
    cases = [authored("FV2_01", "c06_participant"), authored("FV2_02", "c02_two_mentions_one_entity")]
    summary = seal.seal(cases, packages, lock.FV2_SET_ID, "SYNTHETIC")
    originals = lock.package_bindings()
    validate_public = lock.validate_public_bindings

    def public(value):
        with mock.patch.object(lock, "package_bindings", return_value=originals):
            return validate_public(value)

    with ExitStack() as stack:
        stack.enter_context(mock.patch.object(lock, "CASE_IDS", tuple(c.case_id for c in cases)))
        for constant, key in (("FV2_INPUT_SHA256", "input"), ("FV2_GOLD_SHA256", "gold"),
                              ("FV2_MANIFEST_SHA256", "blindness_manifest")):
            stack.enter_context(mock.patch.object(lock, constant, summary["packages"][key]["sha256"]))
        stack.enter_context(mock.patch.object(lock, "validate_public_bindings", side_effect=public))
        protocol_path = root / "protocol.json"
        _, digest = lock.write_protocol(protocol_path)
        loaded = runner.load_cases(packages)
        drafts = {c.case_id: seal.representational_gate(c)["oracle_draft"] for c in cases}
        options = dict(protocol_path=protocol_path, protocol_sha256=digest, fv2_directory=packages,
                       output_root=root / "predictions")
        yield options, loaded, drafts


def fake_transport(drafts, smoke='{"status":"ok"}', overrides=None):
    script = {runner.SMOKE_JOB_ID: [smoke]}
    for cid, draft in drafts.items():
        script[f"M4B3N_{lock.PROMPT_VARIANT}_{cid}_PRIMARY"] = [json.dumps(draft)]
    script.update(overrides or {})
    return FakeTransport(script)


class RunnerTests(unittest.TestCase):
    def test_preflight_no_transport_no_gold_and_wrong_package_refused(self):
        with tempfile.TemporaryDirectory() as tmp, synthetic_bundle(Path(tmp)) as (opts, cases, drafts):
            args = ["--protocol", str(opts["protocol_path"]), "--protocol-sha256", opts["protocol_sha256"],
                    "--fv2-directory", str(opts["fv2_directory"])]
            # Any access (even hashing) of the gold archive is a test failure.
            original_open = Path.open

            def safe_open(path, *a, **kw):
                if path.name == lock.FV2_GOLD_NAME:
                    raise AssertionError("Runner touched gold")
                return original_open(path, *a, **kw)

            with mock.patch.object(Path, "open", safe_open), mock.patch.object(runner, "qualify_credential", wraps=runner.qualify_credential) as smoke, \
                    mock.patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(runner.main(["--mode", "preflight", *args]), 0)
                smoke.assert_not_called()
                self.assertEqual(runner.main(["--mode", "run", *args]), 2)
                transport = fake_transport(drafts)
                result = runner.execute(**opts, transport=transport, wait=lambda _: None)
                self.assertFalse(result["fv2_gold_opened"])
                self.assertEqual(len(transport.calls), 3)
                self.assertTrue(all("gold_batch" not in text for _, text in transport.calls))
                with self.assertRaisesRegex(runner.Fv2PredictionError, "already locked"):
                    runner.execute(**opts, transport=transport)
            for name in (lock.FV2_INPUT_NAME, lock.FV2_MANIFEST_NAME):
                path = opts["fv2_directory"] / name
                original = path.read_bytes()
                path.write_bytes(b"changed")
                with self.subTest(name), mock.patch("sys.stdout", new_callable=io.StringIO):
                    self.assertEqual(runner.main(["--mode", "preflight", *args]), 2)
                path.write_bytes(original)
            with mock.patch.object(runner, "load_input_cases", return_value=[]):
                with self.assertRaisesRegex(runner.Fv2PredictionError, "identity"):
                    runner.load_cases(opts["fv2_directory"])

    def test_real_compiler_primary_repair_and_transport_outcomes(self):
        with tempfile.TemporaryDirectory() as tmp, synthetic_bundle(Path(tmp)) as (opts, cases, drafts):
            cid = cases[0].case_id
            primary = f"M4B3N_{lock.PROMPT_VARIANT}_{cid}_PRIMARY"
            repair = f"M4B3N_{lock.PROMPT_VARIANT}_{cid}_REPAIR_1"
            variants = [("valid", {}, "STRUCTURAL_VALID", False),
                        ("repair", {primary: ["{"], repair: [json.dumps(drafts[cid])]}, "STRUCTURAL_VALID", True),
                        ("failure", {primary: ["null"], repair: ["{"]}, "STRUCTURAL_FAILURE", True),
                        ("transport", {primary: [None]}, "TRANSPORT_FAILURE", False),
                        ("repair transport", {primary: ["{"], repair: [None]}, "TRANSPORT_FAILURE", True)]
            for label, overrides, status, repaired in variants:
                with self.subTest(label):
                    clock = Clock()
                    transport = fake_transport(drafts, overrides=overrides)
                    rows = runner.run_cases(cases, executor(Path(tmp) / label, clock), transport,
                                            Path(tmp) / label / "artifacts", lambda: None, clock.wait)
                    self.assertEqual((rows[0]["terminal_status"], rows[0]["repair_used"]), (status, repaired))
                    self.assertLessEqual(len(rows[0]["attempts"]), 2)
            with self.assertRaisesRegex(runner.Fv2PredictionError, "ordered"):
                runner.run_cases(cases[::-1], None, None, Path(tmp), lambda: None, lambda _: None)

    def test_smoke_failure_run_cli_and_guard(self):
        with tempfile.TemporaryDirectory() as tmp, synthetic_bundle(Path(tmp)) as (opts, cases, drafts):
            for index, raw in enumerate(("invalid JSON", '{"status":"no"}')):
                with self.subTest(raw):
                    target = {**opts, "output_root": Path(tmp) / f"smoke-{index}"}
                    clock = Clock()
                    with self.assertRaisesRegex(runner.Fv2PredictionError, "qualification"):
                        runner.execute(**target, transport=fake_transport(drafts, smoke=raw), wait=clock.wait)
            clock = Clock()
            self.assertFalse(runner.qualify_credential(executor(Path(tmp) / "failed-smoke", clock),
                fake_transport(drafts, smoke=None), clock.wait)["qualified"])
            args = ["--mode", "run", "--protocol", str(opts["protocol_path"]),
                    "--protocol-sha256", opts["protocol_sha256"], "--fv2-directory", str(opts["fv2_directory"]),
                    "--output-root", str(opts["output_root"])]
            execute = runner.execute
            with mock.patch.object(runner, "execute", side_effect=lambda **kw:
                    execute(**kw, transport=fake_transport(drafts), wait=lambda _: None)), \
                    mock.patch("sys.stdout", new_callable=io.StringIO) as output:
                self.assertEqual(runner.main(args), 0)
                self.assertIn("prediction_lock_sha256", output.getvalue())


if __name__ == "__main__":
    unittest.main()
