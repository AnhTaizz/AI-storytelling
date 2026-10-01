"""Story Extraction contract utilities v0 (STORY_EXTRACTION/v0, research baseline).

This module does NOT extract anything. It contains no NLP and calls no model.
It checks an extraction batch envelope, merges candidate Canonical Story records
into a base canonical document, and runs the frozen canonical_story/v0 validator.

    base canonical document (M3 source layer, optionally earlier canonical records)
        + candidate records of one batch
        -> deterministic merge
        -> frozen conformance validation

Contract: docs/research/m4/M4_STORY_EXTRACTION_CONTRACT_V0.md
"""
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.canonical_story.conformance_v0 import validate_document  # noqa: E402

CONTRACT_VERSION = "STORY_EXTRACTION/v0"
BATCH_VERSION = "STORY_EXTRACTION_BATCH/v0"
BATCH_SCHEMA_PATH = REPO_ROOT / "schemas/story_extraction/story_extraction_batch_v0.schema.json"
LOCATOR_KIND = "TEXT_RANGE_V0"

CANDIDATE_COLLECTIONS = ("evidence_refs", "mentions", "entities", "events", "temporal_anchors",
                         "propositions", "extraction_provenance", "assertions")
SOURCE_LAYER_COLLECTIONS = ("source_documents", "source_segments")
ALL_COLLECTIONS = SOURCE_LAYER_COLLECTIONS + CANDIDATE_COLLECTIONS


def canonical_json_bytes(obj: Any) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def document_sha256(document: Dict[str, Any]) -> str:
    """Identity of a base canonical document: SHA-256 of its deterministic serialization."""
    return hashlib.sha256(canonical_json_bytes(document)).hexdigest()


def _envelope_issues(batch: Any) -> List[str]:
    schema = json.loads(BATCH_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(batch), key=lambda e: list(e.absolute_path))
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in errors]


def merge(batch: Dict[str, Any], base_document: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic merge: base records keep their order; candidates are appended sorted by id."""
    merged = copy.deepcopy(base_document)
    for name in CANDIDATE_COLLECTIONS:
        merged[name] = list(merged[name]) + sorted(copy.deepcopy(batch["candidate_records"][name]),
                                                   key=lambda r: r["id"])
    return merged


def _position_key(position: Dict[str, Any]):
    return position["stream_id"], list(position["key"])


def _within(inner_start, inner_end, outer_start, outer_end) -> bool:
    return outer_start <= inner_start < inner_end <= outer_end


def validate_batch(batch: Any, base_document: Dict[str, Any], ingestion: Optional[Any] = None) -> Dict[str, Any]:
    """Validate one extraction batch against a base canonical document.

    `ingestion` is an optional M3 IngestionResult. When given, every passage input and
    every evidence span is re-derived from the exact source and compared.
    """
    checks = {name: [] for name in ("envelope", "scope", "evidence", "review_provenance", "ids", "canonical")}
    report: Dict[str, Any] = {"contract_version": CONTRACT_VERSION, "batch_version": BATCH_VERSION,
                              "source_text_verified": ingestion is not None}

    checks["envelope"] = _envelope_issues(batch)
    if checks["envelope"]:
        return _finish(report, checks, None)

    scope, process, records = batch["scope"], batch["process"], batch["candidate_records"]
    segments = {s["id"]: s for s in base_document["source_segments"]}
    as_of = scope["as_of_position"]

    # ---- scope
    if scope["story_id"] != base_document["story"]["id"]:
        checks["scope"].append("STORY_MISMATCH: scope.story_id differs from the base document")
    if batch["base_canonical_identity"]["base_document_sha256"] != document_sha256(base_document):
        checks["scope"].append("BASE_IDENTITY_MISMATCH: batch was not produced against this base document")
    if as_of["stream_id"] != base_document["story"]["discourse_stream_id"]:
        checks["scope"].append("STREAM_MISMATCH: as_of_position is not in the story's discourse stream")
    prior_records = any(base_document[name] for name in CANDIDATE_COLLECTIONS)
    declared_prior = scope["prior_canonical_context"]["kind"] == "BASE_DOCUMENT_RECORDS"
    if prior_records != declared_prior:
        checks["scope"].append("PRIOR_CONTEXT_MISDECLARED: prior_canonical_context does not match the base document")
    eligible: Dict[str, List[Dict[str, Any]]] = {}
    for index, item in enumerate(scope["passage_inputs"]):
        ref = item["passage_ref"]
        segment = segments.get(ref["segment_id"])
        if segment is None:
            checks["scope"].append(f"UNKNOWN_SEGMENT: passage input {index} cites a segment outside the base document")
            continue
        if _position_key(ref["position"])[1] > list(as_of["key"]):
            checks["scope"].append(f"INPUT_AFTER_AS_OF: passage input {index} lies after the as-of boundary")
        if ingestion is not None:
            try:
                ingestion.verify_passage_ref(ref)
            except Exception as exc:  # fail closed on any mismatch with the exact source
                checks["scope"].append(f"INVALID_PASSAGE_REF: passage input {index}: {exc}")
        if item["use"] == "EVIDENCE_ELIGIBLE":
            eligible.setdefault(ref["segment_id"], []).append(ref["span"])

    # ---- ids
    base_ids = {r["id"] for name in ALL_COLLECTIONS for r in base_document[name]} | {base_document["story"]["id"]}
    seen = set()
    for name in CANDIDATE_COLLECTIONS:
        for record in records[name]:
            if record["id"] in base_ids:
                checks["ids"].append(f"ID_COLLISION: {name} id {record['id']} already exists in the base document")
            if record["id"] in seen:
                checks["ids"].append(f"ID_COLLISION: id {record['id']} is used twice in the batch")
            seen.add(record["id"])

    # ---- evidence
    for record in records["evidence_refs"]:
        rid = record["id"]
        segment = segments.get(record.get("segment_id"))
        if segment is None:
            checks["evidence"].append(f"DANGLING_REFERENCE: evidence ref {rid} cites an unknown segment")
            continue
        span = record.get("span")
        if not isinstance(span, dict) or span.get("kind") != LOCATOR_KIND:
            checks["evidence"].append(f"SPAN_REQUIRED: evidence ref {rid} must carry an exact {LOCATOR_KIND} span")
            continue
        if "role" not in record:
            checks["evidence"].append(f"ROLE_REQUIRED: evidence ref {rid} has no evidence role")
        locator = segment["locator"]
        position = record.get("position", {})
        if position.get("stream_id") != segment["position"]["stream_id"] or \
                list(position.get("key", [])) != list(segment["position"]["key"]):
            checks["evidence"].append(f"POSITION_MISMATCH: evidence ref {rid} does not carry its segment's position")
        if list(segment["position"]["key"]) > list(as_of["key"]):
            checks["evidence"].append(f"EVIDENCE_AFTER_AS_OF: evidence ref {rid} lies after the as-of boundary")
        try:
            start, end = span["char_start"], span["char_end_exclusive"]
            inside_segment = span["source_sha256"] == locator["source_sha256"] and \
                _within(start, end, locator["char_start"], locator["char_end_exclusive"])
        except (KeyError, TypeError):
            inside_segment = False
        if not inside_segment:
            checks["evidence"].append(f"SPAN_OUTSIDE_SEGMENT: evidence ref {rid} is not an exact span of its segment")
            continue
        if not any(_within(start, end, s["char_start"], s["char_end_exclusive"])
                   for s in eligible.get(record["segment_id"], [])):
            checks["evidence"].append(
                f"EVIDENCE_OUTSIDE_SCOPE: evidence ref {rid} is not inside an EVIDENCE_ELIGIBLE passage input")
        if ingestion is not None:
            try:
                expected = ingestion.passage_ref(record["segment_id"], start - locator["char_start"],
                                                 end - locator["char_start"])["span"]
            except Exception as exc:
                expected = None
                checks["evidence"].append(f"SPAN_NOT_RESOLVABLE: evidence ref {rid}: {exc}")
            if expected is not None and expected != span:
                checks["evidence"].append(f"SPAN_MISMATCH: evidence ref {rid} does not match the exact source span")

    # ---- review and provenance
    method = process["method"]
    provenance_ids = set()
    for record in records["extraction_provenance"]:
        provenance_ids.add(record["id"])
        if record.get("method") != method:
            checks["review_provenance"].append(
                f"PROVENANCE_METHOD_MISMATCH: {record['id']} must have method {method}")
        if (record.get("process_id"), record.get("process_version")) != (process["process_id"],
                                                                         process["process_version"]):
            checks["review_provenance"].append(
                f"PROVENANCE_PROCESS_MISMATCH: {record['id']} does not name the batch process")
    for record in records["assertions"]:
        aid = record["id"]
        if record.get("extraction_provenance_id") not in provenance_ids:
            checks["review_provenance"].append(
                f"PROVENANCE_NOT_IN_BATCH: assertion {aid} must cite provenance created by this batch")
        review = record.get("review", {})
        state = review.get("state")
        if method == "AUTOMATED_EXTRACTION":
            if state != "UNREVIEWED" or "reviewer_kind" in review:
                checks["review_provenance"].append(
                    f"SELF_CERTIFICATION: automated assertion {aid} must be UNREVIEWED with no reviewer")
        elif state in ("CONFIRMED", "CORRECTED"):
            if review.get("reviewer_kind") != "HUMAN" or not process.get("human_review_record"):
                checks["review_provenance"].append(
                    f"UNATTESTED_REVIEW: assertion {aid} is {state} without a recorded human review")

    # ---- canonical conformance of the merged document
    merged = merge(batch, base_document)
    conformance = validate_document(merged)
    if not conformance["pass"]:
        for issue in conformance["structural"]["issues"]:
            checks["canonical"].append(f"STRUCTURAL: {issue}")
        for section, result in conformance["semantic"].items():
            for issue in result["issues"]:
                checks["canonical"].append(f"{section}: {issue}")
    return _finish(report, checks, merged)


def _finish(report: Dict[str, Any], checks: Dict[str, List[str]], merged: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    report["checks"] = {name: {"pass": not issues, "issues": issues} for name, issues in checks.items()}
    report["pass"] = all(not issues for issues in checks.values())
    report["merged_document_sha256"] = document_sha256(merged) if merged is not None and report["pass"] else None
    return report


def issue_codes(report: Dict[str, Any]) -> List[str]:
    """Sorted, de-duplicated issue codes of a validation report (text before the first colon)."""
    return sorted({issue.split(":", 1)[0] for check in report["checks"].values() for issue in check["issues"]})
