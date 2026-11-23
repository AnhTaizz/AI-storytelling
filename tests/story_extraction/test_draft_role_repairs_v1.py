"""Role host repairs over synthetic drafts: MR (mention role follows the sentence) and FR (frame roles)."""
from copy import deepcopy
import json
import unittest

from tests.story_extraction import fixture_builder as fx
from tools.story_extraction import run_m4_p4_dev_v1 as runner
from tools.story_extraction.draft_compiler_v1 import DraftCompilerContext
from tools.story_extraction.draft_compiler_v1_1 import migrate_draft_v1_to_v1_1
from tools.story_extraction.draft_coverage_v1 import canonical_gold_to_draft_v1
from tools.story_extraction.draft_role_repairs_v1 import (FR_OUTCOMES, MR_OUTCOMES, fix_frame_roles,
                                                           retag_mention_roles)
from tools.story_extraction.run_m4_04b3g_fv1_predictions_v1 import validate_raw

SUMMARY, SPEECH = "ミラは毎年門を磨いた。", "「ノアが来た」とミラは言った。"


def draft_case(build):
    ingestion, base = fx.ingest_text(SUMMARY + SPEECH)
    b = fx.Builder(ingestion, base)
    build(b)
    gold = b.batch()
    scope = gold["scope"]
    context = DraftCompilerContext(base, scope["passage_inputs"], scope["as_of_position"],
                                   scope["profile_id"], "DEV_V1", "v1", "DEV_V1", ingestion)
    draft, _ = canonical_gold_to_draft_v1(gold, context)
    return migrate_draft_v1_to_v1_1(draft), runner.CaseInput("DEV2_01", runner.prepare_story_extraction_draft_v1_1(
        context), context, ())


def mention_build(mention_role="DEPICTION", sentence_roles=("NARRATION_SUMMARY",), dialogue_role="DEPICTION"):
    def build(b):
        b.named(1, "ミラ", role=mention_role)
        for role in sentence_roles:
            event, _ = b.event("GENERIC")
            b.occurred(event, 1, SUMMARY[:-1] if role != "DEPICTION" else "門を磨いた", role=role)
        b.named(1, "ノア", role=dialogue_role)
        said, _ = b.event("UTTERANCE")
        b.occurred(said, 1, SPEECH[:-1])
    return build


def mention_roles(draft):
    props = {p["handle"]: p for p in draft["propositions"]}
    evidence = {e["handle"]: e for e in draft["evidence"]}
    return sorted(evidence[h]["role"] for a in draft["assertions"]
                  if props[a["proposition_handle"]]["predicate"] == "RefersTo"
                  for s in a["support"]["evidence_sets"] for h in s["evidence_handles"])


class MentionRoleTests(unittest.TestCase):
    def test_mention_evidence_takes_the_single_sentence_role(self):
        cases = (
            ("summary sentence", {}, "RETAGGED", ["DEPICTION", "NARRATION_SUMMARY"]),
            ("already consistent", {"mention_role": "NARRATION_SUMMARY"}, "ALREADY_CONSISTENT",
             ["DEPICTION", "NARRATION_SUMMARY"]),
            ("mixed sentence roles", {"sentence_roles": ("NARRATION_SUMMARY", "DEPICTION")}, "MIXED_SENTENCE_ROLES",
             ["DEPICTION", "DEPICTION"]),
            ("no other evidence", {"sentence_roles": ()}, "NO_SENTENCE_ROLE", ["DEPICTION", "DEPICTION"]),
        )
        for name, options, outcome, roles in cases:
            with self.subTest(name):
                draft, case = draft_case(mention_build(**options))
                before = deepcopy(draft)
                repaired, report = retag_mention_roles(draft, case.prepared_input)
                self.assertEqual(draft, before)
                self.assertEqual(report["outcomes"][outcome], 1)
                self.assertEqual(report["outcomes"]["IN_DIALOGUE"], 1)
                self.assertEqual(mention_roles(repaired), roles)
                self.assertIsNotNone(validate_raw(json.dumps(repaired, ensure_ascii=False),
                                                  case.compiler_context)[2])
                if outcome == "RETAGGED":
                    self.assertEqual((report["evidence_items_added"], report["evidence_items_removed"]), (1, 1))
                    again = retag_mention_roles(repaired, case.prepared_input)[1]
                    self.assertEqual(again["outcomes"]["ALREADY_CONSISTENT"], 1)

    def test_shared_items_are_not_edited_in_place_and_odd_inputs_are_safe(self):
        draft, case = draft_case(mention_build())
        mention = next(a for a in draft["assertions"]
                       if {p["handle"]: p for p in draft["propositions"]}[a["proposition_handle"]]["predicate"]
                       == "RefersTo")
        shared = mention["support"]["evidence_sets"][0]["evidence_handles"][0]
        other = deepcopy(mention)
        other["handle"] = "A99"
        draft["assertions"].append(other)
        repaired, report = retag_mention_roles(draft, case.prepared_input)
        self.assertEqual(report["outcomes"]["RETAGGED"], 2)
        self.assertEqual(report["evidence_items_added"], 1)
        self.assertNotIn(shared, {e["handle"] for e in repaired["evidence"]})
        broken = deepcopy(draft)
        next(e for e in broken["evidence"] if e["handle"] == shared)["quote"] = "存在しない"
        self.assertEqual(retag_mention_roles(broken, case.prepared_input)[1]["outcomes"]["NOT_LOCATED"], 2)
        for value in (None, [], "x"):
            self.assertEqual(retag_mention_roles(value, case.prepared_input),
                             (value, {"outcomes": dict.fromkeys(MR_OUTCOMES, 0), "evidence_items_added": 0,
                                      "evidence_items_removed": 0}))


class FrameRoleTests(unittest.TestCase):
    def test_patient_becomes_theme_only_where_the_frame_has_no_patient(self):
        def build(kind, extra_theme=False):
            def inner(b):
                mira = b.named(1, "ミラ")
                gate = b.entity("OBJECT")
                event, _ = b.event(kind)
                b.occurred(event, 1, "門を磨いた")
                b.claim(b.prop("Participates", event=fx.V(event), participant=fx.E(gate),
                               role=fx.ROLE("PATIENT")), [[b.ev(1, "門を磨いた")]])
                b.claim(b.prop("Participates", event=fx.V(event), participant=fx.E(mira),
                               role=fx.ROLE("AGENT")), [[b.ev(1, "門を磨いた")]])
                if extra_theme:
                    b.claim(b.prop("Participates", event=fx.V(event), participant=fx.E(gate),
                                   role=fx.ROLE("THEME")), [[b.ev(1, "門を磨いた")]])
            return inner
        cases = (("MOVEMENT", False, "PATIENT_TO_THEME", 1), ("GENERIC", False, None, 0),
                 ("MOVEMENT", True, "REFUSED_DUPLICATE", 1))
        for kind, extra, outcome, n in cases:
            with self.subTest(kind=kind, extra=extra):
                draft, case = draft_case(build(kind, extra))
                before = deepcopy(draft)
                repaired, report = fix_frame_roles(draft)
                self.assertEqual(draft, before)
                self.assertEqual(sum(report["outcomes"].values()), n)
                if outcome:
                    self.assertEqual(report["outcomes"][outcome], 1)
                roles = sorted(p["args"]["role"]["value"] for p in repaired["propositions"]
                               if p["predicate"] == "Participates")
                expected = {"PATIENT_TO_THEME": ["AGENT", "THEME"], None: ["AGENT", "PATIENT"],
                            "REFUSED_DUPLICATE": ["AGENT", "PATIENT", "THEME"]}[outcome]
                self.assertEqual(roles, expected)
        self.assertEqual(fix_frame_roles("x"), ("x", {"outcomes": dict.fromkeys(FR_OUTCOMES, 0)}))


if __name__ == "__main__":
    unittest.main()
