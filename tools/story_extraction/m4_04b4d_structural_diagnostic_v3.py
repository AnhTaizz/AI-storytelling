"""Structural repair diagnostic V3 for the P4.1 candidate (M4-04B4D). Offline design only.

Diagnostic V2 told a repair that something failed but not where: every record handle was
masked, a canonical conformance failure named no check and no record, and several
blockers could collapse into one finding. V3 keeps every independent blocker, names the
failing record when it can be verified, and names the structural rule that was broken.

The unchanged compiler is the acceptance authority. V3 only describes its verdict:

- the compiler's own structured blockers, one finding each;
- for the three canonical rule classes seen in the M4-04B4C forensics, an independent
  read-only check of the parsed draft against the frozen registry. The frozen validator
  reports canonical issues only inside the compiler, which exposes the failed check
  names and nothing else. V3 does not wrap or patch the compiler to get more. Canonical
  issues outside those three classes are therefore not enumerated, and V3 says so.

A record is named only by a handle that matches the frozen handle grammar of its
collection and is present exactly once in the parsed draft, together with its numeric
index. Anything else is masked and the diagnostic is marked incomplete. No quote, passage
text, argument value, unexpected key or exception message is ever copied.

V3 never edits a draft. It never chooses an occurrence, an entity kind, a rule or a
predicate. It makes no provider call and reads no dataset.

V3 never overturns the compiler. A draft the compiler accepts has no finding; if an
independent check would have reported one, the finding is discarded and the disagreement
is recorded as a limitation. What V3 cannot describe it reports as a masked finding with
`complete: false`. The only error it raises is the safety assertion on its own output.
"""
from __future__ import annotations

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


DIAGNOSTIC_ID = "M4_P4_1_STRUCTURAL_REPAIR_DIAGNOSTIC_V3"
DIAGNOSTIC_FORMAT = "M4_P4_1_STRUCTURAL_DIAGNOSTIC_V3_FORMAT_1"
DIAGNOSTIC_PATH = "tools/story_extraction/m4_04b4d_structural_diagnostic_v3.py"
MASK = "<UNVERIFIED>"
MAX_HANDLE_LENGTH = 40
MAX_ECHOED_OCCURRENCE = 1_000_000

# Draft collection -> definition of the model schema that owns its handle grammar.
COLLECTION_DEFINITIONS = {
    "evidence": "Evidence", "mentions": "Mention", "entities": "Entity", "events": "Event",
    "anchors": "TemporalAnchor", "propositions": "Proposition", "assertions": "Assertion",
}
CANONICAL_TO_DRAFT_COLLECTION = {canonical: draft for draft, canonical in compiler_v1.COLLECTIONS.items()}
PHASES = ("JSON", "SCHEMA", "HOST_CONTEXT", "QUOTE", "HANDLE", "REGISTRY", "CANONICAL", "COMPILER")
SOURCES = ("JSON_PARSER", "MODEL_SCHEMA_VALIDATOR", "FROZEN_COMPILER_BLOCKER", "INDEPENDENT_REGISTRY_CHECK")
FINDING_FIELDS = (
    "phase", "code", "rule_class", "source", "compiler_reached", "repairable_by_model", "record_collection",
    "record_index", "record_handle", "schema_path", "validator_check", "validator_section", "structural_detail",
)
ENVELOPE_FIELDS = (
    "diagnostic", "format", "model_schema", "category", "compiler_verdict", "complete", "limitations",
    "finding_count", "findings",
)

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
    "CANONICAL_CONFORMANCE_FAILURE": ("CANONICAL", "UNRECOGNIZED_CANONICAL_RULE", None, None, True),
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

LIMIT_CANONICAL_NOT_REACHED = "CANONICAL_VALIDATION_WAS_NOT_REACHED_BY_THE_COMPILER"
LIMIT_CANONICAL_NOT_ENUMERATED = "CANONICAL_ISSUES_OUTSIDE_THE_CHECKED_RULE_CLASSES_ARE_NOT_ENUMERATED"
LIMIT_CANONICAL_UNRECOGNIZED = "A_CANONICAL_FAILURE_COULD_NOT_BE_ATTRIBUTED_TO_A_KNOWN_RULE_CLASS"
LIMIT_LOCATOR = "A_RECORD_COULD_NOT_BE_IDENTIFIED_SAFELY"
LIMIT_HOST_SIDE = "A_FAILURE_IS_ON_THE_HOST_SIDE_AND_IS_NOT_REPAIRABLE_BY_THE_MODEL"
LIMIT_UNRECOGNIZED_CODE = "A_COMPILER_CODE_IS_NOT_IN_THE_V3_TAXONOMY"
LIMIT_SCHEMA_UNDESCRIBED = "A_SCHEMA_REJECTION_COULD_NOT_BE_DESCRIBED_FROM_THE_MODEL_SCHEMA"
LIMIT_CHECK_DISAGREEMENT = "AN_INDEPENDENT_CHECK_DISAGREED_WITH_THE_COMPILER_AND_WAS_DISCARDED"
LIMITATIONS = (
    LIMIT_CANONICAL_NOT_REACHED, LIMIT_CANONICAL_NOT_ENUMERATED, LIMIT_CANONICAL_UNRECOGNIZED, LIMIT_LOCATOR,
    LIMIT_HOST_SIDE, LIMIT_UNRECOGNIZED_CODE, LIMIT_SCHEMA_UNDESCRIBED, LIMIT_CHECK_DISAGREEMENT,
)
# Limitations that mean the model was not told everything V3 is meant to tell it.
INCOMPLETE_LIMITATIONS = frozenset({
    LIMIT_CANONICAL_UNRECOGNIZED, LIMIT_LOCATOR, LIMIT_HOST_SIDE, LIMIT_UNRECOGNIZED_CODE, LIMIT_SCHEMA_UNDESCRIBED,
    LIMIT_CHECK_DISAGREEMENT,
})

QUOTE_DETAIL_KEYS = (
    "passage_handle", "passage_use", "exact_match_count", "occurrence_present", "occurrence_required",
    "occurrence_given", "valid_occurrence_minimum", "valid_occurrence_maximum", "quote_code_points",
    "passage_supplied_by_host", "supplied_passage_count",
)
DETAIL_KEYS = frozenset(QUOTE_DETAIL_KEYS + (
    "records_sharing_this_handle", "failed_validator_checks", "predicate", "argument", "argument_kind",
    "allowed_entity_kinds", "referenced_entity_kind", "referenced_record_handle", "referenced_record_is_existing",
    "rule_id", "derivation_index", "assertion_predicate", "assertion_proposition_is_placeholder",
    "allowed_conclusion_predicates", "identical_to_record_handle", "identical_to_existing_record",
    "json_error_class", "line", "column", "compiler_code_recognized",
))
V2_SCHEMA_KEYS = frozenset({
    "phase", "code", "path", "schema_keyword", "missing_required_fields", "allowed_fields",
    "unexpected_field_count", "expected_type", "allowed_enum_tokens", "required_constant", "required_pattern",
    "limit", "variants", "forbidden_fields", "required_fields", "fixed_values", "findings",
})
V2_MASK = "<UNRECOGNIZED_KEY>"


class DiagnosticV3Error(RuntimeError):
    """The diagnostic failed its own safety assertion. Fail closed."""


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")


def diagnostic_sha256(diagnostic: Mapping[str, Any]) -> str:
    """Identity of a diagnostic: its canonical bytes. No clock, no random value, no path."""
    return hashlib.sha256(canonical_json_bytes(diagnostic)).hexdigest()


# ---------------------------------------------------------------------------
# Safe record identification
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
    """A handle that matches the frozen grammar and can carry nothing else."""
    return (
        isinstance(handle, str)
        and 0 < len(handle) <= MAX_HANDLE_LENGTH
        and handle.isascii()
        and handle.isprintable()
        and not any(character.isspace() for character in handle)
        and collection in handle_patterns()
        and handle_patterns()[collection].fullmatch(handle) is not None
    )


def locate_record(draft: Any, collection: Any, handle: Any) -> dict[str, Any]:
    """Collection, numeric index and handle of one draft record, or a masked fallback. Never guesses."""
    if collection not in COLLECTION_DEFINITIONS:
        return {"record_collection": None, "record_index": None, "record_handle": None}
    fallback = {"record_collection": collection, "record_index": None, "record_handle": None}
    records = draft.get(collection) if isinstance(draft, dict) else None
    if not isinstance(records, list) or not is_safe_handle(handle, collection):
        return fallback
    indices = [index for index, record in enumerate(records)
               if isinstance(record, dict) and record.get("handle") == handle]
    if len(indices) != 1:
        return fallback
    return {"record_collection": collection, "record_index": indices[0], "record_handle": handle}


def _finding(code: str, *, source: str, compiler_reached: bool, locator: Optional[Mapping[str, Any]] = None,
             schema_path: Optional[str] = None, detail: Optional[Mapping[str, Any]] = None,
             validator_check: Optional[str] = None) -> dict[str, Any]:
    recognized = code in RULE_TAXONOMY
    phase, rule_class, check, section, repairable = RULE_TAXONOMY.get(
        code, ("COMPILER", UNRECOGNIZED_CODE, None, None, False))
    locator = locator or {"record_collection": None, "record_index": None, "record_handle": None}
    return {
        "phase": phase,
        "code": code if recognized else UNRECOGNIZED_CODE,
        "rule_class": rule_class,
        "source": source,
        "compiler_reached": compiler_reached,
        "repairable_by_model": repairable,
        "record_collection": locator["record_collection"],
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
        safe.append(part if part.isdigit() and len(part) <= 6 else part if part in vocabulary else MASK)
    return "/".join(safe)


# ---------------------------------------------------------------------------
# Findings from the compiler's own structured blockers
# ---------------------------------------------------------------------------

def _quote_finding(blocker: Mapping[str, str], draft: Mapping[str, Any], passages: Mapping[str, Any]) -> dict[str, Any]:
    field, _, handle = blocker["path"].partition("/")
    locator = locate_record(draft, field, handle)
    detail: dict[str, Any] = {}
    if locator["record_index"] is not None:
        record = draft[field][locator["record_index"]]
        passage_handle = record.get("passage_handle")
        if isinstance(passage_handle, str) and passage_handle in passages:
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
            detail = {"passage_supplied_by_host": False, "supplied_passage_count": len(passages)}
    path = _safe_schema_path([], locator) if locator["record_collection"] else None
    return _finding(blocker["code"], source="FROZEN_COMPILER_BLOCKER", compiler_reached=True, locator=locator,
                    schema_path=path, detail=detail)


def _path_finding(blocker: Mapping[str, str], draft: Mapping[str, Any]) -> dict[str, Any]:
    parts = blocker["path"].split("/") if blocker["path"] else []
    if len(parts) >= 2 and parts[0] in COLLECTION_DEFINITIONS:
        locator = locate_record(draft, parts[0], parts[1])
        return _finding(blocker["code"], source="FROZEN_COMPILER_BLOCKER", compiler_reached=True, locator=locator,
                        schema_path=_safe_schema_path(parts[2:], locator))
    if blocker["code"] == "DUPLICATE_HANDLE" and len(parts) == 1:
        owners = [(collection, sum(isinstance(record, dict) and record.get("handle") == parts[0]
                                   for record in draft.get(collection, [])))
                  for collection in COLLECTION_DEFINITIONS if is_safe_handle(parts[0], collection)]
        owners = [(collection, count) for collection, count in owners if count]
        if len(owners) == 1:
            collection, count = owners[0]
            located = locate_record(draft, collection, parts[0])
            locator = {"record_collection": collection, "record_index": located["record_index"],
                       "record_handle": parts[0]}
            return _finding(blocker["code"], source="FROZEN_COMPILER_BLOCKER", compiler_reached=True,
                            locator=locator, detail={"records_sharing_this_handle": count})
    return _finding(blocker["code"], source="FROZEN_COMPILER_BLOCKER", compiler_reached=True)


def _canonical_compiler_findings(blocker: Mapping[str, str], independent: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if blocker["code"] != "CANONICAL_CONFORMANCE_FAILURE":
        return [_finding(blocker["code"], source="FROZEN_COMPILER_BLOCKER", compiler_reached=True)]
    checks = [name if name in VALIDATOR_CHECK_NAMES else MASK for name in blocker["path"].split(",") if name]
    findings = []
    for check in checks or [None]:
        if check == "canonical" and independent:
            continue  # explained by the independent registry findings, which carry the record and the rule
        findings.append(_finding("CANONICAL_CONFORMANCE_FAILURE", source="FROZEN_COMPILER_BLOCKER",
                                 compiler_reached=True, validator_check=check,
                                 detail={"failed_validator_checks": sorted(checks)}))
    return findings


# ---------------------------------------------------------------------------
# Independent read-only registry checks (the three canonical rule classes)
# ---------------------------------------------------------------------------

def registry_rule_findings(draft: Mapping[str, Any], context: Any, *, compiler_reached: bool) -> list[dict[str, Any]]:
    """Mirror three rules of the frozen canonical validator on the parsed draft. Read-only.

    Each rule is applied under the same preconditions the validator uses, so a finding here
    is a violation the validator reports once it is reached. Nothing is corrected.
    """
    registry = load_registry()
    _, existing = compiler_v1._context_maps(context)
    base = context.base_document
    base_entities = {record["id"]: record for record in base["entities"]}
    base_propositions = {record["id"]: record for record in base["propositions"]}
    new_entities = {record["handle"]: record for record in draft["entities"]}
    new_propositions = {record["handle"]: record for record in draft["propositions"]}
    forbidden = set(registry["forbidden_stored_verdicts"])
    new_handles = {record["handle"] for field in COLLECTION_DEFINITIONS for record in draft[field]}
    entity_kinds = set(materializer.load_tracked_model_schema()["$defs"]["EntityKind"]["enum"])

    def entity_kind(handle: Any) -> tuple[Optional[str], bool]:
        if handle in new_entities:
            return new_entities[handle].get("kind"), False
        if handle in existing and existing[handle][0] == "entities":
            return base_entities[existing[handle][1]].get("kind"), True
        return None, False

    def proposition_of(handle: Any) -> Optional[Mapping[str, Any]]:
        if handle in new_propositions:
            return new_propositions[handle]
        if handle in existing and existing[handle][0] == "propositions":
            return base_propositions[existing[handle][1]]
        return None

    findings: list[dict[str, Any]] = []

    # 1. Referenced entity kind allowed by the registry for the argument.
    for proposition in draft["propositions"]:
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
            kind, is_existing = entity_kind(argument.get("handle"))
            if kind is None or kind in want["entity_kinds"]:
                continue
            locator = locate_record(draft, "propositions", proposition["handle"])
            detail = {
                "predicate": predicate, "argument": name, "argument_kind": "ENTITY",
                "allowed_entity_kinds": list(want["entity_kinds"]),
                "referenced_record_is_existing": is_existing,
            }
            if kind in entity_kinds:
                detail["referenced_entity_kind"] = kind
            if is_safe_handle(argument.get("handle")):
                detail["referenced_record_handle"] = argument["handle"]
            findings.append(_finding(
                "ARGUMENT_ENTITY_KIND_NOT_ALLOWED", source="INDEPENDENT_REGISTRY_CHECK",
                compiler_reached=compiler_reached, locator=locator,
                schema_path=_safe_schema_path(["args", name], locator), detail=detail))

    # 2. Derivation rule may conclude the predicate of the assertion it supports.
    for assertion in draft["assertions"]:
        proposition = proposition_of(assertion.get("proposition_handle"))
        if proposition is None:
            continue
        predicate = proposition.get("predicate")
        for position, derivation in enumerate(assertion["support"]["derivations"]):
            rule = registry["derivation_rules"].get(derivation.get("rule_id"))
            if rule is None or predicate in rule["conclusion_predicates"]:
                continue
            locator = locate_record(draft, "assertions", assertion["handle"])
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
    def signature(proposition: Mapping[str, Any], is_new: bool) -> Optional[str]:
        if proposition.get("placeholder") or "predicate" not in proposition:
            return None
        arguments = {}
        for name, argument in proposition["args"].items():
            if is_new and "handle" in argument:
                handle = argument["handle"]
                if handle in existing:
                    reference = existing[handle][1]
                elif handle in new_handles:
                    reference = "#new#" + handle
                else:
                    return None  # an unknown handle is another blocker; identity cannot be decided
                arguments[name] = {"kind": argument["kind"], "ref": reference}
            else:
                arguments[name] = argument
        return proposition_signature({"predicate": proposition["predicate"], "args": arguments})

    reverse = {record_id: handle for handle, (collection, record_id) in existing.items() if collection == "propositions"}
    seen: dict[str, tuple[str, bool]] = {}
    for record_id in sorted(base_propositions):
        key = signature(base_propositions[record_id], False)
        if key is not None and record_id in reverse:
            seen.setdefault(key, (reverse[record_id], True))
    for handle in sorted(new_propositions):
        key = signature(new_propositions[handle], True)
        if key is None:
            continue
        if key not in seen:
            seen[key] = (handle, False)
            continue
        first, first_is_existing = seen[key]
        locator = locate_record(draft, "propositions", handle)
        detail = {"identical_to_existing_record": first_is_existing}
        if is_safe_handle(first):
            detail["identical_to_record_handle"] = first
        findings.append(_finding(
            "DUPLICATE_CONCRETE_PROPOSITION_CONTENT", source="INDEPENDENT_REGISTRY_CHECK",
            compiler_reached=compiler_reached, locator=locator, schema_path=_safe_schema_path([], locator),
            detail=detail))
    return findings


# ---------------------------------------------------------------------------
# The diagnostic
# ---------------------------------------------------------------------------

def _schema_envelope_findings(draft: Any) -> list[dict[str, Any]]:
    findings = []
    for item in p4_contract.schema_findings(draft):
        parts = item["path"].split("/")
        locator = {"record_collection": None, "record_index": None, "record_handle": None}
        if parts[0] in COLLECTION_DEFINITIONS:
            locator["record_collection"] = parts[0]
            if len(parts) > 1 and parts[1].isdigit():
                locator["record_index"] = int(parts[1])
                records = draft.get(parts[0]) if isinstance(draft, dict) else None
                record = records[locator["record_index"]] if isinstance(records, list) and \
                    locator["record_index"] < len(records) else None
                handle = record.get("handle") if isinstance(record, dict) else None
                if locate_record(draft, parts[0], handle)["record_index"] == locator["record_index"]:
                    locator["record_handle"] = handle
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


def structural_diagnostic_v3(raw_response: Any, compiler_context: Any) -> dict[str, Any]:
    """The complete V3 diagnostic for one response. The unchanged compiler decides validity."""
    findings: list[dict[str, Any]] = []
    limitations: set[str] = set()
    verdict = {"compiled": False, "compiler_blockers": 0, "blocker_codes": [], "failed_validator_checks": []}
    handles: set[str] = set()
    try:
        draft = json.loads(raw_response)
    except (TypeError, json.JSONDecodeError):
        item = p4_contract.json_error_diagnostic(raw_response)
        detail = {key: item[key] for key in ("json_error_class", "line", "column")}
        category, draft = "JSON_PARSE_FAILURE", None
        findings.append(_finding("JSON_PARSE_FAILURE", source="JSON_PARSER", compiler_reached=False,
                                 schema_path="$", detail=detail))
    else:
        try:
            compiler_v1_1.validate_draft_v1_1(draft)
            schema_valid = True
        except compiler_v1_1.DraftCompilationErrorV1_1:
            schema_valid = False
        if not schema_valid:
            category = "DRAFT_SCHEMA_FAILURE"
            findings = _schema_envelope_findings(draft)
            if not findings:
                limitations.add(LIMIT_SCHEMA_UNDESCRIBED)
                findings.append(_finding("DRAFT_SCHEMA_FAILURE", source="FROZEN_COMPILER_BLOCKER",
                                         compiler_reached=True))
        else:
            category = _compiler_findings(draft, compiler_context, findings, limitations, verdict)
    if isinstance(draft, dict):
        for collection in COLLECTION_DEFINITIONS:
            records = draft.get(collection)
            if isinstance(records, list):
                handles.update(record["handle"] for record in records
                               if isinstance(record, dict) and is_safe_handle(record.get("handle"), collection))
    findings = _order(findings)
    if any(finding["record_collection"] in COLLECTION_DEFINITIONS and finding["record_index"] is None
           and finding["record_handle"] is None for finding in findings):
        limitations.add(LIMIT_LOCATOR)
    if any(finding["code"] == UNRECOGNIZED_CODE for finding in findings):
        limitations.add(LIMIT_UNRECOGNIZED_CODE)
    if any(not finding["repairable_by_model"] for finding in findings):
        limitations.add(LIMIT_HOST_SIDE)
    diagnostic = {
        "diagnostic": DIAGNOSTIC_ID,
        "format": DIAGNOSTIC_FORMAT,
        "model_schema": p4_contract.MODEL_SCHEMA_IDENTITY,
        "category": category,
        "compiler_verdict": verdict,
        "complete": not (limitations & INCOMPLETE_LIMITATIONS),
        "limitations": sorted(limitations),
        "finding_count": len(findings),
        "findings": findings,
    }
    assert_diagnostic_safe(diagnostic, handles, compiler_context)
    return diagnostic


def _compiler_findings(draft: Mapping[str, Any], context: Any, findings: list, limitations: set, verdict: dict) -> Optional[str]:
    try:
        compiler_v1_1.compile_story_extraction_draft_v1_1(draft, context)
    except compiler_v1_1.DraftCompilationErrorV1_1 as error:
        blockers = [blocker.as_dict() for blocker in error.blockers]
    else:
        # The compiler accepted the draft and that is final. A check that disagrees is discarded and reported.
        if registry_rule_findings(draft, context, compiler_reached=True):
            limitations.add(LIMIT_CHECK_DISAGREEMENT)
        verdict["compiled"] = True
        return None
    passages, _ = compiler_v1._context_maps(context) if all(
        blocker["phase"] != "CONTEXT" for blocker in blockers) else ({}, {})
    canonical_reached = any(blocker["phase"] == "CANONICAL_COMPILER" for blocker in blockers)
    host_context = any(blocker["phase"] == "CONTEXT" for blocker in blockers)
    independent = [] if host_context else registry_rule_findings(draft, context, compiler_reached=canonical_reached)
    for blocker in blockers:
        if blocker["phase"] == "QUOTE":
            findings.append(_quote_finding(blocker, draft, passages))
        elif blocker["phase"] in ("HANDLE", "REGISTRY"):
            findings.append(_path_finding(blocker, draft))
        elif blocker["phase"] == "CANONICAL_COMPILER":
            findings.extend(_canonical_compiler_findings(blocker, independent))
        else:
            findings.append(_finding(blocker["code"], source="FROZEN_COMPILER_BLOCKER", compiler_reached=True))
    findings.extend(independent)
    checks = sorted({name if name in VALIDATOR_CHECK_NAMES else MASK
                     for blocker in blockers if blocker["code"] == "CANONICAL_CONFORMANCE_FAILURE"
                     for name in blocker["path"].split(",") if name})
    verdict.update({
        "compiler_blockers": len(blockers),
        "blocker_codes": sorted({blocker["code"] if blocker["code"] in RULE_TAXONOMY else UNRECOGNIZED_CODE
                                 for blocker in blockers}),
        "failed_validator_checks": checks,
    })
    limitations.add(LIMIT_CANONICAL_NOT_ENUMERATED)
    if not canonical_reached:
        limitations.add(LIMIT_CANONICAL_NOT_REACHED)
    if any(finding["rule_class"] == "UNRECOGNIZED_CANONICAL_RULE" for finding in findings):
        limitations.add(LIMIT_CANONICAL_UNRECOGNIZED)
    return "DRAFT_COMPILER_FAILURE"


# ---------------------------------------------------------------------------
# Safety and publication
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def _trusted_tokens() -> frozenset[str]:
    """Every string V3 may emit apart from verified handles and paths: tool, schema and registry owned."""
    registry = load_registry()
    tokens = set(p4_contract.diagnostic_vocabulary())
    tokens.update(registry["predicates"])
    tokens.update(registry["derivation_rules"])
    tokens.update(argument["name"] for spec in registry["predicates"].values() for argument in spec["args"])
    tokens.update(kind for spec in registry["predicates"].values() for argument in spec["args"]
                  for kind in argument.get("entity_kinds", []))
    tokens.update(RULE_TAXONOMY)
    tokens.update(rule[1] for rule in RULE_TAXONOMY.values())
    tokens.update(PHASES + SOURCES + LIMITATIONS + VALIDATOR_CHECK_NAMES + tuple(COLLECTION_DEFINITIONS))
    tokens.update({DIAGNOSTIC_ID, DIAGNOSTIC_FORMAT, UNRECOGNIZED_CODE, MASK, V2_MASK, "$", "predicate_integrity",
                   "derivation_integrity", "DRAFT_COMPILER_FAILURE", "EVIDENCE_ELIGIBLE", "CONTEXT_ONLY", "ENTITY"})
    return frozenset(tokens)


def assert_diagnostic_safe(diagnostic: Any, handles: set[str], compiler_context: Any = None) -> None:
    """Fail closed unless every string is tool-, schema- or registry-owned, or a verified handle."""
    tokens = _trusted_tokens()
    vocabulary = p4_contract.path_vocabulary()
    passage_handles = set()
    if compiler_context is not None:
        passage_handles = {f"P{index}" for index in range(1, len(compiler_context.passage_inputs) + 1)}
    allowed_handles = {handle for handle in handles if is_safe_handle(handle)} | passage_handles
    keys = set(FINDING_FIELDS) | set(ENVELOPE_FIELDS) | DETAIL_KEYS | V2_SCHEMA_KEYS | vocabulary | {
        "compiled", "compiler_blockers", "blocker_codes", "failed_validator_checks"}

    def safe_path(value: str) -> bool:
        return all(part.isdigit() or part in vocabulary or part in COLLECTION_DEFINITIONS or part in (MASK, V2_MASK, "$")
                   for part in value.split("/"))

    def walk(node: Any, key: Optional[str]) -> None:
        if isinstance(node, dict):
            for name, value in node.items():
                if name not in keys:
                    raise DiagnosticV3Error("Diagnostic has a key that is not schema or tool owned")
                walk(value, name)
        elif isinstance(node, list):
            for value in node:
                walk(value, key)
        elif isinstance(node, str):
            if key in ("path", "schema_path"):
                if not safe_path(node):
                    raise DiagnosticV3Error("Diagnostic path has an unverified part")
            elif key in ("record_handle", "referenced_record_handle", "identical_to_record_handle", "passage_handle"):
                if node not in allowed_handles and not (key != "passage_handle" and is_safe_handle(node)):
                    raise DiagnosticV3Error("Diagnostic names a handle that was not verified")
            elif node not in tokens:
                raise DiagnosticV3Error("Diagnostic has a string that is not schema, registry or tool owned")
        elif node is not None and type(node) not in (bool, int):
            raise DiagnosticV3Error("Diagnostic has a value of an unexpected type")

    if not isinstance(diagnostic, dict) or tuple(diagnostic) != ENVELOPE_FIELDS:
        raise DiagnosticV3Error("Diagnostic envelope differs from the V3 format")
    for finding in diagnostic["findings"]:
        if tuple(finding) != FINDING_FIELDS:
            raise DiagnosticV3Error("Finding fields differ from the V3 format")
    walk(diagnostic, None)


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
        "limitations": list(diagnostic["limitations"]),
        "finding_count": diagnostic["finding_count"],
        "compiler_blockers": diagnostic["compiler_verdict"]["compiler_blockers"],
        "findings_by_code": tally("code"),
        "findings_by_rule_class": tally("rule_class"),
        "findings_by_source": tally("source"),
        "findings_with_a_verified_record_handle": sum(finding["record_handle"] is not None for finding in findings),
        "findings_with_a_record_index": sum(finding["record_index"] is not None for finding in findings),
    }
