"""Project the full P4 model schema to a provider-facing response schema (M4-04B4BR).

The provider rejected the full model schema as a native response schema. This module
derives a weaker schema from it, mechanically, using only the keyword subset the
installed SDK documents for ``response_json_schema``.

The projection is a relaxation. It removes constraints the provider subset cannot
express and rewrites a string or number ``const`` to the equivalent one-value ``enum``.
It adds no rule, renames nothing and removes no property. Every draft the full schema
accepts, the projection accepts; the inverse is not true and is not required.

The projection only shapes provider output. The full model schema stays in the prompt
and the unchanged local Draft V1.1 validator stays authoritative. The tracked projection
file is never edited by hand. Offline only: no provider, no data.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Iterator, Optional

from tools.story_extraction import m4_04b4a_p4_output_contract_v1 as contract
from tools.story_extraction import materialize_draft_v1_1_model_schema_v1 as materializer


REPO_ROOT = materializer.REPO_ROOT
PROJECTION_PATH = REPO_ROOT / "schemas/story_extraction/story_extraction_draft_v1_1_gemini_response_schema_v1.schema.json"
MANIFEST_PATH = REPO_ROOT / "benchmarks/m4_extraction/M4_04B4BR_PROVIDER_SCHEMA_PROJECTION_MANIFEST.json"

PROJECTION_IDENTITY = "STORY_EXTRACTION_DRAFT_V1_1_GEMINI_RESPONSE_SCHEMA_V1"
PROJECTION_TOOL_ID = "DRAFT_V1_1_MODEL_SCHEMA_TO_GEMINI_PROJECTION_V1"
SOURCE_IDENTITY = materializer.MODEL_SCHEMA_IDENTITY
SOURCE_SHA256 = "5aa2ed6dde3791546ddd5e059648d8dac38df1571a6073b7abc31c89eb257f14"
PROJECTION_SHA256 = "89506defa4089b1449f7c80bbcf782d94065802ceae71aa86e1598a5a17ab9bd"

CONST_TO_SINGLETON_ENUM = "CONST_TO_SINGLETON_ENUM"
DROP_CONSTRAINT = "DROP_PROVIDER_UNSUPPORTED_CONSTRAINT"
DROP_METADATA = "DROP_PROVIDER_METADATA"
ACTIONS = (CONST_TO_SINGLETON_ENUM, DROP_CONSTRAINT, DROP_METADATA)

# The offline basis: the keyword subset the installed SDK documents as supported.
PROVIDER_KEYWORDS = contract.NATIVE_DOCUMENTED_KEYWORDS
# Constraints outside that subset with no equivalent inside it. Removed, never approximated.
DROPPED_CONSTRAINTS = ("pattern", "minLength", "maxLength", "minProperties", "uniqueItems", "if", "then", "else", "not")
# Annotations that identify the source document. The projection is a different document.
ROOT_METADATA = ("$schema", "$id", "title", "description")
# How each kept keyword carries sub-schemas.
SCHEMA_MAP_KEYWORDS = ("properties", "$defs")
SCHEMA_LIST_KEYWORDS = ("oneOf", "anyOf", "prefixItems")
SCHEMA_OR_BOOLEAN_KEYWORDS = ("items", "additionalProperties")
VALUE_KEYWORDS = ("type", "enum", "required", "minItems", "maxItems", "minimum", "maximum", "format", "$ref")


class ProjectionError(RuntimeError):
    """The model schema cannot be projected, or a projection invariant does not hold."""


def _pointer(tokens: tuple[str, ...]) -> str:
    return "".join("/" + token.replace("~", "~0").replace("/", "~1") for token in tokens)


def _enum_expressible(value: Any) -> bool:
    """The SDK documents ``enum`` for strings and numbers only."""
    return isinstance(value, str) or (isinstance(value, (int, float)) and not isinstance(value, bool))


def load_source_schema() -> dict[str, Any]:
    """The exact accepted full model schema. No other input is accepted."""
    try:
        schema = materializer.load_tracked_model_schema()
        digest = materializer.model_schema_sha256()
    except materializer.ModelSchemaError as error:
        raise ProjectionError("Full model schema is unavailable or not the materializer output") from error
    if digest != SOURCE_SHA256 or schema.get("title") != SOURCE_IDENTITY:
        raise ProjectionError("Projection input is not the accepted full model schema")
    return schema


def project(schema: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Project one schema document. Returns the projection and its transformation manifest."""
    transformations: list[dict[str, str]] = []

    def note(tokens: tuple[str, ...], keyword: str, action: str) -> None:
        transformations.append({"pointer": _pointer(tokens + (keyword,)), "keyword": keyword, "action": action})

    def walk(node: Any, tokens: tuple[str, ...]) -> Any:
        if not isinstance(node, dict):
            raise ProjectionError("Schema node is not an object: " + _pointer(tokens))
        result: dict[str, Any] = {}
        for keyword, value in node.items():
            here = tokens + (keyword,)
            if keyword == "$schema" or (not tokens and keyword in ROOT_METADATA):
                note(tokens, keyword, DROP_METADATA)
            elif keyword == "const":
                if _enum_expressible(value):
                    if "enum" in node:
                        raise ProjectionError("A const beside an enum cannot be rewritten: " + _pointer(here))
                    result["enum"] = [copy.deepcopy(value)]
                    note(tokens, keyword, CONST_TO_SINGLETON_ENUM)
                else:
                    note(tokens, keyword, DROP_CONSTRAINT)
            elif keyword in DROPPED_CONSTRAINTS:
                note(tokens, keyword, DROP_CONSTRAINT)
            elif keyword in SCHEMA_MAP_KEYWORDS:
                result[keyword] = {name: walk(child, here + (name,)) for name, child in value.items()}
            elif keyword in SCHEMA_LIST_KEYWORDS:
                result[keyword] = [walk(child, here + (str(index),)) for index, child in enumerate(value)]
            elif keyword in SCHEMA_OR_BOOLEAN_KEYWORDS:
                result[keyword] = value if isinstance(value, bool) else walk(value, here)
            elif keyword in VALUE_KEYWORDS:
                result[keyword] = copy.deepcopy(value)
            else:
                raise ProjectionError("Keyword has no projection rule: " + _pointer(here))
        return result

    return walk(schema, ()), transformations


def project_model_schema() -> dict[str, Any]:
    """The provider projection of the accepted full model schema. Deterministic."""
    projection, _ = project(load_source_schema())
    assert_provider_subset(projection)
    return projection


def projection_text(projection: Optional[dict[str, Any]] = None) -> str:
    """The exact text of the tracked projection file."""
    projection = project_model_schema() if projection is None else projection
    return json.dumps(projection, ensure_ascii=False, indent=2) + "\n"


def projection_sha256() -> str:
    return hashlib.sha256(projection_text().encode("utf-8")).hexdigest()


def transformation_manifest() -> dict[str, Any]:
    """Every transformation: JSON pointer, original keyword and action. No story data."""
    _, transformations = project(load_source_schema())
    counts = {action: sum(item["action"] == action for item in transformations) for action in ACTIONS}
    by_keyword: dict[str, int] = {}
    for item in transformations:
        by_keyword[item["keyword"]] = by_keyword.get(item["keyword"], 0) + 1
    return {
        "manifest": "M4_04B4BR_PROVIDER_SCHEMA_PROJECTION_MANIFEST_V1",
        "projection_tool": PROJECTION_TOOL_ID,
        "source_identity": SOURCE_IDENTITY,
        "source_sha256": SOURCE_SHA256,
        "projection_identity": PROJECTION_IDENTITY,
        "projection_sha256": projection_sha256(),
        "transformation_count": len(transformations),
        "action_counts": counts,
        "keyword_counts": dict(sorted(by_keyword.items())),
        "transformations": transformations,
    }


def manifest_text() -> str:
    return json.dumps(transformation_manifest(), ensure_ascii=False, indent=2) + "\n"


def _load_tracked(path: Path, expected: str, label: str) -> Any:
    try:
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    except (OSError, UnicodeError) as error:
        raise ProjectionError(f"Tracked {label} is unavailable") from error
    if text != expected:
        raise ProjectionError(f"Tracked {label} differs from the projection tool output")
    return json.loads(text)


def load_tracked_projection() -> dict[str, Any]:
    """Load the tracked projection only if it is exactly the tool output and the locked hash."""
    projection = _load_tracked(PROJECTION_PATH, projection_text(), "provider projection")
    if projection_sha256() != PROJECTION_SHA256:
        raise ProjectionError("Provider projection hash differs from the locked hash")
    return projection


def load_tracked_manifest() -> dict[str, Any]:
    return _load_tracked(MANIFEST_PATH, manifest_text(), "projection manifest")


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------

def iter_schema_nodes(schema: dict[str, Any], tokens: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], dict[str, Any]]]:
    """Every schema node of a projected document with its pointer tokens."""
    yield tokens, schema
    for keyword, value in schema.items():
        here = tokens + (keyword,)
        if keyword in SCHEMA_MAP_KEYWORDS:
            for name, child in value.items():
                yield from iter_schema_nodes(child, here + (name,))
        elif keyword in SCHEMA_LIST_KEYWORDS:
            for index, child in enumerate(value):
                yield from iter_schema_nodes(child, here + (str(index),))
        elif keyword in SCHEMA_OR_BOOLEAN_KEYWORDS and isinstance(value, dict):
            yield from iter_schema_nodes(value, here)


def _reference_cycle(schema: dict[str, Any]) -> bool:
    graph = {
        name: {ref[len(materializer.LOCAL_PREFIX):] for ref in materializer.iter_refs(definition)}
        for name, definition in schema.get("$defs", {}).items()
    }
    state: dict[str, int] = {}

    def visit(name: str) -> bool:
        if state.get(name) == 1:
            return True
        if state.get(name) == 2:
            return False
        state[name] = 1
        found = any(visit(target) for target in sorted(graph.get(name, ())))
        state[name] = 2
        return found

    return any(visit(name) for name in sorted(graph))


def assert_provider_subset(projection: dict[str, Any]) -> dict[str, Any]:
    """Fail closed unless the projection stays inside the documented provider subset."""
    used: set[str] = set()
    for tokens, node in iter_schema_nodes(projection):
        used.update(node)
        if "$ref" in node and any(not keyword.startswith("$") for keyword in node if keyword != "$ref"):
            raise ProjectionError("A $ref has sibling keywords: " + _pointer(tokens))
        if "enum" in node and not all(_enum_expressible(value) for value in node["enum"]):
            raise ProjectionError("An enum has a value that is not a string or number: " + _pointer(tokens))
    outside = sorted(used - set(PROVIDER_KEYWORDS))
    if outside:
        raise ProjectionError("Projection uses a keyword outside the provider subset: " + outside[0])
    try:
        references = materializer.assert_self_contained(projection)
    except materializer.ModelSchemaError as error:
        raise ProjectionError("Projection has an unresolved reference or a dangling definition") from error
    if _reference_cycle(projection):
        raise ProjectionError("Projection has a cyclic reference")
    return {"keywords_used": sorted(used), "cyclic_references": False, **references}


def _disjoint_variants(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """Two object variants that no instance can satisfy together, shown from kept keywords only."""
    if first.get("type") != "object" or second.get("type") != "object":
        return False
    required_first, required_second = set(first.get("required", ())), set(second.get("required", ()))
    for name in sorted(required_first & required_second):
        one = first.get("properties", {}).get(name, {}).get("enum")
        two = second.get("properties", {}).get(name, {}).get("enum")
        if one is not None and two is not None and not set(one) & set(two):
            return True
    for required, other in ((required_first, second), (required_second, first)):
        if other.get("additionalProperties") is False and required - set(other.get("properties", {})):
            return True
    return False


def one_of_exclusivity(projection: dict[str, Any]) -> dict[str, int]:
    """Fail closed unless every oneOf keeps mutually exclusive variants after projection.

    Removing a constraint inside a oneOf variant could let an instance match two variants,
    which would make the oneOf stricter. Exclusive variants rule that out. They also make
    oneOf and anyOf accept the same instances, which is how the provider reads oneOf.
    """
    checked = 0
    for tokens, node in iter_schema_nodes(projection):
        variants = node.get("oneOf")
        if variants is None:
            continue
        for index, first in enumerate(variants):
            for second in variants[index + 1:]:
                if not _disjoint_variants(first, second):
                    raise ProjectionError("oneOf variants are not provably exclusive: " + _pointer(tokens))
        checked += 1
    return {"one_of_nodes": checked}


def apply_manifest(schema: dict[str, Any], transformations: list[dict[str, str]]) -> dict[str, Any]:
    """Apply a manifest literally to a schema. Independent of the projection walk."""
    result = copy.deepcopy(schema)
    for item in transformations:
        tokens = [part.replace("~1", "/").replace("~0", "~") for part in item["pointer"].split("/")[1:]]
        parent: Any = result
        for token in tokens[:-1]:
            parent = parent[int(token)] if isinstance(parent, list) else parent[token]
        keyword = tokens[-1]
        if keyword != item["keyword"] or keyword not in parent:
            raise ProjectionError("Manifest entry does not match the schema: " + item["pointer"])
        value = parent.pop(keyword)
        if item["action"] == CONST_TO_SINGLETON_ENUM:
            if not _enum_expressible(value) or "enum" in parent:
                raise ProjectionError("Manifest rewrites a const that cannot be an enum: " + item["pointer"])
            parent["enum"] = [value]
        elif item["action"] not in (DROP_CONSTRAINT, DROP_METADATA):
            raise ProjectionError("Manifest has an unknown action")
    return result


def verify_relaxation_by_construction() -> dict[str, Any]:
    """Prove FULL_VALID implies PROJECTION_VALID from the structure of the projection.

    Each manifest entry removes one keyword or replaces a const by its one-value enum.
    Keywords of a schema node are conjunctive, so removing one relaxes that node, and a
    relaxed node relaxes every parent reached through properties, items,
    additionalProperties or a reference. The contexts where that is not true are negation
    and conditionals, which are removed whole, and oneOf, whose variants stay exclusive.
    """
    source = load_source_schema()
    projection, transformations = project(source)
    rebuilt = apply_manifest(source, transformations)
    dropped = set(DROPPED_CONSTRAINTS) | {"const", "$schema"} | set(ROOT_METADATA)
    checks = {
        "projection_is_source_with_only_manifest_edits": rebuilt == projection,
        "every_action_is_authorized": all(item["action"] in ACTIONS for item in transformations),
        "every_transformed_keyword_is_unsupported_or_metadata": all(item["keyword"] in dropped for item in transformations),
        "no_supported_constraint_dropped": not any(
            item["keyword"] in PROVIDER_KEYWORDS and item["action"] == DROP_CONSTRAINT for item in transformations
        ),
        "no_edit_under_negation_or_conditional": not any(
            set(item["pointer"].split("/")[1:-1]) & {"not", "if", "then", "else"} for item in transformations
        ),
        "no_negation_or_conditional_remains": not any(
            keyword in node for _, node in iter_schema_nodes(projection) for keyword in ("not", "if", "then", "else")
        ),
        "one_of_nodes_all_kept_and_exclusive": one_of_exclusivity(projection)["one_of_nodes"]
        == json.dumps(source).count('"oneOf"'),
        "provider_subset_only": bool(assert_provider_subset(projection)),
    }
    if not all(checks.values()):
        raise ProjectionError("Provider projection is not a provable relaxation of the full model schema")
    return {"checks": checks, "transformation_count": len(transformations)}


def lineage_gate() -> dict[str, str]:
    """canonical schemas -> full model schema -> provider projection, each step mechanical."""
    source = load_source_schema()
    if source != materializer.materialize_model_schema():
        raise ProjectionError("Full model schema is not the materializer output")
    materializer.verify_equivalence_by_construction(source)
    projection = load_tracked_projection()
    if projection != project(source)[0]:
        raise ProjectionError("Tracked projection is not the projection of the full model schema")
    if projection == source:
        raise ProjectionError("Provider projection must differ from the full model schema")
    load_tracked_manifest()
    assert_provider_subset(projection)
    verify_relaxation_by_construction()
    return {
        "full_model_schema_equals_materializer_output": "PASS",
        "full_model_schema_sha256": "PASS",
        "tracked_projection_equals_projection_of_full_model_schema": "PASS",
        "projection_sha256": "PASS",
        "tracked_manifest_equals_tool_output": "PASS",
        "projection_external_ref_count_zero": "PASS",
        "projection_inside_documented_provider_subset": "PASS",
        "relaxation_by_construction": "PASS",
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the tracked projection and manifest files")
    args = parser.parse_args(argv)
    try:
        report = assert_provider_subset(project_model_schema())
        verify_relaxation_by_construction()
        if args.write:
            PROJECTION_PATH.write_text(projection_text(), encoding="utf-8", newline="\n")
            MANIFEST_PATH.write_text(manifest_text(), encoding="utf-8", newline="\n")
        else:
            lineage_gate()
    except ProjectionError as error:
        print(f"PROVIDER_PROJECTION_FAILED: {error}")
        return 2
    print(json.dumps({"identity": PROJECTION_IDENTITY, "sha256": projection_sha256(),
                      "external_ref_count": report["external_ref_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
