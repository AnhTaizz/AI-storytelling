"""Read-only B2 failure forensics + DEV1 oracle representation check, offline.

The only public output is a sanitized JSON report on stdout. Private source,
quotes, literal arguments, canonical IDs and full error messages are not emitted.
The DEV package and B2 work paths are explicit allowlists. No holdout is read.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
from zipfile import ZipFile

import yaml
from jsonschema import Draft202012Validator

from tools.canonical_story.conformance_v0 import load_schema, validate_document
from tools.story_extraction.draft_compiler_v1 import (
    COLLECTIONS, DraftCompilerContext, compile_story_extraction_draft_v1,
)
from tools.story_extraction.draft_coverage_v1 import (
    canonical_gold_to_draft_v1, canonical_representation_signature,
)
from tools.story_extraction.extraction_contract_v0 import canonical_json_bytes, merge
from tools.story_ingestion.light_novel_adapter_v0 import ingest_manifest_file

ROOT = Path(__file__).resolve().parents[2]
BASE_HEAD = "15b8af0357415f9edc9bf7661f0317b50bdcc04e"
CATEGORIES = ("envelope_copy", "passage_span_source_exact", "evidence", "canonical_schema",
              "predicate_argument", "entity_event", "provenance_review", "id_reference",
              "semantic_coverage", "unsupported")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _assert(value, code):
    if not value:
        raise ValueError(code)


def classify_issue(message, section=""):
    """Split diagnostic ownership without inferring correctness from a shape failure."""
    text = message.upper()
    if not section and ":" in message:
        prefix = message.split(":", 1)[0]
        if prefix in {"reference_integrity", "predicate_integrity", "derivation_integrity",
                      "temporal_bound_integrity", "epistemic_integrity", "evidence_set_integrity",
                      "support_path_integrity"}:
            section = prefix
    if any(x in text for x in ("MISSED_REQUIRED_ASSERTION", "MISSING_ENTITY_RESOLUTION")):
        return "semantic_coverage", "SEMANTIC_MODEL_OWNED"
    if "UNSUPPORTED_ASSERTION" in text:
        return "unsupported", "SEMANTIC_MODEL_OWNED"
    if any(x in text for x in ("SELF_CERTIFICATION", "PROVENANCE_", "UNATTESTED_REVIEW")) or section == "review_provenance":
        return "provenance_review", "MACHINE_OWNED"
    if any(x in text for x in ("MALFORMED_PASSAGE", "INVALID_PASSAGE", "SPAN_", "POSITION_MISMATCH")):
        return "passage_span_source_exact", "MACHINE_OWNED"
    if "WRONG_EVIDENCE" in text or "INSUFFICIENT_SUPPORT" in text or section in {"epistemic_integrity", "evidence_set_integrity", "support_path_integrity"}:
        return "evidence", "SEMANTIC_MODEL_OWNED"
    if any(x in text for x in ("COLLISION", "DANGLING", "DUPLICATE ID")) or section == "reference_integrity":
        return "id_reference", "MACHINE_OWNED"
    if any(x in text for x in ("ENTITY_RESOLUTION", "EVENT_GRANULARITY")):
        return "entity_event", "SEMANTIC_MODEL_OWNED"
    if section in {"predicate_integrity", "derivation_integrity", "temporal_bound_integrity"}:
        if "DUPLICATE CONCRETE PROPOSITION" in text:
            return "predicate_argument", "MACHINE_OWNED"
        return "predicate_argument", "SEMANTIC_MODEL_OWNED"
    if section == "canonical" or section == "structural":
        return "canonical_schema", "MACHINE_OWNED"
    return "envelope_copy", "MACHINE_OWNED"


def frozen_integrity():
    bound = {}
    for name in ("M4_EVALUATION_PROTOCOL_SNAPSHOT_V1", "M4_EVALUATION_PROTOCOL_SNAPSHOT_V2"):
        data = yaml.safe_load((ROOT / f"benchmarks/m4_extraction/{name}.yaml").read_text())
        for path, expected in data["files"].items():
            _assert(digest((ROOT / path).read_bytes()) == expected, "SNAPSHOT_BINDING_MISMATCH")
            bound[path] = expected
    for path in (
        "benchmarks/m1_script_quality/SCRIPT_QUALITY_CONTRACT_V0_FREEZE_RECORD.yaml",
        "benchmarks/m2_canonical_model/CANONICAL_STORY_V0_FROZEN.yaml",
        "benchmarks/m3_ingestion/LIGHT_NOVEL_INGESTION_V0_FROZEN.yaml",
    ):
        data = yaml.safe_load((ROOT / path).read_text())

        def verify(value):
            if isinstance(value, dict):
                if "path" in value and "sha256" in value:
                    file = ROOT / value["path"]
                    _assert(digest(file.read_bytes()) == value["sha256"], "FREEZE_BINDING_MISMATCH")
                    bound[value["path"]] = value["sha256"]
                for v in value.values():
                    verify(v)
            elif isinstance(value, list):
                for v in value:
                    verify(v)
        verify(data)
    return {"status": "PASS", "bound_file_count": len(bound), "bound_files": bound}


def analyze(private_root, source_root):
    _assert(subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip() == BASE_HEAD,
            "UNEXPECTED_BASE_HEAD")
    frozen = frozen_integrity()
    work = private_root / "M4_04_WORK"
    loaded = {}
    before = {}

    def read(path):
        data = path.read_bytes()
        before[path] = digest(data)
        return data

    def load(name):
        loaded[name] = json.loads(read(work / name))
        return loaded[name]

    manifest = load("M4_04B2R_DEV_PREDICTION_MANIFEST_V2.json")
    result = load("M4_04B2R_DEV_PREDICTION_RESULT_V2.json")
    evaluation = load("M4_04B2R_DEV_EVALUATION_FINAL_V2.json")
    public = yaml.safe_load((ROOT / "benchmarks/m4_extraction/M4_04B2_DEV_PREDICTION_LOCK.yaml").read_text())
    b2 = yaml.safe_load((ROOT / "benchmarks/m4_extraction/M4_04B2_DEVELOPMENT_EXTRACTION_BENCHMARK_RESULT.yaml").read_text())
    _assert(before[work / "M4_04B2R_DEV_PREDICTION_MANIFEST_V2.json"] == public["private_prediction_manifest_sha256"], "MANIFEST_HASH_MISMATCH")
    _assert(before[work / "M4_04B2R_DEV_EVALUATION_FINAL_V2.json"] == b2["evaluation"]["private_result_sha256"], "EVALUATION_HASH_MISMATCH")
    _assert(b2["status"] == "M4_04B2_DEVELOPMENT_LEADER_NOT_LOCKABLE", "B2_STATUS_MISMATCH")
    _assert(len(manifest["entries"]) == len(result["predictions"]) == 28, "PREDICTION_COUNT_MISMATCH")
    entries = {(x["candidate"], x["case_id"]): x for x in manifest["entries"]}
    eval_rows = {(x["candidate"], x["case_id"]): x for x in evaluation["rows"]}
    for candidate in ("P0", "P1"):
        ids = [{"case_id": x["case_id"], "final_prediction_sha256": x["final_prediction_sha256"],
                "primary_raw_response_sha256": x["primary_raw_response_sha256"],
                "repair_used": x["repair_used"],
                "terminal_state": "STRUCTURAL_VALID" if x["final_structural_valid"] else "STRUCTURAL_FAILURE"}
               for x in result["predictions"] if x["candidate"] == candidate]
        _assert(digest(canonical_json_bytes(ids)) == public["prediction_sets"][candidate]["sha256"], "PREDICTION_SET_HASH_MISMATCH")

    input_dir = work / "M4_04B2_DEV_INPUT_ONLY"
    base = json.loads(read(input_dir / "base_canonical_document.json"))
    cases = {x["case_id"]: x for x in map(json.loads, read(input_dir / "development_cases.jsonl").decode().splitlines()) if x}
    refs = {case_id: [] for case_id in cases}
    for line in read(input_dir / "source_passage_refs.jsonl").decode().splitlines():
        r = json.loads(line)
        refs[r["case_id"]].append({"use": r["use"], "passage_ref": r["passage_ref"]})
    ingestion = ingest_manifest_file(private_root / "M3_02_VALIDATION/light_novel_source_manifest_v0.yaml", source_root)
    terminal_counts, ownership_counts, issue_counts = Counter(), Counter(), Counter()
    rows, response_count, copy_burdens = [], 0, []
    primary_issue_codes, terminal_issue_codes = Counter(), Counter()
    for item in result["predictions"]:
        candidate, case_id = item["candidate"], item["case_id"]
        entry = entries[(candidate, case_id)]
        raw_paths = {"primary": work / f"M4_04B2_PREDICTIONS/raw/{candidate}/{case_id}_primary.txt"}
        if item["repair_used"]:
            raw_paths["repair"] = work / f"M4_04B2_PREDICTIONS/raw/{candidate}/{case_id}_repair.txt"
        raw = {}
        for phase, path in raw_paths.items():
            data = read(path)
            expected = item["primary_raw_response_sha256"] if phase == "primary" else item["repair_transport"]["first_success_response_sha256"]
            _assert(digest(data) == expected, "RAW_RESPONSE_HASH_MISMATCH")
            raw[phase] = data
            response_count += 1
        if entry["final_prediction_sha256"]:
            data = read(work / f"M4_04B2_PREDICTIONS/final/{candidate}/{case_id}.json")
            _assert(digest(data) == entry["final_prediction_sha256"], "FINAL_PREDICTION_HASH_MISMATCH")
        for error in item["primary_validation"].get("errors", []):
            primary_issue_codes[error.split(":", 1)[0]] += 1
        observed = {}

        def observe(category, owner, code):
            observed.setdefault(category, set()).add(owner)
            ownership_counts[owner] += 1
            issue_counts[f"{category}/{owner}/{code}"] += 1

        terminal_validation = item.get("repair_validation") or item["primary_validation"]
        for error in terminal_validation.get("errors", []):
            code = error.split(":", 1)[0]
            terminal_issue_codes[code] += 1
            observe(*classify_issue(error), "LOCKED_VALIDATION")
        row = eval_rows[(candidate, case_id)]
        for failure in row["evaluation"].get("failures", []):
            code = failure["code"]
            if code != "CANONICAL_CONFORMANCE_FAILURE":
                observe(*classify_issue(code), code)
            for detail in failure.get("detail", []) if isinstance(failure.get("detail"), list) else []:
                observe(*classify_issue(detail), "LOCKED_SOURCE_EXACT_DIAGNOSTIC")
        terminal = raw.get("repair", raw["primary"])
        raw_shape = "OBJECT"
        candidate_counts = {}
        try:
            batch = json.loads(terminal)
            if not isinstance(batch, dict):
                raise TypeError()
            scope = {"story_id": base["story"]["id"], "ingestion": {
                "contract_version": "LIGHT_NOVEL_INGESTION/v0", "corpus_fingerprint_sha256": ingestion.fingerprint},
                "passage_inputs": refs[case_id], "as_of_position": cases[case_id]["as_of_position"],
                "prior_canonical_context": {"kind": "BASE_DOCUMENT_RECORDS" if any(base[c] for c in COLLECTIONS.values()) else "NONE"},
                "profile_id": cases[case_id]["extraction_profile"]}
            expected = {"batch_version": "STORY_EXTRACTION_BATCH/v0", "contract_version": "STORY_EXTRACTION/v0",
                        "process": {"method": "AUTOMATED_EXTRACTION", "process_id": f"M4_04B2_{candidate}",
                                    "process_version": "v1", "run_id": f"{candidate}_{case_id}"},
                        "scope": scope, "base_canonical_identity": cases[case_id]["base_canonical_identity"]}
            copy_burdens.append({"passage_input_count": len(refs[case_id]),
                                 "required_envelope_utf8_bytes": len(canonical_json_bytes(expected)),
                                 "terminal_response_utf8_bytes": len(terminal)})
            for field, value in expected.items():
                if batch.get(field) != value:
                    observe("envelope_copy", "MACHINE_OWNED", f"COPY_MISMATCH_{field.upper()}")
            records = batch.get("candidate_records", {})
            if not isinstance(records, dict):
                raise TypeError()
            candidate_counts = {c: len(records.get(c, [])) for c in COLLECTIONS.values() if isinstance(records.get(c), list)}
            provenance = {r.get("id"): r for r in records.get("extraction_provenance", [])}
            for prov in provenance.values():
                if any(prov.get(k) != expected["process"][k] for k in ("method", "process_id", "process_version")):
                    observe("provenance_review", "MACHINE_OWNED", "PROVENANCE_COPY_MISMATCH")
            for assertion in records.get("assertions", []):
                if assertion.get("extraction_provenance_id") not in provenance:
                    observe("provenance_review", "MACHINE_OWNED", "PROVENANCE_NOT_IN_BATCH")
                review = assertion.get("review", {})
                if review.get("state") != "UNREVIEWED" or "reviewer_kind" in review:
                    observe("provenance_review", "MACHINE_OWNED", "SELF_CERTIFICATION")
            for ev in records.get("evidence_refs", []):
                try:
                    seg = next(s for s in base["source_segments"] if s["id"] == ev["segment_id"])
                    start = ev["span"]["char_start"] - seg["locator"]["char_start"]
                    end = ev["span"]["char_end_exclusive"] - seg["locator"]["char_start"]
                    expected_ref = ingestion.passage_ref(seg["id"], start, end)
                    if ev.get("span") != expected_ref["span"] or ev.get("position") != expected_ref["position"]:
                        observe("passage_span_source_exact", "MACHINE_OWNED", "EVIDENCE_SOURCE_EXACT_MISMATCH")
                except (KeyError, TypeError, ValueError, StopIteration):
                    observe("passage_span_source_exact", "MACHINE_OWNED", "EVIDENCE_UNRESOLVABLE")
                if "role" not in ev:
                    observe("evidence", "SEMANTIC_MODEL_OWNED", "EVIDENCE_ROLE_MISSING")
            # Independent diagnostics: bypass only the guard's early return,
            # do NOT rewrite batches or count these as evaluator passes.
            merged = merge(batch, base)
            for error in Draft202012Validator(load_schema()).iter_errors(merged):
                path = list(error.absolute_path)
                cat, owner = "canonical_schema", "MACHINE_OWNED"
                if path and path[0] in {"entities", "events", "temporal_anchors"} and error.validator == "enum":
                    cat, owner = "entity_event", "SEMANTIC_MODEL_OWNED"
                elif path and path[0] == "evidence_refs" and "role" in path:
                    cat, owner = "evidence", "SEMANTIC_MODEL_OWNED"
                elif "args" in path and error.validator == "enum":
                    cat, owner = "predicate_argument", "SEMANTIC_MODEL_OWNED"
                observe(cat, owner, f"SCHEMA_{error.validator.upper()}")
            conformance = validate_document(merged)
            for section, check in conformance["semantic"].items():
                for message in check["issues"]:
                    observe(*classify_issue(message, section), section.upper())
        except (json.JSONDecodeError, TypeError, KeyError):
            raw_shape = "UNPARSEABLE_OR_INCOMPLETE"
            observe("envelope_copy", "MACHINE_OWNED", raw_shape)
        for category in observed:
            terminal_counts[category] += 1
        rows.append({"candidate": candidate, "case_id": case_id,
                     "terminal_structural_valid": item["final_structural_valid"],
                     "source_exact_L0_valid": row["evaluation"]["l0_structural_validity"],
                     "terminal_shape": raw_shape, "candidate_record_counts": candidate_counts,
                     "observed_failure_ownership": {k: sorted(v) for k, v in sorted(observed.items())},
                     "semantic_quality_observability": "LOCKED_EVALUATION" if row["evaluation"]["l0_structural_validity"] else "CENSORED_BY_L0"})

    package = private_root / "M4_02_DEV_CALIBRATION_V1.zip"
    package_bytes = read(package)
    _assert(digest(package_bytes) == "a991921d0ca0afb5643948346acc407a84e17206bd6d0692c362d86de47da809", "DEV_PACKAGE_HASH_MISMATCH")
    coverage, totals = [], Counter()
    with ZipFile(package) as archive:
        prefix = "M4_02_DEV_CALIBRATION/"
        manifest_gold = json.loads(archive.read(prefix + "manifest.json"))
        for filename in ("base_canonical_document.json", "development_cases.jsonl", "source_passage_refs.jsonl"):
            archived = archive.read(prefix + filename)
            _assert(digest(archived) == manifest_gold["files"][filename], "DEV_INPUT_MEMBER_HASH_MISMATCH")
            _assert(archived == read(input_dir / filename), "DEV_INPUT_COPY_MISMATCH")
        for case_id in cases:
            member = f"gold_batches/{case_id}.json"
            gold_bytes = archive.read(prefix + member)
            _assert(digest(gold_bytes) == manifest_gold["files"][member], "DEV_GOLD_MEMBER_HASH_MISMATCH")
            gold = json.loads(gold_bytes)
            scope = gold["scope"]
            ctx = DraftCompilerContext(base, refs[case_id], cases[case_id]["as_of_position"],
                                       scope["profile_id"], "offline-gold-coverage", "v1", case_id, ingestion)
            draft, mapping = canonical_gold_to_draft_v1(gold, ctx)
            compiled = compile_story_extraction_draft_v1(draft, ctx)
            reverse = {r["id"]: next(h for h in mapping.values() if r["id"].endswith("-" + h))
                       for coll in COLLECTIONS.values() for r in compiled["candidate_records"][coll]}
            reverse.update({rid: h for rid, h in mapping.items() if "_EXISTING_" in h})
            same = canonical_representation_signature(gold, mapping) == canonical_representation_signature(compiled, reverse)
            _assert(same, "GOLD_REPRESENTATION_MISMATCH")
            counts = {c: len(gold["candidate_records"][c]) for c in COLLECTIONS.values()}
            totals.update(counts)
            coverage.append({"case_id": case_id, "draft_schema": "PASS", "compiled_source_exact_conformance": "PASS",
                             "semantic_graph_and_exact_evidence_round_trip": "PASS", "record_counts": counts})
    _assert(all(digest(p.read_bytes()) == h for p, h in before.items()), "PRIVATE_ARTIFACT_MUTATED")
    return {"task": "M4-04B3A", "status": "OFFLINE_FORENSICS_AND_REPRESENTATION_CHECK_PASS",
            "base_head": BASE_HEAD, "frozen_integrity": frozen,
            "historical_B2_status": b2["status"],
            "private_integrity": {"prediction_set_hashes": result["candidate_prediction_set_hashes"],
                                  "verified_terminal_predictions": 28, "verified_raw_responses": response_count,
                                  "verified_final_predictions": 6, "read_artifacts_unchanged": True,
                                  "manifest_sha256": public["private_prediction_manifest_sha256"],
                                  "final_evaluation_sha256": b2["evaluation"]["private_result_sha256"]},
            "forensics": {"method": "LOCKED_REPORTS_PLUS_INDEPENDENT_READ_ONLY_SHAPE_SOURCE_GRAPH_DIAGNOSTICS",
                          "counts_are_nonexclusive": True,
                          "category_case_counts": {c: terminal_counts[c] for c in CATEGORIES},
                          "diagnostic_occurrence_counts": dict(sorted(issue_counts.items())),
                          "locked_primary_issue_counts": dict(primary_issue_codes),
                          "locked_terminal_issue_counts": dict(terminal_issue_codes),
                          "copy_burden": {key: {"minimum": min(r[key] for r in copy_burdens),
                                               "maximum": max(r[key] for r in copy_burdens),
                                               "total": sum(r[key] for r in copy_burdens)}
                                          for key in copy_burdens[0]},
                          "rows": rows,
                          "unsupported_observed_in_locked_evaluation": 0,
                          "unsupported_not_assessable_for_L0_failed_cases": 26,
                          "semantic_missing_assertions_in_L0_valid_cases": 11},
            "DEV1_representation": {"status": "PASS", "cases": coverage, "record_totals": dict(totals),
                                    "comparison": "GRAPH_ALPHA_EQUIVALENCE_PLUS_EXACT_SOURCE_SPANS_EXCLUDING_MACHINE_METADATA",
                                    "fresh_validation": False, "data_role": "TUNING_DATA",
                                    "model_quality_measured": False},
            "boundaries": {"provider_calls": 0, "P0_P1_reruns": 0, "holdout_input_opened": False,
                           "holdout_gold_opened": False, "M4_04C_started": False, "M5_started": False,
                           "snapshot_semantics_changed": False}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(analyze(args.private_root, args.source_root), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
