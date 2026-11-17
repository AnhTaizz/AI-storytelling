"""Synthetic, fully offline scoring and prediction-lock tamper tests."""
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tests.story_extraction.test_run_m4_04b3o_fv2_predictions_v1 import synthetic_bundle, fake_transport
from tools.story_extraction import m4_04b3n_fv2_protocol_v1 as lock
from tools.story_extraction import run_m4_04b3o_fv2_predictions_v1 as runner
from tools.story_extraction import score_m4_04b3p_fv2_v1 as scorer


def score_options(options, result):
    return {k: v for k, v in options.items() if k != "output_root"} | {
        "prediction_directory": options["output_root"], "output_directory": options["output_root"].parent / "score",
        "prediction_lock_sha256": result["prediction_lock_sha256"]}


class ScorerTests(unittest.TestCase):
    def test_verified_gold_open_real_source_evaluation_and_aggregate_privacy(self):
        with tempfile.TemporaryDirectory() as tmp, synthetic_bundle(Path(tmp)) as (opts, _, drafts):
            result = runner.execute(**opts, transport=fake_transport(drafts), wait=lambda _: None)
            options = score_options(opts, result)
            read_gold = scorer.shared.read_gold
            evaluation = scorer.shared.evaluator.evaluate_case
            check = scorer.conventions.check_batch
            calls = []

            def read(path):
                access = json.loads((options["output_directory"] / scorer.ACCESS_NAME).read_bytes())
                self.assertEqual(access["prediction_lock_sha256"], result["prediction_lock_sha256"])
                self.assertLessEqual(access["verified_at_utc"], access["gold_open_started_at_utc"])
                calls.append("gold")
                return read_gold(path)

            def evaluate(*a, **kw):
                self.assertEqual(calls, ["gold"])
                self.assertEqual(kw["case_spec"]["mode"], "REAL_SOURCE")
                self.assertEqual(kw["case_spec"]["gold_completeness"], "COMPLETE_FOR_PROFILE")
                return evaluation(*a, **kw)

            with mock.patch.object(scorer.shared, "read_gold", side_effect=read), \
                    mock.patch.object(scorer.shared.evaluator, "evaluate_case", side_effect=evaluate) as evaluated, \
                    mock.patch.object(scorer.conventions, "check_batch", wraps=check) as checked:
                output = scorer.score(**options)
            self.assertEqual((evaluated.call_count, checked.call_count), (2, 2))
            self.assertEqual(output["summary"]["full_canonical_case_success_count"], 2)
            output["rows"][0]["case_id"] = "SECRET_CASE_ID"
            output["rows"][0]["evaluation"]["source_text"] = "SECRET_SOURCE_TEXT"
            output["rows"][0]["annotation_conventions"]["findings"] = [{"record_ids": ["SECRET_RECORD_ID"]}]
            public = scorer.public_summary(output)
            encoded = json.dumps(public)
            for forbidden in ("SECRET", "case_id", "FV2_01", "source_text", "record_ids"):
                self.assertNotIn(forbidden, encoded)
            self.assertEqual(public["annotation_conventions"]["cases_checked"], 2)
            self.assertEqual(public["aggregate"]["cases"], 2)
            self.assertTrue((options["output_directory"] / f"{scorer.EVALUATION_ID}.json").is_file())

    def test_all_hash_changes_refuse_before_gold(self):
        with tempfile.TemporaryDirectory() as tmp, synthetic_bundle(Path(tmp)) as (opts, _, drafts):
            result = runner.execute(**opts, transport=fake_transport(drafts), wait=lambda _: None)
            options = score_options(opts, result)
            root = opts["output_root"]
            record = json.loads((root / runner.PREDICTION_LOCK_NAME).read_bytes())
            paths = [root / runner.PREDICTION_LOCK_NAME, opts["protocol_path"],
                     *(root / name for name in record["files"]),
                     *(opts["fv2_directory"] / name for _, name, _ in lock.package_bindings())]
            for path in paths:
                with self.subTest(path=path.name):
                    payload = path.read_bytes()
                    path.write_bytes(payload + b" ")
                    with mock.patch.object(scorer.shared, "read_gold") as opened:
                        with self.assertRaises((lock.Fv2ProtocolError, scorer.Fv2ScoringError)):
                            scorer.score(**options)
                        opened.assert_not_called()
                    path.write_bytes(payload)
            self.assertFalse((options["output_directory"] / scorer.ACCESS_NAME).exists())

    def test_manifest_semantics_paths_inventory_and_terminal_refusals(self):
        with tempfile.TemporaryDirectory() as tmp, synthetic_bundle(Path(tmp)) as (opts, _, drafts):
            result = runner.execute(**opts, transport=fake_transport(drafts), wait=lambda _: None)
            root = opts["output_root"]
            originals = {p: p.read_bytes() for p in root.rglob("*.json") if "checkpoints" not in p.parts}
            baseline = json.loads(originals[root / runner.PREDICTION_LOCK_NAME])

            def modify_file(name, change):
                path = root / name
                value = json.loads(path.read_bytes())
                change(value)
                path.write_bytes(lock.canonical_json_bytes(value))

            def modify_rows(change):
                value = json.loads((root / runner.RESULT_NAME).read_bytes())
                change(value["predictions"])
                (root / runner.RESULT_NAME).write_bytes(lock.canonical_json_bytes(value))

            mutations = [
                lambda r: r.update(protocol_sha256="wrong"),
                lambda r: r["files"].update({"../escape": "0" * 64}),
                lambda r: r.update(prediction_set_sha256="wrong"),
                lambda r: modify_file(runner.MANIFEST_NAME, lambda m: m.update(predictions_locked=False)),
                lambda r: modify_file(runner.MANIFEST_NAME, lambda m: m.update(protocol_sha256="wrong")),
                lambda r: modify_file(runner.MANIFEST_NAME, lambda m: m.update(entries=[])),
                lambda r: modify_rows(lambda rows: rows.reverse()),
                lambda r: modify_file("artifacts/case_results/FV2_01.json", lambda m: m.update(repair_used=True)),
                lambda r: r["files"].pop("artifacts/raw/FV2_01_primary.txt"),
                lambda r: r["files"].update({"smoke.json": lock.file_sha256(root / "smoke.json")}),
            ]
            for index, mutate in enumerate(mutations):
                for path, data in originals.items():
                    path.write_bytes(data)
                record = deepcopy(baseline)
                mutate(record)
                # Re-pin mutated artifacts to exercise semantic checks independently of byte checks.
                for name in list(record["files"]):
                    if name != "../escape":
                        record["files"][name] = lock.file_sha256(root / name)
                payload = lock.canonical_json_bytes(record)
                (root / runner.PREDICTION_LOCK_NAME).write_bytes(payload)
                with self.subTest(index=index), self.assertRaises(scorer.Fv2ScoringError):
                    scorer.verify_prediction_lock(root, lock.sha256_bytes(payload), opts["protocol_sha256"])

    def test_structural_failures_gold_metadata_and_cli(self):
        with tempfile.TemporaryDirectory() as tmp, synthetic_bundle(Path(tmp)) as (opts, _, drafts):
            prefix = f"M4B3N_{lock.PROMPT_VARIANT}_FV2_01_"
            result = runner.execute(**opts, transport=fake_transport(drafts,
                overrides={prefix + "PRIMARY": ["{"], prefix + "REPAIR_1": ["{"]}), wait=lambda _: None)
            options = score_options(opts, result)
            output = scorer.score(**options)
            self.assertEqual(output["rows"][0]["terminal_status"], "STRUCTURAL_FAILURE")
            self.assertIsNone(output["rows"][0]["annotation_conventions"])
            self.assertEqual(scorer.public_summary(output)["annotation_conventions"]["cases_checked"], 1)
            for gold, message in (({}, "order"), ({cid: {"gold_completeness": "UNCERTAIN"} for cid in lock.CASE_IDS}, "completeness")):
                with self.subTest(message), mock.patch.object(scorer.shared, "read_gold", return_value=gold):
                    with self.assertRaisesRegex(scorer.Fv2ScoringError, message):
                        scorer.score(**options)
            args = []
            for key, value in options.items():
                args.extend(["--" + ("protocol" if key == "protocol_path" else key.replace("_", "-")), str(value)])
            with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                self.assertEqual(scorer.main(args), 0)
                self.assertNotIn("FV2_01", stdout.getvalue())
                args[args.index("--prediction-lock-sha256") + 1] = "wrong"
                self.assertEqual(scorer.main(args), 2)


if __name__ == "__main__":
    unittest.main()
