"""Synthetic TOKEN vocabulary repairs and canonical compiler regressions."""
from copy import deepcopy
import json
import unittest

from tests.story_extraction import fixture_builder as fx
from tests.story_extraction.test_draft_mention_evidence_v1 import example, group, evidence
from tools.story_extraction import run_m4_p4_dev_v1 as runner
from tools.story_extraction.draft_compiler_v1 import DraftCompilerContext
from tools.story_extraction.draft_compiler_v1_1 import migrate_draft_v1_to_v1_1
from tools.story_extraction.draft_coverage_v1 import canonical_gold_to_draft_v1
from tools.story_extraction.draft_vocabulary_guard_v1 import guard_vocabulary


ZERO = dict.fromkeys(("NORMALIZED", "DROPPED", "REFUSED_REFERENCED", "UNKNOWN_VOCABULARY"), 0)


class VocabularyGuardTests(unittest.TestCase):
    def test_membership_normalization_polarity_and_unknown_vocabulary(self):
        for predicate, name, vocab, value, expected, outcome in (
            ("NamedAs", "name_kind", "name_kind", "GIVEN", "GIVEN", None),
            ("NamedAs", "name_kind", "name_kind", "given", "GIVEN", "NORMALIZED"),
            ("Attitude", "attitude", "attitude_kind", "holds true", "HOLDS_TRUE", "NORMALIZED"),
            ("Attitude", "attitude", "attitude_kind", "kept-unaware", "KEPT_UNAWARE", "NORMALIZED"),
            ("Says", "content_polarity", "polarity", "open", "OPEN", "NORMALIZED"),
            ("Conceals", "content_polarity", "signed_polarity", "negated", "NEGATED", "NORMALIZED"),
            ("NamedAs", "name_kind", "unregistered", "given", "given", "UNKNOWN_VOCABULARY"),
            ("NamedAs", "name_kind", "polarity", "affirmed", "affirmed", None),
        ):
            with self.subTest(vocab=vocab, value=value):
                draft, prepared = example()
                prop = draft["propositions"][1]
                prop.update(predicate=predicate, args={name: fx.TOK(vocab, value)})
                before = deepcopy((draft, prepared))
                result, report = guard_vocabulary(draft, prepared)
                self.assertEqual((result, report), guard_vocabulary(draft))
                self.assertEqual(result["propositions"][1]["args"][name]["value"], expected)
                self.assertEqual(report, {"outcomes": ZERO | ({outcome: 1} if outcome else {}),
                    "by_vocabulary": {vocab: ZERO | {outcome: 1}} if outcome else {},
                    "assertions_dropped": 0, "evidence_items_removed": 0})
                result["mentions"].clear()
                self.assertEqual((draft, prepared), before)

    def test_invalid_named_as_is_the_only_loss_in_canonical_validation(self):
        ingestion, base, batch = fx.build("c01_named_character")
        scope = batch["scope"]
        context = DraftCompilerContext(base, scope["passage_inputs"], scope["as_of_position"],
                                       scope["profile_id"], "DEV_V1", "v1", "DEV_V1", ingestion)
        draft, _ = canonical_gold_to_draft_v1(batch, context)
        draft = migrate_draft_v1_to_v1_1(draft)
        named = next(p for p in draft["propositions"] if p["predicate"] == "NamedAs")
        named["args"]["name_kind"]["value"] = "INVENTED"
        raw = json.dumps(draft)
        _, compiled, validation = runner.validate_raw(raw, context)
        self.assertIsNone(compiled)
        self.assertEqual(validation["blockers"][0]["code"], "CANONICAL_CONFORMANCE_FAILURE")
        case = runner.CaseInput("DEV2_01", {}, context, ())
        *_, diagnosis = runner.validate_attempt(raw, case, rich_repair_blockers=True)
        self.assertIn("predicate_integrity:ARGUMENT_TOKEN_NOT_IN_VOCABULARY",
                      [b["code"] for b in diagnosis["blockers"]])
        result, report = guard_vocabulary(draft)
        self.assertEqual(report["outcomes"], ZERO | {"DROPPED": 1})
        self.assertEqual([p["predicate"] for p in result["propositions"]], ["RefersTo"])
        self.assertEqual(result["mentions"], draft["mentions"])
        self.assertEqual(result["entities"], draft["entities"])
        _, compiled, validation = runner.validate_raw(json.dumps(result), context)
        self.assertTrue(validation["pass"], validation)
        self.assertEqual(len(compiled["candidate_records"]["assertions"]), 1)

    def test_only_evidence_orphaned_by_removed_claims_is_pruned(self):
        draft, _ = example()
        draft["propositions"][1]["args"]["name_kind"] = fx.TOK("name_kind", "INVENTED")
        draft["evidence"] += [evidence("EV2", "Mira"), evidence("EV3", "previously unused")]
        named = draft["assertions"][1]
        named["support"]["evidence_sets"] = [group("EV1", "EV2")]
        draft["assertions"].append({**named, "handle": "A3"})
        # A literal spelling the target handle is not a reference.
        draft["mentions"][0]["quote"] = "PROP2"
        before = deepcopy(draft)
        result, report = guard_vocabulary(draft)
        self.assertEqual(result, {**before, "propositions": before["propositions"][:1],
            "assertions": before["assertions"][:1], "evidence": before["evidence"][::2]})
        self.assertEqual(report, {"outcomes": ZERO | {"DROPPED": 1},
            "by_vocabulary": {"name_kind": ZERO | {"DROPPED": 1}}, "assertions_dropped": 2,
            "evidence_items_removed": 1})
        self.assertEqual(draft, before)

    def test_external_references_refuse_entire_proposition_edit(self):
        for kind in ("argument", "alternative", "premise"):
            with self.subTest(kind=kind):
                draft, _ = example()
                draft["propositions"][1].update(predicate="Attitude", args={
                    "attitude": fx.TOK("attitude_kind", "holds-true"),
                    "content_polarity": fx.TOK("polarity", "INVENTED"),
                })
                if kind == "argument":
                    draft["propositions"][0]["args"]["content"] = {"kind": "PROPOSITION", "handle": "PROP2"}
                elif kind == "alternative":
                    draft["assertions"][0]["textual_ambiguity"] = {"alternative_proposition_handles": ["PROP2"]}
                else:
                    draft["assertions"][0]["support"]["derivations"] = [{"premise_handles": ["A2"]}]
                result, report = guard_vocabulary(draft)
                self.assertEqual(result, draft)
                self.assertEqual(report, {"outcomes": ZERO | {"REFUSED_REFERENCED": 1},
                    "by_vocabulary": {"polarity": ZERO | {"REFUSED_REFERENCED": 1}},
                    "assertions_dropped": 0, "evidence_items_removed": 0})

    def test_two_invalid_tokens_count_as_one_drop_in_either_argument_order(self):
        args = {"attitude": fx.TOK("attitude_kind", "INVENTED"),
                "content_polarity": fx.TOK("polarity", "INVENTED")}
        for ordered in (args, dict(reversed(args.items()))):
            with self.subTest(order=list(ordered)):
                draft, _ = example()
                draft["propositions"][1].update(predicate="Attitude", args=ordered)
                result, report = guard_vocabulary(draft)
                self.assertEqual(result["propositions"], draft["propositions"][:1])
                self.assertEqual(report["outcomes"], ZERO | {"DROPPED": 1})
                self.assertEqual(report["by_vocabulary"], {"attitude_kind": ZERO | {"DROPPED": 1}})

    def test_malformed_records_are_left_for_validation(self):
        for draft in (None, [], {"propositions": [{}, {"handle": "PROP1", "args": {
                "role": fx.TOK("participant_role", None)}}], "assertions": [{"proposition_handle": []}]}):
            with self.subTest(draft=draft):
                self.assertEqual(guard_vocabulary(draft), (draft, {
                    "outcomes": ZERO, "by_vocabulary": {}, "assertions_dropped": 0, "evidence_items_removed": 0}))
