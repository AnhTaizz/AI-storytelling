"""Compile STORY_EXTRACTION_DRAFT_V1_2 (contextual anchors) to STORY_EXTRACTION_BATCH/v0.

The model supplies exact quotes and optional exact adjacent context; it never supplies
an occurrence, offset, hash or surface form. This compiler resolves every locator with
``contextual_anchor_resolver_v1``, fails closed on any NOT_FOUND, AMBIGUOUS or INVALID
locator, and then hands an internal V1.1-shaped draft, whose occurrences were computed
here, to the unchanged V1.1/V1 compilation path. After compilation it re-checks that
every canonical span and surface form equals the resolved source text.

Partial extraction is never produced: a case compiles completely or not at all.
Locators the model declares unresolved are not emitted; any reference to one is a
blocker. Compilation is serialized because the reused V1.1 diagnostics observer is
only safe for serial use.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Optional

from jsonschema import Draft202012Validator

from tools.story_extraction.contextual_anchor_resolver_v1 import (
    AMBIGUOUS,
    INVALID,
    NOT_FOUND,
    RESOLVED,
    RESOLVER_VERSION,
    candidate_starts,
    minimal_unique_context,
    occurrence_of,
    resolve_anchor,
)
from tools.story_extraction.draft_compiler_v1 import (
    DraftCompilationError,
    DraftCompilerContext,
    _context_maps,
    prepare_story_extraction_draft_v1,
)
from tools.story_extraction.draft_compiler_v1_1 import (
    DRAFT_VERSION as V1_1_DRAFT_VERSION,
    StructuralBlocker,
    collect_draft_structural_blockers_v1_1,
)
from tools.story_extraction.draft_v1_1_conformance_diagnostics_v1 import (
    compile_with_diagnostics_v1_1,
)


DRAFT_VERSION = "STORY_EXTRACTION_DRAFT_V1_2"
COMPILER_VERSION = "DRAFT_COMPILER_V1_2"
SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "schemas/story_extraction/story_extraction_draft_v1_2.schema.json"
)
LOCATOR_FIELDS = ("evidence", "mentions")
_STATUS_CODES = {
    NOT_FOUND: {"QUOTE_ABSENT": "LOCATOR_QUOTE_NOT_FOUND",
                "CONTEXT_MISMATCH": "LOCATOR_CONTEXT_MISMATCH"},
    AMBIGUOUS: {"MULTIPLE_CANDIDATES": "LOCATOR_AMBIGUOUS"},
    INVALID: {"INVALID_QUOTE": "LOCATOR_INVALID", "INVALID_CONTEXT": "LOCATOR_INVALID"},
}
_LOCAL_ID = re.compile(r"^draftv1-[0-9a-f]{24}-(.+)$")


class DraftCompilationErrorV1_2(DraftCompilationError):
    """Fail-closed V1.2 error carrying every feasible blocker and the locator report."""

    def __init__(self, blockers, report: dict[str, Any]):
        ordered = tuple(sorted(set(blockers)))
        if not ordered:
            raise ValueError("At least one structural blocker is required")
        self.blockers = ordered
        self.report = report
        super().__init__(ordered[0].code, ordered[0].path)


@dataclass(frozen=True)
class ResolvedLocator:
    handle: str
    field: str
    passage_handle: str
    start: int
    end: int
    occurrence: int
    candidate_count: int


def _validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def schema_blockers_v1_2(draft: Any) -> list[StructuralBlocker]:
    errors = sorted(_validator().iter_errors(draft),
                    key=lambda error: tuple(str(part) for part in error.absolute_path))
    return [StructuralBlocker("SCHEMA", "DRAFT_SCHEMA_FAILURE",
                              "/".join(map(str, error.absolute_path))) for error in errors]


def prepare_story_extraction_draft_v1_2(context: DraftCompilerContext) -> dict[str, Any]:
    """Model surface: passages and existing context; no locator metadata of any kind."""
    prepared = prepare_story_extraction_draft_v1(context)
    prepared["draft_version"] = DRAFT_VERSION
    for handle, record in prepared["existing_context"].items():
        if handle.startswith("M_EXISTING_") and isinstance(record, dict):
            record.pop("evidence_handle", None)
    return prepared


def _empty_report() -> dict[str, Any]:
    return {"compiler": COMPILER_VERSION, "resolver": RESOLVER_VERSION, "locators": [],
            "declared_unresolved": [], "advisories": [], "counts": {}}


def _declaration_check(text: str, quote: str, reason: str) -> str:
    starts = candidate_starts(text, quote)
    if not starts:
        return "QUOTE_ABSENT"
    if len(starts) == 1:
        return "UNIQUE_WITHOUT_CONTEXT"
    if reason == "REPEATED_IDENTICAL_CONTEXT":
        if all(minimal_unique_context(text, start, start + len(quote)) is not None
               for start in starts):
            return "UNIQUE_CONTEXT_AVAILABLE"
    return "CONSISTENT"


def resolve_locators_v1_2(draft: dict[str, Any], context: DraftCompilerContext
                          ) -> tuple[dict[str, ResolvedLocator], list[StructuralBlocker],
                                     dict[str, Any]]:
    """Resolve every emitted locator and check every unresolved declaration."""
    report = _empty_report()
    blockers: list[StructuralBlocker] = []
    try:
        passages, _ = _context_maps(context)
    except DraftCompilationError as error:
        return {}, [StructuralBlocker("CONTEXT", error.code, error.path)], report
    resolved: dict[str, ResolvedLocator] = {}
    for field in LOCATOR_FIELDS:
        for record in sorted(draft[field], key=lambda item: item["handle"]):
            handle, passage = record["handle"], record["passage_handle"]
            path = f"{field}/{handle}"
            entry = {"handle": handle, "field": field, "passage_handle": passage}
            if passage not in passages:
                blockers.append(StructuralBlocker("LOCATOR", "UNKNOWN_PASSAGE_HANDLE", path))
                entry.update(status=INVALID, detail="UNKNOWN_PASSAGE_HANDLE")
                report["locators"].append(entry)
                continue
            item, text = passages[passage]
            if item["use"] != "EVIDENCE_ELIGIBLE":
                blockers.append(StructuralBlocker("LOCATOR", "CONTEXT_ONLY_EVIDENCE", path))
                entry.update(status=INVALID, detail="CONTEXT_ONLY_PASSAGE")
                report["locators"].append(entry)
                continue
            result = resolve_anchor(text, record["quote"], record.get("context_before"),
                                    record.get("context_after"))
            entry.update(result.as_dict())
            report["locators"].append(entry)
            if result.status == RESOLVED:
                resolved[handle] = ResolvedLocator(
                    handle, field, passage, result.start, result.end,
                    occurrence_of(text, record["quote"], result.start), result.candidate_count)
            else:
                blockers.append(StructuralBlocker(
                    "LOCATOR", _STATUS_CODES[result.status][result.detail], path))
    emitted = {record["handle"] for field in LOCATOR_FIELDS for record in draft[field]}
    for record in sorted(draft["unresolved_locators"], key=lambda item: item["handle"]):
        handle, passage = record["handle"], record["passage_handle"]
        path = f"unresolved_locators/{handle}"
        if handle in emitted:
            blockers.append(StructuralBlocker("HANDLE", "DUPLICATE_HANDLE", path))
        if passage not in passages:
            blockers.append(StructuralBlocker("LOCATOR", "UNKNOWN_PASSAGE_HANDLE", path))
            check = "UNKNOWN_PASSAGE"
        else:
            check = _declaration_check(passages[passage][1], record["quote"], record["reason"])
        report["declared_unresolved"].append(
            {"handle": handle, "reason": record["reason"], "declaration_check": check})
    handles = [record["handle"] for record in draft["unresolved_locators"]]
    for handle in sorted({item for item in handles if handles.count(item) > 1}):
        blockers.append(StructuralBlocker("HANDLE", "DUPLICATE_HANDLE",
                                          f"unresolved_locators/{handle}"))
    return resolved, blockers, report


def to_internal_v1_1_draft(draft: dict[str, Any],
                           resolved: dict[str, ResolvedLocator]) -> dict[str, Any]:
    """V1.1-shaped draft whose occurrences are host-computed; no model positions survive."""
    internal = {key: deepcopy(value) for key, value in draft.items()
                if key not in {"draft_version", "unresolved_locators"}}
    internal["draft_version"] = V1_1_DRAFT_VERSION
    for field in LOCATOR_FIELDS:
        for record in internal[field]:
            record.pop("context_before", None)
            record.pop("context_after", None)
            locator = resolved.get(record["handle"])
            if locator is not None and locator.candidate_count > 1:
                record["occurrence"] = locator.occurrence
    return internal


def _value_at(draft: dict[str, Any], path: str) -> Any:
    parts = path.split("/")
    collection = draft.get(parts[0])
    if not isinstance(collection, list) or len(parts) < 2:
        return None
    value: Any = next((item for item in collection if item.get("handle") == parts[1]), None)
    for part in parts[2:]:
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return None
    return value


def _structural_blockers(internal: dict[str, Any], context: DraftCompilerContext,
                         unresolved: set[str]) -> list[StructuralBlocker]:
    out = []
    for blocker in collect_draft_structural_blockers_v1_1(internal, context):
        if blocker.phase == "QUOTE":
            continue  # superseded by the LOCATOR phase, which knows the context fields
        if _value_at(internal, blocker.path) in unresolved:
            out.append(StructuralBlocker("HANDLE", "REFERENCE_TO_UNRESOLVED_LOCATOR",
                                         blocker.path))
        else:
            out.append(blocker)
    return out


def _local(record_id: str) -> Optional[str]:
    match = _LOCAL_ID.match(record_id)
    return match.group(1) if match else None


def _post_invariants(batch: dict[str, Any], draft: dict[str, Any],
                     resolved: dict[str, ResolvedLocator],
                     context: DraftCompilerContext) -> list[StructuralBlocker]:
    """G1/G4: every compiled span and surface form equals the resolved source text."""
    passages, _ = _context_maps(context)
    records = batch["candidate_records"]
    evidence = {item["id"]: item for item in records["evidence_refs"]}
    by_local = {_local(item["id"]): item for item in records["evidence_refs"]}
    issues = []

    def expected_span(locator: ResolvedLocator) -> tuple[str, int, int]:
        item, _ = passages[locator.passage_handle]
        base = item["passage_ref"]["span"]["char_start"]
        return item["passage_ref"]["segment_id"], base + locator.start, base + locator.end

    def actual_span(ref: dict[str, Any]) -> tuple[str, int, int]:
        return ref["segment_id"], ref["span"]["char_start"], ref["span"]["char_end_exclusive"]

    for record in draft["evidence"]:
        ref = by_local.get(record["handle"])
        if ref is None or actual_span(ref) != expected_span(resolved[record["handle"]]):
            issues.append(StructuralBlocker("POST_INVARIANT", "GROUNDING_INVARIANT_VIOLATION",
                                            f"evidence/{record['handle']}"))
    mentions = {_local(item["id"]): item for item in records["mentions"]}
    for record in draft["mentions"]:
        mention = mentions.get(record["handle"])
        locator = resolved[record["handle"]]
        if (mention is None
                or actual_span(evidence[mention["evidence_ref_id"]]) != expected_span(locator)
                or mention["surface_form"] != passages[locator.passage_handle][1][
                    locator.start:locator.end]):
            issues.append(StructuralBlocker("POST_INVARIANT", "GROUNDING_INVARIANT_VIOLATION",
                                            f"mentions/{record['handle']}"))
    return issues


def grounding_advisories(batch: dict[str, Any]) -> list[dict[str, str]]:
    """Non-blocking: G5 co-location and mentions with no RefersTo."""
    records = batch["candidate_records"]
    evidence = {item["id"]: item for item in records["evidence_refs"]}
    mentions = {item["id"]: item for item in records["mentions"]}
    propositions = {item["id"]: item for item in records["propositions"]}
    linked: set[str] = set()
    advisories = []
    for assertion in records["assertions"]:
        proposition = propositions.get(assertion["proposition_id"])
        if not proposition or proposition.get("predicate") != "RefersTo":
            continue
        mention_id = proposition["args"]["mention"]["ref"]
        linked.add(mention_id)
        target = evidence[mentions[mention_id]["evidence_ref_id"]]
        covered = any(
            evidence[ref_id]["segment_id"] == target["segment_id"]
            and evidence[ref_id]["span"]["char_start"] <= target["span"]["char_start"]
            and target["span"]["char_end_exclusive"] <= evidence[ref_id]["span"]["char_end_exclusive"]
            for evidence_set in assertion["support"]["evidence_sets"]
            if evidence_set["label"] == "SUFFICIENT"
            for ref_id in evidence_set["evidence_ref_ids"]
        )
        if not covered:
            advisories.append({"code": "REFERSTO_EVIDENCE_NOT_COLOCATED",
                               "subject": _local(assertion["id"]) or "EXISTING_RECORD"})
    for mention_id in sorted(set(mentions) - linked):
        advisories.append({"code": "MENTION_WITHOUT_REFERSTO",
                           "subject": _local(mention_id) or "EXISTING_RECORD"})
    return sorted(advisories, key=lambda item: (item["code"], item["subject"]))


def _counts(report: dict[str, Any]) -> dict[str, int]:
    statuses = [item.get("status") for item in report["locators"]]
    return {
        "emitted_locators": len(statuses),
        "resolved": statuses.count(RESOLVED),
        "not_found": statuses.count(NOT_FOUND),
        "ambiguous": statuses.count(AMBIGUOUS),
        "invalid": statuses.count(INVALID),
        "declared_unresolved": len(report["declared_unresolved"]),
        # A declaration is unjustified when its quote is absent, or when it claims
        # identical context although a unique context of at most 32 code points exists
        # or the quote is unique. REFERENT_UNCERTAIN concerns linking, not location, so
        # a unique quote does not make it unjustified; it is counted separately.
        "declared_unresolved_unjustified": sum(
            item["declaration_check"] in {"QUOTE_ABSENT", "UNKNOWN_PASSAGE"}
            or (item["reason"] == "REPEATED_IDENTICAL_CONTEXT"
                and item["declaration_check"] != "CONSISTENT")
            for item in report["declared_unresolved"]),
        "declared_unresolved_referent_uncertain": sum(
            item["reason"] == "REFERENT_UNCERTAIN" for item in report["declared_unresolved"]),
    }


def compile_story_extraction_draft_v1_2(draft: Any, context: DraftCompilerContext
                                        ) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (canonical batch, locator report) or raise DraftCompilationErrorV1_2."""
    schema = schema_blockers_v1_2(draft)
    if schema:
        raise DraftCompilationErrorV1_2(schema, _empty_report())
    resolved, blockers, report = resolve_locators_v1_2(draft, context)
    report["counts"] = _counts(report)
    if any(blocker.phase == "CONTEXT" for blocker in blockers):
        raise DraftCompilationErrorV1_2(blockers, report)
    internal = to_internal_v1_1_draft(draft, resolved)
    unresolved = {record["handle"] for record in draft["unresolved_locators"]}
    blockers.extend(_structural_blockers(internal, context, unresolved))
    if blockers:
        raise DraftCompilationErrorV1_2(blockers, report)
    batch, diagnostics = compile_with_diagnostics_v1_1(internal, context)
    if batch is None:
        report["canonical_issue_classes"] = diagnostics["canonical_issue_classes"]
        raise DraftCompilationErrorV1_2(
            [StructuralBlocker(**item) for item in diagnostics["blockers"]], report)
    invariants = _post_invariants(batch, draft, resolved, context)
    if invariants:
        raise DraftCompilationErrorV1_2(invariants, report)
    report["advisories"] = grounding_advisories(batch)
    return batch, report
