"""Date anchoring (Conventions V4, R-TIME-03) over synthetic drafts."""
from copy import deepcopy
import json
import unittest

from tests.story_extraction import fixture_builder as fx
from tools.story_extraction import run_m4_p4_dev_v1 as runner
from tools.story_extraction.draft_compiler_v1 import DraftCompilerContext
from tools.story_extraction.draft_compiler_v1_1 import migrate_draft_v1_to_v1_1
from tools.story_extraction.draft_coverage_v1 import canonical_gold_to_draft_v1
from tools.story_extraction.draft_date_anchor_v1 import OUTCOMES, anchor_dates_to_events
from tools.story_extraction.run_m4_04b3g_fv1_predictions_v1 import validate_raw

FIRST, SECOND = "四月一日、ミラは門に入った。", "ノアは笑った。"


def DATE(value):
    return {"kind": "LITERAL", "value_type": "DATE", "value": value}


def date_case(*, date_sentence=FIRST, second_event_in_first=False, event_date=None):
    """A named date, an entering event in the same sentence, a relation and a bound on the named anchor."""
    ingestion, base = fx.ingest_text(FIRST + SECOND)
    b = fx.Builder(ingestion, base)
    mira = b.named(1, "ミラ")
    gate = b.entity("LOCATION")
    enter, enter_anchor = b.event("MOVEMENT")
    b.occurred(enter, 1, FIRST[:-1])
    b.claim(b.prop("Participates", event=fx.V(enter), participant=fx.E(mira), role=fx.ROLE("AGENT")),
            [[b.ev(1, FIRST[:-1])]])
    laugh, _ = b.event("GENERIC")
    b.occurred(laugh, 1, FIRST[:-1] if second_event_in_first else SECOND[:-1])
    named = b._id("t")
    b.records["temporal_anchors"].append({"id": named, "anchor_kind": "NAMED_TIME"})
    b.claim(b.prop("AnchorDate", anchor=fx.T(named), date=DATE("--04-01")), [[b.ev(1, date_sentence[:-1])]])
    if event_date is not None:
        b.claim(b.prop("AnchorDate", anchor=fx.T(enter_anchor), date=DATE(event_date)), [[b.ev(1, FIRST[:-1])]])
    b.claim(b.prop("TemporalRelation", subject=fx.T(enter_anchor), relation=fx.TOK("temporal_relation", "DURING"),
                   object=fx.T(named)), [[b.ev(1, FIRST[:-1])]])
    b.claim(b.prop("LocatedAt", thing=fx.E(mira), location=fx.E(gate)), [[b.ev(1, FIRST[:-1])]],
            validity={"start": b.bound(named, [[b.ev(1, FIRST[:-1])]]), "end": {"kind": "OPEN"}})
    gold = b.batch()
    scope = gold["scope"]
    context = DraftCompilerContext(base, scope["passage_inputs"], scope["as_of_position"],
                                   scope["profile_id"], "DEV_V1", "v1", "DEV_V1", ingestion)
    draft, _ = canonical_gold_to_draft_v1(gold, context)
    prepared = runner.prepare_story_extraction_draft_v1_1(context)
    return migrate_draft_v1_to_v1_1(draft), runner.CaseInput("DEV2_01", prepared, context, ()), gold


def by_predicate(draft, predicate):
    props = {p["handle"]: p for p in draft["propositions"]}
    return [(a, props[a["proposition_handle"]]) for a in draft["assertions"]
            if props[a["proposition_handle"]]["predicate"] == predicate]


class DateAnchorTests(unittest.TestCase):
    def test_date_moves_to_the_event_anchor_with_its_references(self):
        draft, case, _ = date_case()
        before = deepcopy(draft)
        repaired, report = anchor_dates_to_events(draft, case.prepared_input)
        self.assertEqual(draft, before)
        named = [a["handle"] for a in draft["anchors"] if a["anchor_kind"] == "NAMED_TIME"]
        event_anchor = next(e["anchor_handle"] for e in repaired["events"] if e["event_kind"] == "MOVEMENT")
        (_, date), = by_predicate(repaired, "AnchorDate")
        self.assertEqual(date["args"]["anchor"]["handle"], event_anchor)
        self.assertEqual(by_predicate(repaired, "TemporalRelation"), [])
        (located, _), = by_predicate(repaired, "LocatedAt")
        self.assertEqual(located["validity"]["start"]["anchor_handle"], event_anchor)
        self.assertNotIn(named[0], {a["handle"] for a in repaired["anchors"]})
        self.assertEqual(report, {"outcomes": {**dict.fromkeys(OUTCOMES, 0), "MOVED": 1}, "relations_dropped": 1,
                                  "anchors_removed": 1, "duplicates_dropped": 0})
        self.assertIsNotNone(validate_raw(json.dumps(repaired, ensure_ascii=False), case.compiler_context)[2])
        self.assertEqual(anchor_dates_to_events(repaired, case.prepared_input)[1]["outcomes"]["ALREADY_EVENT_ANCHOR"], 1)

    def test_refusals_and_duplicates(self):
        cases = (
            ("no event", dict(date_sentence=SECOND, second_event_in_first=True), "NO_EVENT_IN_SENTENCE"),
            ("several events", dict(second_event_in_first=True), "SEVERAL_EVENTS_IN_SENTENCE"),
            ("conflicting date", dict(event_date="--05-01"), "CONFLICTING_DATE"),
            ("duplicate", dict(event_date="--04-01"), "MOVED"),
        )
        for name, options, outcome in cases:
            with self.subTest(name):
                draft, case, _ = date_case(**options)
                repaired, report = anchor_dates_to_events(draft, case.prepared_input)
                self.assertEqual(report["outcomes"][outcome], 1)
                if outcome != "MOVED":
                    self.assertEqual(repaired, draft)
                else:
                    self.assertEqual(report["duplicates_dropped"], 1)
                    self.assertEqual(len(by_predicate(repaired, "AnchorDate")), 1)
                    self.assertIsNotNone(validate_raw(json.dumps(repaired, ensure_ascii=False),
                                                      case.compiler_context)[2])

    def test_unlocated_and_degenerate_inputs(self):
        draft, case, _ = date_case()
        unlocated = deepcopy(draft)
        (claim, _), = by_predicate(unlocated, "AnchorDate")
        for group in claim["support"]["evidence_sets"]:
            group["label"] = "PARTIAL"
        self.assertEqual(anchor_dates_to_events(unlocated, case.prepared_input)[1]["outcomes"]["NOT_LOCATED"], 1)
        dangling = deepcopy(draft)
        (_, prop), = by_predicate(dangling, "AnchorDate")
        prop["args"]["anchor"]["handle"] = "T99"
        self.assertEqual(anchor_dates_to_events(dangling, case.prepared_input)[1]["outcomes"]["NOT_LOCATED"], 1)
        for value in (None, [], "x"):
            self.assertEqual(anchor_dates_to_events(value, case.prepared_input),
                             (value, {"outcomes": dict.fromkeys(OUTCOMES, 0), "relations_dropped": 0,
                                      "anchors_removed": 0, "duplicates_dropped": 0}))


if __name__ == "__main__":
    unittest.main()
