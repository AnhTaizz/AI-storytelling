"""Model-facing, reference-free bundle of STORY_EXTRACTION_DRAFT_V1_1.

The authoritative V1.1 schema keeps its cross-document ``$ref`` into the frozen V1
schema and is never modified. A model cannot resolve a URN, so the prompt embeds a
derived bundle in which every external reference is inlined as a local ``$defs``
entry. The bundle is documentation for the model only; drafts are still validated
by ``draft_compiler_v1_1`` against the authoritative schema.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[2]
V1_SCHEMA_PATH = REPO_ROOT / "schemas/story_extraction/story_extraction_draft_v1.schema.json"
V1_1_SCHEMA_PATH = REPO_ROOT / "schemas/story_extraction/story_extraction_draft_v1_1.schema.json"
V1_ID = "urn:ai-storytelling:story-extraction:draft:v1"
BUNDLE_ID = "urn:ai-storytelling:story-extraction:draft:v1.1:model-facing-bundle:v1"
BUNDLE_VERSION = "STORY_EXTRACTION_DRAFT_V1_1_MODEL_FACING_BUNDLE_V1"


class SchemaBundleError(ValueError):
    """The authoritative schemas cannot be bundled without losing a definition."""


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _rewrite_refs(value: Any) -> Any:
    if isinstance(value, list):
        return [_rewrite_refs(item) for item in value]
    if not isinstance(value, dict):
        return value
    out = {}
    for key, item in value.items():
        if key == "$ref" and isinstance(item, str):
            if item.startswith(V1_ID + "#/$defs/"):
                item = "#/$defs/" + item[len(V1_ID + "#/$defs/"):]
            elif not item.startswith("#/$defs/"):
                raise SchemaBundleError("Unsupported schema reference")
        out[key] = _rewrite_refs(item)
    return out


def build_bundle() -> dict[str, Any]:
    """Inline the V1 definitions that V1.1 references; V1.1 Mention takes precedence."""
    v1 = _load(V1_SCHEMA_PATH)
    v1_1 = _load(V1_1_SCHEMA_PATH)
    if v1.get("$id") != V1_ID:
        raise SchemaBundleError("Unexpected V1 schema identity")
    definitions = deepcopy(v1["$defs"])
    definitions.pop("Mention", None)
    for name, definition in v1_1.get("$defs", {}).items():
        definitions[name] = deepcopy(definition)
    bundle = {key: deepcopy(value) for key, value in v1_1.items() if key not in {"$id", "$defs"}}
    bundle["$id"] = BUNDLE_ID
    bundle["$comment"] = (
        "Derived model-facing bundle of STORY_EXTRACTION_DRAFT_V1_1. "
        "Validation authority remains the unmodified V1.1 schema."
    )
    # The authoritative description documents the V1 migration history and names the
    # removed field. Annotations do not affect validation, so the model sees only the
    # current contract.
    bundle["description"] = (
        "Semantic-only model output. A mention is an exact quote locator; the host "
        "creates its evidence locator. Assertion support cites authored evidence only."
    )
    bundle["$defs"] = definitions
    bundle = _rewrite_refs(bundle)
    unresolved = _unresolved_local_refs(bundle)
    if unresolved:
        raise SchemaBundleError("Bundle has unresolved local references")
    used = _local_refs(bundle)
    bundle["$defs"] = {name: bundle["$defs"][name] for name in sorted(used)}
    return bundle


def _local_refs(value: Any, found: set[str] | None = None) -> set[str]:
    found = set() if found is None else found
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "$ref" and isinstance(item, str) and item.startswith("#/$defs/"):
                found.add(item[len("#/$defs/"):])
            else:
                _local_refs(item, found)
    elif isinstance(value, list):
        for item in value:
            _local_refs(item, found)
    return found


def _unresolved_local_refs(bundle: dict[str, Any]) -> set[str]:
    return _local_refs(bundle) - set(bundle["$defs"])


def bundle_text() -> str:
    """Canonical text embedded in the prompt (LF, sorted keys, two-space indent)."""
    return json.dumps(build_bundle(), ensure_ascii=False, indent=2, sort_keys=True)


def bundle_sha256() -> str:
    return hashlib.sha256(bundle_text().encode("utf-8")).hexdigest()


def bundle_validator() -> Draft202012Validator:
    bundle = build_bundle()
    Draft202012Validator.check_schema(bundle)
    return Draft202012Validator(bundle)
