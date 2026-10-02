"""Fail-closed structural guard for the frozen STORY_EXTRACTION/v0 validator.

This module is a prospective robustness correction.  It never rewrites a batch:
safe passage-input shapes are delegated unchanged to the frozen V1 validator,
while shapes that V1 would dereference unsafely become deterministic failures.
"""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any, Optional

from tools.story_extraction.extraction_contract_v0 import (
    BATCH_VERSION,
    CONTRACT_VERSION,
    validate_batch as validate_batch_v1,
)


GUARD_ID = "M4_EXTRACTION_VALIDATION_GUARD_V1"
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
CHECK_NAMES = ("envelope", "scope", "evidence", "review_provenance", "ids", "canonical")


class UnexpectedValidatorInternalError(RuntimeError):
    """Frozen V1 raised after every known unsafe passage shape was excluded."""


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _passage_input_issues(batch: Any) -> list[str]:
    """Return ordered issues for only the fields V1 dereferences without guards."""
    if not isinstance(batch, Mapping):
        return []
    scope = batch.get("scope")
    if not isinstance(scope, Mapping):
        return []
    inputs = scope.get("passage_inputs")
    if not isinstance(inputs, list):
        return []

    issues: list[str] = []
    for index, item in enumerate(inputs):
        prefix = f"scope.passage_inputs[{index}].passage_ref"
        if not isinstance(item, Mapping):
            continue  # Frozen envelope validation handles this before dereference.
        ref = item.get("passage_ref")
        if not isinstance(ref, Mapping):
            issues.append(f"MALFORMED_PASSAGE_INPUT: {prefix} must be an object")
            continue
        if ref.get("kind") != "SOURCE_PASSAGE_REF_V0":
            issues.append(f"MALFORMED_PASSAGE_INPUT: {prefix}.kind must be SOURCE_PASSAGE_REF_V0")
        segment_id = ref.get("segment_id")
        if not isinstance(segment_id, str) or ID_PATTERN.fullmatch(segment_id) is None:
            issues.append(f"MALFORMED_PASSAGE_INPUT: {prefix}.segment_id must be a valid non-empty id")

        position = ref.get("position")
        if not isinstance(position, Mapping):
            issues.append(f"MALFORMED_PASSAGE_INPUT: {prefix}.position must be an object")
        else:
            stream_id = position.get("stream_id")
            if not isinstance(stream_id, str) or ID_PATTERN.fullmatch(stream_id) is None:
                issues.append(f"MALFORMED_PASSAGE_INPUT: {prefix}.position.stream_id must be a valid id")
            key = position.get("key")
            if not (
                isinstance(key, list)
                and 1 <= len(key) <= 8
                and all(_is_int(value) and value >= 0 for value in key)
            ):
                issues.append(
                    f"MALFORMED_PASSAGE_INPUT: {prefix}.position.key must be a non-empty integer array"
                )

        span = ref.get("span")
        if not isinstance(span, Mapping):
            issues.append(f"MALFORMED_PASSAGE_INPUT: {prefix}.span must be an object")
            continue
        if span.get("kind") != "TEXT_RANGE_V0":
            issues.append(f"MALFORMED_PASSAGE_INPUT: {prefix}.span.kind must be TEXT_RANGE_V0")
        source_sha = span.get("source_sha256")
        if not isinstance(source_sha, str) or SHA256_PATTERN.fullmatch(source_sha) is None:
            issues.append(f"MALFORMED_PASSAGE_INPUT: {prefix}.span.source_sha256 must be lowercase SHA-256")
        start = span.get("char_start")
        end = span.get("char_end_exclusive")
        if not _is_int(start):
            issues.append(f"MALFORMED_PASSAGE_INPUT: {prefix}.span.char_start must be an integer")
        if not _is_int(end):
            issues.append(f"MALFORMED_PASSAGE_INPUT: {prefix}.span.char_end_exclusive must be an integer")
        if _is_int(start) and _is_int(end) and start >= end:
            issues.append(
                f"MALFORMED_PASSAGE_INPUT: {prefix}.span must satisfy char_start < char_end_exclusive"
            )
    return issues


def _failure_report(issues: list[str], ingestion: Optional[Any]) -> dict[str, Any]:
    checks = {name: {"pass": True, "issues": []} for name in CHECK_NAMES}
    checks["scope"] = {"pass": False, "issues": issues}
    return {
        "contract_version": CONTRACT_VERSION,
        "batch_version": BATCH_VERSION,
        "source_text_verified": ingestion is not None,
        "checks": checks,
        "pass": False,
        "merged_document_sha256": None,
    }


def validate_batch_guarded(
    batch: Any,
    base_document: dict[str, Any],
    ingestion: Optional[Any] = None,
) -> dict[str, Any]:
    """Preflight known unsafe shapes, then delegate unchanged to frozen V1."""
    issues = _passage_input_issues(batch)
    if issues:
        return _failure_report(issues, ingestion)
    try:
        return validate_batch_v1(batch, base_document, ingestion)
    except Exception as error:
        raise UnexpectedValidatorInternalError(
            "Frozen extraction validator raised after Guard V1 structural preflight"
        ) from error
