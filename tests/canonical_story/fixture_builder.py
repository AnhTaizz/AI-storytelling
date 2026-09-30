"""Deterministic builder for synthetic Canonical Story v0 documents.

Source-neutral: all entities, events and names are invented. Positions use
key [chapter, segment]; "chapter" here is a synthetic discourse unit.
"""
import copy

STREAM = "stream-main"


class Doc:
    def __init__(self, story_id: str):
        self.doc = {
            "schema_version": "canonical_story/v0",
            "authority_policy": "DEFAULT_V0",
            "story": {"id": story_id, "discourse_stream_id": STREAM, "editorial_label": "synthetic story"},
            "source_documents": [{"id": "doc-1", "story_id": story_id, "stream_id": STREAM,
                                  "version": "synthetic-1", "media_kind": "synthetic_text"}],
            "source_segments": [],
            "evidence_refs": [],
            "mentions": [],
            "entities": [],
            "events": [],
            "temporal_anchors": [],
            "propositions": [],
            "extraction_provenance": [{"id": "xp-human", "method": "HUMAN_ANNOTATION",
                                       "process_id": "synthetic-fixture", "process_version": "v0"}],
            "assertions": [],
        }
        self._n = {"p": 0, "a": 0, "es": 0, "dv": 0}

    # --- L1 -------------------------------------------------------------
    def ev(self, chapter: int, role: str = "DEPICTION", segment: int = 1) -> str:
        seg_id = f"seg-{chapter}-{segment}"
        if not any(s["id"] == seg_id for s in self.doc["source_segments"]):
            self.doc["source_segments"].append({
                "id": seg_id, "document_id": "doc-1",
                "position": {"stream_id": STREAM, "key": [chapter, segment]},
                "locator": {"kind": "synthetic_unit", "unit": chapter, "part": segment}})
        ref_id = f"ev-{chapter}-{segment}-{role.lower()}"
        if not any(r["id"] == ref_id for r in self.doc["evidence_refs"]):
            self.doc["evidence_refs"].append({
                "id": ref_id, "segment_id": seg_id,
                "position": {"stream_id": STREAM, "key": [chapter, segment]}, "role": role})
        return ref_id

    def mention(self, mid: str, ref_id: str, surface: str) -> str:
        self.doc["mentions"].append({"id": mid, "evidence_ref_id": ref_id, "surface_form": surface})
        return mid

    # --- L2 -------------------------------------------------------------
    def entity(self, eid: str, kind: str, placeholder: bool = False, label: str = None) -> str:
        rec = {"id": eid, "kind": kind}
        if placeholder:
            rec["placeholder"] = True
        if label:
            rec["editorial_label"] = label
        self.doc["entities"].append(rec)
        return eid

    def event(self, eid: str, kind: str = "GENERIC") -> str:
        anchor = f"t-{eid}"
        self.doc["events"].append({"id": eid, "event_kind": kind, "anchor_id": anchor})
        self.doc["temporal_anchors"].append({"id": anchor, "anchor_kind": "EVENT_TIME", "event_id": eid})
        return eid

    def anchor(self, aid: str, label: str = None) -> str:
        rec = {"id": aid, "anchor_kind": "NAMED_TIME"}
        if label:
            rec["editorial_label"] = label
        self.doc["temporal_anchors"].append(rec)
        return aid

    # --- L3 -------------------------------------------------------------
    def prop(self, predicate: str, **args) -> str:
        self._n["p"] += 1
        pid = f"p-{self._n['p']:03d}"
        self.doc["propositions"].append({"id": pid, "predicate": predicate, "args": args})
        return pid

    def placeholder_prop(self, label: str) -> str:
        self._n["p"] += 1
        pid = f"p-{self._n['p']:03d}"
        self.doc["propositions"].append({"id": pid, "placeholder": True, "editorial_label": label})
        return pid

    # --- L4 -------------------------------------------------------------
    def support(self, sets=(), derivations=()):
        out = {"evidence_sets": [], "derivations": []}
        for label, refs in sets:
            self._n["es"] += 1
            out["evidence_sets"].append({"id": f"es-{self._n['es']:03d}", "label": label,
                                         "evidence_ref_ids": list(refs)})
        for rule, premises in derivations:
            self._n["dv"] += 1
            out["derivations"].append({"id": f"dv-{self._n['dv']:03d}", "rule_id": rule,
                                       "premise_assertion_ids": list(premises)})
        return out

    def assertion(self, prop_id: str, status: str = "EXPLICIT", polarity: str = "AFFIRMED",
                  sets=(), derivations=(), validity=None, review=None) -> str:
        self._n["a"] += 1
        aid = f"a-{self._n['a']:03d}"
        rec = {"id": aid, "proposition_id": prop_id, "polarity": polarity, "epistemic_status": status,
               "support": self.support(sets, derivations),
               "extraction_provenance_id": "xp-human", "review": review or {"state": "UNREVIEWED"}}
        if validity:
            rec["validity"] = validity
        self.doc["assertions"].append(rec)
        return aid

    def bound(self, anchor_id: str = None, sets=(), derivations=()):
        if anchor_id is None:
            return {"kind": "OPEN"}
        rec = {"kind": "ANCHOR", "anchor_id": anchor_id}
        if sets or derivations:
            rec["support"] = self.support(sets, derivations)
        return rec

    def build(self) -> dict:
        return copy.deepcopy(self.doc)


# Argument helpers
def E(ref): return {"kind": "ENTITY", "ref": ref}
def V(ref): return {"kind": "EVENT", "ref": ref}
def T(ref): return {"kind": "ANCHOR", "ref": ref}
def M(ref): return {"kind": "MENTION", "ref": ref}
def P(ref): return {"kind": "PROPOSITION", "ref": ref}
def S(value): return {"kind": "LITERAL", "value_type": "STRING", "value": value}
def TOK(vocab, value): return {"kind": "TOKEN", "vocabulary": vocab, "value": value}
def POL(value="AFFIRMED"): return TOK("polarity", value)
def ROLE(value): return TOK("participant_role", value)
def SUF(*refs): return ("SUFFICIENT", refs)


def occurred_with(d: Doc, event_id: str, chapter: int, participants=(), role="DEPICTION"):
    """Assert occurrence plus participation; returns (occurred_id, [participation ids])."""
    ref = d.ev(chapter, role)
    occ = d.assertion(d.prop("Occurred", event=V(event_id)), sets=[SUF(ref)])
    parts = [d.assertion(d.prop("Participates", event=V(event_id), participant=E(ent), role=ROLE(r)),
                         sets=[SUF(ref)]) for ent, r in participants]
    return occ, parts


# ---------------------------------------------------------------------------
# Stress tests A-J
# ---------------------------------------------------------------------------

def case_a_multiple_names() -> dict:
    d = Doc("story-a")
    a, b = d.entity("ent-a", "CHARACTER"), d.entity("ent-b", "CHARACTER")
    d.assertion(d.prop("NamedAs", entity=E(a), name=S("Formal Name A"), name_kind=TOK("name_kind", "FORMAL")),
                sets=[SUF(d.ev(1))], validity={"start": d.bound(), "end": d.bound()})
    d.assertion(d.prop("NamedAs", entity=E(a), name=S("The Title"), name_kind=TOK("name_kind", "TITLE")),
                sets=[SUF(d.ev(2, "NARRATION_SUMMARY"))], validity={"start": d.bound(), "end": d.bound()})
    d.assertion(d.prop("NamedAs", entity=E(a), name=S("Nick"), name_kind=TOK("name_kind", "NICKNAME")),
                sets=[SUF(d.ev(3))], validity={"start": d.bound(), "end": d.bound()})
    rename = d.event("evt-rename", "ADDRESS_CHANGE")
    occurred_with(d, rename, 8, [(b, "AGENT"), (a, "PATIENT")])
    d.assertion(d.prop("AddressesAs", speaker=E(b), addressee=E(a), form=TOK("address_form", "FAMILY_NAME")),
                sets=[SUF(d.ev(2))],
                validity={"start": d.bound(), "end": d.bound("t-evt-rename", sets=[SUF(d.ev(8))])})
    d.assertion(d.prop("AddressesAs", speaker=E(b), addressee=E(a), form=TOK("address_form", "GIVEN_NAME")),
                sets=[SUF(d.ev(8))], validity={"start": d.bound("t-evt-rename"), "end": d.bound()})
    m1 = d.mention("men-1", d.ev(1), "Formal Name A")
    m2 = d.mention("men-2", d.ev(3), "Nick")
    d.assertion(d.prop("RefersTo", mention=M(m1), entity=E(a)), sets=[SUF(d.ev(1))])
    d.assertion(d.prop("RefersTo", mention=M(m2), entity=E(a)), sets=[SUF(d.ev(3))])
    return d.build()


def case_b_flashback() -> dict:
    d = Doc("story-b")
    d.entity("ent-a", "CHARACTER")
    opening, old = d.event("evt-opening"), d.event("evt-old")
    occurred_with(d, opening, 1, [("ent-a", "AGENT")])
    occurred_with(d, old, 20, [("ent-a", "AGENT")])
    d.assertion(d.prop("TemporalRelation", subject=T("t-evt-old"), relation=TOK("temporal_relation", "BEFORE"),
                       object=T("t-evt-opening")), sets=[SUF(d.ev(20))])
    return d.build()


def case_c_possession() -> dict:
    d = Doc("story-c")
    a, b = d.entity("ent-a", "CHARACTER"), d.entity("ent-b", "CHARACTER")
    item = d.entity("ent-item", "OBJECT")
    e1, e2 = d.event("evt-give", "TRANSFER"), d.event("evt-return", "TRANSFER")
    d.assertion(d.prop("Possesses", holder=E(a), item=E(item)), sets=[SUF(d.ev(1))],
                validity={"start": d.bound(), "end": d.bound("t-evt-give", sets=[SUF(d.ev(4))])})
    occ1, parts1 = occurred_with(d, e1, 4, [(a, "SOURCE"), (b, "RECIPIENT"), (item, "THEME")])
    d.assertion(d.prop("Possesses", holder=E(b), item=E(item)), status="ENTAILED",
                derivations=[("TRANSFER_RESULT", [occ1] + parts1)],
                validity={"start": d.bound("t-evt-give"), "end": d.bound("t-evt-return", sets=[SUF(d.ev(9))])})
    occ2, parts2 = occurred_with(d, e2, 9, [(b, "SOURCE"), (a, "RECIPIENT"), (item, "THEME")])
    d.assertion(d.prop("Possesses", holder=E(a), item=E(item)), status="ENTAILED",
                derivations=[("TRANSFER_RESULT", [occ2] + parts2)],
                validity={"start": d.bound("t-evt-return"), "end": d.bound()})
    return d.build()


def case_d_relationship_progression() -> dict:
    d = Doc("story-d")
    a, b = d.entity("ent-a", "CHARACTER"), d.entity("ent-b", "CHARACTER")
    tx, ty = d.anchor("t-shift-1", "first shift"), d.anchor("t-shift-2", "second shift")
    help_evt = d.event("evt-help")
    occ, parts = occurred_with(d, help_evt, 6, [(b, "AGENT"), (a, "RECIPIENT")])

    def regard(level):
        return d.prop("Regard", holder=E(a), target=E(b), dimension=TOK("regard_dimension", "TRUST"),
                      level=TOK("regard_level", level))
    d.assertion(regard("NEGATIVE"), sets=[SUF(d.ev(2, "NARRATION_SUMMARY"))],
                validity={"start": d.bound(), "end": d.bound(tx, derivations=[("BEHAVIOUR_SUGGESTS_STATE", [occ])])})
    d.assertion(regard("NEUTRAL"), status="SUGGESTED",
                derivations=[("BEHAVIOUR_SUGGESTS_STATE", [occ] + parts)],
                validity={"start": d.bound(tx), "end": d.bound(ty, sets=[SUF(d.ev(11, "NARRATION_SUMMARY"))])})
    d.assertion(regard("POSITIVE"), sets=[SUF(d.ev(11, "NARRATION_SUMMARY"))],
                validity={"start": d.bound(ty), "end": d.bound()})
    return d.build()


def case_e_secret_and_reveals() -> dict:
    d = Doc("story-e")
    a, b = d.entity("ent-a", "CHARACTER"), d.entity("ent-b", "CHARACTER")
    key, garden = d.entity("ent-key", "OBJECT"), d.entity("ent-garden", "LOCATION")
    p_x = d.prop("LocatedAt", thing=E(key), location=E(garden))
    hidden = d.placeholder_prop("something A knows")
    d.assertion(d.prop("Attitude", holder=E(a), attitude=TOK("attitude_kind", "HOLDS_TRUE"),
                       content=P(hidden), content_polarity=POL()), sets=[SUF(d.ev(1))],
                validity={"start": d.bound(), "end": d.bound()})
    d.assertion(d.prop("SameContent", placeholder=P(hidden), concrete=P(p_x)), sets=[SUF(d.ev(7))])
    d.assertion(d.prop("Attitude", holder=E(a), attitude=TOK("attitude_kind", "HOLDS_TRUE"),
                       content=P(p_x), content_polarity=POL()), sets=[SUF(d.ev(3))],
                validity={"start": d.bound(), "end": d.bound()})
    d.assertion(d.prop("Conceals", concealer=E(a), content=P(p_x), concealed_from=E(b)), sets=[SUF(d.ev(3))],
                validity={"start": d.bound(), "end": d.bound("t-evt-tell", sets=[SUF(d.ev(15))])})
    ask = d.event("evt-ask", "UTTERANCE")
    occ_ask, parts_ask = occurred_with(d, ask, 4, [(b, "AGENT")])
    tell = d.event("evt-tell", "REVEAL_TELL")
    d.assertion(d.prop("Attitude", holder=E(b), attitude=TOK("attitude_kind", "UNAWARE"),
                       content=P(p_x), content_polarity=POL()), status="ENTAILED",
                derivations=[("BEHAVIOUR_ENTAILS_UNAWARE", [occ_ask] + parts_ask)],
                validity={"start": d.bound(), "end": d.bound("t-evt-tell", sets=[SUF(d.ev(15))])})
    d.assertion(p_x, sets=[SUF(d.ev(7, "NARRATION_SUMMARY"))])          # reader can learn P_X at 7
    occ_tell, parts_tell = occurred_with(d, tell, 15, [(a, "SOURCE"), (b, "RECIPIENT")])
    conveys = d.assertion(d.prop("Conveys", event=V(tell), content=P(p_x), content_polarity=POL()),
                          sets=[SUF(d.ev(15))])
    d.assertion(d.prop("Attitude", holder=E(b), attitude=TOK("attitude_kind", "HOLDS_TRUE"),
                       content=P(p_x), content_polarity=POL()), status="ENTAILED",
                derivations=[("REVEAL_RESULT", [occ_tell] + parts_tell + [conveys])],
                validity={"start": d.bound("t-evt-tell"), "end": d.bound()})
    return d.build()


def case_f_mistaken_belief() -> dict:
    d = Doc("story-f")
    b = d.entity("ent-b", "CHARACTER")
    box, shed = d.entity("ent-box", "OBJECT"), d.entity("ent-shed", "LOCATION")
    p_y = d.prop("LocatedAt", thing=E(box), location=E(shed))
    d.assertion(d.prop("Attitude", holder=E(b), attitude=TOK("attitude_kind", "HOLDS_TRUE"),
                       content=P(p_y), content_polarity=POL()), sets=[SUF(d.ev(5))],
                validity={"start": d.bound(), "end": d.bound()})
    d.assertion(p_y, polarity="NEGATED", sets=[SUF(d.ev(18, "NARRATION_SUMMARY"))])
    return d.build()


def case_g_reported_claim() -> dict:
    d = Doc("story-g")
    a = d.entity("ent-a", "CHARACTER")
    bridge, north = d.entity("ent-bridge", "OBJECT"), d.entity("ent-north", "LOCATION")
    p_x = d.prop("LocatedAt", thing=E(bridge), location=E(north))
    say = d.event("evt-say", "UTTERANCE")
    occurred_with(d, say, 6, [(a, "AGENT")])
    d.assertion(d.prop("Says", speaker=E(a), content=P(p_x), content_polarity=POL()), sets=[SUF(d.ev(6))])
    # Deliberately no assertion of p_x: its truth is not established.
    return d.build()


def case_h_multi_path() -> dict:
    d = Doc("story-h")
    a, b = d.entity("ent-a", "CHARACTER"), d.entity("ent-b", "CHARACTER")
    meet = d.event("evt-meet", "ENCOUNTER")
    d.assertion(d.prop("Occurred", event=V(meet)),
                sets=[SUF(d.ev(8)), SUF(d.ev(20, "RETROSPECTIVE"))])
    d.assertion(d.prop("Participates", event=V(meet), participant=E(a), role=ROLE("AGENT")), sets=[SUF(d.ev(8))])
    d.assertion(d.prop("Participates", event=V(meet), participant=E(b), role=ROLE("PATIENT")), sets=[SUF(d.ev(8))])
    return d.build()


def case_i_partial_retrospective() -> dict:
    d = Doc("story-i")
    a, b = d.entity("ent-a", "CHARACTER"), d.entity("ent-b", "CHARACTER")
    carry = d.event("evt-carry", "MOVEMENT")
    d.assertion(d.prop("Occurred", event=V(carry)),
                sets=[SUF(d.ev(5)), SUF(d.ev(12, "RETROSPECTIVE"))])
    d.assertion(d.prop("Manner", event=V(carry), manner=S("by cart")),
                sets=[SUF(d.ev(5)), ("PARTIAL", [d.ev(12, "RETROSPECTIVE")])])
    d.assertion(d.prop("Participates", event=V(carry), participant=E(a), role=ROLE("AGENT")), sets=[SUF(d.ev(5))])
    d.assertion(d.prop("Participates", event=V(carry), participant=E(b), role=ROLE("PATIENT")), sets=[SUF(d.ev(5))])
    return d.build()


def case_j_unknown_identity() -> dict:
    d = Doc("story-j")
    a = d.entity("ent-a", "CHARACTER")
    u = d.entity("ent-u", "CHARACTER", placeholder=True, label="the stranger")
    m = d.mention("men-u", d.ev(4), "the stranger")
    d.assertion(d.prop("RefersTo", mention=M(m), entity=E(u)), sets=[SUF(d.ev(4))])
    d.assertion(d.prop("IdentityKnown", entity=E(u)), polarity="OPEN", sets=[SUF(d.ev(4))])
    d.assertion(d.prop("SameAs", first=E(u), second=E(a)), sets=[SUF(d.ev(22))])
    return d.build()


def snapshot_m2_02_s21() -> dict:
    """Cases E, F and J combined in one document, matching the M2-02 section 21 snapshots."""
    d = Doc("story-snapshot")
    a, b = d.entity("ent-a", "CHARACTER"), d.entity("ent-b", "CHARACTER")
    u = d.entity("ent-u", "CHARACTER", placeholder=True, label="the stranger")
    key, garden = d.entity("ent-key", "OBJECT"), d.entity("ent-garden", "LOCATION")
    box, shed = d.entity("ent-box", "OBJECT"), d.entity("ent-shed", "LOCATION")
    p_x = d.prop("LocatedAt", thing=E(key), location=E(garden))
    p_y = d.prop("LocatedAt", thing=E(box), location=E(shed))
    # Case E: A holds and conceals P_X (3); B's unawareness entailed (4); reader learns P_X (7); B told (15).
    d.assertion(d.prop("Attitude", holder=E(a), attitude=TOK("attitude_kind", "HOLDS_TRUE"),
                       content=P(p_x), content_polarity=POL()), sets=[SUF(d.ev(3))],
                validity={"start": d.bound(), "end": d.bound()})
    d.assertion(d.prop("Conceals", concealer=E(a), content=P(p_x), concealed_from=E(b)), sets=[SUF(d.ev(3))],
                validity={"start": d.bound(), "end": d.bound("t-evt-tell", sets=[SUF(d.ev(15))])})
    ask = d.event("evt-ask", "UTTERANCE")
    occ_ask, parts_ask = occurred_with(d, ask, 4, [(b, "AGENT")])
    tell = d.event("evt-tell", "REVEAL_TELL")
    d.assertion(d.prop("Attitude", holder=E(b), attitude=TOK("attitude_kind", "UNAWARE"),
                       content=P(p_x), content_polarity=POL()), status="ENTAILED",
                derivations=[("BEHAVIOUR_ENTAILS_UNAWARE", [occ_ask] + parts_ask)],
                validity={"start": d.bound(), "end": d.bound("t-evt-tell", sets=[SUF(d.ev(15))])})
    d.assertion(p_x, sets=[SUF(d.ev(7, "NARRATION_SUMMARY"))])
    occ_tell, parts_tell = occurred_with(d, tell, 15, [(a, "SOURCE"), (b, "RECIPIENT")])
    conveys = d.assertion(d.prop("Conveys", event=V(tell), content=P(p_x), content_polarity=POL()),
                          sets=[SUF(d.ev(15))])
    d.assertion(d.prop("Attitude", holder=E(b), attitude=TOK("attitude_kind", "HOLDS_TRUE"),
                       content=P(p_x), content_polarity=POL()), status="ENTAILED",
                derivations=[("REVEAL_RESULT", [occ_tell] + parts_tell + [conveys])],
                validity={"start": d.bound("t-evt-tell"), "end": d.bound()})
    # Case F: B believes P_Y (5); narration negates it (18).
    d.assertion(d.prop("Attitude", holder=E(b), attitude=TOK("attitude_kind", "HOLDS_TRUE"),
                       content=P(p_y), content_polarity=POL()), sets=[SUF(d.ev(5))],
                validity={"start": d.bound(), "end": d.bound()})
    d.assertion(p_y, polarity="NEGATED", sets=[SUF(d.ev(18, "NARRATION_SUMMARY"))])
    # Case J: identity of U explicitly unknown (4); resolved as A (22).
    m = d.mention("men-u", d.ev(4), "the stranger")
    d.assertion(d.prop("RefersTo", mention=M(m), entity=E(u)), sets=[SUF(d.ev(4))])
    d.assertion(d.prop("IdentityKnown", entity=E(u)), polarity="OPEN", sets=[SUF(d.ev(4))])
    d.assertion(d.prop("SameAs", first=E(u), second=E(a)), sets=[SUF(d.ev(22))])
    return d.build()


EXTRA_VALID_CASES = {
    "snapshot_m2_02_s21.json": snapshot_m2_02_s21,
}


VALID_CASES = {
    "case_a_multiple_names.json": case_a_multiple_names,
    "case_b_flashback.json": case_b_flashback,
    "case_c_possession.json": case_c_possession,
    "case_d_relationship_progression.json": case_d_relationship_progression,
    "case_e_secret_and_reveals.json": case_e_secret_and_reveals,
    "case_f_mistaken_belief.json": case_f_mistaken_belief,
    "case_g_reported_claim.json": case_g_reported_claim,
    "case_h_multi_path.json": case_h_multi_path,
    "case_i_partial_retrospective.json": case_i_partial_retrospective,
    "case_j_unknown_identity.json": case_j_unknown_identity,
}


# ---------------------------------------------------------------------------
# Negative fixtures: (name, builder, expected layer, expected message fragment)
# ---------------------------------------------------------------------------

def _base_negative():
    d = Doc("story-neg")
    d.entity("ent-a", "CHARACTER")
    d.entity("ent-b", "CHARACTER")
    ev = d.event("evt-1", "UTTERANCE")
    occ, parts = occurred_with(d, ev, 2, [("ent-a", "AGENT")])
    return d, occ, parts


def neg_assertion_without_proposition():
    d, occ, _ = _base_negative()
    doc = d.build()
    del doc["assertions"][0]["proposition_id"]
    return doc


def neg_invalid_reference():
    d, _, _ = _base_negative()
    d.assertion(d.prop("Participates", event=V("evt-1"), participant=E("ent-missing"), role=ROLE("AGENT")),
                sets=[SUF(d.ev(2))])
    return d.build()


def neg_sufficient_set_empty():
    d, _, _ = _base_negative()
    doc = d.build()
    doc["assertions"][0]["support"]["evidence_sets"][0]["evidence_ref_ids"] = []
    return doc


def neg_entailed_without_path():
    d, _, _ = _base_negative()
    d.assertion(d.prop("Possesses", holder=E("ent-a"), item=E(d.entity("ent-item", "OBJECT"))), status="ENTAILED")
    return d.build()


def neg_missing_premise():
    d, occ, parts = _base_negative()
    d.entity("ent-item", "OBJECT")
    d.assertion(d.prop("Possesses", holder=E("ent-b"), item=E("ent-item")), status="ENTAILED",
                derivations=[("TRANSFER_RESULT", [occ, "a-999"])])
    return d.build()


def neg_belief_asserts_content():
    d, _, _ = _base_negative()
    item, place = d.entity("ent-item", "OBJECT"), d.entity("ent-place", "LOCATION")
    p = d.prop("LocatedAt", thing=E(item), location=E(place))
    belief = d.assertion(d.prop("Attitude", holder=E("ent-a"), attitude=TOK("attitude_kind", "HOLDS_TRUE"),
                                content=P(p), content_polarity=POL()), sets=[SUF(d.ev(3))])
    d.assertion(p, status="ENTAILED", derivations=[("BEHAVIOUR_SUGGESTS_STATE", [belief])])
    return d.build()


def neg_invalid_validity_anchor():
    d, _, _ = _base_negative()
    item = d.entity("ent-item", "OBJECT")
    d.assertion(d.prop("Possesses", holder=E("ent-a"), item=E(item)), sets=[SUF(d.ev(2))],
                validity={"start": d.bound("t-missing"), "end": d.bound()})
    return d.build()


def neg_event_marked_occurred():
    d, _, _ = _base_negative()
    doc = d.build()
    doc["events"][0]["occurred"] = True
    return doc


def neg_reported_epistemic_status():
    d, _, _ = _base_negative()
    doc = d.build()
    doc["assertions"][0]["epistemic_status"] = "REPORTED"
    return doc


def neg_mistaken_stored():
    d, _, _ = _base_negative()
    item, place = d.entity("ent-item", "OBJECT"), d.entity("ent-place", "LOCATION")
    p = d.prop("LocatedAt", thing=E(item), location=E(place))
    d.assertion(d.prop("Attitude", holder=E("ent-a"), attitude=TOK("attitude_kind", "MISTAKEN"),
                       content=P(p), content_polarity=POL()), sets=[SUF(d.ev(3))])
    return d.build()


def neg_knows_predicate():
    d, _, _ = _base_negative()
    item, place = d.entity("ent-item", "OBJECT"), d.entity("ent-place", "LOCATION")
    p = d.prop("LocatedAt", thing=E(item), location=E(place))
    d.assertion(d.prop("Knows", holder=E("ent-a"), content=P(p)), sets=[SUF(d.ev(3))])
    return d.build()


def neg_paratext_sufficient():
    d, _, _ = _base_negative()
    item = d.entity("ent-item", "OBJECT")
    d.assertion(d.prop("Possesses", holder=E("ent-a"), item=E(item)), sets=[SUF(d.ev(3, "PARATEXT"))])
    return d.build()


def neg_explicit_derivation_only():
    d, occ, parts = _base_negative()
    d.entity("ent-item", "OBJECT")
    d.assertion(d.prop("Possesses", holder=E("ent-a"), item=E("ent-item")), status="EXPLICIT",
                derivations=[("TRANSFER_RESULT", [occ] + parts)])
    return d.build()


def neg_validity_on_event_predicate():
    d, _, _ = _base_negative()
    doc = d.build()
    doc["assertions"][0]["validity"] = {"start": {"kind": "OPEN"}, "end": {"kind": "OPEN"}}
    return doc


def neg_derivation_cycle():
    d, occ, parts = _base_negative()
    d.entity("ent-item", "OBJECT")
    first = d.assertion(d.prop("Possesses", holder=E("ent-a"), item=E("ent-item")), status="ENTAILED",
                        derivations=[("TRANSFER_RESULT", [occ, "a-004"])])
    d.assertion(d.prop("Possesses", holder=E("ent-b"), item=E("ent-item")), status="ENTAILED",
                derivations=[("TRANSFER_RESULT", [occ, first])])
    return d.build()


def neg_self_report_internal_state_explicit():
    d, _, _ = _base_negative()
    d.assertion(d.prop("Regard", holder=E("ent-a"), target=E("ent-b"),
                       dimension=TOK("regard_dimension", "TRUST"), level=TOK("regard_level", "POSITIVE")),
                sets=[SUF(d.ev(3, "IN_WORLD_REPORT"))])
    return d.build()


def neg_arity_mismatch():
    d, _, _ = _base_negative()
    d.assertion(d.prop("Possesses", holder=E("ent-a")), sets=[SUF(d.ev(2))])
    return d.build()


INVALID_CASES = {
    "neg_01_assertion_without_proposition.json": (neg_assertion_without_proposition, "structural", "proposition_id"),
    "neg_02_invalid_reference.json": (neg_invalid_reference, "reference_integrity", "unknown ENTITY ent-missing"),
    "neg_03_sufficient_set_empty.json": (neg_sufficient_set_empty, "structural", "should be non-empty"),
    "neg_04_entailed_without_path.json": (neg_entailed_without_path, "support_path_integrity", "has no support path"),
    "neg_05_missing_premise.json": (neg_missing_premise, "derivation_integrity", "premise a-999 does not exist"),
    "neg_06_belief_asserts_content.json": (neg_belief_asserts_content, "derivation_integrity", "never establishes its content"),
    "neg_07_invalid_validity_anchor.json": (neg_invalid_validity_anchor, "temporal_bound_integrity", "unknown anchor t-missing"),
    "neg_08_event_marked_occurred.json": (neg_event_marked_occurred, "structural", "Additional properties"),
    "neg_09_reported_epistemic_status.json": (neg_reported_epistemic_status, "structural", "'REPORTED' is not one of"),
    "neg_10_mistaken_stored.json": (neg_mistaken_stored, "predicate_integrity", "forbidden verdict MISTAKEN"),
    "neg_11_knows_predicate.json": (neg_knows_predicate, "predicate_integrity", "forbidden stored verdict predicate Knows"),
    "neg_12_paratext_sufficient.json": (neg_paratext_sufficient, "evidence_set_integrity", "PARATEXT"),
    "neg_13_explicit_derivation_only.json": (neg_explicit_derivation_only, "epistemic_integrity", "EXPLICIT without"),
    "neg_14_validity_on_event_predicate.json": (neg_validity_on_event_predicate, "temporal_bound_integrity", "not stative"),
    "neg_15_derivation_cycle.json": (neg_derivation_cycle, "derivation_integrity", "derivation cycle"),
    "neg_16_self_report_internal_state.json": (neg_self_report_internal_state_explicit, "epistemic_integrity", "self-report"),
    "neg_17_arity_mismatch.json": (neg_arity_mismatch, "predicate_integrity", "arity mismatch"),
}
