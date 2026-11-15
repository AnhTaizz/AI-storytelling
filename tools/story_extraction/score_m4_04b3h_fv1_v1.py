"""M4-04B3H: score the locked M4-04B3G FV1 predictions with the frozen Snapshot V2 evaluator.

Order of operations, each refusing to go on when its check fails:
1. every private prediction artifact hashes to the public prediction lock, and the prediction
   set hash recomputes; the lock record is the one committed on main;
2. the FV1 input, gold and blindness-manifest files hash to the M4-04B3E seal;
3. only then is the gold package opened (an access record states the chronology);
4. each case is scored by `evaluate_extraction_guarded_v1.evaluate_case` in `REAL_SOURCE`
   mode with the sealed `COMPLETE_FOR_PROFILE` completeness, the structural failure as a
   failed case; aggregates come from the frozen `aggregate` and the M4-04B2R summary layers.

No model call, repair or re-run happens here. The full result stays private (it carries
assertion identities and evidence); `public_summary` keeps metrics, outcomes, codes and hashes.

    python -m tools.story_extraction.score_m4_04b3h_fv1_v1 --fv1-directory <dir> \\
        --prediction-directory <dir> --output-directory <dir> --lock-commit <sha>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
from zipfile import ZipFile

import yaml

from tools.story_extraction import evaluate_extraction_guarded_v1 as evaluator
from tools.story_extraction import m4_04b3f_fv1_protocol_v1 as fv1lock
from tools.story_extraction.evaluate_m4_04b2r_dev_v2 import _structural_failure_result, _summary

REPO = Path(__file__).resolve().parents[2]
EVALUATION_ID = "M4_04B3H_FV1_EVALUATION_V1"
LOCK_RECORD = REPO / "benchmarks/m4_extraction/M4_04B3G_FV1_PREDICTION_LOCK.yaml"
GOLD_NAME = "M4_04B3E_FRESH_VALIDATION_V1_GOLD.zip"
INPUT_NAME = "M4_04B3E_FRESH_VALIDATION_V1_INPUT.zip"
MANIFEST_NAME = "M4_04B3E_FRESH_VALIDATION_V1_BLINDNESS_MANIFEST.json"
GOLD_SHA256 = "732a3555717c6d3426e6e379e43061cd1fd6d11df8798ec859f37248202ddc73"
SNAPSHOT_V2_SHA256 = "8dddbd0b9f3ea51af593c1fab0631b088b6f4e6b8c16833a1f11b8448088eee9"


class Fv1ScoringError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def verify_prediction_lock(lock: Mapping[str, Any], prediction_directory: Path) -> List[Dict[str, Any]]:
    """Check every private artifact against the lock; returns the per-case results."""
    root = Path(prediction_directory)
    expected = lock["prediction_lock"]
    for key in ("private_prediction_manifest", "private_result"):
        if _sha256(root / expected[key]["name"]) != expected[key]["sha256"]:
            raise Fv1ScoringError(f"{key} hash mismatch")
    artifacts = root / "artifacts"
    results = []
    for case in lock["cases"]:
        cid = case["case_id"]
        if case["compiled_batch_sha256"] and _sha256(artifacts / "compiled" / f"{cid}.json") != case["compiled_batch_sha256"]:
            raise Fv1ScoringError(f"{cid}: compiled batch hash mismatch")
        if case["terminal_failure_sha256"] and _sha256(artifacts / "failures" / f"{cid}.json") != case["terminal_failure_sha256"]:
            raise Fv1ScoringError(f"{cid}: terminal failure hash mismatch")
        for attempt in case["attempts"]:
            name = f"{cid}_{attempt['phase']}"
            if _sha256(artifacts / "raw" / f"{name}.txt") != attempt["raw_response_sha256"]:
                raise Fv1ScoringError(f"{name}: raw response hash mismatch")
            if attempt["draft_sha256"] and _sha256(artifacts / "drafts" / f"{name}.json") != attempt["draft_sha256"]:
                raise Fv1ScoringError(f"{name}: draft hash mismatch")
        results.append(_load(artifacts / "case_results" / f"{cid}.json"))
    identities = [{"case_id": r["case_id"], "terminal_status": r["terminal_status"],
                   "compiled_batch_sha256": r["compiled_batch_sha256"],
                   "terminal_failure_sha256": r["terminal_failure_sha256"],
                   "attempts": [{key: a[key] for key in ("phase", "request_fingerprint", "raw_response_sha256",
                                                          "draft_sha256")} for a in r["attempts"]]}
                  for r in results]
    if fv1lock.sha256_bytes(fv1lock.canonical_json_bytes(identities)) != expected["prediction_set_sha256"]:
        raise Fv1ScoringError("prediction set hash mismatch")
    if [r["case_id"] for r in results] != list(fv1lock.CASE_IDS):
        raise Fv1ScoringError("case identity or order mismatch")
    return results


def verify_fv1_files(fv1_directory: Path) -> None:
    root = Path(fv1_directory)
    if _sha256(root / INPUT_NAME) != fv1lock.FV1_INPUT_SHA256:
        raise Fv1ScoringError("FV1 input hash mismatch")
    if _sha256(root / MANIFEST_NAME) != fv1lock.FV1_MANIFEST_SHA256:
        raise Fv1ScoringError("FV1 blindness manifest hash mismatch")
    if _sha256(root / GOLD_NAME) != GOLD_SHA256:
        raise Fv1ScoringError("FV1 gold hash mismatch")


def read_gold(gold_zip: Path) -> Dict[str, Dict[str, Any]]:
    """case id -> {"gold_batch", "gold_completeness", "gold_sha256"} from the sealed gold package."""
    with ZipFile(gold_zip) as archive:
        manifest = json.loads(archive.read("gold_manifest.json"))
        gold = {}
        for row in manifest["cases"]:
            data = archive.read(row["gold_batch_member"])
            gold[row["case_id"]] = {"gold_batch": json.loads(data), "gold_sha256": hashlib.sha256(data).hexdigest(),
                                    "gold_completeness": row["gold_completeness"]}
    return gold


def score(fv1_directory: Path, prediction_directory: Path, output_directory: Path, lock_commit: str,
          lock_record: Path = LOCK_RECORD, load_cases=None) -> Dict[str, Any]:
    """Verify, open the gold, score every case; writes the private result and access record."""
    lock = yaml.safe_load(Path(lock_record).read_text(encoding="utf-8"))
    predictions = verify_prediction_lock(lock, prediction_directory)
    verify_fv1_files(fv1_directory)
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    opened_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    gold = read_gold(Path(fv1_directory) / GOLD_NAME)
    if list(gold) != list(fv1lock.CASE_IDS):
        raise Fv1ScoringError("gold case identity or order mismatch")
    access = {"artifact": "M4_04B3H_FV1_GOLD_ACCESS_V1", "prediction_lock_commit": lock_commit,
              "chronology": "PREDICTION_LOCK_ON_MAIN_THEN_FV1_GOLD_OPENED", "fv1_gold_opened_at_utc": opened_at,
              "gold_member_sha256": {cid: item["gold_sha256"] for cid, item in gold.items()},
              "provider_operations_after_gold_open": 0, "holdout_accessed": False}
    (output_directory / "M4_04B3H_FV1_GOLD_ACCESS_V1.json").write_text(
        json.dumps(access, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    if load_cases is None:
        from tools.story_extraction.fresh_validation_seal_v1 import load_input_cases as load_cases
    contexts = {row["case_id"]: row for row in load_cases(Path(fv1_directory) / INPUT_NAME)}
    rows = []
    artifacts = Path(prediction_directory) / "artifacts"
    for prediction in predictions:
        cid = prediction["case_id"]
        case = gold[cid]
        if prediction["terminal_status"] == "STRUCTURAL_VALID":
            compiled = _load(artifacts / "compiled" / f"{cid}.json")
            result = evaluator.evaluate_case(
                contexts[cid]["base_document"], case["gold_batch"], compiled,
                ingestion=contexts[cid]["context"].ingestion,
                case_spec={"mode": "REAL_SOURCE", "gold_completeness": case["gold_completeness"],
                           "acceptable_assertion_ids": [], "adjudications": []})
        else:
            validation = _load(artifacts / "failures" / f"{cid}.json")["validation"]
            codes = sorted({f"{b.get('phase')}:{b.get('code')}" for b in validation.get("blockers", [])}
                           or {str(validation.get("category"))})
            result = _structural_failure_result({"repair_validation": {"errors": codes}}, case["gold_completeness"])
        rows.append({"case_id": cid, "terminal_status": prediction["terminal_status"],
                     "repair_used": prediction["repair_used"], "evaluation": result})
    output = {"artifact": EVALUATION_ID, "completed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "snapshot_v2_sha256": SNAPSHOT_V2_SHA256, "evaluator_version": evaluator.EVALUATOR_VERSION,
              "prediction_lock_commit": lock_commit,
              "prediction_set_sha256": lock["prediction_lock"]["prediction_set_sha256"],
              "gold_sha256": GOLD_SHA256, "rows": rows, "summary": _summary([r["evaluation"] for r in rows]),
              "provider_operations_after_gold_open": 0, "holdout_accessed": False}
    (output_directory / f"{EVALUATION_ID}.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return output


METRICS = ("assertion_precision", "assertion_recall", "evidence_grounding_precision", "evidence_grounding_recall",
           "epistemic_accuracy", "evidence_role_accuracy", "referent_resolution_accuracy")


def public_summary(output: Mapping[str, Any]) -> Dict[str, Any]:
    """The publishable part: per-case outcome, metrics, counts and failure codes; no assertion
    content, evidence or source text."""
    cases = []
    for row in output["rows"]:
        evaluation = row["evaluation"]
        metrics = evaluation.get("metrics") or {}
        cases.append({
            "case_id": row["case_id"], "terminal_status": row["terminal_status"], "repair_used": row["repair_used"],
            "l0_structural_validity": evaluation.get("l0_structural_validity"),
            "case_outcome": evaluation.get("case_outcome"),
            "metrics": {name: metrics.get(name) for name in METRICS} if metrics else None,
            "counts": evaluation.get("counts"),
            "failure_code_counts": dict(sorted(Counter(f.get("code") for f in evaluation.get("failures", [])).items())),
        })
    summary = dict(output["summary"])
    return {"artifact": output["artifact"], "evaluator_version": output["evaluator_version"],
            "snapshot_v2_sha256": output["snapshot_v2_sha256"], "prediction_lock_commit": output["prediction_lock_commit"],
            "prediction_set_sha256": output["prediction_set_sha256"], "gold_sha256": output["gold_sha256"],
            "aggregate": summary, "cases": cases}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fv1-directory", type=Path, required=True)
    parser.add_argument("--prediction-directory", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--lock-commit", required=True)
    args = parser.parse_args(argv)
    try:
        output = score(args.fv1_directory, args.prediction_directory, args.output_directory, args.lock_commit)
    except Fv1ScoringError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(public_summary(output), ensure_ascii=False, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
