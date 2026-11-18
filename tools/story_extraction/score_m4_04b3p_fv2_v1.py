"""Offline FV2 scoring, only after a digest-pinned terminal prediction lock verifies.

All prediction artifacts, public protocol bindings and three sealed package hashes
verify before gold is opened. The access record is persisted before that open.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from tools.story_extraction import m4_04b3n_fv2_protocol_v1 as lock
from tools.story_extraction import run_m4_04b3o_fv2_predictions_v1 as runner
from tools.story_extraction import score_m4_04b3h_fv1_v1 as shared
from tools.story_extraction import check_annotation_conventions_v1 as conventions
from tools.story_extraction.fresh_validation_seal_v1 import load_input_cases

EVALUATION_ID = "M4_04B3P_FV2_EVALUATION_V1"
ACCESS_NAME = "M4_04B3P_FV2_GOLD_ACCESS_V1.json"
Fv2ScoringError = shared.Fv1ScoringError


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Fv2ScoringError(message)


def verify_prediction_lock(prediction_directory: Path, expected_sha256: str,
                           protocol_sha256: str) -> tuple[list[dict], dict]:
    root = Path(prediction_directory)
    payload = (root / runner.PREDICTION_LOCK_NAME).read_bytes()
    _require(lock.sha256_bytes(payload) == expected_sha256, "Prediction lock hash mismatch")
    record = json.loads(payload)
    _require(record["artifact"] == runner.PREDICTION_LOCK_NAME[:-5]
             and record["protocol_sha256"] == protocol_sha256, "Prediction lock identity mismatch")
    for name, digest in record["files"].items():
        path = PurePosixPath(name)
        _require(not path.is_absolute() and ".." not in path.parts and "\\" not in name
                 and ":" not in name and (root / name).resolve().is_relative_to(root.resolve()),
                 "Unsafe prediction artifact path")
        _require(lock.file_sha256(root / name) == digest, "Prediction artifact hash mismatch")
    manifest = shared._load(root / runner.MANIFEST_NAME)
    result = shared._load(root / runner.RESULT_NAME)
    predictions = result["predictions"]
    _require(manifest["predictions_locked"] is True and result["smoke"]["qualified"] is True,
             "Nonterminal or unqualified predictions")
    _require([r["case_id"] for r in predictions] == list(lock.CASE_IDS), "Prediction case order mismatch")
    identities = runner.prediction_identities(predictions)
    digest = lock.sha256_bytes(lock.canonical_json_bytes(identities))
    bindings = {k: h for k, _, h in lock.package_bindings()}
    _require(manifest["entries"] == identities and digest == record["prediction_set_sha256"],
             "Prediction set hash mismatch")
    for item in (manifest, result):
        _require(item["prediction_set_sha256"] == digest and item["protocol_sha256"] == protocol_sha256
                 and item["fv2_bindings"] == bindings and item["fv2_gold_opened"] is False,
                 "Prediction protocol or package binding mismatch")
    required = {runner.MANIFEST_NAME, runner.RESULT_NAME}
    for row in predictions:
        cid = row["case_id"]
        case_name = f"artifacts/case_results/{cid}.json"
        required.add(case_name)
        _require(shared._load(root / case_name) == row, "Case result differs from locked result")
        attempts = row["attempts"]
        _require([a["phase"] for a in attempts] in (["primary"], ["primary", "repair_1"])
                 and row["repair_used"] == (len(attempts) == 2), "Invalid prediction attempt sequence")
        valid = row["terminal_status"] == "STRUCTURAL_VALID"
        _require(row["terminal_status"] in ("STRUCTURAL_VALID", "STRUCTURAL_FAILURE", "TRANSPORT_FAILURE")
                 and bool(row["compiled_batch_sha256"]) == valid
                 and bool(row["terminal_failure_sha256"]) != valid, "Invalid terminal prediction")
        terminal = f"artifacts/{'compiled' if valid else 'failures'}/{cid}.json"
        required.add(terminal)
        _require(record["files"].get(terminal) == row["compiled_batch_sha256" if valid else "terminal_failure_sha256"],
                 "Terminal artifact binding mismatch")
        for attempt in attempts:
            for folder, suffix, key in (("raw", "txt", "raw_response_sha256"), ("drafts", "json", "draft_sha256")):
                if attempt[key] is not None:
                    name = f"artifacts/{folder}/{cid}_{attempt['phase']}.{suffix}"
                    required.add(name)
                    _require(record["files"].get(name) == attempt[key], "Attempt artifact binding mismatch")
    _require(set(record["files"]) == required, "Prediction artifact inventory mismatch")
    return predictions, record


def score(*, fv2_directory: Path, prediction_directory: Path, output_directory: Path,
          protocol_path: Path, protocol_sha256: str, prediction_lock_sha256: str) -> dict[str, Any]:
    validated = lock.validate_protocol_file(protocol_path, protocol_sha256)
    predictions, record = verify_prediction_lock(prediction_directory, prediction_lock_sha256, protocol_sha256)
    lock.verify_fv2_packages(fv2_directory, include_gold=True)
    # Cache the verified input and prediction bytes before opening gold; no provider path exists here.
    inputs = load_input_cases(Path(fv2_directory) / lock.FV2_INPUT_NAME)
    _require([r["case_id"] for r in inputs] == list(lock.CASE_IDS), "Input case order mismatch")
    contexts = {r["case_id"]: r for r in inputs}
    batches, failures = {}, {}
    for row in predictions:
        cid = row["case_id"]
        if row["terminal_status"] == "STRUCTURAL_VALID":
            batches[cid] = shared._load(Path(prediction_directory) / f"artifacts/compiled/{cid}.json")
        else:
            failures[cid] = shared._load(Path(prediction_directory) / f"artifacts/failures/{cid}.json")["validation"]
    # Reverify after loading so mutable artifact paths cannot silently change during preparation.
    verify_prediction_lock(prediction_directory, prediction_lock_sha256, protocol_sha256)
    validated.assert_unchanged()
    lock.validate_public_bindings(validated.value)
    lock.verify_fv2_packages(fv2_directory, include_gold=True)
    access = {"artifact": ACCESS_NAME[:-5], "prediction_lock_sha256": prediction_lock_sha256,
              "verified_at_utc": runner.shared._utc_now(), "gold_open_started_at_utc": runner.shared._utc_now(),
              "chronology": "ALL_LOCKS_AND_PACKAGE_HASHES_VERIFIED_BEFORE_GOLD_OPEN",
              "provider_operations_after_gold_open": 0}
    runner.shared._write_json(Path(output_directory) / ACCESS_NAME, access)
    gold = shared.read_gold(Path(fv2_directory) / lock.FV2_GOLD_NAME)
    _require(list(gold) == list(lock.CASE_IDS), "Gold case order mismatch")
    _require(all(g["gold_completeness"] == "COMPLETE_FOR_PROFILE" for g in gold.values()),
             "Sealed completeness mismatch")
    rows = []
    for prediction in predictions:
        cid = prediction["case_id"]
        case, context = gold[cid], contexts[cid]
        if cid in batches:
            result = shared.evaluator.evaluate_case(context["base_document"], case["gold_batch"], batches[cid],
                ingestion=context["context"].ingestion,
                case_spec={"mode": "REAL_SOURCE", "gold_completeness": case["gold_completeness"],
                           "acceptable_assertion_ids": [], "adjudications": []})
            report = conventions.check_batch(batches[cid], (d.source_bytes for d in context["context"].ingestion.documents),
                                             context["base_document"])
        else:
            validation = failures[cid]
            codes = sorted({f"{b['phase']}:{b['code']}" for b in validation.get("blockers", [])}
                           or {validation["category"]})
            result = shared._structural_failure_result({"repair_validation": {"errors": codes}}, case["gold_completeness"])
            report = None
        rows.append({"case_id": cid, "terminal_status": prediction["terminal_status"],
                     "repair_used": prediction["repair_used"], "evaluation": result, "annotation_conventions": report})
    output = {"artifact": EVALUATION_ID, "rows": rows, "summary": shared._summary([r["evaluation"] for r in rows]),
              "prediction_set_sha256": record["prediction_set_sha256"], "prediction_lock_sha256": prediction_lock_sha256,
              "protocol_sha256": protocol_sha256, "snapshot_v2_sha256": lock.fv1.SNAPSHOT_V2_SHA256,
              "gold_sha256": lock.FV2_GOLD_SHA256, "access": access, "provider_operations_after_gold_open": 0}
    runner.shared._write_json(Path(output_directory) / f"{EVALUATION_ID}.json", output)
    return output


def public_summary(output: Mapping[str, Any]) -> dict:
    """Recompute aggregates from evaluator output; no per-case rows, ids, text or findings."""
    summary = shared._summary([r["evaluation"] for r in output["rows"]])
    return {"artifact": EVALUATION_ID, "aggregate": summary,
            "annotation_conventions": {
                "cases_checked": sum(r["annotation_conventions"] is not None for r in output["rows"]),
                "counts": {rule: sum((r["annotation_conventions"] or {}).get("counts", {}).get(rule, 0)
                                     for r in output["rows"]) for rule in conventions.RULE_IDS}}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("fv2-directory", "prediction-directory", "output-directory", "protocol"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--protocol-sha256", required=True)
    parser.add_argument("--prediction-lock-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        output = score(fv2_directory=args.fv2_directory, prediction_directory=args.prediction_directory,
                       output_directory=args.output_directory, protocol_path=args.protocol,
                       protocol_sha256=args.protocol_sha256, prediction_lock_sha256=args.prediction_lock_sha256)
        print(json.dumps(public_summary(output), sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, lock.Fv2ProtocolError, Fv2ScoringError):
        print("FV2 scoring refused")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
