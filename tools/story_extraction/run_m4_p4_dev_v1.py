"""Development-only P3/P4 Draft V1.1 runner on open-gold DEV2 tuning data.

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
import tempfile
import time
from typing import Any, Callable, Mapping, Sequence
from zipfile import ZipFile

from tools.story_extraction import m4_04b3f_fv1_protocol_v1 as protocol
from tools.story_extraction import score_m4_04b3h_fv1_v1 as scoring
from tools.story_extraction.check_annotation_conventions_v1 import RULE_IDS, check_batch
from tools.story_extraction.draft_compiler_v1 import DraftCompilerContext
from tools.story_extraction.draft_compiler_v1_1 import prepare_story_extraction_draft_v1_1
from tools.story_extraction.durable_research_executor_v1 import (
    CheckpointIntegrityError, DurableJobSpec, DurableResearchExecutor, PersistentRollingOperationPacer,
)
from tools.story_extraction.evaluate_extraction_v0 import FAILURE_CODES
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


class DevelopmentError(RuntimeError):
    """Invalid development inputs or artifacts; diagnostics contain no source text."""


@dataclass(frozen=True)
class CaseInput:
    case_id: str
    prepared_input: Mapping[str, Any]
    compiler_context: DraftCompilerContext
    sources: tuple[bytes, ...]


def prompt_material(variant: str) -> dict[str, str]:
    """Reuse the locked composition, substituting only the selected preamble."""
    if variant not in ("P3", "P4"):
        raise DevelopmentError("Unknown prompt variant")
    material = protocol.prompt_material()
    if variant == "P4":
        old = protocol._normalized_text(protocol.SYSTEM_PREAMBLE_PATH)
        new = protocol._normalized_text(protocol.PROMPT_ROOT / "story_extraction_draft_p4_system_v1_1.txt")
        material["primary_system"] = new + material["primary_system"][len(old):]
        material["repair_system"] = material["primary_system"] + "\n\n" + protocol.REPAIR_SYSTEM_SUFFIX
    return material


def prompt_hashes(variant: str) -> dict[str, Any]:
    paths = (protocol.PROMPT_ROOT / f"story_extraction_draft_{variant.lower()}_system_v1_1.txt",
             protocol.USER_TEMPLATE_PATH, protocol.REPAIR_USER_TEMPLATE_PATH,
             protocol.DRAFT_SCHEMA_PATH, protocol.V1_SCHEMA_PATH, protocol.PREDICATE_REGISTRY_PATH)
    return {"composed_sha256": {key: protocol.sha256_text(value)
                                for key, value in prompt_material(variant).items()},
            "source_sha256": {p.name: protocol.file_sha256(p) for p in paths}}


def verify_packages(dev2_input: Path, dev2_gold: Path) -> None:
    for path, expected in ((dev2_input, INPUT_SHA256), (dev2_gold, GOLD_SHA256)):
        if protocol.file_sha256(path) != expected:
            raise DevelopmentError("DEV2 archive hash mismatch")


def selected_cases(cases: Sequence[str] | None) -> tuple[str, ...]:
    selected = tuple(CASE_IDS if cases is None else cases)
    if not selected or len(set(selected)) != len(selected) or not set(selected) <= set(CASE_IDS):
        raise DevelopmentError("Unknown, empty or duplicate DEV2 selection")
    return selected


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
    return replace(protocol._spec(f"{TASK_ID}_{variant}_{case.case_id}_PRIMARY",
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
    return replace(primary, job_id=f"{TASK_ID}_{variant}_{case.case_id}_REPAIR_1",
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
                           "adjudications": []})
            report = check_batch(batch, case.sources, case.compiler_context.base_document)
            conventions.update(report["counts"])
            checked.update(report["checked"])
        else:
            validation = saved["validation"]
            codes = sorted({f"{b['phase']}:{b['code']}" for b in validation["blockers"]}
                           or {validation["category"]})
            result = scoring._structural_failure_result({"repair_validation": {"errors": codes}},
                                                        item["gold_completeness"])
        rows.append({"case_id": case.case_id, "evaluation": result, "conventions": report,
                     "terminal_status": saved["terminal_status"], "repair_used": saved["repair_used"]})
    summary = scoring._summary([row["evaluation"] for row in rows])
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
    return {"aggregate": numbers(score["summary"], shape),
            "conventions_counts": numbers(score["conventions_counts"], dict.fromkeys(RULE_IDS, 0)),
            "conventions_cases_checked": numbers(score, {"conventions_cases_checked": 0}).get(
                "conventions_cases_checked")}


def execute(*, variant: str, dev2_input: Path, dev2_gold: Path, output_root: Path,
            model: str = protocol.MODEL, credential_slot: str = protocol.CREDENTIAL_SLOT,
            cases: Sequence[str] | None = None, mode: str = "preflight",
            case_loader: Callable = load_case_inputs, transport: Transport | None = None,
            wait: Callable = time.sleep, clock: Callable = time.time) -> dict[str, Any]:
    if mode not in ("preflight", "run", "score"):
        raise DevelopmentError("Unknown development mode")
    selected = selected_cases(cases)
    verify_packages(dev2_input, dev2_gold)
    hashes = prompt_hashes(variant)
    root = Path(output_root) / variant
    with tempfile.TemporaryDirectory() as tmp:
        loaded = load_cases(dev2_input, Path(tmp), selected, case_loader, variant)
        specs = [build_primary_spec(variant, case, model, credential_slot) for case in loaded]
        metadata = {"variant": variant, "model": model, "credential_slot": credential_slot,
                    "case_count": len(loaded), "primary_specs": len(specs), "prompt_hashes": hashes,
                    "input_sha256": INPUT_SHA256, "gold_sha256": GOLD_SHA256}
        if mode == "preflight":
            return {**metadata, "status": "PREFLIGHT_PASS"}

        def guard():
            verify_packages(dev2_input, dev2_gold)
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
                                               protocol_id=f"{TASK_ID}:{variant}", clock=clock,
                                               window_cooldown_seconds=protocol.WINDOW_COOLDOWN_SECONDS,
                                               forbidden_secrets=secrets)
            smoke = replace(smoke_spec(), job_id=f"{TASK_ID}_{variant}_SMOKE_{credential_slot.upper()}",
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
        score = score_cases(loaded, specs, read_gold(dev2_gold, selected), root)
        score.update(metadata)
        score["snapshot_v2_sha256"] = scoring.SNAPSHOT_V2_SHA256
        score["evaluator_version"] = scoring.evaluator.EVALUATOR_VERSION
        _write_json(root / "score.json", score)
        return score


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=("P3", "P4"), required=True)
    parser.add_argument("--dev2-input", type=Path, required=True)
    parser.add_argument("--dev2-gold", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--model", default=protocol.MODEL)
    parser.add_argument("--credential-slot", default=protocol.CREDENTIAL_SLOT)
    parser.add_argument("--cases", type=lambda value: value.split(","))
    parser.add_argument("--mode", choices=("preflight", "run", "score"), default="preflight")
    args = parser.parse_args(argv)
    try:
        result = execute(**vars(args))
        print(json.dumps(result if args.mode == "preflight" else public_summary(result), sort_keys=True))
    except (DevelopmentError, Dev2PredictionError, CheckpointIntegrityError, OSError, ValueError, KeyError,
            protocol.Fv1ProtocolError) as error:
        print(f"M4_P4_DEV_STOPPED: {type(error).__name__}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
