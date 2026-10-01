"""Story Extraction evaluator skeleton v0 (STORY_EXTRACTION/v0, research baseline).

Compares a predicted extraction batch with a gold batch built on the SAME base
canonical document. Opaque ids are never compared: records are aligned by what
they are grounded in and what they say.

    evidence refs   by exact source span
    mentions        by evidence span + surface form
    entities        by the mentions resolved to them (RefersTo)
    events          by event kind + the evidence of assertions about them
    propositions    by predicate + aligned arguments (order-insensitive)
    assertions      by proposition content + polarity

This is deliberately not a general graph matcher. Cases it cannot align are
reported as unaligned, never guessed. Open questions are listed in
docs/research/m4/M4_EXTRACTION_EVALUATION_PROTOCOL_V0.md.

No model, network or NLP.
"""
import json
import sys
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.canonical_story.conformance_v0 import load_registry  # noqa: E402
from tools.story_extraction.extraction_contract_v0 import CANDIDATE_COLLECTIONS, merge, validate_batch  # noqa: E402

EVALUATOR_VERSION = "evaluate_extraction_v0/0.1.0"
STATUS_STRENGTH = {"SUGGESTED": 1, "ENTAILED": 2, "EXPLICIT": 3}
CAUSAL_PREDICATES = ("Causes", "Enables")
NON_MATERIAL_FAILURES = ("DUPLICATE_ASSERTION",)

FAILURE_CODES = (
    "CANONICAL_CONFORMANCE_FAILURE", "MISSED_REQUIRED_ASSERTION", "MISSING_ENTITY_RESOLUTION",
    "UNSUPPORTED_ASSERTION", "HOLDER_RELATIVE_TRUTH_LEAK", "INVENTED_CAUSALITY", "WRONG_ENTITY_RESOLUTION",
    "WRONG_POLARITY", "EPISTEMIC_OVERSTATEMENT", "EPISTEMIC_UNDERSTATEMENT", "WRONG_VALIDITY_BOUND",
    "WRONG_EVIDENCE_SPAN", "WRONG_EVIDENCE_ROLE", "INSUFFICIENT_SUPPORT_MARKED_SUFFICIENT", "DUPLICATE_ASSERTION",
)


class _View:
    """Indexes over one merged canonical document."""

    def __init__(self, document: Dict[str, Any], candidate: Dict[str, Any], registry: Dict[str, Any]):
        self.doc = document
        self.registry = registry
        self.by_id = {name: {r["id"]: r for r in document[name]} for name in CANDIDATE_COLLECTIONS}
        self.candidate_ids = {name: {r["id"] for r in candidate[name]} for name in CANDIDATE_COLLECTIONS}
        self.assertions = [a for a in document["assertions"] if a["review"]["state"] != "REJECTED"]

    def span_key(self, evidence_ref_id: str) -> Tuple:
        ref = self.by_id["evidence_refs"][evidence_ref_id]
        span = ref.get("span", {})
        return ref["segment_id"], span.get("char_start"), span.get("char_end_exclusive")

    def mention_key(self, mention_id: str) -> Tuple:
        mention = self.by_id["mentions"][mention_id]
        return self.span_key(mention["evidence_ref_id"]), mention["surface_form"]

    def proposition(self, assertion: Dict[str, Any]) -> Dict[str, Any]:
        return self.by_id["propositions"][assertion["proposition_id"]]

    def sufficient_sets(self, assertion: Dict[str, Any]) -> List[FrozenSet]:
        return [frozenset(self.span_key(r) for r in s["evidence_ref_ids"])
                for s in assertion["support"]["evidence_sets"] if s["label"] == "SUFFICIENT"]

    def entity_mentions(self) -> Dict[str, set]:
        out: Dict[str, set] = {e["id"]: set() for e in self.doc["entities"]}
        for assertion in self.assertions:
            prop = self.proposition(assertion)
            if prop.get("predicate") == "RefersTo" and assertion["polarity"] == "AFFIRMED":
                out[prop["args"]["entity"]["ref"]].add(self.mention_key(prop["args"]["mention"]["ref"]))
        return out

    def event_evidence(self) -> Dict[str, set]:
        out: Dict[str, set] = {e["id"]: set() for e in self.doc["events"]}
        for assertion in self.assertions:
            for event_id in self._events_in(assertion["proposition_id"]):
                for spans in self.sufficient_sets(assertion):
                    out[event_id] |= spans
        return out

    def _events_in(self, proposition_id: str) -> set:
        """Events named by a proposition, including inside embedded (reported or believed) content."""
        found = set()
        for arg in self.by_id["propositions"][proposition_id].get("args", {}).values():
            if arg["kind"] == "EVENT":
                found.add(arg["ref"])
            elif arg["kind"] == "PROPOSITION":
                found |= self._events_in(arg["ref"])
        return found


def _shared(a: set, b: set) -> int:
    return len(a & b)


def _overlapping_spans(a: set, b: set) -> int:
    """Number of spans in `a` that overlap some span in `b` (same segment, intersecting ranges)."""
    return sum(1 for (seg, start, end) in a
               if any(seg == s2 and None not in (start, end, st2, en2) and start < en2 and st2 < end
                      for (s2, st2, en2) in b))


def _greedy_align(gold: Dict[str, set], pred: Dict[str, set], compatible, score=_shared) -> Dict[str, str]:
    """Injective pred -> gold alignment by largest shared evidence; deterministic tie-break by id."""
    pairs = sorted(((-score(gold[g], pred[p]), g, p) for g in gold for p in pred
                    if score(gold[g], pred[p]) and compatible(g, p)))
    mapping: Dict[str, str] = {}
    used = set()
    for _, g, p in pairs:
        if p not in mapping and g not in used:
            mapping[p] = g
            used.add(g)
    return mapping


class _Alignment:
    def __init__(self, gold: _View, pred: _View, base_ids: set):
        self.gold, self.pred = gold, pred
        identity = {i: i for i in base_ids}                      # prior-context records keep their ids
        gold_entities = {k: v for k, v in gold.entity_mentions().items() if k not in base_ids}
        pred_entities = {k: v for k, v in pred.entity_mentions().items() if k not in base_ids}
        kind = lambda view, eid: view.by_id["entities"][eid]["kind"]
        self.entities = dict(identity)
        self.entities.update(_greedy_align(gold_entities, pred_entities,
                                           lambda g, p: kind(gold, g) == kind(pred, p)))
        gold_events = {k: v for k, v in gold.event_evidence().items() if k not in base_ids}
        pred_events = {k: v for k, v in pred.event_evidence().items() if k not in base_ids}
        ekind = lambda view, eid: view.by_id["events"][eid]["event_kind"]
        self.events = dict(identity)
        # Events are aligned by OVERLAPPING evidence, so a too-wide or too-narrow span is scored as a
        # grounding error on a matched assertion, not as a missed event plus an invented one.
        self.events.update(_greedy_align(gold_events, pred_events, lambda g, p: ekind(gold, g) == ekind(pred, p),
                                         score=_overlapping_spans))
        self.anchors = dict(identity)
        for pred_event, gold_event in self.events.items():
            if pred_event in pred.by_id["events"] and gold_event in gold.by_id["events"]:
                self.anchors[pred.by_id["events"][pred_event]["anchor_id"]] = gold.by_id["events"][gold_event]["anchor_id"]

    def signature(self, view: _View, proposition_id: str, translate: bool) -> str:
        """Content signature in GOLD terms. `translate` is True for the predicted document."""
        prop = view.by_id["propositions"][proposition_id]
        if prop.get("placeholder"):
            return json.dumps(["PLACEHOLDER", proposition_id if not translate else f"?{proposition_id}"])
        parts = []
        for name in sorted(prop["args"]):
            arg = prop["args"][name]
            kind = arg["kind"]
            if kind == "LITERAL":
                value: Any = [arg["value_type"], arg["value"]]
            elif kind == "TOKEN":
                value = [arg["vocabulary"], arg["value"]]
            elif kind == "PROPOSITION":
                value = self.signature(view, arg["ref"], translate)
            elif kind == "MENTION":
                value = list(map(str, view.mention_key(arg["ref"])))
            else:
                table = {"ENTITY": self.entities, "EVENT": self.events, "ANCHOR": self.anchors}[kind]
                value = (table.get(arg["ref"], f"?{arg['ref']}") if translate else arg["ref"])
            parts.append([name, kind, value])
        predicate = prop["predicate"]
        if view.registry["predicates"].get(predicate, {}).get("directionality") == "SYMMETRIC":
            values = sorted(json.dumps(p[2]) for p in parts)
            parts = [["*", parts[0][1], v] for v in values]
        return json.dumps([predicate, parts], ensure_ascii=False, separators=(",", ":"))

    def validity(self, view: _View, assertion: Dict[str, Any], translate: bool):
        validity = assertion.get("validity")
        if validity is None:
            return None
        out = []
        for side in ("start", "end"):
            bound = validity[side]
            if bound["kind"] == "OPEN":
                out.append("OPEN")
            else:
                anchor = bound["anchor_id"]
                out.append(self.anchors.get(anchor, f"?{anchor}") if translate else anchor)
        return tuple(out)


def _ratio(numerator: int, denominator: int) -> Optional[float]:
    return None if denominator == 0 else round(numerator / denominator, 4)


def evaluate_case(base_document: Dict[str, Any], gold_batch: Dict[str, Any], predicted_batch: Dict[str, Any],
                  acceptable_gold_assertion_ids=(), ingestion: Optional[Any] = None) -> Dict[str, Any]:
    """Score one case. Gold assertions are required unless listed as acceptable (correct but optional)."""
    registry = load_registry()
    result: Dict[str, Any] = {"evaluator_version": EVALUATOR_VERSION, "failures": []}
    gold_report = validate_batch(gold_batch, base_document, ingestion)
    if not gold_report["pass"]:
        raise ValueError(f"gold batch is not valid: {gold_report['checks']}")
    pred_report = validate_batch(predicted_batch, base_document, ingestion)
    result["l0_structural_validity"] = pred_report["pass"]
    if not pred_report["pass"]:
        result["failures"].append({"code": "CANONICAL_CONFORMANCE_FAILURE",
                                   "detail": [i for c in pred_report["checks"].values() for i in c["issues"]][:10]})
        result["metrics"] = None
        result["failure_codes"] = ["CANONICAL_CONFORMANCE_FAILURE"]
        result["full_canonical_case_success"] = False
        return result

    gold = _View(merge(gold_batch, base_document), gold_batch["candidate_records"], registry)
    pred = _View(merge(predicted_batch, base_document), predicted_batch["candidate_records"], registry)
    base_ids = {r["id"] for name in CANDIDATE_COLLECTIONS for r in base_document[name]}
    align = _Alignment(gold, pred, base_ids)
    fail = lambda code, **detail: result["failures"].append({"code": code, **detail})

    acceptable = set(acceptable_gold_assertion_ids)
    gold_assertions = [a for a in gold.assertions if a["id"] in gold.candidate_ids["assertions"]]
    pred_assertions = [a for a in pred.assertions if a["id"] in pred.candidate_ids["assertions"]]
    gold_by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
    gold_by_signature: Dict[str, Dict[str, Any]] = {}
    for a in gold_assertions:
        signature = align.signature(gold, a["proposition_id"], False)
        gold_by_key[(signature, a["polarity"])] = a
        gold_by_signature[signature] = a
    holder_relative = set(registry["holder_relative_predicates"])
    embedded_content = set()
    gold_resolutions = {}
    for a in gold.assertions:
        prop = gold.proposition(a)
        if prop.get("predicate") in holder_relative:
            embedded_content.add(align.signature(gold, prop["args"]["content"]["ref"], False))
        if prop.get("predicate") == "RefersTo":
            gold_resolutions[gold.mention_key(prop["args"]["mention"]["ref"])] = prop["args"]["entity"]["ref"]
    gold_roles: Dict[Tuple, set] = {}
    for ref in gold.doc["evidence_refs"]:
        gold_roles.setdefault(gold.span_key(ref["id"]), set()).add(ref["role"])

    matched: Dict[str, Dict[str, Any]] = {}            # gold assertion id -> predicted assertion
    counts = {"matched_predictions": 0, "unsupported": 0, "duplicates": 0, "grounded": 0, "epistemic_equal": 0}
    for p in pred_assertions:
        signature = align.signature(pred, p["proposition_id"], True)
        predicate = pred.proposition(p).get("predicate")
        g = gold_by_key.get((signature, p["polarity"]))
        if g is None:
            counts["unsupported"] += 1
            if signature in gold_by_signature:
                fail("WRONG_POLARITY", predicted=p["polarity"], gold=gold_by_signature[signature]["polarity"])
            elif signature in embedded_content:
                fail("HOLDER_RELATIVE_TRUTH_LEAK", predicate=predicate)
            elif predicate in CAUSAL_PREDICATES:
                fail("INVENTED_CAUSALITY", predicate=predicate)
            elif predicate == "RefersTo" and \
                    pred.mention_key(pred.proposition(p)["args"]["mention"]["ref"]) in gold_resolutions:
                fail("WRONG_ENTITY_RESOLUTION")
            else:
                fail("UNSUPPORTED_ASSERTION", predicate=predicate)
            continue
        if g["id"] in matched:
            counts["duplicates"] += 1
            fail("DUPLICATE_ASSERTION", predicate=predicate)
            continue
        matched[g["id"]] = p
        counts["matched_predictions"] += 1

        if p["epistemic_status"] == g["epistemic_status"]:
            counts["epistemic_equal"] += 1
        else:
            stronger = STATUS_STRENGTH[p["epistemic_status"]] > STATUS_STRENGTH[g["epistemic_status"]]
            fail("EPISTEMIC_OVERSTATEMENT" if stronger else "EPISTEMIC_UNDERSTATEMENT", predicate=predicate,
                 predicted=p["epistemic_status"], gold=g["epistemic_status"])
        if align.validity(pred, p, True) != align.validity(gold, g, False):
            fail("WRONG_VALIDITY_BOUND", predicate=predicate)

        gold_sets = gold.sufficient_sets(g)
        gold_derivations = {(d["rule_id"], frozenset(
            (align.signature(gold, gold.by_id["assertions"][x]["proposition_id"], False),
             gold.by_id["assertions"][x]["polarity"]) for x in d["premise_assertion_ids"]))
            for d in g["support"]["derivations"]}
        pred_sets = pred.sufficient_sets(p)
        pred_derivations = {(d["rule_id"], frozenset(
            (align.signature(pred, pred.by_id["assertions"][x]["proposition_id"], True),
             pred.by_id["assertions"][x]["polarity"]) for x in d["premise_assertion_ids"]))
            for d in p["support"]["derivations"]}
        grounded = any(s in gold_sets for s in pred_sets) or bool(pred_derivations & gold_derivations)
        if grounded:
            counts["grounded"] += 1
        elif any(s < g_set for s in pred_sets for g_set in gold_sets):
            fail("INSUFFICIENT_SUPPORT_MARKED_SUFFICIENT", predicate=predicate)
        else:
            fail("WRONG_EVIDENCE_SPAN", predicate=predicate)

    required = [a for a in gold_assertions if a["id"] not in acceptable]
    recovered = [a for a in required if a["id"] in matched]
    for a in required:
        if a["id"] not in matched:
            predicate = gold.proposition(a).get("predicate")
            fail("MISSING_ENTITY_RESOLUTION" if predicate == "RefersTo" else "MISSED_REQUIRED_ASSERTION",
                 predicate=predicate)

    role_total = role_equal = 0
    for ref in predicted_batch["candidate_records"]["evidence_refs"]:
        key = pred.span_key(ref["id"])
        if key in gold_roles:
            role_total += 1
            if ref["role"] in gold_roles[key]:
                role_equal += 1
            else:
                fail("WRONG_EVIDENCE_ROLE", predicted=ref["role"], gold=sorted(gold_roles[key]))

    required_resolutions = [a for a in required if gold.proposition(a).get("predicate") == "RefersTo"]
    grounded_required = sum(1 for a in recovered if _is_grounded(gold, pred, align, a, matched[a["id"]]))
    result["counts"] = {"gold_required": len(required), "gold_acceptable": len(acceptable),
                        "predicted": len(pred_assertions), **counts,
                        "required_recovered": len(recovered)}
    result["metrics"] = {
        "assertion_precision": _ratio(counts["matched_predictions"], len(pred_assertions)),
        "assertion_recall": _ratio(len(recovered), len(required)),
        "evidence_grounding_precision": _ratio(counts["grounded"], counts["matched_predictions"]),
        "evidence_grounding_recall": _ratio(grounded_required, len(required)),
        "epistemic_accuracy": _ratio(counts["epistemic_equal"], counts["matched_predictions"]),
        "evidence_role_accuracy": _ratio(role_equal, role_total),
        "referent_resolution_accuracy": _ratio(sum(1 for a in required_resolutions if a["id"] in matched),
                                               len(required_resolutions)),
        "unsupported_assertion_count": counts["unsupported"],
        "unsupported_assertion_rate": _ratio(counts["unsupported"], len(pred_assertions)),
    }
    result["failure_codes"] = sorted({f["code"] for f in result["failures"]})
    result["full_canonical_case_success"] = all(f["code"] in NON_MATERIAL_FAILURES for f in result["failures"])
    return result


def _is_grounded(gold: _View, pred: _View, align: _Alignment, g: Dict[str, Any], p: Dict[str, Any]) -> bool:
    if any(s in gold.sufficient_sets(g) for s in pred.sufficient_sets(p)):
        return True
    key = lambda view, a, translate: (align.signature(view, view.by_id["assertions"][a]["proposition_id"], translate),
                                      view.by_id["assertions"][a]["polarity"])
    gold_d = {(d["rule_id"], frozenset(key(gold, x, False) for x in d["premise_assertion_ids"]))
              for d in g["support"]["derivations"]}
    pred_d = {(d["rule_id"], frozenset(key(pred, x, True) for x in d["premise_assertion_ids"]))
              for d in p["support"]["derivations"]}
    return bool(gold_d & pred_d)


def aggregate(case_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Micro-aggregate counts over cases, plus the strict case-level endpoint."""
    scored = [r for r in case_results if r.get("metrics") is not None]
    total = lambda key: sum(r["counts"][key] for r in scored)
    return {
        "cases": len(case_results),
        "cases_structurally_invalid": len(case_results) - len(scored),
        "full_canonical_case_success_count": sum(1 for r in case_results if r["full_canonical_case_success"]),
        "full_canonical_case_success_rate": _ratio(sum(1 for r in case_results if r["full_canonical_case_success"]),
                                                   len(case_results)),
        "assertion_precision": _ratio(total("matched_predictions"), total("predicted")) if scored else None,
        "assertion_recall": _ratio(total("required_recovered"), total("gold_required")) if scored else None,
        "unsupported_assertion_rate": _ratio(total("unsupported"), total("predicted")) if scored else None,
    }
