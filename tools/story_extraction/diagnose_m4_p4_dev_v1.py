"""Offline, counts-only diagnosis of saved M4 DEV1/DEV2 prompt runs.

The private JSON retains assertion identities, never signatures, positions, raw
validator messages or source text. Public output contains aggregate counts only.
Evidence roles count once per distinct role on an unmatched assertion (including
all support sets); a saved role failure with several gold roles contributes one
pair per gold role. Recovery means proposition/polarity matching, as in Snapshot
V2, including required RefersTo assertions. It does not require correct grounding.

Temporary compiler/evaluator wrappers are restored in finally blocks. This CLI is
single-threaded; do not invoke its diagnostic functions concurrently in-process.
"""
from __future__ import annotations

import argparse
from itertools import combinations
import json
from pathlib import Path
import re
import tempfile
from typing import Callable, Mapping, Sequence

from tools.story_extraction import diagnose_m4_04b3i_fv1_v1 as frozen
from tools.story_extraction import draft_compiler_v1 as compiler
from tools.story_extraction import draft_compiler_v1_1 as compiler11
from tools.story_extraction import run_m4_p4_dev_v1 as runner

PRIVATE_NAME = "M4_P4_DEV_DIAGNOSIS_V1.json"
COMPLETENESS = ("COMPLETE_FOR_PROFILE", "UNCERTAIN")
KNOWN_TEMPLATES = {
    "event <id> anchor <id> is not an EVENT_TIME anchor of that event":
        "EVENT_ANCHOR_NOT_OWN_EVENT_TIME",
    "event <id> references unknown anchor <id>": "EVENT_UNKNOWN_ANCHOR",
    "anchor <id> references unknown event <id>": "ANCHOR_UNKNOWN_EVENT",
    "assertion <id> references unknown proposition <id>": "ASSERTION_UNKNOWN_PROPOSITION",
    "proposition embedding cycle through <id>": "PROPOSITION_EMBEDDING_CYCLE",
    "assertion <id> validity starts and ends at the same anchor": "VALIDITY_SAME_ANCHOR",
    "assertion <id> has no support path (needs a SUFFICIENT evidence set or a derivation)":
        "NO_SUPPORT_PATH",
    "assertion <id> has no complete support path (availability undefined)": "NO_COMPLETE_SUPPORT_PATH",
}
_IDS = re.compile(
    r"\b(?:draftv1-[\w.:-]+|d2-[\w.:-]+|[A-Z]+(?:_EXISTING_)?\d+|"
    r"(?=[\w.:-]*\d)[A-Za-z][\w.]*[-_:][\w.:-]+)\b"
)
_QUOTES = re.compile(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`[^`]*`|‘[^’]*’|“[^”]*”")
# These validator slots contain model-authored strings without quotation marks.
# Discard their values as well, including invalid predicates and token values.
_VALUE_TEMPLATES = (
    (r"event <id> has unregistered event_kind .+", "EVENT_KIND_UNREGISTERED"),
    (r"proposition <id> uses unregistered predicate .+", "PREDICATE_UNREGISTERED"),
    (r"proposition <id> uses forbidden stored verdict predicate .+", "FORBIDDEN_VERDICT_PREDICATE"),
    (r"proposition <id> arity mismatch for .+", "PREDICATE_ARITY_MISMATCH"),
    (r"proposition <id> .+ vocabulary .+ != .+", "ARGUMENT_VOCABULARY_MISMATCH"),
    (r"proposition <id> .+ stores forbidden verdict .+", "FORBIDDEN_VERDICT_VALUE"),
    (r"proposition <id> .+ value .+ not in .+", "ARGUMENT_TOKEN_NOT_IN_VOCABULARY"),
    (r"proposition <id> argument .+ references unknown .+", "ARGUMENT_UNKNOWN_REFERENCE"),
)


def issue_code(section: str, message: str) -> str:
    """Remove variable values, then shorten known canonical issue templates."""
    # Canonical issues are nested as 'reference_integrity: ...' by the batch validator.
    if section == "canonical" and ": " in message:
        section, message = message.split(": ", 1)
    message = _IDS.sub("<id>", message)
    message = _QUOTES.sub("<text>", message)
    message = re.sub(r"(?<![\w<])[-+]?\d+(?:\.\d+)?(?![\w>])", "<n>", message)
    message = " ".join(message.split())
    for pattern, code in _VALUE_TEMPLATES:
        if re.fullmatch(pattern, message):
            return f"{section}:{code}"
    return f"{section}:{KNOWN_TEMPLATES.get(message, message)}"


def structural_diagnosis(directory: Path, context) -> dict:
    """Recompile the last saved draft, capturing discarded canonical issues as codes."""
    path = next((directory / f"{phase}_draft.json" for phase in ("repair_1", "primary")
                 if (directory / f"{phase}_draft.json").is_file()), None)
    if path is None:
        return {"draft_phase": None, "codes": ["artifact:NO_SAVED_DRAFT"],
                "blockers": [], "validator_reports": []}
    draft = _read(path)
    blockers = list(compiler11.collect_draft_structural_blockers_v1_1(draft, context))
    reports = []
    original = compiler.validate_batch_guarded

    def capture(*args, **kwargs):
        report = original(*args, **kwargs)
        reports.append(report)
        return report

    compiler.validate_batch_guarded = capture
    try:
        compiler11.compile_story_extraction_draft_v1_1(draft, context)
    except compiler11.DraftCompilationErrorV1_1 as error:
        # The compiler can discover a later failure absent from the preliminary collector.
        blockers = sorted(set(blockers) | set(error.blockers))
    finally:
        compiler.validate_batch_guarded = original
    projected = [{"pass": report["pass"], "checks": {
        section: {"pass": check["pass"], "codes": [issue_code(section, issue)
                  for issue in check["issues"]]} for section, check in report["checks"].items()}}
        for report in reports]
    codes = [code for report in projected for check in report["checks"].values()
             for code in check["codes"]]
    # Do not count the compiler's summary of canonical failures again.
    codes += [issue_code(b.phase, b.code) for b in blockers
              if not (codes and b.phase == "CANONICAL_COMPILER")]
    return {"draft_phase": path.stem.removesuffix("_draft"), "codes": codes,
            "blockers": [{"phase": b.phase, "code": b.code} for b in blockers],
            "validator_reports": projected}


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _predicates(batch: Mapping, base: Mapping) -> dict[str, str]:
    # A placeholder proposition has no predicate of its own (Canonical Story v0).
    props = {p["id"]: p.get("predicate", "PLACEHOLDER") for p in
             [*base["propositions"], *batch["candidate_records"]["propositions"]]}
    return {a["id"]: props[a["proposition_id"]] for a in batch["candidate_records"]["assertions"]}


def valid_diagnosis(case, item: Mapping, predicted: dict, evaluation: Mapping) -> dict:
    """Adapt optional gold, literal variants and pending matches to the FV1 classifier."""
    base, gold = case.compiler_context.base_document, item["gold_batch"]
    literal_groups = frozen.ev._literal_groups
    groups = literal_groups(item)
    frozen.ev._literal_groups = lambda spec: groups
    try:
        diagnosis = frozen.case_diagnosis(base, gold, predicted)
    finally:
        frozen.ev._literal_groups = literal_groups
    predicates = _predicates(gold, base)
    optional = set(item.get("acceptable_optional_assertion_ids", item.get("acceptable_assertions", [])))
    required = predicates.keys() - optional
    diagnosis["missed"] = [m for m in diagnosis["missed"] if m["id"] in required]
    diagnosis["missed_resolutions"] = [m for m in diagnosis["missed_resolutions"] if m["id"] in required]
    # check_reproduction calls all unmatched predictions 'unsupported'. Snapshot V2
    # instead calls them pending on UNCERTAIN gold. Compare their mechanical total.
    counts = evaluation["counts"]
    unmatched = sum(counts.get(k, 0) for k in
                    ("unsupported", "pending_adjudication", "valid_additional", "out_of_scope"))
    frozen.check_reproduction(case.case_id, diagnosis, {**evaluation, "counts": {**counts, "unsupported": unmatched}})
    missed_ids = {m["id"] for key in ("missed", "missed_resolutions") for m in diagnosis[key]}
    recovered = required - missed_ids
    resolution_failures = sum(f["code"] == "MISSING_ENTITY_RESOLUTION" for f in evaluation["failures"])
    if (len(required) != counts["gold_required"] or len(recovered) != counts["required_recovered"]
            or len(diagnosis["missed_resolutions"]) != resolution_failures):
        raise frozen.DiagnosisError("Required recovery does not reproduce saved evaluation")
    evidence = {e["id"]: e for e in [*base["evidence_refs"], *predicted["candidate_records"]["evidence_refs"]]}
    assertions = {a["id"]: a for a in predicted["candidate_records"]["assertions"]}
    # Explicit allowlist: the classifier also returns source-bearing signatures/positions.
    result = {key: [{k: m[k] for k in ("id", "predicate", "class", "cause", "partner", "differing_arguments")
                    if k in m} for m in diagnosis[key]]
              for key in ("missed", "missed_resolutions", "unsupported")}
    for m in result["missed_resolutions"]:
        m["predicate"] = "RefersTo"
    for m in result["unsupported"]:
        m["evidence_roles"] = sorted({evidence[rid]["role"] for support in
            assertions[m["id"]]["support"]["evidence_sets"] for rid in support["evidence_ref_ids"]})
    result["recovered"] = [{"id": rid, "predicate": predicates[rid]} for rid in sorted(recovered)]
    return result


def _load_inputs(*, dataset, variant, selected, input_root, dev2_input, dev2_gold,
                 dev1_package, dev1_ingestion_manifest, dev1_source_root):
    """Use exactly the runner's package verification and dataset loaders."""
    if dataset == "DEV1":
        if any(p is None for p in (dev1_package, dev1_ingestion_manifest, dev1_source_root)):
            raise runner.DevelopmentError("DEV1 requires package, ingestion manifest and source root")
        if runner.protocol.file_sha256(dev1_package) != runner.DEV1_SHA256:
            raise runner.DevelopmentError("DEV1 archive hash mismatch")
        return runner.load_dev1_cases(dev1_package, input_root, selected, dev1_ingestion_manifest,
                                      dev1_source_root, variant)
    if dev2_input is None or dev2_gold is None:
        raise runner.DevelopmentError("DEV2 requires input and gold archives")
    runner.verify_packages(dev2_input, dev2_gold)
    return (runner.load_cases(dev2_input, input_root, selected, variant=variant),
            runner.read_gold(dev2_gold, selected))


def diagnose(*, dataset: str, variants: Sequence[str], output_root: Path, output_directory: Path,
             dev2_input: Path | None = None, dev2_gold: Path | None = None,
             dev1_package: Path | None = None, dev1_ingestion_manifest: Path | None = None,
             dev1_source_root: Path | None = None, cases: Sequence[str] | None = None,
             input_loader: Callable = _load_inputs) -> dict:
    """Read saved runs; input_loader(**dataset arguments) -> (cases, gold) is the test seam."""
    selected = runner.selected_cases(cases, dataset)
    if (len(variants) < 2 or len(set(variants)) != len(variants)
            or any(re.fullmatch(r"P[0-9A-Z]+", v) is None for v in variants)):
        raise runner.DevelopmentError("Supply at least two distinct prompt variants")
    record = {"dataset": dataset, "variants": {}}
    for variant in variants:
        root = (Path(output_root) / "DEV1" if dataset == "DEV1" else Path(output_root)) / variant
        score = _read(root / "score.json")
        rows = {r["case_id"]: r for r in score["rows"]}
        if len(rows) != len(score["rows"]) or not set(selected) <= rows.keys():
            raise runner.DevelopmentError("Saved score case identity mismatch")
        with tempfile.TemporaryDirectory() as tmp:
            loaded, gold = input_loader(dataset=dataset, variant=variant, selected=selected, input_root=Path(tmp),
                dev2_input=dev2_input, dev2_gold=dev2_gold, dev1_package=dev1_package,
                dev1_ingestion_manifest=dev1_ingestion_manifest, dev1_source_root=dev1_source_root)
            by_id = {c.case_id: c for c in loaded}
            if len(by_id) != len(loaded) or not set(selected) <= by_id.keys() or not set(selected) <= gold.keys():
                raise runner.DevelopmentError("Loaded case identity mismatch")
            details = {}
            for cid in selected:
                row, item = rows[cid], gold[cid]
                completeness = item["gold_completeness"]
                if completeness not in COMPLETENESS:
                    raise runner.DevelopmentError("Unknown gold completeness")
                evaluation = row["evaluation"]
                detail = {"completeness": completeness, "structurally_valid":
                          row["terminal_status"] == "STRUCTURAL_VALID", "role_pairs": []}
                for failure in evaluation.get("failures", []):
                    if failure["code"] == "WRONG_EVIDENCE_ROLE":
                        detail["role_pairs"].extend({"gold": role, "predicted": failure["predicted"]}
                            for role in sorted(set(failure["gold"])))
                directory = root / "artifacts" / cid
                if detail["structurally_valid"]:
                    detail.update(valid_diagnosis(by_id[cid], item, _read(directory / "compiled_batch.json"), evaluation))
                else:
                    detail["structural"] = structural_diagnosis(directory, by_id[cid].compiler_context)
                details[cid] = detail
            record["variants"][variant] = details
    # Require identical completeness labels for a meaningful paired comparison.
    for cid in selected:
        if len({record["variants"][v][cid]["completeness"] for v in variants}) != 1:
            raise runner.DevelopmentError("Variant gold completeness mismatch")
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    (output_directory / PRIVATE_NAME).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def _increment(out: dict, path: Sequence[str], amount: int = 1) -> None:
    for key in path[:-1]:
        out = out.setdefault(key, {})
    out[path[-1]] = out.get(path[-1], 0) + amount


def _aggregate(details) -> dict:
    out = {"cases": 0, "structurally_valid": 0, "structural_failures": 0,
           **{key: {} for key in ("structural_codes", "missed_by_class", "missed_by_cause",
           "missed_resolutions_by_class", "unmatched_by_class", "missed_by_class_predicate",
           "missed_by_cause_predicate", "missed_resolutions_by_class_predicate", "unmatched_by_class_predicate",
           "unmatched_by_predicate", "no_gold_by_predicate", "no_gold_by_role",
           "no_gold_by_predicate_role", "role_pairs")}}
    for detail in details:
        out["cases"] += 1
        valid = detail["structurally_valid"]
        out["structurally_valid" if valid else "structural_failures"] += 1
        for code in detail.get("structural", {}).get("codes", []):
            _increment(out, ("structural_codes", code))
        for pair in detail["role_pairs"]:
            _increment(out, ("role_pairs", pair["gold"], pair["predicted"]))
        for key, label in (("missed", "missed"), ("missed_resolutions", "missed_resolutions"), ("unsupported", "unmatched")):
            for m in detail.get(key, []):
                _increment(out, (label + "_by_class", m["class"]))
                _increment(out, (label + "_by_class_predicate", m["class"], m["predicate"]))
                if key == "missed":
                    _increment(out, ("missed_by_cause", m["cause"]))
                    _increment(out, ("missed_by_cause_predicate", m["cause"], m["predicate"]))
                if key == "unsupported":
                    _increment(out, ("unmatched_by_predicate", m["predicate"]))
                    if m["class"] == "NO_GOLD_ON_EVIDENCE":
                        _increment(out, ("no_gold_by_predicate", m["predicate"]))
                        for role in m["evidence_roles"]:
                            _increment(out, ("no_gold_by_role", role))
                            _increment(out, ("no_gold_by_predicate_role", m["predicate"], role))
    return out


def _paired(a: Mapping, b: Mapping, completeness: str | None) -> dict:
    out = {"cases_valid_in_both": 0, "required_recovered_a": 0, "required_recovered_b": 0,
           "a_only_by_predicate": {}, "b_only_by_predicate": {}, "both_by_predicate": {}}
    for cid in a.keys() & b.keys():
        left, right = a[cid], b[cid]
        if (not left["structurally_valid"] or not right["structurally_valid"]
                or completeness is not None and left["completeness"] != completeness):
            continue
        out["cases_valid_in_both"] += 1
        aa = {r["id"]: r["predicate"] for r in left["recovered"]}
        bb = {r["id"]: r["predicate"] for r in right["recovered"]}
        out["required_recovered_a"] += len(aa)
        out["required_recovered_b"] += len(bb)
        for key, ids, predicates in (("a_only_by_predicate", aa.keys() - bb.keys(), aa),
                                    ("b_only_by_predicate", bb.keys() - aa.keys(), bb),
                                    ("both_by_predicate", aa.keys() & bb.keys(), aa)):
            for rid in ids:
                _increment(out, (key, predicates[rid]))
    return out


def public_record(record: Mapping) -> dict:
    """Project private case details to counts; no case or record identities are keys."""
    variants = record["variants"]
    out = {"variants": {}, "paired": {}}
    for variant, cases in variants.items():
        out["variants"][variant] = {"all": _aggregate(cases.values()), "by_completeness": {
            label: _aggregate(d for d in cases.values() if d["completeness"] == label)
            for label in COMPLETENESS}}
    for a, b in combinations(variants, 2):
        out["paired"][f"{a}__{b}"] = {"all": _paired(variants[a], variants[b], None), "by_completeness": {
            label: _paired(variants[a], variants[b], label) for label in COMPLETENESS}}
    return {record["dataset"]: out}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=("DEV1", "DEV2"), required=True)
    parser.add_argument("--variants", type=lambda s: s.split(","), required=True)
    for name in ("output-root", "output-directory", "dev2-input", "dev2-gold", "dev1-package",
                 "dev1-ingestion-manifest", "dev1-source-root"):
        parser.add_argument("--" + name, type=Path, required=name.startswith("output-"))
    parser.add_argument("--cases", type=lambda s: s.split(","))
    args = parser.parse_args(argv)
    try:
        result = diagnose(**vars(args))
        print(json.dumps(public_record(result), sort_keys=True))
    except (runner.DevelopmentError, frozen.DiagnosisError, OSError, ValueError, KeyError) as error:
        # Exception messages can include private input values.
        print(f"M4_P4_DEV_DIAGNOSIS_STOPPED: {type(error).__name__}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
