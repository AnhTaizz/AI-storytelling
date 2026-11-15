"""Offline tests for tools/story_extraction/score_m4_04b3h_fv1_v1.py (synthetic files only)."""
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from zipfile import ZipFile

import yaml

from tools.story_extraction import m4_04b3f_fv1_protocol_v1 as fv1lock
from tools.story_extraction import score_m4_04b3h_fv1_v1 as scorer

CASES = list(fv1lock.CASE_IDS)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def scored(case_id):
    metrics = {name: 0.5 for name in scorer.METRICS}
    return {"evaluator_version": "x", "mode": "REAL_SOURCE", "l0_structural_validity": True, "metrics": metrics,
            "counts": {"matched_predictions": 1, "valid_additional": 0, "predicted": 2, "out_of_scope": 0,
                       "equivalent_representation": 0, "required_recovered": 1, "gold_required": 2,
                       "unsupported": 1},
            "failures": [{"code": "MISSED_REQUIRED_ASSERTION", "detail": "private"}],
            "failure_codes": ["MISSED_REQUIRED_ASSERTION"], "unmatched_predictions": [],
            "full_canonical_case_success": False, "case_outcome": "FAIL"}


class Fixture:
    """A prediction directory, an FV1 directory and a lock record whose hashes agree."""

    def __init__(self, root: Path):
        self.predictions, self.fv1, self.out = root / "pred", root / "fv1", root / "out"
        art = self.predictions / "artifacts"
        for sub in ("compiled", "failures", "raw", "drafts", "case_results"):
            (art / sub).mkdir(parents=True)
        cases, results = [], []
        for cid in CASES:
            failed = cid == "FV1_03"
            raw = f"raw {cid}".encode()
            draft = json.dumps({"draft": cid}).encode()
            (art / "raw" / f"{cid}_primary.txt").write_bytes(raw)
            (art / "drafts" / f"{cid}_primary.json").write_bytes(draft)
            attempt = {"phase": "primary", "request_fingerprint": "f", "raw_response_sha256": sha(raw),
                       "draft_sha256": sha(draft)}
            if failed:
                data = json.dumps({"case_id": cid, "terminal_status": "STRUCTURAL_FAILURE", "validation": {
                    "pass": False, "category": "DRAFT_COMPILER_FAILURE",
                    "blockers": [{"phase": "CANONICAL_COMPILER", "code": "CANONICAL_CONFORMANCE_FAILURE",
                                  "path": "canonical"}]}}).encode()
                (art / "failures" / f"{cid}.json").write_bytes(data)
                compiled, failure = None, sha(data)
            else:
                data = json.dumps({"batch": cid}).encode()
                (art / "compiled" / f"{cid}.json").write_bytes(data)
                compiled, failure = sha(data), None
            status = "STRUCTURAL_FAILURE" if failed else "STRUCTURAL_VALID"
            result = {"case_id": cid, "terminal_status": status, "repair_used": False, "attempts": [attempt],
                      "compiled_batch_sha256": compiled, "terminal_failure_sha256": failure}
            (art / "case_results" / f"{cid}.json").write_text(json.dumps(result), encoding="utf-8")
            results.append(result)
            cases.append({"case_id": cid, "terminal_status": status, "repair_used": False,
                          "compiled_batch_sha256": compiled, "terminal_failure_sha256": failure,
                          "attempts": [attempt]})
        for name in ("MANIFEST", "RESULT"):
            (self.predictions / f"{name}.json").write_text("{}", encoding="utf-8")
        identities = [{"case_id": r["case_id"], "terminal_status": r["terminal_status"],
                       "compiled_batch_sha256": r["compiled_batch_sha256"],
                       "terminal_failure_sha256": r["terminal_failure_sha256"],
                       "attempts": r["attempts"]} for r in results]
        self.lock = {"prediction_lock": {
            "prediction_set_sha256": fv1lock.sha256_bytes(fv1lock.canonical_json_bytes(identities)),
            "private_prediction_manifest": {"name": "MANIFEST.json", "sha256": sha(b"{}")},
            "private_result": {"name": "RESULT.json", "sha256": sha(b"{}")}}, "cases": cases}
        self.lock_path = root / "lock.yaml"
        self.lock_path.write_text(yaml.safe_dump(self.lock), encoding="utf-8")
        self.fv1.mkdir()
        (self.fv1 / scorer.INPUT_NAME).write_bytes(b"input")
        (self.fv1 / scorer.MANIFEST_NAME).write_bytes(b"manifest")
        with ZipFile(self.fv1 / scorer.GOLD_NAME, "w") as archive:
            archive.writestr("gold_manifest.json", json.dumps({"cases": [
                {"case_id": cid, "gold_batch_member": f"gold/{cid}/gold_batch.json",
                 "gold_completeness": "COMPLETE_FOR_PROFILE"} for cid in CASES]}))
            for cid in CASES:
                archive.writestr(f"gold/{cid}/gold_batch.json", json.dumps({"gold": cid}))
        self.hashes = {"input": sha(b"input"), "manifest": sha(b"manifest"),
                       "gold": sha((self.fv1 / scorer.GOLD_NAME).read_bytes())}

    def patches(self):
        return [mock.patch.object(fv1lock, "FV1_INPUT_SHA256", self.hashes["input"]),
                mock.patch.object(fv1lock, "FV1_MANIFEST_SHA256", self.hashes["manifest"]),
                mock.patch.object(scorer, "GOLD_SHA256", self.hashes["gold"])]


def load_cases(_path):
    return [{"case_id": cid, "base_document": {"base": cid}, "context": mock.Mock(ingestion=None)} for cid in CASES]


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fx = Fixture(Path(self.tmp.name))
        for patch in self.fx.patches():
            patch.start()
            self.addCleanup(patch.stop)

    def run_score(self):
        with mock.patch.object(scorer.evaluator, "evaluate_case", side_effect=lambda base, gold, pred, **kw: scored(
                gold["gold"])) as evaluate:
            output = scorer.score(self.fx.fv1, self.fx.predictions, self.fx.out, "abc", self.fx.lock_path,
                                  load_cases=load_cases)
        return output, evaluate

    def test_verified_predictions_are_scored_and_the_failure_counts_as_a_failed_case(self):
        output, evaluate = self.run_score()
        self.assertEqual(evaluate.call_count, 9)
        spec = evaluate.call_args.kwargs["case_spec"]
        self.assertEqual((spec["mode"], spec["gold_completeness"]), ("REAL_SOURCE", "COMPLETE_FOR_PROFILE"))
        failed = next(r for r in output["rows"] if r["case_id"] == "FV1_03")["evaluation"]
        self.assertEqual((failed["case_outcome"], failed["l0_structural_validity"]), ("FAIL", False))
        self.assertEqual(failed["failures"][0]["detail"], ["CANONICAL_COMPILER:CANONICAL_CONFORMANCE_FAILURE"])
        self.assertEqual(output["summary"]["layers"]["L0_structural_valid"], 9)
        access = json.loads((self.fx.out / "M4_04B3H_FV1_GOLD_ACCESS_V1.json").read_text(encoding="utf-8"))
        self.assertEqual(access["chronology"], "PREDICTION_LOCK_ON_MAIN_THEN_FV1_GOLD_OPENED")
        self.assertEqual(set(access["gold_member_sha256"]), set(CASES))
        public = scorer.public_summary(output)
        text = json.dumps(public)
        self.assertNotIn("private", text)  # failure details never reach the public record
        self.assertEqual(public["cases"][0]["failure_code_counts"], {"MISSED_REQUIRED_ASSERTION": 1})
        self.assertIsNone(public["cases"][2]["metrics"])

    def test_any_mismatch_stops_before_the_gold_is_opened(self):
        artifacts = self.fx.predictions / "artifacts"
        tamper = {
            "compiled batch": artifacts / "compiled" / "FV1_01.json",
            "terminal failure": artifacts / "failures" / "FV1_03.json",
            "raw response": artifacts / "raw" / "FV1_02_primary.txt",
            "draft": artifacts / "drafts" / "FV1_02_primary.json",
            "private manifest": self.fx.predictions / "MANIFEST.json",
            "gold": self.fx.fv1 / scorer.GOLD_NAME,
            "input": self.fx.fv1 / scorer.INPUT_NAME,
            "blindness manifest": self.fx.fv1 / scorer.MANIFEST_NAME,
        }
        for label, path in tamper.items():
            with self.subTest(label):
                original = path.read_bytes()
                path.write_bytes(original + b" ")
                try:
                    with mock.patch.object(scorer, "read_gold") as read_gold, self.assertRaises(scorer.Fv1ScoringError):
                        scorer.score(self.fx.fv1, self.fx.predictions, self.fx.out, "abc", self.fx.lock_path,
                                     load_cases=load_cases)
                    read_gold.assert_not_called()
                finally:
                    path.write_bytes(original)
        lock = yaml.safe_load(self.fx.lock_path.read_text(encoding="utf-8"))
        lock["prediction_lock"]["prediction_set_sha256"] = "0" * 64
        self.fx.lock_path.write_text(yaml.safe_dump(lock), encoding="utf-8")
        with self.assertRaisesRegex(scorer.Fv1ScoringError, "prediction set"):
            scorer.score(self.fx.fv1, self.fx.predictions, self.fx.out, "abc", self.fx.lock_path, load_cases=load_cases)

    def test_cli_prints_the_public_summary_or_refuses(self):
        args = ["--fv1-directory", str(self.fx.fv1), "--prediction-directory", str(self.fx.predictions),
                "--output-directory", str(self.fx.out), "--lock-commit", "abc"]
        out = io.StringIO()
        with mock.patch.object(scorer, "score", return_value={
                "artifact": "a", "evaluator_version": "e", "snapshot_v2_sha256": "s", "prediction_lock_commit": "abc",
                "prediction_set_sha256": "p", "gold_sha256": "g", "summary": {"cases": 0}, "rows": []}), \
                contextlib.redirect_stdout(out):
            self.assertEqual(scorer.main(args), 0)
        self.assertEqual(json.loads(out.getvalue())["prediction_lock_commit"], "abc")
        err = io.StringIO()
        with mock.patch.object(scorer, "score", side_effect=scorer.Fv1ScoringError("gold hash mismatch")), \
                contextlib.redirect_stderr(err):
            self.assertEqual(scorer.main(args), 1)
        self.assertIn("refused: gold hash mismatch", err.getvalue())


if __name__ == "__main__":
    unittest.main()
