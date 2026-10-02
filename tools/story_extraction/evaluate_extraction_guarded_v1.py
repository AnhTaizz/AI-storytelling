"""Snapshot-V2 entry point: Guard V1 plus the otherwise unchanged V1 evaluator."""

from __future__ import annotations

from typing import Any, Optional

from tools.story_extraction import evaluate_extraction_v0 as frozen
from tools.story_extraction.extraction_contract_guard_v1 import validate_batch_guarded


EVALUATOR_VERSION = "evaluate_extraction_guarded_v1/1.0.0"
aggregate = frozen.aggregate


def evaluate_case(
    base_document: dict[str, Any],
    gold_batch: dict[str, Any],
    predicted_batch: dict[str, Any],
    acceptable_gold_assertion_ids=(),
    ingestion: Optional[Any] = None,
    case_spec: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Return frozen V1 output for safe inputs; fail closed before its unsafe path."""
    gold_report = validate_batch_guarded(gold_batch, base_document, ingestion)
    if not gold_report["pass"]:
        raise ValueError(f"gold batch is not valid: {gold_report['checks']}")
    pred_report = validate_batch_guarded(predicted_batch, base_document, ingestion)
    if pred_report["pass"]:
        return frozen.evaluate_case(
            base_document,
            gold_batch,
            predicted_batch,
            acceptable_gold_assertion_ids=acceptable_gold_assertion_ids,
            ingestion=ingestion,
            case_spec=case_spec,
        )
    result: dict[str, Any] = {
        "evaluator_version": frozen.EVALUATOR_VERSION,
        "mode": (case_spec or {}).get("mode", "SYNTHETIC_COMPLETE"),
        "failures": [
            {
                "code": "CANONICAL_CONFORMANCE_FAILURE",
                "material": True,
                "detail": [
                    issue
                    for check in pred_report["checks"].values()
                    for issue in check["issues"]
                ][:10],
            }
        ],
        "unmatched_predictions": [],
        "l0_structural_validity": False,
        "metrics": None,
        "failure_codes": ["CANONICAL_CONFORMANCE_FAILURE"],
        "full_canonical_case_success": False,
        "case_outcome": "FAIL",
    }
    if result["mode"] == "REAL_SOURCE":
        result["gold_completeness"] = (case_spec or {}).get(
            "gold_completeness", "COMPLETE_FOR_PROFILE"
        )
    return result
