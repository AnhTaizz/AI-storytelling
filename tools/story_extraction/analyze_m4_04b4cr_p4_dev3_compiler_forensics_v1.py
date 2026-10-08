"""Offline forensics of the locked M4-04B4C P4 DEV3 compiler failures (M4-04B4CR).

Read-only. It reproduces the locked result, replays every locked response through the
unchanged Draft V1.1 validator and compiler, and explains each compiler failure with
structural facts only. It calls no provider, opens no gold, scores nothing and changes
no prediction, prompt, schema, compiler or validator.

Instrumentation: the frozen compiler reports a canonical conformance failure as one
generic blocker. To see which check failed, the validator call inside the compiler is
wrapped by a recorder for the duration of one replay. The recorder calls the real
validator and returns its report unchanged, so the authoritative result is untouched.

Counterfactuals are diagnostics on in-memory copies of failed drafts. They are never
predictions, are never written into the prediction root and never enter a count of
original results.

Public output holds codes, counts, booleans, hashes and fixed analyst sentences. It holds
no quote, passage, offset, handle or model-written value.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
import itertools
import json
from pathlib import Path
import re
from typing import Any, Mapping, Optional, Sequence
from unittest import mock

from jsonschema import Draft202012Validator
import yaml

from tools.canonical_story.conformance_v0 import load_registry
from tools.story_extraction import draft_compiler_v1 as compiler_v1
from tools.story_extraction import draft_compiler_v1_1 as compiler_v1_1
from tools.story_extraction import m4_04b4a_p4_output_contract_v1 as contract
from tools.story_extraction import m4_04b4br_p4_protocol_v2 as protocol
from tools.story_extraction import run_m4_04b4c_p4_dev3_tuning_v1 as b4c
from tools.story_extraction.run_m4_04b2_dev_predictions_v1 import _write_bytes_atomic
from tools.story_extraction.run_m4_04b3g_dev3_p3_predictions_v1 import CaseInput


TASK_ID = "M4-04B4CR"
ANALYZER_ID = "M4_04B4CR_P4_DEV3_COMPILER_FORENSICS_ANALYZER_V1"
ANALYZER_PATH = "tools/story_extraction/analyze_m4_04b4cr_p4_dev3_compiler_forensics_v1.py"
REPO_ROOT = b4c.REPO_ROOT
EXPECTED_BASE_COMMIT = "30436aca8d19fff16b61c3385a169568df575008"
PUBLIC_RECORD_PATH = REPO_ROOT / "benchmarks/m4_extraction/M4_04B4CR_P4_DEV3_COMPILER_FORENSICS.yaml"
DEFAULT_FORENSIC_ROOT = REPO_ROOT / ".local/m4_04b4cr_p4_compiler_forensics"
NON_PREDICTION_LABEL = "NON_PREDICTION_DIAGNOSTIC_ONLY"
COUNTERFACTUAL_COMBINATION_LIMIT = 256

STATUS_COMPLETE = "M4_04B4CR_COMPILER_FORENSICS_COMPLETE"
STATUS_INTEGRITY_DEFECT = "M4_04B4CR_LOCKED_RESULT_INTEGRITY_DEFECT"
STATUS_REPRODUCTION_DEFECT = "M4_04B4CR_COMPILATION_REPRODUCTION_DEFECT"
STATUS_PROTOCOL_VIOLATION = "M4_04B4CR_PROTOCOL_VIOLATION"
STATUS_FAIL_CLOSED = "M4_04B4CR_STOPPED_FAIL_CLOSED"

PHASES = (("PRIMARY", "primary", "raw_primary"), ("REPAIR_1", "repair_1", "raw_repair"))
MASK = "<UNRECOGNIZED_KEY>"
_TOKEN = re.compile(r"^[A-Za-z0-9_.:/<>-]{1,200}$")
_GENERATED_ID = re.compile(r"draftv1-[0-9a-f]{24}-([A-Za-z0-9_]+(?:-[A-Za-z0-9_]+)*)")
PROSE: set[str] = set()


def _p(text: str) -> str:
    """Register one fixed analyst sentence. Only registered sentences may be published as prose."""
    PROSE.add(text)
    return text


class ForensicsError(RuntimeError):
    """A fail-closed forensic error with no private text."""


class IntegrityDefect(ForensicsError):
    """A locked artifact or identity does not match."""


class ReproductionDefect(ForensicsError):
    """A locked compilation outcome does not reproduce."""


canonical_json_bytes = protocol.canonical_json_bytes
sha256_bytes = protocol.sha256_bytes


# ---------------------------------------------------------------------------
# Locked result verification
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise IntegrityDefect("A locked artifact is missing or unreadable: " + path.name) from error


def verify_locked_result(
    *,
    private_root: Path,
    input_archive: Path,
    expected_input_sha256: str = b4c.DEV3_INPUT_SHA256,
    prediction_lock_path: Optional[Path] = None,
) -> tuple[dict[str, Any], list[CaseInput], dict[str, Any]]:
    """Reproduce the integrity of the locked run before anything is interpreted."""
    prediction_lock_path = b4c.PREDICTION_LOCK_PATH if prediction_lock_path is None else prediction_lock_path
    if any("gold" in part.lower() or "holdout" in part.lower() for part in input_archive.parts):
        raise ForensicsError("A gold or holdout path is not accepted")
    try:
        _, lock_sha256 = b4c.locked_experiment()
        with mock.patch.object(b4c, "PREDICTION_LOCK_PATH", prediction_lock_path):
            verification = b4c.verify_run(
                input_archive=input_archive, private_root=private_root, expected_input_sha256=expected_input_sha256
            )
        layout = b4c.private_layout(private_root)
        cases = b4c.load_p4_case_inputs(input_archive, layout["input"], expected_input_sha256=expected_input_sha256)
    except b4c.P4Dev3Error as error:
        raise IntegrityDefect("The locked run failed its integrity check: " + str(error)) from error
    result = _read_json(layout["root"] / f"{b4c.TUNING_RESULT_ID}.json")
    manifest = _read_json(layout["root"] / f"{b4c.PREDICTION_MANIFEST_ID}.json")
    try:
        public_lock = yaml.safe_load(prediction_lock_path.read_text(encoding="utf-8"))
        published = b4c.validate_public_prediction_lock(public_lock, input_sha256=expected_input_sha256)
    except (OSError, yaml.YAMLError, b4c.P4Dev3Error) as error:
        raise IntegrityDefect("The public prediction lock is unavailable or invalid") from error

    # Independent rebuild of the prediction set from the artifact files themselves.
    identities = []
    counts = Counter()
    for case, item in zip(cases, result["predictions"]):
        attempts = {}
        for phase_label, phase, folder in PHASES:
            raw_path = layout[folder] / f"{case.case_id}.txt"
            if not raw_path.exists():
                continue
            raw = raw_path.read_bytes()
            draft_path = layout["drafts"] / f"{case.case_id}_{phase}.json"
            if phase == "primary":
                spec = protocol.build_primary_spec(case.case_id, case.prepared_input)
            else:
                diagnostic = _read_json(layout["failures"] / f"{case.case_id}_primary_diagnostic.json")
                primary_raw = (layout["raw_primary"] / f"{case.case_id}.txt").read_bytes().decode("utf-8")
                spec = protocol.build_repair_spec(case.case_id, case.prepared_input, primary_raw, diagnostic)
            attempts[phase] = {
                "job_id": spec.job_id,
                "fingerprint": spec.request_fingerprint,
                "raw_sha256": sha256_bytes(raw),
                "draft_sha256": sha256_bytes(draft_path.read_bytes()) if draft_path.exists() else None,
            }
            counts["raw_responses"] += 1
            counts["parsed_drafts"] += draft_path.exists()
            counts["diagnostics"] += (layout["failures"] / f"{case.case_id}_{phase}_diagnostic.json").exists()
        compiled_path = layout["compiled"] / f"{case.case_id}.json"
        failure_path = layout["failures"] / f"{case.case_id}.json"
        counts["compiled_batches"] += compiled_path.exists()
        counts["terminal_failure_records"] += failure_path.exists()
        counts["case_results"] += (layout["case_results"] / f"{case.case_id}.json").exists()
        last = attempts.get("repair_1", attempts["primary"])
        repair = attempts.get("repair_1")
        identities.append({
            "case_id": case.case_id,
            "protocol_sha256": protocol.PROTOCOL_SHA256,
            "experiment_lock_sha256": lock_sha256,
            "primary_request_fingerprint": attempts["primary"]["fingerprint"],
            "primary_response_sha256": attempts["primary"]["raw_sha256"],
            "repair_used": repair is not None,
            "repair_request_fingerprint": None if repair is None else repair["fingerprint"],
            "repair_response_sha256": None if repair is None else repair["raw_sha256"],
            "terminal_status": item["terminal_status"],
            "terminal_draft_sha256": last["draft_sha256"],
            "compiled_batch_sha256": sha256_bytes(compiled_path.read_bytes()) if compiled_path.exists() else None,
            "terminal_failure_sha256": sha256_bytes(failure_path.read_bytes()) if failure_path.exists() else None,
            "durable_job_success_identities": [
                {"job_id": entry["job_id"], "response_sha256": entry["raw_sha256"]} for entry in attempts.values()
            ],
        })
    counts["durable_checkpoints"] = len(list((layout["checkpoints"] / "jobs").glob("*.json")))
    try:
        rebuilt = b4c.prediction_set_sha256(identities, lock_sha256, expected_input_sha256)
    except b4c.P4Dev3Error as error:
        raise IntegrityDefect("The prediction set cannot be rebuilt from the artifacts") from error
    if not (rebuilt == result["prediction_set_sha256"] == manifest["prediction_set_sha256"] == published
            == verification["prediction_set_sha256"]):
        raise IntegrityDefect("The rebuilt prediction set differs from the locked prediction set")
    reproduction = {
        "experiment_lock_sha256": lock_sha256,
        "protocol_sha256": protocol.protocol_sha256(),
        "adapter_sha256": protocol.normalized_file_sha256(REPO_ROOT / b4c.ADAPTER_PATH),
        "adapter_unchanged_since_the_run": result["adapter_sha256"]
        == protocol.normalized_file_sha256(REPO_ROOT / b4c.ADAPTER_PATH),
        "b4c_integrity_checks_passed": len(verification["checks"]),
        "b4c_integrity_checks_all_pass": all(verification["checks"].values()),
        "artifact_counts": {name: int(counts[name]) for name in (
            "raw_responses", "parsed_drafts", "compiled_batches", "terminal_failure_records", "diagnostics",
            "case_results", "durable_checkpoints")},
        "prediction_set_sha256_rebuilt_from_artifact_files": rebuilt,
        "prediction_set_matches_private_result_manifest_and_public_lock": True,
        "real_provider_operations_recorded": result["operations"]["real_provider_operations"],
        "operation_budget": result["operations"]["operation_budget"],
        "provider_operations_during_forensics": 0,
    }
    if not reproduction["adapter_unchanged_since_the_run"] or not reproduction["b4c_integrity_checks_all_pass"]:
        raise IntegrityDefect("The locked adapter or an integrity check differs")
    return reproduction, cases, {"layout": layout, "result": result, "lock_sha256": lock_sha256}


# ---------------------------------------------------------------------------
# Replay of every locked attempt through the unchanged compiler
# ---------------------------------------------------------------------------

def compile_with_recorder(draft: Any, context: Any) -> tuple[Optional[dict], list[dict[str, str]], list[dict]]:
    """Run the unchanged V1.1 compiler once and record what its canonical validator reported.

    Returns the batch or None, the raw structural blockers and the validator reports. The
    recorder returns the real report unchanged; the compiler's own verdict is authoritative.
    """
    reports: list[dict] = []
    real = compiler_v1.validate_batch_guarded

    def recorder(batch, base_document, ingestion):
        report = real(batch, base_document, ingestion)
        reports.append(copy.deepcopy(report))
        return report

    with mock.patch.object(compiler_v1, "validate_batch_guarded", side_effect=recorder):
        try:
            batch = compiler_v1_1.compile_story_extraction_draft_v1_1(draft, context)
        except compiler_v1_1.DraftCompilationErrorV1_1 as error:
            return None, [blocker.as_dict() for blocker in error.blockers], reports
    return batch, [], reports


def replay_attempts(cases: Sequence[CaseInput], locked: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Replay all locked responses and require every recorded outcome to reproduce."""
    layout, result = locked["layout"], locked["result"]
    projection_validator = Draft202012Validator(protocol.native_response_schema())
    rows: list[dict[str, Any]] = []
    for case, item in zip(cases, result["predictions"]):
        primary_raw = None
        for phase_label, phase, folder in PHASES:
            recorded = item["primary"] if phase == "primary" else item["repair"]
            raw_path = layout[folder] / f"{case.case_id}.txt"
            if recorded is None:
                if raw_path.exists():
                    raise ReproductionDefect("A response exists for an attempt that was not recorded")
                continue
            raw = raw_path.read_bytes()
            if sha256_bytes(raw) != recorded["raw_response_sha256"]:
                raise IntegrityDefect("A raw response hash differs")
            text = raw.decode("utf-8")
            primary_raw = text if phase == "primary" else primary_raw
            try:
                draft = json.loads(text)
                json_valid = True
            except json.JSONDecodeError:
                draft, json_valid = None, False
            schema_valid = projection_valid = None
            blockers: list[dict[str, str]] = []
            batch, reports = None, []
            if json_valid:
                projection_valid = projection_validator.is_valid(draft)
                try:
                    compiler_v1_1.validate_draft_v1_1(draft)
                    schema_valid = True
                except compiler_v1_1.DraftCompilationErrorV1_1:
                    schema_valid = False
            if schema_valid:
                plain_error = None
                try:
                    plain = compiler_v1_1.compile_story_extraction_draft_v1_1(draft, case.compiler_context)
                except compiler_v1_1.DraftCompilationErrorV1_1 as error:
                    plain, plain_error = None, [blocker.as_dict() for blocker in error.blockers]
                batch, blockers, reports = compile_with_recorder(draft, case.compiler_context)
                if (plain, plain_error or []) != (batch, blockers):
                    raise ReproductionDefect("Instrumented and plain compilation disagree")
            compiled = batch is not None
            category = (None if compiled else "DRAFT_COMPILER_FAILURE" if schema_valid
                        else "DRAFT_SCHEMA_FAILURE" if json_valid else "JSON_PARSE_FAILURE")
            draft_sha256 = None if draft is None else sha256_bytes(canonical_json_bytes(draft))
            checks = {
                "json": recorded["json_parse"] == json_valid,
                "projection": recorded["provider_projection_valid"] == projection_valid,
                "schema": recorded["full_schema_valid"] == schema_valid,
                "compiler_reached": recorded["compiler_reached"] == bool(schema_valid),
                "compiler_success": recorded["compiler_success"] == (compiled if schema_valid else None),
                "category": recorded["structural_failure_category"] == category,
                "draft_sha256": recorded["draft_sha256"] == draft_sha256,
            }
            diagnostic_path = layout["failures"] / f"{case.case_id}_{phase}_diagnostic.json"
            stored_diagnostic = _read_json(diagnostic_path) if diagnostic_path.exists() else None
            if schema_valid and not compiled:
                checks["diagnostic"] = stored_diagnostic is not None and stored_diagnostic["findings"] == \
                    contract.compiler_findings(blockers)
            else:
                checks["diagnostic"] = (stored_diagnostic is None) == compiled if schema_valid else True
            if not all(checks.values()):
                raise ReproductionDefect("A locked attempt outcome does not reproduce")
            rows.append({
                "case_id": case.case_id,
                "phase": phase_label,
                "request_fingerprint": recorded["request_fingerprint"],
                "raw_response_sha256": recorded["raw_response_sha256"],
                "draft_sha256": draft_sha256,
                "json_valid": json_valid,
                "projection_valid": projection_valid,
                "full_schema_valid": schema_valid,
                "compiler_reached": bool(schema_valid),
                "compiler_success": compiled if schema_valid else None,
                "blockers": blockers,
                "blocker_count": len(blockers),
                "blocker_phase": blockers[0]["phase"] if blockers else None,
                "blocker_code": blockers[0]["code"] if blockers else None,
                "blocker_path": blockers[0]["path"] if blockers else None,
                "repair_used": item["repair_used"],
                "repair_identical_to_primary": None,
                "terminal_status": item["terminal_status"],
                "_draft": draft, "_case": case, "_batch": batch, "_reports": reports,
                "_stored_diagnostic": stored_diagnostic, "_raw": text,
            })
        mine = [row for row in rows if row["case_id"] == case.case_id]
        if len(mine) == 2:
            identical = mine[0]["raw_response_sha256"] == mine[1]["raw_response_sha256"]
            if identical != (mine[0]["_raw"] == mine[1]["_raw"]):
                raise IntegrityDefect("Hash equality and byte equality of a repair disagree")
            mine[1]["repair_identical_to_primary"] = identical
        terminal = mine[-1]
        expected = "STRUCTURAL_VALID" if terminal["compiler_success"] else "STRUCTURAL_FAILURE"
        if item["terminal_status"] != expected or len(mine) != 1 + item["repair_used"]:
            raise ReproductionDefect("A terminal status does not reproduce")
        if terminal["compiler_success"]:
            compiled_bytes = (layout["compiled"] / f"{case.case_id}.json").read_bytes()
            if canonical_json_bytes(terminal["_batch"]) != compiled_bytes:
                raise ReproductionDefect("A compiled batch does not reproduce byte for byte")
    return rows


def public_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """The private matrix row: structural fields only, no draft, text or batch."""
    return {key: value for key, value in row.items() if not key.startswith("_")}


# ---------------------------------------------------------------------------
# Quote locator forensics
# ---------------------------------------------------------------------------

def occurrence_count(text: str, quote: str) -> int:
    """Exact code-point matches as the frozen compiler counts them: overlapping, never normalized."""
    return len(compiler_v1._occurrences(text, quote))


def classify_locator(record: Mapping[str, Any], passages: Mapping[str, Any]) -> dict[str, Any]:
    """Structural class of one evidence or mention locator. Uses the compiler's own matcher."""
    handle = record.get("passage_handle")
    if handle not in passages:
        return {"class": "QUOTE_LOCATOR_INVALID", "reason": "UNKNOWN_PASSAGE_HANDLE", "exact_occurrences": None,
                "occurrence_present": "occurrence" in record, "passage_use": None, "overlapping_only": None}
    item, text = passages[handle]
    quote = record["quote"]
    count = occurrence_count(text, quote)
    present = "occurrence" in record
    facts = {"exact_occurrences": count, "occurrence_present": present, "passage_use": item["use"],
             "overlapping_only": count > 1 and text.count(quote) == 1, "quote_code_points": len(quote)}
    if item["use"] != "EVIDENCE_ELIGIBLE":
        return {"class": "OTHER_QUOTE_BINDING_FAILURE", "reason": "CONTEXT_ONLY_EVIDENCE", **facts}
    if count == 0:
        return {"class": "QUOTE_NOT_FOUND", "reason": "QUOTE_NOT_FOUND", **facts}
    if not present:
        if count > 1:
            return {"class": "QUOTE_REPEATED_OCCURRENCE_MISSING", "reason": "AMBIGUOUS_QUOTE", **facts}
        return {"class": "QUOTE_UNIQUE_OCCURRENCE_OMITTED", "reason": None, **facts}
    if record["occurrence"] > count:
        return {"class": "QUOTE_LOCATOR_INVALID", "reason": "OCCURRENCE_OUT_OF_RANGE", **facts}
    if count > 1:
        return {"class": "QUOTE_REPEATED_OCCURRENCE_PRESENT", "reason": None, **facts}
    return {"class": "QUOTE_UNIQUE_OCCURRENCE_PRESENT", "reason": None, **facts}


def _compiler_quote_code(record: Mapping[str, Any], passages: Mapping[str, Any], context: Any) -> Optional[str]:
    try:
        compiler_v1._quote_ref(record, passages, context)
    except compiler_v1.DraftCompilationError as error:
        return error.code
    return None


def _length_bucket(code_points: Optional[int]) -> str:
    if code_points is None:
        return "UNKNOWN"
    return "1" if code_points == 1 else "2_TO_3" if code_points <= 3 else "4_TO_9" if code_points <= 9 else "10_OR_MORE"


def _count_bucket(count: Optional[int]) -> str:
    return "UNKNOWN" if count is None else str(count) if count <= 2 else "3_OR_MORE"


def quote_forensics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Every locator of every attempt, and every quote blocker, classified mechanically."""
    private: list[dict[str, Any]] = []
    census: Counter = Counter()
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if row["_draft"] is None or not row["full_schema_valid"]:
            continue
        passages, _ = compiler_v1._context_maps(row["_case"].compiler_context)
        records = {}
        for field in ("evidence", "mentions"):
            for record in row["_draft"][field]:
                facts = classify_locator(record, passages)
                if facts["reason"] != _compiler_quote_code(record, passages, row["_case"].compiler_context):
                    raise ReproductionDefect("Locator classification disagrees with the frozen compiler")
                census[(row["phase"], field, facts["class"])] += 1
                records[(field, record["handle"])] = (record, facts)
        by_key[(row["case_id"], row["phase"])] = records
        for blocker in row["blockers"]:
            if blocker["phase"] != "QUOTE":
                continue
            field, handle = blocker["path"].split("/", 1)
            record, facts = records[(field, handle)]
            entry = {"case_id": row["case_id"], "phase": row["phase"], "record_kind": field, "handle": handle,
                     "blocker_code": blocker["code"], **facts}
            if row["phase"] == "REPAIR_1":
                before = by_key[(row["case_id"], "PRIMARY")].get((field, handle))
                entry["same_handle_in_primary"] = before is not None
                if before is not None:
                    entry["repair_changed_quote"] = before[0]["quote"] != record["quote"]
                    entry["repair_changed_occurrence"] = before[0].get("occurrence") != record.get("occurrence")
            private.append(entry)
    # What each repair did to the records that had blocked its primary.
    repairs = []
    for row in rows:
        if row["phase"] != "PRIMARY" or (row["case_id"], "REPAIR_1") not in by_key:
            continue
        after = by_key[(row["case_id"], "REPAIR_1")]
        for blocker in row["blockers"]:
            if blocker["phase"] != "QUOTE":
                continue
            field, handle = blocker["path"].split("/", 1)
            before_record = by_key[(row["case_id"], "PRIMARY")][(field, handle)][0]
            later = after.get((field, handle))
            repairs.append({
                "case_id": row["case_id"], "record_kind": field, "handle": handle,
                "record_still_present": later is not None,
                "repair_changed_quote": None if later is None else later[0]["quote"] != before_record["quote"],
                "repair_added_occurrence": None if later is None else "occurrence" in later[0],
                "class_after_repair": None if later is None else later[1]["class"],
                "ambiguity_cleared": later is None or later[1]["reason"] is None,
            })
    blockers = Counter((entry["blocker_code"], entry["class"]) for entry in private)
    ambiguous = [entry for entry in private if entry["blocker_code"] == "AMBIGUOUS_QUOTE"]
    public = {
        "matcher": "FROZEN_COMPILER_EXACT_CODE_POINT_MATCH_OVERLAPPING_NO_NORMALIZATION",
        "quote_blockers": len(private),
        "attempts_with_a_quote_blocker": len({(e["case_id"], e["phase"]) for e in private}),
        "blockers_by_code_and_class": {f"{code}:{label}": count for (code, label), count in sorted(blockers.items())},
        "ambiguous_quote": {
            "blockers": len(ambiguous),
            "by_phase": dict(sorted(Counter(e["phase"] for e in ambiguous).items())),
            "by_record_kind": dict(sorted(Counter(e["record_kind"] for e in ambiguous).items())),
            "quote_exists_in_designated_passage": sum(e["exact_occurrences"] > 0 for e in ambiguous),
            "occurrence_omitted": sum(not e["occurrence_present"] for e in ambiguous),
            "passage_evidence_eligible": sum(e["passage_use"] == "EVIDENCE_ELIGIBLE" for e in ambiguous),
            "caused_by_repeated_exact_text": sum(e["class"] == "QUOTE_REPEATED_OCCURRENCE_MISSING" for e in ambiguous),
            "repetition_only_through_overlapping_matches": sum(bool(e["overlapping_only"]) for e in ambiguous),
            "exact_occurrence_count_buckets": dict(sorted(Counter(
                _count_bucket(e["exact_occurrences"]) for e in ambiguous).items())),
            "quote_length_buckets_in_code_points": dict(sorted(Counter(
                _length_bucket(e.get("quote_code_points")) for e in ambiguous).items())),
        },
        "locator_census_all_attempts": {
            f"{phase}:{field}:{label}": count for (phase, field, label), count in sorted(census.items())
        },
        "repeated_quote_locators_that_did_carry_an_occurrence": sum(
            count for (_, _, label), count in census.items() if label == "QUOTE_REPEATED_OCCURRENCE_PRESENT"),
        "effect_of_repair_on_primary_quote_blockers": {
            "primary_quote_blockers_in_repaired_cases": len(repairs),
            "record_still_present": sum(e["record_still_present"] for e in repairs),
            "quote_text_changed": sum(bool(e["repair_changed_quote"]) for e in repairs),
            "occurrence_added": sum(bool(e["repair_added_occurrence"]) for e in repairs),
            "ambiguity_cleared": sum(e["ambiguity_cleared"] for e in repairs),
            "ambiguity_unchanged": sum(not e["ambiguity_cleared"] for e in repairs),
        },
    }
    return {"public": public, "private": {"blockers": private, "repair_effects": repairs}}


# ---------------------------------------------------------------------------
# Canonical conformance forensics
# ---------------------------------------------------------------------------

# Rule classes of the frozen canonical validator, matched on its fixed message templates.
RULE_CLASSES = (
    ("predicate_integrity", r"duplicate concrete proposition content", "DUPLICATE_CONCRETE_PROPOSITION_CONTENT"),
    ("predicate_integrity", r"unregistered event_kind", "UNREGISTERED_EVENT_KIND"),
    ("predicate_integrity", r"forbidden stored verdict predicate", "FORBIDDEN_STORED_VERDICT_PREDICATE"),
    ("predicate_integrity", r"unregistered predicate", "UNREGISTERED_PREDICATE"),
    ("predicate_integrity", r"arity mismatch", "PREDICATE_ARGUMENT_SET_MISMATCH"),
    ("predicate_integrity", r"entity kind \S+ not in", "ARGUMENT_ENTITY_KIND_NOT_ALLOWED"),
    ("predicate_integrity", r"literal type", "LITERAL_TYPE_MISMATCH"),
    ("predicate_integrity", r"stores forbidden verdict", "FORBIDDEN_STORED_VERDICT_VALUE"),
    ("predicate_integrity", r" vocabulary \S+ != ", "TOKEN_VOCABULARY_MISMATCH"),
    ("predicate_integrity", r" value .* not in ", "TOKEN_VALUE_NOT_IN_VOCABULARY"),
    ("predicate_integrity", r" kind \S+ != ", "ARGUMENT_KIND_MISMATCH"),
    ("reference_integrity", r"duplicate id", "DUPLICATE_ID"),
    ("reference_integrity", r"is not an EVENT_TIME anchor of that event", "EVENT_ANCHOR_NOT_ITS_EVENT_TIME_ANCHOR"),
    ("reference_integrity", r"outside the story discourse stream", "POSITION_OUTSIDE_DISCOURSE_STREAM"),
    ("reference_integrity", r"proposition embedding cycle", "PROPOSITION_EMBEDDING_CYCLE"),
    ("reference_integrity", r"unknown", "UNKNOWN_REFERENCE"),
    ("evidence_set_integrity", r"references unknown evidence ref", "EVIDENCE_SET_UNKNOWN_EVIDENCE"),
    ("evidence_set_integrity", r".", "EVIDENCE_SET_RULE"),
    ("support_path_integrity", r"has no support path", "NO_SUPPORT_PATH"),
    ("support_path_integrity", r"no complete support path", "NO_COMPLETE_SUPPORT_PATH"),
    ("derivation_integrity", r"unregistered rule", "UNREGISTERED_RULE"),
    ("derivation_integrity", r"cannot conclude attitude", "RULE_CANNOT_CONCLUDE_ATTITUDE"),
    ("derivation_integrity", r"cannot conclude", "RULE_CANNOT_CONCLUDE_PREDICATE"),
    ("derivation_integrity", r"lacks required premise predicates", "RULE_REQUIRED_PREMISES_MISSING"),
    ("derivation_integrity", r"does not exist", "PREMISE_MISSING"),
    ("derivation_integrity", r"uses itself as a premise", "SELF_PREMISE"),
    ("derivation_integrity", r"REJECTED premise", "REJECTED_PREMISE"),
    ("derivation_integrity", r"derivation cycle", "DERIVATION_CYCLE"),
    ("derivation_integrity", r".", "DERIVATION_RULE"),
    ("temporal_bound_integrity", r"is not stative", "VALIDITY_ON_NON_STATIVE_PREDICATE"),
    ("temporal_bound_integrity", r"unknown anchor", "UNKNOWN_REFERENCE"),
    ("temporal_bound_integrity", r"no complete path", "BOUND_SUPPORT_INCOMPLETE"),
    ("temporal_bound_integrity", r"same anchor", "VALIDITY_STARTS_AND_ENDS_AT_SAME_ANCHOR"),
    ("epistemic_integrity", r"internal state as EXPLICIT", "INTERNAL_STATE_EXPLICIT_WITHOUT_DEPICTION"),
    ("epistemic_integrity", r"is EXPLICIT without", "EXPLICIT_WITHOUT_DIRECT_EVIDENCE_PATH"),
    ("epistemic_integrity", r"exceeds what its derivations support", "STATUS_EXCEEDS_DERIVATIONS"),
)
SECTION_CATEGORY = {
    "STRUCTURAL": "CANONICAL_RECORD_SCHEMA",
    "reference_integrity": "CROSS_RECORD_REFERENCE",
    "evidence_set_integrity": "SUPPORT_RELATION",
    "support_path_integrity": "SUPPORT_RELATION",
    "derivation_integrity": "SUPPORT_RELATION",
    "temporal_bound_integrity": "TEMPORAL_CONSTRAINT",
    "predicate_integrity": "OTHER_CANONICAL_CONSTRAINT",
    "epistemic_integrity": "OTHER_CANONICAL_CONSTRAINT",
}
CHECK_CATEGORY = {
    "envelope": "EXTRACTION_ENVELOPE", "scope": "EXTRACTION_ENVELOPE", "ids": "EXTRACTION_ENVELOPE",
    "evidence": "EVIDENCE_PROVENANCE", "review_provenance": "EVIDENCE_PROVENANCE",
}


def classify_issue(check: str, issue: str) -> dict[str, str]:
    """Map one validator issue to its check, section, rule class and category. No issue text is kept."""
    if check != "canonical":
        code = issue.split(":", 1)[0]
        code = code if re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code) else "UNCLASSIFIED_ISSUE"
        category = "GUARDED_BATCH_CONFORMANCE" if code == "MALFORMED_PASSAGE_INPUT" else CHECK_CATEGORY.get(
            check, "OTHER_CANONICAL_CONSTRAINT")
        return {"check": check, "section": check, "rule_class": code, "category": category}
    section, _, body = issue.partition(": ")
    if section not in SECTION_CATEGORY:
        return {"check": check, "section": "UNCLASSIFIED_SECTION", "rule_class": "UNCLASSIFIED_ISSUE",
                "category": "OTHER_CANONICAL_CONSTRAINT"}
    if section == "STRUCTURAL":
        return {"check": check, "section": section, "rule_class": "CANONICAL_RECORD_SCHEMA_VIOLATION",
                "category": SECTION_CATEGORY[section]}
    if body.startswith("check aborted on unresolved reference"):
        rule = "CHECK_ABORTED_ON_UNRESOLVED_REFERENCE"
    else:
        rule = next((name for owner, pattern, name in RULE_CLASSES if owner == section and re.search(pattern, body)),
                    "UNCLASSIFIED_ISSUE")
    return {"check": check, "section": section, "rule_class": rule, "category": SECTION_CATEGORY[section]}


def _handles_in(issue: str) -> list[str]:
    """Draft handles named by generated canonical ids in a validator issue. Private use only."""
    return [match.split("-es-")[0].split("-der-")[0] for match in _GENERATED_ID.findall(issue)]


def draft_carries_violation(rule_class: str, issue: str, draft: Mapping[str, Any], registry: Mapping[str, Any]) -> Optional[bool]:
    """Whether the violation is already present in the model's draft, before any compilation.

    True means the compiler transcribed draft content faithfully and the canonical rule
    rejected that content. None means this rule class has no mechanical check here.
    """
    handles = _handles_in(issue)
    by_handle = {record["handle"]: record for field in ("entities", "propositions", "assertions")
                 for record in draft[field]}
    try:
        if rule_class == "DUPLICATE_CONCRETE_PROPOSITION_CONTENT":
            first, second = (by_handle[handle] for handle in handles[:2])
            return {k: v for k, v in first.items() if k != "handle"} == {k: v for k, v in second.items() if k != "handle"}
        if rule_class == "ARGUMENT_ENTITY_KIND_NOT_ALLOWED":
            proposition = by_handle[handles[0]]
            spec = {arg["name"]: arg for arg in registry["predicates"][proposition["predicate"]]["args"]}
            unresolved = False
            for name, argument in proposition["args"].items():
                allowed = spec.get(name, {}).get("entity_kinds")
                if not allowed:
                    continue
                target = by_handle.get(argument.get("handle"))
                if target is None:
                    unresolved = True  # an existing entity: its kind is not in the draft
                elif target.get("kind") not in allowed:
                    return True
            return None if unresolved else False
        if rule_class == "RULE_CANNOT_CONCLUDE_PREDICATE":
            assertion = by_handle[handles[0]]
            predicate = by_handle[assertion["proposition_handle"]].get("predicate")
            rules = registry["derivation_rules"]
            return any(
                derivation["rule_id"] in rules
                and predicate not in rules[derivation["rule_id"]].get("conclusion_predicates", [predicate])
                for derivation in assertion["support"]["derivations"]
            )
    except (KeyError, IndexError, TypeError):
        return None
    return None


def canonical_forensics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Which check, section and rule class failed in every canonical conformance failure."""
    registry = load_registry()
    private: list[dict[str, Any]] = []
    for row in rows:
        if row["blocker_code"] not in ("CANONICAL_CONFORMANCE_FAILURE", "CANONICAL_VALIDATOR_EXCEPTION"):
            continue
        if row["blocker_code"] == "CANONICAL_VALIDATOR_EXCEPTION" or not row["_reports"]:
            private.append({"case_id": row["case_id"], "phase": row["phase"], "issues": [],
                            "failed_checks": [], "category": "VALIDATOR_EXCEPTION"})
            continue
        report = row["_reports"][-1]
        failed = [name for name, check in report["checks"].items() if not check["pass"]]
        if row["blocker_path"] != ",".join(failed):
            raise ReproductionDefect("Recorded validator report and compiler blocker disagree")
        issues = []
        for name in failed:
            for issue in report["checks"][name]["issues"]:
                entry = classify_issue(name, issue)
                entry["draft_carries_violation"] = draft_carries_violation(
                    entry["rule_class"], issue, row["_draft"], registry)
                entry["handles"] = _handles_in(issue)
                issues.append(entry)
        precompile = compiler_v1_1.collect_draft_structural_blockers_v1_1(row["_draft"], row["_case"].compiler_context)
        private.append({"case_id": row["case_id"], "phase": row["phase"], "failed_checks": failed,
                        "issues": issues, "precompile_structural_blockers": len(precompile)})
    flat = [(entry, issue) for entry in private for issue in entry["issues"]]

    def tally(key):
        return dict(sorted(Counter(issue[key] for _, issue in flat).items()))

    by_rule: dict[str, dict[str, Any]] = {}
    for entry, issue in flat:
        slot = by_rule.setdefault(issue["rule_class"], {
            "check": issue["check"], "section": issue["section"], "category": issue["category"],
            "affected_attempts": set(), "primary_attempts": 0, "repair_attempts": 0, "issues": 0,
            "violation_present_in_model_draft": 0, "violation_not_mechanically_checked": 0,
            "violation_absent_from_model_draft": 0})
        key = (entry["case_id"], entry["phase"])
        if key not in slot["affected_attempts"]:
            slot["affected_attempts"].add(key)
            slot["primary_attempts" if entry["phase"] == "PRIMARY" else "repair_attempts"] += 1
        slot["issues"] += 1
        outcome = issue["draft_carries_violation"]
        slot["violation_present_in_model_draft" if outcome is True else "violation_not_mechanically_checked"
             if outcome is None else "violation_absent_from_model_draft"] += 1
    for slot in by_rule.values():
        slot["affected_attempts"] = len(slot["affected_attempts"])
    public = {
        "instrumentation": "READ_ONLY_RECORDER_AROUND_THE_VALIDATOR_CALL_INSIDE_THE_UNCHANGED_COMPILER",
        "authoritative_result": "UNCHANGED_COMPILER_VERDICT",
        "attempts_with_canonical_conformance_failure": len(private),
        "by_phase": dict(sorted(Counter(entry["phase"] for entry in private).items())),
        "failed_checks": dict(sorted(Counter(name for entry in private for name in entry["failed_checks"]).items())),
        "issues_total": len(flat),
        "issues_per_attempt_maximum": max((len(entry["issues"]) for entry in private), default=0),
        "issues_by_section": tally("section"),
        "issues_by_rule_class": tally("rule_class"),
        "issues_by_category": tally("category"),
        "rule_classes": dict(sorted(by_rule.items())),
        "attempts_with_zero_precompile_structural_blockers": sum(
            entry.get("precompile_structural_blockers") == 0 for entry in private),
        "validator_exceptions": sum(entry.get("category") == "VALIDATOR_EXCEPTION" for entry in private),
        "unclassified_issues": sum(issue["rule_class"] == "UNCLASSIFIED_ISSUE" for _, issue in flat),
    }
    return {"public": public, "private": private}


# ---------------------------------------------------------------------------
# Repair effectiveness and the diagnostic that the repair received
# ---------------------------------------------------------------------------

def _blocker_set(row: Mapping[str, Any]) -> set[tuple[str, str, str]]:
    return {(b["phase"], b["code"], b["path"]) for b in row["blockers"]}


def repair_effect(primary: Mapping[str, Any], repair: Mapping[str, Any]) -> str:
    if repair["repair_identical_to_primary"]:
        return "IDENTICAL_RESPONSE"
    if repair["compiler_success"]:
        return "REPAIR_STRUCTURALLY_VALID"
    before, after = _blocker_set(primary), _blocker_set(repair)
    if before == after:
        return "BLOCKER_UNCHANGED"
    if not before & after:
        return "PRIMARY_BLOCKER_CLEARED_BUT_NEW_BLOCKER"
    return "BLOCKER_CHANGED"


def diagnostic_mechanism(primary: Mapping[str, Any], repair: Mapping[str, Any], effect: str) -> str:
    """Probable mechanism for a repair that did not clear its primary blocker. Rule based."""
    if effect in ("REPAIR_STRUCTURALLY_VALID", "PRIMARY_BLOCKER_CLEARED_BUT_NEW_BLOCKER"):
        return "NOT_APPLICABLE_PRIMARY_BLOCKER_WAS_CLEARED"
    if primary["blocker_code"] == "CANONICAL_CONFORMANCE_FAILURE":
        return "DIAGNOSTIC_TOO_GENERIC_FOR_STRUCTURAL_REPAIR"
    if primary["blocker_code"] == "AMBIGUOUS_QUOTE":
        return "CORRECT_DIAGNOSTIC_BUT_MODEL_DID_NOT_REPAIR"
    return "INSUFFICIENT_EVIDENCE"


MECHANISM_RULE = _p(
    "A repair that cleared its primary blocker needs no mechanism. A canonical conformance failure that "
    "was not cleared is classed as a diagnostic too generic to act on, because the finding named neither "
    "the failed check nor the record. An ambiguous quote that was not cleared is classed as a correct "
    "diagnostic the model did not act on, because the same shape of finding was acted on in other cases."
)


def repair_forensics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_case: dict[str, dict[str, Mapping[str, Any]]] = {}
    for row in rows:
        by_case.setdefault(row["case_id"], {})[row["phase"]] = row
    material = contract.prompt_material()
    private = []
    for case_id, phases in sorted(by_case.items()):
        if "REPAIR_1" not in phases:
            continue
        primary, repair = phases["PRIMARY"], phases["REPAIR_1"]
        effect = repair_effect(primary, repair)
        stored = primary["_stored_diagnostic"]
        findings = stored["findings"] if stored else []
        raw = primary["blockers"]
        private.append({
            "case_id": case_id,
            "effect": effect,
            "probable_mechanism": diagnostic_mechanism(primary, repair, effect),
            "response_sha256_equal": primary["raw_response_sha256"] == repair["raw_response_sha256"],
            "request_fingerprints_differ": primary["request_fingerprint"] != repair["request_fingerprint"],
            "primary_blocker_code": primary["blocker_code"],
            "repair_blocker_code": repair["blocker_code"],
            "primary_blocker_count": primary["blocker_count"],
            "repair_blocker_count": repair["blocker_count"],
            "blocker_paths_equal": [b["path"] for b in raw] == [b["path"] for b in repair["blockers"]],
            "repair_compiler_success": bool(repair["compiler_success"]),
            "primary_blocker_cleared": not (_blocker_set(primary) & _blocker_set(repair)),
            "diagnostic": {
                "identity_is_v2": bool(stored) and stored["diagnostic"] == contract.REPAIR_DIAGNOSTIC_ID,
                "category_correct": bool(stored) and stored["category"] == "DRAFT_COMPILER_FAILURE",
                "phase_and_code_preserved": {(f["phase"], f["code"]) for f in findings}
                == {(b["phase"], b["code"]) for b in raw},
                "raw_compiler_blockers": len(raw),
                "findings_sent": len(findings),
                "blockers_collapsed_into_fewer_findings": len(findings) < len(raw),
                "record_handle_masked_in_path": any(MASK in f["path"] for f in findings),
                "path_fully_masked": bool(findings) and all(f["path"] == MASK for f in findings),
                "failed_canonical_check_named": any(
                    f["code"] == "CANONICAL_CONFORMANCE_FAILURE" and f["path"] not in (MASK, "$") for f in findings),
                "finding_fields": sorted({key for f in findings for key in f}),
                "equals_sanitized_raw_blockers": findings == contract.compiler_findings(raw),
            },
        })
    effects = Counter(entry["effect"] for entry in private)
    mechanisms = Counter(entry["probable_mechanism"] for entry in private)

    def count(predicate):
        return sum(bool(predicate(entry)) for entry in private)

    public = {
        "repair_attempts": len(private),
        "effects": dict(sorted(effects.items())),
        "identical_repair_responses": effects.get("IDENTICAL_RESPONSE", 0),
        "distinct_repair_responses": len(private) - effects.get("IDENTICAL_RESPONSE", 0),
        "repair_compiler_successes": count(lambda e: e["repair_compiler_success"]),
        "primary_blocker_cleared": count(lambda e: e["primary_blocker_cleared"]),
        "primary_blocker_not_cleared": count(lambda e: not e["primary_blocker_cleared"]),
        "request_fingerprints_differ_from_primary": count(lambda e: e["request_fingerprints_differ"]),
        "by_primary_blocker_code": {
            code: dict(sorted(Counter(e["effect"] for e in private if e["primary_blocker_code"] == code).items()))
            for code in sorted({e["primary_blocker_code"] for e in private})
        },
    }
    audit = {
        "diagnostic_identity": contract.REPAIR_DIAGNOSTIC_ID,
        "repairs_audited": len(private),
        "primary_error_category_correct": count(lambda e: e["diagnostic"]["category_correct"]),
        "blocker_phase_and_code_preserved": count(lambda e: e["diagnostic"]["phase_and_code_preserved"]),
        "diagnostic_equals_sanitized_compiler_blockers": count(lambda e: e["diagnostic"]["equals_sanitized_raw_blockers"]),
        "finding_fields": sorted({key for e in private for key in e["diagnostic"]["finding_fields"]}),
        "record_handle_masked_in_path": count(lambda e: e["diagnostic"]["record_handle_masked_in_path"]),
        "path_fully_masked": count(lambda e: e["diagnostic"]["path_fully_masked"]),
        "canonical_failures_sent_to_repair": count(lambda e: e["primary_blocker_code"] == "CANONICAL_CONFORMANCE_FAILURE"),
        "canonical_failures_naming_the_failed_check": count(lambda e: e["diagnostic"]["failed_canonical_check_named"]),
        "repairs_where_blockers_were_collapsed": count(lambda e: e["diagnostic"]["blockers_collapsed_into_fewer_findings"]),
        "raw_compiler_blockers_total": sum(e["diagnostic"]["raw_compiler_blockers"] for e in private),
        "findings_sent_total": sum(e["diagnostic"]["findings_sent"] for e in private),
        "repair_system_prompt_states_the_occurrence_rule": "occurrence is mandatory" in material["repair_system"],
        "repair_user_prompt_describes_findings_as_schema_rules": "schema rule broken" in material["repair_user_template"],
        "diagnostic_explains_any_compiler_code": False,
        "probable_mechanisms": dict(sorted(mechanisms.items())),
        "mechanism_rule": MECHANISM_RULE,
    }
    return {"public": public, "audit": audit, "private": private}


# ---------------------------------------------------------------------------
# Offline structural counterfactuals (in memory only, never predictions)
# ---------------------------------------------------------------------------

def _outcome(draft: Any, context: Any) -> str:
    try:
        compiler_v1_1.compile_story_extraction_draft_v1_1(draft, context)
    except compiler_v1_1.DraftCompilationErrorV1_1 as error:
        return "+".join(sorted({blocker.code for blocker in error.blockers}))
    return "COMPILES"


def quote_counterfactual(row: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    """Every valid occurrence choice for the ambiguous locators of one failed draft. No choice is preferred."""
    targets = [b["path"].split("/", 1) for b in row["blockers"] if b["code"] == "AMBIGUOUS_QUOTE"]
    if not targets or len(targets) != row["blocker_count"]:
        return None
    passages, _ = compiler_v1._context_maps(row["_case"].compiler_context)
    ranges = []
    for field, handle in targets:
        record = next(r for r in row["_draft"][field] if r["handle"] == handle)
        ranges.append(range(1, occurrence_count(passages[record["passage_handle"]][1], record["quote"]) + 1))
    combinations = 1
    for choices in ranges:
        combinations *= len(choices)
    entry = {"label": NON_PREDICTION_LABEL, "case_id": row["case_id"], "phase": row["phase"],
             "ambiguous_locators": len(targets), "occurrence_combinations": combinations}
    if combinations > COUNTERFACTUAL_COMBINATION_LIMIT:
        return {**entry, "enumerated": False, "outcomes": {}}
    outcomes: Counter = Counter()
    for choice in itertools.product(*ranges):
        candidate = copy.deepcopy(row["_draft"])
        for (field, handle), occurrence in zip(targets, choice):
            next(r for r in candidate[field] if r["handle"] == handle)["occurrence"] = occurrence
        outcomes[_outcome(candidate, row["_case"].compiler_context)] += 1
    return {**entry, "enumerated": True, "outcomes": dict(sorted(outcomes.items())),
            "quote_blocker_cleared_by_every_choice": not any("AMBIGUOUS_QUOTE" in key for key in outcomes),
            "compiles_under_every_choice": set(outcomes) == {"COMPILES"},
            "outcome_depends_on_choice": len(outcomes) > 1}


def duplicate_proposition_counterfactual(row: Mapping[str, Any], handles: Sequence[str]) -> dict[str, Any]:
    """Refer to one of two identical propositions everywhere and drop the other. No semantic choice."""
    keep, drop = sorted(handles[:2])
    candidate = copy.deepcopy(row["_draft"])
    candidate["propositions"] = [p for p in candidate["propositions"] if p["handle"] != drop]
    for assertion in candidate["assertions"]:
        if assertion["proposition_handle"] == drop:
            assertion["proposition_handle"] = keep
        ambiguity = assertion.get("textual_ambiguity")
        if ambiguity:
            ambiguity["alternative_proposition_handles"] = [
                keep if h == drop else h for h in ambiguity["alternative_proposition_handles"]]
    for proposition in candidate["propositions"]:
        for argument in proposition.get("args", {}).values():
            if argument.get("kind") == "PROPOSITION" and argument.get("handle") == drop:
                argument["handle"] = keep
    return {"label": NON_PREDICTION_LABEL, "case_id": row["case_id"], "phase": row["phase"],
            "edit": "REFER_TO_ONE_OF_TWO_IDENTICAL_PROPOSITIONS", "outcome": _outcome(candidate, row["_case"].compiler_context)}


def counterfactuals(rows: Sequence[Mapping[str, Any]], canonical_private: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    quote = [entry for entry in (quote_counterfactual(row) for row in rows) if entry is not None]
    by_key = {(row["case_id"], row["phase"]): row for row in rows}
    canonical, skipped = [], Counter()
    for entry in canonical_private:
        for issue in entry["issues"]:
            if issue["rule_class"] == "DUPLICATE_CONCRETE_PROPOSITION_CONTENT" and issue["draft_carries_violation"]:
                canonical.append(duplicate_proposition_counterfactual(by_key[(entry["case_id"], entry["phase"])],
                                                                      issue["handles"]))
            else:
                skipped[issue["rule_class"]] += 1
    enumerated = [entry for entry in quote if entry["enumerated"]]
    public = {
        "label": NON_PREDICTION_LABEL,
        "counted_as_predictions": False,
        "written_to_the_prediction_root": False,
        "an_occurrence_was_chosen_as_correct": False,
        "quote_occurrence": {
            "failed_attempts_examined": len(quote),
            "attempts_enumerated": len(enumerated),
            "occurrence_combinations_tried": sum(entry["occurrence_combinations"] for entry in enumerated),
            "attempts_where_every_choice_clears_the_quote_blocker": sum(
                entry["quote_blocker_cleared_by_every_choice"] for entry in enumerated),
            "attempts_that_compile_under_every_choice": sum(entry["compiles_under_every_choice"] for entry in enumerated),
            "attempts_where_another_blocker_follows": sum(
                not entry["compiles_under_every_choice"] for entry in enumerated),
            "attempts_where_the_outcome_depends_on_the_choice": sum(
                entry["outcome_depends_on_choice"] for entry in enumerated),
            "outcome_codes_after_the_edit": dict(sorted(Counter(
                code for entry in enumerated for code in entry["outcomes"]).items())),
        },
        "canonical": {
            "duplicate_proposition_edits_tried": len(canonical),
            "outcomes": dict(sorted(Counter(entry["outcome"] for entry in canonical).items())),
            "skipped_because_the_edit_needs_a_semantic_choice": dict(sorted(skipped.items())),
        },
    }
    return {"public": public, "private": {"quote": quote, "canonical": canonical}}


# ---------------------------------------------------------------------------
# Prompt and schema versus compiler requirements
# ---------------------------------------------------------------------------

AUDIT_NOTES = tuple(_p(note) for note in (
    'The prompt states the rule in words. The schema leaves occurrence optional and cannot express uniqueness, so neither the schema nor the provider projection can enforce it.',
    'The prompt requires an exact quote and tells the model to preserve Unicode, punctuation and whitespace. No quote-not-found failure was observed.',
    'The compiler counts overlapping matches. The prompt does not say so. No observed ambiguity arose only from overlapping matches.',
    'Stated in the prompt. Every observed locator was in an evidence-eligible passage.',
    'The prompt says a mention carries no evidence handle and the compiler binds it. No binding failure was observed.',
    'Handle patterns are in the schema and the prompt requires type-correct handles. No handle failure was observed.',
    'The constraint is in the registry text inside the prompt as a field of the argument. The prompt prose never says that the referenced entity must have one of those kinds.',
    'Each rule lists its conclusion predicates in the registry text inside the prompt. The prompt prose never says that a derivation may only support an assertion of one of those predicates.',
    'Neither the prompt, the schema nor the registry text tells the model that two propositions with the same content are rejected.',
    'The host builds the envelope and provenance. The model never outputs them and no envelope failure was observed.',
    'The repair prompt says each finding gives a path and the schema rule broken there. A compiler finding gives a code and a path with the record handle masked, and for canonical conformance it gives no check and no record at all.',
))


def contract_audit() -> dict[str, Any]:
    """What the model was shown about each rule the compiler enforced. Mechanical facts plus a fixed class."""
    material = contract.prompt_material()
    system = material["primary_system"]
    schema = contract.extract_prompt_schema(system, contract.SCHEMA_SECTION_MARKER, contract.REGISTRY_SECTION_MARKER)
    registry = load_registry()
    registry_text = system.split(contract.REGISTRY_SECTION_MARKER, 1)[1]
    mention, evidence = schema["$defs"]["Mention"], schema["$defs"]["Evidence"]
    entity_kind_arguments = sum("entity_kinds" in arg for spec in registry["predicates"].values() for arg in spec["args"])
    rules_with_conclusions = sum("conclusion_predicates" in rule for rule in registry["derivation_rules"].values())
    facts = {
        "prompt_states_occurrence_is_mandatory_for_a_repeated_quote": "occurrence is mandatory" in system,
        "prompt_states_occurrence_is_one_based": "1-based" in system,
        "prompt_states_quotes_are_exact_byte_for_byte": "exact byte-for-byte" in system,
        "prompt_states_how_overlapping_matches_are_counted": "overlap" in system.split(
            contract.SCHEMA_SECTION_MARKER)[0].lower(),
        "prompt_restricts_locators_to_evidence_eligible_passages": "only EVIDENCE_ELIGIBLE passages" in system,
        "schema_makes_occurrence_optional": all(
            "occurrence" in record["properties"] and "occurrence" not in record["required"]
            for record in (mention, evidence)),
        "schema_can_express_quote_uniqueness": False,
        "prompt_contains_the_registry_entity_kind_constraints": "entity_kinds" in registry_text,
        "registry_arguments_with_an_entity_kind_constraint": entity_kind_arguments,
        "prompt_prose_explains_entity_kind_constraints": "entity_kinds" in system.split(contract.SCHEMA_SECTION_MARKER)[0]
        or "entity kind" in system.split(contract.SCHEMA_SECTION_MARKER)[0].lower(),
        "prompt_contains_the_derivation_rule_conclusion_predicates": "conclusion_predicates" in registry_text,
        "registry_derivation_rules_with_conclusion_predicates": rules_with_conclusions,
        "prompt_prose_explains_what_a_derivation_rule_may_conclude": "conclude" in system.split(
            contract.SCHEMA_SECTION_MARKER)[0].lower(),
        "prompt_states_propositions_with_identical_content_must_be_one": bool(
            re.search(r"duplicate|identical content|same proposition|reuse one proposition", system, re.IGNORECASE)),
        "prompt_tells_the_model_to_use_only_registry_predicates_arguments_and_rules": "derivation" in system
        and "appended exact predicate registry" in system,
        "repair_prompt_describes_findings_as_schema_rules": "schema rule broken" in material["repair_user_template"],
    }

    def rule(requirement, enforced_by, classification, observed, note):
        if note not in PROSE:
            raise ForensicsError("An audit note is not a registered analyst sentence")
        return {"requirement": requirement, "enforced_by": enforced_by, "classification": classification,
                "observed_in_the_locked_failures": observed, "note": note}

    rules = [
        rule("OCCURRENCE_REQUIRED_WHEN_THE_EXACT_QUOTE_REPEATS", "COMPILER_QUOTE_RESOLUTION",
             "EXPLICIT_AND_CORRECT" if facts["prompt_states_occurrence_is_mandatory_for_a_repeated_quote"] else "ABSENT",
             True, "The prompt states the rule in words. The schema leaves occurrence optional and cannot express "
                   "uniqueness, so neither the schema nor the provider projection can enforce it."),
        rule("EXACT_QUOTE_MATCH_WITHOUT_NORMALIZATION", "COMPILER_QUOTE_RESOLUTION",
             "EXPLICIT_AND_CORRECT" if facts["prompt_states_quotes_are_exact_byte_for_byte"] else "ABSENT",
             False, "The prompt requires an exact quote and tells the model to preserve Unicode, punctuation and "
                    "whitespace. No quote-not-found failure was observed."),
        rule("OVERLAPPING_MATCHES_COUNT_AS_OCCURRENCES", "COMPILER_QUOTE_RESOLUTION",
             "EXPLICIT_AND_CORRECT" if facts["prompt_states_how_overlapping_matches_are_counted"] else "ABSENT",
             False, "The compiler counts overlapping matches. The prompt does not say so. No observed ambiguity "
                    "arose only from overlapping matches."),
        rule("LOCATORS_ONLY_IN_EVIDENCE_ELIGIBLE_PASSAGES", "COMPILER_QUOTE_RESOLUTION",
             "EXPLICIT_AND_CORRECT" if facts["prompt_restricts_locators_to_evidence_eligible_passages"] else "ABSENT",
             False, "Stated in the prompt. Every observed locator was in an evidence-eligible passage."),
        rule("MENTION_EVIDENCE_BINDING", "COMPILER_V1_1_BINDING", "EXPLICIT_AND_CORRECT", False,
             "The prompt says a mention carries no evidence handle and the compiler binds it. No binding failure "
             "was observed."),
        rule("HANDLE_AND_REFERENCE_TYPE_CORRECTNESS", "COMPILER_HANDLE_CHECKS", "EXPLICIT_AND_CORRECT", False,
             "Handle patterns are in the schema and the prompt requires type-correct handles. No handle failure "
             "was observed."),
        rule("ARGUMENT_ENTITY_KIND_ALLOWED_BY_REGISTRY", "CANONICAL_VALIDATOR_PREDICATE_INTEGRITY",
             "IMPLICIT_ONLY" if facts["prompt_contains_the_registry_entity_kind_constraints"]
             and not facts["prompt_prose_explains_entity_kind_constraints"] else "EXPLICIT_AND_CORRECT"
             if facts["prompt_contains_the_registry_entity_kind_constraints"] else "ABSENT",
             True, "The constraint is in the registry text inside the prompt as a field of the argument. The prompt "
                   "prose never says that the referenced entity must have one of those kinds."),
        rule("DERIVATION_RULE_MAY_CONCLUDE_THE_ASSERTED_PREDICATE", "CANONICAL_VALIDATOR_DERIVATION_INTEGRITY",
             "IMPLICIT_ONLY" if facts["prompt_contains_the_derivation_rule_conclusion_predicates"]
             and not facts["prompt_prose_explains_what_a_derivation_rule_may_conclude"] else "EXPLICIT_AND_CORRECT"
             if facts["prompt_contains_the_derivation_rule_conclusion_predicates"] else "ABSENT",
             True, "Each rule lists its conclusion predicates in the registry text inside the prompt. The prompt "
                   "prose never says that a derivation may only support an assertion of one of those predicates."),
        rule("PROPOSITIONS_WITH_IDENTICAL_CONTENT_MUST_BE_ONE_RECORD", "CANONICAL_VALIDATOR_PREDICATE_INTEGRITY",
             "EXPLICIT_AND_CORRECT" if facts["prompt_states_propositions_with_identical_content_must_be_one"] else "ABSENT",
             True, "Neither the prompt, the schema nor the registry text tells the model that two propositions "
                   "with the same content are rejected."),
        rule("EXTRACTION_ENVELOPE_AND_HOST_OWNED_FIELDS", "COMPILER_AND_BATCH_VALIDATOR", "NOT_APPLICABLE", False,
             "The host builds the envelope and provenance. The model never outputs them and no envelope failure "
             "was observed."),
        rule("REPAIR_INSTRUCTIONS_FOR_COMPILER_FINDINGS", "REPAIR_PROMPT_AND_DIAGNOSTIC_V2",
             "AMBIGUOUS", True, "The repair prompt says each finding gives a path and the schema rule broken "
                                "there. A compiler finding gives a code and a path with the record handle masked, "
                                "and for canonical conformance it gives no check and no record at all."),
    ]
    return {"facts": facts, "rules": rules,
            "schema_valid_is_not_compiler_valid_because": sorted(
                r["requirement"] for r in rules if r["observed_in_the_locked_failures"]
                and r["enforced_by"] != "REPAIR_PROMPT_AND_DIAGNOSTIC_V2")}


# ---------------------------------------------------------------------------
# Aggregates, attribution and the public record
# ---------------------------------------------------------------------------

def attempt_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    def block(selected):
        codes = Counter(row["blocker_code"] for row in selected if row["blocker_code"])
        return {
            "attempts": len(selected),
            "json_valid": sum(row["json_valid"] for row in selected),
            "projection_valid": sum(row["projection_valid"] is True for row in selected),
            "full_schema_valid": sum(row["full_schema_valid"] is True for row in selected),
            "compiler_reached": sum(row["compiler_reached"] for row in selected),
            "compiler_success": sum(row["compiler_success"] is True for row in selected),
            "compiler_failure": sum(row["compiler_success"] is False for row in selected),
            "first_blocker_codes": dict(sorted(codes.items())),
            "compiler_blockers_total": sum(row["blocker_count"] for row in selected),
        }

    primary = [row for row in rows if row["phase"] == "PRIMARY"]
    repair = [row for row in rows if row["phase"] == "REPAIR_1"]
    terminal = Counter(row["terminal_status"] for row in primary)
    return {
        "primary": block(primary),
        "repair": block(repair),
        "totals": {
            **block(list(rows)),
            "cases": len(primary),
            "final_structural_valid_cases": terminal.get("STRUCTURAL_VALID", 0),
            "final_structural_failure_cases": terminal.get("STRUCTURAL_FAILURE", 0),
            "final_transport_failure_cases": terminal.get("TRANSPORT_FAILURE", 0),
            "repair_attempts": len(repair),
            "identical_repair_responses": sum(row["repair_identical_to_primary"] is True for row in repair),
            "distinct_repair_responses": sum(row["repair_identical_to_primary"] is False for row in repair),
            "repair_compiler_successes": sum(row["compiler_success"] is True for row in repair),
        },
    }


ATTRIBUTION_NAMES = {
    "A": "MODEL_STRUCTURAL_CONFORMANCE", "B": "MODEL_FACING_INTERFACE_GAP", "C": "REPAIR_DIAGNOSTIC_LIMITATION",
    "D": "DETERMINISTIC_COMPILER_DEFECT", "E": "CANONICAL_CONTRACT_MISMATCH",
    "F": "EXECUTION_OR_SERIALIZATION_DEFECT", "G": "INSUFFICIENT_EVIDENCE",
}


QUOTE_SUPPORTING = _p('Every ambiguous-quote blocker is a mention whose exact quote occurs more than once in an evidence-eligible passage and which omits occurrence. The prompt states that occurrence is mandatory in exactly that situation. The compiler applied the stated rule.')
QUOTE_CONTRARY = _p('The rule cannot be enforced by the model schema or the provider projection, so nothing stops a schema-valid draft from breaking it. In the repair attempts the finding masked which mention was ambiguous. Both points bear on how the rule is delivered, not on whether it was stated.')
QUOTE_UNCERTAINTY = _p('Why the model applied the rule to some repeated quotes and not to others is not observable offline. One run at temperature 0 cannot separate a stable tendency from chance.')
CANONICAL_SUPPORTING = _p('The read-only recorder shows the canonical check, section and rule class that failed. A mechanical comparison shows the rejected structure already present in the model draft, so the compiler transcribed it and the frozen canonical rule rejected it.')
CANONICAL_CONTRARY = _p('The rule reaches the model only as registry data without an explanation, or not at all, and the model output schema accepts the draft. When the failure went to repair, the finding named neither the check nor the record.')
CANONICAL_UNCERTAINTY = _p('Each of these rule classes was seen in one case only. Whether the model would follow the rule if it were stated in words, or would repair it if the finding named it, was not tested.')
REPAIR_SUPPORTING = _p('Diagnostic V2 keeps only names that belong to the schema. A record handle is not one, so every compiler finding lost the handle of the failing record, and the canonical finding lost its whole path. No canonical failure that went to repair was cleared.')
REPAIR_CONTRARY = _p('Findings of the same shape were enough for the repairs that did clear an ambiguous quote, so a masked handle does not by itself prevent a repair. An identical response shows the model did not change its output; it does not show why.')
REPAIR_UNCERTAINTY = _p('Whether a finding that names the record and the failed check would have produced a different repair is unknown. No further model call is allowed in this task.')


def root_cause_attribution(
    rows: Sequence[Mapping[str, Any]], quote: Mapping[str, Any], canonical: Mapping[str, Any],
    repairs: Mapping[str, Any], audit: Mapping[str, Any], counter: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """One entry per recurring mechanism. Counts are computed; the judgement text is fixed and conditional."""
    facts = audit["facts"]
    classes = {r["requirement"]: r["classification"] for r in audit["rules"]}
    quote_rows = [row for row in rows if row["blocker_code"] == "AMBIGUOUS_QUOTE"]
    entries = []
    if quote_rows:
        ambiguous = quote["public"]["ambiguous_quote"]
        explicit = classes["OCCURRENCE_REQUIRED_WHEN_THE_EXACT_QUOTE_REPEATS"] == "EXPLICIT_AND_CORRECT"
        all_missing = ambiguous["caused_by_repeated_exact_text"] == ambiguous["blockers"]
        entries.append({
            "mechanism": "AMBIGUOUS_QUOTE:QUOTE_REPEATED_OCCURRENCE_MISSING",
            "affected_attempts": len(quote_rows),
            "primary_attempts": sum(row["phase"] == "PRIMARY" for row in quote_rows),
            "repair_attempts": sum(row["phase"] == "REPAIR_1" for row in quote_rows),
            "attribution": ["A"] if explicit and all_missing else ["G"],
            "contributing": ["B", "C"] if explicit and all_missing else [],
            "confidence": "HIGH" if explicit and all_missing else "LOW",
            "structural_evidence": {
                "blockers": ambiguous["blockers"],
                "all_on_mention_records": ambiguous["by_record_kind"].get("mentions", 0) == ambiguous["blockers"],
                "all_quotes_exist_and_repeat_exactly": all_missing,
                "all_omit_occurrence": ambiguous["occurrence_omitted"] == ambiguous["blockers"],
                "rule_stated_in_prompt": facts["prompt_states_occurrence_is_mandatory_for_a_repeated_quote"],
                "rule_enforceable_by_schema_or_projection": facts["schema_can_express_quote_uniqueness"],
                "other_repeated_quote_locators_carried_an_occurrence":
                    quote["public"]["repeated_quote_locators_that_did_carry_an_occurrence"],
                "every_valid_occurrence_choice_clears_the_blocker":
                    counter["public"]["quote_occurrence"]["attempts_where_every_choice_clears_the_quote_blocker"]
                    == counter["public"]["quote_occurrence"]["attempts_enumerated"],
            },
            "supporting": QUOTE_SUPPORTING,
            "contrary": QUOTE_CONTRARY,
            "uncertainty": QUOTE_UNCERTAINTY,
        })
    for rule_class, slot in canonical["public"]["rule_classes"].items():
        visible = {
            "ARGUMENT_ENTITY_KIND_ALLOWED_BY_REGISTRY": "ARGUMENT_ENTITY_KIND_NOT_ALLOWED",
            "DERIVATION_RULE_MAY_CONCLUDE_THE_ASSERTED_PREDICATE": "RULE_CANNOT_CONCLUDE_PREDICATE",
            "PROPOSITIONS_WITH_IDENTICAL_CONTENT_MUST_BE_ONE_RECORD": "DUPLICATE_CONCRETE_PROPOSITION_CONTENT",
        }
        requirement = next((name for name, target in visible.items() if target == rule_class), None)
        classification = classes.get(requirement, "NOT_AUDITED")
        in_draft = slot["violation_present_in_model_draft"] == slot["issues"] and slot["issues"] > 0
        if not in_draft or requirement is None:
            attribution, contributing, confidence = ["G"], [], "LOW"
        elif classification == "ABSENT":
            attribution, contributing, confidence = ["B"], ["A"], "MEDIUM"
        elif classification == "IMPLICIT_ONLY":
            attribution, contributing, confidence = ["A", "B"], ["C"] if slot["repair_attempts"] else [], "MEDIUM"
        else:
            attribution, contributing, confidence = ["A"], ["C"] if slot["repair_attempts"] else [], "MEDIUM"
        entries.append({
            "mechanism": "CANONICAL_CONFORMANCE_FAILURE:" + rule_class,
            "affected_attempts": slot["affected_attempts"],
            "primary_attempts": slot["primary_attempts"],
            "repair_attempts": slot["repair_attempts"],
            "attribution": attribution,
            "contributing": contributing,
            "confidence": confidence,
            "structural_evidence": {
                "validator_check": slot["check"],
                "validator_section": slot["section"],
                "category": slot["category"],
                "rule_is_part_of_the_frozen_canonical_contract": True,
                "model_facing_rule_classification": classification,
                "violation_present_in_the_model_draft_before_compilation": in_draft,
                "compiler_generated_the_invalid_structure": False if in_draft else None,
                "canonical_rule_stricter_than_the_model_output_schema": True,
                "detected_by_precompile_structural_checks": False,
            },
            "supporting": CANONICAL_SUPPORTING,
            "contrary": CANONICAL_CONTRARY,
            "uncertainty": CANONICAL_UNCERTAINTY,
        })
    unchanged = repairs["public"]["primary_blocker_not_cleared"]
    if repairs["public"]["repair_attempts"]:
        diag = repairs["audit"]
        entries.append({
            "mechanism": "REPAIR_DID_NOT_CLEAR_THE_PRIMARY_BLOCKER",
            "affected_attempts": unchanged,
            "primary_attempts": 0,
            "repair_attempts": unchanged,
            "attribution": ["C"] if diag["path_fully_masked"] or diag["record_handle_masked_in_path"] else ["G"],
            "contributing": ["A"],
            "confidence": "MEDIUM",
            "structural_evidence": {
                "repair_attempts": repairs["public"]["repair_attempts"],
                "identical_repair_responses": repairs["public"]["identical_repair_responses"],
                "primary_blocker_cleared": repairs["public"]["primary_blocker_cleared"],
                "findings_with_the_record_handle_masked": diag["record_handle_masked_in_path"],
                "findings_with_the_whole_path_masked": diag["path_fully_masked"],
                "canonical_failures_sent_to_repair": diag["canonical_failures_sent_to_repair"],
                "canonical_failures_naming_the_failed_check": diag["canonical_failures_naming_the_failed_check"],
                "repairs_where_blockers_were_collapsed": diag["repairs_where_blockers_were_collapsed"],
                "request_fingerprints_differ_from_primary": repairs["public"]["request_fingerprints_differ_from_primary"],
            },
            "supporting": REPAIR_SUPPORTING,
            "contrary": REPAIR_CONTRARY,
            "uncertainty": REPAIR_UNCERTAINTY,
        })
    return entries


RECOMMENDATIONS = {
    "P4.1 VERSIONED REPAIR DIAGNOSTIC REDESIGN": _p(
        "Supported by the diagnostic audit: every compiler finding sent to repair masked the record handle, the "
        "canonical finding named no check and no record, several blockers were collapsed into one finding, and "
        "no canonical failure was cleared by repair."),
    "P4.1 VERSIONED QUOTE-LOCATOR / COMPILER-INTERFACE REDESIGN": _p(
        "Supported by the quote forensics: the largest single blocker is an omitted occurrence on a repeated "
        "exact quote, a rule the prompt states but which the schema and provider projection cannot enforce. "
        "Every valid occurrence choice clears the blocker."),
    "CANONICAL CONTRACT CLARIFICATION": _p(
        "Supported by the conformance forensics: the three canonical rule classes that failed are enforced only "
        "after compilation, are accepted by the model output schema, and reach the model as unexplained "
        "registry data or not at all."),
}
NOT_RECOMMENDED = {
    "CANONICAL COMPILER DEFECT INVESTIGATION": _p(
        "Not supported. All sixteen outcomes reproduce, the rejected structures are already in the model "
        "drafts, and no input was found that the frozen contract requires the compiler to accept."),
}
LIMITATIONS = (
    _p("No semantic quality was measured. Structural validity says nothing about whether extracted content is correct."),
    _p("DEV3 gold was not opened and nothing was evaluated against it."),
    _p("No model was called. Why the model produced a given draft or repeated a response is not observable offline."),
    _p("DEV3 is tuning data for P4. Nothing here is fresh validation."),
    _p("Sixteen attempts on ten cases from one source family, each sent once. Counts this small do not generalize."),
    _p("The compiler stops canonical validation at the first failed batch, and a quote blocker hides later "
       "checks. Blockers that would appear after a fix are known only where a counterfactual exposed them."),
    _p("Counterfactuals show that an edit removes a blocker. They are not predictions and say nothing about "
       "which occurrence or structure is correct."),
)
PUBLIC_SECTIONS = (
    "task", "status", "base_commit", "analyzer", "accepted_B4C", "boundaries", "reproduction", "attempt_metrics",
    "quote_forensics", "canonical_conformance_forensics", "repair_effectiveness", "repair_diagnostic_audit",
    "contract_audit", "counterfactuals", "root_cause_attribution", "alternative_explanations", "limitations",
    "decision",
)


NO_COMPILER_DEFECT_EVIDENCE = _p('No compiler defect was demonstrated. The instrumented and plain compilations agree, every outcome and every compiled batch reproduces, and each rejected canonical structure is already in the model draft. A defect claim would need an input that the frozen canonical contract requires the compiler to accept; none was found.')
NO_CONTRACT_MISMATCH_EVIDENCE = _p('No conflict between the canonical contract and the draft contract was found. The canonical rules are stricter than the model output schema, which is a gap in what the schema can express, not a contradiction.')
NO_EXECUTION_DEFECT_EVIDENCE = _p('Not supported. All raw, draft, compiled and failure-record hashes match, request fingerprints rebuild from the input, and the prediction set rebuilds from the artifact files.')


def build_public_record(
    reproduction: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], quote: Mapping[str, Any],
    canonical: Mapping[str, Any], repairs: Mapping[str, Any], audit: Mapping[str, Any], counter: Mapping[str, Any],
    b4c_result: Mapping[str, Any],
) -> dict[str, Any]:
    metrics = attempt_metrics(rows)
    attribution = root_cause_attribution(rows, quote, canonical, repairs, audit, counter)
    for entry in attribution:
        entry["attribution"] = [f"{code}_{ATTRIBUTION_NAMES[code]}" for code in entry["attribution"]]
        entry["contributing"] = [f"{code}_{ATTRIBUTION_NAMES[code]}" for code in entry["contributing"]]
    recommended = []
    if repairs["audit"]["record_handle_masked_in_path"] or repairs["audit"]["path_fully_masked"]:
        recommended.append("P4.1 VERSIONED REPAIR DIAGNOSTIC REDESIGN")
    if quote["public"]["ambiguous_quote"]["blockers"]:
        recommended.append("P4.1 VERSIONED QUOTE-LOCATOR / COMPILER-INTERFACE REDESIGN")
    if canonical["public"]["attempts_with_canonical_conformance_failure"]:
        recommended.append("CANONICAL CONTRACT CLARIFICATION")
    if not recommended:
        recommended.append("INSUFFICIENT EVIDENCE " + chr(0x2014) + " FURTHER OFFLINE INVESTIGATION")
    compiler_defect_evidence = any(
        slot["violation_absent_from_model_draft"] for slot in canonical["public"]["rule_classes"].values())
    record = {
        "task": TASK_ID,
        "status": STATUS_COMPLETE,
        "base_commit": EXPECTED_BASE_COMMIT,
        "analyzer": {"id": ANALYZER_ID, "path": ANALYZER_PATH,
                     "sha256": protocol.normalized_file_sha256(REPO_ROOT / ANALYZER_PATH)},
        "accepted_B4C": {
            "status": b4c_result["status"],
            "orchestrator_verdict": "ACCEPT",
            "experiment_lock_sha256": reproduction["experiment_lock_sha256"],
            "prediction_set_sha256": reproduction["prediction_set_sha256_rebuilt_from_artifact_files"],
            "protocol_sha256": reproduction["protocol_sha256"],
            "full_model_schema_sha256": protocol.FULL_MODEL_SCHEMA_SHA256,
            "provider_projection_sha256": protocol.PROVIDER_PROJECTION_SHA256,
            "adapter_sha256": reproduction["adapter_sha256"],
            "prelive_commit": b4c_result["source_commit"],
            "executor_recommendation_threshold": "HISTORICAL_ADVISORY_ONLY_NOT_AN_ACCEPTANCE_GATE",
            "comparison_with_p3": {"label": "TUNING_COMPARISON_NOT_BLIND_VALIDATION",
                                   **{key: b4c_result["comparison_with_p3"][key]
                                      for key in ("p3_structural_valid", "p4_structural_valid")}},
        },
        "boundaries": {
            "provider_calls": 0, "model_calls": 0, "predictions_rerun": False, "repairs_issued": False,
            "DEV3_gold_opened": False, "holdout_opened": False, "semantic_scoring": False,
            "DEV3_input_use": "DETERMINISTIC_COMPILER_REPLAY_AND_OCCURRENCE_COUNTING_ONLY",
            "frozen_stack_modified": False, "original_predictions_modified": False,
            "B4C_records_modified": False, "new_acceptance_threshold_introduced": False,
            "redesign_implemented": False, "DEV4_created": False,
        },
        "reproduction": {
            **reproduction,
            "attempts_replayed": len(rows),
            "compiler_results_reproduced": True,
            "terminal_statuses_reproduced": metrics["totals"]["cases"],
            "compiled_batches_reproduced_byte_for_byte": metrics["totals"]["final_structural_valid_cases"],
            "stored_diagnostics_equal_sanitized_replayed_blockers": True,
            "instrumented_and_plain_compilation_agree": True,
        },
        "attempt_metrics": metrics,
        "quote_forensics": quote["public"],
        "canonical_conformance_forensics": canonical["public"],
        "repair_effectiveness": repairs["public"],
        "repair_diagnostic_audit": repairs["audit"],
        "contract_audit": audit,
        "counterfactuals": counter["public"],
        "root_cause_attribution": attribution,
        "alternative_explanations": {
            "D_DETERMINISTIC_COMPILER_DEFECT": {
                "supported": compiler_defect_evidence,
                "evidence": NO_COMPILER_DEFECT_EVIDENCE,
            },
            "E_CANONICAL_CONTRACT_MISMATCH": {
                "supported": False,
                "evidence": NO_CONTRACT_MISMATCH_EVIDENCE,
            },
            "F_EXECUTION_OR_SERIALIZATION_DEFECT": {
                "supported": False,
                "evidence": NO_EXECUTION_DEFECT_EVIDENCE,
            },
        },
        "limitations": list(LIMITATIONS),
        "decision": {
            "next_research_candidate": recommended,
            "recommendation_evidence": {name: RECOMMENDATIONS[name] for name in recommended if name in RECOMMENDATIONS},
            "not_recommended": dict(NOT_RECOMMENDED) if not compiler_defect_evidence else {},
            "implementation_authorized": False,
            "requires_orchestrator_authorization": True,
            "semantic_quality_claim": False,
        },
    }
    validate_public_record(record)
    return record


def validate_public_record(record: Any) -> None:
    """Allowlist check: fixed sections; every string is a structural token or a registered analyst sentence."""
    if not isinstance(record, Mapping) or tuple(record) != PUBLIC_SECTIONS:
        raise ForensicsError("Public record sections differ from the allowlist")

    def walk(node, path):
        if isinstance(node, Mapping):
            for key, value in node.items():
                if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_.:/<> -]{1,200}", key):
                    raise ForensicsError("Public record key is not public-safe: " + path)
                walk(value, f"{path}.{key}")
        elif isinstance(node, (list, tuple)):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")
        elif isinstance(node, str):
            if node not in PROSE and not _TOKEN.fullmatch(node) and not re.fullmatch(r"[A-Z0-9.][A-Z0-9 ./_-]{0,90}", node) \
                    and not re.fullmatch("[A-Z ]+ " + chr(0x2014) + " [A-Z ]+", node):
                raise ForensicsError("Public record value is not public-safe: " + path)
        elif node is not None and type(node) not in (bool, int, float):
            raise ForensicsError("Public record value type is not public-safe: " + path)

    walk(record, "$")
    boundaries = record["boundaries"]
    if (boundaries["provider_calls"], boundaries["model_calls"]) != (0, 0) or boundaries["DEV3_gold_opened"] \
            or boundaries["holdout_opened"] or boundaries["semantic_scoring"]:
        raise ForensicsError("Public record reports a boundary violation")


def write_public_record(record: Mapping[str, Any], path: Path = PUBLIC_RECORD_PATH) -> str:
    validate_public_record(record)
    data = yaml.safe_dump(dict(record), sort_keys=False, default_flow_style=False, width=118, allow_unicode=True)
    _write_bytes_atomic(path, data.encode("utf-8"))
    return sha256_bytes(data.encode("utf-8"))


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def forensic_layout(forensic_root: Path, private_root: Path) -> Path:
    root = forensic_root.resolve()
    repository = REPO_ROOT.resolve()
    if root == repository or (repository in root.parents and root.relative_to(repository).parts[0] != ".local"):
        raise ForensicsError("Forensic artifacts must live under ignored local storage")
    prediction_root = private_root.resolve()
    if root == prediction_root or prediction_root in root.parents or root in prediction_root.parents:
        raise ForensicsError("Forensic artifacts must not share storage with the prediction root")
    if any("gold" in part.lower() or "holdout" in part.lower() for part in root.parts[-2:]):
        raise ForensicsError("A gold or holdout location is not accepted")
    root.mkdir(parents=True, exist_ok=True)
    return root


def analyze(
    *,
    private_root: Path,
    input_archive: Path,
    forensic_root: Path,
    expected_input_sha256: str = b4c.DEV3_INPUT_SHA256,
    prediction_lock_path: Optional[Path] = None,
) -> dict[str, Any]:
    """The whole forensic pass. Reads the locked artifacts, writes only under the forensic root."""
    root = forensic_layout(forensic_root, private_root)
    before = prediction_root_fingerprint(private_root)
    reproduction, cases, locked = verify_locked_result(
        private_root=private_root, input_archive=input_archive, expected_input_sha256=expected_input_sha256,
        prediction_lock_path=prediction_lock_path,
    )
    rows = replay_attempts(cases, locked)
    quote = quote_forensics(rows)
    canonical = canonical_forensics(rows)
    repairs = repair_forensics(rows)
    audit = contract_audit()
    counter = counterfactuals(rows, canonical["private"])
    record = build_public_record(reproduction, rows, quote, canonical, repairs, audit, counter, locked["result"])
    if prediction_root_fingerprint(private_root) != before:
        raise IntegrityDefect("The prediction root changed during the forensic pass")
    private = {
        "attempt_matrix": [public_row(row) for row in rows],
        "quote_forensics": quote["private"],
        "canonical_conformance": canonical["private"],
        "repair_comparisons": repairs["private"],
        "counterfactuals": {"label": NON_PREDICTION_LABEL, **counter["private"]},
        "reproduction_report": reproduction,
    }
    for name, value in private.items():
        payload = {"artifact": f"M4_04B4CR_{name.upper()}_V1", "kind": "FORENSIC_DIAGNOSTIC_NOT_A_PREDICTION", "data": value}
        _write_bytes_atomic(root / f"{name}.json", canonical_json_bytes(payload))
    return {"record": record, "private": private}


def prediction_root_fingerprint(private_root: Path) -> str:
    """Hash of every prediction artifact, to prove the forensic pass changed none of them."""
    root = private_root.resolve()
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "session_progress.md":
            entries.append([path.relative_to(root).as_posix(), sha256_bytes(path.read_bytes())])
    return sha256_bytes(canonical_json_bytes(entries))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("analyze", "publish"))
    parser.add_argument("--input-archive", required=True, type=Path)
    parser.add_argument("--private-root", type=Path, default=b4c.DEFAULT_PRIVATE_ROOT)
    parser.add_argument("--forensic-root", type=Path, default=DEFAULT_FORENSIC_ROOT)
    args = parser.parse_args(argv)
    try:
        outcome = analyze(private_root=args.private_root, input_archive=args.input_archive,
                          forensic_root=args.forensic_root)
        record = outcome["record"]
        summary = {
            "status": record["status"],
            "prediction_set_sha256": record["accepted_B4C"]["prediction_set_sha256"],
            "attempts": record["attempt_metrics"]["totals"]["attempts"],
            "compiler_success": record["attempt_metrics"]["totals"]["compiler_success"],
            "compiler_failure": record["attempt_metrics"]["totals"]["compiler_failure"],
            "first_blocker_codes": record["attempt_metrics"]["totals"]["first_blocker_codes"],
            "provider_operations": 0,
        }
        if args.mode == "publish":
            summary["public_record_sha256"] = write_public_record(record)
        print(json.dumps(summary, sort_keys=True))
        return 0
    except IntegrityDefect as error:
        print(f"{STATUS_INTEGRITY_DEFECT}: {error}", flush=True)
        return 3
    except ReproductionDefect as error:
        print(f"{STATUS_REPRODUCTION_DEFECT}: {error}", flush=True)
        return 4
    except (ForensicsError, RuntimeError) as error:
        print(f"{STATUS_FAIL_CLOSED}: {type(error).__name__}", flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
