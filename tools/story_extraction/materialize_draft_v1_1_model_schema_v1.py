"""Materialize the self-contained model-facing schema for STORY_EXTRACTION_DRAFT_V1_1.

The canonical Draft V1.1 schema is a delta: it defines the root object and Mention and
refers to the Draft V1 schema for every other record. A model shown only that file never
sees those definitions. This module copies every Draft V1 definition the delta needs into
one local $defs namespace and rewrites the external references to local ones.

The result changes no rule. It is derived mechanically from the two canonical files and is
verified against them; it is never edited by hand. Offline only: no provider, no data.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Iterator, Optional


REPO_ROOT = Path(__file__).resolve().parents[2]
V1_SCHEMA_PATH = REPO_ROOT / "schemas/story_extraction/story_extraction_draft_v1.schema.json"
V1_1_SCHEMA_PATH = REPO_ROOT / "schemas/story_extraction/story_extraction_draft_v1_1.schema.json"
MODEL_SCHEMA_PATH = REPO_ROOT / "schemas/story_extraction/story_extraction_draft_v1_1_model_schema_v1.schema.json"

MODEL_SCHEMA_IDENTITY = "STORY_EXTRACTION_DRAFT_V1_1_MODEL_SCHEMA_V1"
MODEL_SCHEMA_ID = "urn:ai-storytelling:story-extraction:draft:v1.1:model-schema:v1"
CANONICAL_DRAFT_VERSION = "STORY_EXTRACTION_DRAFT_V1_1"
MODEL_SCHEMA_DESCRIPTION = (
    "Self-contained model-facing form of STORY_EXTRACTION_DRAFT_V1_1. Every definition is local; "
    "no reference leaves this document. Materialized mechanically from the canonical Draft V1 and "
    "Draft V1.1 schemas without changing any rule."
)
LOCAL_PREFIX = "#/$defs/"
ANNOTATION_KEYS = ("$id", "title", "description", "$defs")


class ModelSchemaError(RuntimeError):
    """The canonical schemas cannot be materialized, or a schema is not self-contained."""


def _load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ModelSchemaError("Canonical schema is unavailable: " + path.name) from error


def iter_refs(node: Any) -> Iterator[str]:
    """Every $ref value in a schema, including refs nested in arrays."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref":
                if not isinstance(value, str):
                    raise ModelSchemaError("A $ref must be a string")
                yield value
            else:
                yield from iter_refs(value)
    elif isinstance(node, list):
        for value in node:
            yield from iter_refs(value)


def _rewrite(node: Any, external_prefix: str) -> Any:
    """A copy of a schema node with references to the Draft V1 resource made local."""
    if isinstance(node, dict):
        return {
            key: (LOCAL_PREFIX + value[len(external_prefix):]
                  if key == "$ref" and isinstance(value, str) and value.startswith(external_prefix)
                  else _rewrite(value, external_prefix))
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [_rewrite(value, external_prefix) for value in node]
    return copy.deepcopy(node)


def _closure(v1: dict[str, Any], v1_1: dict[str, Any], external_prefix: str) -> list[str]:
    """Draft V1 definitions reachable from the Draft V1.1 delta, in Draft V1 file order."""
    pending = [ref[len(external_prefix):] for ref in iter_refs(v1_1) if ref.startswith(external_prefix)]
    needed: set[str] = set()
    while pending:
        name = pending.pop()
        if name in needed:
            continue
        if name not in v1["$defs"]:
            raise ModelSchemaError("Draft V1.1 refers to an unknown Draft V1 definition: " + name)
        needed.add(name)
        for ref in iter_refs(v1["$defs"][name]):
            if not ref.startswith(LOCAL_PREFIX):
                raise ModelSchemaError("Draft V1 definition has a non-local reference: " + name)
            pending.append(ref[len(LOCAL_PREFIX):])
    return [name for name in v1["$defs"] if name in needed]


def materialize_model_schema() -> dict[str, Any]:
    """Build the model-facing schema from the two canonical files. Deterministic."""
    v1, v1_1 = _load(V1_SCHEMA_PATH), _load(V1_1_SCHEMA_PATH)
    external_prefix = v1["$id"] + LOCAL_PREFIX
    for ref in iter_refs(v1_1):
        if not (ref.startswith(LOCAL_PREFIX) or ref.startswith(external_prefix)):
            raise ModelSchemaError("Draft V1.1 has a reference to an unknown resource")
    copied = _closure(v1, v1_1, external_prefix)
    local = list(v1_1.get("$defs", {}))
    collisions = sorted(set(copied) & set(local))
    if collisions:
        raise ModelSchemaError("Definition name collision: " + collisions[0])
    schema = {
        "$schema": v1_1["$schema"],
        "$id": MODEL_SCHEMA_ID,
        "title": MODEL_SCHEMA_IDENTITY,
        "description": MODEL_SCHEMA_DESCRIPTION,
    }
    for key, value in v1_1.items():
        if key not in ("$schema",) + ANNOTATION_KEYS:
            schema[key] = _rewrite(value, external_prefix)
    schema["$defs"] = {name: _rewrite(v1_1["$defs"][name], external_prefix) for name in local}
    schema["$defs"].update({name: copy.deepcopy(v1["$defs"][name]) for name in copied})
    assert_self_contained(schema)
    return schema


def resolve_local_ref(schema: dict[str, Any], ref: str) -> Any:
    """Resolve a reference inside the given schema object, or fail closed."""
    if not ref.startswith("#/"):
        raise ModelSchemaError("Reference leaves the schema supplied to the model")
    node: Any = schema
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            raise ModelSchemaError("Reference does not resolve inside the schema: " + ref)
        node = node[part]
    return node


def external_refs(schema: dict[str, Any]) -> list[str]:
    """References that do not resolve inside this exact schema object."""
    unresolved = []
    for ref in iter_refs(schema):
        try:
            resolve_local_ref(schema, ref)
        except ModelSchemaError:
            unresolved.append(ref)
    return sorted(set(unresolved))


def assert_self_contained(schema: dict[str, Any]) -> dict[str, int]:
    """Fail closed unless every reference resolves inside the schema and nothing is dynamic."""
    def keys(node: Any) -> Iterator[str]:
        if isinstance(node, dict):
            for key, value in node.items():
                yield key
                yield from keys(value)
        elif isinstance(node, list):
            for value in node:
                yield from keys(value)

    if any(key in ("$dynamicRef", "$recursiveRef", "$anchor", "$dynamicAnchor") for key in keys(schema)):
        raise ModelSchemaError("Dynamic or anchored references are not allowed in the model schema")
    unresolved = external_refs(schema)
    if unresolved:
        raise ModelSchemaError("Model schema has an external or unresolved reference")
    referenced = {ref[len(LOCAL_PREFIX):] for ref in iter_refs(schema)}
    unused = sorted(set(schema.get("$defs", {})) - referenced)
    if unused:
        raise ModelSchemaError("Model schema carries an unreferenced definition: " + unused[0])
    return {
        "external_ref_count": 0,
        "ref_count": sum(1 for _ in iter_refs(schema)),
        "definition_count": len(schema.get("$defs", {})),
    }


def verify_equivalence_by_construction(schema: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Prove the model schema is the canonical contract with only its references relocated."""
    schema = materialize_model_schema() if schema is None else schema
    v1, v1_1 = _load(V1_SCHEMA_PATH), _load(V1_1_SCHEMA_PATH)
    external_prefix = v1["$id"] + LOCAL_PREFIX
    copied = _closure(v1, v1_1, external_prefix)
    local = list(v1_1.get("$defs", {}))
    root = {key: value for key, value in schema.items() if key not in ANNOTATION_KEYS}
    canonical_root = _rewrite({key: value for key, value in v1_1.items() if key not in ANNOTATION_KEYS}, external_prefix)
    checks = {
        "root_equals_draft_v1_1_root": root == canonical_root,
        "definition_set_is_exact": list(schema["$defs"]) == local + copied,
        "local_definitions_equal_draft_v1_1": all(
            schema["$defs"][name] == _rewrite(v1_1["$defs"][name], external_prefix) for name in local
        ),
        "copied_definitions_equal_draft_v1": all(schema["$defs"][name] == v1["$defs"][name] for name in copied),
        "mention_has_no_evidence_handle": "evidence_handle" not in schema["$defs"]["Mention"]["properties"],
        "draft_version_constant_unchanged": schema["properties"]["draft_version"] == {"const": CANONICAL_DRAFT_VERSION},
    }
    if not all(checks.values()):
        raise ModelSchemaError("Model schema is not equivalent to the canonical Draft V1.1 contract")
    return {
        "checks": checks,
        "definitions_from_draft_v1_1": local,
        "definitions_copied_from_draft_v1": copied,
        "draft_v1_definitions_not_needed": [name for name in v1["$defs"] if name not in copied],
    }


def model_schema_text(schema: Optional[dict[str, Any]] = None) -> str:
    """The exact text supplied to the model and written to the tracked file."""
    schema = materialize_model_schema() if schema is None else schema
    return json.dumps(schema, ensure_ascii=False, indent=2) + "\n"


def model_schema_sha256() -> str:
    return hashlib.sha256(model_schema_text().encode("utf-8")).hexdigest()


def load_tracked_model_schema() -> dict[str, Any]:
    """Load the tracked file only if it is exactly what the materializer produces."""
    try:
        text = MODEL_SCHEMA_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
    except (OSError, UnicodeError) as error:
        raise ModelSchemaError("Tracked model schema is unavailable") from error
    if text != model_schema_text():
        raise ModelSchemaError("Tracked model schema differs from the materializer output")
    return json.loads(text)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the tracked model schema file")
    args = parser.parse_args(argv)
    try:
        schema = materialize_model_schema()
        verify_equivalence_by_construction(schema)
        report = assert_self_contained(schema)
        if args.write:
            MODEL_SCHEMA_PATH.write_text(model_schema_text(schema), encoding="utf-8", newline="\n")
        else:
            load_tracked_model_schema()
    except ModelSchemaError as error:
        print(f"MODEL_SCHEMA_MATERIALIZATION_FAILED: {error}")
        return 2
    print(json.dumps({"identity": MODEL_SCHEMA_IDENTITY, "sha256": model_schema_sha256(), **report}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
