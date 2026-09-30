"""Reference as-of projection for Canonical Story Schema v0 (TASK M2-04).

``project_as_of(document, discourse_position)`` returns a derived, disposable
view: which assertions are visible at position N and what follows from them.
The view is NOT a Canonical Story record and is never written back.

Normative rules (see docs/research/m2/M2_AS_OF_PROJECTION_V0.md):
- An assertion is visible iff review.state != REJECTED and availability <= N,
  using the shared availability rule from conformance_v0 (no second calculator).
- A validity bound is shown only if its own availability <= N; otherwise OPEN.
- Referents appear only if a visible assertion (or visible mention) references them.
- Identity, mention and content resolution use only visible, canonically
  AFFIRMED SameAs / RefersTo / SameContent assertions; records are never mutated.
- KNOWS / MISTAKEN / UNRESOLVED_BELIEF, relationships, secrets, reported claims,
  reader reveals and event occurrence are computed here and never stored.
- Reader reveal is valid only under DEFAULT_V0's reliable-narration assumption.

Deterministic, pure (input is deep-copied), and free of storage, model, API or
network dependencies.
"""
import copy
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from tools.canonical_story.conformance_v0 import (
    availability_calculator,
    load_registry,
    validate_document,
)

VIEW_FORMAT = "canonical_story_view/v0"
READER_ASSUMPTION = "DEFAULT_V0_RELIABLE_NARRATION"
HOLDS_TRUE = "HOLDS_TRUE"


class ProjectionError(ValueError):
    """Raised when a view cannot be defined for the given document."""


class _UnionFind:
    def __init__(self, items: Iterable[str]):
        self.parent = {i: i for i in items}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            keep, drop = sorted((ra, rb))
            self.parent[drop] = keep

    def classes(self) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        for item in sorted(self.parent):
            out.setdefault(self.find(item), []).append(item)
        return out


def project_as_of(document: dict, discourse_position: Sequence[int],
                  registry: Optional[dict] = None, validate: bool = True) -> Dict[str, Any]:
    """Project the canonical document to a leak-free view as of ``discourse_position``."""
    registry = registry or load_registry()
    if validate:
        report = validate_document(document, registry)
        if not report["pass"]:
            raise ProjectionError("document does not conform to Canonical Story Schema v0")
    if document.get("authority_policy") != "DEFAULT_V0":
        raise ProjectionError("as-of semantics (including reader reveal) are defined only for DEFAULT_V0")
    if not discourse_position or not all(isinstance(k, int) and k >= 0 for k in discourse_position):
        raise ProjectionError("discourse_position must be a non-empty list of non-negative integers")
    doc = copy.deepcopy(document)
    return _Projector(doc, registry, tuple(discourse_position)).build()


class _Projector:
    def __init__(self, doc: dict, registry: dict, n: Tuple[int, ...]):
        self.doc, self.registry, self.n = doc, registry, n
        self.calc = availability_calculator(doc, registry)
        self.ix = self.calc.ix
        self.diagnostics: List[Dict[str, Any]] = []
        self.visible = {
            aid: a for aid, a in sorted(self.ix.assertions.items())
            if a["review"]["state"] != "REJECTED" and self._le(self.calc.of(aid))
        }

    # -- helpers -----------------------------------------------------------
    def _le(self, position) -> bool:
        return position is not None and tuple(position) <= self.n

    def _pred(self, assertion: dict) -> Optional[str]:
        return self.ix.predicate_of(assertion)

    def _arg(self, assertion: dict, name: str) -> Optional[dict]:
        return self.ix.arg(assertion, name)

    def _by_predicate(self, predicate: str) -> List[dict]:
        return [a for a in self.visible.values() if self._pred(a) == predicate]

    def _validity(self, aid: str) -> Optional[Dict[str, Any]]:
        validity = self.ix.assertions[aid].get("validity")
        if not validity:
            return None
        out = {}
        for side in ("start", "end"):
            bound = validity[side]
            if bound["kind"] == "ANCHOR" and self._le(self.calc.bound(aid, side)):
                out[side] = {"kind": "ANCHOR", "anchor_id": bound["anchor_id"]}
            else:
                out[side] = {"kind": "OPEN"}
        return out

    def _support(self, aid: str) -> Dict[str, List[str]]:
        support = self.ix.assertions[aid]["support"]
        grounding = [s["id"] for s in support["evidence_sets"] if self._le(self.calc.set_completion(s))]
        other = []
        for s in support["evidence_sets"]:
            if s["label"] == "SUFFICIENT":
                continue
            positions = [tuple(self.ix.evidence[r]["position"]["key"]) for r in s["evidence_ref_ids"]]
            if max(positions) <= self.n:
                other.append(s["id"])
        derivations = [d["id"] for d in support["derivations"] if self._le(self.calc.derivation_completion(d))]
        return {"sufficient_evidence_sets": grounding, "derivations": derivations,
                "non_grounding_evidence_sets": other}

    # -- referents ---------------------------------------------------------
    def _referents(self) -> Dict[str, List[str]]:
        found = {"ENTITY": set(), "EVENT": set(), "ANCHOR": set(), "MENTION": set(), "PROPOSITION": set()}

        def walk(pid: str) -> None:
            if pid in found["PROPOSITION"]:
                return
            found["PROPOSITION"].add(pid)
            for arg in (self.ix.propositions[pid].get("args") or {}).values():
                if arg["kind"] == "PROPOSITION":
                    walk(arg["ref"])
                elif arg["kind"] in found:
                    found[arg["kind"]].add(arg["ref"])

        for aid, a in self.visible.items():
            walk(a["proposition_id"])
            for side, bound in (self._validity(aid) or {}).items():
                if bound["kind"] == "ANCHOR":
                    found["ANCHOR"].add(bound["anchor_id"])
        for mid in self.visible_mentions:
            found["MENTION"].add(mid)
        for ev in found["EVENT"]:
            found["ANCHOR"].add(self.ix.events[ev]["anchor_id"])
        return {k: sorted(v) for k, v in found.items()}

    # -- commitments -------------------------------------------------------
    def _disjoint(self, a: str, b: str) -> bool:
        """Provably disjoint only when one interval ends at the anchor where the other starts."""
        va, vb = self._validity(a), self._validity(b)
        if not va or not vb:
            return False

        def meets(x, y):
            return (x["end"]["kind"] == "ANCHOR" and y["start"]["kind"] == "ANCHOR"
                    and x["end"]["anchor_id"] == y["start"]["anchor_id"])
        return meets(va, vb) or meets(vb, va)

    def _status(self, assertion_ids: List[str]) -> Dict[str, Any]:
        groups = {"AFFIRMED": [], "NEGATED": [], "OPEN": []}
        for aid in sorted(assertion_ids):
            groups[self.visible[aid]["polarity"]].append(aid)
        if groups["AFFIRMED"] and groups["NEGATED"]:
            disjoint = all(self._disjoint(x, y) for x in groups["AFFIRMED"] for y in groups["NEGATED"])
            status = "TIME_SCOPED" if disjoint else "CONTESTED"
        elif groups["AFFIRMED"]:
            status = "AFFIRMED"
        elif groups["NEGATED"]:
            status = "NEGATED"
        elif groups["OPEN"]:
            status = "OPEN"
        else:
            status = "UNCOMMITTED"
        return {"status": status, "affirmed": groups["AFFIRMED"], "negated": groups["NEGATED"],
                "open": groups["OPEN"]}

    def _direct_status(self, proposition_id: str) -> str:
        ids = [aid for aid, a in self.visible.items() if a["proposition_id"] == proposition_id]
        return self._status(ids)["status"]

    # -- build -------------------------------------------------------------
    def build(self) -> Dict[str, Any]:
        self.visible_mentions = sorted(
            mid for mid, m in self.ix.mentions.items()
            if tuple(self.ix.evidence[m["evidence_ref_id"]]["position"]["key"]) <= self.n)
        referents = self._referents()
        identity = self._identity(referents["ENTITY"])
        content = self._content(referents["PROPOSITION"])
        commitments = self._commitments(referents["PROPOSITION"])
        view = {
            "view_format": VIEW_FORMAT,
            "derived": True,
            "as_of": {"stream_id": self.ix.stream, "key": list(self.n)},
            "authority_assumption": READER_ASSUMPTION,
            "visible_assertions": {
                aid: {
                    "proposition_id": a["proposition_id"],
                    "predicate": self._pred(a),
                    "polarity": a["polarity"],
                    "epistemic_status": a["epistemic_status"],
                    "review_state": a["review"]["state"],
                    "availability": list(self.calc.of(aid)),
                    "visible_support": self._support(aid),
                    "validity": self._validity(aid),
                } for aid, a in self.visible.items()
            },
            "visible_referents": {
                "entities": referents["ENTITY"], "events": referents["EVENT"],
                "anchors": referents["ANCHOR"], "propositions": referents["PROPOSITION"],
            },
            "visible_mentions": self.visible_mentions,
            "identity_equivalence": identity,
            "mention_resolution": self._mentions(),
            "content_resolution": content,
            "canonical_commitments": commitments,
            "knowledge_verdicts": self._knowledge(),
            "reported_claims": self._reports(),
            "relationships": self._relationships(),
            "secrets": self._secrets(),
            "reader_reveals": self._reader_reveals(),
            "event_occurrence": self._events(referents["EVENT"]),
            "temporal_relations": self._temporal(),
        }
        self._functional_diagnostics()
        view["diagnostics"] = sorted(self.diagnostics, key=lambda d: (d["code"], str(d.get("assertions"))))
        return view

    def _identity(self, entities: List[str]) -> Dict[str, Any]:
        uf = _UnionFind(entities)
        distinct = []
        for a in self._by_predicate("SameAs"):
            first, second = self._arg(a, "first")["ref"], self._arg(a, "second")["ref"]
            status = self._direct_status(a["proposition_id"])
            if status == "AFFIRMED":
                uf.union(first, second)
            elif status == "NEGATED":
                distinct.append((first, second, a["id"]))
            elif status == "CONTESTED":
                self.diagnostics.append({"code": "IDENTITY_CONTESTED", "entities": sorted([first, second]),
                                         "assertions": [a["id"]]})
        for first, second, aid in distinct:
            if uf.find(first) == uf.find(second):
                self.diagnostics.append({"code": "IDENTITY_CONFLICT", "entities": sorted([first, second]),
                                         "assertions": [aid]})
        self.uf_entities = uf
        classes = uf.classes()
        return {
            "classes": [members for members in classes.values() if len(members) > 1],
            "entity_class": {e: uf.find(e) for e in sorted(entities)},
        }

    def _entity_class(self, entity_id: str) -> str:
        return self.uf_entities.find(entity_id)

    def _mentions(self) -> Dict[str, Any]:
        resolved: Dict[str, set] = {m: set() for m in self.visible_mentions}
        via: Dict[str, List[str]] = {m: [] for m in self.visible_mentions}
        for a in self._by_predicate("RefersTo"):
            if self._direct_status(a["proposition_id"]) != "AFFIRMED":
                continue
            mid, eid = self._arg(a, "mention")["ref"], self._arg(a, "entity")["ref"]
            if mid in resolved:
                resolved[mid].add(self._entity_class(eid))
                via[mid].append(a["id"])
        out = {}
        for mid in self.visible_mentions:
            classes = sorted(resolved[mid])
            status = "UNRESOLVED" if not classes else "RESOLVED" if len(classes) == 1 else "AMBIGUOUS"
            if status == "AMBIGUOUS":
                self.diagnostics.append({"code": "MENTION_AMBIGUOUS", "mention": mid, "assertions": sorted(via[mid])})
            out[mid] = {"status": status, "entity_classes": classes, "via": sorted(via[mid])}
        return out

    def _content(self, propositions: List[str]) -> Dict[str, Any]:
        uf = _UnionFind(propositions)
        for a in self._by_predicate("SameContent"):
            if self._direct_status(a["proposition_id"]) == "AFFIRMED":
                uf.union(self._arg(a, "placeholder")["ref"], self._arg(a, "concrete")["ref"])
        self.uf_content = uf
        placeholders = {}
        for pid in propositions:
            if self.ix.propositions[pid].get("placeholder"):
                members = [m for m in uf.classes()[uf.find(pid)]
                           if m != pid and not self.ix.propositions[m].get("placeholder")]
                placeholders[pid] = {"status": "RESOLVED" if members else "UNRESOLVED", "resolved_to": members}
        return {"classes": [m for m in uf.classes().values() if len(m) > 1], "placeholders": placeholders}

    def _content_class(self, pid: str) -> List[str]:
        return self.uf_content.classes()[self.uf_content.find(pid)]

    def _commitments(self, propositions: List[str]) -> Dict[str, Any]:
        out = {}
        for pid in propositions:
            members = set(self._content_class(pid))
            ids = [aid for aid, a in self.visible.items() if a["proposition_id"] in members]
            entry = self._status(ids)
            entry["content_class"] = sorted(members)
            out[pid] = entry
        self.commitments = out
        return out

    def _commitment_status(self, pid: str) -> str:
        return self.commitments[pid]["status"]

    def _knowledge(self) -> List[Dict[str, Any]]:
        out = []
        for a in self._by_predicate("Attitude"):
            if a["polarity"] != "AFFIRMED":
                continue
            holder = self._arg(a, "holder")["ref"]
            attitude = self._arg(a, "attitude")["value"]
            content = self._arg(a, "content")["ref"]
            content_polarity = self._arg(a, "content_polarity")["value"]
            status = self._commitment_status(content)
            if attitude == HOLDS_TRUE:
                if status in ("AFFIRMED", "NEGATED") and content_polarity in ("AFFIRMED", "NEGATED"):
                    verdict = "KNOWS" if status == content_polarity else "MISTAKEN"
                else:
                    verdict = "UNRESOLVED_BELIEF"
            else:
                verdict = attitude
            out.append({"assertion_id": a["id"], "holder": holder, "holder_class": self._entity_class(holder),
                        "attitude": attitude, "content": content, "content_polarity": content_polarity,
                        "canonical_content_status": status, "verdict": verdict,
                        "epistemic_status": a["epistemic_status"], "validity": self._validity(a["id"])})
        return sorted(out, key=lambda x: x["assertion_id"])

    def _reports(self) -> Dict[str, Any]:
        claims, by_content = [], {}
        for a in self._by_predicate("Says"):
            if a["polarity"] != "AFFIRMED":
                continue
            content = self._arg(a, "content")["ref"]
            content_polarity = self._arg(a, "content_polarity")["value"]
            status = self._commitment_status(content)
            if status in ("AFFIRMED", "NEGATED") and content_polarity in ("AFFIRMED", "NEGATED"):
                relation = "CONSISTENT" if status == content_polarity else "CONTRADICTED"
            else:
                relation = "UNRESOLVED"
            speaker = self._arg(a, "speaker")["ref"]
            claims.append({"assertion_id": a["id"], "speaker": speaker, "speaker_class": self._entity_class(speaker),
                           "content": content, "content_polarity": content_polarity,
                           "canonical_content_status": status, "relation_to_canonical": relation})
            key = self.uf_content.find(content)
            by_content.setdefault(key, {"AFFIRMED": [], "NEGATED": [], "OPEN": []})[content_polarity].append(a["id"])
        conflicts = [{"content_class": self._content_class(key), "affirming_reports": sorted(g["AFFIRMED"]),
                      "negating_reports": sorted(g["NEGATED"]),
                      "canonical_content_status": self._commitment_status(key)}
                     for key, g in sorted(by_content.items()) if g["AFFIRMED"] and g["NEGATED"]]
        return {"claims": sorted(claims, key=lambda x: x["assertion_id"]), "conflicts": conflicts}

    def _relationships(self) -> List[Dict[str, Any]]:
        groups: Dict[tuple, Dict[str, Any]] = {}
        for aid, a in self.visible.items():
            pred = self._pred(a)
            spec = self.ix.predicates.get(pred, {})
            if spec.get("classification") != "RELATION":
                continue
            entity_args = [x["name"] for x in spec["args"] if x["kind"] == "ENTITY"]
            if len(entity_args) < 2:
                continue
            key_args = spec.get("functional_on") or entity_args
            subject, obj = (self._entity_class(self._arg(a, n)["ref"]) for n in entity_args[:2])
            if spec.get("directionality") == "SYMMETRIC":
                subject, obj = sorted((subject, obj))
            key_tokens = {n: self._arg(a, n)["value"] for n in key_args if self._arg(a, n)["kind"] == "TOKEN"}
            value = {n: self._value(self._arg(a, n)) for n in sorted(self._args(a)) if n not in key_args}
            gkey = (pred, subject, obj, tuple(sorted(key_tokens.items())))
            group = groups.setdefault(gkey, {"predicate": pred, "directionality": spec.get("directionality"),
                                             "subject_class": subject, "object_class": obj,
                                             "key_tokens": key_tokens, "stages": []})
            group["stages"].append({"assertion_id": aid, "value": value, "polarity": a["polarity"],
                                    "epistemic_status": a["epistemic_status"], "validity": self._validity(aid),
                                    "availability": list(self.calc.of(aid))})
        for g in groups.values():
            g["stages"].sort(key=lambda s: (s["availability"], s["assertion_id"]))
        return [groups[k] for k in sorted(groups)]

    def _args(self, assertion: dict) -> Dict[str, dict]:
        return self.ix.propositions[assertion["proposition_id"]].get("args") or {}

    def _value(self, arg: dict) -> Any:
        if arg["kind"] == "ENTITY":
            return self._entity_class(arg["ref"])
        if arg["kind"] in ("EVENT", "ANCHOR", "MENTION"):
            return arg["ref"]
        if arg["kind"] == "PROPOSITION":
            return self.uf_content.find(arg["ref"])
        return arg["value"]

    def _attitudes(self, holder_class: str, kinds: Sequence[str], content: str) -> List[str]:
        cls = set(self._content_class(content))
        return sorted(a["id"] for a in self._by_predicate("Attitude")
                      if a["polarity"] == "AFFIRMED"
                      and self._entity_class(self._arg(a, "holder")["ref"]) == holder_class
                      and self._arg(a, "attitude")["value"] in kinds
                      and self._arg(a, "content")["ref"] in cls)

    def _secrets(self) -> List[Dict[str, Any]]:
        out = []
        for a in self._by_predicate("Conceals"):
            if a["polarity"] != "AFFIRMED":
                continue
            concealer = self._entity_class(self._arg(a, "concealer")["ref"])
            target = self._entity_class(self._arg(a, "concealed_from")["ref"])
            content = self._arg(a, "content")["ref"]
            holding = self._attitudes(concealer, [HOLDS_TRUE], content)
            if not holding:
                self.diagnostics.append({"code": "CONCEALMENT_WITHOUT_EVIDENCED_HOLDING", "assertions": [a["id"]]})
                continue
            unaware = self._attitudes(target, ["UNAWARE", "KEPT_UNAWARE"], content)
            learned = self._attitudes(target, [HOLDS_TRUE], content)
            validity = self._validity(a["id"]) or {"end": {"kind": "OPEN"}}
            ended = bool(learned) or validity["end"]["kind"] == "ANCHOR"
            out.append({
                "conceals_assertion": a["id"], "concealer_class": concealer, "concealed_from_class": target,
                "content": content, "status": "ENDED" if ended else "ACTIVE",
                "holder_evidence": holding, "target_unaware_evidence": unaware,
                "target_learned_evidence": learned,
                "reader_has_canonical_content": self._commitment_status(content) in ("AFFIRMED", "NEGATED"),
                "concealment_validity": self._validity(a["id"]),
            })
        return sorted(out, key=lambda x: x["conceals_assertion"])

    def _reader_reveals(self) -> List[Dict[str, Any]]:
        out, seen = [], set()
        for pid, entry in sorted(self.commitments.items()):
            key = tuple(entry["content_class"])
            if key in seen or entry["status"] not in ("AFFIRMED", "NEGATED", "TIME_SCOPED", "CONTESTED"):
                continue
            seen.add(key)
            committing = entry["affirmed"] + entry["negated"]
            first = min(tuple(self.calc.of(aid)) for aid in committing)
            out.append({"content_class": list(key), "canonical_status": entry["status"],
                        "reader_reveal_position": list(first), "assumption": READER_ASSUMPTION})
        return out

    def _events(self, events: List[str]) -> Dict[str, Any]:
        holder_relative = set(self.registry["holder_relative_predicates"])
        in_holder_content = set()
        for a in self.visible.values():
            if self._pred(a) in holder_relative:
                stack = [self._arg(a, "content")["ref"]]
                while stack:
                    pid = stack.pop()
                    for arg in (self.ix.propositions[pid].get("args") or {}).values():
                        if arg["kind"] == "EVENT":
                            in_holder_content.add(arg["ref"])
                        elif arg["kind"] == "PROPOSITION":
                            stack.append(arg["ref"])
        mapping = {"AFFIRMED": "OCCURRED", "NEGATED": "NOT_OCCURRED", "OPEN": "OPEN",
                   "CONTESTED": "CONTESTED", "UNCOMMITTED": "NOT_ESTABLISHED", "TIME_SCOPED": "CONTESTED"}
        out = {}
        for ev in events:
            ids = [aid for aid, a in self.visible.items()
                   if self._pred(a) == "Occurred" and self._arg(a, "event")["ref"] == ev]
            status = self._status(ids)
            out[ev] = {"event_exists": True, "occurrence_status": mapping[status["status"]],
                       "occurrence_assertions": sorted(ids),
                       "referenced_in_holder_relative_content": ev in in_holder_content}
        return out

    def _temporal(self) -> List[Dict[str, Any]]:
        return [{"assertion_id": a["id"], "subject": self._arg(a, "subject")["ref"],
                 "relation": self._arg(a, "relation")["value"], "object": self._arg(a, "object")["ref"],
                 "polarity": a["polarity"], "epistemic_status": a["epistemic_status"]}
                for a in self._by_predicate("TemporalRelation")]

    def _functional_diagnostics(self) -> None:
        groups: Dict[tuple, List[Tuple[str, tuple]]] = {}
        for aid, a in self.visible.items():
            spec = self.ix.predicates.get(self._pred(a), {})
            key_args = spec.get("functional_on")
            if not key_args or a["polarity"] != "AFFIRMED":
                continue
            args = self._args(a)
            key = (self._pred(a),) + tuple(str(self._value(args[n])) for n in key_args)
            value = tuple((n, str(self._value(args[n]))) for n in sorted(args) if n not in key_args)
            groups.setdefault(key, []).append((aid, value))
        for key, members in sorted(groups.items()):
            for i, (a1, v1) in enumerate(members):
                for a2, v2 in members[i + 1:]:
                    if v1 == v2:
                        continue
                    va, vb = self._validity(a1), self._validity(a2)
                    if va == vb:  # both timeless, or identical visible scope: obviously overlapping
                        self.diagnostics.append({"code": "POTENTIAL_FUNCTIONAL_CONFLICT",
                                                 "predicate": key[0], "assertions": [a1, a2]})
                    elif not self._disjoint(a1, a2):
                        self.diagnostics.append({"code": "FUNCTIONAL_OVERLAP_NOT_DETERMINED",
                                                 "predicate": key[0], "assertions": [a1, a2]})
