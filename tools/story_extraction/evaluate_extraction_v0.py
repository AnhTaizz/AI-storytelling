"""Story Extraction evaluator v0 (STORY_EXTRACTION/v0, research baseline; real-source development calibrated).

Compares a predicted extraction batch with a gold batch built on the SAME base
canonical document. Opaque ids are never compared: records are aligned by what
they are grounded in and what they say.

    evidence refs   by source span (containment rule, see span_matches)
    mentions        by exact evidence span + surface form
    entities        by identity class (SameAs within scope), then by mentions, then by structural role
    events          by event kind + structural role with overlapping evidence
    anchors         event-time anchors through their event; named-time anchors by structural role
    placeholders    by structural role
    propositions    by predicate + aligned arguments (order-insensitive)
    assertions      by proposition content + polarity

Unmatched predictions are NOT called hallucinations by default on real-source
cases: they are GOLD_UNMATCHED_PENDING_ADJUDICATION until a reviewer decides.

This is deliberately not a general graph matcher. Protocol and limits:
docs/research/m4/M4_EXTRACTION_EVALUATION_PROTOCOL_V0.md

No model, network or NLP.
"""
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.canonical_story.conformance_v0 import load_registry  # noqa: E402
from tools.story_extraction.extraction_contract_v0 import CANDIDATE_COLLECTIONS, merge, validate_batch  # noqa: E402

EVALUATOR_VERSION = "evaluate_extraction_v0/0.2.0"
STATUS_STRENGTH = {"SUGGESTED": 1, "ENTAILED": 2, "EXPLICIT": 3}
CAUSAL_PREDICATES = ("Causes", "Enables")
MODES = ("SYNTHETIC_COMPLETE", "REAL_SOURCE")
GOLD_COMPLETENESS = ("COMPLETE_FOR_PROFILE", "INCOMPLETE", "UNCERTAIN")
PENDING = "GOLD_UNMATCHED_PENDING_ADJUDICATION"
ADJUDICATION_STATES = ("VALID_ADDITIONAL_ASSERTION", "UNSUPPORTED_ASSERTION", "OUT_OF_SCOPE_ASSERTION",
                       "EQUIVALENT_REPRESENTATION")
SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
MATERIAL_SEVERITIES = ("CRITICAL", "HIGH")
NON_MATERIAL_FAILURES = ("DUPLICATE_ASSERTION",)

FAILURE_CODES = (
    "CANONICAL_CONFORMANCE_FAILURE", "MISSED_REQUIRED_ASSERTION", "MISSING_ENTITY_RESOLUTION",
    "UNSUPPORTED_ASSERTION", "HOLDER_RELATIVE_TRUTH_LEAK", "INVENTED_CAUSALITY", "WRONG_ENTITY_RESOLUTION",
    "WRONG_POLARITY", "EPISTEMIC_OVERSTATEMENT", "EPISTEMIC_UNDERSTATEMENT", "WRONG_VALIDITY_BOUND",
    "WRONG_EVIDENCE_SPAN", "WRONG_EVIDENCE_ROLE", "INSUFFICIENT_SUPPORT_MARKED_SUFFICIENT", "DUPLICATE_ASSERTION",
    # assigned only through adjudication (a reviewer relabels an unmatched prediction):
    "WRONG_PREDICATE", "WRONG_ARGUMENT", "WRONG_EVENT_GRANULARITY", "NON_ATOMIC_ASSERTION",
)

Span = Tuple[str, int, int]


def span_matches(predicted: Span, gold: Span, narrow_segments=frozenset()) -> bool:
    """Evaluation equivalence of two evidence spans (evidence identity itself stays exact).

    A predicted span is accepted for a gold span when it lies in the same SourceSegment and
    contains the gold span. In a segment declared narrow (mixed roles), only the exact span
    is accepted. A predicted span never leaves its segment (the batch validator enforces it).
    """
    if predicted[0] != gold[0] or None in predicted or None in gold:
        return False
    if gold[0] in narrow_segments:
        return predicted == gold
    return predicted[1] <= gold[1] and gold[2] <= predicted[2]


def _overlap(a: Span, b: Span) -> bool:
    return a[0] == b[0] and None not in a and None not in b and a[1] < b[2] and b[1] < a[2]


def _set_relation(predicted: frozenset, gold: frozenset, narrow) -> str:
    """MATCH, SUBSET (valid spans but some gold evidence missing) or MISMATCH."""
    if not predicted:
        return "MISMATCH"
    if not all(any(span_matches(p, g, narrow) for g in gold) for p in predicted):
        return "MISMATCH"
    return "MATCH" if all(any(span_matches(p, g, narrow) for p in predicted) for g in gold) else "SUBSET"


class _View:
    """Indexes over one merged canonical document."""

    def __init__(self, document: Dict[str, Any], candidate: Dict[str, Any], registry: Dict[str, Any]):
        self.doc = document
        self.registry = registry
        self.by_id = {name: {r["id"]: r for r in document[name]} for name in CANDIDATE_COLLECTIONS}
        self.candidate_ids = {name: {r["id"] for r in candidate[name]} for name in CANDIDATE_COLLECTIONS}
        self.assertions = [a for a in document["assertions"] if a["review"]["state"] != "REJECTED"]
        self._parent: Dict[str, str] = {e["id"]: e["id"] for e in document["entities"]}
        for assertion in self.assertions:                      # identity classes within the scope (as-of safe)
            prop = self.proposition(assertion)
            if prop.get("predicate") == "SameAs" and assertion["polarity"] == "AFFIRMED":
                a, b = self.entity_class(prop["args"]["first"]["ref"]), self.entity_class(prop["args"]["second"]["ref"])
                self._parent[max(a, b)] = min(a, b)

    def entity_class(self, entity_id: str) -> str:
        while self._parent[entity_id] != entity_id:
            entity_id = self._parent[entity_id]
        return entity_id

    def span_key(self, evidence_ref_id: str) -> Span:
        ref = self.by_id["evidence_refs"][evidence_ref_id]
        span = ref.get("span", {})
        return ref["segment_id"], span.get("char_start"), span.get("char_end_exclusive")

    def mention_key(self, mention_id: str) -> Tuple:
        mention = self.by_id["mentions"][mention_id]
        return self.span_key(mention["evidence_ref_id"]), mention["surface_form"]

    def proposition(self, assertion: Dict[str, Any]) -> Dict[str, Any]:
        return self.by_id["propositions"][assertion["proposition_id"]]

    def sufficient_sets(self, support: Dict[str, Any]) -> List[frozenset]:
        return [frozenset(self.span_key(r) for r in s["evidence_ref_ids"])
                for s in support["evidence_sets"] if s["label"] == "SUFFICIENT"]

    def spans(self, support: Dict[str, Any]) -> frozenset:
        return frozenset(s for group in self.sufficient_sets(support) for s in group)

    def entity_mentions(self) -> Dict[str, set]:
        """Mentions resolved to each entity RECORD (not to its identity class)."""
        out: Dict[str, set] = {}
        for assertion in self.assertions:
            prop = self.proposition(assertion)
            if prop.get("predicate") == "RefersTo" and assertion["polarity"] == "AFFIRMED":
                out.setdefault(prop["args"]["entity"]["ref"], set()).add(
                    self.mention_key(prop["args"]["mention"]["ref"]))
        return out

    def class_members(self, entity_id: str) -> List[str]:
        target = self.entity_class(entity_id)
        return sorted(e for e in self._parent if self.entity_class(e) == target)

    def structural_items(self) -> Dict[Tuple[str, str], List[Tuple[Tuple, frozenset]]]:
        """For every referent: the roles it plays, with the evidence of the assertion that says so.

        Keys are (kind, id) with kind in ENTITY, EVENT, ANCHOR, PLACEHOLDER. An item is
        ((top predicate, argument path, sibling tokens and literals), evidence spans).
        Display or editorial labels are never used.
        """
        items: Dict[Tuple[str, str], List] = {}

        def walk(proposition_id: str, top: str, path: str, spans: frozenset):
            prop = self.by_id["propositions"][proposition_id]
            if prop.get("placeholder"):
                items.setdefault(("PLACEHOLDER", proposition_id), []).append(((top, path, ()), spans))
                return
            args = prop["args"]
            siblings = tuple(sorted((n, str(a["value"])) for n, a in args.items() if a["kind"] in ("TOKEN", "LITERAL")))
            symmetric = self.registry["predicates"].get(prop["predicate"], {}).get("directionality") == "SYMMETRIC"
            for name, arg in args.items():
                here = f"{path}/{prop['predicate']}.{'*' if symmetric else name}"
                if arg["kind"] == "ENTITY":
                    items.setdefault(("ENTITY", arg["ref"]), []).append(((top, here, siblings), spans))
                elif arg["kind"] in ("EVENT", "ANCHOR"):
                    items.setdefault((arg["kind"], arg["ref"]), []).append(((top, here, siblings), spans))
                elif arg["kind"] == "PROPOSITION":
                    walk(arg["ref"], top, here, spans)

        for assertion in self.assertions:
            prop = self.proposition(assertion)
            spans = self.spans(assertion["support"])
            walk(assertion["proposition_id"], prop.get("predicate", "PLACEHOLDER"), "", spans)
            for side in ("start", "end"):
                bound = (assertion.get("validity") or {}).get(side, {})
                if bound.get("kind") == "ANCHOR":
                    bound_spans = self.spans(bound["support"]) if "support" in bound else frozenset()
                    items.setdefault(("ANCHOR", bound["anchor_id"]), []).append(
                        ((f"@{side}", prop.get("predicate", ""), ()), bound_spans))
        return items


def _item_score(gold_items: List, pred_items: List) -> int:
    """Number of gold role items the predicted referent also has, with overlapping (or no) evidence."""
    score = 0
    for key, spans in gold_items:
        for other_key, other_spans in pred_items:
            if key == other_key and ((not spans and not other_spans)
                                     or any(_overlap(a, b) for a in spans for b in other_spans)):
                score += 1
                break
    return score


def _greedy(gold_ids: List[str], pred_ids: List[str], score, compatible, ambiguities: List,
            same_group=lambda a, b: False) -> Dict[str, str]:
    """Injective pred -> gold alignment by highest score; deterministic tie-break by id."""
    scored = sorted((-score(g, p), g, p) for g in gold_ids for p in pred_ids if compatible(g, p) and score(g, p) > 0)
    mapping: Dict[str, str] = {}
    used = set()
    for negative, g, p in scored:
        if p in mapping or g in used:
            continue
        rivals = [g2 for n2, g2, p2 in scored if p2 == p and n2 == negative and g2 != g and g2 not in used
                  and not same_group(g, g2)]
        if rivals:
            ambiguities.append({"predicted": p, "candidates": sorted([g] + rivals), "score": -negative})
        mapping[p] = g
        used.add(g)
    return mapping


class _Alignment:
    def __init__(self, gold: _View, pred: _View, base_ids: set, literal_groups: Dict):
        self.gold, self.pred, self.literal_groups = gold, pred, literal_groups
        self.ambiguities: List[Dict[str, Any]] = []
        gold_items, pred_items = gold.structural_items(), pred.structural_items()
        g_items = lambda kind, i: gold_items.get((kind, i), [])
        p_items = lambda kind, i: pred_items.get((kind, i), [])

        # ---- entities: records are aligned one to one; identity classes are applied in signatures
        gold_classes = sorted(e["id"] for e in gold.doc["entities"])
        pred_classes = sorted(e["id"] for e in pred.doc["entities"])
        self.entities: Dict[str, str] = {c: c for c in pred_classes if c in base_ids and c in gold_classes}
        g_mentions, p_mentions = gold.entity_mentions(), pred.entity_mentions()
        same_class = lambda a, b: gold.entity_class(a) == gold.entity_class(b)
        kind = lambda view, i: view.by_id["entities"][i]["kind"]
        free = lambda mapping, gs, ps: ([g for g in gs if g not in mapping.values()], [p for p in ps if p not in mapping])
        gs, ps = free(self.entities, gold_classes, pred_classes)
        self.entities.update(_greedy(gs, ps, lambda g, p: len(g_mentions.get(g, set()) & p_mentions.get(p, set())),
                                     lambda g, p: kind(gold, g) == kind(pred, p), self.ambiguities, same_class))
        gs, ps = free(self.entities, gold_classes, pred_classes)
        self.entities.update(_greedy(gs, ps, lambda g, p: _item_score(g_items("ENTITY", g), p_items("ENTITY", p)),
                                     lambda g, p: kind(gold, g) == kind(pred, p), self.ambiguities, same_class))

        # ---- events
        ekind = lambda view, i: view.by_id["events"][i]["event_kind"]
        gold_events, pred_events = sorted(gold.by_id["events"]), sorted(pred.by_id["events"])
        self.events: Dict[str, str] = {e: e for e in pred_events if e in base_ids and e in gold.by_id["events"]}
        gs, ps = free(self.events, gold_events, pred_events)
        self.events.update(_greedy(gs, ps, lambda g, p: _item_score(g_items("EVENT", g), p_items("EVENT", p)),
                                   lambda g, p: ekind(gold, g) == ekind(pred, p), self.ambiguities))

        # ---- anchors: event-time through the event; named-time by structural role
        g_anchor, p_anchor = gold.by_id["temporal_anchors"], pred.by_id["temporal_anchors"]
        self.anchors: Dict[str, str] = {a: a for a in p_anchor if a in base_ids and a in g_anchor}
        for pred_event, gold_event in self.events.items():
            self.anchors[pred.by_id["events"][pred_event]["anchor_id"]] = gold.by_id["events"][gold_event]["anchor_id"]
        # Remaining anchors (named-time anchors, and event-time anchors of events that appear only as a
        # validity bound) are aligned by structural role; such an event then follows its anchor.
        akind = lambda view, i: view.by_id["temporal_anchors"][i]["anchor_kind"]
        gs, ps = free(self.anchors, sorted(g_anchor), sorted(p_anchor))
        self.anchors.update(_greedy(gs, ps, lambda g, p: _item_score(g_items("ANCHOR", g), p_items("ANCHOR", p)),
                                    lambda g, p: akind(gold, g) == akind(pred, p), self.ambiguities))
        for pred_anchor, gold_anchor in self.anchors.items():
            pe, ge = p_anchor[pred_anchor].get("event_id"), g_anchor[gold_anchor].get("event_id")
            if pe and ge and pe not in self.events and ge not in self.events.values() \
                    and ekind(gold, ge) == ekind(pred, pe):
                self.events[pe] = ge

        # ---- placeholder propositions
        holders = lambda view: sorted(i for i, r in view.by_id["propositions"].items() if r.get("placeholder"))
        self.placeholders: Dict[str, str] = {i: i for i in holders(pred) if i in base_ids}
        gs, ps = free(self.placeholders, holders(gold), holders(pred))
        self.placeholders.update(_greedy(gs, ps,
                                         lambda g, p: _item_score(g_items("PLACEHOLDER", g), p_items("PLACEHOLDER", p)),
                                         lambda g, p: True, self.ambiguities))

    def entity_value(self, view: _View, entity_id: str, translate: bool) -> str:
        """Gold identity class of an entity. A predicted entity with no counterpart of its own inherits
        the counterpart of another member of its identity class (split entity joined by SameAs in scope)."""
        if not translate:
            return self.gold.entity_class(entity_id)
        for member in [entity_id] + view.class_members(entity_id):
            if member in self.entities:
                return self.gold.entity_class(self.entities[member])
        return f"?{view.entity_class(entity_id)}"

    def _literal(self, predicate: str, name: str, value: Any) -> Any:
        return self.literal_groups.get((predicate, name, value), value)

    def signature(self, view: _View, proposition_id: str, translate: bool) -> str:
        """Content signature in GOLD terms. `translate` is True for the predicted document."""
        prop = view.by_id["propositions"][proposition_id]
        if prop.get("placeholder"):
            target = self.placeholders.get(proposition_id, f"?{proposition_id}") if translate else proposition_id
            return json.dumps(["PLACEHOLDER", target])
        predicate = prop["predicate"]
        parts = []
        for name in sorted(prop["args"]):
            arg = prop["args"][name]
            kind = arg["kind"]
            if kind == "LITERAL":
                value: Any = [arg["value_type"], self._literal(predicate, name, arg["value"])]
            elif kind == "TOKEN":
                value = [arg["vocabulary"], arg["value"]]
            elif kind == "PROPOSITION":
                value = self.signature(view, arg["ref"], translate)
            elif kind == "MENTION":
                value = [str(x) for x in view.mention_key(arg["ref"])]
            elif kind == "ENTITY":
                value = self.entity_value(view, arg["ref"], translate)
            else:
                table = {"EVENT": self.events, "ANCHOR": self.anchors}[kind]
                value = table.get(arg["ref"], f"?{arg['ref']}") if translate else arg["ref"]
            parts.append([name, kind, value])
        if view.registry["predicates"].get(predicate, {}).get("directionality") == "SYMMETRIC":
            parts = [["*", parts[0][1], v] for v in sorted(json.dumps(p[2]) for p in parts)]
        return json.dumps([predicate, parts], ensure_ascii=False, separators=(",", ":"))

    def is_reflexive_identity(self, view: _View, proposition_id: str, translate: bool) -> bool:
        prop = view.by_id["propositions"][proposition_id]
        if prop.get("predicate") != "SameAs":
            return False
        first, second = (self.entity_value(view, prop["args"][n]["ref"], translate) for n in ("first", "second"))
        return not first.startswith("?") and first == second

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


def _literal_groups(case_spec: Dict[str, Any]) -> Dict:
    """Case-declared acceptable literal variants: every listed value maps to the first one."""
    groups = {}
    for entry in case_spec.get("literal_variants", ()):
        for value in entry["values"]:
            groups[(entry["predicate"], entry["argument"], value)] = entry["values"][0]
    return groups


def evaluate_case(base_document: Dict[str, Any], gold_batch: Dict[str, Any], predicted_batch: Dict[str, Any],
                  acceptable_gold_assertion_ids=(), ingestion: Optional[Any] = None,
                  case_spec: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Score one case.

    case_spec (all optional):
      mode                       SYNTHETIC_COMPLETE (default) or REAL_SOURCE
      gold_completeness          COMPLETE_FOR_PROFILE, INCOMPLETE or UNCERTAIN (REAL_SOURCE only)
      acceptable_assertion_ids   gold assertions that are correct but optional
      narrow_span_segments       segment ids where only the exact gold span is accepted (mixed roles)
      literal_variants           [{predicate, argument, values: [...]}] accepted wordings of one literal
      adjudications              [{content_key, state, severity?, failure_code?}] reviewer decisions on
                                 predictions that match no gold assertion
    """
    spec = dict(case_spec or {})
    mode = spec.get("mode", "SYNTHETIC_COMPLETE")
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode}")
    completeness = spec.get("gold_completeness", "COMPLETE_FOR_PROFILE")
    if completeness not in GOLD_COMPLETENESS:
        raise ValueError(f"unknown gold_completeness {completeness}")
    acceptable = set(acceptable_gold_assertion_ids) | set(spec.get("acceptable_assertion_ids", ()))
    narrow = frozenset(spec.get("narrow_span_segments", ()))
    adjudications = {}
    for entry in spec.get("adjudications", ()):
        if entry["state"] not in ADJUDICATION_STATES:
            raise ValueError(f"unknown adjudication state {entry['state']}")
        if entry["state"] == "UNSUPPORTED_ASSERTION" and entry.get("severity") not in SEVERITIES:
            raise ValueError("an UNSUPPORTED_ASSERTION adjudication needs a severity")
        adjudications[entry["content_key"]] = entry

    registry = load_registry()
    result: Dict[str, Any] = {"evaluator_version": EVALUATOR_VERSION, "mode": mode, "failures": [],
                              "unmatched_predictions": []}
    if mode == "REAL_SOURCE":
        result["gold_completeness"] = completeness
    gold_report = validate_batch(gold_batch, base_document, ingestion)
    if not gold_report["pass"]:
        raise ValueError(f"gold batch is not valid: {gold_report['checks']}")
    pred_report = validate_batch(predicted_batch, base_document, ingestion)
    result["l0_structural_validity"] = pred_report["pass"]
    if not pred_report["pass"]:
        result["failures"].append({"code": "CANONICAL_CONFORMANCE_FAILURE", "material": True,
                                   "detail": [i for c in pred_report["checks"].values() for i in c["issues"]][:10]})
        result.update(metrics=None, failure_codes=["CANONICAL_CONFORMANCE_FAILURE"],
                      full_canonical_case_success=False, case_outcome="FAIL")
        return result

    gold = _View(merge(gold_batch, base_document), gold_batch["candidate_records"], registry)
    pred = _View(merge(predicted_batch, base_document), predicted_batch["candidate_records"], registry)
    base_ids = {r["id"] for name in CANDIDATE_COLLECTIONS for r in base_document[name]}
    align = _Alignment(gold, pred, base_ids, _literal_groups(spec))
    result["alignment_ambiguities"] = align.ambiguities

    def fail(code, material=True, **detail):
        result["failures"].append({"code": code, "material": material and code not in NON_MATERIAL_FAILURES, **detail})

    gold_assertions = [a for a in gold.assertions if a["id"] in gold.candidate_ids["assertions"]]
    pred_assertions = [a for a in pred.assertions if a["id"] in pred.candidate_ids["assertions"]]
    gold_by_key: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    gold_by_signature: Dict[str, Dict[str, Any]] = {}
    for a in gold_assertions:
        signature = align.signature(gold, a["proposition_id"], False)
        gold_by_key.setdefault((signature, a["polarity"]), []).append(a)
        gold_by_signature[signature] = a
    matched: Dict[str, Dict[str, Any]] = {}            # gold assertion id -> predicted assertion
    holder_relative = set(registry["holder_relative_predicates"])
    embedded_content, gold_resolutions = set(), {}
    for a in gold.assertions:
        prop = gold.proposition(a)
        if prop.get("predicate") in holder_relative:
            embedded_content.add(align.signature(gold, prop["args"]["content"]["ref"], False))
        if prop.get("predicate") == "RefersTo":
            gold_resolutions[gold.mention_key(prop["args"]["mention"]["ref"])] = prop["args"]["entity"]["ref"]
    gold_span_roles = [(gold.span_key(r["id"]), r["role"]) for r in gold.doc["evidence_refs"]]
    roles_by_segment: Dict[str, set] = {}
    for (segment_id, _, _), role in gold_span_roles:
        roles_by_segment.setdefault(segment_id, set()).add(role)
    narrow = narrow | frozenset(s for s, roles in roles_by_segment.items() if len(roles) > 1)
    result["narrow_span_segments"] = len(narrow)

    def premise_keys(view, derivation, translate):
        return derivation["rule_id"], frozenset(
            (align.signature(view, view.by_id["assertions"][x]["proposition_id"], translate),
             view.by_id["assertions"][x]["polarity"]) for x in derivation["premise_assertion_ids"])

    def grounding(g, p) -> str:
        gold_sets, pred_sets = gold.sufficient_sets(g["support"]), pred.sufficient_sets(p["support"])
        relations = [_set_relation(ps, gs, narrow) for ps in pred_sets for gs in gold_sets]
        if "MATCH" in relations:
            return "MATCH"
        if {premise_keys(pred, d, True) for d in p["support"]["derivations"]} & \
                {premise_keys(gold, d, False) for d in g["support"]["derivations"]}:
            return "MATCH"
        return "SUBSET" if "SUBSET" in relations else "MISMATCH"

    counts = {"matched_predictions": 0, "duplicates": 0, "grounded": 0, "epistemic_equal": 0, "unsupported": 0,
              "pending_adjudication": 0, "valid_additional": 0, "out_of_scope": 0, "equivalent_representation": 0}
    grounded_ids = set()
    for p in pred_assertions:
        signature = align.signature(pred, p["proposition_id"], True)
        predicate = pred.proposition(p).get("predicate")
        candidates = gold_by_key.get((signature, p["polarity"]))
        g = None
        if candidates:
            # The same proposition may hold over several intervals: prefer the gold assertion with the
            # same validity, then any gold assertion not matched yet.
            open_candidates = [c for c in candidates if c["id"] not in matched]
            same_validity = [c for c in open_candidates
                             if align.validity(gold, c, False) == align.validity(pred, p, True)]
            g = (same_validity or open_candidates or candidates)[0]
        if g is None:
            if signature in gold_by_signature:
                hint = "WRONG_POLARITY"
            elif signature in embedded_content:
                hint = "HOLDER_RELATIVE_TRUTH_LEAK"
            elif predicate in CAUSAL_PREDICATES:
                hint = "INVENTED_CAUSALITY"
            elif predicate == "RefersTo" and \
                    pred.mention_key(pred.proposition(p)["args"]["mention"]["ref"]) in gold_resolutions:
                hint = "WRONG_ENTITY_RESOLUTION"
            else:
                hint = "UNSUPPORTED_ASSERTION"
            content_key = f"{signature}|{p['polarity']}"
            entry = {"content_key": content_key, "predicate": predicate, "mechanical_hint": hint}
            decision = adjudications.get(content_key)
            if align.is_reflexive_identity(pred, p["proposition_id"], True) and \
                    not any(align.is_reflexive_identity(gold, a["proposition_id"], False) for a in gold_assertions):
                entry["state"] = "EQUIVALENT_REPRESENTATION"      # split entity + SameAs inside the scope
            elif decision is not None:
                entry.update({k: decision[k] for k in ("state", "severity", "failure_code") if k in decision})
            elif mode == "SYNTHETIC_COMPLETE":
                entry.update(state="UNSUPPORTED_ASSERTION", severity="HIGH")
            elif completeness == "COMPLETE_FOR_PROFILE":
                entry.update(state="UNSUPPORTED_ASSERTION", severity="UNRATED")
            else:
                entry["state"] = PENDING
            result["unmatched_predictions"].append(entry)
            state = entry["state"]
            if state == "UNSUPPORTED_ASSERTION":
                counts["unsupported"] += 1
                code = entry.get("failure_code", hint)
                fail(code, material=entry["severity"] in MATERIAL_SEVERITIES + ("UNRATED",),
                     predicate=predicate, severity=entry["severity"])
            else:
                counts[{PENDING: "pending_adjudication", "VALID_ADDITIONAL_ASSERTION": "valid_additional",
                        "OUT_OF_SCOPE_ASSERTION": "out_of_scope",
                        "EQUIVALENT_REPRESENTATION": "equivalent_representation"}[state]] += 1
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
        relation = grounding(g, p)
        if relation == "MATCH":
            counts["grounded"] += 1
            grounded_ids.add(g["id"])
        else:
            fail("INSUFFICIENT_SUPPORT_MARKED_SUFFICIENT" if relation == "SUBSET" else "WRONG_EVIDENCE_SPAN",
                 predicate=predicate)

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
        roles = {role for gold_span, role in gold_span_roles if span_matches(key, gold_span, narrow)}
        if roles:
            role_total += 1
            if ref["role"] in roles:
                role_equal += 1
            else:
                fail("WRONG_EVIDENCE_ROLE", predicted=ref["role"], gold=sorted(roles))

    required_resolutions = [a for a in required if gold.proposition(a).get("predicate") == "RefersTo"]
    pending = counts["pending_adjudication"]
    countable = len(pred_assertions) - counts["out_of_scope"] - counts["equivalent_representation"]
    result["counts"] = {"gold_required": len(required), "gold_acceptable": len(gold_assertions) - len(required),
                        "predicted": len(pred_assertions), **counts, "required_recovered": len(recovered)}
    result["metrics"] = {
        "assertion_precision": None if pending else _ratio(counts["matched_predictions"] + counts["valid_additional"],
                                                           countable),
        "assertion_recall": _ratio(len(recovered), len(required)),
        "evidence_grounding_precision": _ratio(counts["grounded"], counts["matched_predictions"]),
        "evidence_grounding_recall": _ratio(sum(1 for a in recovered if a["id"] in grounded_ids), len(required)),
        "epistemic_accuracy": _ratio(counts["epistemic_equal"], counts["matched_predictions"]),
        "evidence_role_accuracy": _ratio(role_equal, role_total),
        "referent_resolution_accuracy": _ratio(sum(1 for a in required_resolutions if a["id"] in matched),
                                               len(required_resolutions)),
        "unsupported_assertion_count": None if pending else counts["unsupported"],
        "unsupported_assertion_rate": None if pending else _ratio(counts["unsupported"], len(pred_assertions)),
        "gold_unmatched_pending_adjudication": pending,
    }
    result["failure_codes"] = sorted({f["code"] for f in result["failures"]})
    material_failure = any(f["material"] for f in result["failures"])
    if material_failure:
        result["case_outcome"], result["full_canonical_case_success"] = "FAIL", False
    elif pending:
        result["case_outcome"], result["full_canonical_case_success"] = "PENDING_ADJUDICATION", None
    else:
        result["case_outcome"], result["full_canonical_case_success"] = "SUCCESS", True
    return result


def aggregate(case_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Micro-aggregate counts over cases, plus the strict case-level endpoint."""
    scored = [r for r in case_results if r.get("metrics") is not None]
    total = lambda key: sum(r["counts"][key] for r in scored)
    pending_cases = sum(1 for r in case_results if r.get("case_outcome") == "PENDING_ADJUDICATION")
    success = sum(1 for r in case_results if r["full_canonical_case_success"] is True)
    final = pending_cases == 0
    return {
        "cases": len(case_results),
        "cases_structurally_invalid": len(case_results) - len(scored),
        "cases_pending_adjudication": pending_cases,
        "full_canonical_case_success_count": success,
        "full_canonical_case_success_rate": _ratio(success, len(case_results)) if final else None,
        "assertion_precision": (_ratio(total("matched_predictions") + total("valid_additional"),
                                       total("predicted") - total("out_of_scope") - total("equivalent_representation"))
                                if scored and final else None),
        "assertion_recall": _ratio(total("required_recovered"), total("gold_required")) if scored else None,
        "unsupported_assertion_rate": _ratio(total("unsupported"), total("predicted")) if scored and final else None,
    }
