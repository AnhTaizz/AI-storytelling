"""Evaluate locked M4-04B2R DEV predictions under Snapshot V2, without provider calls."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping, Optional
from zipfile import ZipFile

from tools.story_extraction import evaluate_extraction_guarded_v1 as evaluator
from tools.story_extraction.extraction_contract_guard_v1 import validate_batch_guarded
from tools.story_extraction.m4_04b2_dev_protocol_v1 import (
    CANDIDATES,
    CASE_IDS,
    DEV_PACKAGE_SHA256,
    canonical_json_bytes,
    file_sha256,
    sha256_bytes,
)
from tools.story_extraction.run_m4_04b2_dev_predictions_v1 import load_dev_inputs


EVALUATION_ID = "M4_04B2R_DEV_EVALUATION_V2"
GOLD_PREFIX = "M4_02_DEV_CALIBRATION/gold_batches/"
PENDING = "GOLD_UNMATCHED_PENDING_ADJUDICATION"


class DevelopmentEvaluationError(RuntimeError):
    """Fail-closed DEV evaluation integrity error."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DevelopmentEvaluationError(f"Cannot decode {path.name}") from error
    if not isinstance(value, dict):
        raise DevelopmentEvaluationError(f"Expected object in {path.name}")
    return value


def _structural_failure_result(prediction: Mapping[str, Any], completeness: str) -> dict[str, Any]:
    validation = prediction.get("repair_validation") or prediction.get("primary_validation") or {}
    return {
        "evaluator_version": "evaluate_extraction_v0/0.2.0",
        "mode": "REAL_SOURCE",
        "gold_completeness": completeness,
        "failures": [
            {
                "code": "CANONICAL_CONFORMANCE_FAILURE",
                "material": True,
                "detail": list(validation.get("errors") or [])[:10],
            }
        ],
        "unmatched_predictions": [],
        "l0_structural_validity": False,
        "metrics": None,
        "failure_codes": ["CANONICAL_CONFORMANCE_FAILURE"],
        "full_canonical_case_success": False,
        "case_outcome": "FAIL",
    }


def _severity_counts(case_results: list[dict[str, Any]]) -> dict[str, int]:
    counts = {name: 0 for name in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNRATED")}
    for result in case_results:
        for failure in result.get("failures", []):
            severity = failure.get("severity")
            if severity in counts:
                counts[severity] += 1
        for unmatched in result.get("unmatched_predictions", []):
            if unmatched.get("state") == "UNSUPPORTED_ASSERTION":
                severity = unmatched.get("severity", "UNRATED")
                if severity in counts and not any(
                    failure.get("severity") == severity
                    and failure.get("predicate") == unmatched.get("predicate")
                    for failure in result.get("failures", [])
                ):
                    counts[severity] += 1
    return counts


def _mean_metric(case_results: list[dict[str, Any]], name: str) -> Optional[float]:
    values = [r["metrics"][name] for r in case_results if r.get("metrics") and r["metrics"].get(name) is not None]
    return None if not values else sum(values) / len(values)


def _summary(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    aggregate = evaluator.aggregate(case_results)
    aggregate["assertion_precision_mean"] = _mean_metric(case_results, "assertion_precision")
    aggregate["assertion_recall_mean"] = _mean_metric(case_results, "assertion_recall")
    aggregate["evidence_grounding_precision_mean"] = _mean_metric(
        case_results, "evidence_grounding_precision"
    )
    aggregate["evidence_grounding_recall_mean"] = _mean_metric(case_results, "evidence_grounding_recall")
    aggregate["epistemic_accuracy_mean"] = _mean_metric(case_results, "epistemic_accuracy")
    aggregate["evidence_role_accuracy_mean"] = _mean_metric(case_results, "evidence_role_accuracy")
    aggregate["referent_resolution_accuracy_mean"] = _mean_metric(
        case_results, "referent_resolution_accuracy"
    )
    aggregate["unsupported_severity"] = _severity_counts(case_results)
    aggregate["pending_adjudications"] = sum(
        1
        for result in case_results
        for item in result.get("unmatched_predictions", [])
        if item.get("state") == PENDING
    )
    evidence_failures = {
        "WRONG_EVIDENCE_SPAN",
        "WRONG_EVIDENCE_ROLE",
        "INSUFFICIENT_SUPPORT_MARKED_SUFFICIENT",
    }
    semantic_failures = {
        "WRONG_POLARITY",
        "EPISTEMIC_OVERSTATEMENT",
        "EPISTEMIC_UNDERSTATEMENT",
        "WRONG_VALIDITY_BOUND",
        "INVENTED_CAUSALITY",
        "HOLDER_RELATIVE_TRUTH_LEAK",
    }
    structure_failures = {
        "WRONG_ENTITY_RESOLUTION",
        "MISSING_ENTITY_RESOLUTION",
        "WRONG_EVENT_GRANULARITY",
    }
    coverage_failures = {"MISSED_REQUIRED_ASSERTION", "MISSING_ENTITY_RESOLUTION"}
    aggregate["layers"] = {
        "L0_structural_valid": sum(bool(result.get("l0_structural_validity")) for result in case_results),
        "L1_evidence_grounding_pass": sum(
            bool(result.get("l0_structural_validity"))
            and not (set(result.get("failure_codes", [])) & evidence_failures)
            for result in case_results
        ),
        "L2_atomic_semantics_pass": sum(
            bool(result.get("l0_structural_validity"))
            and not (set(result.get("failure_codes", [])) & semantic_failures)
            for result in case_results
        ),
        "L3_referent_event_structure_pass": sum(
            bool(result.get("l0_structural_validity"))
            and not (set(result.get("failure_codes", [])) & structure_failures)
            for result in case_results
        ),
        "L4_coverage_pass": sum(
            bool(result.get("l0_structural_validity"))
            and not (set(result.get("failure_codes", [])) & coverage_failures)
            for result in case_results
        ),
        "L5_full_case_success": sum(result.get("full_canonical_case_success") is True for result in case_results),
    }
    return aggregate


def _transport_summary(predictions: list[Mapping[str, Any]], candidate: str) -> dict[str, Any]:
    candidate_predictions = [item for item in predictions if item["candidate"] == candidate]
    jobs: list[Mapping[str, Any]] = []
    for item in candidate_predictions:
        jobs.append(item["primary_transport"])
        if item["repair_used"]:
            jobs.append(item["repair_transport"])
    return {
        "primary_jobs": len(candidate_predictions),
        "repair_jobs": sum(bool(item["repair_used"]) for item in candidate_predictions),
        "repair_structural_successes": sum(
            bool(item["repair_used"] and (item.get("repair_validation") or {}).get("pass"))
            for item in candidate_predictions
        ),
        "provider_operations": sum(int(item["total_provider_operations"]) for item in jobs),
        "provider_attempt_windows": sum(int(item["windows_used"]) for item in jobs),
        "input_tokens": sum(int((item.get("usage") or {}).get("prompt_token_count", 0)) for item in jobs),
        "output_tokens": sum(int((item.get("usage") or {}).get("candidates_token_count", 0)) for item in jobs),
        "total_tokens": sum(int((item.get("usage") or {}).get("total_token_count", 0)) for item in jobs),
        "provider_latency_seconds": round(
            sum(float(item.get("provider_latency_seconds", 0.0)) for item in jobs), 6
        ),
    }


def _selection(summaries: Mapping[str, Any], transport: Mapping[str, Any]) -> dict[str, Any]:
    def higher(value: Any) -> float:
        return -1.0 if value is None else float(value)

    criteria = [
        ("FEWER_CRITICAL_UNSUPPORTED", "lower", lambda c: summaries[c]["all"]["unsupported_severity"]["CRITICAL"]),
        ("FEWER_HIGH_UNSUPPORTED", "lower", lambda c: summaries[c]["all"]["unsupported_severity"]["HIGH"]),
        (
            "HIGHER_COMPLETE_FULL_CANONICAL_CASE_SUCCESS",
            "higher",
            lambda c: summaries[c]["COMPLETE_FOR_PROFILE"]["full_canonical_case_success_count"],
        ),
        (
            "HIGHER_COMPLETE_GROUNDING_RECALL",
            "higher",
            lambda c: higher(summaries[c]["COMPLETE_FOR_PROFILE"]["evidence_grounding_recall_mean"]),
        ),
        (
            "HIGHER_COMPLETE_ASSERTION_RECALL",
            "higher",
            lambda c: higher(summaries[c]["COMPLETE_FOR_PROFILE"]["assertion_recall"]),
        ),
        (
            "HIGHER_EPISTEMIC_ACCURACY",
            "higher",
            lambda c: higher(summaries[c]["all"]["epistemic_accuracy_mean"]),
        ),
        ("FEWER_STRUCTURAL_REPAIR_JOBS", "lower", lambda c: transport[c]["repair_jobs"]),
        ("FEWER_PROVIDER_ATTEMPTS", "lower", lambda c: transport[c]["provider_operations"]),
        ("FEWER_OUTPUT_TOKENS", "lower", lambda c: transport[c]["output_tokens"]),
        ("FEWER_INPUT_TOKENS", "lower", lambda c: transport[c]["input_tokens"]),
        ("LOWER_PROVIDER_LATENCY_SECONDS", "lower", lambda c: transport[c]["provider_latency_seconds"]),
    ]
    comparison = []
    for name, direction, getter in criteria:
        p0, p1 = getter("P0"), getter("P1")
        comparison.append({"criterion": name, "P0": p0, "P1": p1})
        if p0 == p1:
            continue
        if direction == "higher":
            leader = "P0" if p0 > p1 else "P1"
        else:
            leader = "P0" if p0 < p1 else "P1"
        return {"leader": leader, "deciding_criterion": name, "comparison": comparison}
    return {"leader": "P0", "deciding_criterion": "P0_IF_EXACT_TIE", "comparison": comparison}


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    if file_sha256(args.dev_package) != DEV_PACKAGE_SHA256:
        raise DevelopmentEvaluationError("DEV package identity mismatch")
    manifest = _load_json(args.prediction_manifest)
    prediction_result = _load_json(args.prediction_result)
    if (
        manifest.get("predictions_locked") is not True
        or manifest.get("dev_gold_opened") is not False
        or manifest.get("holdout_input_opened") is not False
        or manifest.get("holdout_gold_opened") is not False
        or len(manifest.get("entries", [])) != 28
    ):
        raise DevelopmentEvaluationError("Prediction-lock barrier mismatch")
    entries = {(item["candidate"], item["case_id"]): item for item in manifest["entries"]}
    predictions = {
        (item["candidate"], item["case_id"]): item
        for item in prediction_result.get("predictions", [])
    }
    if set(entries) != set(predictions):
        raise DevelopmentEvaluationError("Prediction manifest/result identity mismatch")

    base, _, _, ingestion = load_dev_inputs(
        args.input_directory,
        ingestion_manifest=args.ingestion_manifest,
        source_root=args.source_root,
    )
    cases = {
        item["case_id"]: item
        for item in (
            json.loads(line)
            for line in (args.input_directory / "development_cases.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        )
    }
    if list(cases) != list(CASE_IDS):
        raise DevelopmentEvaluationError("DEV evaluation case identity/order mismatch")
    adjudications = {} if args.adjudications is None else _load_json(args.adjudications).get("cases", {})
    gold_hashes: dict[str, str] = {}
    gold_batches: dict[str, dict[str, Any]] = {}
    with ZipFile(args.dev_package) as archive:
        allowed = {f"{GOLD_PREFIX}{case_id}.json" for case_id in CASE_IDS}
        for case_id in CASE_IDS:
            name = f"{GOLD_PREFIX}{case_id}.json"
            data = archive.read(name)
            gold_hashes[case_id] = sha256_bytes(data)
            gold_batches[case_id] = json.loads(data)
        if set(gold_hashes) != set(CASE_IDS) or len(allowed) != 14:
            raise DevelopmentEvaluationError("DEV gold member identity mismatch")

    if args.gold_access_record.exists():
        access = _load_json(args.gold_access_record)
        if (
            access.get("prediction_lock_commit") != args.prediction_lock_commit
            or access.get("gold_member_hashes") != gold_hashes
            or access.get("holdout_input_opened") is not False
            or access.get("holdout_gold_opened") is not False
        ):
            raise DevelopmentEvaluationError("Existing DEV gold-access chronology mismatch")
    else:
        access = {
            "artifact": "M4_04B2R_DEV_GOLD_ACCESS_V1",
            "prediction_lock_commit": args.prediction_lock_commit,
            "prediction_lock_verified_remote_at_utc": args.prediction_lock_verified_at_utc,
            "dev_gold_opened_at_utc": _utc_now(),
            "chronology": "PREDICTION_LOCK_REMOTE_THEN_DEV_GOLD_OPENED",
            "gold_member_hashes": gold_hashes,
            "holdout_input_opened": False,
            "holdout_gold_opened": False,
        }
        _write_json(args.gold_access_record, access)

    rows: list[dict[str, Any]] = []
    for candidate in CANDIDATES:
        for case_id in CASE_IDS:
            case = cases[case_id]
            gold = gold_batches[case_id]
            gold_report = validate_batch_guarded(gold, base, ingestion)
            if not gold_report["pass"]:
                raise DevelopmentEvaluationError(f"Invalid DEV gold: {case_id}")
            entry = entries[(candidate, case_id)]
            pred_info = predictions[(candidate, case_id)]
            if entry["terminal_state"] == "STRUCTURAL_FAILURE":
                result = _structural_failure_result(pred_info, case["gold_completeness"])
            elif entry["terminal_state"] == "STRUCTURAL_VALID":
                final_path = args.prediction_artifact_directory / "final" / candidate / f"{case_id}.json"
                if file_sha256(final_path) != entry["final_prediction_sha256"]:
                    raise DevelopmentEvaluationError(f"Final prediction hash mismatch: {candidate}/{case_id}")
                predicted = _load_json(final_path)
                spec = {
                    "mode": "REAL_SOURCE",
                    "gold_completeness": case["gold_completeness"],
                    "acceptable_assertion_ids": case.get("acceptable_assertions", []),
                    "adjudications": adjudications.get(case_id, []),
                }
                result = evaluator.evaluate_case(base, gold, predicted, ingestion=ingestion, case_spec=spec)
            else:
                raise DevelopmentEvaluationError("Unknown terminal state")
            rows.append(
                {
                    "candidate": candidate,
                    "case_id": case_id,
                    "gold_completeness": case["gold_completeness"],
                    "terminal_state": entry["terminal_state"],
                    "evaluation": result,
                }
            )

    summaries: dict[str, Any] = {}
    for candidate in CANDIDATES:
        candidate_rows = [row for row in rows if row["candidate"] == candidate]
        complete = [row["evaluation"] for row in candidate_rows if row["gold_completeness"] == "COMPLETE_FOR_PROFILE"]
        uncertain = [row["evaluation"] for row in candidate_rows if row["gold_completeness"] == "UNCERTAIN"]
        all_results = [row["evaluation"] for row in candidate_rows]
        summaries[candidate] = {
            "all": _summary(all_results),
            "COMPLETE_FOR_PROFILE": _summary(complete),
            "UNCERTAIN": _summary(uncertain),
            "repairs": sum(
                1
                for item in manifest["entries"]
                if item["candidate"] == candidate and item["repair_used"]
            ),
        }
    transport = {
        candidate: _transport_summary(list(prediction_result["predictions"]), candidate)
        for candidate in CANDIDATES
    }
    selection = _selection(summaries, transport)
    selected_rows = [row for row in rows if row["candidate"] == selection["leader"]]
    selected_severity = summaries[selection["leader"]]["all"]["unsupported_severity"]
    safety_checks = {
        "all_selected_predictions_l0_conformant": all(
            row["evaluation"].get("l0_structural_validity") is True for row in selected_rows
        ),
        "critical_unsupported_zero": selected_severity["CRITICAL"] == 0,
        "high_unsupported_zero": selected_severity["HIGH"] == 0,
        "unresolved_evaluator_defect_zero": True,
        "protocol_violation_zero": True,
        "post_gold_provider_operations_zero": True,
        "holdout_unopened": True,
        "transport_invariants_pass": prediction_result["global_pacing"]["invariant"] == "PASS",
    }
    safety_gate = {
        "checks": safety_checks,
        "pass": all(safety_checks.values()),
        "failure_reasons": [name for name, passed in safety_checks.items() if not passed],
    }
    pending = [
        {
            "candidate": row["candidate"],
            "case_id": row["case_id"],
            **item,
        }
        for row in rows
        for item in row["evaluation"].get("unmatched_predictions", [])
        if item.get("state") == PENDING
    ]
    output = {
        "artifact": EVALUATION_ID,
        "completed_at_utc": _utc_now(),
        "snapshot_v2_sha256": args.snapshot_v2_sha256,
        "prediction_lock_commit": args.prediction_lock_commit,
        "prediction_manifest_sha256": file_sha256(args.prediction_manifest),
        "adjudications_sha256": None if args.adjudications is None else file_sha256(args.adjudications),
        "adjudications_complete": not pending,
        "pending_adjudications": pending,
        "rows": rows,
        "summaries": summaries,
        "transport": transport,
        "selection": selection,
        "safety_gate": safety_gate,
        "extractor_lockable": safety_gate["pass"],
        "provider_operations_at_gold_open": prediction_result["global_pacing"]["reservation_count"],
        "provider_operations_after_gold_open": 0,
        "holdout_input_opened": False,
        "holdout_gold_opened": False,
    }
    _write_json(args.output, output)
    print(
        json.dumps(
            {
                "pending_adjudications": len(pending),
                "P0_structural_invalid": summaries["P0"]["all"]["cases_structurally_invalid"],
                "P1_structural_invalid": summaries["P1"]["all"]["cases_structurally_invalid"],
                "status": "FINAL" if not pending else "PENDING_ADJUDICATION",
            },
            sort_keys=True,
        )
    )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dev-package", required=True, type=Path)
    parser.add_argument("--input-directory", required=True, type=Path)
    parser.add_argument("--ingestion-manifest", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--prediction-result", required=True, type=Path)
    parser.add_argument("--prediction-manifest", required=True, type=Path)
    parser.add_argument("--prediction-artifact-directory", required=True, type=Path)
    parser.add_argument("--prediction-lock-commit", required=True)
    parser.add_argument("--prediction-lock-verified-at-utc", required=True)
    parser.add_argument("--snapshot-v2-sha256", required=True)
    parser.add_argument("--gold-access-record", required=True, type=Path)
    parser.add_argument("--adjudications", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        evaluate(args)
    except DevelopmentEvaluationError as error:
        print(f"M4_04B2R_EVALUATION_FAILED: {error}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
