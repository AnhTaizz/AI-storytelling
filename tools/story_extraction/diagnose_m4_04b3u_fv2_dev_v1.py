"""Replay saved FV2 responses for development diagnosis.

FV2 is development data under M4-04B3R. M4-04B3O supplies the blind validation
result.

The counterfactuals remove material failures from a fixed evaluation, with no
rescoring or change to structural validity, matches, or any other failure.
L5 is the full-case outcome. U holds material failures without a specific
layer in LAYER_CODES. A failure that belongs to both L3 and L4 appears in both
in the blocking set, and removing either layer removes that failure once.
ALL_BUT_L4 and ALL_BUT_U retain every failure in the named layer, including
overlaps. The counts include cases that already succeed.

L0 marks an unscorable case in the blocking sets. Item histograms cover
structurally valid cases, including zero counts. Missed required assertions
exclude RefersTo, whose misses have a separate resolution breakdown.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from zipfile import BadZipFile

from tools.story_extraction import check_annotation_conventions_v2 as conventions
from tools.story_extraction import diagnose_m4_04b3i_fv1_v1 as fv1
from tools.story_extraction import evaluate_extraction_v0 as ev
from tools.story_extraction import fresh_validation_seal_v1 as seal
from tools.story_extraction import m4_04b3n_fv2_protocol_v1 as lock
from tools.story_extraction import run_m4_04b3o_fv2_predictions_v1 as runner
from tools.story_extraction import score_m4_04b3h_fv1_v1 as scorer
from tools.story_extraction.diagnose_m4_04b3q_fv2_v1 import (
    LAYER_CODES,
    NO_PREDICATE,
    _evaluation_details,
    _public_record,
    grounding_diagnosis,
)
from tools.story_ingestion.light_novel_adapter_v0 import IngestionError

ITEMS_NAME = "M4_04B3U_FV2_DEV_DIAGNOSIS_ITEMS_V1.json"
PUBLIC_NAME = "M4_04B3U_FV2_DEV_DIAGNOSIS_PUBLIC_V1.json"
REPAIR_OPTIONS = {
    "QR": "quote_resolution",
    "AM": "anchor_mentions",
    "ME": "mention_evidence",
    "SE": "sentence_evidence",
    "TB": "transfer_bounds",
}
REMOVABLE_GROUPS = (
    "L1", "L2", "L3", "L4", "U", "L1+L2", "L1+U", "L4+U", "L1+L2+U", "L1+L4+U",
)
RETAINED_LAYERS = ("L4", "U")
HISTOGRAM_BINS = ("0", "1", "2", "3-5", "6+")
TOTAL_KEYS = {
    "matched": "matched_predictions",
    "grounded": "grounded",
    "required_recovered": "required_recovered",
    "predicted": "predicted",
    "unsupported": "unsupported",
}


def _blocker_counts(evaluations):
    blocking_sets = Counter()
    groups = {group: set(group.split("+")) for group in REMOVABLE_GROUPS}
    counterfactual = dict.fromkeys(
        (*groups, *(f"ALL_BUT_{layer}" for layer in RETAINED_LAYERS)), 0,
    )
    for evaluation in evaluations:
        if not evaluation["l0_structural_validity"]:
            blocking_sets["L0"] += 1
            continue
        failures = [
            {layer for layer, codes in LAYER_CODES.items() if layer != "L0" and failure["code"] in codes}
            or {"U"}
            for failure in evaluation["failures"] if failure["material"]
        ]
        layers = set().union(*failures)
        blocking_sets["+".join(sorted(layers)) or "NONE"] += 1
        if evaluation["counts"]["pending_adjudication"]:
            continue
        for group, removed in groups.items():
            counterfactual[group] += all(removed & failure for failure in failures)
        for layer in RETAINED_LAYERS:
            counterfactual[f"ALL_BUT_{layer}"] += layer not in layers
    return blocking_sets, counterfactual


def _histogram_bin(count):
    if count <= 2:
        return str(count)
    return "3-5" if count <= 5 else "6+"


def _development_record(cases, repairs, align_v3):
    public = _public_record(cases)
    evaluations = [case["evaluation"] for case in cases.values()]
    blocking_sets, counterfactual = _blocker_counts(evaluations)
    missed = defaultdict(Counter)
    unsupported = defaultdict(Counter)
    l1_remaining = defaultdict(Counter)
    missed_histogram = dict.fromkeys(HISTOGRAM_BINS, 0)
    unsupported_histogram = dict.fromkeys(HISTOGRAM_BINS, 0)
    for case in cases.values():
        evaluation = case["evaluation"]
        if not evaluation["l0_structural_validity"]:
            continue
        for item in case["missed"]:
            missed[item["predicate"]][item["class"]] += 1
        for item in case["unmatched_predictions"]:
            if item["state"] == "UNSUPPORTED_ASSERTION":
                unsupported[item["predicate"]][item["mechanical_hint"]] += 1
        for failure in evaluation["failures"]:
            if failure["code"] in LAYER_CODES["L1"]:
                l1_remaining[failure.get("predicate") or NO_PREDICATE][failure["code"]] += 1
        missed_histogram[_histogram_bin(len(case["missed"]))] += 1
        unsupported_histogram[_histogram_bin(evaluation["counts"]["unsupported"])] += 1

    public["unsupported"]["by_predicate_and_mechanical_hint"] = unsupported
    public.update(
        blocking_sets=blocking_sets,
        counterfactual_full_success=counterfactual,
        missed_required=missed,
        missed_per_case_histogram=missed_histogram,
        unsupported_per_case_histogram=unsupported_histogram,
        l1_remaining=l1_remaining,
        repairs=sorted(repairs),
        align_v3=align_v3,
        aligned=sum(case["alignment"]["aligned"] for case in cases.values()),
        flagged=sum(case["alignment"]["flagged"] for case in cases.values()),
        case_count=len(cases),
        valid_cases=sum(evaluation["l0_structural_validity"] for evaluation in evaluations),
        l1_pass=sum(
            evaluation["l0_structural_validity"]
            and not (LAYER_CODES["L1"] & set(evaluation["failure_codes"]))
            for evaluation in evaluations
        ),
        full_success=sum(evaluation["full_canonical_case_success"] is True for evaluation in evaluations),
        totals={
            name: sum(evaluation.get("counts", {}).get(key, 0) for evaluation in evaluations)
            for name, key in TOTAL_KEYS.items()
        },
    )
    return public


def _replay(case, raw_directory, repair_options):
    attempts = {}
    for phase in ("primary", "repair_1"):
        try:
            raw = (raw_directory / f"{case.case_id}_{phase}.txt").read_bytes().decode("utf-8")
        except FileNotFoundError:
            attempts[phase] = {"category": "RAW_RESPONSE_ABSENT"}
            continue
        _, _, batch, validation = lock.dev.validate_attempt(raw, case, **repair_options)
        attempts[phase] = validation
        if batch is not None:
            return batch, phase, attempts
    return None, None, attempts


def diagnose(fv2_directory, run_directory, output_directory, *, repairs: frozenset[str], align_v3: bool) -> dict:
    """Write private case items and return the public FV2 development counts."""
    if not repairs <= REPAIR_OPTIONS.keys():
        raise ValueError("Unknown FV2 development repair")
    repair_options = {option: code in repairs for code, option in REPAIR_OPTIONS.items()}
    repair_options["mention_evidence_predicates"] = lock.dev.MENTION_EVIDENCE_PREDICATES
    fv2_directory = Path(fv2_directory)
    lock.verify_fv2_packages(fv2_directory, include_gold=True)
    replay_cases = runner.load_cases(fv2_directory)
    contexts = seal.load_input_cases(fv2_directory / lock.FV2_INPUT_NAME)
    if [case.case_id for case in replay_cases] != [row["case_id"] for row in contexts]:
        raise fv1.DiagnosisError("FV2 input case order mismatch")
    lock.verify_fv2_packages(fv2_directory, include_gold=True)
    gold = scorer.read_gold(fv2_directory / lock.FV2_GOLD_NAME)
    if list(gold) != [case.case_id for case in replay_cases]:
        raise fv1.DiagnosisError("FV2 gold case order mismatch")
    if any(row["gold_completeness"] != "COMPLETE_FOR_PROFILE" for row in gold.values()):
        raise fv1.DiagnosisError("FV2 gold completeness mismatch")

    predicates = set(ev.load_registry()["predicates"]) | {NO_PREDICATE}
    raw_directory = Path(run_directory) / "predictions" / "artifacts" / "raw"
    cases = {}
    for case, context in zip(replay_cases, contexts, strict=True):
        batch, phase, attempts = _replay(case, raw_directory, repair_options)
        gold_row = gold[case.case_id]
        completeness = gold_row["gold_completeness"]
        alignment = {"aligned": 0, "flagged": 0}
        if batch is None:
            codes = sorted({f"{attempt_phase}:{report['category']}" for attempt_phase, report in attempts.items()})
            evaluation = scorer._structural_failure_result({"repair_validation": {"errors": codes}}, completeness)
        else:
            base = context["base_document"]
            ingestion = context["context"].ingestion
            gold_batch = gold_row["gold_batch"]
            if align_v3:
                # The adapter binds these original bytes to the source version.
                # The checker verifies source and evidence-span hashes.
                sources = {doc.version: doc.source_bytes for doc in ingestion.documents}
                gold_batch, alignment = conventions.align_mention_roles(gold_batch, sources, base)
            evaluation = ev.evaluate_case(
                base, gold_batch, batch, ingestion=ingestion,
                case_spec={"mode": "REAL_SOURCE", "gold_completeness": completeness,
                           "acceptable_assertion_ids": [], "adjudications": []},
            )
        items = _evaluation_details(evaluation, predicates)
        items.update(evaluation=evaluation, phase=phase, attempts=attempts, alignment=alignment)
        if evaluation["l0_structural_validity"]:
            diagnosis = fv1.case_diagnosis(base, gold_batch, batch)
            fv1.check_reproduction(case.case_id, diagnosis, evaluation)
            items.update(diagnosis, grounding=grounding_diagnosis(base, gold_batch, batch, evaluation))
        cases[case.case_id] = items

    public = _development_record(cases, repairs, align_v3)
    output_directory = Path(output_directory)
    runner.shared._write_json(output_directory / ITEMS_NAME, cases)
    runner.shared._write_json(output_directory / PUBLIC_NAME, public)
    return public


def _parse_repairs(value):
    repairs = frozenset(part.strip() for part in value.split(",")) if value.strip() else frozenset()
    if not repairs <= REPAIR_OPTIONS.keys():
        raise argparse.ArgumentTypeError("repairs must be a comma-separated subset of QR,AM,ME,SE,TB")
    return repairs


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fv2", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repairs", type=_parse_repairs, default=frozenset())
    parser.add_argument("--align-v3", action="store_true")
    args = parser.parse_args(argv)
    try:
        public = diagnose(args.fv2, args.run, args.out, repairs=args.repairs, align_v3=args.align_v3)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, BadZipFile, IngestionError,
            lock.Fv2ProtocolError, runner.Fv2PredictionError, scorer.Fv1ScoringError, fv1.DiagnosisError):
        print("FV2 development diagnosis refused", file=sys.stderr)
        return 2
    print(json.dumps(public, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
