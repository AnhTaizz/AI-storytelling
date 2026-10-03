"""Compile STORY_EXTRACTION_DRAFT_V1_1 without model-facing mention evidence links.

V1.1 is an additive interface version. The model supplies an exact mention locator,
and deterministic code creates or reuses an EvidenceRef only when passage span and
role are identical. Assertion support remains limited to model-authored evidence[].
No semantic assertion, entity identity, predicate, or truth value is inferred here.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from tools.story_extraction.draft_compiler_v1 import (
    ARG_COLLECTIONS,
    COLLECTIONS,
    DraftCompilationError,
    DraftCompilerContext,
    _context_maps,
    _quote_ref,
    compile_story_extraction_draft_v1,
    prepare_story_extraction_draft_v1,
    validate_draft_v1,
)
from tools.story_ingestion.light_novel_adapter_v0 import materialize_evidence_ref


DRAFT_VERSION = "STORY_EXTRACTION_DRAFT_V1_1"
V1_DRAFT_VERSION = "STORY_EXTRACTION_DRAFT_V1"
SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "schemas/story_extraction/story_extraction_draft_v1_1.schema.json"
)
V1_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "schemas/story_extraction/story_extraction_draft_v1.schema.json"
)


@dataclass(frozen=True, order=True)
class StructuralBlocker:
    """A source-text-free deterministic blocker suitable for repair feedback."""

    phase: str
    code: str
    path: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"phase": self.phase, "code": self.code, "path": self.path}


class DraftCompilationErrorV1_1(DraftCompilationError):
    """Fail-closed compilation error carrying every feasible deterministic blocker."""

    def __init__(self, blockers: list[StructuralBlocker] | tuple[StructuralBlocker, ...]):
        ordered = tuple(sorted(set(blockers)))
        if not ordered:
            raise ValueError("At least one structural blocker is required")
        self.blockers = ordered
        first = ordered[0]
        super().__init__(first.code, first.path)


def _validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    v1_schema = json.loads(V1_SCHEMA_PATH.read_text(encoding="utf-8"))
    registry = Registry().with_resource(
        v1_schema["$id"], Resource.from_contents(v1_schema)
    )
    return Draft202012Validator(schema, registry=registry)


def _schema_blockers(draft: Any) -> list[StructuralBlocker]:
    errors = sorted(
        _validator().iter_errors(draft),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    return [
        StructuralBlocker(
            "SCHEMA",
            "DRAFT_SCHEMA_FAILURE",
            "/".join(map(str, error.absolute_path)),
        )
        for error in errors
    ]


def validate_draft_v1_1(draft: Any) -> None:
    """Validate V1.1 and report all schema blockers without echoing values."""
    blockers = _schema_blockers(draft)
    if blockers:
        raise DraftCompilationErrorV1_1(blockers)


def migrate_draft_v1_to_v1_1(draft: Any) -> dict[str, Any]:
    """Mechanically remove mention evidence_handle and change only the version tag."""
    validate_draft_v1(draft)
    migrated = deepcopy(draft)
    migrated["draft_version"] = DRAFT_VERSION
    for mention in migrated["mentions"]:
        mention.pop("evidence_handle", None)
    validate_draft_v1_1(migrated)
    return migrated


def prepare_story_extraction_draft_v1_1(
    context: DraftCompilerContext,
) -> dict[str, Any]:
    """Return the V1.1 model surface without any mention evidence_handle field."""
    prepared = prepare_story_extraction_draft_v1(context)
    prepared["draft_version"] = DRAFT_VERSION
    for handle, record in prepared["existing_context"].items():
        if handle.startswith("M_EXISTING_") and isinstance(record, dict):
            record.pop("evidence_handle", None)
    return prepared


def _check_handle(
    blockers: list[StructuralBlocker],
    handles: Mapping[str, str],
    handle: Any,
    expected_collection: str,
    path: str,
) -> None:
    if handle not in handles:
        blockers.append(StructuralBlocker("HANDLE", "UNKNOWN_HANDLE", path))
    elif handles[handle] != expected_collection:
        blockers.append(StructuralBlocker("HANDLE", "HANDLE_TYPE_MISMATCH", path))


def _check_support(
    blockers: list[StructuralBlocker],
    support: Mapping[str, Any],
    handles: Mapping[str, str],
    authored_evidence: set[str],
    path: str,
) -> None:
    for set_index, evidence_set in enumerate(support["evidence_sets"]):
        for handle_index, handle in enumerate(evidence_set["evidence_handles"]):
            target_path = f"{path}/evidence_sets/{set_index}/evidence_handles/{handle_index}"
            if handle not in authored_evidence:
                blockers.append(
                    StructuralBlocker("HANDLE", "PRIOR_CONTEXT_NOT_EVIDENCE", target_path)
                )
            else:
                _check_handle(blockers, handles, handle, "evidence_refs", target_path)
    for derivation_index, derivation in enumerate(support["derivations"]):
        for premise_index, handle in enumerate(derivation["premise_handles"]):
            _check_handle(
                blockers,
                handles,
                handle,
                "assertions",
                f"{path}/derivations/{derivation_index}/premise_handles/{premise_index}",
            )


def collect_draft_structural_blockers_v1_1(
    draft: Any,
    context: DraftCompilerContext,
) -> tuple[StructuralBlocker, ...]:
    """Collect independent deterministic blockers when later checks remain feasible."""
    schema_blockers = _schema_blockers(draft)
    if schema_blockers:
        return tuple(sorted(set(schema_blockers)))
    try:
        passages, existing = _context_maps(context)
    except DraftCompilationError as error:
        return (StructuralBlocker("CONTEXT", error.code, error.path),)

    blockers: list[StructuralBlocker] = []
    for field in ("evidence", "mentions"):
        for record in sorted(draft[field], key=lambda value: value["handle"]):
            try:
                _quote_ref(record, passages, context)
            except DraftCompilationError as error:
                blockers.append(
                    StructuralBlocker("QUOTE", error.code, f"{field}/{record['handle']}")
                )

    handles = {handle: collection for handle, (collection, _) in existing.items()}
    for field, collection in COLLECTIONS.items():
        for record in sorted(draft[field], key=lambda value: value["handle"]):
            handle = record["handle"]
            if handle in handles:
                blockers.append(StructuralBlocker("HANDLE", "DUPLICATE_HANDLE", handle))
            else:
                handles[handle] = collection

    for record in draft["events"]:
        _check_handle(
            blockers,
            handles,
            record["anchor_handle"],
            "temporal_anchors",
            f"events/{record['handle']}/anchor_handle",
        )
    for record in draft["anchors"]:
        if "event_handle" in record:
            _check_handle(
                blockers,
                handles,
                record["event_handle"],
                "events",
                f"anchors/{record['handle']}/event_handle",
            )
    for record in draft["propositions"]:
        for argument_name, argument in record.get("args", {}).items():
            if "handle" in argument:
                _check_handle(
                    blockers,
                    handles,
                    argument["handle"],
                    ARG_COLLECTIONS[argument["kind"]],
                    f"propositions/{record['handle']}/args/{argument_name}/handle",
                )

    authored_evidence = {record["handle"] for record in draft["evidence"]}
    for record in draft["assertions"]:
        handle = record["handle"]
        _check_handle(
            blockers,
            handles,
            record["proposition_handle"],
            "propositions",
            f"assertions/{handle}/proposition_handle",
        )
        _check_support(
            blockers,
            record["support"],
            handles,
            authored_evidence,
            f"assertions/{handle}/support",
        )
        for side, bound in record.get("validity", {}).items():
            if "anchor_handle" in bound:
                _check_handle(
                    blockers,
                    handles,
                    bound["anchor_handle"],
                    "temporal_anchors",
                    f"assertions/{handle}/validity/{side}/anchor_handle",
                )
            if "support" in bound:
                _check_support(
                    blockers,
                    bound["support"],
                    handles,
                    authored_evidence,
                    f"assertions/{handle}/validity/{side}/support",
                )
        ambiguity = record.get("textual_ambiguity", {})
        for index, alternative in enumerate(
            ambiguity.get("alternative_proposition_handles", [])
        ):
            _check_handle(
                blockers,
                handles,
                alternative,
                "propositions",
                f"assertions/{handle}/textual_ambiguity/alternative_proposition_handles/{index}",
            )
    return tuple(sorted(set(blockers)))


def _evidence_signature(
    record: Mapping[str, Any], passages: Mapping[str, Any], context: DraftCompilerContext
) -> str:
    ref = _quote_ref(record, passages, context)
    materialized = materialize_evidence_ref(ref, record["role"], "signature")
    materialized.pop("id", None)
    return json.dumps(materialized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def bind_exact_mention_evidence_v1_1(
    draft: Any,
    context: DraftCompilerContext,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Create a compiler-internal V1 draft with exact mention EvidenceRef aliases."""
    blockers = collect_draft_structural_blockers_v1_1(draft, context)
    if blockers:
        raise DraftCompilationErrorV1_1(blockers)
    passages, _ = _context_maps(context)
    transformed = deepcopy(draft)
    transformed["draft_version"] = V1_DRAFT_VERSION
    by_signature: dict[str, str] = {}
    origin: dict[str, str] = {}
    for record in sorted(transformed["evidence"], key=lambda value: value["handle"]):
        signature = _evidence_signature(record, passages, context)
        if signature not in by_signature:
            by_signature[signature] = record["handle"]
            origin[signature] = "MODEL_EVIDENCE"

    used_numbers = {
        int(record["handle"][2:]) for record in transformed["evidence"]
    }
    next_number = 1
    stats = {
        "mention_count": len(transformed["mentions"]),
        "reused_exact_model_evidence": 0,
        "reused_exact_prior_mention_evidence": 0,
        "created_exact_mention_evidence": 0,
    }
    for mention in sorted(transformed["mentions"], key=lambda value: value["handle"]):
        signature = _evidence_signature(mention, passages, context)
        evidence_handle = by_signature.get(signature)
        if evidence_handle is None:
            while next_number in used_numbers:
                next_number += 1
            evidence_handle = f"EV{next_number}"
            used_numbers.add(next_number)
            next_number += 1
            evidence_record = {
                key: deepcopy(mention[key])
                for key in ("passage_handle", "quote", "occurrence", "role")
                if key in mention
            }
            evidence_record["handle"] = evidence_handle
            transformed["evidence"].append(evidence_record)
            by_signature[signature] = evidence_handle
            origin[signature] = "MENTION_EVIDENCE"
            stats["created_exact_mention_evidence"] += 1
        elif origin[signature] == "MODEL_EVIDENCE":
            stats["reused_exact_model_evidence"] += 1
        else:
            stats["reused_exact_prior_mention_evidence"] += 1
        mention["evidence_handle"] = evidence_handle
    return transformed, stats


def compile_story_extraction_draft_v1_1(
    draft: Any,
    context: DraftCompilerContext,
) -> dict[str, Any]:
    """Compile V1.1 through the unchanged V1 canonical compiler after exact binding."""
    transformed, _ = bind_exact_mention_evidence_v1_1(draft, context)
    try:
        return compile_story_extraction_draft_v1(transformed, context)
    except DraftCompilationError as error:
        raise DraftCompilationErrorV1_1(
            [StructuralBlocker("CANONICAL_COMPILER", error.code, error.path)]
        ) from error
