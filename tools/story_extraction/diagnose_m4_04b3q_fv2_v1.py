"""Diagnose a scored FV2 run offline after verifying its locks and gold-access record.

The public report contains aggregate counts with fixed categorical labels.
The items file is private and includes assertion IDs and unmatched content keys.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from zipfile import BadZipFile

from tools.story_extraction import diagnose_m4_04b3i_fv1_v1 as fv1
from tools.story_extraction import evaluate_extraction_v0 as ev
from tools.story_extraction import m4_04b3n_fv2_protocol_v1 as lock
from tools.story_extraction import score_m4_04b3p_fv2_v1 as scorer

ITEMS_NAME = "M4_04B3Q_FV2_DIAGNOSIS_ITEMS_V1.json"
PUBLIC_NAME = "M4_04B3Q_FV2_DIAGNOSIS_PUBLIC_V1.json"
VALID = "STRUCTURAL_VALID"
NO_PREDICATE = "NO_PREDICATE"
NO_GOLD_ROLE = "NO_GOLD_EVIDENCE_ROLE"

# These are the independent layer checks in the scorer's shared _summary.
LAYER_CODES = {
    "L0": {"CANONICAL_CONFORMANCE_FAILURE"},
    "L1": {"WRONG_EVIDENCE_SPAN", "WRONG_EVIDENCE_ROLE", "INSUFFICIENT_SUPPORT_MARKED_SUFFICIENT"},
    "L2": {"WRONG_POLARITY", "EPISTEMIC_OVERSTATEMENT", "EPISTEMIC_UNDERSTATEMENT",
           "WRONG_VALIDITY_BOUND", "INVENTED_CAUSALITY", "HOLDER_RELATIVE_TRUTH_LEAK"},
    "L3": {"WRONG_ENTITY_RESOLUTION", "MISSING_ENTITY_RESOLUTION", "WRONG_EVENT_GRANULARITY"},
    "L4": {"MISSED_REQUIRED_ASSERTION", "MISSING_ENTITY_RESOLUTION"},
}
UNMATCHED_HINTS = {"WRONG_POLARITY", "HOLDER_RELATIVE_TRUTH_LEAK", "INVENTED_CAUSALITY",
                   "WRONG_ENTITY_RESOLUTION", "UNSUPPORTED_ASSERTION"}

DiagnosisError = fv1.DiagnosisError


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DiagnosisError(message)


def _matched_pairs(base, gold_batch, predicted_batch):
    """Return the evaluator's nonduplicate candidate matches in prediction order."""
    registry = ev.load_registry()
    gold = ev._View(ev.merge(gold_batch, base), gold_batch["candidate_records"], registry)
    pred = ev._View(ev.merge(predicted_batch, base), predicted_batch["candidate_records"], registry)
    base_ids = {r["id"] for name in ev.CANDIDATE_COLLECTIONS for r in base[name]}
    align = ev._Alignment(gold, pred, base_ids, ev._literal_groups({}))
    available = defaultdict(list)
    for assertion in gold.assertions:
        if assertion["id"] in gold.candidate_ids["assertions"]:
            key = (align.signature(gold, assertion["proposition_id"], False), assertion["polarity"])
            available[key].append(assertion)
    pairs = []
    for assertion in pred.assertions:
        if assertion["id"] not in pred.candidate_ids["assertions"]:
            continue
        key = (align.signature(pred, assertion["proposition_id"], True), assertion["polarity"])
        candidates = available[key]
        if candidates:
            validity = align.validity(pred, assertion, True)
            match = next((g for g in candidates if align.validity(gold, g, False) == validity), candidates[0])
            candidates.remove(match)
            pairs.append((match, assertion))
    return gold, pred, align, pairs


def _span_class(predicted, gold):
    if predicted == gold:
        return "EXACT"
    if not predicted or not gold:
        # The evidence-set count delta describes one-sided direct evidence.
        return None
    if ev._set_relation(predicted, gold, frozenset()) == "MATCH":
        return "PRED_WIDER"
    if ev._set_relation(gold, predicted, frozenset()) == "MATCH":
        return "PRED_NARROWER"
    if any(ev._overlap(p, g) for p in predicted for g in gold):
        return "PARTIAL_OVERLAP"
    if {p[0] for p in predicted} & {g[0] for g in gold}:
        return "NO_OVERLAP_SAME_PASSAGE"
    return "OTHER_PASSAGE"


def _premise_keys(view, support, align, translate):
    return {
        (d["rule_id"], frozenset(
            (align.signature(view, a["proposition_id"], translate), a["polarity"])
            for a in (view.by_id["assertions"][aid] for aid in d["premise_assertion_ids"])
        ))
        for d in support["derivations"]
    }


def grounding_diagnosis(base, gold_batch, predicted_batch, evaluation):
    """Describe each pair's sufficient spans and reproduce the scorer's grounding count.

    Geometry compares the union of sufficient spans. Set-count differences add one
    class per pair. Grounding retains the evaluator's alternative sets, exact-only
    rule in mixed-role segments and derivation equivalence.
    """
    gold, pred, align, pairs = _matched_pairs(base, gold_batch, predicted_batch)
    roles_by_segment = defaultdict(set)
    for ref in gold.doc["evidence_refs"]:
        roles_by_segment[ref["segment_id"]].add(ref["role"])
    narrow = frozenset(segment for segment, roles in roles_by_segment.items() if len(roles) > 1)
    _require(len(narrow) == evaluation["narrow_span_segments"], "Narrow span segment count mismatch")
    items = []
    for g, p in pairs:
        gs, ps = g["support"], p["support"]
        gold_sets, pred_sets = gold.sufficient_sets(gs), pred.sufficient_sets(ps)
        relation = _span_class(frozenset().union(*pred_sets), frozenset().union(*gold_sets))
        classes = [relation] if relation else []
        if len(gold_sets) > len(pred_sets):
            classes.append("MISSING_GOLD_EVIDENCE_SET")
        if len(pred_sets) > len(gold_sets):
            classes.append("EXTRA_PREDICTED_EVIDENCE_SET")
        grounded = any(ev._set_relation(pset, gset, narrow) == "MATCH"
                       for pset in pred_sets for gset in gold_sets)
        if not grounded:
            grounded = bool(_premise_keys(pred, ps, align, True) & _premise_keys(gold, gs, align, False))
        roles = {gold.by_id["evidence_refs"][rid]["role"]
                 for evidence_set in gs["evidence_sets"] if evidence_set["label"] == "SUFFICIENT"
                 for rid in evidence_set["evidence_ref_ids"]}
        items.append({"gold_id": g["id"], "prediction_id": p["id"],
                      "predicate": gold.proposition(g).get("predicate", NO_PREDICATE),
                      "classes": classes, "gold_evidence_roles": sorted(roles),
                      "gold_sufficient_sets": len(gold_sets), "predicted_sufficient_sets": len(pred_sets),
                      "grounded": grounded})
    counts = evaluation["counts"]
    _require(len(items) == counts["matched_predictions"], "Matched prediction count mismatch")
    _require(sum(item["grounded"] for item in items) == counts["grounded"], "Grounded prediction count mismatch")
    return items


def _evaluation_details(evaluation, predicates):
    failures = []
    for failure in evaluation["failures"]:
        code, material = failure["code"], failure["material"]
        predicate = failure.get("predicate") or NO_PREDICATE
        _require(code in ev.FAILURE_CODES and predicate in predicates and type(material) is bool,
                 "Invalid failure category")
        layers = [layer for layer, codes in LAYER_CODES.items() if code in codes]
        if material:
            layers.append("L5")
        failures.append({"code": code, "predicate": predicate, "layers": layers or ["NON_BLOCKING"]})
    _require({f["code"] for f in failures} == set(evaluation["failure_codes"]), "Failure code list mismatch")
    failed = {layer for f in failures for layer in f["layers"]}
    if not evaluation["l0_structural_validity"]:
        first = "L0"
    else:
        first = next((layer for layer in ("L1", "L2", "L3", "L4") if layer in failed),
                     "NONE" if evaluation["full_canonical_case_success"] is True else "L5")
    unmatched = []
    for entry in evaluation["unmatched_predictions"]:
        predicate = entry["predicate"] or NO_PREDICATE
        state, hint = entry["state"], entry["mechanical_hint"]
        _require(predicate in predicates and state in (*ev.ADJUDICATION_STATES, ev.PENDING)
                 and hint in UNMATCHED_HINTS, "Invalid unmatched prediction category")
        unmatched.append({"predicate": predicate, "state": state, "mechanical_hint": hint,
                          "content_key": entry["content_key"]})
    return {"first_failing_layer": first, "failures": failures, "unmatched_predictions": unmatched}


def _public_record(cases):
    public = fv1.public_record({cid: case for cid, case in cases.items() if "missed" in case})
    del public["per_case"]
    grounding = {"by_class": Counter(), "by_predicate": defaultdict(Counter),
                 "by_gold_evidence_role": defaultdict(Counter), "matched_pairs": 0, "grounded_pairs": 0}
    layers = {"by_layer": defaultdict(Counter), "by_predicate": defaultdict(Counter)}
    unsupported = {f"by_{key}": Counter() for key in ("state", "mechanical_hint", "predicate")}
    first_layers = Counter()
    for case in cases.values():
        first_layers[case["first_failing_layer"]] += 1
        for pair in case.get("grounding", ()):
            grounding["matched_pairs"] += 1
            grounding["grounded_pairs"] += pair["grounded"]
            grounding["by_class"].update(pair["classes"])
            grounding["by_predicate"][pair["predicate"]].update(pair["classes"])
            for role in pair["gold_evidence_roles"] or [NO_GOLD_ROLE]:
                grounding["by_gold_evidence_role"][role].update(pair["classes"])
        for failure in case["failures"]:
            for layer in failure["layers"]:
                layers["by_layer"][layer][failure["code"]] += 1
            layers["by_predicate"][failure["predicate"]][failure["code"]] += 1
        for entry in case["unmatched_predictions"]:
            for key in ("state", "mechanical_hint", "predicate"):
                unsupported[f"by_{key}"][entry[key]] += 1
    return {**public, "grounding": grounding, "layer_blocking": layers, "unsupported": unsupported,
            "first_failing_layer": first_layers}


def diagnose(*, fv2_directory: Path, prediction_directory: Path, scoring_directory: Path,
             output_directory: Path, protocol_path: Path, protocol_sha256: str,
             prediction_lock_sha256: str) -> dict:
    validated = lock.validate_protocol_file(protocol_path, protocol_sha256)
    predictions, record = scorer.verify_prediction_lock(prediction_directory, prediction_lock_sha256, protocol_sha256)
    access = scorer.shared._load(scoring_directory / scorer.ACCESS_NAME)
    _require(access["artifact"] == scorer.ACCESS_NAME[:-5]
             and access["prediction_lock_sha256"] == prediction_lock_sha256
             and access["chronology"] == "ALL_LOCKS_AND_PACKAGE_HASHES_VERIFIED_BEFORE_GOLD_OPEN"
             and access["provider_operations_after_gold_open"] == 0, "Scorer gold-access record mismatch")
    evaluation = scorer.shared._load(scoring_directory / f"{scorer.EVALUATION_ID}.json")
    expected = {"artifact": scorer.EVALUATION_ID, "access": access, "protocol_sha256": protocol_sha256,
                "prediction_lock_sha256": prediction_lock_sha256, "gold_sha256": lock.FV2_GOLD_SHA256,
                "prediction_set_sha256": record["prediction_set_sha256"],
                "snapshot_v2_sha256": lock.fv1.SNAPSHOT_V2_SHA256}
    _require(all(evaluation.get(key) == value for key, value in expected.items()), "Scorer evaluation binding mismatch")
    rows = evaluation["rows"]
    identity_fields = ("case_id", "terminal_status", "repair_used")
    _require([tuple(row[k] for k in identity_fields) for row in rows]
             == [tuple(row[k] for k in identity_fields) for row in predictions], "Scorer case rows mismatch")
    _require(all(row["evaluation"]["l0_structural_validity"] is (row["terminal_status"] == VALID)
                 for row in rows), "Scorer structural validity mismatch")

    lock.verify_fv2_packages(fv2_directory, include_gold=True)
    inputs = scorer.load_input_cases(fv2_directory / lock.FV2_INPUT_NAME)
    _require([r["case_id"] for r in inputs] == list(lock.CASE_IDS), "Input case order mismatch")
    batches = {}
    for row in predictions:
        if row["terminal_status"] == VALID:
            cid = row["case_id"]
            payload = (prediction_directory / "artifacts" / "compiled" / f"{cid}.json").read_bytes()
            _require(lock.sha256_bytes(payload) == row["compiled_batch_sha256"], "Compiled batch hash mismatch")
            batches[cid] = json.loads(payload)

    scorer.verify_prediction_lock(prediction_directory, prediction_lock_sha256, protocol_sha256)
    validated.assert_unchanged()
    lock.validate_public_bindings(validated.value)
    lock.verify_fv2_packages(fv2_directory, include_gold=True)
    gold = scorer.shared.read_gold(fv2_directory / lock.FV2_GOLD_NAME)
    _require(list(gold) == list(lock.CASE_IDS), "Gold case order mismatch")
    _require(all(g["gold_completeness"] == "COMPLETE_FOR_PROFILE" for g in gold.values()),
             "Sealed completeness mismatch")

    predicates = set(ev.load_registry()["predicates"]) | {NO_PREDICATE}
    cases = {}
    for row, context in zip(rows, inputs, strict=True):
        cid, scored = row["case_id"], row["evaluation"]
        case = _evaluation_details(scored, predicates)
        if cid in batches:
            base, gold_batch, predicted = context["base_document"], gold[cid]["gold_batch"], batches[cid]
            diagnosis = fv1.case_diagnosis(base, gold_batch, predicted)
            fv1.check_reproduction(cid, diagnosis, scored)
            case.update(diagnosis, grounding=grounding_diagnosis(base, gold_batch, predicted, scored))
        cases[cid] = case

    public = _public_record(cases)
    scorer.runner.shared._write_json(output_directory / ITEMS_NAME, cases)
    scorer.runner.shared._write_json(output_directory / PUBLIC_NAME, public)
    return public


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("fv2-directory", "prediction-directory", "scoring-directory", "output-directory", "protocol"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--protocol-sha256", required=True)
    parser.add_argument("--prediction-lock-sha256", required=True)
    args = vars(parser.parse_args(argv))
    args["protocol_path"] = args.pop("protocol")
    try:
        public = diagnose(**args)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, BadZipFile, lock.Fv2ProtocolError,
            scorer.Fv2ScoringError, DiagnosisError):
        print("FV2 diagnosis refused", file=sys.stderr)
        return 2
    print(json.dumps(public, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
