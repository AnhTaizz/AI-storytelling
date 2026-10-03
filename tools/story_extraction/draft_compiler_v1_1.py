"""Deterministic compiler for STORY_EXTRACTION_DRAFT_V1_1.

The model supplies exact mention locators but never mention evidence identifiers.
This compiler reuses only an identical resolved span+role EvidenceRef, otherwise it
creates one. It adds no semantic assertion, identity, truth, event, or causality.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from tools.canonical_story.conformance_v0 import load_registry
from tools.story_extraction.draft_compiler_v1 import (
    ARG_COLLECTIONS,
    COLLECTIONS,
    DraftCompilationError,
    DraftCompilerContext,
    _context_maps,
    _quote_ref,
    compile_story_extraction_draft_v1,
    prepare_story_extraction_draft_v1,
)
from tools.story_ingestion.light_novel_adapter_v0 import materialize_evidence_ref


DRAFT_VERSION = "STORY_EXTRACTION_DRAFT_V1_1"
V1_DRAFT_VERSION = "STORY_EXTRACTION_DRAFT_V1"
ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas/story_extraction/story_extraction_draft_v1_1.schema.json"
V1_SCHEMA_PATH = ROOT / "schemas/story_extraction/story_extraction_draft_v1.schema.json"


@dataclass(frozen=True, order=True)
class StructuralBlocker:
    phase: str
    code: str
    path: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"phase": self.phase, "code": self.code, "path": self.path}


class DraftCompilationErrorV1_1(DraftCompilationError):
    """A fail-closed error carrying all independently detectable blockers."""

    def __init__(self, blockers):
        ordered = tuple(sorted(set(blockers)))
        if not ordered:
            raise ValueError("At least one blocker is required")
        self.blockers = ordered
        super().__init__(ordered[0].code, ordered[0].path)


def _validator():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    v1 = json.loads(V1_SCHEMA_PATH.read_text(encoding="utf-8"))
    registry = Registry().with_resource(v1["$id"], Resource.from_contents(v1))
    return Draft202012Validator(schema, registry=registry)


def _schema_blockers(draft):
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


def validate_draft_v1_1(draft):
    blockers = _schema_blockers(draft)
    if blockers:
        raise DraftCompilationErrorV1_1(blockers)


def prepare_story_extraction_draft_v1_1(context: DraftCompilerContext):
    prepared = prepare_story_extraction_draft_v1(context)
    prepared["draft_version"] = DRAFT_VERSION
    for handle, record in prepared["existing_context"].items():
        if handle.startswith("M_EXISTING_") and isinstance(record, dict):
            record.pop("evidence_handle", None)
    return prepared


def _check_handle(blockers, handles, handle, expected, path):
    if handle not in handles:
        blockers.append(StructuralBlocker("HANDLE", "UNKNOWN_HANDLE", path))
    elif handles[handle] != expected:
        blockers.append(StructuralBlocker("HANDLE", "HANDLE_TYPE_MISMATCH", path))


def _check_support(blockers, support, handles, evidence, path, rules):
    for set_index, evidence_set in enumerate(support["evidence_sets"]):
        for handle_index, handle in enumerate(evidence_set["evidence_handles"]):
            target = f"{path}/evidence_sets/{set_index}/evidence_handles/{handle_index}"
            if handle not in evidence:
                blockers.append(StructuralBlocker("HANDLE", "PRIOR_CONTEXT_NOT_EVIDENCE", target))
            else:
                _check_handle(blockers, handles, handle, "evidence_refs", target)
    for derivation_index, derivation in enumerate(support["derivations"]):
        base = f"{path}/derivations/{derivation_index}"
        if derivation["rule_id"] not in rules:
            blockers.append(StructuralBlocker("REGISTRY", "UNREGISTERED_RULE", f"{base}/rule_id"))
        for premise_index, handle in enumerate(derivation["premise_handles"]):
            _check_handle(
                blockers,
                handles,
                handle,
                "assertions",
                f"{base}/premise_handles/{premise_index}",
            )


def collect_draft_structural_blockers_v1_1(draft, context):
    """Return ordered, source-text-free blockers without semantic repair."""
    blockers = _schema_blockers(draft)
    if blockers:
        return tuple(sorted(set(blockers)))
    try:
        passages, existing = _context_maps(context)
    except DraftCompilationError as error:
        return (StructuralBlocker("CONTEXT", error.code, error.path),)

    blockers = []
    for field in ("evidence", "mentions"):
        for record in sorted(draft[field], key=lambda item: item["handle"]):
            try:
                _quote_ref(record, passages, context)
            except DraftCompilationError as error:
                blockers.append(StructuralBlocker("QUOTE", error.code, f"{field}/{record['handle']}"))

    handles = {handle: collection for handle, (collection, _) in existing.items()}
    for field, collection in COLLECTIONS.items():
        for record in sorted(draft[field], key=lambda item: item["handle"]):
            handle = record["handle"]
            if handle in handles:
                blockers.append(StructuralBlocker("HANDLE", "DUPLICATE_HANDLE", handle))
            else:
                handles[handle] = collection

    registry = load_registry()
    predicates = registry["predicates"]
    rules = registry["derivation_rules"]
    event_kinds = set(registry["vocabularies"]["event_kind"])
    for record in draft["events"]:
        if record["event_kind"] not in event_kinds:
            blockers.append(
                StructuralBlocker("REGISTRY", "UNREGISTERED_EVENT_KIND", f"events/{record['handle']}/event_kind")
            )
        _check_handle(
            blockers, handles, record["anchor_handle"], "temporal_anchors",
            f"events/{record['handle']}/anchor_handle",
        )
    for record in draft["anchors"]:
        if "event_handle" in record:
            _check_handle(
                blockers, handles, record["event_handle"], "events",
                f"anchors/{record['handle']}/event_handle",
            )
    for record in draft["propositions"]:
        if "predicate" not in record:
            continue
        if record["predicate"] not in predicates:
            blockers.append(
                StructuralBlocker("REGISTRY", "UNREGISTERED_PREDICATE", f"propositions/{record['handle']}/predicate")
            )
        for name, argument in record["args"].items():
            if "handle" in argument:
                _check_handle(
                    blockers, handles, argument["handle"], ARG_COLLECTIONS[argument["kind"]],
                    f"propositions/{record['handle']}/args/{name}/handle",
                )

    evidence = {record["handle"] for record in draft["evidence"]}
    for record in draft["assertions"]:
        handle = record["handle"]
        _check_handle(
            blockers, handles, record["proposition_handle"], "propositions",
            f"assertions/{handle}/proposition_handle",
        )
        _check_support(blockers, record["support"], handles, evidence, f"assertions/{handle}/support", rules)
        for side, bound in record.get("validity", {}).items():
            if "anchor_handle" in bound:
                _check_handle(
                    blockers, handles, bound["anchor_handle"], "temporal_anchors",
                    f"assertions/{handle}/validity/{side}/anchor_handle",
                )
            if "support" in bound:
                _check_support(
                    blockers, bound["support"], handles, evidence,
                    f"assertions/{handle}/validity/{side}/support", rules,
                )
        for index, alternative in enumerate(
            record.get("textual_ambiguity", {}).get("alternative_proposition_handles", [])
        ):
            _check_handle(
                blockers, handles, alternative, "propositions",
                f"assertions/{handle}/textual_ambiguity/alternative_proposition_handles/{index}",
            )
    return tuple(sorted(set(blockers)))


def _signature(record: Mapping[str, Any], passages, context):
    ref = _quote_ref(record, passages, context)
    value = materialize_evidence_ref(ref, record["role"], "signature")
    value.pop("id", None)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def bind_exact_mention_evidence_v1_1(draft, context):
    """Return a compiler-internal V1 draft and public-safe binding counts."""
    blockers = collect_draft_structural_blockers_v1_1(draft, context)
    if blockers:
        raise DraftCompilationErrorV1_1(blockers)
    passages, _ = _context_maps(context)
    transformed = deepcopy(draft)
    transformed["draft_version"] = V1_DRAFT_VERSION
    by_signature = {}
    origin = {}
    for record in sorted(transformed["evidence"], key=lambda item: item["handle"]):
        signature = _signature(record, passages, context)
        if signature not in by_signature:
            by_signature[signature] = record["handle"]
            origin[signature] = "MODEL_EVIDENCE"

    used = {int(item["handle"][2:]) for item in transformed["evidence"]}
    next_number = 1
    stats = {
        "mention_count": len(transformed["mentions"]),
        "reused_exact_model_evidence": 0,
        "reused_exact_prior_mention_evidence": 0,
        "created_exact_mention_evidence": 0,
    }
    for mention in sorted(transformed["mentions"], key=lambda item: item["handle"]):
        signature = _signature(mention, passages, context)
        evidence_handle = by_signature.get(signature)
        if evidence_handle is None:
            while next_number in used:
                next_number += 1
            evidence_handle = f"EV{next_number}"
            used.add(next_number)
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


def compile_story_extraction_draft_v1_1(draft, context):
    transformed, _ = bind_exact_mention_evidence_v1_1(draft, context)
    try:
        return compile_story_extraction_draft_v1(transformed, context)
    except DraftCompilationError as error:
        raise DraftCompilationErrorV1_1(
            [StructuralBlocker("CANONICAL_COMPILER", error.code, error.path)]
        ) from error
