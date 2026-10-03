"""Compile semantic handles and exact quotes to frozen STORY_EXTRACTION_BATCH/v0.

No extraction, inference, repair, provider access or evaluator changes occur here.
The caller supplies trusted source/context; model output supplies every semantic
choice. Invalid/ambiguous drafts fail closed without returning a partial batch.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from tools.canonical_story.conformance_v0 import validate_document
from tools.story_extraction.extraction_contract_guard_v1 import validate_batch_guarded
from tools.story_extraction.extraction_contract_v0 import (
    BATCH_VERSION, CONTRACT_VERSION, CANDIDATE_COLLECTIONS, document_sha256,
)
from tools.story_ingestion.light_novel_adapter_v0 import materialize_evidence_ref

DRAFT_VERSION = "STORY_EXTRACTION_DRAFT_V1"
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas/story_extraction/story_extraction_draft_v1.schema.json"
COLLECTIONS = {
    "evidence": "evidence_refs", "mentions": "mentions", "entities": "entities",
    "events": "events", "anchors": "temporal_anchors",
    "propositions": "propositions", "assertions": "assertions",
}
EXISTING_PREFIXES = {
    "evidence_refs": "EV", "mentions": "M", "entities": "E", "events": "EVT",
    "temporal_anchors": "T", "propositions": "PROP", "assertions": "A",
}
ARG_COLLECTIONS = {
    "ENTITY": "entities", "EVENT": "events", "ANCHOR": "temporal_anchors",
    "MENTION": "mentions", "PROPOSITION": "propositions",
}


class DraftCompilationError(ValueError):
    """A coded failure; details deliberately exclude private quotes/source text."""

    def __init__(self, code: str, path: str = ""):
        self.code, self.path = code, path
        super().__init__(f"{code}: {path}" if path else code)


@dataclass(frozen=True)
class DraftCompilerContext:
    """Trusted host inputs. Never ask a model to reproduce these fields."""

    base_document: dict[str, Any]
    passage_inputs: list[dict[str, Any]]
    as_of_position: dict[str, Any]
    profile_id: str
    process_id: str
    process_version: str
    run_id: str
    ingestion: Any


def validate_draft_v1(draft: Any) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(draft),
                    key=lambda e: tuple(str(p) for p in e.absolute_path))
    if errors:
        raise DraftCompilationError("DRAFT_SCHEMA_FAILURE", "/".join(map(str, errors[0].absolute_path)))


def _context_maps(context: DraftCompilerContext):
    if context.ingestion is None:
        raise DraftCompilationError("EXACT_SOURCE_REQUIRED")
    base = context.base_document
    if not validate_document(base)["pass"]:
        raise DraftCompilationError("INVALID_BASE")
    if not context.passage_inputs:
        raise DraftCompilationError("EMPTY_SCOPE")
    stream = base["story"]["discourse_stream_id"]
    as_of = context.as_of_position
    if (not isinstance(as_of, dict) or set(as_of) - {"stream_id", "key", "display"}
            or as_of.get("stream_id") != stream or not isinstance(as_of.get("key"), list)
            or not 1 <= len(as_of["key"]) <= 8
            or any(type(k) is not int or k < 0 for k in as_of["key"])):
        raise DraftCompilationError("INVALID_AS_OF")
    segments = {r["id"]: r for r in base["source_segments"]}
    source_segments = {r["id"]: r for r in context.ingestion.canonical_skeleton()["source_segments"]}
    passages = {}
    for i, item in enumerate(context.passage_inputs, 1):
        path = f"P{i}"
        try:
            if set(item) != {"use", "passage_ref"} or item["use"] not in {"EVIDENCE_ELIGIBLE", "CONTEXT_ONLY"}:
                raise ValueError()
            ref = item["passage_ref"]
            context.ingestion.verify_passage_ref(ref)
            seg = segments[ref["segment_id"]]
            if (seg != source_segments.get(seg["id"])
                    or ref["position"]["stream_id"] != stream
                    or ref["position"]["key"] > as_of["key"]):
                raise ValueError()
            passages[path] = (deepcopy(item), context.ingestion.resolve_passage_text(ref))
        except Exception as exc:
            raise DraftCompilationError("INVALID_PASSAGE_INPUT", path) from exc
    existing = {}
    for coll, prefix in EXISTING_PREFIXES.items():
        for i, record in enumerate(sorted(base[coll], key=lambda r: r["id"]), 1):
            existing[f"{prefix}_EXISTING_{i}"] = (coll, record["id"])
    return passages, existing


def _occurrences(text: str, quote: str) -> list[int]:
    """All code-point matches, including overlapping matches; never normalize."""
    starts, at = [], 0
    while True:
        at = text.find(quote, at)
        if at < 0:
            return starts
        starts.append(at)
        at += 1


def _quote_ref(record, passages, context):
    handle = record["passage_handle"]
    if handle not in passages:
        raise DraftCompilationError("UNKNOWN_PASSAGE_HANDLE", handle)
    item, text = passages[handle]
    if item["use"] != "EVIDENCE_ELIGIBLE":
        raise DraftCompilationError("CONTEXT_ONLY_EVIDENCE", handle)
    starts = _occurrences(text, record["quote"])
    if not starts:
        raise DraftCompilationError("QUOTE_NOT_FOUND", handle)
    occurrence = record.get("occurrence")
    if occurrence is None:
        if len(starts) != 1:
            raise DraftCompilationError("AMBIGUOUS_QUOTE", handle)
        occurrence = 1
    if occurrence > len(starts):
        raise DraftCompilationError("OCCURRENCE_OUT_OF_RANGE", handle)
    passage = item["passage_ref"]
    seg = next(r for r in context.base_document["source_segments"] if r["id"] == passage["segment_id"])
    start = passage["span"]["char_start"] - seg["locator"]["char_start"] + starts[occurrence - 1]
    return context.ingestion.passage_ref(seg["id"], start, start + len(record["quote"]))


def prepare_story_extraction_draft_v1(context: DraftCompilerContext) -> dict[str, Any]:
    """Model-facing input: passage/record handles with no deterministic metadata."""
    passages, existing = _context_maps(context)
    reverse = {rid: handle for handle, (_, rid) in existing.items()}
    existing_context = {}
    rename = {"ref": "handle", "anchor_id": "anchor_handle", "event_id": "event_handle",
              "proposition_id": "proposition_handle", "evidence_ref_id": "evidence_handle",
              "evidence_ref_ids": "evidence_handles", "premise_assertion_ids": "premise_handles",
              "alternative_proposition_ids": "alternative_proposition_handles"}

    def semantic_record(value, key=""):
        if isinstance(value, list):
            return [semantic_record(v, key) for v in value]
        if not isinstance(value, dict):
            return reverse[value] if key in rename and isinstance(value, str) else value
        return {rename.get(k, k): semantic_record(v, k) for k, v in value.items()
                if k not in {"id", "review", "extraction_provenance_id", "span", "position", "segment_id"}}

    for handle, (coll, rid) in existing.items():
        r = next(r for r in context.base_document[coll] if r["id"] == rid)
        existing_context[handle] = semantic_record(r)
    return {"draft_version": DRAFT_VERSION,
            "passages": [{"handle": h, "use": item["use"], "text": text}
                         for h, (item, text) in passages.items()],
            "existing_context": existing_context}


def compile_story_extraction_draft_v1(draft: Any, context: DraftCompilerContext) -> dict[str, Any]:
    """Return a source-exact canonical batch, or fail closed.

    Labels, predicates, arguments, roles, epistemic status, polarity, support
    membership, rule and temporal bounds come only from the draft. No implicit
    RefersTo, Occurred, SameAs, causality, entity merge or truth upgrade is added.
    """
    validate_draft_v1(draft)
    passages, existing = _context_maps(context)
    namespace = hashlib.sha256(json.dumps({
        "base": document_sha256(context.base_document), "process": context.process_id,
        "version": context.process_version, "run": context.run_id,
    }, sort_keys=True).encode()).hexdigest()[:24]
    records = {name: [] for name in CANDIDATE_COLLECTIONS}
    handles = dict(existing)
    base_ids = {context.base_document["story"]["id"]}
    for coll in ("source_documents", "source_segments", *CANDIDATE_COLLECTIONS):
        base_ids.update(r["id"] for r in context.base_document[coll])
    generated = set()

    def new_id(label):
        rid = f"draftv1-{namespace}-{label}"
        if rid in base_ids or rid in generated:
            raise DraftCompilationError("ID_COLLISION")
        generated.add(rid)
        return rid

    for field, coll in COLLECTIONS.items():
        for r in sorted(draft[field], key=lambda r: r["handle"]):
            h = r["handle"]
            if h in handles:
                raise DraftCompilationError("DUPLICATE_HANDLE", h)
            handles[h] = (coll, new_id(h))

    def resolve(handle, coll):
        if handle not in handles:
            raise DraftCompilationError("UNKNOWN_HANDLE", handle)
        target, rid = handles[handle]
        if target != coll:
            raise DraftCompilationError("HANDLE_TYPE_MISMATCH", handle)
        return rid

    evidence_by_handle = {}
    for r in sorted(draft["evidence"], key=lambda r: r["handle"]):
        ref = _quote_ref(r, passages, context)
        ev = materialize_evidence_ref(ref, r["role"], resolve(r["handle"], "evidence_refs"))
        records["evidence_refs"].append(ev)
        evidence_by_handle[r["handle"]] = ev
    for r in sorted(draft["mentions"], key=lambda r: r["handle"]):
        ref = _quote_ref(r, passages, context)
        if "evidence_handle" in r:
            ev = evidence_by_handle.get(r["evidence_handle"])
            if ev is None:
                raise DraftCompilationError("UNKNOWN_EVIDENCE_HANDLE", r["handle"])
            expected = materialize_evidence_ref(ref, r["role"], ev["id"])
            if ev != expected:
                raise DraftCompilationError("MENTION_EVIDENCE_MISMATCH", r["handle"])
        else:
            ev = materialize_evidence_ref(ref, r["role"], new_id(f"mention-evidence-{r['handle']}"))
            records["evidence_refs"].append(ev)
        records["mentions"].append({"id": resolve(r["handle"], "mentions"),
                                   "evidence_ref_id": ev["id"],
                                   "surface_form": r.get("surface_form", r["quote"])})

    for field in ("entities", "events", "anchors", "propositions"):
        coll = COLLECTIONS[field]
        for r in sorted(draft[field], key=lambda r: r["handle"]):
            out = deepcopy(r)
            out["id"] = resolve(out.pop("handle"), coll)
            for key, target in (("anchor_handle", "temporal_anchors"), ("event_handle", "events")):
                if key in out:
                    out[key.replace("_handle", "_id")] = resolve(out.pop(key), target)
            for arg in out.get("args", {}).values():
                if "handle" in arg:
                    arg["ref"] = resolve(arg.pop("handle"), ARG_COLLECTIONS[arg["kind"]])
            records[coll].append(out)

    provenance_id = new_id("provenance")
    process = {"method": "AUTOMATED_EXTRACTION", "process_id": context.process_id,
               "process_version": context.process_version, "run_id": context.run_id}
    records["extraction_provenance"].append({"id": provenance_id, **process})

    def support(value, label):
        for s in value["evidence_sets"]:
            for h in s["evidence_handles"]:
                if h not in evidence_by_handle:
                    raise DraftCompilationError("PRIOR_CONTEXT_NOT_EVIDENCE", h)
        return {"evidence_sets": [
            {"id": new_id(f"{label}-es-{i}"), "label": s["label"],
             "evidence_ref_ids": [resolve(h, "evidence_refs") for h in s["evidence_handles"]]}
            for i, s in enumerate(value["evidence_sets"], 1)],
            "derivations": [
                {"id": new_id(f"{label}-der-{i}"), "rule_id": d["rule_id"],
                 "premise_assertion_ids": [resolve(h, "assertions") for h in d["premise_handles"]]}
                for i, d in enumerate(value["derivations"], 1)]}

    for r in sorted(draft["assertions"], key=lambda r: r["handle"]):
        out = deepcopy(r)
        h = out.pop("handle")
        out["id"] = resolve(h, "assertions")
        out["proposition_id"] = resolve(out.pop("proposition_handle"), "propositions")
        out["support"] = support(out["support"], h)
        for side, bound in out.get("validity", {}).items():
            if "anchor_handle" in bound:
                bound["anchor_id"] = resolve(bound.pop("anchor_handle"), "temporal_anchors")
            if "support" in bound:
                bound["support"] = support(bound["support"], f"{h}-{side}")
        if "textual_ambiguity" in out:
            alt = out["textual_ambiguity"]
            alt["alternative_proposition_ids"] = [resolve(h, "propositions")
                for h in alt.pop("alternative_proposition_handles")]
        out["extraction_provenance_id"] = provenance_id
        out["review"] = {"state": "UNREVIEWED"}
        records["assertions"].append(out)

    for coll in records:
        records[coll].sort(key=lambda r: r["id"])
    batch = {"batch_version": BATCH_VERSION, "contract_version": CONTRACT_VERSION,
             "process": process,
             "scope": {"story_id": context.base_document["story"]["id"],
                       "ingestion": {"contract_version": "LIGHT_NOVEL_INGESTION/v0",
                                     "corpus_fingerprint_sha256": context.ingestion.fingerprint},
                       "passage_inputs": deepcopy(context.passage_inputs),
                       "as_of_position": deepcopy(context.as_of_position),
                       "prior_canonical_context": {"kind": "BASE_DOCUMENT_RECORDS" if any(
                           context.base_document[c] for c in CANDIDATE_COLLECTIONS) else "NONE"},
                       "profile_id": context.profile_id},
             "base_canonical_identity": {"schema_version": "canonical_story/v0",
                                         "base_document_sha256": document_sha256(context.base_document)},
             "candidate_records": records}
    try:
        report = validate_batch_guarded(batch, context.base_document, context.ingestion)
    except Exception as exc:
        raise DraftCompilationError("CANONICAL_VALIDATOR_EXCEPTION") from exc
    if not report["pass"]:
        sections = ",".join(k for k, v in report["checks"].items() if not v["pass"])
        raise DraftCompilationError("CANONICAL_CONFORMANCE_FAILURE", sections)
    return batch
