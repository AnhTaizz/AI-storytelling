"""OFFLINE ONLY: verify and seal a fresh validation set for STORY_EXTRACTION_DRAFT_V1_1.

A case author supplies, for every case, one M3 source document, a base canonical document
and an independently authored canonical gold batch. This module authors no semantics. It

- runs the representational gate (gold -> Draft V1.1 oracle projection -> unchanged
  deterministic compiler -> source-exact canonical validation -> graph comparison);
- writes two separate private packages (extractor input, gold) with deterministic bytes;
- writes a blindness manifest that binds both hashes and the frozen interfaces;
- re-verifies everything from the sealed packages alone.

Nothing here calls a provider, selects an extractor, or scores a prediction. Source text
and gold never belong in the repository: write packages under a git-ignored directory.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from tools.story_extraction.draft_compiler_v1 import COLLECTIONS, DraftCompilationError, DraftCompilerContext
from tools.story_extraction.draft_compiler_v1_1 import (
    DRAFT_VERSION,
    DraftCompilationErrorV1_1,
    compile_story_extraction_draft_v1_1,
    migrate_draft_v1_to_v1_1,
    prepare_story_extraction_draft_v1_1,
)
from tools.story_extraction.draft_coverage_v1 import (
    canonical_gold_to_draft_v1,
    canonical_representation_signature,
)
from tools.story_extraction.extraction_contract_guard_v1 import validate_batch_guarded
from tools.story_extraction.extraction_contract_v0 import merge as contract_merge  # noqa: F401  (for case authors)
from tools.story_extraction.holdout_seal_v1 import check_package_separation, gold_batch_labels
from tools.story_ingestion.light_novel_adapter_v0 import ingest

REPO_ROOT = Path(__file__).resolve().parents[2]

PROFILE_ID = "STORY_UNDERSTANDING_CORE_V0"
GOLD_STATUS = ("AGENT_DRAFT_GOLD", "NOT_HUMAN_CONFIRMED")
PROCESS_ID = "fresh-validation-oracle-projection"
PROCESS_VERSION = "v1"
EXTRACTOR_SURFACE = "prepared_draft_input.json members only"
INPUT_MANIFEST = "input_manifest.json"
GOLD_MANIFEST = "gold_manifest.json"
SOURCE_MEMBER = "unit.txt"

# Files whose bytes define the interface this set validates. A changed hash means the set
# was sealed against something else.
BOUND_FILES = (
    "schemas/story_extraction/story_extraction_draft_v1_1.schema.json",
    "schemas/story_extraction/story_extraction_draft_v1.schema.json",
    "schemas/story_extraction/story_extraction_batch_v0.schema.json",
    "schemas/canonical_story/canonical_story_v0.schema.json",
    "schemas/canonical_story/predicate_registry_v0.yaml",
    "tools/story_extraction/draft_compiler_v1_1.py",
    "tools/story_extraction/draft_compiler_v1.py",
    "tools/story_extraction/draft_coverage_v1.py",
    "tools/story_extraction/extraction_contract_v0.py",
    "tools/story_extraction/extraction_contract_guard_v1.py",
    "tools/story_ingestion/light_novel_adapter_v0.py",
    "benchmarks/m4_extraction/M4_EVALUATION_PROTOCOL_SNAPSHOT_V2.yaml",
)

# Keys that only gold may carry. The extractor input is scanned for them at any depth.
GOLD_ONLY_KEYS = frozenset({
    "candidate_records", "gold_batch", "gold_completeness", "gold_status", "required_assertions",
    "acceptable_assertions", "line_coverage", "capability", "oracle_draft", "compiled_round_trip",
    "representational_gate", "expected_metrics", "adjudications",
})


class FreshValidationError(ValueError):
    pass


@dataclass(frozen=True)
class AuthoredCase:
    """One independently authored case. `line_coverage` has one note per evidence-eligible
    passage: {"segment": <1-based passage number>, "note": <what is in or out of profile>}."""

    case_id: str
    capability: str
    manifest: Dict[str, Any]
    source_bytes: bytes
    base_document: Dict[str, Any]
    gold_batch: Dict[str, Any]
    line_coverage: Tuple[Dict[str, Any], ...]
    ingestion: Any


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")


def bound_file_hashes(root: Path = REPO_ROOT) -> Dict[str, str]:
    return {name: sha256_bytes((root / name).read_bytes()) for name in BOUND_FILES}


def ingest_source(manifest: Mapping[str, Any], source_bytes: bytes) -> Any:
    """Run the frozen M3 adapter over a one-document manifest whose file is SOURCE_MEMBER."""
    documents = manifest.get("documents", [])
    if len(documents) != 1 or documents[0].get("path") != SOURCE_MEMBER:
        raise FreshValidationError(f"a case manifest must name exactly one document at {SOURCE_MEMBER!r}")
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / SOURCE_MEMBER).write_bytes(source_bytes)
        return ingest(dict(manifest), Path(tmp))


def compiler_context(case_id: str, base_document: Dict[str, Any], scope: Mapping[str, Any],
                     ingestion: Any) -> DraftCompilerContext:
    return DraftCompilerContext(base_document, scope["passage_inputs"], scope["as_of_position"],
                                scope["profile_id"], PROCESS_ID, PROCESS_VERSION, case_id, ingestion)


def representational_gate(case: AuthoredCase) -> Dict[str, Any]:
    """Can the authored gold be written in Draft V1.1 and compiled back unchanged?

    The oracle projection tests the notation; it is not a prediction. Failures are reported
    as codes only, so a report never carries source text or gold.
    """
    result: Dict[str, Any] = {"gold_valid": False, "draft_compiles": False, "compiled_valid": False,
                              "alpha_equivalent": False, "failure": None}
    gold, base = case.gold_batch, case.base_document
    result["gold_valid"] = bool(validate_batch_guarded(gold, base, case.ingestion)["pass"])
    if not result["gold_valid"]:
        result["failure"] = "GOLD_FAILS_FROZEN_VALIDATION"
    else:
        context = compiler_context(case.case_id, base, gold["scope"], case.ingestion)
        try:
            draft_v1, mapping = canonical_gold_to_draft_v1(gold, context)
            draft = migrate_draft_v1_to_v1_1(draft_v1)
            compiled = compile_story_extraction_draft_v1_1(draft, context)
        except DraftCompilationErrorV1_1 as error:
            result["failure"] = "DRAFT_V1_1_BLOCKERS:" + ",".join(sorted({b.code for b in error.blockers}))
        except DraftCompilationError as error:
            result["failure"] = f"ORACLE_PROJECTION:{error.code}"
        else:
            result["draft_compiles"] = True
            result["compiled_valid"] = bool(validate_batch_guarded(compiled, base, case.ingestion)["pass"])
            handles = set(mapping.values())
            # Records of the base document keep their ids in both batches.
            reverse = {rid: handle for rid, handle in mapping.items() if "_EXISTING_" in handle}
            for collection in COLLECTIONS.values():
                for record in compiled["candidate_records"][collection]:
                    handle = record["id"].rsplit("-", 1)[-1]
                    if handle in handles:
                        reverse[record["id"]] = handle
            result["alpha_equivalent"] = (canonical_representation_signature(gold, mapping)
                                          == canonical_representation_signature(compiled, reverse))
            if not result["compiled_valid"]:
                result["failure"] = "COMPILED_FAILS_FROZEN_VALIDATION"
            elif not result["alpha_equivalent"]:
                result["failure"] = "GRAPH_NOT_EQUIVALENT"
            result["oracle_draft"], result["compiled_round_trip"] = draft, compiled
    result["representable"] = result["failure"] is None
    return result


def case_issues(case: AuthoredCase) -> List[str]:
    """Labelling and completeness problems of one authored case (empty: none)."""
    issues = [f"{case.case_id}: {issue}" for issue in gold_batch_labels(case.gold_batch)]
    scope = case.gold_batch["scope"]
    if scope.get("profile_id") != PROFILE_ID:
        issues.append(f"{case.case_id}: profile is not {PROFILE_ID}")
    eligible = {index for index, item in enumerate(scope["passage_inputs"], start=1)
                if item["use"] == "EVIDENCE_ELIGIBLE"}
    covered = [note.get("segment") for note in case.line_coverage]
    if set(covered) != eligible or len(covered) != len(set(covered)):
        issues.append(f"{case.case_id}: coverage notes must cover every evidence-eligible passage exactly once")
    if any(not str(note.get("note", "")).strip() for note in case.line_coverage):
        issues.append(f"{case.case_id}: an empty coverage note")
    if not case.gold_batch["candidate_records"]["assertions"]:
        issues.append(f"{case.case_id}: no assertions")
    return issues


def gold_leaks(entries: Mapping[str, Any]) -> List[str]:
    """`entries` maps input member name -> parsed JSON (or None for non-JSON members)."""
    found = []

    def walk(value: Any, where: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in GOLD_ONLY_KEYS:
                    found.append(f"{where}.{key}")
                walk(child, f"{where}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{where}[{index}]")

    for name, value in sorted(entries.items()):
        if any("gold" in part.lower() for part in PurePosixPath(name).parts):
            found.append(f"{name}: member name refers to gold")
        walk(value, name)
    return found


def _input_members(case: AuthoredCase) -> Dict[str, bytes]:
    scope = case.gold_batch["scope"]
    context = compiler_context(case.case_id, case.base_document, scope, case.ingestion)
    root = f"cases/{case.case_id}"
    return {
        f"{root}/base_document.json": json_bytes(case.base_document),
        f"{root}/prepared_draft_input.json": json_bytes(prepare_story_extraction_draft_v1_1(context)),
        f"{root}/scope.json": json_bytes({key: scope[key] for key in
                                          ("passage_inputs", "as_of_position", "profile_id")}),
        f"{root}/ingestion_report.json": json_bytes(case.ingestion.ingestion_report()),
        f"{root}/m3/manifest.json": json_bytes(case.manifest),
        f"{root}/m3/{SOURCE_MEMBER}": case.source_bytes,
    }


def _zip_bytes(members: Mapping[str, bytes]) -> bytes:
    """A ZIP with stored (uncompressed) members in name order and fixed timestamps, so the
    same members always give the same bytes on every machine."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "package.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as bundle:
            for name in sorted(members):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.external_attr = 0o644 << 16
                bundle.writestr(info, members[name])
        return path.read_bytes()


def summarize(cases: Sequence[AuthoredCase]) -> Dict[str, Any]:
    """Public-safe counts: no text, quotes, names or per-case semantics."""
    records: Counter = Counter()
    predicates: Counter = Counter()
    status: Counter = Counter()
    polarity: Counter = Counter()
    roles: Counter = Counter()
    labels: Counter = Counter()
    derivations = validity = 0
    for case in cases:
        candidate = case.gold_batch["candidate_records"]
        for name, rows in candidate.items():
            records[name] += len(rows)
        # An assertion may commit to a proposition that the base document already holds.
        by_id = {p["id"]: p for p in [*case.base_document["propositions"], *candidate["propositions"]]}
        for evidence in candidate["evidence_refs"]:
            roles[evidence["role"]] += 1
        for assertion in candidate["assertions"]:
            predicates[by_id[assertion["proposition_id"]]["predicate"]] += 1
            status[assertion["epistemic_status"]] += 1
            polarity[assertion["polarity"]] += 1
            validity += "validity" in assertion
            derivations += len(assertion["support"]["derivations"])
            for evidence_set in assertion["support"]["evidence_sets"]:
                labels[evidence_set["label"]] += 1
    return {"cases": len(cases), "required_assertions": records["assertions"],
            "acceptable_optional_assertions": 0, "record_counts": dict(sorted(records.items())),
            "predicate_counts": dict(sorted(predicates.items())), "epistemic_status": dict(sorted(status.items())),
            "assertion_polarity": dict(sorted(polarity.items())), "evidence_roles": dict(sorted(roles.items())),
            "evidence_set_labels": dict(sorted(labels.items())), "derivations": derivations,
            "assertions_with_validity": validity}


def seal(cases: Sequence[AuthoredCase], out_dir: Path, set_id: str, source_family: str,
         extra_gold_members: Mapping[str, bytes] = ()) -> Dict[str, Any]:
    """Gate every case, then write <set_id>_INPUT.zip, <set_id>_GOLD.zip and
    <set_id>_BLINDNESS_MANIFEST.json into `out_dir`. Returns the public-safe seal summary.

    `extra_gold_members` (for example the authoring script, for a deterministic rebuild)
    are stored in the gold package under `gold/authoring/`.
    """
    case_ids = [case.case_id for case in cases]
    if not cases or len(set(case_ids)) != len(case_ids):
        raise FreshValidationError("case ids must be unique and at least one case is required")
    issues = [issue for case in cases for issue in case_issues(case)]
    gates = {case.case_id: representational_gate(case) for case in cases}
    issues += [f"{case_id}: {gate['failure']}" for case_id, gate in gates.items() if not gate["representable"]]
    if issues:
        raise FreshValidationError("; ".join(issues))

    input_members: Dict[str, bytes] = {}
    gold_members: Dict[str, bytes] = {f"gold/authoring/{name}": data
                                      for name, data in dict(extra_gold_members).items()}
    input_rows, gold_rows = [], []
    for case in cases:
        members = _input_members(case)
        input_members.update(members)
        root = f"cases/{case.case_id}"
        input_rows.append({"case_id": case.case_id, "base_document_member": f"{root}/base_document.json",
                           "prepared_input_member": f"{root}/prepared_draft_input.json",
                           "scope_member": f"{root}/scope.json",
                           "ingestion_report_member": f"{root}/ingestion_report.json",
                           "m3_manifest_member": f"{root}/m3/manifest.json"})
        gate = gates[case.case_id]
        gold_root = f"gold/{case.case_id}"
        gold_members[f"{gold_root}/gold_batch.json"] = json_bytes(case.gold_batch)
        gold_members[f"{gold_root}/oracle_draft_v1_1.json"] = json_bytes(gate["oracle_draft"])
        gold_members[f"{gold_root}/compiled_round_trip.json"] = json_bytes(gate["compiled_round_trip"])
        gold_rows.append({
            "case_id": case.case_id, "capability": case.capability, "extraction_profile": PROFILE_ID,
            "gold_status": list(GOLD_STATUS), "gold_completeness": "COMPLETE_FOR_PROFILE",
            "required_assertions": sorted(a["id"] for a in case.gold_batch["candidate_records"]["assertions"]),
            "acceptable_assertions": [], "line_coverage": list(case.line_coverage),
            "gold_batch_member": f"{gold_root}/gold_batch.json",
        })
    input_members[INPUT_MANIFEST] = json_bytes({
        "artifact": f"{set_id}_INPUT", "case_count": len(cases), "draft_interface": DRAFT_VERSION,
        "extractor_surface": EXTRACTOR_SURFACE, "cases": input_rows})
    gold_members[GOLD_MANIFEST] = json_bytes({
        "artifact": f"{set_id}_GOLD", "case_count": len(cases), "source_family": source_family,
        "annotation_method": "HUMAN_ANNOTATION", "human_review_performed": False, "cases": gold_rows})

    input_zip, gold_zip = _zip_bytes(input_members), _zip_bytes(gold_members)
    input_sha, gold_sha = sha256_bytes(input_zip), sha256_bytes(gold_zip)
    leaks = gold_leaks({name: (json.loads(data) if name.endswith(".json") else None)
                        for name, data in input_members.items()})
    separation = check_package_separation(input_members, gold_members, input_sha, gold_sha)
    if leaks or separation:
        raise FreshValidationError("; ".join(leaks + separation))

    manifest = {
        "manifest": f"{set_id}_BLINDNESS_MANIFEST", "set_id": set_id, "source_family": source_family,
        "draft_interface": DRAFT_VERSION, "case_ids": case_ids,
        "input_package": {"name": f"{set_id}_INPUT.zip", "sha256": input_sha, "bytes": len(input_zip),
                          "members": len(input_members)},
        "gold_package": {"name": f"{set_id}_GOLD.zip", "sha256": gold_sha, "bytes": len(gold_zip),
                         "members": len(gold_members)},
        "bound_files_sha256": bound_file_hashes(),
        "extractor_access_allowed": {"input_package": True, "gold_package": False},
        "gold_may_be_opened_after": {"predictions_locked_and_hashed": True},
        "gold_status": list(GOLD_STATUS),
        "contamination_state": "CLEAN",
        "contamination_rule": "gold opened before the prediction package is locked and hashed => CONTAMINATED",
    }
    manifest_bytes = json_bytes(manifest)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / manifest["input_package"]["name"]).write_bytes(input_zip)
    (out_dir / manifest["gold_package"]["name"]).write_bytes(gold_zip)
    (out_dir / f"{set_id}_BLINDNESS_MANIFEST.json").write_bytes(manifest_bytes)

    gate_counts = {key: f"{sum(bool(g[key]) for g in gates.values())}/{len(cases)}"
                   for key in ("gold_valid", "draft_compiles", "compiled_valid", "alpha_equivalent",
                               "representable")}
    return {"set_id": set_id, "source_family": source_family, "draft_interface": DRAFT_VERSION,
            "case_capabilities": {case.case_id: case.capability for case in cases},
            "gold": summarize(cases), "representational_gate": gate_counts,
            "packages": {"input": manifest["input_package"], "gold": manifest["gold_package"],
                         "blindness_manifest": {"name": f"{set_id}_BLINDNESS_MANIFEST.json",
                                                "sha256": sha256_bytes(manifest_bytes)}},
            "input_contains_gold": False, "shared_member_names": 0}


def _read_members(path: Path) -> Dict[str, bytes]:
    with zipfile.ZipFile(path) as bundle:
        return {info.filename: bundle.read(info) for info in bundle.infolist() if not info.is_dir()}


def load_input_cases(input_zip: Path) -> List[Dict[str, Any]]:
    """Read the extractor input package: per case the prepared input (the only extractor
    surface) and the trusted host context the compiler needs. Refuses a package with gold."""
    members = _read_members(input_zip)
    parsed = {name: (json.loads(data) if name.endswith(".json") else None) for name, data in members.items()}
    leaks = gold_leaks(parsed)
    if leaks:
        raise FreshValidationError("gold found in the input package: " + "; ".join(leaks))
    manifest = parsed.get(INPUT_MANIFEST)
    if (not isinstance(manifest, dict) or manifest.get("draft_interface") != DRAFT_VERSION
            or manifest.get("extractor_surface") != EXTRACTOR_SURFACE
            or manifest.get("case_count") != len(manifest.get("cases", []))):
        raise FreshValidationError("input manifest identity mismatch")
    loaded = []
    for row in manifest["cases"]:
        m3_manifest = parsed[row["m3_manifest_member"]]
        source = members[str(PurePosixPath(row["m3_manifest_member"]).parent / SOURCE_MEMBER)]
        ingestion = ingest_source(m3_manifest, source)
        report = parsed[row["ingestion_report_member"]]
        if report.get("corpus_fingerprint_sha256") != ingestion.fingerprint:
            raise FreshValidationError(f"{row['case_id']}: M3 ingestion binding mismatch")
        base, scope = parsed[row["base_document_member"]], parsed[row["scope_member"]]
        context = compiler_context(row["case_id"], base, scope, ingestion)
        prepared = parsed[row["prepared_input_member"]]
        if prepared != prepare_story_extraction_draft_v1_1(context):
            raise FreshValidationError(f"{row['case_id']}: prepared input does not match its source")
        loaded.append({"case_id": row["case_id"], "prepared_input": prepared, "context": context,
                       "manifest": m3_manifest, "source_bytes": source, "base_document": base})
    return loaded


def verify_sealed(out_dir: Path, set_id: str) -> Dict[str, Any]:
    """Re-check a sealed set from its three files alone: hashes, bound interfaces, package
    separation, no gold in the input, and the representational gate for every case.

    This opens the gold package, so it is for the author before any prediction exists and
    for the evaluator after predictions are locked; never run it in between.
    """
    manifest = json.loads((out_dir / f"{set_id}_BLINDNESS_MANIFEST.json").read_text(encoding="utf-8"))
    input_path = out_dir / manifest["input_package"]["name"]
    gold_path = out_dir / manifest["gold_package"]["name"]
    issues = []
    for label, path in (("input", input_path), ("gold", gold_path)):
        if sha256_bytes(path.read_bytes()) != manifest[f"{label}_package"]["sha256"]:
            issues.append(f"{label} package hash mismatch")
    changed = sorted(name for name, digest in bound_file_hashes().items()
                     if manifest["bound_files_sha256"].get(name) != digest)
    issues += [f"bound file changed since the seal: {name}" for name in changed]
    gold_members = _read_members(gold_path)
    issues += check_package_separation(_read_members(input_path), gold_members,
                                       manifest["input_package"]["sha256"], manifest["gold_package"]["sha256"])
    gold_manifest = json.loads(gold_members[GOLD_MANIFEST])
    rows = {row["case_id"]: row for row in gold_manifest["cases"]}
    inputs = load_input_cases(input_path)
    if [item["case_id"] for item in inputs] != manifest["case_ids"] or set(rows) != set(manifest["case_ids"]):
        issues.append("case ids differ between the manifest and the packages")
    gates = {}
    for item in inputs:
        row = rows.get(item["case_id"])
        if row is None:
            continue
        case = AuthoredCase(item["case_id"], row["capability"], item["manifest"], item["source_bytes"],
                            item["base_document"], json.loads(gold_members[row["gold_batch_member"]]),
                            tuple(row["line_coverage"]), item["context"].ingestion)
        issues += case_issues(case)
        gates[case.case_id] = representational_gate(case)["representable"]
    issues += [f"{case_id}: not representable" for case_id, ok in gates.items() if not ok]
    return {"pass": not issues, "issues": issues, "cases_representable": f"{sum(gates.values())}/{len(inputs)}"}
