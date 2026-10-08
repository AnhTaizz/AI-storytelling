"""Structural repair diagnostic V3.1 for the P4.1 candidate (M4-04B4D-F1). Offline design only.

V3.1 supersedes diagnostic V3 (M4-04B4D). V3 stays in the repository unchanged as the
historical record. V3 stated that a record handle is shown only when it matches the
frozen grammar and occurs exactly once in the draft, and did not hold to that in two
places: a DUPLICATE_HANDLE finding named the duplicated handle without an index, and
the final safety assertion accepted any grammar-valid handle without checking that it
was a record of the draft. No source text was shown to be disclosed. V3.1 corrects both.

Record identity. `record_index` and `record_handle` are a verified pair or both null.
The pair is set only when the handle matches the frozen grammar of its collection, is
the handle of exactly one record of that collection in the parsed draft, and that
record is at that index. Nothing else names a record. A duplicated handle identifies
no record, so it is never shown: the finding keeps the collection and the number of
records that share the handle. A handle in the detail of a finding is shown only when
it is a unique new record of the expected collection, or a handle of the expected type
in the host's existing context. A reference that cannot be verified that way produces
no independent finding at all; the compiler's own blocker for it is still reported.

Safety assertion. Every diagnostic is checked against an identity index the host builds
from the parsed draft and the compiler context. The check verifies the relations
between collection, index and handle, not only the characters of a handle. It fails
closed.

Completeness. `complete` is a conjunction of named statements, listed in
COMPLETENESS_FIELDS. It is true only when nothing is known to be missing. For a
rejected draft it is always false, because the frozen compiler exposes the names of
failed validator checks and not the validator's issues, so V3.1 cannot show that every
canonical issue was enumerated. Read the separate statements.

As in V3: the unchanged compiler is the acceptance authority and is never wrapped,
patched or overturned; for the three canonical rule classes seen in the M4-04B4C
forensics V3.1 checks the parsed draft against the frozen registry itself, read-only;
no quote, passage text, argument value, unexpected key or exception message is copied;
V3.1 never edits a draft and never chooses an occurrence, entity kind, rule or
predicate; it makes no provider call and reads no dataset.
"""
from __future__ import annotations

from dataclasses import dataclass
import functools
import hashlib
import json
import re
from typing import Any, Mapping, Optional

from tools.canonical_story.conformance_v0 import load_registry, proposition_signature
from tools.story_extraction import draft_compiler_v1 as compiler_v1
from tools.story_extraction import draft_compiler_v1_1 as compiler_v1_1
from tools.story_extraction import m4_04b4a_p4_output_contract_v1 as p4_contract
from tools.story_extraction import materialize_draft_v1_1_model_schema_v1 as materializer
from tools.story_extraction.extraction_contract_guard_v1 import CHECK_NAMES as VALIDATOR_CHECK_NAMES


DIAGNOSTIC_ID = "M4_P4_1_STRUCTURAL_REPAIR_DIAGNOSTIC_V3_1"
DIAGNOSTIC_FORMAT = "M4_P4_1_STRUCTURAL_DIAGNOSTIC_V3_1_FORMAT_1"
DIAGNOSTIC_PATH = "tools/story_extraction/m4_04b4d_f1_structural_diagnostic_v3_1.py"
SUPERSEDES_DIAGNOSTIC_ID = "M4_P4_1_STRUCTURAL_REPAIR_DIAGNOSTIC_V3"
MASK = "<UNVERIFIED>"
MAX_HANDLE_LENGTH = 40
MAX_ECHOED_OCCURRENCE = 1_000_000
MAX_PATH_INDEX_DIGITS = 6

# Draft collection -> definition of the model schema that owns its handle grammar.
COLLECTION_DEFINITIONS = {
    "evidence": "Evidence", "mentions": "Mention", "entities": "Entity", "events": "Event",
    "anchors": "TemporalAnchor", "propositions": "Proposition", "assertions": "Assertion",
}
CANONICAL_TO_DRAFT_COLLECTION = {canonical: draft for draft, canonical in compiler_v1.COLLECTIONS.items()}
PHASES = ("JSON", "SCHEMA", "HOST_CONTEXT", "QUOTE", "HANDLE", "REGISTRY", "CANONICAL", "COMPILER")
SOURCES = ("JSON_PARSER", "MODEL_SCHEMA_VALIDATOR", "FROZEN_COMPILER_BLOCKER", "INDEPENDENT_REGISTRY_CHECK")

# How a finding points at a record.
LOCATOR_VERIFIED = "VERIFIED_UNIQUE_RECORD"      # collection, index and handle, verified against the draft
LOCATOR_SCHEMA_PATH = "SCHEMA_PATH_INDEX"        # position from the schema validator's own path; no handle
LOCATOR_NOT_SCOPED = "NOT_RECORD_SCOPED"         # the finding is about the response, the root or a whole check
LOCATOR_UNAVAILABLE = "UNAVAILABLE"              # a record locator is required and could not be verified
LOCATOR_STATES = (LOCATOR_VERIFIED, LOCATOR_SCHEMA_PATH, LOCATOR_NOT_SCOPED, LOCATOR_UNAVAILABLE)

FINDING_FIELDS = (
    "phase", "code", "rule_class", "source", "compiler_reached", "repairable_by_model", "record_collection",
    "record_locator", "record_index", "record_handle", "schema_path", "validator_check", "validator_section",
    "structural_detail",
)
VERDICT_FIELDS = ("compiled", "compiler_blockers", "blocker_codes", "failed_validator_checks")
# Separate statements. `complete` is true only when every one of them is true.
COMPLETENESS_FIELDS = (
    "observed_blockers_preserved",                  # one finding for every blocker the parser, schema or compiler gave
    "observed_blockers_located",                    # every finding that needs a record has a verified locator
    "observed_blockers_attributed",                 # every finding has a recognized code and rule class
    "compiler_structural_rules_checked",            # the compiler ran its quote, handle and registry phases
    "canonical_validation_reached",                 # the compiler reached the canonical validator
    "downstream_canonical_issues_enumerated",       # every canonical issue is known to be listed
    "independent_checks_consistent_with_compiler",  # no independent check fired on a draft the compiler accepted
)
ENVELOPE_FIELDS = (
    "diagnostic", "format", "model_schema", "category", "compiler_verdict", "completeness", "complete",
    "limitations", "finding_count", "findings",
)
CATEGORIES = (None, "JSON_PARSE_FAILURE", "DRAFT_SCHEMA_FAILURE", "DRAFT_COMPILER_FAILURE")

CANONICAL_FAILURE = "CANONICAL_CONFORMANCE_FAILURE"
RULE_CLASS_CANONICAL_UNRECOGNIZED = "UNRECOGNIZED_CANONICAL_RULE"
RULE_CLASS_CANONICAL_EXPLAINED = "CANONICAL_CHECK_FAILED_SEE_INDEPENDENT_FINDINGS"
# code -> (phase, rule class, validator check, validator section, repairable by the model)
RULE_TAXONOMY = {
    "JSON_PARSE_FAILURE": ("JSON", "RESPONSE_IS_NOT_ONE_JSON_VALUE", None, None, True),
    "DRAFT_SCHEMA_FAILURE": ("SCHEMA", "MODEL_SCHEMA_RULE", None, None, True),
    "AMBIGUOUS_QUOTE": ("QUOTE", "QUOTE_REPEATED_OCCURRENCE_MISSING", None, None, True),
    "QUOTE_NOT_FOUND": ("QUOTE", "QUOTE_NOT_AN_EXACT_SUBSTRING_OF_THE_PASSAGE", None, None, True),
    "OCCURRENCE_OUT_OF_RANGE": ("QUOTE", "OCCURRENCE_EXCEEDS_THE_EXACT_MATCH_COUNT", None, None, True),
    "UNKNOWN_PASSAGE_HANDLE": ("QUOTE", "PASSAGE_HANDLE_NOT_SUPPLIED_BY_THE_HOST", None, None, True),
    "CONTEXT_ONLY_EVIDENCE": ("QUOTE", "PASSAGE_IS_NOT_EVIDENCE_ELIGIBLE", None, None, True),
    "UNKNOWN_HANDLE": ("HANDLE", "REFERENCED_HANDLE_DOES_NOT_EXIST", None, None, True),
    "HANDLE_TYPE_MISMATCH": ("HANDLE", "REFERENCED_HANDLE_HAS_THE_WRONG_RECORD_TYPE", None, None, True),
    "DUPLICATE_HANDLE": ("HANDLE", "HANDLE_USED_FOR_MORE_THAN_ONE_RECORD", None, None, True),
    "PRIOR_CONTEXT_NOT_EVIDENCE": ("HANDLE", "SUPPORT_CITES_EVIDENCE_NOT_DECLARED_IN_THIS_DRAFT", None, None, True),
    "UNREGISTERED_PREDICATE": ("REGISTRY", "PREDICATE_NOT_IN_THE_REGISTRY", None, None, True),
    "UNREGISTERED_EVENT_KIND": ("REGISTRY", "EVENT_KIND_NOT_IN_THE_REGISTRY", None, None, True),
    "UNREGISTERED_RULE": ("REGISTRY", "DERIVATION_RULE_NOT_IN_THE_REGISTRY", None, None, True),
    "ARGUMENT_ENTITY_KIND_NOT_ALLOWED": (
        "CANONICAL", "ARGUMENT_ENTITY_KIND_NOT_ALLOWED", "canonical", "predicate_integrity", True),
    "RULE_CANNOT_CONCLUDE_PREDICATE": (
        "CANONICAL", "RULE_CANNOT_CONCLUDE_PREDICATE", "canonical", "derivation_integrity", True),
    "DUPLICATE_CONCRETE_PROPOSITION_CONTENT": (
        "CANONICAL", "DUPLICATE_CONCRETE_PROPOSITION_CONTENT", "canonical", "predicate_integrity", True),
    CANONICAL_FAILURE: ("CANONICAL", RULE_CLASS_CANONICAL_UNRECOGNIZED, None, None, True),
    "CANONICAL_VALIDATOR_EXCEPTION": ("CANONICAL", "CANONICAL_VALIDATOR_DID_NOT_COMPLETE", None, None, False),
    "MENTION_EVIDENCE_MISMATCH": ("COMPILER", "COMPILER_BINDING_FAILURE", None, None, False),
    "UNKNOWN_EVIDENCE_HANDLE": ("COMPILER", "COMPILER_BINDING_FAILURE", None, None, False),
    "ID_COLLISION": ("COMPILER", "COMPILER_BINDING_FAILURE", None, None, False),
    "EMPTY_SCOPE": ("HOST_CONTEXT", "HOST_CONTEXT_ERROR", None, None, False),
    "EXACT_SOURCE_REQUIRED": ("HOST_CONTEXT", "HOST_CONTEXT_ERROR", None, None, False),
    "INVALID_AS_OF": ("HOST_CONTEXT", "HOST_CONTEXT_ERROR", None, None, False),
    "INVALID_BASE": ("HOST_CONTEXT", "HOST_CONTEXT_ERROR", None, None, False),
    "INVALID_PASSAGE_INPUT": ("HOST_CONTEXT", "HOST_CONTEXT_ERROR", None, None, False),
}
UNRECOGNIZED_CODE = "UNRECOGNIZED_COMPILER_CODE"
OBSERVED_RULE_CLASSES = (
    "AMBIGUOUS_QUOTE", "ARGUMENT_ENTITY_KIND_NOT_ALLOWED", "RULE_CANNOT_CONCLUDE_PREDICATE",
    "DUPLICATE_CONCRETE_PROPOSITION_CONTENT",
)
INDEPENDENTLY_CHECKED_CANONICAL_RULES = OBSERVED_RULE_CLASSES[1:]
# Compiler phases whose blockers are about one record, so a record locator is required.
RECORD_SCOPED_PHASES = ("QUOTE", "HANDLE", "REGISTRY")

LIMIT_COMPILER_NOT_REACHED = "THE_COMPILER_DID_NOT_CHECK_ITS_QUOTE_HANDLE_AND_REGISTRY_RULES"
LIMIT_CANONICAL_NOT_REACHED = "CANONICAL_VALIDATION_WAS_NOT_REACHED_BY_THE_COMPILER"
LIMIT_CANONICAL_NOT_ENUMERATED = "CANONICAL_ISSUES_OUTSIDE_THE_CHECKED_RULE_CLASSES_ARE_NOT_ENUMERATED"
LIMIT_CANONICAL_UNRECOGNIZED = "A_CANONICAL_FAILURE_COULD_NOT_BE_ATTRIBUTED_TO_A_KNOWN_RULE_CLASS"
LIMIT_LOCATOR = "A_RECORD_COULD_NOT_BE_IDENTIFIED_SAFELY"
LIMIT_HOST_SIDE = "A_FAILURE_IS_ON_THE_HOST_SIDE_AND_IS_NOT_REPAIRABLE_BY_THE_MODEL"
LIMIT_UNRECOGNIZED_CODE = "A_COMPILER_CODE_IS_NOT_IN_THE_V3_1_TAXONOMY"
LIMIT_SCHEMA_UNDESCRIBED = "A_SCHEMA_REJECTION_COULD_NOT_BE_DESCRIBED_FROM_THE_MODEL_SCHEMA"
LIMIT_CHECK_DISAGREEMENT = "AN_INDEPENDENT_CHECK_DISAGREED_WITH_THE_COMPILER_AND_WAS_DISCARDED"
LIMITATIONS = (
    LIMIT_COMPILER_NOT_REACHED, LIMIT_CANONICAL_NOT_REACHED, LIMIT_CANONICAL_NOT_ENUMERATED,
    LIMIT_CANONICAL_UNRECOGNIZED, LIMIT_LOCATOR, LIMIT_HOST_SIDE, LIMIT_UNRECOGNIZED_CODE,
    LIMIT_SCHEMA_UNDESCRIBED, LIMIT_CHECK_DISAGREEMENT,
)

QUOTE_DETAIL_KEYS = (
    "passage_handle", "passage_use", "exact_match_count", "occurrence_present", "occurrence_required",
    "occurrence_given", "valid_occurrence_minimum", "valid_occurrence_maximum", "quote_code_points",
    "passage_supplied_by_host", "supplied_passage_count",
)
DETAIL_KEYS = frozenset(QUOTE_DETAIL_KEYS + (
    "records_sharing_this_handle", "failed_validator_checks", "independent_findings_for_the_canonical_check",
    "predicate", "argument", "argument_kind", "allowed_entity_kinds", "referenced_entity_kind",
    "referenced_record_handle", "referenced_record_is_existing", "rule_id", "derivation_index",
    "assertion_predicate", "assertion_proposition_is_placeholder", "allowed_conclusion_predicates",
    "identical_to_record_handle", "identical_to_existing_record", "json_error_class", "line", "column",
))
# Detail key that carries a handle -> (detail key saying whether it is existing context, expected collection).
REFERENCE_KEYS = {
    "referenced_record_handle": ("referenced_record_is_existing", "entities"),
    "identical_to_record_handle": ("identical_to_existing_record", "propositions"),
}
HANDLE_KEYS = frozenset({"record_handle", "passage_handle", *REFERENCE_KEYS})
V2_SCHEMA_KEYS = frozenset({
    "phase", "code", "path", "schema_keyword", "missing_required_fields", "allowed_fields",
    "unexpected_field_count", "expected_type", "allowed_enum_tokens", "required_constant", "required_pattern",
    "limit", "variants", "forbidden_fields", "required_fields", "fixed_values", "findings",
})
V2_MASK = "<UNRECOGNIZED_KEY>"


class DiagnosticV31Error(RuntimeError):
    """The diagnostic failed its own safety assertion. Fail closed."""


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")


def diagnostic_sha256(diagnostic: Mapping[str, Any]) -> str:
    """Identity of a diagnostic: its canonical bytes. No clock, no random value, no path."""
    return hashlib.sha256(canonical_json_bytes(diagnostic)).hexdigest()


# ---------------------------------------------------------------------------
# Verified record identity
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def handle_patterns() -> dict[str, re.Pattern]:
    """Handle grammar of every draft collection, read from the frozen model schema."""
    definitions = materializer.load_tracked_model_schema()["$defs"]
    patterns = {}
    for collection, name in COLLECTION_DEFINITIONS.items():
        definition = definitions[name]
        owner = definition["oneOf"][0] if "oneOf" in definition else definition
        patterns[collection] = re.compile(owner["properties"]["handle"]["pattern"])
    patterns["*"] = re.compile(definitions["Handle"]["pattern"])
    return patterns


def is_safe_handle(handle: Any, collection: str = "*") -> bool:
    """The handle matches the frozen grammar and can carry nothing else. Grammar only: not membership."""
    return (
        isinstance(handle, str)
        and 0 < len(handle) <= MAX_HANDLE_LENGTH
        and handle.isascii()
        and handle.isprintable()
        and not any(character.isspace() for character in handle)
        and collection in handle_patterns()
        and handle_patterns()[collection].fullmatch(handle) is not None
    )


@dataclass(frozen=True)
class IdentityIndex:
    """What the host can vouch for: which record handles exist, where, and how often.

    records   draft collection -> one entry per record position: the record's handle when it
              matches the grammar of that collection, otherwise None.
    existing  existing-context handle -> the draft collection of the record it names.
    passages  the passage handles the host supplied.
    """
    records: Mapping[str, tuple]
    existing: Mapping[str, str]
    passages: frozenset

    def size(self, collection: Any) -> int:
        return len(self.records.get(collection, ())) if isinstance(collection, str) else 0

    def count(self, collection: Any, handle: Any) -> int:
        if not isinstance(collection, str) or not isinstance(handle, str):
            return 0
        return sum(entry == handle for entry in self.records.get(collection, ()))

    def unique_index(self, collection: Any, handle: Any) -> Optional[int]:
        """Position of the one record of the collection with this handle, or None. Never guesses."""
        if not is_safe_handle(handle, collection) or self.count(collection, handle) != 1:
            return None
        return self.records[collection].index(handle)

    def is_existing(self, handle: Any, collection: str) -> bool:
        return isinstance(handle, str) and is_safe_handle(handle) and self.existing.get(handle) == collection


def _context_view(compiler_context: Any) -> tuple[dict, dict]:
    """The host's passages and existing-context handles, or nothing when the context is unusable."""
    try:
        passages, existing = compiler_v1._context_maps(compiler_context)
    except (compiler_v1.DraftCompilationError, AttributeError, TypeError):
        return {}, {}
    return passages, existing


def _identity(draft: Any, passages: Mapping[str, Any], existing: Mapping[str, Any]) -> IdentityIndex:
    records = {}
    for collection in COLLECTION_DEFINITIONS:
        entries = draft.get(collection) if isinstance(draft, dict) else None
        records[collection] = tuple(
            entry["handle"] if isinstance(entry, dict) and is_safe_handle(entry.get("handle"), collection) else None
            for entry in entries
        ) if isinstance(entries, list) else ()
    known = {}
    for handle, (canonical, _) in existing.items():
        if is_safe_handle(handle) and canonical in CANONICAL_TO_DRAFT_COLLECTION:
            known[handle] = CANONICAL_TO_DRAFT_COLLECTION[canonical]
    return IdentityIndex(records, known, frozenset(handle for handle in passages if is_safe_handle(handle)))


def build_identity_index(draft: Any, compiler_context: Any) -> IdentityIndex:
    """The identity index for one parsed draft and one compiler context. Reads nothing else."""
    return _identity(draft, *_context_view(compiler_context))


def _locator(collection: Optional[str], state: str, index: Optional[int] = None,
             handle: Optional[str] = None) -> dict[str, Any]:
    return {"record_collection": collection, "record_locator": state, "record_index": index, "record_handle": handle}


def locate_record(identity: IdentityIndex, collection: Any, handle: Any) -> dict[str, Any]:
    """A verified collection/index/handle triple for one record, or an unavailable locator. Never guesses."""
    if collection not in COLLECTION_DEFINITIONS:
        return _locator(None, LOCATOR_UNAVAILABLE)
    index = identity.unique_index(collection, handle)
    if index is None:
        return _locator(collection, LOCATOR_UNAVAILABLE)
    return _locator(collection, LOCATOR_VERIFIED, index, handle)


def _finding(code: str, *, source: str, compiler_reached: bool, locator: Optional[Mapping[str, Any]] = None,
             schema_path: Optional[str] = None, detail: Optional[Mapping[str, Any]] = None,
             validator_check: Optional[str] = None, rule_class: Optional[str] = None) -> dict[str, Any]:
    recognized = code in RULE_TAXONOMY
    phase, taxonomy_class, check, section, repairable = RULE_TAXONOMY.get(
        code, ("COMPILER", UNRECOGNIZED_CODE, None, None, False))
    if locator is None:
        # A blocker about one record with no usable path still needs a record: say that it is unavailable.
        locator = _locator(None, LOCATOR_UNAVAILABLE if phase in RECORD_SCOPED_PHASES else LOCATOR_NOT_SCOPED)
    return {
        "phase": phase,
        "code": code if recognized else UNRECOGNIZED_CODE,
        "rule_class": rule_class or taxonomy_class,
        "source": source,
        "compiler_reached": compiler_reached,
        "repairable_by_model": repairable,
        "record_collection": locator["record_collection"],
        "record_locator": locator["record_locator"],
        "record_index": locator["record_index"],
        "record_handle": locator["record_handle"],
        "schema_path": schema_path,
        "validator_check": validator_check if validator_check is not None else check,
        "validator_section": section,
        "structural_detail": dict(detail or {}),
    }


def _safe_schema_path(parts: list[str], locator: Mapping[str, Any]) -> str:
    """collection/index/schema-owned fields. A part that is not schema- or registry-owned is masked."""
    vocabulary = p4_contract.path_vocabulary()
    safe = [locator["record_collection"] or MASK,
            str(locator["record_index"]) if locator["record_index"] is not None else MASK]
    for part in parts:
        numeric = part.isascii() and part.isdigit() and len(part) <= MAX_PATH_INDEX_DIGITS
        safe.append(part if numeric or part in vocabulary else MASK)
    return "/".join(safe)


# ---------------------------------------------------------------------------
# Findings from the compiler's own structured blockers
# ---------------------------------------------------------------------------

def _quote_finding(blocker: Mapping[str, str], draft: Mapping[str, Any], identity: IdentityIndex,
                   passages: Mapping[str, Any]) -> dict[str, Any]:
    field, _, handle = blocker["path"].partition("/")
    locator = locate_record(identity, field, handle)
    detail: dict[str, Any] = {}
    if locator["record_locator"] == LOCATOR_VERIFIED:
        record = draft[field][locator["record_index"]]
        passage_handle = record.get("passage_handle")
        if passage_handle in identity.passages:
            item, text = passages[passage_handle]
            count = len(compiler_v1._occurrences(text, record["quote"]))
            detail = {
                "passage_handle": passage_handle,
                "passage_use": item["use"],
                "exact_match_count": count,
                "occurrence_present": "occurrence" in record,
                "occurrence_required": count > 1,
                "quote_code_points": len(record["quote"]),
            }
            if count >= 1:
                detail["valid_occurrence_minimum"] = 1
                detail["valid_occurrence_maximum"] = count
            given = record.get("occurrence")
            if blocker["code"] == "OCCURRENCE_OUT_OF_RANGE" and type(given) is int and 1 <= given <= MAX_ECHOED_OCCURRENCE:
                detail["occurrence_given"] = given
        else:
            detail = {"passage_supplied_by_host": False, "supplied_passage_count": len(identity.passages)}
    return _finding(blocker["code"], source="FROZEN_COMPILER_BLOCKER", compiler_reached=True, locator=locator,
                    schema_path=_safe_schema_path([], locator), detail=detail)


def _duplicate_handle_finding(blocker: Mapping[str, str], identity: IdentityIndex) -> dict[str, Any]:
    """A duplicated handle names no single record. Keep the collection and the count; show no handle."""
    owners = [(collection, identity.count(collection, blocker["path"])) for collection in COLLECTION_DEFINITIONS]
    owners = [(collection, count) for collection, count in owners if count >= 2]
    if len(owners) != 1:
        return _finding(blocker["code"], source="FROZEN_COMPILER_BLOCKER", compiler_reached=True,
                        locator=_locator(None, LOCATOR_UNAVAILABLE))
    collection, count = owners[0]
    locator = _locator(collection, LOCATOR_UNAVAILABLE)
    return _finding(blocker["code"], source="FROZEN_COMPILER_BLOCKER", compiler_reached=True, locator=locator,
                    schema_path=_safe_schema_path([], locator), detail={"records_sharing_this_handle": count})


def _path_finding(blocker: Mapping[str, str], identity: IdentityIndex) -> dict[str, Any]:
    if blocker["code"] == "DUPLICATE_HANDLE":
        return _duplicate_handle_finding(blocker, identity)
    parts = blocker["path"].split("/") if blocker["path"] else []
    locator = locate_record(identity, parts[0], parts[1]) if len(parts) >= 2 else _locator(None, LOCATOR_UNAVAILABLE)
    path = _safe_schema_path(parts[2:], locator) if locator["record_collection"] else None
    return _finding(blocker["code"], source="FROZEN_COMPILER_BLOCKER", compiler_reached=True, locator=locator,
                    schema_path=path)


def _canonical_blocker_finding(blocker: Mapping[str, str], independent_count: int) -> dict[str, Any]:
    """One finding for the compiler's own canonical blocker. It is kept even when independent findings explain it."""
    if blocker["code"] != CANONICAL_FAILURE:
        return _finding(blocker["code"], source="FROZEN_COMPILER_BLOCKER", compiler_reached=True)
    checks = sorted({name if name in VALIDATOR_CHECK_NAMES else MASK for name in blocker["path"].split(",") if name})
    explained = checks == ["canonical"] and independent_count > 0
    return _finding(
        CANONICAL_FAILURE, source="FROZEN_COMPILER_BLOCKER", compiler_reached=True,
        validator_check=checks[0] if len(checks) == 1 else None,
        rule_class=RULE_CLASS_CANONICAL_EXPLAINED if explained else RULE_CLASS_CANONICAL_UNRECOGNIZED,
        detail={"failed_validator_checks": checks,
                "independent_findings_for_the_canonical_check": independent_count if "canonical" in checks else 0})


# ---------------------------------------------------------------------------
# Independent read-only registry checks (the three canonical rule classes)
# ---------------------------------------------------------------------------

def registry_rule_findings(draft: Mapping[str, Any], context: Any, identity: IdentityIndex,
                           existing: Mapping[str, Any], *, compiler_reached: bool) -> list[dict[str, Any]]:
    """Mirror three rules of the frozen canonical validator on the parsed draft. Read-only.

    Each rule is applied under the same preconditions the validator uses, so a finding here
    is a violation the validator reports once it is reached. Nothing is corrected. Only
    records and references the identity index can verify take part: a record whose handle
    is duplicated is skipped, because the compiler stops at the duplicate and no single
    record can be named.
    """
    registry = load_registry()
    base = context.base_document
    base_entities = {record["id"]: record for record in base["entities"]}
    base_propositions = {record["id"]: record for record in base["propositions"]}
    forbidden = set(registry["forbidden_stored_verdicts"])
    entity_kinds = set(materializer.load_tracked_model_schema()["$defs"]["EntityKind"]["enum"])

    def unique_records(collection: str):
        for index, record in enumerate(draft[collection]):
            if identity.unique_index(collection, identity.records[collection][index]) == index:
                yield index, record

    def new_record(collection: str, handle: Any) -> Optional[Mapping[str, Any]]:
        index = identity.unique_index(collection, handle)
        return None if index is None else draft[collection][index]

    def existing_record(collection: str, handle: Any, base_records: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
        return base_records.get(existing[handle][1]) if identity.is_existing(handle, collection) else None

    findings: list[dict[str, Any]] = []

    # 1. Referenced entity kind allowed by the registry for the argument.
    for index, proposition in unique_records("propositions"):
        predicate = proposition.get("predicate")
        spec = registry["predicates"].get(predicate) if isinstance(predicate, str) else None
        if spec is None or predicate.upper() in forbidden:
            continue
        expected = {argument["name"]: argument for argument in spec["args"]}
        if set(proposition["args"]) != set(expected):
            continue
        for name in sorted(proposition["args"]):
            argument, want = proposition["args"][name], expected[name]
            if argument["kind"] != want["kind"] or want["kind"] != "ENTITY" or not want.get("entity_kinds"):
                continue
            handle = argument.get("handle")
            entity, is_existing = new_record("entities", handle), False
            if entity is None:
                entity, is_existing = existing_record("entities", handle, base_entities), True
            if entity is None or entity.get("kind") in want["entity_kinds"]:
                continue  # an unverifiable reference is another blocker; the kind cannot be decided
            locator = _locator("propositions", LOCATOR_VERIFIED, index, proposition["handle"])
            detail = {
                "predicate": predicate, "argument": name, "argument_kind": "ENTITY",
                "allowed_entity_kinds": list(want["entity_kinds"]),
                "referenced_record_is_existing": is_existing,
                "referenced_record_handle": handle,
            }
            if entity.get("kind") in entity_kinds:
                detail["referenced_entity_kind"] = entity["kind"]
            findings.append(_finding(
                "ARGUMENT_ENTITY_KIND_NOT_ALLOWED", source="INDEPENDENT_REGISTRY_CHECK",
                compiler_reached=compiler_reached, locator=locator,
                schema_path=_safe_schema_path(["args", name], locator), detail=detail))

    # 2. Derivation rule may conclude the predicate of the assertion it supports.
    for index, assertion in unique_records("assertions"):
        handle = assertion.get("proposition_handle")
        proposition = new_record("propositions", handle) or existing_record("propositions", handle, base_propositions)
        if proposition is None:
            continue
        predicate = proposition.get("predicate")
        for position, derivation in enumerate(assertion["support"]["derivations"]):
            rule = registry["derivation_rules"].get(derivation.get("rule_id"))
            if rule is None or predicate in rule["conclusion_predicates"]:
                continue
            locator = _locator("assertions", LOCATOR_VERIFIED, index, assertion["handle"])
            detail = {
                "rule_id": derivation["rule_id"], "derivation_index": position,
                "allowed_conclusion_predicates": list(rule["conclusion_predicates"]),
                "assertion_proposition_is_placeholder": predicate is None,
            }
            if predicate in registry["predicates"]:
                detail["assertion_predicate"] = predicate
            findings.append(_finding(
                "RULE_CANNOT_CONCLUDE_PREDICATE", source="INDEPENDENT_REGISTRY_CHECK",
                compiler_reached=compiler_reached, locator=locator,
                schema_path=_safe_schema_path(["support", "derivations", str(position), "rule_id"], locator),
                detail=detail))

    # 3. Concrete propositions with identical content.
    unique_new = {handle for collection in COLLECTION_DEFINITIONS for handle in identity.records[collection]
                  if identity.unique_index(collection, handle) is not None}

    def signature(proposition: Mapping[str, Any], is_new: bool) -> Optional[str]:
        if proposition.get("placeholder") or "predicate" not in proposition:
            return None
        arguments = {}
        for name, argument in proposition["args"].items():
            if is_new and "handle" in argument:
                handle = argument["handle"]
                if identity.existing.get(handle) is not None:
                    reference = existing[handle][1]
                elif handle in unique_new:
                    reference = "#new#" + handle
                else:
                    return None  # an unverifiable handle is another blocker; identity cannot be decided
                arguments[name] = {"kind": argument["kind"], "ref": reference}
            else:
                arguments[name] = argument
        return proposition_signature({"predicate": proposition["predicate"], "args": arguments})

    reverse = {record_id: handle for handle, (canonical, record_id) in existing.items()
               if identity.is_existing(handle, "propositions")}
    seen: dict[str, tuple[str, bool]] = {}
    for record_id in sorted(base_propositions):
        key = signature(base_propositions[record_id], False)
        if key is not None and record_id in reverse:
            seen.setdefault(key, (reverse[record_id], True))
    for handle, index, proposition in sorted(
            (proposition["handle"], index, proposition) for index, proposition in unique_records("propositions")):
        key = signature(proposition, True)
        if key is None:
            continue
        if key not in seen:
            seen[key] = (handle, False)
            continue
        first, first_is_existing = seen[key]
        locator = _locator("propositions", LOCATOR_VERIFIED, index, handle)
        findings.append(_finding(
            "DUPLICATE_CONCRETE_PROPOSITION_CONTENT", source="INDEPENDENT_REGISTRY_CHECK",
            compiler_reached=compiler_reached, locator=locator, schema_path=_safe_schema_path([], locator),
            detail={"identical_to_existing_record": first_is_existing, "identical_to_record_handle": first}))
    return findings


# ---------------------------------------------------------------------------
# The diagnostic
# ---------------------------------------------------------------------------

def _schema_envelope_findings(draft: Any, identity: IdentityIndex) -> list[dict[str, Any]]:
    findings = []
    for item in p4_contract.schema_findings(draft):
        parts = item["path"].split("/")
        locator = _locator(None, LOCATOR_NOT_SCOPED)
        if parts[0] in COLLECTION_DEFINITIONS:
            collection = parts[0]
            locator = _locator(collection, LOCATOR_NOT_SCOPED)
            position = int(parts[1]) if len(parts) > 1 and parts[1].isascii() and parts[1].isdigit() \
                and len(parts[1]) <= MAX_PATH_INDEX_DIGITS else None
            if position is not None and position < identity.size(collection):
                handle = identity.records[collection][position]
                if identity.unique_index(collection, handle) == position:
                    locator = _locator(collection, LOCATOR_VERIFIED, position, handle)
                else:
                    locator = _locator(collection, LOCATOR_SCHEMA_PATH)
        detail = {key: value for key, value in item.items() if key not in ("phase", "code", "path")}
        findings.append(_finding("DRAFT_SCHEMA_FAILURE", source="MODEL_SCHEMA_VALIDATOR", compiler_reached=False,
                                 locator=locator, schema_path=item["path"], detail=detail))
    return findings


def _order(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic order. Nothing is merged: two findings that look alike are still two blockers."""
    collections = list(COLLECTION_DEFINITIONS)

    def key(finding: Mapping[str, Any]):
        collection = finding["record_collection"]
        return (
            PHASES.index(finding["phase"]),
            collections.index(collection) if collection in collections else len(collections),
            finding["record_index"] if finding["record_index"] is not None else 10 ** 9,
            finding["code"], finding["schema_path"] or "", canonical_json_bytes(finding["structural_detail"]),
        )

    return sorted(findings, key=key)


def structural_diagnostic_v3_1(raw_response: Any, compiler_context: Any) -> dict[str, Any]:
    """The complete V3.1 diagnostic for one response. The unchanged compiler decides validity."""
    findings: list[dict[str, Any]] = []
    limitations: set[str] = set()
    verdict = {"compiled": False, "compiler_blockers": 0, "blocker_codes": [], "failed_validator_checks": []}
    state = {"compiler_structural_rules_checked": False, "canonical_validation_reached": False,
             "independent_checks_consistent_with_compiler": True}
    passages, existing = _context_view(compiler_context)
    try:
        draft = json.loads(raw_response)
    except (TypeError, json.JSONDecodeError):
        item = p4_contract.json_error_diagnostic(raw_response)
        detail = {key: item[key] for key in ("json_error_class", "line", "column")}
        category, draft = "JSON_PARSE_FAILURE", None
        identity = _identity(None, passages, existing)
        findings.append(_finding("JSON_PARSE_FAILURE", source="JSON_PARSER", compiler_reached=False,
                                 schema_path="$", detail=detail))
    else:
        identity = _identity(draft, passages, existing)
        try:
            compiler_v1_1.validate_draft_v1_1(draft)
            schema_valid = True
        except compiler_v1_1.DraftCompilationErrorV1_1:
            schema_valid = False
        if not schema_valid:
            category = "DRAFT_SCHEMA_FAILURE"
            findings = _schema_envelope_findings(draft, identity)
            if not findings:
                limitations.add(LIMIT_SCHEMA_UNDESCRIBED)
                findings.append(_finding("DRAFT_SCHEMA_FAILURE", source="FROZEN_COMPILER_BLOCKER",
                                         compiler_reached=True))
        else:
            category = _compiler_findings(draft, compiler_context, identity, passages, existing, findings,
                                          limitations, verdict, state)
    findings = _order(findings)
    if any(finding["record_locator"] == LOCATOR_UNAVAILABLE for finding in findings):
        limitations.add(LIMIT_LOCATOR)
    if any(finding["code"] == UNRECOGNIZED_CODE for finding in findings):
        limitations.add(LIMIT_UNRECOGNIZED_CODE)
    if any(finding["rule_class"] == RULE_CLASS_CANONICAL_UNRECOGNIZED for finding in findings):
        limitations.add(LIMIT_CANONICAL_UNRECOGNIZED)
    if any(not finding["repairable_by_model"] for finding in findings):
        limitations.add(LIMIT_HOST_SIDE)
    if not state["compiler_structural_rules_checked"]:
        limitations.add(LIMIT_COMPILER_NOT_REACHED)
    if not state["canonical_validation_reached"]:
        limitations.add(LIMIT_CANONICAL_NOT_REACHED)
    if not verdict["compiled"]:
        limitations.add(LIMIT_CANONICAL_NOT_ENUMERATED)
    completeness = {
        "observed_blockers_preserved": True,
        "observed_blockers_located": LIMIT_LOCATOR not in limitations,
        "observed_blockers_attributed": not (
            {LIMIT_UNRECOGNIZED_CODE, LIMIT_CANONICAL_UNRECOGNIZED, LIMIT_SCHEMA_UNDESCRIBED} & limitations),
        "compiler_structural_rules_checked": state["compiler_structural_rules_checked"],
        "canonical_validation_reached": state["canonical_validation_reached"],
        "downstream_canonical_issues_enumerated": verdict["compiled"],
        "independent_checks_consistent_with_compiler": state["independent_checks_consistent_with_compiler"],
    }
    diagnostic = {
        "diagnostic": DIAGNOSTIC_ID,
        "format": DIAGNOSTIC_FORMAT,
        "model_schema": p4_contract.MODEL_SCHEMA_IDENTITY,
        "category": category,
        "compiler_verdict": verdict,
        "completeness": completeness,
        "complete": all(completeness.values()),
        "limitations": sorted(limitations),
        "finding_count": len(findings),
        "findings": findings,
    }
    assert_diagnostic_safe(diagnostic, identity)
    return diagnostic


def _compiler_findings(draft: Mapping[str, Any], context: Any, identity: IdentityIndex, passages: Mapping[str, Any],
                       existing: Mapping[str, Any], findings: list, limitations: set, verdict: dict,
                       state: dict) -> Optional[str]:
    try:
        compiler_v1_1.compile_story_extraction_draft_v1_1(draft, context)
    except compiler_v1_1.DraftCompilationErrorV1_1 as error:
        blockers = [blocker.as_dict() for blocker in error.blockers]
    else:
        # The compiler accepted the draft and that is final. A check that disagrees is discarded and reported.
        if registry_rule_findings(draft, context, identity, existing, compiler_reached=True):
            limitations.add(LIMIT_CHECK_DISAGREEMENT)
            state["independent_checks_consistent_with_compiler"] = False
        verdict["compiled"] = True
        state["compiler_structural_rules_checked"] = state["canonical_validation_reached"] = True
        return None
    host_context = any(blocker["phase"] == "CONTEXT" for blocker in blockers)
    canonical_reached = any(blocker["code"] == CANONICAL_FAILURE for blocker in blockers)
    independent = [] if host_context else registry_rule_findings(
        draft, context, identity, existing, compiler_reached=canonical_reached)
    for blocker in blockers:
        if blocker["phase"] == "QUOTE":
            findings.append(_quote_finding(blocker, draft, identity, passages))
        elif blocker["phase"] in ("HANDLE", "REGISTRY"):
            findings.append(_path_finding(blocker, identity))
        elif blocker["phase"] == "CANONICAL_COMPILER":
            findings.append(_canonical_blocker_finding(blocker, len(independent)))
        else:
            findings.append(_finding(blocker["code"], source="FROZEN_COMPILER_BLOCKER", compiler_reached=True))
    findings.extend(independent)
    checks = sorted({name if name in VALIDATOR_CHECK_NAMES else MASK
                     for blocker in blockers if blocker["code"] == CANONICAL_FAILURE
                     for name in blocker["path"].split(",") if name})
    verdict.update({
        "compiler_blockers": len(blockers),
        "blocker_codes": sorted({blocker["code"] if blocker["code"] in RULE_TAXONOMY else UNRECOGNIZED_CODE
                                 for blocker in blockers}),
        "failed_validator_checks": checks,
    })
    state["compiler_structural_rules_checked"] = not host_context
    state["canonical_validation_reached"] = canonical_reached
    return "DRAFT_COMPILER_FAILURE"


# ---------------------------------------------------------------------------
# Safety and publication
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def _trusted_tokens() -> frozenset[str]:
    """Every string V3.1 may emit apart from verified handles and paths: tool, schema and registry owned."""
    registry = load_registry()
    tokens = set(p4_contract.diagnostic_vocabulary())
    tokens.update(registry["predicates"])
    tokens.update(registry["derivation_rules"])
    tokens.update(argument["name"] for spec in registry["predicates"].values() for argument in spec["args"])
    tokens.update(kind for spec in registry["predicates"].values() for argument in spec["args"]
                  for kind in argument.get("entity_kinds", []))
    tokens.update(RULE_TAXONOMY)
    tokens.update(rule[1] for rule in RULE_TAXONOMY.values())
    tokens.update(PHASES + SOURCES + LIMITATIONS + LOCATOR_STATES + VALIDATOR_CHECK_NAMES
                  + tuple(COLLECTION_DEFINITIONS) + tuple(category for category in CATEGORIES if category))
    tokens.update({DIAGNOSTIC_ID, DIAGNOSTIC_FORMAT, p4_contract.MODEL_SCHEMA_IDENTITY, UNRECOGNIZED_CODE,
                   RULE_CLASS_CANONICAL_EXPLAINED, MASK, V2_MASK, "$", "predicate_integrity", "derivation_integrity",
                   "EVIDENCE_ELIGIBLE", "CONTEXT_ONLY", "ENTITY"})
    return frozenset(tokens)


def _fail(reason: str) -> None:
    raise DiagnosticV31Error(reason)


def _safe_path_parts(value: Any) -> list[str]:
    vocabulary = p4_contract.path_vocabulary()
    if not isinstance(value, str):
        _fail("Diagnostic path is not a string")
    parts = value.split("/")
    for part in parts:
        numeric = part.isascii() and part.isdigit() and len(part) <= MAX_PATH_INDEX_DIGITS
        if not (numeric or part in vocabulary or part in COLLECTION_DEFINITIONS or part in (MASK, V2_MASK, "$")):
            _fail("Diagnostic path has an unverified part")
    return parts


def _check_plain(node: Any, key: Optional[str]) -> None:
    """Strings must be tool, schema or registry owned. No handle may appear below this point."""
    keys = DETAIL_KEYS | V2_SCHEMA_KEYS | p4_contract.path_vocabulary()
    if isinstance(node, dict):
        for name, value in node.items():
            if name not in keys or name in HANDLE_KEYS:
                _fail("Diagnostic has a key that is not schema or tool owned")
            _check_plain(value, name)
    elif isinstance(node, list):
        for value in node:
            _check_plain(value, key)
    elif isinstance(node, str):
        if key == "path":
            _safe_path_parts(node)
        elif node not in _trusted_tokens():
            _fail("Diagnostic has a string that is not schema, registry or tool owned")
    elif node is not None and type(node) not in (bool, int):
        _fail("Diagnostic has a value of an unexpected type")


def _check_finding(finding: Any, identity: IdentityIndex) -> None:
    if not isinstance(finding, dict) or tuple(finding) != FINDING_FIELDS:
        _fail("Finding fields differ from the V3.1 format")
    for name in ("phase", "code", "rule_class", "source", "validator_check", "validator_section"):
        _check_plain(finding[name], name)
    if finding["phase"] not in PHASES or finding["source"] not in SOURCES:
        _fail("Finding phase or source is not a V3.1 value")
    if type(finding["compiler_reached"]) is not bool or type(finding["repairable_by_model"]) is not bool:
        _fail("Finding flag is not a boolean")

    # The record: a verified collection/index/handle triple, or no index and no handle at all.
    collection, state = finding["record_collection"], finding["record_locator"]
    index, handle = finding["record_index"], finding["record_handle"]
    if state not in LOCATOR_STATES or (collection is not None and collection not in COLLECTION_DEFINITIONS):
        _fail("Finding locator state or collection is not a V3.1 value")
    path = None if finding["schema_path"] is None else _safe_path_parts(finding["schema_path"])
    if state == LOCATOR_VERIFIED:
        if (collection is None or type(index) is not int or not 0 <= index < identity.size(collection)
                or identity.unique_index(collection, handle) != index):
            _fail("Finding names a record that is not verified by the draft")
        if path is not None and path[:2] != [collection, str(index)]:
            _fail("Finding path does not agree with its record")
    else:
        if index is not None or handle is not None:
            _fail("Finding carries an index or a handle without a verified record")
        if state == LOCATOR_SCHEMA_PATH:
            position = int(path[1]) if path is not None and len(path) > 1 and path[1].isdigit() else None
            if (finding["source"] != "MODEL_SCHEMA_VALIDATOR" or collection is None or position is None
                    or path[0] != collection or position >= identity.size(collection)):
                _fail("Finding schema position is not verified by the draft")
        elif state == LOCATOR_UNAVAILABLE and path is not None and path[:2] != [collection or MASK, MASK]:
            _fail("Finding path does not agree with its unavailable record")
    if state == LOCATOR_NOT_SCOPED and finding["phase"] in RECORD_SCOPED_PHASES:
        _fail("Finding about one record carries no locator state")

    # Handles inside the detail: a supplied passage, a unique new record, or typed existing context.
    detail = finding["structural_detail"]
    if not isinstance(detail, dict):
        _fail("Finding detail is not an object")
    for name, value in detail.items():
        if name == "passage_handle":
            if value not in identity.passages:
                _fail("Finding names a passage the host did not supply")
        elif name in REFERENCE_KEYS:
            flag, expected = REFERENCE_KEYS[name]
            is_existing = detail.get(flag)
            if type(is_existing) is not bool:
                _fail("Finding references a record without saying where it lives")
            verified = identity.is_existing(value, expected) if is_existing \
                else identity.unique_index(expected, value) is not None
            if not verified:
                _fail("Finding references a record that is not verified")
        elif name not in DETAIL_KEYS and name not in V2_SCHEMA_KEYS:
            _fail("Finding detail has a key that is not schema or tool owned")
        else:
            _check_plain(value, name)


def assert_diagnostic_safe(diagnostic: Any, identity: IdentityIndex) -> None:
    """Fail closed unless the diagnostic is well formed, verified against the identity index and consistent.

    A string is accepted only when it is tool-, schema- or registry-owned, or a handle the
    identity index verifies in the place where it is used. Grammar alone is not enough.
    """
    try:
        _assert_diagnostic_safe(diagnostic, identity)
    except DiagnosticV31Error:
        raise
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as error:
        raise DiagnosticV31Error("Diagnostic is malformed") from error


def _assert_diagnostic_safe(diagnostic: Any, identity: Any) -> None:
    if not isinstance(identity, IdentityIndex):
        _fail("A diagnostic can only be checked against a host-built identity index")
    if not isinstance(diagnostic, dict) or tuple(diagnostic) != ENVELOPE_FIELDS:
        _fail("Diagnostic envelope differs from the V3.1 format")
    if (diagnostic["diagnostic"], diagnostic["format"], diagnostic["model_schema"]) != (
            DIAGNOSTIC_ID, DIAGNOSTIC_FORMAT, p4_contract.MODEL_SCHEMA_IDENTITY):
        _fail("Diagnostic identity differs from V3.1")
    category, findings = diagnostic["category"], diagnostic["findings"]
    if category not in CATEGORIES or not isinstance(findings, list):
        _fail("Diagnostic category or findings differ from the V3.1 format")
    for finding in findings:
        _check_finding(finding, identity)

    verdict = diagnostic["compiler_verdict"]
    if not isinstance(verdict, dict) or tuple(verdict) != VERDICT_FIELDS:
        _fail("Compiler verdict differs from the V3.1 format")
    blockers = verdict["compiler_blockers"]
    if type(verdict["compiled"]) is not bool or type(blockers) is not int or blockers < 0:
        _fail("Compiler verdict has a value of an unexpected type")
    for name in ("blocker_codes", "failed_validator_checks"):
        if not isinstance(verdict[name], list):
            _fail("Compiler verdict has a value of an unexpected type")
        _check_plain(verdict[name], name)
    limitations = diagnostic["limitations"]
    if (not isinstance(limitations, list) or limitations != sorted(set(limitations))
            or not set(limitations) <= set(LIMITATIONS)):
        _fail("Diagnostic limitations differ from the V3.1 tokens")
    completeness = diagnostic["completeness"]
    if (not isinstance(completeness, dict) or tuple(completeness) != COMPLETENESS_FIELDS
            or any(type(value) is not bool for value in completeness.values())):
        _fail("Diagnostic completeness differs from the V3.1 format")

    # The envelope must say what the findings show.
    unavailable = any(finding["record_locator"] == LOCATOR_UNAVAILABLE for finding in findings)
    from_compiler = sum(finding["source"] == "FROZEN_COMPILER_BLOCKER" for finding in findings)
    consistent = (
        diagnostic["finding_count"] == len(findings) and type(diagnostic["finding_count"]) is int
        and diagnostic["complete"] is all(completeness.values())
        and (LIMIT_LOCATOR in limitations) is unavailable
        and completeness["observed_blockers_located"] is (not unavailable)
        and completeness["observed_blockers_preserved"] is True
        and completeness["downstream_canonical_issues_enumerated"] is verdict["compiled"]
        and (category is None) is verdict["compiled"]
        and (not verdict["compiled"] or (not findings and blockers == 0 and completeness["canonical_validation_reached"]))
        and (category is None or bool(findings))
        and (category != "DRAFT_COMPILER_FAILURE" or (from_compiler == blockers and blockers > 0))
        and (category == "DRAFT_COMPILER_FAILURE" or verdict["compiled"] or blockers == 0)
        and (not verdict["failed_validator_checks"] or completeness["canonical_validation_reached"])
        and (completeness["canonical_validation_reached"] or LIMIT_CANONICAL_NOT_REACHED in limitations)
        and (verdict["compiled"] or LIMIT_CANONICAL_NOT_ENUMERATED in limitations)
    )
    if not consistent:
        _fail("Diagnostic envelope does not agree with its findings")


def public_summary(diagnostic: Mapping[str, Any]) -> dict[str, Any]:
    """Codes and counts only. No handle, index or path leaves the private repair request."""
    findings = diagnostic["findings"]

    def tally(field):
        counts: dict[str, int] = {}
        for finding in findings:
            counts[str(finding[field])] = counts.get(str(finding[field]), 0) + 1
        return dict(sorted(counts.items()))

    return {
        "diagnostic": diagnostic["diagnostic"],
        "category": diagnostic["category"],
        "complete": diagnostic["complete"],
        "completeness": dict(diagnostic["completeness"]),
        "limitations": list(diagnostic["limitations"]),
        "finding_count": diagnostic["finding_count"],
        "compiler_blockers": diagnostic["compiler_verdict"]["compiler_blockers"],
        "findings_by_code": tally("code"),
        "findings_by_rule_class": tally("rule_class"),
        "findings_by_source": tally("source"),
        "findings_by_record_locator": tally("record_locator"),
    }
