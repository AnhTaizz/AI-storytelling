"""Offline gold chronology, pinning and public aggregate tests."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tests.story_extraction.test_run_m4_04b3z_fv3_predictions_v1 import synthetic_bundle
from tests.story_extraction.test_score_m4_04b3p_fv2_v1 import score_options
from tools.story_extraction import m4_04b3z_fv3_protocol_v1 as lock
from tools.story_extraction import run_m4_04b3z_fv3_predictions_v1 as runner
from tools.story_extraction import score_m4_04b3z_fv3_v1 as scorer


class ScorerTests(unittest.TestCase):
    def test_hash_refusals_then_verified_gold_access_and_counts_only_summary(self):
        with tempfile.TemporaryDirectory() as tmp, synthetic_bundle(Path(tmp)) as (opts, transport):
            result = runner.execute(**opts, transport=transport, wait=lambda _: None)
            options = score_options(opts, result)
            output = options["output_directory"]
            root = opts["output_root"]
            pinned = root / runner.PREDICTION_LOCK_NAME
            record = json.loads(pinned.read_bytes())
            for path in [opts["protocol_path"], pinned, Path(str(pinned) + ".sha256"), *(root / name for name in record["files"]),
                         *(opts["fv3_directory"] / name for _, name, _ in lock.package_bindings())]:
                original = path.read_bytes()
                path.write_bytes(original + b"!")
                with self.subTest(path=path.name), mock.patch.object(scorer.shared, "read_gold") as opened:
                    with self.assertRaises((lock.Fv3ProtocolError, scorer.Fv3ScoringError)):
                        scorer.score(**options)
                    opened.assert_not_called()
                    self.assertFalse((output / scorer.ACCESS_NAME).exists())
                path.write_bytes(original)

            read = scorer.shared.read_gold
            def open_after_lock(path):
                access = json.loads((output / scorer.ACCESS_NAME).read_bytes())
                self.assertEqual(access["prediction_lock_sha256"], lock.file_sha256(pinned))
                self.assertLessEqual(access["verified_at_utc"], access["gold_open_started_at_utc"])
                self.assertEqual(access["provider_operations_after_gold_open"], 0)
                return read(path)

            args = []
            for key, value in options.items():
                args.extend(["--" + ("protocol" if key == "protocol_path" else key.replace("_", "-")), str(value)])
            with mock.patch.object(scorer.shared, "read_gold", side_effect=open_after_lock) as opened:
                self.assertEqual(scorer.main(args), 0)
                opened.assert_called_once()
                self.assertEqual(scorer.main([*args, "--prediction-lock-sha256", "bad"]), 2)
                opened.assert_called_once()
            public = json.loads((output / "PUBLIC_SUMMARY.json").read_bytes())
            private = json.loads((output / (scorer.EVALUATION_ID + ".json")).read_bytes())
            self.assertEqual(public["aggregate"]["cases"], 2)
            self.assertEqual(public["annotation_conventions"]["cases_checked"], 1)
            self.assertEqual(set(public["annotation_conventions"]["counts"]), set(scorer.conventions.RULES))
            private["rows"][0].update(case_id="PRIVATE_ID", source_text="PRIVATE_TEXT")
            private["rows"][0]["annotation_conventions"]["findings"] = [{"record_ids": ["PRIVATE"]}]
            self.assertEqual(public, scorer.public_summary(private))
            def check_counts(tree):
                for value in tree.values():
                    if isinstance(value, dict):
                        check_counts(value)
                    else:
                        self.assertIs(type(value), int)
            for key in ("aggregate", "annotation_conventions"):
                check_counts(public[key])
            for case_id in lock.CASE_IDS:
                self.assertNotIn(case_id, json.dumps(public))
