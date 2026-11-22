"""Development-only prompt-variant Draft V1.1 runner on DEV1, DEV2 and FV2 tuning data.

Preflight is offline. Run uses the durable Gemini path and automatically scores;
score only reads saved artifacts. A changed request requires a fresh output root.
The injectable case_loader and transport are intended for synthetic offline tests.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, replace
import json
from pathlib import Path
import re
import tempfile
import time
from typing import Any, Callable, Mapping, Sequence
from zipfile import ZipFile

from tools.story_extraction import m4_04b3f_fv1_protocol_v1 as protocol
from tools.story_extraction import score_m4_04b3h_fv1_v1 as scoring
from tools.story_extraction import m4_04b2_dev_protocol_v1 as dev1_protocol
from tools.story_extraction import m4_04b3n_fv2_protocol_v1 as fv2_protocol
from tools.story_extraction import draft_compiler_v1 as compiler
from tools.story_extraction.draft_quote_resolution_v1 import OUTCOMES, resolve_quotes
from tools.story_extraction.draft_mention_anchoring_v1 import anchor_mentions as _anchor_mentions
from tools.story_extraction.draft_mention_evidence_v1 import (
    PREDICATES as MENTION_EVIDENCE_PREDICATES, narrow_mention_evidence,
)
from tools.story_extraction.draft_sentence_evidence_v1 import widen_to_sentence
from tools.story_extraction.draft_transfer_bounds_v1 import bound_by_transfer
from tools.story_extraction.draft_date_anchor_v1 import anchor_dates_to_events
from tools.story_extraction.draft_vocabulary_guard_v1 import guard_vocabulary
from tools.story_extraction.check_annotation_conventions_v1 import RULE_IDS, check_batch
from tools.story_extraction.check_annotation_conventions_v2 import align_mention_roles
from tools.story_extraction.check_annotation_conventions_v3 import align_date_anchors
from tools.story_extraction.draft_compiler_v1 import DraftCompilerContext
from tools.story_extraction.draft_compiler_v1_1 import prepare_story_extraction_draft_v1_1
from tools.story_extraction.durable_research_executor_v1 import (
    CheckpointIntegrityError, DurableJobSpec, DurableResearchExecutor, PersistentRollingOperationPacer,
)
from tools.story_extraction.evaluate_extraction_v0 import FAILURE_CODES
from tools.story_extraction.run_m4_04b2_dev_predictions_v1 import load_dev_inputs
from tools.story_extraction.run_m4_04b3c_dev2_predictions_v1 import (
    Dev2PredictionError, _member_path, load_case_inputs,
)
from tools.story_extraction.run_m4_04b3g_fv1_predictions_v1 import (
    Fv1PredictionError, Transport, _run_job, _telemetry, _write_json, _write_text, smoke_spec, validate_raw,
)

INPUT_SHA256 = "e63937252e69820ff6f4b097537f860524ea9937e1e0bbd7187f2ae52cd812d5"
GOLD_SHA256 = "77b9655b92b09c5b2c0d0ce749432ae12da342bbf07d62a01b16b37b1fce9939"
GOLD_MANIFEST = "M4_04B3_DEV2_GOLD_MANIFEST_V1.json"
CASE_IDS = tuple(f"DEV2_{i:02d}" for i in range(1, 11))
TASK_ID = "M4_P4_DEV_V1"
PROMPT_ROOT = protocol.PROMPT_ROOT
DEV1_SHA256 = dev1_protocol.DEV_PACKAGE_SHA256
DEV1_PREFIX = "M4_02_DEV_CALIBRATION/"


class DevelopmentError(RuntimeError):
    """Invalid development inputs or artifacts; diagnostics contain no source text."""


@dataclass(frozen=True)
class CaseInput:
    case_id: str
    prepared_input: Mapping[str, Any]
    compiler_context: DraftCompilerContext
    sources: tuple[bytes, ...]
    dataset: str = "DEV2"


def prompt_material(variant: str) -> dict[str, str]:
    """Reuse the locked composition, substituting only the selected preamble."""
    if not re.fullmatch(r"P[0-9A-Z]+", variant):
        raise DevelopmentError("Unknown prompt variant")
    path = PROMPT_ROOT / f"story_extraction_draft_{variant.lower()}_system_v1_1.txt"
    if not path.is_file():
        raise DevelopmentError("Missing prompt variant")
    material = protocol.prompt_material()
    if variant != "P3":
        old = protocol._normalized_text(protocol.SYSTEM_PREAMBLE_PATH)
        new = protocol._normalized_text(path)
        material["primary_system"] = new + material["primary_system"][len(old):]
        material["repair_system"] = material["primary_system"] + "\n\n" + protocol.REPAIR_SYSTEM_SUFFIX
    return material


def prompt_hashes(variant: str) -> dict[str, Any]:
    material = prompt_material(variant)
    paths = (PROMPT_ROOT / f"story_extraction_draft_{variant.lower()}_system_v1_1.txt",
             protocol.USER_TEMPLATE_PATH, protocol.REPAIR_USER_TEMPLATE_PATH,
             protocol.DRAFT_SCHEMA_PATH, protocol.V1_SCHEMA_PATH, protocol.PREDICATE_REGISTRY_PATH)
    return {"composed_sha256": {key: protocol.sha256_text(value)
                                for key, value in material.items()},
            "source_sha256": {p.name: protocol.file_sha256(p) for p in paths}}


def verify_packages(dev2_input: Path, dev2_gold: Path) -> None:
    for path, expected in ((dev2_input, INPUT_SHA256), (dev2_gold, GOLD_SHA256)):
        if protocol.file_sha256(path) != expected:
            raise DevelopmentError("DEV2 archive hash mismatch")


def selected_cases(cases: Sequence[str] | None, dataset: str = "DEV2") -> tuple[str, ...]:
    datasets = {"DEV1": dev1_protocol.CASE_IDS, "DEV2": CASE_IDS, "FV2": fv2_protocol.CASE_IDS}
    if dataset not in datasets:
        raise DevelopmentError("Unknown development dataset")
    allowed = datasets[dataset]
    selected = tuple(allowed if cases is None else cases)
    if not selected or len(set(selected)) != len(selected) or not set(selected) <= set(allowed):
        raise DevelopmentError(f"Unknown, empty or duplicate {dataset} selection")
    return selected


def _job_prefix(variant: str, dataset: str) -> str:
    variant = variant.replace("+", "_")  # Durable job ids exclude '+'.
    return f"{TASK_ID}_{variant}" if dataset == "DEV2" else f"{TASK_ID}_{dataset}_{variant}"


def _run_variant(variant: str, quote_resolution: bool, rich_repair_blockers: bool,
                 existing_names: bool = False, anchor_mentions: bool = False,
                 mention_evidence: bool = False,
                 mention_evidence_predicates: Sequence[str] = MENTION_EVIDENCE_PREDICATES, *,
                 sentence_evidence: bool = False, transfer_bounds: bool = False, date_anchor: bool = False,
                 vocabulary_guard: bool = False) -> str:
    label = (variant + ("+QR" if quote_resolution else "") + ("+RB" if rich_repair_blockers else "")
             + ("+EN" if existing_names else "") + ("+AM" if anchor_mentions else ""))
    if mention_evidence:
        suffix = {frozenset(MENTION_EVIDENCE_PREDICATES): "+ME",
                  frozenset(("RefersTo",)): "+ME_R", frozenset(("NamedAs",)): "+ME_N"}
        selected = frozenset(mention_evidence_predicates)
        if selected not in suffix:
            raise DevelopmentError("Mention evidence predicates must select RefersTo, NamedAs, or both")
        label += suffix[selected]
    return (label + ("+SE" if sentence_evidence else "") + ("+TB" if transfer_bounds else "")
            + ("+DA" if date_anchor else "") + ("+VG" if vocabulary_guard else ""))


def _with_existing_names(prepared: Mapping[str, Any], context: DraftCompilerContext) -> dict[str, Any]:
    """Enrich model-facing entity handles using only affirmed prior-context facts."""
    # V1.1 compilation takes the draft and trusted context separately, then delegates
    # to V1, which rebuilds _context_maps(context). It never consumes this prepared
    # input, so these model-facing additions do not change compiler context/mapping.
    _, existing = compiler._context_maps(context)
    base = context.base_document
    propositions = {p["id"]: p for p in base["propositions"]}
    mentions = {m["id"]: m["surface_form"] for m in base["mentions"]}
    names: dict[str, set[tuple[str, str]]] = {}
    forms: dict[str, set[str]] = {}
    for assertion in base["assertions"]:
        if assertion["polarity"] != "AFFIRMED":
            continue
        proposition = propositions[assertion["proposition_id"]]
        predicate = proposition.get("predicate")
        if predicate not in ("NamedAs", "RefersTo"):
            continue
        args = proposition["args"]
        if predicate == "NamedAs":
            names.setdefault(args["entity"]["ref"], set()).add(
                (args["name"]["value"], args["name_kind"]["value"]))
        else:
            forms.setdefault(args["entity"]["ref"], set()).add(mentions[args["mention"]["ref"]])
    records = dict(prepared["existing_context"])
    for handle, (collection, rid) in existing.items():
        if collection == "entities" and rid in names:
            records[handle] = {**records[handle],
                "names": [{"name": name, "name_kind": kind} for name, kind in sorted(names[rid])],
                "mention_forms": sorted(forms.get(rid, set()))}
    return {**prepared, "existing_context": records}


def load_dev1_cases(archive: Path, input_root: Path, selected: Sequence[str],
                    ingestion_manifest: Path, source_root: Path, variant: str,
                    case_loader: Callable = load_dev_inputs) -> tuple[list[CaseInput], dict[str, dict]]:
    """Verify used members, retaining gold metadata outside the safe model inputs.

    B2R reads completeness and acceptable_assertions from development_cases.jsonl.
    Its imported Snapshot V2 evaluator derives required assertions and mixed-role
    narrow spans, and interprets any declared narrow spans and literal variants.
    """
    with ZipFile(archive) as bundle:
        manifest = json.loads(bundle.read(DEV1_PREFIX + "manifest.json"))

        def read(member):
            name = DEV1_PREFIX + member
            if bundle.namelist().count(name) != 1:
                raise DevelopmentError("DEV1 member missing or duplicated")
            data = bundle.read(name)
            if dev1_protocol.sha256_bytes(data) != manifest["files"].get(member):
                raise DevelopmentError("DEV1 member hash mismatch")
            return data

        for name in dev1_protocol.INPUT_MEMBERS:
            member = name.removeprefix(DEV1_PREFIX)
            (input_root / member).write_bytes(read(member))
        rows = [json.loads(line) for line in (input_root / "development_cases.jsonl")
                .read_text(encoding="utf-8").splitlines() if line.strip()]
        raw_cases = {row["case_id"]: row for row in rows}
        if len(raw_cases) != len(rows) or not set(selected) <= raw_cases.keys():
            raise DevelopmentError("DEV1 gold case identity mismatch")
        gold = {}
        for cid in selected:
            row = raw_cases[cid]
            if row["gold_completeness"] not in ("COMPLETE_FOR_PROFILE", "UNCERTAIN"):
                raise DevelopmentError("Unknown DEV1 gold completeness")
            gold[cid] = {**row, "gold_batch": json.loads(read(f"gold_batches/{cid}.json")),
                         "acceptable_optional_assertion_ids": row.get("acceptable_assertions", [])}

    base, cases, refs, ingestion = case_loader(
        input_root, ingestion_manifest=ingestion_manifest, source_root=source_root)
    if not set(selected) <= cases.keys() or not set(selected) <= refs.keys():
        raise DevelopmentError("DEV1 loader case identity mismatch")
    sources = tuple(doc.source_bytes for doc in ingestion.documents
                    if isinstance(doc.source_bytes, bytes))
    result = []
    for cid in selected:
        context = DraftCompilerContext(
            base, refs[cid], cases[cid]["as_of_position"], gold[cid]["gold_batch"]["scope"]["profile_id"],
            _job_prefix(variant, "DEV1"), "v1.1", f"DEV1_{variant}_{cid}_PRIMARY", ingestion)
        result.append(CaseInput(cid, prepare_story_extraction_draft_v1_1(context), context, sources, "DEV1"))
    return result, gold


def _prepare_case(cid: str, context: DraftCompilerContext, variant: str,
                  sources: tuple[bytes, ...], dataset: str) -> CaseInput:
    run_prefix = variant if dataset == "DEV2" else f"{dataset}_{variant}"
    context = replace(context, process_id=f"{TASK_ID}_{run_prefix}",
                      process_version="v1.1", run_id=f"{run_prefix}_{cid}_PRIMARY")
    return CaseInput(cid, prepare_story_extraction_draft_v1_1(context), context, sources, dataset)


def load_cases(archive: Path, input_root: Path, selected: Sequence[str],
               case_loader: Callable = load_case_inputs, variant: str = "P3") -> list[CaseInput]:
    """Adapt B3C's context as B3D does, then prepare the actual V1.1 model input."""
    with ZipFile(archive) as bundle:
        for info in bundle.infolist():
            target = _member_path(input_root, info.filename)
            if not info.is_dir():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(bundle.read(info))
    loaded = case_loader(archive, input_root)
    by_id = {case.case_id: case for case in loaded}
    if len(by_id) != len(loaded) or not set(selected) <= by_id.keys():
        raise DevelopmentError("DEV2 loader case identity mismatch")
    result = []
    for cid in selected:
        sources = ((input_root / "m3_sources" / cid / "unit.txt").read_bytes(),)
        result.append(_prepare_case(cid, by_id[cid].compiler_context, variant, sources, "DEV2"))
    return result


def load_fv2_cases(directory: Path, selected: Sequence[str], variant: str) -> list[CaseInput]:
    # The FV2 protocol imports this module. Load its runner after both modules are initialized.
    from tools.story_extraction.run_m4_04b3o_fv2_predictions_v1 import load_cases as load_sealed_cases

    contexts = {case.case_id: case.compiler_context for case in load_sealed_cases(directory)}
    return [_prepare_case(cid, contexts[cid], variant,
                          tuple(doc.source_bytes for doc in contexts[cid].ingestion.documents), "FV2")
            for cid in selected]


def build_primary_spec(variant: str, case: CaseInput, model: str = protocol.MODEL,
                       credential_slot: str = protocol.CREDENTIAL_SLOT, *,
                       quote_resolution: bool = False, rich_repair_blockers: bool = False,
                       existing_names: bool = False, anchor_mentions: bool = False,
                       mention_evidence: bool = False,
                       mention_evidence_predicates: Sequence[str] = MENTION_EVIDENCE_PREDICATES,
                       sentence_evidence: bool = False, transfer_bounds: bool = False, date_anchor: bool = False,
                       vocabulary_guard: bool = False) -> DurableJobSpec:
    material = prompt_material(variant)
    user = protocol._render(material["primary_user_template"], {
        "CASE_ID": case.case_id,
        "PREPARED_INPUT_JSON": protocol.canonical_json_bytes(dict(case.prepared_input)).decode().rstrip(),
    })
    label = _run_variant(variant, quote_resolution, rich_repair_blockers, existing_names, anchor_mentions,
                         mention_evidence, mention_evidence_predicates,
                         sentence_evidence=sentence_evidence, transfer_bounds=transfer_bounds, date_anchor=date_anchor,
                         vocabulary_guard=vocabulary_guard)
    return replace(protocol._spec(f"{_job_prefix(label, case.dataset)}_{case.case_id}_PRIMARY",
                                  material["primary_system"], user),
                   model=model, credential_slot=credential_slot, research_task_id=TASK_ID)


def build_repair_spec(variant: str, case: CaseInput, primary_raw: str, validation: Mapping,
                      model: str = protocol.MODEL,
                      credential_slot: str = protocol.CREDENTIAL_SLOT, *,
                      quote_resolution: bool = False, rich_repair_blockers: bool = False,
                      existing_names: bool = False, anchor_mentions: bool = False,
                      mention_evidence: bool = False,
                      mention_evidence_predicates: Sequence[str] = MENTION_EVIDENCE_PREDICATES,
                      sentence_evidence: bool = False, transfer_bounds: bool = False, date_anchor: bool = False,
                      vocabulary_guard: bool = False) -> DurableJobSpec:
    payload = protocol.sanitized_failure(validation["category"], validation["blockers"])
    material = prompt_material(variant)
    user = protocol._render(material["repair_user_template"], {
        "CASE_ID": case.case_id,
        "PREPARED_INPUT_JSON": protocol.canonical_json_bytes(dict(case.prepared_input)).decode().rstrip(),
        "PRIMARY_RESPONSE": primary_raw,
        "FAILURE_JSON": protocol.canonical_json_bytes(payload).decode().rstrip(),
    })
    primary = build_primary_spec(variant, case, model, credential_slot,
                                 quote_resolution=quote_resolution, rich_repair_blockers=rich_repair_blockers,
                                 existing_names=existing_names, anchor_mentions=anchor_mentions,
                                 mention_evidence=mention_evidence,
                                 mention_evidence_predicates=mention_evidence_predicates,
                                 sentence_evidence=sentence_evidence, transfer_bounds=transfer_bounds, date_anchor=date_anchor,
                                 vocabulary_guard=vocabulary_guard)
    label = _run_variant(variant, quote_resolution, rich_repair_blockers, existing_names, anchor_mentions,
                         mention_evidence, mention_evidence_predicates,
                         sentence_evidence=sentence_evidence, transfer_bounds=transfer_bounds, date_anchor=date_anchor,
                         vocabulary_guard=vocabulary_guard)
    return replace(primary, job_id=f"{_job_prefix(label, case.dataset)}_{case.case_id}_REPAIR_1",
                   system_prompt=material["repair_system"], user_prompt=user)


def _canonical_blockers(draft: Any, captures: list) -> list[dict[str, str]]:
    # Lazy import: the diagnosis module itself imports this runner.
    from tools.story_extraction import diagnose_m4_p4_dev_v1 as diagnosis

    known = set(diagnosis.KNOWN_TEMPLATES.values()) | {code for _, code in diagnosis._VALUE_TEMPLATES}
    handles = {record["handle"] for field in compiler.COLLECTIONS
               for record in draft.get(field, [])
               if re.fullmatch(r"[A-Z][A-Z_]*\d+", record["handle"])}
    result = []
    for batch, report in captures:
        ids = {record["id"]: handle for records in batch["candidate_records"].values()
               for record in records for handle in handles if record["id"].endswith("-" + handle)}
        for section, check in report["checks"].items():
            for issue in check["issues"]:
                code = diagnosis.issue_code(section, issue)
                # issue_code's unknown-template fallback can contain unquoted literals.
                # Emit only its recognized codes; never pass that fallback to a model.
                if (code.rsplit(":", 1)[-1] not in known or
                        not re.fullmatch(r"[a-z_]+:[A-Z_]+", code)):
                    code = "canonical:UNCLASSIFIED_ISSUE"
                message = diagnosis._QUOTES.sub("", issue)
                candidates = []
                for value, handle in {**{h: h for h in handles}, **ids}.items():
                    match = re.search(r"(?<![\w.:-])" + re.escape(value) + r"(?![\w.:-])", message)
                    if match:
                        candidates.append((match.start(), handle))
                result.append({"phase": "CANONICAL", "code": code,
                               "path": min(candidates)[1] if candidates else "canonical"})
    return result


def validate_attempt(raw: str, case: CaseInput, *, quote_resolution: bool = False,
                     rich_repair_blockers: bool = False,
                     anchor_mentions: bool = False, mention_evidence: bool = False,
                     mention_evidence_predicates: Sequence[str] = MENTION_EVIDENCE_PREDICATES,
                     sentence_evidence: bool = False, transfer_bounds: bool = False, date_anchor: bool = False,
                     vocabulary_guard: bool = False,
                     ) -> tuple[Any, Any, Any, dict]:
    """Validate one response with optional draft repairs and safe diagnostics.

    The temporary canonical-validator wrapper is single-threaded, like diagnosis.
    Both the untouched draft and the draft actually validated are returned.
    """
    original_draft, report, anchoring_report, evidence_report = None, None, None, None
    sentence_report, bounds_report, date_report, vocabulary_report = None, None, None, None
    host_repair = any((quote_resolution, anchor_mentions, mention_evidence, sentence_evidence,
                       transfer_bounds, date_anchor, vocabulary_guard))
    if host_repair:
        try:
            original_draft = json.loads(raw)
        except json.JSONDecodeError:
            pass  # validate_raw retains the standard parse failure.
        else:
            resolved = original_draft
            if quote_resolution:
                resolved, report = resolve_quotes(resolved, case.prepared_input)
            if anchor_mentions:
                resolved, anchoring_report = _anchor_mentions(resolved, case.prepared_input)
            if mention_evidence:
                resolved, evidence_report = narrow_mention_evidence(
                    resolved, case.prepared_input, predicates=mention_evidence_predicates)
            if sentence_evidence:
                resolved, sentence_report = widen_to_sentence(resolved, case.prepared_input)
            if transfer_bounds:
                resolved, bounds_report = bound_by_transfer(resolved, case.prepared_input)
            if date_anchor:
                resolved, date_report = anchor_dates_to_events(resolved, case.prepared_input)
            if vocabulary_guard:
                resolved, vocabulary_report = guard_vocabulary(resolved, case.prepared_input)
            raw = json.dumps(resolved, ensure_ascii=False)
    captures = []
    original_validator = compiler.validate_batch_guarded

    def capture(batch, *args, **kwargs):
        validation_report = original_validator(batch, *args, **kwargs)
        captures.append((batch, validation_report))
        return validation_report

    if rich_repair_blockers:
        compiler.validate_batch_guarded = capture
    try:
        draft, batch, validation = validate_raw(raw, case.compiler_context)
    finally:
        if rich_repair_blockers:
            compiler.validate_batch_guarded = original_validator
    if rich_repair_blockers and any(b["phase"] == "CANONICAL_COMPILER" and
            b["code"] == "CANONICAL_CONFORMANCE_FAILURE" for b in validation["blockers"]):
        validation["blockers"].extend(_canonical_blockers(draft, captures))
    if report is not None:
        validation["quote_resolution"] = report
    if anchoring_report is not None:
        validation["mention_anchoring"] = anchoring_report
    if evidence_report is not None:
        validation["mention_evidence"] = evidence_report
    if sentence_report is not None:
        validation["sentence_evidence"] = sentence_report
    if bounds_report is not None:
        validation["transfer_bounds"] = bounds_report
    if date_report is not None:
        validation["date_anchor"] = date_report
    if vocabulary_report is not None:
        validation["vocabulary_guard"] = vocabulary_report
    return original_draft if host_repair else draft, draft, batch, validation


def run_cases(cases: Sequence[CaseInput], specs: Sequence[DurableJobSpec], variant: str,
              executor: DurableResearchExecutor, transport: Transport, root: Path,
              guard: Callable[[], None], wait: Callable[[float], None], *,
              quote_resolution: bool = False, rich_repair_blockers: bool = False,
              existing_names: bool = False, anchor_mentions: bool = False, mention_evidence: bool = False,
              mention_evidence_predicates: Sequence[str] = MENTION_EVIDENCE_PREDICATES,
              sentence_evidence: bool = False, transfer_bounds: bool = False, date_anchor: bool = False,
              vocabulary_guard: bool = False) -> None:
    for case, primary in zip(cases, specs):
        directory = root / "artifacts" / case.case_id
        attempts = []
        batch = None
        spec = primary
        for phase in ("primary", "repair_1"):
            guard()
            record = _run_job(executor, spec, transport, wait)
            raw = (record.get("first_success") or {}).get("raw_response")
            attempt = {"phase": phase, "job_id": spec.job_id,
                       "request_fingerprint": spec.request_fingerprint, "transport": _telemetry(record)}
            attempts.append(attempt)
            if not isinstance(raw, str):
                validation = {"pass": False, "category": "TRANSPORT_FAILURE", "blockers": []}
                attempt["validation"] = validation
                break
            _write_text(directory / f"{phase}_raw.txt", raw)
            draft, resolved, batch, validation = validate_attempt(
                raw, case, quote_resolution=quote_resolution, rich_repair_blockers=rich_repair_blockers,
                anchor_mentions=anchor_mentions, mention_evidence=mention_evidence,
                mention_evidence_predicates=mention_evidence_predicates,
                sentence_evidence=sentence_evidence, transfer_bounds=transfer_bounds, date_anchor=date_anchor,
                vocabulary_guard=vocabulary_guard)
            if draft is not None:
                _write_json(directory / f"{phase}_draft.json", draft)
                if any((quote_resolution, anchor_mentions, mention_evidence, sentence_evidence,
                        transfer_bounds, date_anchor, vocabulary_guard)):
                    _write_json(directory / f"{phase}_resolved_draft.json", resolved)
            attempt["validation"] = validation
            if validation["pass"] or phase == "repair_1":
                break
            # Only deterministic JSON/schema/compiler failures can reach this repair.
            spec = build_repair_spec(variant, case, raw, validation, primary.model, primary.credential_slot,
                                     quote_resolution=quote_resolution, rich_repair_blockers=rich_repair_blockers,
                                     existing_names=existing_names, anchor_mentions=anchor_mentions,
                                     mention_evidence=mention_evidence,
                                     mention_evidence_predicates=mention_evidence_predicates,
                                     sentence_evidence=sentence_evidence, transfer_bounds=transfer_bounds, date_anchor=date_anchor,
                                     vocabulary_guard=vocabulary_guard)
        compiled_sha256 = None
        if batch is not None:
            compiled_sha256 = _write_json(directory / "compiled_batch.json", batch)
        _write_json(directory / "validation.json", {
            "terminal_status": "STRUCTURAL_VALID" if batch is not None else validation["category"],
            "compiled_sha256": compiled_sha256, "repair_used": len(attempts) == 2,
            "validation": validation, "attempts": attempts,
        })


def read_gold(archive: Path, selected: Sequence[str]) -> dict[str, dict]:
    with ZipFile(archive) as bundle:
        manifest = json.loads(bundle.read(GOLD_MANIFEST))
        rows = manifest["cases"]
        by_id = {row["case_id"]: row for row in rows}
        if len(by_id) != len(rows) or not set(selected) <= by_id.keys():
            raise DevelopmentError("DEV2 gold case identity mismatch")
        gold = {}
        for cid in selected:
            row = by_id[cid]
            batch = json.loads(bundle.read(row["canonical_annotation_member"]))
            required, optional = set(row["required_assertion_ids"]), set(row["acceptable_optional_assertion_ids"])
            ids = {a["id"] for a in batch["candidate_records"]["assertions"]}
            # The frozen evaluator treats every non-optional gold assertion as required.
            if required & optional or required | optional != ids:
                raise DevelopmentError("DEV2 gold required/optional partition mismatch")
            if row["gold_completeness"] not in scoring.evaluator.frozen.GOLD_COMPLETENESS:
                raise DevelopmentError("Unknown gold completeness")
            gold[cid] = {**row, "gold_batch": batch}
    return gold


def _align_gold(batch: dict, context: DraftCompilerContext, totals: dict) -> dict:
    sources = tuple(doc.source_bytes for doc in context.ingestion.documents)
    for name, align in (("mention_roles", align_mention_roles), ("date_anchors", align_date_anchors)):
        batch, report = align(batch, sources, context.base_document)
        counts = totals.setdefault(name, {})
        for key, count in report.items():
            if isinstance(count, dict):
                counts.setdefault(key, Counter()).update(count)
            else:
                counts[key] = counts.get(key, 0) + count
    return batch


def score_cases(cases: Sequence[CaseInput], specs: Sequence[DurableJobSpec],
                gold: Mapping[str, dict], root: Path, *, align_gold: bool = False) -> dict[str, Any]:
    rows = []
    conventions = Counter({rule: 0 for rule in RULE_IDS})
    checked = Counter()
    alignment_counts = {}
    for case, spec in zip(cases, specs):
        directory = root / "artifacts" / case.case_id
        saved = json.loads((directory / "validation.json").read_text(encoding="utf-8"))
        if saved["attempts"][0]["request_fingerprint"] != spec.request_fingerprint:
            raise CheckpointIntegrityError("Prediction request differs from selected development configuration")
        item = gold[case.case_id]
        if align_gold:
            item = {**item, "gold_batch": _align_gold(item["gold_batch"], case.compiler_context, alignment_counts)}
        report = None
        conventions_reason = None
        if saved["validation"]["pass"]:
            path = directory / "compiled_batch.json"
            if protocol.file_sha256(path) != saved["compiled_sha256"]:
                raise CheckpointIntegrityError("Compiled prediction hash mismatch")
            batch = json.loads(path.read_text(encoding="utf-8"))
            result = scoring.evaluator.evaluate_case(
                case.compiler_context.base_document, item["gold_batch"], batch,
                ingestion=case.compiler_context.ingestion,
                case_spec={"mode": "REAL_SOURCE", "gold_completeness": item["gold_completeness"],
                           "acceptable_assertion_ids": item["acceptable_optional_assertion_ids"],
                           **{key: item[key] for key in ("narrow_span_segments", "literal_variants")
                              if case.dataset == "DEV1" and key in item},
                           "adjudications": []})
            try:
                report = check_batch(batch, case.sources, case.compiler_context.base_document)
            except ValueError:
                if case.dataset != "DEV1":
                    raise
                conventions_reason = "SOURCE_OR_SPAN_UNVERIFIABLE"
            if report is not None:
                conventions.update(report["counts"])
                checked.update(report["checked"])
        else:
            validation = saved["validation"]
            codes = sorted({f"{b['phase']}:{b['code']}" for b in validation["blockers"]}
                           or {validation["category"]})
            result = scoring._structural_failure_result({"repair_validation": {"errors": codes}},
                                                        item["gold_completeness"])
        rows.append({"case_id": case.case_id, "evaluation": result, "conventions": report,
                     "conventions_reason": conventions_reason,
                     "terminal_status": saved["terminal_status"], "repair_used": saved["repair_used"]})
    summary = scoring._summary([row["evaluation"] for row in rows])
    summary["cases_by_completeness"] = {key: sum(gold[case.case_id]["gold_completeness"] == key
                                                for case in cases)
                                        for key in sorted(scoring.evaluator.frozen.GOLD_COMPLETENESS)}
    summary["failure_code_counts"] = dict(sorted(Counter(
        f["code"] for row in rows for f in row["evaluation"].get("failures", [])).items()))
    score = {"rows": rows, "summary": summary, "conventions_counts": dict(conventions),
             "conventions_checked": dict(checked), "conventions_cases_checked": sum(
                 row["conventions"] is not None for row in rows)}
    if align_gold:
        score.update(gold_alignment="V4_DEVELOPMENT_ONLY", gold_alignment_counts=alignment_counts)
    return score


def public_summary(score: Mapping[str, Any]) -> dict[str, Any]:
    """Allow only aggregate numeric metrics and known codes; never gold ids or text."""
    def numbers(value, shape):
        return {key: numbers(value.get(key, {}), allowed) if isinstance(allowed, dict)
                else value.get(key) for key, allowed in shape.items()
                if isinstance(allowed, dict) or value.get(key) is None
                or type(value.get(key)) in (int, float, bool)}

    shape = scoring._summary([])
    shape["failure_code_counts"] = dict.fromkeys(FAILURE_CODES, 0)
    shape["cases_by_completeness"] = dict.fromkeys(scoring.evaluator.frozen.GOLD_COMPLETENESS, 0)
    return {"aggregate": numbers(score["summary"], shape),
            "conventions_counts": numbers(score["conventions_counts"], dict.fromkeys(RULE_IDS, 0)),
            "conventions_cases_checked": numbers(score, {"conventions_cases_checked": 0}).get(
                "conventions_cases_checked")}


def _add_report_counts(total: dict, report: dict) -> None:
    """Accumulate nested outcome counts, including newly observed vocabularies."""
    for key, value in report.items():
        if isinstance(value, dict):
            _add_report_counts(total.setdefault(key, {}), value)
        else:
            total[key] = total.get(key, 0) + value


def revalidate_cases(cases: Sequence[CaseInput], source: Path, destination: Path, *,
                     quote_resolution: bool, rich_repair_blockers: bool, anchor_mentions: bool = False,
                     mention_evidence: bool = False,
                     mention_evidence_predicates: Sequence[str] = MENTION_EVIDENCE_PREDICATES,
                     sentence_evidence: bool = False, transfer_bounds: bool = False, date_anchor: bool = False,
                     vocabulary_guard: bool = False) -> dict:
    """Replay saved attempts without touching checkpoints or original validations.

    All saved attempts are inspected, even when the new primary passes. The new
    terminal result is the first valid attempt, or the last recorded failure.
    Missing drafts on transport failures retain their original failure status.
    Counts include every replayed attempt, even after an earlier attempt passes.
    """
    rows = []
    repair_reports = [key for key, enabled in (("mention_evidence", mention_evidence),
                      ("sentence_evidence", sentence_evidence), ("transfer_bounds", transfer_bounds)) if enabled]

    def statistics():
        counts = {"remaining_blocker_counts": Counter(), "quote_resolution_report": {
            kind: dict.fromkeys(OUTCOMES, 0) for kind in ("evidence", "mentions")}}
        if anchor_mentions:
            counts["mention_anchoring_report"] = _anchor_mentions({}, {})[1]
        if mention_evidence:
            counts["mention_evidence_report"] = narrow_mention_evidence(
                {}, {}, predicates=mention_evidence_predicates)[1]
        if sentence_evidence:
            counts["sentence_evidence_report"] = widen_to_sentence({}, {})[1]
        if transfer_bounds:
            counts["transfer_bounds_report"] = bound_by_transfer({}, {})[1]
        if date_anchor:
            counts["date_anchor_report"] = anchor_dates_to_events({}, {})[1]
        if vocabulary_guard:
            counts["vocabulary_guard_report"] = guard_vocabulary({})[1]
        return counts

    totals = statistics()
    by_phase = {phase: statistics() for phase in ("primary", "repair_1")}
    for case in cases:
        directory = source / "artifacts" / case.case_id
        saved = json.loads((directory / "validation.json").read_text(encoding="utf-8"))
        attempts = []
        terminal = None
        for attempt in saved["attempts"]:
            phase = attempt["phase"]
            if phase not in ("primary", "repair_1"):
                raise DevelopmentError("Unknown saved draft phase")
            path = directory / f"{phase}_draft.json"
            raw_path = directory / f"{phase}_raw.txt"
            if path.is_file() or raw_path.is_file():
                raw = (path if path.is_file() else raw_path).read_text(encoding="utf-8")
                _, _, batch, validation = validate_attempt(
                    raw, case, quote_resolution=quote_resolution, rich_repair_blockers=rich_repair_blockers,
                    anchor_mentions=anchor_mentions, mention_evidence=mention_evidence,
                    mention_evidence_predicates=mention_evidence_predicates,
                    sentence_evidence=sentence_evidence, transfer_bounds=transfer_bounds, date_anchor=date_anchor,
                    vocabulary_guard=vocabulary_guard)
                status = "STRUCTURAL_VALID" if batch is not None else validation["category"]
            elif attempt["validation"]["category"] == "TRANSPORT_FAILURE":
                validation = attempt["validation"]
                status = "TRANSPORT_FAILURE"
            else:
                raise DevelopmentError("Missing saved draft response")
            attempts.append({"phase": phase, "terminal_status": status, "validation": validation})
            for counts in (totals, by_phase[phase]):
                counts["remaining_blocker_counts"].update(
                    f"{b['phase']}:{b['code']}" for b in validation["blockers"])
                for kind, outcomes in validation.get("quote_resolution", {}).items():
                    for code, count in outcomes.items():
                        counts["quote_resolution_report"][kind][code] += count
                if anchor_mentions:
                    for kind, outcomes in validation.get("mention_anchoring", {}).items():
                        for code, count in outcomes.items():
                            counts["mention_anchoring_report"][kind][code] += count
                for name in ("date_anchor", "vocabulary_guard"):
                    if name in validation:
                        _add_report_counts(counts[f"{name}_report"], validation[name])
                for name in repair_reports:
                    if name not in validation:
                        continue
                    report = validation[name]
                    aggregate = counts[f"{name}_report"]
                    for predicate, outcomes in report["by_predicate"].items():
                        predicate_counts = aggregate["by_predicate"].setdefault(predicate, dict.fromkeys(outcomes, 0))
                        for code, count in outcomes.items():
                            predicate_counts[code] += count
                    for key, count in report.items():
                        if key != "by_predicate":
                            aggregate[key] += count
            if terminal != "STRUCTURAL_VALID":
                terminal = status
        if not attempts:
            raise DevelopmentError("Missing saved validation attempts")
        rows.append({"case_id": case.case_id, "original_terminal_status": saved["terminal_status"],
                     "new_terminal_status": terminal, "attempts": attempts})
    transitions = Counter(f"{r['original_terminal_status']}->{r['new_terminal_status']}" for r in rows)
    for counts in (totals, *by_phase.values()):
        counts["remaining_blocker_counts"] = dict(sorted(counts["remaining_blocker_counts"].items()))
    result = {"rows": rows, "totals": {"cases": len(rows),
        "original_structurally_valid": sum(r["original_terminal_status"] == "STRUCTURAL_VALID" for r in rows),
        "new_structurally_valid": sum(r["new_terminal_status"] == "STRUCTURAL_VALID" for r in rows),
        "fixed": sum(r["original_terminal_status"] != "STRUCTURAL_VALID" and
                     r["new_terminal_status"] == "STRUCTURAL_VALID" for r in rows),
        "transitions": dict(sorted(transitions.items())), **totals, "by_phase": by_phase},
        "quote_resolution": quote_resolution, "rich_repair_blockers": rich_repair_blockers}
    if anchor_mentions:
        result["anchor_mentions"] = True
    if mention_evidence:
        result["mention_evidence"] = True
        result["mention_evidence_predicates"] = list(totals["mention_evidence_report"]["by_predicate"])
    if sentence_evidence:
        result["sentence_evidence"] = True
    if transfer_bounds:
        result["transfer_bounds"] = True
    if date_anchor:
        result["date_anchor"] = True
    if vocabulary_guard:
        result["vocabulary_guard"] = True
    _write_json(destination / "revalidation.json", result)
    return result


def execute(*, variant: str, output_root: Path, dev2_input: Path | None = None,
            dev2_gold: Path | None = None, dataset: str = "DEV2", fv2_dir: Path | None = None,
            dev1_package: Path | None = None, dev1_ingestion_manifest: Path | None = None,
            dev1_source_root: Path | None = None, dev1_case_loader: Callable = load_dev_inputs,
            model: str = protocol.MODEL, credential_slot: str = protocol.CREDENTIAL_SLOT,
            cases: Sequence[str] | None = None, mode: str = "preflight",
            case_loader: Callable = load_case_inputs, transport: Transport | None = None,
            wait: Callable = time.sleep, clock: Callable = time.time,
            quote_resolution: bool = False, rich_repair_blockers: bool = False,
            existing_names: bool = False, anchor_mentions: bool = False,
            mention_evidence: bool = False,
            mention_evidence_predicates: Sequence[str] = MENTION_EVIDENCE_PREDICATES,
            sentence_evidence: bool = False, transfer_bounds: bool = False, date_anchor: bool = False,
            vocabulary_guard: bool = False,
            run_directory: Path | None = None, align_gold: bool = False) -> dict[str, Any]:
    if mode not in ("preflight", "run", "score", "revalidate"):
        raise DevelopmentError("Unknown development mode")
    if run_directory is not None and mode != "revalidate":
        raise DevelopmentError("Run directory is only used for revalidation")
    selected = selected_cases(cases, dataset)

    def verify(*, include_gold: bool = False):
        if dataset == "DEV1":
            if dev1_package is None or dev1_ingestion_manifest is None or dev1_source_root is None:
                raise DevelopmentError("DEV1 requires package, ingestion manifest and source root")
            if protocol.file_sha256(dev1_package) != DEV1_SHA256:
                raise DevelopmentError("DEV1 archive hash mismatch")
        elif dataset == "FV2":
            if fv2_dir is None:
                raise DevelopmentError("FV2 requires an FV2 directory")
            fv2_protocol.verify_fv2_packages(fv2_dir, include_gold=include_gold)
        else:
            if dev2_input is None or dev2_gold is None:
                raise DevelopmentError("DEV2 requires input and gold archives")
            verify_packages(dev2_input, dev2_gold)

    verify()
    hashes = prompt_hashes(variant)
    label = _run_variant(variant, quote_resolution, rich_repair_blockers, existing_names, anchor_mentions,
                         mention_evidence, mention_evidence_predicates,
                         sentence_evidence=sentence_evidence, transfer_bounds=transfer_bounds, date_anchor=date_anchor,
                         vocabulary_guard=vocabulary_guard)
    identity = label.replace("+", "_")
    base_root = Path(output_root) if dataset == "DEV2" else Path(output_root) / dataset
    root = base_root / label
    job_prefix = _job_prefix(label, dataset)
    with tempfile.TemporaryDirectory() as tmp:
        if dataset == "DEV1":
            loaded, gold = load_dev1_cases(dev1_package, Path(tmp), selected, dev1_ingestion_manifest,
                                          dev1_source_root, identity, dev1_case_loader)
            input_sha256 = gold_sha256 = DEV1_SHA256
        elif dataset == "FV2":
            loaded = load_fv2_cases(fv2_dir, selected, identity)
            input_sha256, gold_sha256 = fv2_protocol.FV2_INPUT_SHA256, fv2_protocol.FV2_GOLD_SHA256
        else:
            loaded = load_cases(dev2_input, Path(tmp), selected, case_loader, identity)
            input_sha256, gold_sha256 = INPUT_SHA256, GOLD_SHA256
        if existing_names:
            loaded = [replace(case, prepared_input=_with_existing_names(
                case.prepared_input, case.compiler_context)) for case in loaded]
        specs = [build_primary_spec(variant, case, model, credential_slot,
                 quote_resolution=quote_resolution, rich_repair_blockers=rich_repair_blockers,
                 existing_names=existing_names, anchor_mentions=anchor_mentions,
                 mention_evidence=mention_evidence,
                 mention_evidence_predicates=mention_evidence_predicates,
                 sentence_evidence=sentence_evidence, transfer_bounds=transfer_bounds, date_anchor=date_anchor,
                 vocabulary_guard=vocabulary_guard) for case in loaded]
        metadata = {"dataset": dataset, "variant": variant, "model": model, "credential_slot": credential_slot,
                    "case_count": len(loaded), "primary_specs": len(specs), "prompt_hashes": hashes,
                    "input_sha256": input_sha256, "gold_sha256": gold_sha256,
                    "quote_resolution": quote_resolution, "rich_repair_blockers": rich_repair_blockers,
                    "existing_names": existing_names}
        if anchor_mentions:
            metadata["anchor_mentions"] = True
        if mention_evidence:
            metadata["mention_evidence"] = True
            metadata["mention_evidence_predicates"] = [p for p in MENTION_EVIDENCE_PREDICATES
                                                      if p in mention_evidence_predicates]
        if sentence_evidence:
            metadata["sentence_evidence"] = True
        if transfer_bounds:
            metadata["transfer_bounds"] = True
        if date_anchor:
            metadata["date_anchor"] = True
        if vocabulary_guard:
            metadata["vocabulary_guard"] = True
        if mode == "preflight":
            return {**metadata, "status": "PREFLIGHT_PASS"}
        if mode == "revalidate":
            # Explicit source wins; otherwise replay the selected configuration.
            return revalidate_cases(loaded, Path(run_directory) if run_directory is not None else root, root,
                                    quote_resolution=quote_resolution, rich_repair_blockers=rich_repair_blockers,
                                    anchor_mentions=anchor_mentions, mention_evidence=mention_evidence,
                                    mention_evidence_predicates=mention_evidence_predicates,
                                    sentence_evidence=sentence_evidence, transfer_bounds=transfer_bounds, date_anchor=date_anchor,
                                    vocabulary_guard=vocabulary_guard)

        def guard(*, include_gold: bool = False):
            verify(include_gold=include_gold)
            if prompt_hashes(variant) != hashes:
                raise CheckpointIntegrityError("Development prompt sources changed during execution")

        if mode == "run":
            pacer = PersistentRollingOperationPacer(
                root / "checkpoints" / "global_pacing.json",
                max_operations=protocol.GLOBAL_MAX_PROVIDER_OPERATIONS,
                window_seconds=protocol.GLOBAL_ROLLING_WINDOW_SECONDS, clock=clock, sleep=wait)
            secrets = ()
            if transport is None:  # pragma: no cover - live provider only
                from tools.story_extraction.gemini_key_pool_v1 import load_runtime_config
                from tools.story_extraction.run_m4_04b2_dev_predictions_v1 import GeminiDevWindowTransport

                config = load_runtime_config()
                slots = [c for c in config.credentials if c.slot_id == credential_slot]
                if len(slots) != 1:
                    raise DevelopmentError("Credential slot is unavailable or ambiguous")
                transport = GeminiDevWindowTransport(slots[0], pacer, guard)
                secrets = tuple(c._api_key for c in config.credentials)
            executor = DurableResearchExecutor(root / "checkpoints" / "jobs",
                                               protocol_id=(f"{TASK_ID}:{label}" if dataset == "DEV2"
                                                            else f"{TASK_ID}:{dataset}:{label}"), clock=clock,
                                               window_cooldown_seconds=protocol.WINDOW_COOLDOWN_SECONDS,
                                               forbidden_secrets=secrets)
            smoke = replace(smoke_spec(), job_id=f"{job_prefix}_SMOKE_{credential_slot.upper()}",
                            model=model, credential_slot=credential_slot, research_task_id=TASK_ID)
            guard()
            record = _run_job(executor, smoke, transport, wait)
            raw = (record.get("first_success") or {}).get("raw_response")
            try:
                qualified = isinstance(raw, str) and json.loads(raw) == {"status": "ok"}
            except json.JSONDecodeError:
                qualified = False
            _write_json(root / "smoke.json", {"qualified": qualified, "transport": _telemetry(record)})
            if not qualified:
                raise DevelopmentError("Credential smoke qualification failed")
            run_cases(loaded, specs, variant, executor, transport, root, guard, wait,
                      quote_resolution=quote_resolution, rich_repair_blockers=rich_repair_blockers,
                      existing_names=existing_names, anchor_mentions=anchor_mentions,
                      mention_evidence=mention_evidence,
                      mention_evidence_predicates=mention_evidence_predicates,
                      sentence_evidence=sentence_evidence, transfer_bounds=transfer_bounds, date_anchor=date_anchor,
                      vocabulary_guard=vocabulary_guard)
        guard(include_gold=True)
        if dataset == "FV2":
            sealed_gold = scoring.read_gold(fv2_dir / fv2_protocol.FV2_GOLD_NAME)
            gold = {cid: {**sealed_gold[cid], "acceptable_optional_assertion_ids": []} for cid in selected}
        elif dataset == "DEV2":
            gold = read_gold(dev2_gold, selected)
        score = score_cases(loaded, specs, gold, root, align_gold=align_gold)
        score.update(metadata)
        score["snapshot_v2_sha256"] = scoring.SNAPSHOT_V2_SHA256
        score["evaluator_version"] = scoring.evaluator.EVALUATOR_VERSION
        _write_json(root / ("score_aligned.json" if align_gold else "score.json"), score)
        return score


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--dataset", choices=("DEV1", "DEV2", "FV2"), default="DEV2")
    parser.add_argument("--fv2-dir", type=Path, help="Directory holding the sealed FV2 packages")
    parser.add_argument("--align-gold", action="store_true", help="Align development gold in memory when scoring")
    parser.add_argument("--dev2-input", type=Path)
    parser.add_argument("--dev2-gold", type=Path)
    parser.add_argument("--dev1-package", type=Path)
    parser.add_argument("--dev1-ingestion-manifest", type=Path)
    parser.add_argument("--dev1-source-root", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--model", default=protocol.MODEL)
    parser.add_argument("--credential-slot", default=protocol.CREDENTIAL_SLOT)
    parser.add_argument("--cases", type=lambda value: value.split(","))
    parser.add_argument("--quote-resolution", action="store_true")
    parser.add_argument("--anchor-mentions", action="store_true")
    parser.add_argument("--mention-evidence", action="store_true",
                        help="Narrow sufficient evidence to located mentions and verbatim names")
    parser.add_argument("--mention-evidence-predicates", default=MENTION_EVIDENCE_PREDICATES,
                        type=lambda value: tuple(part.strip() for part in value.split(",")),
                        help="Comma-separated subset of RefersTo,NamedAs (default: both)")
    parser.add_argument("--sentence-evidence", action="store_true",
                        help="Widen sufficient assertion evidence to single sentences")
    parser.add_argument("--transfer-bounds", action="store_true",
                        help="Bound possession validity using matching transfer anchors")
    parser.add_argument("--date-anchor", action="store_true",
                        help="Move a named calendar date to the sole event in its sentence")
    parser.add_argument("--vocabulary-guard", action="store_true",
                        help="Normalize TOKEN values or drop unreferenced invalid propositions")
    parser.add_argument("--rich-repair-blockers", action="store_true")
    parser.add_argument("--existing-names", action="store_true",
                        help="Add affirmed prior-context names and mention forms to model input")
    parser.add_argument("--run-directory", type=Path, help="Existing run directory to revalidate")
    parser.add_argument("--mode", choices=("preflight", "run", "score", "revalidate"), default="preflight")
    args = parser.parse_args(argv)
    try:
        result = execute(**vars(args))
        public = result["totals"] if args.mode == "revalidate" else (
            result if args.mode == "preflight" else public_summary(result))
        print(json.dumps(public, sort_keys=True))
    except (DevelopmentError, Dev2PredictionError, Fv1PredictionError, dev1_protocol.DevBenchmarkProtocolError,
            CheckpointIntegrityError, OSError, ValueError, KeyError,
            protocol.Fv1ProtocolError) as error:
        print(f"M4_P4_DEV_STOPPED: {type(error).__name__}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
