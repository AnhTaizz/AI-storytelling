"""Source-text-free diagnostics for Draft V1.1 compilation failures.

``draft_compiler_v1`` reports a canonical failure as ``CANONICAL_CONFORMANCE_FAILURE``
with only the failing check-section names. This module observes the guarded batch
report that the frozen compiler already computes and classifies each issue into a
stable code with a local subject handle. It never changes the compile result: the
observer returns the identical report object to the compiler, and no frozen file is
edited. Issue text is discarded after classification because conformance messages can
echo model-authored values.
"""
from __future__ import annotations

from contextlib import contextmanager
import re
import threading
from typing import Any, Iterator, Mapping, Optional

from tools.story_extraction import draft_compiler_v1 as _compiler_v1
from tools.story_extraction.draft_compiler_v1 import DraftCompilerContext
from tools.story_extraction.draft_compiler_v1_1 import (
    DraftCompilationErrorV1_1,
    compile_story_extraction_draft_v1_1,
)


OBSERVER_VERSION = "DRAFT_V1_1_CANONICAL_REPORT_OBSERVER_V1"
_OBSERVER_LOCK = threading.Lock()
_LOCAL_ID = re.compile(r"^draftv1-[0-9a-f]{24}-(.+)$")

# Patterns follow tools/canonical_story/conformance_v0.py message templates.
_SEMANTIC_PATTERNS: tuple[tuple[str, str], ...] = (
    ("DUPLICATE_PROPOSITION_CONTENT", r"^duplicate concrete proposition content"),
    ("UNREGISTERED_EVENT_KIND", r"^event \S+ has unregistered event_kind"),
    ("FORBIDDEN_VERDICT_PREDICATE", r" uses forbidden stored verdict predicate "),
    ("UNREGISTERED_PREDICATE", r" uses unregistered predicate "),
    ("ARITY_MISMATCH", r" arity mismatch for "),
    ("ARGUMENT_KIND_MISMATCH", r"^proposition \S+ \S+\.\S+ kind \S+ != "),
    ("VOCABULARY_MISMATCH", r"^proposition \S+ \S+\.\S+ vocabulary \S+ != "),
    ("FORBIDDEN_VERDICT_VALUE", r" stores forbidden verdict "),
    ("TOKEN_NOT_IN_VOCABULARY", r"^proposition \S+ \S+\.\S+ value .+ not in \S+$"),
    ("LITERAL_TYPE_MISMATCH", r" literal type \S+ != "),
    ("ENTITY_KIND_NOT_ALLOWED", r" entity kind \S+ not in "),
    ("NON_GROUNDING_ROLE_IN_SUFFICIENT_SET", r" is SUFFICIENT but contains "),
    ("UNKNOWN_EVIDENCE_REF_IN_SET", r" evidence set \S+ references unknown evidence ref "),
    ("NO_SUPPORT_PATH", r" has no support path "),
    ("INCOMPLETE_SUPPORT_PATH", r" has no complete support path "),
    ("UNREGISTERED_DERIVATION_RULE", r" uses unregistered rule "),
    ("DERIVATION_PREMISE_MISSING", r" premise \S+ does not exist"),
    ("DERIVATION_SELF_PREMISE", r" uses itself as a premise"),
    ("DERIVATION_REJECTED_PREMISE", r" relies on REJECTED premise "),
    ("HOLDER_RELATIVE_CONTENT_CONCLUDED", r" concludes the embedded content of holder-relative"),
    ("RULE_CANNOT_CONCLUDE_PREDICATE", r" cannot conclude (?!attitude )\S+$"),
    ("RULE_CANNOT_CONCLUDE_ATTITUDE", r" cannot conclude attitude "),
    ("DERIVATION_MISSING_PREMISE_PREDICATES", r" lacks required premise predicates "),
    ("SIGNED_CONTENT_NOT_PRESERVED", r" does not preserve the signed content"),
    ("DERIVATION_CYCLE", r"^derivation cycle through "),
    ("VALIDITY_ON_NON_STATIVE_PREDICATE", r" has validity but predicate "),
    ("UNKNOWN_VALIDITY_ANCHOR", r" validity \S+ references unknown anchor "),
    ("BOUND_SUPPORT_INCOMPLETE", r" bound has support but no complete path"),
    ("VALIDITY_SAME_START_END_ANCHOR", r" validity starts and ends at the same anchor"),
    ("EXPLICIT_WITHOUT_DIRECT_EVIDENCE", r" is EXPLICIT without a complete direct evidence path"),
    ("STATUS_EXCEEDS_DERIVATION", r" status \S+ exceeds what its derivations support"),
    ("INTERNAL_STATE_EXPLICIT_WITHOUT_DEPICTION", r" states an internal state as EXPLICIT without "),
    ("DUPLICATE_ID", r"^duplicate id "),
    ("ANCHOR_EVENT_MISMATCH", r" is not an EVENT_TIME anchor of that event"),
    ("PROPOSITION_EMBEDDING_CYCLE", r"^proposition embedding cycle through "),
    ("POSITION_OUTSIDE_STREAM", r" position is outside the story discourse stream"),
    ("UNKNOWN_REFERENCE", r" references unknown "),
    ("CHECK_ABORTED_ON_UNRESOLVED_REFERENCE", r"^check aborted on unresolved reference"),
)
_SUBJECT = re.compile(
    r"^(?:assertion|proposition|event|anchor|mention|evidence ref|segment|source document) (\S+)"
)


def local_label(record_id: str) -> str:
    """Map a compiler-generated id to its draft handle; base records stay opaque."""
    match = _LOCAL_ID.match(record_id)
    return match.group(1) if match else "EXISTING_RECORD"


def classify_issue(check: str, issue: str) -> dict[str, str]:
    """Return a stable, text-free classification for one batch-report issue."""
    if check != "canonical":
        code = issue.split(":", 1)[0].strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", code):
            code = "UNCLASSIFIED"
        return {"check": check, "section": check, "code": code, "subject": ""}
    head, _, rest = issue.partition(": ")
    if head == "STRUCTURAL":
        path = rest.split(": ", 1)[0]
        return {
            "check": check,
            "section": "structural",
            "code": "CANONICAL_SCHEMA_VIOLATION",
            "subject": _sanitize_path(path),
        }
    section, message = head, rest
    for code, pattern in _SEMANTIC_PATTERNS:
        if re.search(pattern, message):
            subject = _SUBJECT.match(message)
            return {
                "check": check,
                "section": section,
                "code": code,
                "subject": local_label(subject.group(1)) if subject else "",
            }
    return {"check": check, "section": section, "code": "UNCLASSIFIED", "subject": ""}


def _sanitize_path(path: str) -> str:
    return "/".join(
        part if re.fullmatch(r"[A-Za-z_]+|[0-9]+", part) else "*" for part in path.split("/")
    )


def classify_report(report: Mapping[str, Any]) -> list[dict[str, str]]:
    found = []
    for check, result in sorted(report.get("checks", {}).items()):
        for issue in result.get("issues", []):
            found.append(classify_issue(check, str(issue)))
    unique = {tuple(sorted(item.items())) for item in found}
    return [dict(item) for item in sorted(unique)]


@contextmanager
def _observe_guarded_report() -> Iterator[list[Mapping[str, Any]]]:
    reports: list[Mapping[str, Any]] = []
    original = _compiler_v1.validate_batch_guarded

    def observer(batch: Any, base_document: Any, ingestion: Any) -> Any:
        report = original(batch, base_document, ingestion)
        reports.append(report)
        return report

    with _OBSERVER_LOCK:
        _compiler_v1.validate_batch_guarded = observer
        try:
            yield reports
        finally:
            _compiler_v1.validate_batch_guarded = original


def compile_with_diagnostics_v1_1(
    draft: Any, context: DraftCompilerContext
) -> tuple[Optional[dict[str, Any]], dict[str, Any]]:
    """Compile through the unchanged V1.1 path and return sanitized diagnostics."""
    with _observe_guarded_report() as reports:
        try:
            batch = compile_story_extraction_draft_v1_1(draft, context)
        except DraftCompilationErrorV1_1 as error:
            canonical = classify_report(reports[-1]) if reports else []
            return None, {
                "pass": False,
                "observer": OBSERVER_VERSION,
                "blockers": [blocker.as_dict() for blocker in error.blockers],
                "canonical_issue_classes": canonical,
            }
    return batch, {
        "pass": True,
        "observer": OBSERVER_VERSION,
        "blockers": [],
        "canonical_issue_classes": [],
    }
