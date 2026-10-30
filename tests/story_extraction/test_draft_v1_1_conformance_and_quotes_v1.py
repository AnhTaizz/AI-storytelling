"""Offline reproductions for M4-04B4B failure-class investigation.

Covers canonical-conformance classification, repeated-quote location and the
deterministic mention-evidence binding. All drafts are synthetic.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from p3_v1_1_offline_support import (  # noqa: E402
    JA_REPEATED_NAME_TEXT,
    japanese_repeated_name_case,
    oracle_case,
)

from tools.story_extraction import draft_compiler_v1  # noqa: E402
from tools.story_extraction.draft_compiler_v1 import _occurrences  # noqa: E402
from tools.story_extraction.draft_compiler_v1_1 import (  # noqa: E402
    DraftCompilationErrorV1_1,
    bind_exact_mention_evidence_v1_1,
    compile_story_extraction_draft_v1_1,
)
from tools.story_extraction.extraction_contract_guard_v1 import (  # noqa: E402
    validate_batch_guarded,
)
from tools.story_extraction.draft_v1_1_conformance_diagnostics_v1 import (  # noqa: E402
    classify_issue,
    compile_with_diagnostics_v1_1,
    local_label,
)


def outcome(draft, context):
    try:
        return ("batch", compile_story_extraction_draft_v1_1(deepcopy(draft), context))
    except DraftCompilationErrorV1_1 as error:
        return ("error", [blocker.as_dict() for blocker in error.blockers])


class CanonicalConformanceTests(unittest.TestCase):
    MUTATIONS = {
        "UNREGISTERED_PREDICATE": ("c06_participant",
                                   lambda d: d["propositions"][0].__setitem__("predicate", "Unregistered")),
        "FORBIDDEN_VERDICT_PREDICATE": ("c06_participant",
                                        lambda d: d["propositions"][0].__setitem__("predicate", "Knows")),
        "TOKEN_NOT_IN_VOCABULARY": ("c06_participant", None),
        "NO_SUPPORT_PATH": ("c06_participant", None),
        "INTERNAL_STATE_EXPLICIT_WITHOUT_DEPICTION": ("c11_explicit_emotion", None),
        "VALIDITY_ON_NON_STATIVE_PREDICATE": ("c05_event_occurred", None),
        "UNREGISTERED_EVENT_KIND": ("c05_event_occurred",
                                    lambda d: d["events"][0].__setitem__("event_kind", "NOT_A_KIND")),
    }

    @staticmethod
    def _apply(code, draft):
        if code == "TOKEN_NOT_IN_VOCABULARY":
            for proposition in draft["propositions"]:
                for argument in proposition.get("args", {}).values():
                    if argument.get("kind") == "TOKEN":
                        argument["value"] = "NOT_IN_VOCABULARY"
                        return
        elif code == "NO_SUPPORT_PATH":
            for evidence_set in draft["assertions"][0]["support"]["evidence_sets"]:
                evidence_set["label"] = "PARTIAL"
        elif code == "INTERNAL_STATE_EXPLICIT_WITHOUT_DEPICTION":
            for evidence in draft["evidence"]:
                evidence["role"] = "IN_WORLD_REPORT"
        elif code == "VALIDITY_ON_NON_STATIVE_PREDICATE":
            draft["assertions"][0]["validity"] = {"start": {"kind": "OPEN"}, "end": {"kind": "OPEN"}}

    def test_model_owned_registry_and_epistemic_violations_reach_canonical_stage(self):
        for code, (name, mutate) in self.MUTATIONS.items():
            with self.subTest(code=code):
                case, draft = oracle_case(name)
                (mutate or (lambda d: self._apply(code, d)))(draft)
                batch, diagnostics = compile_with_diagnostics_v1_1(draft, case.context)
                self.assertIsNone(batch)
                self.assertEqual(
                    diagnostics["blockers"],
                    [{"phase": "CANONICAL_COMPILER", "code": "CANONICAL_CONFORMANCE_FAILURE",
                      "path": "canonical"}],
                )
                self.assertIn(code, {item["code"] for item in diagnostics["canonical_issue_classes"]})

    def test_observer_never_changes_the_compile_outcome(self):
        for name in ("c02_two_mentions_one_entity", "c06_participant"):
            case, draft = oracle_case(name)
            broken = deepcopy(draft)
            broken["propositions"][0]["predicate"] = "Unregistered"
            for candidate in (draft, broken):
                with self.subTest(name=name, valid=candidate is draft):
                    expected = outcome(candidate, case.context)
                    batch, diagnostics = compile_with_diagnostics_v1_1(deepcopy(candidate),
                                                                       case.context)
                    actual = ("batch", batch) if batch is not None else (
                        "error", diagnostics["blockers"])
                    self.assertEqual(actual, expected)
        self.assertIs(draft_compiler_v1.validate_batch_guarded, validate_batch_guarded)

    def test_diagnostics_never_echo_source_or_model_values(self):
        case, draft = oracle_case("c06_participant")
        for proposition in draft["propositions"]:
            for argument in proposition.get("args", {}).values():
                if argument.get("kind") == "TOKEN":
                    argument["value"] = "SECRET_MODEL_VALUE"
        _, diagnostics = compile_with_diagnostics_v1_1(draft, case.context)
        text = json.dumps(diagnostics)
        self.assertNotIn("SECRET_MODEL_VALUE", text)
        for passage in case.prepared_input["passages"]:
            self.assertNotIn(passage["text"], text)

    def test_classifier_maps_ids_to_local_handles_and_drops_messages(self):
        self.assertEqual(local_label("draftv1-0123456789abcdef01234567-A3"), "A3")
        self.assertEqual(local_label("g-a-001"), "EXISTING_RECORD")
        item = classify_issue("canonical", "STRUCTURAL: candidate_records/mentions/0/surface_form: "
                                           "'quoted model text' is too long")
        self.assertEqual(item["code"], "CANONICAL_SCHEMA_VIOLATION")
        self.assertNotIn("quoted", json.dumps(item))
        self.assertEqual(classify_issue("evidence", "SPAN_MISMATCH: evidence ref x")["code"],
                         "SPAN_MISMATCH")
        self.assertEqual(classify_issue("canonical", "predicate_integrity: something new")["code"],
                         "UNCLASSIFIED")


class RepeatedQuoteTests(unittest.TestCase):
    def test_occurrence_counting_includes_overlapping_matches(self):
        self.assertEqual(_occurrences("ははは", "はは"), [0, 1])
        self.assertEqual(_occurrences(JA_REPEATED_NAME_TEXT, "真白"), [0, 7])

    def test_omitted_occurrence_on_repeated_quote_is_rejected(self):
        case, draft = japanese_repeated_name_case()
        for record in draft["mentions"] + draft["evidence"]:
            record.pop("occurrence", None)
        _, diagnostics = compile_with_diagnostics_v1_1(draft, case.context)
        codes = {item["code"] for item in diagnostics["blockers"]}
        self.assertEqual(codes, {"AMBIGUOUS_QUOTE"})
        self.assertEqual(len(diagnostics["blockers"]), 2)

    def test_out_of_range_occurrence_is_rejected(self):
        case, draft = japanese_repeated_name_case()
        draft["mentions"][0]["occurrence"] = 3
        _, diagnostics = compile_with_diagnostics_v1_1(draft, case.context)
        self.assertEqual({item["code"] for item in diagnostics["blockers"]},
                         {"OCCURRENCE_OUT_OF_RANGE"})

    def test_wrong_but_in_range_occurrence_compiles_silently_to_the_other_span(self):
        """Structural validity cannot detect a mislocated repeated quote."""
        case, draft = japanese_repeated_name_case()
        right = compile_story_extraction_draft_v1_1(deepcopy(draft), case.context)
        wrong_draft = deepcopy(draft)
        wrong_draft["mentions"][0]["occurrence"] = 2
        wrong = compile_story_extraction_draft_v1_1(wrong_draft, case.context)

        def mention_span(batch):
            records = batch["candidate_records"]
            evidence = {item["id"]: item for item in records["evidence_refs"]}
            return evidence[records["mentions"][0]["evidence_ref_id"]]["span"]

        self.assertNotEqual(mention_span(right), mention_span(wrong))

    def test_longer_unique_evidence_quote_needs_no_occurrence(self):
        case, draft = japanese_repeated_name_case()
        draft["evidence"][0]["quote"] = "真白は笑った"
        draft["evidence"][0].pop("occurrence", None)
        batch, diagnostics = compile_with_diagnostics_v1_1(draft, case.context)
        self.assertIsNotNone(batch, diagnostics)


class MentionGroundingTests(unittest.TestCase):
    def test_mention_binding_uses_exact_span_and_role_identity(self):
        case, draft = japanese_repeated_name_case()
        bound, stats = bind_exact_mention_evidence_v1_1(draft, case.context)
        self.assertEqual(stats["reused_exact_model_evidence"], 1)
        draft["mentions"][0]["role"] = "NARRATION_SUMMARY"
        bound, stats = bind_exact_mention_evidence_v1_1(draft, case.context)
        self.assertEqual(stats["reused_exact_model_evidence"], 0)
        self.assertEqual(stats["created_exact_mention_evidence"], 1)

    def test_binding_is_deterministic_and_never_touches_assertion_support(self):
        case, draft = oracle_case("c02_two_mentions_one_entity")
        first = bind_exact_mention_evidence_v1_1(deepcopy(draft), case.context)
        reordered = deepcopy(draft)
        reordered["mentions"].reverse()
        reordered["evidence"].reverse()
        second = bind_exact_mention_evidence_v1_1(reordered, case.context)
        self.assertEqual(first[1], second[1])
        self.assertEqual(
            sorted(json.dumps(item, sort_keys=True) for item in first[0]["evidence"]),
            sorted(json.dumps(item, sort_keys=True) for item in second[0]["evidence"]),
        )
        self.assertEqual([item["support"] for item in first[0]["assertions"]],
                         [item["support"] for item in draft["assertions"]])

    def test_compiler_accepts_ungrounded_surface_form_and_orphan_mentions(self):
        """Documented gaps: neither is a structural error, so the runner reports advisories."""
        case, draft = japanese_repeated_name_case()
        draft["mentions"][0]["surface_form"] = "別人"
        batch = compile_story_extraction_draft_v1_1(deepcopy(draft), case.context)
        self.assertEqual(batch["candidate_records"]["mentions"][0]["surface_form"], "別人")
        orphan = deepcopy(draft)
        orphan["mentions"].append({"handle": "M9", "passage_handle": "P1", "quote": "窓",
                                   "role": "DEPICTION"})
        self.assertIsNotNone(compile_story_extraction_draft_v1_1(orphan, case.context))


if __name__ == "__main__":
    unittest.main()
