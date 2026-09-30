"""Conformance validator for Canonical Story Schema v0 (TASK M2-03).

Two clearly separated layers:

1. STRUCTURAL: JSON Schema Draft 2020-12 validation against
   ``schemas/canonical_story/canonical_story_v0.schema.json``.
2. SEMANTIC: domain invariants JSON Schema cannot express cleanly, grouped as
   reference_integrity, predicate_integrity, support_path_integrity,
   derivation_integrity, evidence_set_integrity, temporal_bound_integrity and
   epistemic_integrity.

Availability (normative for v0):
  completion(SUFFICIENT evidence set) = max discourse position of its refs
  completion(derivation)              = max availability of ALL its premises
  availability(assertion)             = min completion over valid complete paths
CORROBORATING and PARTIAL sets never contribute. REJECTED assertions have no
availability and cannot serve as premises. An ANCHOR validity bound with its
own support becomes available at max(assertion availability, min completion of
its own paths); a bound without its own support shares the assertion's.

This is a format conformance checker, not application logic, and it contains
no story content. It needs no model, API or network.
"""
import argparse
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schemas/canonical_story/canonical_story_v0.schema.json"
REGISTRY_PATH = REPO_ROOT / "schemas/canonical_story/predicate_registry_v0.yaml"

STATUS_RANK = {"SUGGESTED": 0, "ENTAILED": 1, "EXPLICIT": 2}
SEMANTIC_SECTIONS = (
    "reference_integrity",
    "predicate_integrity",
    "support_path_integrity",
    "derivation_integrity",
    "evidence_set_integrity",
    "temporal_bound_integrity",
    "epistemic_integrity",
)
Position = Tuple[int, ...]


@lru_cache(maxsize=1)
def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_registry() -> dict:
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))


def structural_issues(doc: Any) -> List[str]:
    from jsonschema import Draft202012Validator

    validator = Draft202012Validator(load_schema())
    issues = []
    for error in validator.iter_errors(doc):
        path = "/".join(str(p) for p in error.absolute_path) or "<root>"
        issues.append(f"{path}: {error.message}")
    return sorted(issues)


class _Index:
    """Lookup tables over one structurally valid document."""

    def __init__(self, doc: dict, registry: dict):
        self.doc = doc
        self.registry = registry
        self.stream = doc["story"]["discourse_stream_id"]
        self.documents = {d["id"]: d for d in doc["source_documents"]}
        self.segments = {s["id"]: s for s in doc["source_segments"]}
        self.evidence = {e["id"]: e for e in doc["evidence_refs"]}
        self.mentions = {m["id"]: m for m in doc["mentions"]}
        self.entities = {e["id"]: e for e in doc["entities"]}
        self.events = {e["id"]: e for e in doc["events"]}
        self.anchors = {a["id"]: a for a in doc["temporal_anchors"]}
        self.propositions = {p["id"]: p for p in doc["propositions"]}
        self.provenance = {p["id"]: p for p in doc["extraction_provenance"]}
        self.assertions = {a["id"]: a for a in doc["assertions"]}
        self.predicates = registry["predicates"]
        self.rules = registry["derivation_rules"]
        policy = registry["authority_policies"][doc["authority_policy"]]
        self.non_grounding_roles = set(policy.get("roles_not_sufficient_for_story_world", []))

    def predicate_of(self, assertion: dict) -> Optional[str]:
        prop = self.propositions.get(assertion["proposition_id"])
        return prop.get("predicate") if prop else None

    def arg(self, assertion: dict, name: str) -> Optional[dict]:
        prop = self.propositions.get(assertion["proposition_id"]) or {}
        return (prop.get("args") or {}).get(name)


def _all_ids(doc: dict) -> List[Tuple[str, str]]:
    out = [("story", doc["story"]["id"])]
    for key in ("source_documents", "source_segments", "evidence_refs", "mentions", "entities",
                "events", "temporal_anchors", "propositions", "extraction_provenance", "assertions"):
        out += [(key, rec["id"]) for rec in doc[key]]
    for assertion in doc["assertions"]:
        for support in _supports(assertion):
            out += [("evidence_set", s["id"]) for s in support["evidence_sets"]]
            out += [("derivation", d["id"]) for d in support["derivations"]]
    return out


def _supports(assertion: dict) -> List[dict]:
    """The assertion's support plus any bound-level supports."""
    supports = [assertion["support"]]
    for side in ("start", "end"):
        bound = (assertion.get("validity") or {}).get(side) or {}
        if bound.get("support"):
            supports.append(bound["support"])
    return supports


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------

class Availability:
    """Computes availability positions per the normative v0 rule."""

    def __init__(self, index: _Index):
        self.ix = index
        self._memo: Dict[str, Optional[Position]] = {}
        self._visiting: Set[str] = set()
        self.cycles: Set[str] = set()

    def set_completion(self, evidence_set: dict) -> Optional[Position]:
        if evidence_set["label"] != "SUFFICIENT":
            return None
        positions = []
        for ref_id in evidence_set["evidence_ref_ids"]:
            ref = self.ix.evidence.get(ref_id)
            if ref is None or ref["position"]["stream_id"] != self.ix.stream:
                return None
            if ref["role"] in self.ix.non_grounding_roles:
                return None
            positions.append(tuple(ref["position"]["key"]))
        return max(positions)

    def derivation_completion(self, derivation: dict) -> Optional[Position]:
        if derivation["rule_id"] not in self.ix.rules:
            return None
        premise_positions = []
        for premise_id in derivation["premise_assertion_ids"]:
            position = self.of(premise_id)
            if position is None:
                return None
            premise_positions.append(position)
        return max(premise_positions)

    def support_completion(self, support: dict) -> Optional[Position]:
        completions = [self.set_completion(s) for s in support["evidence_sets"]]
        completions += [self.derivation_completion(d) for d in support["derivations"]]
        completions = [c for c in completions if c is not None]
        return min(completions) if completions else None

    def of(self, assertion_id: str) -> Optional[Position]:
        if assertion_id in self._memo:
            return self._memo[assertion_id]
        assertion = self.ix.assertions.get(assertion_id)
        if assertion is None or assertion["review"]["state"] == "REJECTED":
            return None
        if assertion_id in self._visiting:
            self.cycles.add(assertion_id)
            return None
        self._visiting.add(assertion_id)
        result = self.support_completion(assertion["support"])
        self._visiting.discard(assertion_id)
        self._memo[assertion_id] = result
        return result

    def bound(self, assertion_id: str, side: str) -> Optional[Position]:
        own = self.of(assertion_id)
        bound = (self.ix.assertions[assertion_id].get("validity") or {}).get(side)
        if own is None or not bound or bound["kind"] == "OPEN":
            return own
        if not bound.get("support"):
            return own
        bound_completion = self.support_completion(bound["support"])
        return None if bound_completion is None else max(own, bound_completion)


def availability_map(doc: dict, registry: Optional[dict] = None) -> Dict[str, Optional[List[int]]]:
    """Availability per assertion (as key lists), for a structurally valid document."""
    calc = Availability(_Index(doc, registry or load_registry()))
    return {aid: (list(p) if p is not None else None)
            for aid in sorted(calc.ix.assertions) for p in [calc.of(aid)]}


# ---------------------------------------------------------------------------
# Semantic checks
# ---------------------------------------------------------------------------

def _check_references(ix: _Index, issues: List[str]) -> None:
    seen: Dict[str, str] = {}
    for kind, rid in _all_ids(ix.doc):
        if rid in seen:
            issues.append(f"duplicate id {rid} ({seen[rid]} and {kind})")
        seen[rid] = kind
    story_id = ix.doc["story"]["id"]
    for d in ix.documents.values():
        if d["story_id"] != story_id:
            issues.append(f"source document {d['id']} references unknown story {d['story_id']}")
    for s in ix.segments.values():
        if s["document_id"] not in ix.documents:
            issues.append(f"segment {s['id']} references unknown document {s['document_id']}")
    for e in ix.evidence.values():
        if e["segment_id"] not in ix.segments:
            issues.append(f"evidence ref {e['id']} references unknown segment {e['segment_id']}")
        if e["position"]["stream_id"] != ix.stream:
            issues.append(f"evidence ref {e['id']} position is outside the story discourse stream")
    for m in ix.mentions.values():
        if m["evidence_ref_id"] not in ix.evidence:
            issues.append(f"mention {m['id']} references unknown evidence ref {m['evidence_ref_id']}")
    for ev in ix.events.values():
        anchor = ix.anchors.get(ev["anchor_id"])
        if anchor is None:
            issues.append(f"event {ev['id']} references unknown anchor {ev['anchor_id']}")
        elif anchor.get("event_id") != ev["id"]:
            issues.append(f"event {ev['id']} anchor {anchor['id']} is not an EVENT_TIME anchor of that event")
    for an in ix.anchors.values():
        if an.get("event_id") and an["event_id"] not in ix.events:
            issues.append(f"anchor {an['id']} references unknown event {an['event_id']}")
    targets = {"ENTITY": ix.entities, "EVENT": ix.events, "ANCHOR": ix.anchors,
               "MENTION": ix.mentions, "PROPOSITION": ix.propositions}
    for p in ix.propositions.values():
        for name, arg in (p.get("args") or {}).items():
            if arg["kind"] in targets and arg["ref"] not in targets[arg["kind"]]:
                issues.append(f"proposition {p['id']} argument {name} references unknown {arg['kind']} {arg['ref']}")
    for a in ix.assertions.values():
        if a["proposition_id"] not in ix.propositions:
            issues.append(f"assertion {a['id']} references unknown proposition {a['proposition_id']}")
        if a["extraction_provenance_id"] not in ix.provenance:
            issues.append(f"assertion {a['id']} references unknown extraction provenance")
        corrected = a["review"].get("corrects_assertion_id")
        if corrected and corrected not in ix.assertions:
            issues.append(f"assertion {a['id']} review corrects unknown assertion {corrected}")
        for alt in (a.get("textual_ambiguity") or {}).get("alternative_proposition_ids", []):
            if alt not in ix.propositions:
                issues.append(f"assertion {a['id']} ambiguity references unknown proposition {alt}")
    # Proposition embedding must be acyclic.
    state: Dict[str, int] = {}

    def visit(pid: str) -> bool:
        if state.get(pid) == 1:
            return True
        if state.get(pid) == 2:
            return False
        state[pid] = 1
        for arg in (ix.propositions.get(pid, {}).get("args") or {}).values():
            if arg["kind"] == "PROPOSITION" and arg["ref"] in ix.propositions and visit(arg["ref"]):
                return True
        state[pid] = 2
        return False

    for pid in sorted(ix.propositions):
        if visit(pid):
            issues.append(f"proposition embedding cycle through {pid}")
            break


def _check_predicates(ix: _Index, issues: List[str]) -> None:
    vocab = ix.registry["vocabularies"]
    forbidden = set(ix.registry["forbidden_stored_verdicts"])
    for ev in ix.events.values():
        if ev["event_kind"] not in vocab["event_kind"]:
            issues.append(f"event {ev['id']} has unregistered event_kind {ev['event_kind']}")
    for p in ix.propositions.values():
        if p.get("placeholder"):
            continue
        pred = p["predicate"]
        if pred.upper() in forbidden:
            issues.append(f"proposition {p['id']} uses forbidden stored verdict predicate {pred}")
            continue
        spec = ix.predicates.get(pred)
        if spec is None:
            issues.append(f"proposition {p['id']} uses unregistered predicate {pred}")
            continue
        expected = {a["name"]: a for a in spec["args"]}
        if set(p["args"]) != set(expected):
            issues.append(f"proposition {p['id']} arity mismatch for {pred}: "
                          f"got {sorted(p['args'])}, expected {sorted(expected)}")
            continue
        for name, arg in p["args"].items():
            want = expected[name]
            if arg["kind"] != want["kind"]:
                issues.append(f"proposition {p['id']} {pred}.{name} kind {arg['kind']} != {want['kind']}")
                continue
            if want["kind"] == "TOKEN":
                if arg["vocabulary"] != want["vocabulary"]:
                    issues.append(f"proposition {p['id']} {pred}.{name} vocabulary {arg['vocabulary']} != {want['vocabulary']}")
                elif arg["value"].upper() in forbidden:
                    issues.append(f"proposition {p['id']} {pred}.{name} stores forbidden verdict {arg['value']}")
                elif arg["value"] not in vocab[want["vocabulary"]]:
                    issues.append(f"proposition {p['id']} {pred}.{name} value {arg['value']} not in {want['vocabulary']}")
            if want["kind"] == "LITERAL" and arg["value_type"] != want["value_type"]:
                issues.append(f"proposition {p['id']} {pred}.{name} literal type {arg['value_type']} != {want['value_type']}")
            if want["kind"] == "ENTITY" and want.get("entity_kinds"):
                entity = ix.entities.get(arg["ref"])
                if entity and entity["kind"] not in want["entity_kinds"]:
                    issues.append(f"proposition {p['id']} {pred}.{name} entity kind {entity['kind']} not in {want['entity_kinds']}")


def _check_evidence_sets(ix: _Index, issues: List[str]) -> None:
    for a in ix.assertions.values():
        for support in _supports(a):
            for s in support["evidence_sets"]:
                for ref_id in s["evidence_ref_ids"]:
                    ref = ix.evidence.get(ref_id)
                    if ref is None:
                        issues.append(f"assertion {a['id']} evidence set {s['id']} references unknown evidence ref {ref_id}")
                    elif s["label"] == "SUFFICIENT" and ref["role"] in ix.non_grounding_roles:
                        issues.append(
                            f"assertion {a['id']} evidence set {s['id']} is SUFFICIENT but contains "
                            f"{ref['role']} evidence, which policy {ix.doc['authority_policy']} does not accept "
                            "as story-world grounding")


def _check_support_paths(ix: _Index, calc: Availability, issues: List[str]) -> None:
    for a in ix.assertions.values():
        if a["review"]["state"] == "REJECTED":
            continue
        support = a["support"]
        if not any(s["label"] == "SUFFICIENT" for s in support["evidence_sets"]) and not support["derivations"]:
            issues.append(f"assertion {a['id']} has no support path (needs a SUFFICIENT evidence set or a derivation)")
        elif calc.of(a["id"]) is None:
            issues.append(f"assertion {a['id']} has no complete support path (availability undefined)")


def _check_derivations(ix: _Index, calc: Availability, issues: List[str]) -> None:
    holder_relative = set(ix.registry["holder_relative_predicates"])
    for a in ix.assertions.values():
        conclusion_pred = ix.predicate_of(a)
        for support in _supports(a):
            for d in support["derivations"]:
                rule = ix.rules.get(d["rule_id"])
                if rule is None:
                    issues.append(f"assertion {a['id']} derivation {d['id']} uses unregistered rule {d['rule_id']}")
                premises = []
                for pid in d["premise_assertion_ids"]:
                    premise = ix.assertions.get(pid)
                    if premise is None:
                        issues.append(f"assertion {a['id']} derivation {d['id']} premise {pid} does not exist")
                        continue
                    if pid == a["id"]:
                        issues.append(f"assertion {a['id']} derivation {d['id']} uses itself as a premise")
                    if premise["review"]["state"] == "REJECTED":
                        issues.append(f"assertion {a['id']} derivation {d['id']} relies on REJECTED premise {pid}")
                    premises.append(premise)
                    if ix.predicate_of(premise) in holder_relative:
                        content = ix.arg(premise, "content")
                        if content and content["ref"] == a["proposition_id"]:
                            issues.append(
                                f"assertion {a['id']} derivation {d['id']} concludes the embedded content of "
                                f"holder-relative premise {pid}; a belief or report never establishes its content")
                if rule is None or support is not a["support"]:
                    continue
                if conclusion_pred not in rule["conclusion_predicates"]:
                    issues.append(f"assertion {a['id']} derivation {d['id']} rule {d['rule_id']} cannot conclude {conclusion_pred}")
                kinds = rule.get("conclusion_attitude_kinds")
                attitude = ix.arg(a, "attitude")
                if kinds and attitude and attitude["value"] not in kinds:
                    issues.append(f"assertion {a['id']} derivation {d['id']} rule {d['rule_id']} cannot conclude attitude {attitude['value']}")
                present = {ix.predicate_of(p) for p in premises}
                missing = [pred for pred in rule["required_premise_predicates"] if pred not in present]
                if missing:
                    issues.append(f"assertion {a['id']} derivation {d['id']} lacks required premise predicates {missing}")
    for aid in sorted(ix.assertions):
        calc.of(aid)
    for aid in sorted(calc.cycles):
        issues.append(f"derivation cycle through assertion {aid}")


def _check_temporal(ix: _Index, calc: Availability, issues: List[str]) -> None:
    for a in ix.assertions.values():
        validity = a.get("validity")
        if not validity:
            continue
        spec = ix.predicates.get(ix.predicate_of(a) or "", {})
        if not spec.get("stative"):
            issues.append(f"assertion {a['id']} has validity but predicate {ix.predicate_of(a)} is not stative")
        for side in ("start", "end"):
            bound = validity[side]
            if bound["kind"] != "ANCHOR":
                continue
            if bound["anchor_id"] not in ix.anchors:
                issues.append(f"assertion {a['id']} validity {side} references unknown anchor {bound['anchor_id']}")
                continue
            if bound.get("support") and a["review"]["state"] != "REJECTED":
                if calc.support_completion(bound["support"]) is None:
                    issues.append(f"assertion {a['id']} validity {side} bound has support but no complete path")
        start, end = validity["start"], validity["end"]
        if start["kind"] == end["kind"] == "ANCHOR" and start["anchor_id"] == end["anchor_id"]:
            issues.append(f"assertion {a['id']} validity starts and ends at the same anchor")


def _check_epistemic(ix: _Index, calc: Availability, issues: List[str]) -> None:
    for a in ix.assertions.values():
        if a["review"]["state"] == "REJECTED":
            continue
        status = a["epistemic_status"]
        sets = a["support"]["evidence_sets"]
        direct = [s for s in sets if s["label"] == "SUFFICIENT" and calc.set_completion(s) is not None]
        if status == "EXPLICIT" and not direct:
            issues.append(f"assertion {a['id']} is EXPLICIT without a complete direct evidence path "
                          "(inferred assertions cannot be EXPLICIT)")
        if not direct and a["support"]["derivations"]:
            caps = []
            for d in a["support"]["derivations"]:
                rule = ix.rules.get(d["rule_id"])
                premises = [ix.assertions[p] for p in d["premise_assertion_ids"] if p in ix.assertions]
                if rule is None or not premises:
                    continue
                cap = min([STATUS_RANK[rule["max_status"]]] + [STATUS_RANK[p["epistemic_status"]] for p in premises])
                caps.append(cap)
            if caps and STATUS_RANK[status] > max(caps):
                issues.append(f"assertion {a['id']} status {status} exceeds what its derivations support")
        spec = ix.predicates.get(ix.predicate_of(a) or "", {})
        if spec.get("epistemic_gate") == "INTERNAL_STATE" and status == "EXPLICIT":
            ok_roles = {"DEPICTION", "NARRATION_SUMMARY"}
            if not any(any(ix.evidence[r]["role"] in ok_roles for r in s["evidence_ref_ids"] if r in ix.evidence)
                       for s in direct):
                issues.append(f"assertion {a['id']} states an internal state as EXPLICIT without DEPICTION or "
                              "NARRATION_SUMMARY evidence (self-report alone is not sufficient)")


def validate_document(doc: Any, registry: Optional[dict] = None) -> Dict[str, Any]:
    """Return a deterministic conformance report for one document."""
    registry = registry or load_registry()
    structural = structural_issues(doc)
    report: Dict[str, Any] = {
        "structural": {"layer": "JSON_SCHEMA_DRAFT_2020_12", "pass": not structural, "issues": structural},
        "semantic": {},
        "availability": {},
    }
    if structural:
        for section in SEMANTIC_SECTIONS:
            report["semantic"][section] = {"pass": None, "issues": ["SKIPPED: structural validation failed"]}
        report["pass"] = False
        return report
    ix = _Index(doc, registry)
    calc = Availability(ix)
    checks = {
        "reference_integrity": lambda out: _check_references(ix, out),
        "predicate_integrity": lambda out: _check_predicates(ix, out),
        "evidence_set_integrity": lambda out: _check_evidence_sets(ix, out),
        "derivation_integrity": lambda out: _check_derivations(ix, calc, out),
        "support_path_integrity": lambda out: _check_support_paths(ix, calc, out),
        "temporal_bound_integrity": lambda out: _check_temporal(ix, calc, out),
        "epistemic_integrity": lambda out: _check_epistemic(ix, calc, out),
    }
    for section in SEMANTIC_SECTIONS:
        out: List[str] = []
        try:
            checks[section](out)
        except KeyError as exc:  # unresolved reference already reported elsewhere
            out.append(f"check aborted on unresolved reference {exc}")
        report["semantic"][section] = {"pass": not out, "issues": sorted(set(out))}
    report["availability"] = {
        aid: {
            "assertion": list(p) if p is not None else None,
            "validity_start": _as_list(calc.bound(aid, "start")) if ix.assertions[aid].get("validity") else None,
            "validity_end": _as_list(calc.bound(aid, "end")) if ix.assertions[aid].get("validity") else None,
        }
        for aid in sorted(ix.assertions) for p in [calc.of(aid)]
    }
    report["pass"] = all(v["pass"] for v in report["semantic"].values())
    return report


def _as_list(position: Optional[Position]) -> Optional[List[int]]:
    return list(position) if position is not None else None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Canonical Story Schema v0 conformance validator")
    parser.add_argument("documents", nargs="+")
    parser.add_argument("--report", help="write a combined machine-readable report to this path")
    args = parser.parse_args(argv)
    combined = {"schema": str(SCHEMA_PATH.relative_to(REPO_ROOT)).replace("\\", "/"),
                "registry": str(REGISTRY_PATH.relative_to(REPO_ROOT)).replace("\\", "/"),
                "documents": {}}
    all_pass = True
    for path in args.documents:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        report = validate_document(doc)
        combined["documents"][Path(path).name] = report
        all_pass &= report["pass"]
    text = json.dumps(combined, indent=2, sort_keys=True) + "\n"
    if args.report:
        Path(args.report).write_text(text, encoding="utf-8", newline="\n")
    else:
        print(text)
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
