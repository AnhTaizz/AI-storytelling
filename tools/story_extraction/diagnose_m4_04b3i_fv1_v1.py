"""M4-04B3I: why the Draft V1.1 extractor missed required FV1 assertions, and what its
unmatched predictions are. FV1 is development data since M4-04B3H opened its gold.

For every case it rebuilds the frozen Snapshot V2 alignment (`evaluate_extraction_v0`
internals, unchanged), checks that the rebuilt matching reproduces the M4-04B3H counts, and
gives each item one mechanical class:

Missed required assertions (RefersTo misses are MISSING_ENTITY_RESOLUTION and are counted apart):
- REFERENT_MISMATCH   a prediction with the same predicate cites overlapping evidence, but an
                      entity/event/anchor argument differs or did not align;
- VALUE_MISMATCH      same predicate and overlapping evidence; referents agree, a token, literal,
                      mention or nested proposition differs;
- POLARITY_MISMATCH   the same proposition was predicted with the other polarity;
- OTHER_PREDICATE     the evidence was used, but only by predictions with other predicates;
- NOT_EXTRACTED       no prediction cites overlapping evidence.

Missed RefersTo (MISSING_ENTITY_RESOLUTION): MENTION_SPAN_DIFFERS (a predicted RefersTo covers
an overlapping but different mention), ENTITY_DIFFERS (same mention, another entity) or
NOT_EXTRACTED.

Unmatched predictions:
- PAIRED_WITH_MISSED_RESOLUTION  a RefersTo on the evidence of a missed gold RefersTo;
- PAIRED_WITH_MISS    same predicate and overlapping evidence as a missed gold assertion (the
                      other half of a REFERENT/VALUE mismatch, so not an invention as such);
- ON_GOLD_EVIDENCE    overlaps the evidence of some gold assertion, with another predicate;
- NO_GOLD_ON_EVIDENCE no gold assertion cites overlapping evidence: either a gold gap or an
                      invention, which only a reader of the source can tell (manual review).

No model call. The per-item output carries private evidence and is written under .local;
`public_record` keeps counts only.

    python -m tools.story_extraction.diagnose_m4_04b3i_fv1_v1 --fv1-directory <dir> \\
        --prediction-directory <dir> --scoring-directory <dir> --output-directory <dir>
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from tools.story_extraction import evaluate_extraction_v0 as ev

MISSED_CLASSES = ("REFERENT_MISMATCH", "VALUE_MISMATCH", "POLARITY_MISMATCH", "OTHER_PREDICATE", "NOT_EXTRACTED")
UNSUPPORTED_CLASSES = ("PAIRED_WITH_MISSED_RESOLUTION", "PAIRED_WITH_MISS", "ON_GOLD_EVIDENCE", "NO_GOLD_ON_EVIDENCE")
RESOLUTION_CLASSES = ("MENTION_SPAN_DIFFERS", "ENTITY_DIFFERS", "NOT_EXTRACTED")
REFERENT_KINDS = ("ENTITY", "EVENT", "ANCHOR")


class DiagnosisError(RuntimeError):
    pass


def _parts(signature: str) -> Tuple[str, Dict[str, Tuple[str, str]]]:
    """(predicate, {argument: (kind, value as JSON)}) from an evaluator signature."""
    data = json.loads(signature)
    if data[0] == "PLACEHOLDER":
        return "PLACEHOLDER", {}
    return data[0], {name: (kind, json.dumps(value, ensure_ascii=False, sort_keys=True))
                     for name, kind, value in data[1]}


def _overlaps(a: Iterable, b: Iterable) -> bool:
    return any(ev._overlap(x, y) for x in a for y in b)


def _positions(view: Any, assertion: Mapping[str, Any]) -> List[str]:
    out = []
    for evidence_set in assertion["support"]["evidence_sets"]:
        for ref_id in evidence_set["evidence_ref_ids"]:
            display = view.by_id["evidence_refs"][ref_id].get("position", {}).get("display")
            if display and display not in out:
                out.append(display)
    return out


MISS_CAUSES = ("NAMING_NOT_EMITTED", "EVENT_NOT_ALIGNED", "ROLE_LABEL", "LITERAL_WORDING", "MISSING_PARTICIPANT",
               "TEMPORAL_STRUCTURE", "OTHER_OMISSION")
TEMPORAL_PREDICATES = ("AnchorDate", "TemporalRelation")


def miss_cause(predicate: str, cls: str, differing: Sequence[str], gold_args: Mapping[str, Tuple[str, str]],
               partner_args: Mapping[str, Tuple[str, str]], partner_matched: bool = False) -> str:
    """The likely cause of one missed assertion, by fixed rules applied in this order:
    an unaligned event argument (one event's kind differs, so every assertion about it
    misses); a differing literal (wording or language of a value); only the participant
    role differs; another participant of the same event that was never asserted (the
    nearest prediction is a different, matched participation); a temporal predicate; a name
    never asserted (NamedAs); anything else."""
    if cls in ("REFERENT_MISMATCH", "VALUE_MISMATCH"):
        if any(partner_args.get(n, ("", ""))[1].startswith('"?') and gold_args.get(n, ("",))[0] == "EVENT"
               for n in differing):
            return "EVENT_NOT_ALIGNED"
        if any(gold_args.get(n, ("",))[0] == "LITERAL" for n in differing):
            return "LITERAL_WORDING"
        if list(differing) == ["role"]:
            return "ROLE_LABEL"
        if partner_matched and predicate == "Participates":
            return "MISSING_PARTICIPANT"
    if predicate in TEMPORAL_PREDICATES:
        return "TEMPORAL_STRUCTURE"
    if predicate == "NamedAs":
        return "NAMING_NOT_EMITTED"
    return "OTHER_OMISSION"


def case_diagnosis(base_document: Dict[str, Any], gold_batch: Dict[str, Any],
                   predicted_batch: Dict[str, Any]) -> Dict[str, Any]:
    """Missed required and unmatched predicted assertions of one case, each with its class."""
    registry = ev.load_registry()
    gold = ev._View(ev.merge(gold_batch, base_document), gold_batch["candidate_records"], registry)
    pred = ev._View(ev.merge(predicted_batch, base_document), predicted_batch["candidate_records"], registry)
    base_ids = {r["id"] for name in ev.CANDIDATE_COLLECTIONS for r in base_document[name]}
    align = ev._Alignment(gold, pred, base_ids, ev._literal_groups({}))
    gold_as = [a for a in gold.assertions if a["id"] in gold.candidate_ids["assertions"]]
    pred_as = [a for a in pred.assertions if a["id"] in pred.candidate_ids["assertions"]]

    def info(view, a, translate):
        signature = align.signature(view, a["proposition_id"], translate)
        predicate, args = _parts(signature)
        return {"id": a["id"], "predicate": predicate, "polarity": a["polarity"], "signature": signature,
                "args": args, "spans": view.spans(a["support"]), "positions": _positions(view, a),
                "epistemic_status": a["epistemic_status"]}

    golds = [info(gold, a, False) for a in gold_as]
    preds = [info(pred, a, True) for a in pred_as]
    by_key: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for g in golds:
        by_key.setdefault((g["signature"], g["polarity"]), []).append(g)
    matched, unmatched = set(), []
    for p in preds:
        candidates = by_key.get((p["signature"], p["polarity"]))
        if candidates:
            open_ones = [c for c in candidates if c["id"] not in matched]
            matched.add((open_ones or candidates)[0]["id"])
        elif not align.is_reflexive_identity(pred, next(a for a in pred_as if a["id"] == p["id"])["proposition_id"], True):
            unmatched.append(p)
    missed = [g for g in golds if g["id"] not in matched and g["predicate"] != "RefersTo"]
    unmatched_ids = {p["id"] for p in unmatched}

    def differing(g, p):
        names = sorted(set(g["args"]) | set(p["args"]))
        return [n for n in names if g["args"].get(n) != p["args"].get(n)]

    missed_out = []
    for g in missed:
        same = [p for p in preds if p["predicate"] == g["predicate"] and _overlaps(p["spans"], g["spans"])]
        if any(p["signature"] == g["signature"] and p["polarity"] != g["polarity"] for p in preds):
            cls, partner, diff = "POLARITY_MISMATCH", None, []
        elif same:
            partner = min(same, key=lambda p: (len(differing(g, p)), p["id"]))
            diff = differing(g, partner)
            kinds = {(g["args"].get(n) or partner["args"].get(n))[0] for n in diff}
            cls = "REFERENT_MISMATCH" if kinds & set(REFERENT_KINDS) else "VALUE_MISMATCH"
            partner = partner["id"]
        elif any(_overlaps(p["spans"], g["spans"]) for p in preds):
            cls, partner, diff = "OTHER_PREDICATE", None, []
        else:
            cls, partner, diff = "NOT_EXTRACTED", None, []
        partner_args = next((p["args"] for p in preds if p["id"] == partner), {})
        missed_out.append({"id": g["id"], "predicate": g["predicate"], "class": cls, "partner": partner,
                           "cause": miss_cause(g["predicate"], cls, diff, g["args"], partner_args,
                                               partner is not None and partner not in unmatched_ids),
                           "differing_arguments": diff, "positions": g["positions"],
                           "epistemic_status": g["epistemic_status"], "signature": g["signature"]})
    # RefersTo misses (MISSING_ENTITY_RESOLUTION) are counted apart, but a predicted RefersTo on
    # the same mention is their other half: say whether the mention span or the entity differs.
    missed_resolutions = [g for g in golds if g["id"] not in matched and g["predicate"] == "RefersTo"]
    resolutions_out = []
    for g in missed_resolutions:
        same = [p for p in preds if p["predicate"] == "RefersTo" and _overlaps(p["spans"], g["spans"])]
        if not same:
            cls = "NOT_EXTRACTED"
        elif any(p["args"].get("mention") == g["args"].get("mention") for p in same):
            cls = "ENTITY_DIFFERS"
        else:
            cls = "MENTION_SPAN_DIFFERS"
        resolutions_out.append({"id": g["id"], "class": cls, "positions": g["positions"]})
    paired = {m["partner"] for m in missed_out if m["partner"]}
    unsupported_out = []
    for p in unmatched:
        if p["predicate"] == "RefersTo" and any(_overlaps(p["spans"], g["spans"]) for g in missed_resolutions):
            cls = "PAIRED_WITH_MISSED_RESOLUTION"
        elif p["id"] in paired or any(p["predicate"] == g["predicate"] and _overlaps(p["spans"], g["spans"])
                                      for g in missed):
            cls = "PAIRED_WITH_MISS"
        elif any(_overlaps(p["spans"], g["spans"]) for g in golds):
            cls = "ON_GOLD_EVIDENCE"
        else:
            cls = "NO_GOLD_ON_EVIDENCE"
        unsupported_out.append({"id": p["id"], "predicate": p["predicate"], "class": cls, "positions": p["positions"],
                                "epistemic_status": p["epistemic_status"], "signature": p["signature"],
                                "content_key": f"{p['signature']}|{p['polarity']}"})
    return {"missed": missed_out, "unsupported": unsupported_out, "missed_resolutions": resolutions_out}


def check_reproduction(case_id: str, diagnosis: Mapping[str, Any], evaluation: Mapping[str, Any]) -> None:
    """The rebuilt matching must give the M4-04B3H counts, or the classes mean nothing."""
    codes = Counter(f["code"] for f in evaluation["failures"])
    unsupported = evaluation.get("counts", {}).get("unsupported", 0)
    if len(diagnosis["missed"]) != codes["MISSED_REQUIRED_ASSERTION"] or len(diagnosis["unsupported"]) != unsupported:
        raise DiagnosisError(f"{case_id}: rebuilt matching does not reproduce M4-04B3H "
                             f"({len(diagnosis['missed'])}/{codes['MISSED_REQUIRED_ASSERTION']} missed, "
                             f"{len(diagnosis['unsupported'])}/{unsupported} unsupported)")


def public_record(cases: Mapping[str, Mapping[str, Any]],
                  adjudications: Optional[Mapping[str, Mapping[str, Any]]] = None) -> Dict[str, Any]:
    """Counts only: classes per case, predicates per class, and (when given) the manual
    adjudication of the unmatched predictions by state and severity."""
    out: Dict[str, Any] = {"per_case": {}, "missed_by_class": Counter(), "unsupported_by_class": Counter(),
                           "missed_resolutions_by_class": Counter(), "missed_by_cause": Counter(),
                           "missed_predicates_by_class": {}, "unsupported_predicates_by_class": {}}
    for case_id, diagnosis in cases.items():
        out["per_case"][case_id] = {
            "missed": dict(Counter(m["class"] for m in diagnosis["missed"])),
            "unsupported": dict(Counter(u["class"] for u in diagnosis["unsupported"])),
            "missed_resolutions": dict(Counter(r["class"] for r in diagnosis.get("missed_resolutions", [])))}
        for r in diagnosis.get("missed_resolutions", []):
            out["missed_resolutions_by_class"][r["class"]] += 1
        out["per_case"][case_id]["missed_causes"] = dict(Counter(m["cause"] for m in diagnosis["missed"]))
        for m in diagnosis["missed"]:
            out["missed_by_cause"][m["cause"]] += 1
            out["missed_by_class"][m["class"]] += 1
            out["missed_predicates_by_class"].setdefault(m["class"], Counter())[m["predicate"]] += 1
        for u in diagnosis["unsupported"]:
            out["unsupported_by_class"][u["class"]] += 1
            out["unsupported_predicates_by_class"].setdefault(u["class"], Counter())[u["predicate"]] += 1
    if adjudications is not None:
        states, severities = Counter(), Counter()
        for entry in adjudications.values():
            states[entry["state"]] += 1
            if entry["state"] == "UNSUPPORTED_ASSERTION":
                severities[entry["severity"]] += 1
        out["adjudication"] = {"states": dict(states), "unsupported_severity": dict(severities)}
    out["missed_by_class"] = {k: out["missed_by_class"][k] for k in MISSED_CLASSES if out["missed_by_class"][k]}
    out["unsupported_by_class"] = {k: out["unsupported_by_class"][k] for k in UNSUPPORTED_CLASSES
                                   if out["unsupported_by_class"][k]}
    out["missed_by_cause"] = {k: out["missed_by_cause"][k] for k in MISS_CAUSES if out["missed_by_cause"][k]}
    out["missed_resolutions_by_class"] = {k: out["missed_resolutions_by_class"][k] for k in RESOLUTION_CLASSES
                                          if out["missed_resolutions_by_class"][k]}
    for key in ("missed_predicates_by_class", "unsupported_predicates_by_class"):
        out[key] = {cls: dict(sorted(c.items())) for cls, c in sorted(out[key].items())}
    return out


def diagnose(fv1_directory: Path, prediction_directory: Path, scoring_directory: Path,
             output_directory: Path, load_cases=None) -> Dict[str, Any]:
    from tools.story_extraction import score_m4_04b3h_fv1_v1 as scoring
    if load_cases is None:
        from tools.story_extraction.fresh_validation_seal_v1 import load_input_cases as load_cases
    evaluation = json.loads((Path(scoring_directory) / f"{scoring.EVALUATION_ID}.json").read_text(encoding="utf-8"))
    gold = scoring.read_gold(Path(fv1_directory) / scoring.GOLD_NAME)
    contexts = {row["case_id"]: row for row in load_cases(Path(fv1_directory) / scoring.INPUT_NAME)}
    cases = {}
    for row in evaluation["rows"]:
        cid = row["case_id"]
        if row["terminal_status"] != "STRUCTURAL_VALID":
            continue
        compiled = json.loads((Path(prediction_directory) / "artifacts" / "compiled" / f"{cid}.json").read_text(
            encoding="utf-8"))
        diagnosis = case_diagnosis(contexts[cid]["base_document"], gold[cid]["gold_batch"], compiled)
        check_reproduction(cid, diagnosis, row["evaluation"])
        cases[cid] = diagnosis
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    (output_directory / "M4_04B3I_FV1_DIAGNOSIS_ITEMS_V1.json").write_text(
        json.dumps(cases, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return cases


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("fv1-directory", "prediction-directory", "scoring-directory", "output-directory"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--adjudications", type=Path, help="private manual adjudication JSON (content_key -> entry)")
    args = parser.parse_args(argv)
    try:
        cases = diagnose(args.fv1_directory, args.prediction_directory, args.scoring_directory, args.output_directory)
    except DiagnosisError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    adjudications = json.loads(args.adjudications.read_text(encoding="utf-8")) if args.adjudications else None
    print(json.dumps(public_record(cases, adjudications), ensure_ascii=False, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
