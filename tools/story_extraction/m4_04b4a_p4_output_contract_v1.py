"""P4 output contract for story extraction (M4-04B4A). Offline design and readiness only.

P4 keeps the canonical STORY_EXTRACTION_DRAFT_V1_1 semantics and the unchanged V1.1
compiler. What changes is the model-facing side:

* the prompt carries the complete self-contained model schema, never a delta;
* the same schema object is bound to the provider's native response-schema parameter;
* a coverage gate proves that every structural rule the validator enforces is available
  to the model before any request exists;
* the structural repair diagnostic names the broken schema rule, not only its path.

This module makes no provider call, loads no credential and reads no dataset. It does not
bind a model, a credential slot or a runtime; that is a later protocol lock.
"""
from __future__ import annotations

from collections import Counter
import functools
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Optional

from jsonschema import Draft202012Validator
import yaml

from tools.story_extraction.materialize_draft_v1_1_model_schema_v1 import (
    CANONICAL_DRAFT_VERSION,
    LOCAL_PREFIX,
    MODEL_SCHEMA_IDENTITY,
    REPO_ROOT,
    V1_1_SCHEMA_PATH,
    V1_SCHEMA_PATH,
    assert_self_contained,
    load_tracked_model_schema,
    model_schema_sha256,
    model_schema_text,
)


TASK_ID = "M4-04B4A"
P4_EXTRACTOR_ID = "P4_STORY_EXTRACTION_DRAFT_V1_1_SELF_CONTAINED_V1"
REPAIR_DIAGNOSTIC_ID = "M4_P4_STRUCTURAL_REPAIR_DIAGNOSTIC_V2"
MAX_STRUCTURAL_REPAIRS_PER_CASE = 1
TEMPERATURE = 0
MAX_OUTPUT_TOKENS = 16384
RESPONSE_MIME_TYPE = "application/json"
NATIVE_SCHEMA_PARAMETER = "response_json_schema"
STRUCTURED_OUTPUT_DECISION = "NATIVE_SCHEMA_CONSTRAINT_SUPPORTED_OFFLINE"

PROMPT_ROOT = REPO_ROOT / "tools/story_extraction/prompts"
SYSTEM_PREAMBLE_PATH = PROMPT_ROOT / "story_extraction_draft_p4_v1_system.txt"
USER_TEMPLATE_PATH = PROMPT_ROOT / "story_extraction_draft_p4_v1_user.txt"
REPAIR_USER_TEMPLATE_PATH = PROMPT_ROOT / "story_extraction_draft_p4_v1_repair_user.txt"
PREDICATE_REGISTRY_PATH = REPO_ROOT / "schemas/canonical_story/predicate_registry_v0.yaml"
B3HR_RECORD_PATH = REPO_ROOT / "benchmarks/m4_extraction/M4_04B3HR_DEV3_P3_STRUCTURAL_FAILURE_FORENSICS.yaml"

SCHEMA_SECTION_MARKER = f"COMPLETE SELF-CONTAINED MODEL OUTPUT SCHEMA ({MODEL_SCHEMA_IDENTITY}):"
REGISTRY_SECTION_MARKER = "EXACT PREDICATE REGISTRY:"
REPAIR_SYSTEM_SUFFIX = """
STRUCTURAL REPAIR MODE
Repair only the complete structural diagnostic supplied by the host. Each finding names
a path and the schema rule broken there. Preserve the primary semantic choices. Do not
fill coverage gaps, optimize quality, consult gold, or introduce a new interpretation.
This is the only repair for the case.
""".strip()

# JSON Schema keywords the installed SDK documents as honoured by native schema-constrained
# output (google-genai 2.27.0, GenerateContentConfig.response_json_schema).
NATIVE_DOCUMENTED_KEYWORDS = frozenset({
    "$id", "$defs", "$ref", "$anchor", "type", "format", "title", "description", "enum", "items",
    "prefixItems", "minItems", "maxItems", "minimum", "maximum", "anyOf", "oneOf", "properties",
    "additionalProperties", "required", "propertyOrdering",
})
ANNOTATION_KEYWORDS = frozenset({"$schema", "$id", "title", "description", "$defs"})
UNAVAILABLE = "REQUIRED_BY_VALIDATOR_BUT_UNAVAILABLE_TO_MODEL"

_FAMILY = {
    "type": "TYPE_OR_COLLECTION_SHAPE", "items": "TYPE_OR_COLLECTION_SHAPE",
    "additionalProperties": "TYPE_OR_COLLECTION_SHAPE", "minItems": "TYPE_OR_COLLECTION_SHAPE",
    "uniqueItems": "TYPE_OR_COLLECTION_SHAPE", "minProperties": "TYPE_OR_COLLECTION_SHAPE",
    "pattern": "HANDLE_OR_TOKEN_PATTERN", "const": "CONSTANT",
    "minLength": "VALUE_BOUND", "maxLength": "VALUE_BOUND", "minimum": "VALUE_BOUND",
    "if": "CONDITIONAL_RULE", "then": "CONDITIONAL_RULE", "else": "CONDITIONAL_RULE", "not": "CONDITIONAL_RULE",
}
_P3_PATH_DEFINITION = {
    "assertions/*": "Assertion", "entities/*": "Entity", "events/*": "Event", "anchors/*": "TemporalAnchor",
    "propositions/*": "Proposition", "evidence/*": "Evidence", "mentions/*": "Mention",
    "mentions/*/role": "EvidenceRole", "evidence/*/role": "EvidenceRole", "entities/*/kind": "EntityKind",
}


class OutputContractError(RuntimeError):
    """The P4 contract, a prompt or a coverage gate is not satisfied."""


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


# ---------------------------------------------------------------------------
# Prompt material
# ---------------------------------------------------------------------------

def prompt_material() -> dict[str, str]:
    """The exact P4 prompt texts. The schema section is the tracked materialized schema."""
    schema = load_tracked_model_schema()
    system = (
        _text(SYSTEM_PREAMBLE_PATH).rstrip()
        + "\n\n" + SCHEMA_SECTION_MARKER + "\n" + model_schema_text(schema).rstrip()
        + "\n\n" + REGISTRY_SECTION_MARKER + "\n" + _text(PREDICATE_REGISTRY_PATH).rstrip()
    )
    return {
        "primary_system": system,
        "primary_user_template": _text(USER_TEMPLATE_PATH).rstrip() + "\n",
        "repair_system": system + "\n\n" + REPAIR_SYSTEM_SUFFIX,
        "repair_user_template": _text(REPAIR_USER_TEMPLATE_PATH).rstrip() + "\n",
    }


def _render(template: str, replacements: Mapping[str, str]) -> str:
    rendered = template
    for key, value in replacements.items():
        marker = "{" + key + "}"
        if rendered.count(marker) != 1:
            raise OutputContractError("Prompt marker missing or repeated: " + marker)
        rendered = rendered.replace(marker, value)
    return rendered


def render_primary_user(case_id: str, prepared_input: Mapping[str, Any]) -> str:
    if prepared_input.get("draft_version") != CANONICAL_DRAFT_VERSION:
        raise OutputContractError("Prepared input is not Draft V1.1")
    return _render(prompt_material()["primary_user_template"], {
        "CASE_ID": case_id, "PREPARED_INPUT_JSON": canonical_json(prepared_input),
    })


def render_repair_user(
    case_id: str, prepared_input: Mapping[str, Any], primary_response: str, diagnostic: Mapping[str, Any]
) -> str:
    if diagnostic.get("diagnostic") != REPAIR_DIAGNOSTIC_ID or not diagnostic.get("findings"):
        raise OutputContractError("Repair requires a non-empty structural diagnostic V2")
    if not isinstance(primary_response, str) or not primary_response:
        raise OutputContractError("Repair requires one successful primary response")
    return _render(prompt_material()["repair_user_template"], {
        "CASE_ID": case_id,
        "PREPARED_INPUT_JSON": canonical_json(prepared_input),
        "STRUCTURAL_DIAGNOSTIC_JSON": canonical_json(diagnostic),
        "PRIMARY_RESPONSE": primary_response,
    })


# ---------------------------------------------------------------------------
# Structural requirements and the prompt-coverage gate
# ---------------------------------------------------------------------------

def _ref_target(ref: str) -> str:
    return ref.split(LOCAL_PREFIX, 1)[1] if LOCAL_PREFIX in ref else ref


def canonical_definitions() -> dict[str, Any]:
    """The contract the validator enforces: the Draft V1.1 delta resolved against Draft V1."""
    v1 = json.loads(_text(V1_SCHEMA_PATH))
    v1_1 = json.loads(_text(V1_1_SCHEMA_PATH))
    definitions = {"<root>": {key: value for key, value in v1_1.items() if key != "$defs"}}
    definitions.update(v1_1.get("$defs", {}))
    pending = [_ref_target(ref) for ref in _refs(v1_1)]
    while pending:
        name = pending.pop()
        if name in definitions:
            continue
        definitions[name] = v1["$defs"][name]
        pending.extend(_ref_target(ref) for ref in _refs(v1["$defs"][name]))
    return definitions


def supplied_definitions(schema: Mapping[str, Any]) -> dict[str, Any]:
    """The definitions a model can actually read in one supplied schema object."""
    definitions = {"<root>": {key: value for key, value in schema.items() if key != "$defs"}}
    definitions.update(schema.get("$defs", {}))
    return definitions


def _refs(node: Any) -> Iterable[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref":
                yield value
            else:
                yield from _refs(value)
    elif isinstance(node, list):
        for value in node:
            yield from _refs(value)


def structural_requirements(definitions: Mapping[str, Any]) -> dict[tuple[str, str, str, str], str]:
    """Every structural rule in a set of definitions, keyed for comparison, with its family."""
    found: dict[tuple[str, str, str, str], str] = {}

    def walk(name: str, node: Mapping[str, Any], pointer: str) -> None:
        for keyword, value in node.items():
            if keyword in ANNOTATION_KEYWORDS:
                continue
            if keyword == "properties":
                for field, child in value.items():
                    found[(name, pointer, "property", field)] = "ALLOWED_PROPERTY"
                    walk(name, child, f"{pointer}/properties/{field}")
            elif keyword == "required":
                for field in value:
                    found[(name, pointer, "required", field)] = "REQUIRED_FIELD"
            elif keyword == "enum":
                for token in value:
                    found[(name, pointer, "enum", json.dumps(token))] = "ENUM_TOKEN"
            elif keyword == "oneOf":
                for index, child in enumerate(value):
                    found[(name, pointer, "oneOf", str(index))] = "ONE_OF_VARIANT"
                    walk(name, child, f"{pointer}/oneOf/{index}")
            elif keyword == "$ref":
                found[(name, pointer, "$ref", _ref_target(value))] = "REFERENCE"
            elif isinstance(value, dict):
                found[(name, pointer, keyword, "<schema>")] = _FAMILY.get(keyword, "OTHER")
                walk(name, value, f"{pointer}/{keyword}")
            else:
                found[(name, pointer, keyword, json.dumps(value, sort_keys=True))] = _FAMILY.get(keyword, "OTHER")

    for name, body in definitions.items():
        walk(name, body, "")
    return found


def extract_prompt_schema(system_prompt: str, schema_marker: str, registry_marker: str) -> dict[str, Any]:
    """The schema object a system prompt really contains, parsed from its schema section."""
    try:
        start = system_prompt.index(schema_marker) + len(schema_marker)
        end = system_prompt.index(registry_marker, start)
        schema = json.loads(system_prompt[start:end])
    except (ValueError, json.JSONDecodeError) as error:
        raise OutputContractError("System prompt does not contain a parseable schema section") from error
    if not isinstance(schema, dict):
        raise OutputContractError("Prompt schema section is not a JSON object")
    return schema


def _in_prompt_text(requirement: tuple[str, str, str, str], family: str, text: str) -> bool:
    """Whether a rule is spelled out in prose. Only names and tokens can be; shapes cannot."""
    if family not in ("REQUIRED_FIELD", "ALLOWED_PROPERTY", "ENUM_TOKEN", "CONSTANT"):
        return False
    token = requirement[3]
    if family in ("ENUM_TOKEN", "CONSTANT"):
        token = json.loads(token)
        if not isinstance(token, str):
            return False
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])", text) is not None


def audit_prompt_coverage(
    system_prompt: str,
    schema_marker: str = SCHEMA_SECTION_MARKER,
    registry_marker: str = REGISTRY_SECTION_MARKER,
) -> dict[str, Any]:
    """Classify every rule the validator enforces by how the model receives it."""
    required = structural_requirements(canonical_definitions())
    schema = extract_prompt_schema(system_prompt, schema_marker, registry_marker)
    supplied = structural_requirements(supplied_definitions(schema))
    preamble = system_prompt[: system_prompt.index(schema_marker)]
    by_availability, by_family, unavailable = Counter(), {}, []
    for requirement, family in required.items():
        if requirement in supplied:
            availability = "MODEL_SCHEMA"
        elif _in_prompt_text(requirement, family, preamble):
            availability = "EXPLICIT_PROMPT_TEXT"
        else:
            availability = UNAVAILABLE
            unavailable.append(requirement)
        by_availability[availability] += 1
        by_family.setdefault(family, Counter())[availability] += 1
    definitions_required = sorted(canonical_definitions())
    definitions_supplied = sorted(supplied_definitions(schema))
    return {
        "structural_requirements": len(required),
        "by_availability": dict(sorted(by_availability.items())),
        "by_family": {family: dict(sorted(counts.items())) for family, counts in sorted(by_family.items())},
        "unavailable_count": len(unavailable),
        "unavailable_by_definition": dict(sorted(Counter(item[0] for item in unavailable).items())),
        "definitions_required": definitions_required,
        "definitions_missing_from_prompt_schema": [n for n in definitions_required if n not in definitions_supplied],
        "prompt_schema_external_ref_count": sum(1 for ref in _refs(schema) if not ref.startswith("#/")),
        "requirements_supplied": supplied,
    }


def assert_prompt_coverage(system_prompt: Optional[str] = None) -> dict[str, Any]:
    """The gate: no structural rule may be enforced by the validator yet hidden from the model."""
    report = audit_prompt_coverage(prompt_material()["primary_system"] if system_prompt is None else system_prompt)
    if report["unavailable_count"] or report["prompt_schema_external_ref_count"]:
        raise OutputContractError(UNAVAILABLE)
    return report


def p3_blocker_projection(p3_system_prompt: str, p3_schema_marker: str, p3_registry_marker: str) -> dict[str, Any]:
    """For each requirement family in the published P3 blocker inventory: could the model see it?"""
    record = yaml.safe_load(_text(B3HR_RECORD_PATH))
    families: set[tuple[str, str, str]] = set()
    for phase in ("primary", "repair"):
        bucket = record["aggregate"][phase]
        for key in bucket["required_fields_missing"]:
            pattern, field = key.rsplit(":", 1)
            families.add((_P3_PATH_DEFINITION[pattern], "required", field))
        for key in bucket["unexpected_fields"]:
            families.add((_P3_PATH_DEFINITION[key.rsplit(":", 1)[0]], "additionalProperties", "allowed key set"))
        for key in bucket["enum_value_classes"]:
            families.add((_P3_PATH_DEFINITION[key.rsplit(":", 1)[0]], "enum", "allowed values"))
        if "oneOf" in bucket["schema_keywords"]:
            families.add(("Proposition", "oneOf", "record variants"))

    def unavailable(system_prompt: str, schema_marker: str, registry_marker: str) -> list[tuple[str, str, str]]:
        supplied = audit_prompt_coverage(system_prompt, schema_marker, registry_marker)["requirements_supplied"]
        missing = []
        for definition, keyword, detail in sorted(families):
            if keyword == "required":
                # A required field may be stated directly or through a conditional (then/else).
                present = any(item[0] == definition and item[2] == "required" and item[3] == detail for item in supplied)
            elif keyword == "additionalProperties":
                present = (definition, "", "additionalProperties", "false") in supplied
            elif keyword == "enum":
                present = any(item[0] == definition and item[2] == "enum" for item in supplied)
            else:
                present = (definition, "", "oneOf", "0") in supplied
            if not present:
                missing.append((definition, keyword, detail))
        return missing

    p3_missing = unavailable(p3_system_prompt, p3_schema_marker, p3_registry_marker)
    p4_missing = unavailable(prompt_material()["primary_system"], SCHEMA_SECTION_MARKER, REGISTRY_SECTION_MARKER)
    return {
        "source": "M4_04B3HR_PUBLIC_RECORD_ONLY",
        "blocker_requirement_families": len(families),
        "definitions_involved": sorted({item[0] for item in families}),
        "p3_structurally_unavailable_to_model": len(p3_missing),
        "p4_structurally_unavailable_to_model": len(p4_missing),
        "p4_unavailable": [":".join(item) for item in p4_missing],
        "claim": "AVAILABILITY_OF_RULES_ONLY_NOT_A_PREDICTION_OF_MODEL_OUTPUT",
    }


# ---------------------------------------------------------------------------
# Structured output: one schema for the prompt and for the provider
# ---------------------------------------------------------------------------

def native_response_schema() -> dict[str, Any]:
    """The schema bound to the provider. It is the tracked model schema, not a second copy."""
    return load_tracked_model_schema()


def generation_config() -> dict[str, Any]:
    """Generation settings carrying the native schema constraint. No model or credential is bound."""
    return {
        "temperature": TEMPERATURE,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        NATIVE_SCHEMA_PARAMETER: native_response_schema(),
    }


def _keywords(node: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("properties", "$defs"):
                for child in value.values():
                    found |= _keywords(child)
                found.add(key)
            else:
                found.add(key)
                found |= _keywords(value)
    elif isinstance(node, list):
        for value in node:
            found |= _keywords(value)
    return found


def native_enforcement_gap() -> dict[str, Any]:
    """Which rules of the model schema the provider is not documented to enforce natively."""
    schema = native_response_schema()
    used = _keywords(schema)

    def ref_with_siblings(node: Any) -> int:
        if isinstance(node, dict):
            here = int("$ref" in node and any(not key.startswith("$") for key in node))
            return here + sum(ref_with_siblings(value) for value in node.values())
        if isinstance(node, list):
            return sum(ref_with_siblings(value) for value in node)
        return 0

    graph = {name: {_ref_target(ref) for ref in _refs(body)} for name, body in schema["$defs"].items()}
    state: dict[str, int] = {}

    def cyclic(name: str) -> bool:
        if state.get(name) == 1:
            return True
        if state.get(name) == 2:
            return False
        state[name] = 1
        result = any(cyclic(target) for target in graph[name])
        state[name] = 2
        return result

    return {
        "keywords_used_by_model_schema": sorted(used),
        "keywords_not_documented_as_natively_enforced": sorted(used - NATIVE_DOCUMENTED_KEYWORDS),
        "ref_nodes_with_sibling_keywords": ref_with_siblings(schema),
        "cyclic_references": any(cyclic(name) for name in graph),
        "local_validator_remains_authoritative": True,
    }


def sdk_structured_output_capability() -> dict[str, Any]:
    """Inspect the installed SDK types only. Constructs no client and makes no call."""
    import importlib.metadata

    from google.genai import types

    fields = types.GenerateContentConfig.model_fields
    supported = NATIVE_SCHEMA_PARAMETER in fields and "response_mime_type" in fields
    wire_name = None
    if supported:
        config = types.GenerateContentConfig(
            temperature=TEMPERATURE, max_output_tokens=MAX_OUTPUT_TOKENS,
            response_mime_type=RESPONSE_MIME_TYPE, **{NATIVE_SCHEMA_PARAMETER: {"type": "object"}},
        )
        dumped = config.model_dump(exclude_none=True, by_alias=True)
        wire_name = next((key for key, value in dumped.items() if value == {"type": "object"}), None)
    return {
        "sdk": "google-genai",
        "sdk_version": importlib.metadata.version("google-genai"),
        "config_type": "GenerateContentConfig",
        "native_schema_parameter": NATIVE_SCHEMA_PARAMETER if supported else None,
        "native_schema_wire_name": wire_name,
        "alternative_parameter_present": "response_schema" in fields,
        "decision": STRUCTURED_OUTPUT_DECISION if supported and wire_name else "JSON_MIME_ONLY",
    }


# ---------------------------------------------------------------------------
# Structural repair diagnostic V2
# ---------------------------------------------------------------------------

def _schema_vocabulary(schema: Mapping[str, Any]) -> set[str]:
    names: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "properties":
                    names.update(value)
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    return names


@functools.lru_cache(maxsize=1)
def _model_validator() -> Draft202012Validator:
    return Draft202012Validator(load_tracked_model_schema())


@functools.lru_cache(maxsize=1)
def path_vocabulary() -> frozenset[str]:
    """Keys that may appear in a diagnostic path: schema fields and registry argument names."""
    registry = yaml.safe_load(_text(PREDICATE_REGISTRY_PATH))
    arguments = {
        argument["name"] for predicate in registry["predicates"].values() for argument in predicate.get("args", [])
    }
    return frozenset(_schema_vocabulary(load_tracked_model_schema()) | arguments)


def _safe_path(parts: Iterable[Any], vocabulary: frozenset[str]) -> str:
    safe = []
    for part in parts:
        if isinstance(part, int) and not isinstance(part, bool):
            safe.append(str(part))
        elif isinstance(part, str) and part in vocabulary:
            safe.append(part)
        else:
            safe.append("<UNRECOGNIZED_KEY>")
    return "/".join(safe) if safe else "$"


def json_error_diagnostic(text: Any) -> dict[str, Any]:
    """Class and position of a JSON syntax failure. Never includes any text of the response."""
    finding = {"phase": "JSON", "code": "JSON_PARSE_FAILURE", "path": "$"}
    if not isinstance(text, str) or not text.strip():
        return {**finding, "json_error_class": "EMPTY_RESPONSE", "line": 1, "column": 1}
    stripped = text.strip()
    try:
        json.loads(text)
    except json.JSONDecodeError as error:
        before, after = text[: error.pos].rstrip()[-1:], text[error.pos:].lstrip()
        balanced = text.count("{") == text.count("}") and text.count("[") == text.count("]")
        if stripped[0] not in "{[":
            category = "NON_JSON_PREFIX_SUFFIX"
        elif error.msg.startswith("Extra data"):
            category = "EXTRA_DATA"
        elif "escape" in error.msg.lower() or "control character" in error.msg.lower():
            category = "INVALID_ESCAPE"
        elif error.msg.startswith("Unterminated") or not balanced or error.pos >= len(text.rstrip()):
            category = "UNTERMINATED_JSON"
        elif (before == "," and after[:1] in ("}", "]")) or (after[:1] == "," and after[1:].lstrip()[:1] in ("}", "]")):
            category = "TRAILING_COMMA"
        elif error.msg.startswith("Expecting property name"):
            category = "INVALID_PROPERTY_NAME"
        else:
            category = "OTHER_JSON_SYNTAX"
        return {**finding, "json_error_class": category, "line": int(error.lineno), "column": int(error.colno)}
    raise OutputContractError("Response is valid JSON; no JSON diagnostic applies")


def _variant_summary(branches: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    variants = []
    for branch in branches:
        fixed = {}
        for field, rule in branch.get("properties", {}).items():
            if "const" in rule:
                fixed[field] = [rule["const"]]
            elif "enum" in rule:
                fixed[field] = list(rule["enum"])
        variants.append({
            "required_fields": list(branch.get("required", [])),
            "allowed_fields": sorted(branch.get("properties", {})),
            "fixed_values": fixed,
        })
    return variants


def _findings(errors: Iterable[Any], vocabulary: frozenset[str]) -> list[dict[str, Any]]:
    """Findings for validator errors, built from the schema side of each error only."""
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for error in errors:
        keyword = str(error.validator)
        path = _safe_path(error.absolute_path, vocabulary)
        finding = grouped.setdefault((path, keyword), {
            "phase": "SCHEMA", "code": "DRAFT_SCHEMA_FAILURE", "path": path, "schema_keyword": keyword,
        })
        rule, instance = error.validator_value, error.instance
        if keyword == "required":
            missing = [name for name in rule if not (isinstance(instance, dict) and name in instance)]
            finding["missing_required_fields"] = sorted(set(finding.get("missing_required_fields", [])) | set(missing))
        elif keyword == "additionalProperties" and rule is False:
            allowed = sorted(error.schema.get("properties", {}))
            finding["allowed_fields"] = allowed
            finding["unexpected_field_count"] = sum(1 for key in instance if key not in allowed)
        elif keyword == "type":
            finding["expected_type"] = rule
        elif keyword == "enum":
            finding["allowed_enum_tokens"] = list(rule)
        elif keyword == "const":
            finding["required_constant"] = rule
        elif keyword == "pattern":
            finding["required_pattern"] = rule
        elif keyword in ("minLength", "maxLength", "minimum", "minItems", "minProperties"):
            finding["limit"] = rule
        elif keyword == "oneOf":
            # Say why each variant was not matched, using that variant's own schema findings.
            by_variant: dict[Any, list[Any]] = {}
            for child in error.context or []:
                by_variant.setdefault(child.relative_schema_path[0] if child.relative_schema_path else None, []).append(child)
            variants = _variant_summary(rule)
            for index, variant in enumerate(variants):
                variant["findings"] = _findings(by_variant.get(index, []), vocabulary)
            finding["variants"] = variants
        elif keyword == "not":
            finding["forbidden_fields"] = list(rule.get("required", []))
    return [grouped[key] for key in sorted(grouped)]


def schema_findings(draft: Any) -> list[dict[str, Any]]:
    """Schema findings for a parsed response against the model schema."""
    return _findings(_model_validator().iter_errors(draft), path_vocabulary())


def compiler_findings(blockers: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic compiler blockers, restricted to phase, code and a sanitized path."""
    vocabulary = path_vocabulary()
    findings = set()
    for blocker in blockers:
        phase, code, path = blocker.get("phase"), blocker.get("code"), blocker.get("path", "")
        if not (isinstance(phase, str) and re.fullmatch(r"[A-Z][A-Z_]{0,39}", phase)
                and isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code) and isinstance(path, str)):
            raise OutputContractError("Compiler blocker is not structural")
        parts = [int(part) if part.isdigit() else part for part in path.split("/") if part and part != "$"]
        findings.add((phase, code, _safe_path(parts, vocabulary)))
    return [{"phase": phase, "code": code, "path": path} for phase, code, path in sorted(findings)]


def structural_diagnostic_v2(raw_response: Any) -> dict[str, Any]:
    """The complete structural diagnostic for one response. Structural information only."""
    try:
        draft = json.loads(raw_response)
    except (TypeError, json.JSONDecodeError):
        category, findings = "JSON_PARSE_FAILURE", [json_error_diagnostic(raw_response)]
    else:
        findings = schema_findings(draft)
        category = "DRAFT_SCHEMA_FAILURE" if findings else None
    return {
        "diagnostic": REPAIR_DIAGNOSTIC_ID,
        "model_schema": MODEL_SCHEMA_IDENTITY,
        "category": category,
        "finding_count": len(findings),
        "findings": findings,
    }


@functools.lru_cache(maxsize=1)
def diagnostic_vocabulary() -> frozenset[str]:
    """Every string a diagnostic may contain apart from paths: schema- and tool-owned only."""
    schema = load_tracked_model_schema()
    strings: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                strings.add(key)
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            strings.add(node)

    walk(schema)
    return frozenset(strings | {
        REPAIR_DIAGNOSTIC_ID, MODEL_SCHEMA_IDENTITY, "JSON", "SCHEMA", "JSON_PARSE_FAILURE", "DRAFT_SCHEMA_FAILURE",
        "$", "EMPTY_RESPONSE", "NON_JSON_PREFIX_SUFFIX", "UNTERMINATED_JSON", "INVALID_PROPERTY_NAME",
        "INVALID_ESCAPE", "EXTRA_DATA", "TRAILING_COMMA", "OTHER_JSON_SYNTAX",
    })


def contract_identity() -> dict[str, Any]:
    """Public-safe identity of the P4 output contract. Reads tracked files only."""
    material = prompt_material()
    schema = load_tracked_model_schema()
    return {
        "extractor_id": P4_EXTRACTOR_ID,
        "canonical_draft_contract": CANONICAL_DRAFT_VERSION,
        "model_schema_identity": MODEL_SCHEMA_IDENTITY,
        "model_schema_sha256": model_schema_sha256(),
        "self_contained": assert_self_contained(schema),
        "repair_diagnostic": REPAIR_DIAGNOSTIC_ID,
        "maximum_structural_repairs_per_case": MAX_STRUCTURAL_REPAIRS_PER_CASE,
        "primary_system_prompt_chars": len(material["primary_system"]),
        "model_or_credential_bound": False,
    }
