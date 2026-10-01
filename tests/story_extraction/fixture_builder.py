"""Deterministic synthetic fixtures for STORY_EXTRACTION/v0.

Every fixture starts from invented English text, runs the frozen M3 adapter on it,
and builds an extraction batch on top of the resulting source-layer skeleton.
Nothing here extracts anything: the "gold" is written by hand in code.

Gold batches are AGENT-AUTHORED DRAFTS: method HUMAN_ANNOTATION, review UNREVIEWED.
They are not human-confirmed.

A case function receives a Builder and a variant name. Variant "gold" is the intended
answer. Other variants are deliberately wrong predictions for negative tests.
"""
import hashlib
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.story_extraction import extraction_contract_v0 as contract  # noqa: E402
from tools.story_ingestion import light_novel_adapter_v0 as adapter  # noqa: E402


def ingest_text(text: str, story_id: str = "story-syn-m4"):
    """Run the frozen M3 adapter over synthetic text. Returns (IngestionResult, base skeleton)."""
    data = text.encode("utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "unit.txt").write_bytes(data)
        manifest = {"contract_version": "LIGHT_NOVEL_INGESTION/v0", "story_id": story_id,
                    "stream_id": "stream-syn-m4", "source_language": "en",
                    "documents": [{"document_id": "srcdoc-syn-m4", "order": 1, "path": "unit.txt",
                                   "expected_sha256": hashlib.sha256(data).hexdigest()}]}
        result = adapter.ingest(manifest, Path(tmp))
    return result, result.canonical_skeleton()


# Argument helpers
def E(ref): return {"kind": "ENTITY", "ref": ref}
def V(ref): return {"kind": "EVENT", "ref": ref}
def T(ref): return {"kind": "ANCHOR", "ref": ref}
def M(ref): return {"kind": "MENTION", "ref": ref}
def P(ref): return {"kind": "PROPOSITION", "ref": ref}
def S(value): return {"kind": "LITERAL", "value_type": "STRING", "value": value}
def TOK(vocabulary, value): return {"kind": "TOKEN", "vocabulary": vocabulary, "value": value}
def POL(value="AFFIRMED"): return TOK("polarity", value)
def SPOL(value="AFFIRMED"): return TOK("signed_polarity", value)
def ROLE(value): return TOK("participant_role", value)
OPEN = {"start": {"kind": "OPEN"}, "end": {"kind": "OPEN"}}


class Builder:
    """Builds one extraction batch over an ingested synthetic text."""

    def __init__(self, ingestion, base, prefix="g", method="HUMAN_ANNOTATION", context_only=(),
                 dedupe_propositions=True):
        self.ingestion, self.base = ingestion, base
        self.prefix, self.method = prefix, method
        self.segments = ingestion.documents[0].segments
        self.context_only = set(context_only)
        self.dedupe = dedupe_propositions
        self.records = {name: [] for name in contract.CANDIDATE_COLLECTIONS}
        self.process = {"method": method, "process_id": "synthetic-fixture", "process_version": "v0"}
        self._evidence = {}
        self._n = {}
        self.provenance = self._id("xp")
        self.records["extraction_provenance"].append({"id": self.provenance, **self.process})

    def _id(self, kind):
        self._n[kind] = self._n.get(kind, 0) + 1
        return f"{self.prefix}-{kind}-{self._n[kind]:03d}"

    # ---- evidence and mentions
    def ev(self, segment, text=None, role="DEPICTION"):
        """Evidence ref for an exact span of segment number `segment` (1-based); whole segment if text is None."""
        seg = self.segments[segment - 1]
        if text is None:
            ref = self.ingestion.passage_ref(seg["id"])
        else:
            start = self.ingestion.segment_text(seg["id"]).index(text)
            ref = self.ingestion.passage_ref(seg["id"], start, start + len(text))
        key = (segment, text, role)
        if key not in self._evidence:
            record = adapter.materialize_evidence_ref(ref, role, self._id("ev"))
            self.records["evidence_refs"].append(record)
            self._evidence[key] = record["id"]
        return self._evidence[key]

    def mention(self, segment, surface, role="DEPICTION"):
        mid = self._id("m")
        self.records["mentions"].append({"id": mid, "evidence_ref_id": self.ev(segment, surface, role),
                                         "surface_form": surface})
        return mid

    # ---- referents
    def entity(self, kind="CHARACTER", placeholder=False):
        eid = self._id("ent")
        record = {"id": eid, "kind": kind}
        if placeholder:
            record["placeholder"] = True
        self.records["entities"].append(record)
        return eid

    def named(self, segment, surface, kind="CHARACTER", placeholder=False, role="DEPICTION", entity=None):
        """Mention + (new or given) entity + RefersTo. Returns the entity id."""
        mention = self.mention(segment, surface, role)
        entity = entity or self.entity(kind, placeholder)
        self.claim(self.prop("RefersTo", mention=M(mention), entity=E(entity)),
                   [[self.ev(segment, surface, role)]])
        return entity

    def event(self, kind="GENERIC"):
        eid, anchor = self._id("evt"), self._id("t")
        self.records["events"].append({"id": eid, "event_kind": kind, "anchor_id": anchor})
        self.records["temporal_anchors"].append({"id": anchor, "anchor_kind": "EVENT_TIME", "event_id": eid})
        return eid, anchor

    # ---- propositions and assertions
    def prop(self, predicate, **args):
        if self.dedupe:
            for existing in self.records["propositions"]:
                if existing.get("predicate") == predicate and existing.get("args") == args:
                    return existing["id"]
        pid = self._id("p")
        self.records["propositions"].append({"id": pid, "predicate": predicate, "args": args})
        return pid

    def support(self, sufficient=(), partial=(), corroborating=(), derivations=()):
        out = {"evidence_sets": [], "derivations": []}
        for label, groups in (("SUFFICIENT", sufficient), ("PARTIAL", partial), ("CORROBORATING", corroborating)):
            for refs in groups:
                out["evidence_sets"].append({"id": self._id("es"), "label": label, "evidence_ref_ids": list(refs)})
        for rule, premises in derivations:
            out["derivations"].append({"id": self._id("dv"), "rule_id": rule, "premise_assertion_ids": list(premises)})
        return out

    def claim(self, proposition, sufficient=(), status="EXPLICIT", polarity="AFFIRMED", validity=None,
              partial=(), corroborating=(), derivations=(), review=None):
        aid = self._id("a")
        record = {"id": aid, "proposition_id": proposition, "polarity": polarity, "epistemic_status": status,
                  "support": self.support(sufficient, partial, corroborating, derivations),
                  "extraction_provenance_id": self.provenance, "review": review or {"state": "UNREVIEWED"}}
        if validity is not None:
            record["validity"] = validity
        self.records["assertions"].append(record)
        return aid

    def occurred(self, event, segment, text=None, role="DEPICTION", polarity="AFFIRMED"):
        return self.claim(self.prop("Occurred", event=V(event)), [[self.ev(segment, text, role)]], polarity=polarity)

    def bound(self, anchor, sufficient):
        return {"kind": "ANCHOR", "anchor_id": anchor, "support": self.support(sufficient)}

    # ---- envelope
    def batch(self, as_of_segment=None):
        last = self.segments[(as_of_segment or len(self.segments)) - 1]
        inputs = [{"use": "CONTEXT_ONLY" if i in self.context_only else "EVIDENCE_ELIGIBLE",
                   "passage_ref": self.ingestion.passage_ref(seg["id"])}
                  for i, seg in enumerate(self.segments, start=1)
                  if seg["position"]["key"] <= last["position"]["key"]]
        prior = any(self.base[name] for name in contract.CANDIDATE_COLLECTIONS)
        return {
            "batch_version": contract.BATCH_VERSION,
            "contract_version": contract.CONTRACT_VERSION,
            "process": dict(self.process),
            "scope": {
                "story_id": self.base["story"]["id"],
                "ingestion": {"contract_version": adapter.CONTRACT_VERSION,
                              "corpus_fingerprint_sha256": self.ingestion.fingerprint},
                "passage_inputs": inputs,
                "as_of_position": {"stream_id": last["position"]["stream_id"], "key": last["position"]["key"]},
                "prior_canonical_context": {"kind": "BASE_DOCUMENT_RECORDS" if prior else "NONE"},
                "profile_id": "synthetic-profile-v0",
            },
            "base_canonical_identity": {"schema_version": "canonical_story/v0",
                                        "base_document_sha256": contract.document_sha256(self.base)},
            "candidate_records": self.records,
        }


# ------------------------------------------------------------------------------------------------ cases
# Each case: (text, build function). Segments are numbered from 1 in reading order.

def c01_named_character(b, variant):
    mira = b.named(1, "Mira")
    b.claim(b.prop("NamedAs", entity=E(mira), name=S("Mira"), name_kind=TOK("name_kind", "GIVEN")),
            [[b.ev(1, "Mira")]], validity=OPEN)


def c02_two_mentions_one_entity(b, variant):
    mira = b.named(1, "Mira")
    if variant == "split_entity":
        b.named(2, "The captain")                              # wrongly a second entity
    else:
        b.named(2, "The captain", entity=mira)


def c03_unknown_referent(b, variant):
    stranger = b.named(1, "A hooded stranger", placeholder=True)
    b.claim(b.prop("IdentityKnown", entity=E(stranger)), [[b.ev(1)]], polarity="OPEN")


def c04_later_same_as(b, variant):
    stranger = b.named(1, "A hooded stranger", placeholder=True)
    mira = b.named(2, "Mira")
    if variant != "no_resolution":
        b.claim(b.prop("SameAs", first=E(stranger), second=E(mira)), [[b.ev(2)]])


def c05_event_occurred(b, variant):
    event, _ = b.event()
    if variant != "event_without_occurred":
        b.occurred(event, 1)
    else:
        b.records["propositions"].append({"id": b._id("p"), "predicate": "Occurred", "args": {"event": V(event)}})


def c06_participant(b, variant):
    mira = b.named(1, "Mira")
    event, _ = b.event()
    b.occurred(event, 1)
    role = "PATIENT" if variant == "wrong_role" else "AGENT"
    b.claim(b.prop("Participates", event=V(event), participant=E(mira), role=ROLE(role)), [[b.ev(1)]])


def c07_location(b, variant):
    mira = b.named(1, "Mira")
    courtyard = b.named(1, "the courtyard", kind="LOCATION")
    event, _ = b.event()
    b.occurred(event, 1)
    b.claim(b.prop("Participates", event=V(event), participant=E(mira), role=ROLE("AGENT")), [[b.ev(1)]])
    b.claim(b.prop("OccursAt", event=V(event), location=E(courtyard)), [[b.ev(1)]])


def c08_possession(b, variant):
    mira = b.named(1, "Mira")
    lantern = b.named(1, "the lantern", kind="OBJECT")
    b.claim(b.prop("Possesses", holder=E(mira), item=E(lantern)), [[b.ev(1)]], validity=OPEN)


def c09_ownership(b, variant):
    lantern = b.named(1, "The lantern", kind="OBJECT")
    joren = b.named(1, "Joren")
    b.claim(b.prop("Owns", owner=E(joren), item=E(lantern)), [[b.ev(1, role="NARRATION_SUMMARY")]], validity=OPEN)


def c10_relationship_state(b, variant):
    mira, joren = b.named(1, "Mira"), b.named(1, "Joren")
    b.claim(b.prop("Regard", holder=E(mira), target=E(joren), dimension=TOK("regard_dimension", "TRUST"),
                   level=TOK("regard_level", "POSITIVE")), [[b.ev(1, role="NARRATION_SUMMARY")]], validity=OPEN)


def c11_explicit_emotion(b, variant):
    mira, joren = b.named(1, "Mira"), b.named(1, "Joren")
    b.claim(b.prop("EmotionToward", holder=E(mira), target=E(joren), emotion=S("anger")),
            [[b.ev(1, role="NARRATION_SUMMARY")]], validity=OPEN)


def c12_suggested_emotion(b, variant):
    mira, joren = b.named(1, "Mira"), b.named(1, "Joren")
    event, _ = b.event()
    occurred = b.occurred(event, 1)
    b.claim(b.prop("Participates", event=V(event), participant=E(mira), role=ROLE("AGENT")), [[b.ev(1)]])
    emotion = b.prop("EmotionToward", holder=E(mira), target=E(joren), emotion=S("anger"))
    if variant == "overstated":
        b.claim(emotion, [[b.ev(1)]], status="EXPLICIT", validity=OPEN)
    else:
        b.claim(emotion, status="SUGGESTED", derivations=[("BEHAVIOUR_SUGGESTS_STATE", [occurred])], validity=OPEN)


def c13_self_report(b, variant):
    joren = b.named(1, "Joren")
    mira = b.named(1, "Mira")
    utterance, _ = b.event("UTTERANCE")
    b.occurred(utterance, 1)
    b.claim(b.prop("Participates", event=V(utterance), participant=E(mira), role=ROLE("AGENT")), [[b.ev(1)]])
    content = b.prop("EmotionToward", holder=E(mira), target=E(joren), emotion=S("anger"))
    b.claim(b.prop("Says", speaker=E(mira), content=P(content), content_polarity=POL("NEGATED")), [[b.ev(1)]])
    if variant in ("explicit_leak", "suggested_leak"):
        quote = b.ev(1, '"I am not angry at Joren,"', role="IN_WORLD_REPORT")
        # explicit_leak: self-report promoted to an EXPLICIT internal state (the frozen validator rejects it).
        # suggested_leak: weaker and structurally legal, but still a truth leak.
        b.claim(content, [[quote]], status="EXPLICIT" if variant == "explicit_leak" else "SUGGESTED",
                polarity="NEGATED", validity=OPEN)


def c14_reported_event(b, variant):
    joren = b.named(1, "Joren")
    mira = b.named(1, "Mira")
    utterance, _ = b.event("UTTERANCE")
    b.occurred(utterance, 1)
    b.claim(b.prop("Participates", event=V(utterance), participant=E(mira), role=ROLE("AGENT")), [[b.ev(1)]])
    reported, _ = b.event()                 # the event record exists; that does not make it occur
    content = b.prop("Occurred", event=V(reported))
    b.claim(b.prop("Says", speaker=E(mira), content=P(content), content_polarity=POL()), [[b.ev(1)]])
    if variant == "truth_leak":
        b.claim(content, [[b.ev(1, '"Joren broke the seal yesterday,"', role="IN_WORLD_REPORT")]])


def c15_says_embedded(b, variant):
    lantern = b.named(1, "The lantern", kind="OBJECT")
    joren = b.named(1, "Joren")
    content = b.prop("Owns", owner=E(joren), item=E(lantern))
    b.claim(b.prop("Says", speaker=E(joren), content=P(content), content_polarity=POL()), [[b.ev(1)]])


def c16_belief(b, variant):
    mira, joren = b.named(1, "Mira"), b.named(1, "Joren")
    lantern = b.named(1, "the lantern", kind="OBJECT")
    content = b.prop("Owns", owner=E(joren), item=E(lantern))
    b.claim(b.prop("Attitude", holder=E(mira), attitude=TOK("attitude_kind", "HOLDS_TRUE"), content=P(content),
                   content_polarity=POL()), [[b.ev(1, role="NARRATION_SUMMARY")]], validity=OPEN)
    if variant == "truth_leak":
        b.claim(content, [[b.ev(1, role="NARRATION_SUMMARY")]], validity=OPEN)


def c17_conceal_convey(b, variant):
    joren, mira = b.named(1, "Joren"), b.named(1, "Mira")
    lantern = b.named(1, "the lantern", kind="OBJECT")
    content = b.prop("Owns", owner=E(joren), item=E(lantern))
    b.claim(b.prop("Conceals", concealer=E(joren), content=P(content), content_polarity=SPOL(),
                   concealed_from=E(mira)), [[b.ev(1, role="NARRATION_SUMMARY")]], validity=OPEN)
    tell, _ = b.event("REVEAL_TELL")
    b.occurred(tell, 2)
    b.claim(b.prop("Participates", event=V(tell), participant=E(joren), role=ROLE("AGENT")), [[b.ev(2)]])
    b.claim(b.prop("Conveys", event=V(tell), content=P(content), content_polarity=SPOL()), [[b.ev(2)]])


def c18_explicit_causality(b, variant):
    bell, _ = b.event()
    run, _ = b.event("MOVEMENT")
    b.occurred(bell, 1, "the bell rang")
    b.occurred(run, 1, "the guards ran to the wall")
    b.claim(b.prop("Causes", cause=V(bell), effect=V(run)), [[b.ev(1)]])


def c19_adjacency_no_causality(b, variant):
    bell, _ = b.event()
    run, _ = b.event("MOVEMENT")
    b.occurred(bell, 1, "The bell rang.")
    b.occurred(run, 1, "The guards ran to the wall.")
    if variant == "invented_causality":
        b.claim(b.prop("Causes", cause=V(bell), effect=V(run)), [[b.ev(1)]], status="ENTAILED")


def c20_state_open_end(b, variant):
    mira = b.named(1, "Mira")
    lantern = b.named(1, "the lantern", kind="OBJECT")
    validity = OPEN
    if variant == "invented_end":
        event, anchor = b.event()
        b.occurred(event, 1)
        validity = {"start": {"kind": "OPEN"}, "end": b.bound(anchor, [[b.ev(1)]])}
    b.claim(b.prop("Possesses", holder=E(mira), item=E(lantern)), [[b.ev(1)]], validity=validity)


def c21_state_end_learned_later(b, variant):
    mira = b.named(1, "Mira")
    lantern = b.named(1, "the lantern", kind="OBJECT")
    give, anchor = b.event("TRANSFER")
    b.occurred(give, 2, role="RETROSPECTIVE")
    b.claim(b.prop("Participates", event=V(give), participant=E(mira), role=ROLE("SOURCE")),
            [[b.ev(2, role="RETROSPECTIVE")]])
    end = {"kind": "OPEN"} if variant == "missing_end" else b.bound(anchor, [[b.ev(2, role="RETROSPECTIVE")]])
    b.claim(b.prop("Possesses", holder=E(mira), item=E(lantern)), [[b.ev(1)]],
            validity={"start": {"kind": "OPEN"}, "end": end})


def c22_mixed_segment_roles(b, variant):
    event, _ = b.event()
    if variant == "whole_segment_one_role":
        b.occurred(event, 1)                                   # the whole mixed segment as DEPICTION
    else:
        b.occurred(event, 1, "Mira opened the gate.")
        b.ev(1, "Author note: thanks for reading.",
             role="DEPICTION" if variant == "paratext_as_depiction" else "PARATEXT")


def c23_multi_evidence_sufficient(b, variant):
    mira = b.named(2, "Mira", role="RETROSPECTIVE")
    event, _ = b.event()
    b.occurred(event, 1)
    b.claim(b.prop("Participates", event=V(event), participant=E(mira), role=ROLE("AGENT")),
            [[b.ev(1), b.ev(2, role="RETROSPECTIVE")]])


def c24_partial_not_sufficient(b, variant):
    mira = b.named(2, "Mira", role="RETROSPECTIVE")
    event, _ = b.event()
    b.occurred(event, 1)
    participation = b.prop("Participates", event=V(event), participant=E(mira), role=ROLE("AGENT"))
    if variant == "partial_marked_sufficient":
        b.claim(participation, [[b.ev(2, role="RETROSPECTIVE")]])
    else:
        b.claim(participation, [[b.ev(1), b.ev(2, role="RETROSPECTIVE")]], partial=[[b.ev(1)]])


def c25_negated_event(b, variant):
    b.named(1, "Mira")
    event, _ = b.event()
    b.occurred(event, 1, polarity="AFFIRMED" if variant == "wrong_polarity" else "NEGATED")


def c26_duplicate_proposition(b, variant):
    event, _ = b.event()
    b.occurred(event, 1)
    if variant == "duplicate_proposition":
        b.dedupe = False
        b.occurred(event, 1)


CASES = {
    "c01_named_character": ("Mira opened the gate.", c01_named_character),
    "c02_two_mentions_one_entity": ("Mira opened the gate.\n\nThe captain smiled.", c02_two_mentions_one_entity),
    "c03_unknown_referent": ("A hooded stranger watched from the bridge.", c03_unknown_referent),
    "c04_later_same_as": ("A hooded stranger watched from the bridge.\n\nThe hood fell back: it was Mira.",
                          c04_later_same_as),
    "c05_event_occurred": ("The gate opened at dawn.", c05_event_occurred),
    "c06_participant": ("Mira opened the gate.", c06_participant),
    "c07_location": ("Mira waited in the courtyard.", c07_location),
    "c08_possession": ("Mira held the lantern.", c08_possession),
    "c09_ownership": ("The lantern belonged to Joren.", c09_ownership),
    "c10_relationship_state": ("Mira trusted Joren completely.", c10_relationship_state),
    "c11_explicit_emotion": ("Mira was furious at Joren.", c11_explicit_emotion),
    "c12_suggested_emotion": ("Mira slammed the door when Joren arrived.", c12_suggested_emotion),
    "c13_self_report": ('"I am not angry at Joren," Mira said.', c13_self_report),
    "c14_reported_event": ('"Joren broke the seal yesterday," Mira said.', c14_reported_event),
    "c15_says_embedded": ('"The lantern belongs to me," Joren said.', c15_says_embedded),
    "c16_belief": ("Mira believed that Joren owned the lantern.", c16_belief),
    "c17_conceal_convey": ("Joren hid from Mira that he owned the lantern.\n\nThat night Joren told her.",
                           c17_conceal_convey),
    "c18_explicit_causality": ("Because the bell rang, the guards ran to the wall.", c18_explicit_causality),
    "c19_adjacency_no_causality": ("The bell rang. The guards ran to the wall.", c19_adjacency_no_causality),
    "c20_state_open_end": ("Mira held the lantern.", c20_state_open_end),
    "c21_state_end_learned_later": ("Mira held the lantern.\n\nBy nightfall she had given it away.",
                                    c21_state_end_learned_later),
    "c22_mixed_segment_roles": ("Chapter One\nMira opened the gate.\nAuthor note: thanks for reading.",
                                c22_mixed_segment_roles),
    "c23_multi_evidence_sufficient": ("Someone opened the gate at dawn.\n\nIt was Mira who had opened it.",
                                      c23_multi_evidence_sufficient),
    "c24_partial_not_sufficient": ("Someone opened the gate at dawn.\n\nIt had been Mira.",
                                   c24_partial_not_sufficient),
    "c25_negated_event": ("Mira did not open the gate.", c25_negated_event),
    "c26_duplicate_proposition": ("The gate opened at dawn.", c26_duplicate_proposition),
}


def build(case_id, variant="gold", prefix="g", method="HUMAN_ANNOTATION"):
    """Return (ingestion, base skeleton, batch) for one case and variant."""
    text, function = CASES[case_id]
    ingestion, base = ingest_text(text)
    builder = Builder(ingestion, base, prefix=prefix, method=method)
    function(builder, variant)
    return ingestion, base, builder.batch()
