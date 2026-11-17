"""Development-only prompt-variant Draft V1.1 runner on open-gold DEV1/DEV2 tuning data.

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
from tools.story_extraction.check_annotation_conventions_v1 import RULE_IDS, check_batch
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
    Transport, _run_job, _telemetry, _write_json, _write_text, smoke_spec, validate_raw,
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
    if dataset not in ("DEV1", "DEV2"):
        raise DevelopmentError("Unknown development dataset")
    allowed = dev1_protocol.CASE_IDS if dataset == "DEV1" else CASE_IDS
    selected = tuple(allowed if cases is None else cases)
    if not selected or len(set(selected)) != len(selected) or not set(selected) <= set(allowed):
        raise DevelopmentError(f"Unknown, empty or duplicate {dataset} selection")
    return selected


def _job_prefix(variant: str, dataset: str) -> str:
    return f"{TASK_ID}_DEV1_{variant}" if dataset == "DEV1" else f"{TASK_ID}_{variant}"


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
        context = replace(by_id[cid].compiler_context, process_id=f"{TASK_ID}_{variant}",
                          process_version="v1.1", run_id=f"{variant}_{cid}_PRIMARY")
        result.append(CaseInput(cid, prepare_story_extraction_draft_v1_1(context), context,
                                ((input_root / "m3_sources" / cid / "unit.txt").read_bytes(),)))
    return result


def build_primary_spec(variant: str, case: CaseInput, model: str = protocol.MODEL,
                       credential_slot: str = protocol.CREDENTIAL_SLOT) -> DurableJobSpec:
    material = prompt_material(variant)
    user = protocol._render(material["primary_user_template"], {
        "CASE_ID": case.case_id,
        "PREPARED_INPUT_JSON": protocol.canonical_json_bytes(dict(case.prepared_input)).decode().rstrip(),
    })
    return replace(protocol._spec(f"{_job_prefix(variant, case.dataset)}_{case.case_id}_PRIMARY",
                                  material["primary_system"], user),
                   model=model, credential_slot=credential_slot, research_task_id=TASK_ID)


def build_repair_spec(variant: str, case: CaseInput, primary_raw: str, validation: Mapping,
                      model: str = protocol.MODEL,
                      credential_slot: str = protocol.CREDENTIAL_SLOT) -> DurableJobSpec:
    payload = protocol.sanitized_failure(validation["category"], validation["blockers"])
    material = prompt_material(variant)
    user = protocol._render(material["repair_user_template"], {
        "CASE_ID": case.case_id,
        "PREPARED_INPUT_JSON": protocol.canonical_json_bytes(dict(case.prepared_input)).decode().rstrip(),
        "PRIMARY_RESPONSE": primary_raw,
        "FAILURE_JSON": protocol.canonical_json_bytes(payload).decode().rstrip(),
    })
    primary = build_primary_spec(variant, case, model, credential_slot)
    return replace(primary, job_id=f"{_job_prefix(variant, case.dataset)}_{case.case_id}_REPAIR_1",
                   system_prompt=material["repair_system"], user_prompt=user)


def run_cases(cases: Sequence[CaseInput], specs: Sequence[DurableJobSpec], variant: str,
              executor: DurableResearchExecutor, transport: Transport, root: Path,
              guard: Callable[[], None], wait: Callable[[float], None]) -> None:
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
            draft, batch, validation = validate_raw(raw, case.compiler_context)
            if draft is not None:
                _write_json(directory / f"{phase}_draft.json", draft)
            attempt["validation"] = validation
            if validation["pass"] or phase == "repair_1":
                break
            # Only deterministic JSON/schema/compiler failures can reach this repair.
            spec = build_repair_spec(variant, case, raw, validation, primary.model, primary.credential_slot)
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


def score_cases(cases: Sequence[CaseInput], specs: Sequence[DurableJobSpec],
                gold: Mapping[str, dict], root: Path) -> dict[str, Any]:
    rows = []
    conventions = Counter({rule: 0 for rule in RULE_IDS})
    checked = Counter()
    for case, spec in zip(cases, specs):
        directory = root / "artifacts" / case.case_id
        saved = json.loads((directory / "validation.json").read_text(encoding="utf-8"))
        if saved["attempts"][0]["request_fingerprint"] != spec.request_fingerprint:
            raise CheckpointIntegrityError("Prediction request differs from selected development configuration")
        item = gold[case.case_id]
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
    return {"rows": rows, "summary": summary, "conventions_counts": dict(conventions),
            "conventions_checked": dict(checked), "conventions_cases_checked": sum(
                row["conventions"] is not None for row in rows)}


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


def execute(*, variant: str, output_root: Path, dev2_input: Path | None = None,
            dev2_gold: Path | None = None, dataset: str = "DEV2",
            dev1_package: Path | None = None, dev1_ingestion_manifest: Path | None = None,
            dev1_source_root: Path | None = None, dev1_case_loader: Callable = load_dev_inputs,
            model: str = protocol.MODEL, credential_slot: str = protocol.CREDENTIAL_SLOT,
            cases: Sequence[str] | None = None, mode: str = "preflight",
            case_loader: Callable = load_case_inputs, transport: Transport | None = None,
            wait: Callable = time.sleep, clock: Callable = time.time) -> dict[str, Any]:
    if mode not in ("preflight", "run", "score"):
        raise DevelopmentError("Unknown development mode")
    selected = selected_cases(cases, dataset)

    def verify():
        if dataset == "DEV1":
            if dev1_package is None or dev1_ingestion_manifest is None or dev1_source_root is None:
                raise DevelopmentError("DEV1 requires package, ingestion manifest and source root")
            if protocol.file_sha256(dev1_package) != DEV1_SHA256:
                raise DevelopmentError("DEV1 archive hash mismatch")
        else:
            if dev2_input is None or dev2_gold is None:
                raise DevelopmentError("DEV2 requires input and gold archives")
            verify_packages(dev2_input, dev2_gold)

    verify()
    hashes = prompt_hashes(variant)
    root = (Path(output_root) / "DEV1" if dataset == "DEV1" else Path(output_root)) / variant
    job_prefix = _job_prefix(variant, dataset)
    with tempfile.TemporaryDirectory() as tmp:
        if dataset == "DEV1":
            loaded, gold = load_dev1_cases(dev1_package, Path(tmp), selected, dev1_ingestion_manifest,
                                          dev1_source_root, variant, dev1_case_loader)
        else:
            loaded = load_cases(dev2_input, Path(tmp), selected, case_loader, variant)
        specs = [build_primary_spec(variant, case, model, credential_slot) for case in loaded]
        metadata = {"dataset": dataset, "variant": variant, "model": model, "credential_slot": credential_slot,
                    "case_count": len(loaded), "primary_specs": len(specs), "prompt_hashes": hashes,
                    "input_sha256": DEV1_SHA256 if dataset == "DEV1" else INPUT_SHA256,
                    "gold_sha256": DEV1_SHA256 if dataset == "DEV1" else GOLD_SHA256}
        if mode == "preflight":
            return {**metadata, "status": "PREFLIGHT_PASS"}

        def guard():
            verify()
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
                                               protocol_id=(f"{TASK_ID}:DEV1:{variant}" if dataset == "DEV1"
                                                            else f"{TASK_ID}:{variant}"), clock=clock,
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
            run_cases(loaded, specs, variant, executor, transport, root, guard, wait)
        guard()
        score = score_cases(loaded, specs, gold if dataset == "DEV1" else read_gold(dev2_gold, selected), root)
        score.update(metadata)
        score["snapshot_v2_sha256"] = scoring.SNAPSHOT_V2_SHA256
        score["evaluator_version"] = scoring.evaluator.EVALUATOR_VERSION
        _write_json(root / "score.json", score)
        return score


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--dataset", choices=("DEV1", "DEV2"), default="DEV2")
    parser.add_argument("--dev2-input", type=Path)
    parser.add_argument("--dev2-gold", type=Path)
    parser.add_argument("--dev1-package", type=Path)
    parser.add_argument("--dev1-ingestion-manifest", type=Path)
    parser.add_argument("--dev1-source-root", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--model", default=protocol.MODEL)
    parser.add_argument("--credential-slot", default=protocol.CREDENTIAL_SLOT)
    parser.add_argument("--cases", type=lambda value: value.split(","))
    parser.add_argument("--mode", choices=("preflight", "run", "score"), default="preflight")
    args = parser.parse_args(argv)
    try:
        result = execute(**vars(args))
        print(json.dumps(result if args.mode == "preflight" else public_summary(result), sort_keys=True))
    except (DevelopmentError, Dev2PredictionError, dev1_protocol.DevBenchmarkProtocolError,
            CheckpointIntegrityError, OSError, ValueError, KeyError,
            protocol.Fv1ProtocolError) as error:
        print(f"M4_P4_DEV_STOPPED: {type(error).__name__}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
