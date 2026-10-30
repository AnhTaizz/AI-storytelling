"""M4-04B4B-R1: silent grounding corruption under Draft V1.1, synthetic text only.

Each test documents current behaviour. A passing test here records that a corruption
mechanism exists (or that a safeguard holds); it does not endorse the behaviour.
The context-selector helper at the end is a test-local analysis aid, not a V1.2
implementation.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unicodedata
import unittest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixture_builder as fx  # noqa: E402

from tools.story_extraction.draft_compiler_v1 import DraftCompilerContext, _occurrences  # noqa: E402
from tools.story_extraction.draft_compiler_v1_1 import (  # noqa: E402
    DraftCompilationErrorV1_1,
    compile_story_extraction_draft_v1_1,
    migrate_draft_v1_to_v1_1,
)
from tools.story_extraction.draft_coverage_v1 import canonical_gold_to_draft_v1  # noqa: E402
from tools.story_extraction.evaluate_extraction_guarded_v1 import evaluate_case  # noqa: E402
from tools.story_extraction.extraction_contract_guard_v1 import validate_batch_guarded  # noqa: E402

E, S, TOK = fx.E, fx.S, fx.TOK
OPEN = {"start": {"kind": "OPEN"}, "end": {"kind": "OPEN"}}


def build(text, author):
    """Synthetic gold over invented text, its context and the oracle V1.1 draft."""
    ingestion, base = fx.ingest_text(text)
    builder = fx.Builder(ingestion, base)
    author(builder)
    gold = builder.batch()
    scope = gold["scope"]
    context = DraftCompilerContext(base, scope["passage_inputs"], scope["as_of_position"],
                                   scope["profile_id"], "r1-probe", "v1", "r1", ingestion)
    draft, _ = canonical_gold_to_draft_v1(gold, context)
    return context, gold, migrate_draft_v1_to_v1_1(draft)


def compile_ok(draft, context):
    return compile_story_extraction_draft_v1_1(deepcopy(draft), context)


def blocker_codes(draft, context):
    try:
        compile_story_extraction_draft_v1_1(deepcopy(draft), context)
    except DraftCompilationErrorV1_1 as error:
        return {blocker.code for blocker in error.blockers}
    return set()


def mention_span(batch, index=0):
    records = batch["candidate_records"]
    evidence = {item["id"]: item for item in records["evidence_refs"]}
    ref = evidence[records["mentions"][index]["evidence_ref_id"]]
    return ref["segment_id"], ref["span"]["char_start"], ref["span"]["char_end_exclusive"]


def colocated(batch):
    """Analysis aid: every RefersTo SUFFICIENT set contains a span covering its mention."""
    records = batch["candidate_records"]
    evidence = {item["id"]: item for item in records["evidence_refs"]}
    mentions = {item["id"]: item for item in records["mentions"]}
    propositions = {item["id"]: item for item in records["propositions"]}
    for assertion in records["assertions"]:
        proposition = propositions[assertion["proposition_id"]]
        if proposition.get("predicate") != "RefersTo":
            continue
        mention = mentions[proposition["args"]["mention"]["ref"]]
        target = evidence[mention["evidence_ref_id"]]
        covered = False
        for evidence_set in assertion["support"]["evidence_sets"]:
            if evidence_set["label"] != "SUFFICIENT":
                continue
            for ref_id in evidence_set["evidence_ref_ids"]:
                ref = evidence[ref_id]
                if (ref["segment_id"] == target["segment_id"]
                        and ref["span"]["char_start"] <= target["span"]["char_start"]
                        and target["span"]["char_end_exclusive"] <= ref["span"]["char_end_exclusive"]):
                    covered = True
        if not covered:
            return False
    return True


def named_once(builder):
    builder.named(1, "真白")


TWO_NAMES = "真白は笑った。真白は窓を開けた。"


class WrongOccurrenceTests(unittest.TestCase):
    def test_wrong_in_range_mention_occurrence_is_structurally_valid_and_provenance_consistent(self):
        context, gold, draft = build(TWO_NAMES, named_once)
        wrong = deepcopy(draft)
        wrong["mentions"][0]["occurrence"] = 2
        batch = compile_ok(wrong, context)
        report = validate_batch_guarded(batch, context.base_document, context.ingestion)
        self.assertTrue(report["pass"])                     # source-exact re-derivation passes
        right = compile_ok(draft, context)
        self.assertNotEqual(mention_span(batch), mention_span(right))
        segment, start, end = mention_span(batch)
        self.assertEqual(context.ingestion.segment_text(segment)[start:end], "真白")

    def test_only_gold_based_evaluation_detects_the_mislocation(self):
        context, gold, draft = build(TWO_NAMES, named_once)
        control = evaluate_case(context.base_document, gold, compile_ok(draft, context),
                                ingestion=context.ingestion)
        self.assertEqual(control["case_outcome"], "SUCCESS")
        wrong = deepcopy(draft)
        for record in wrong["mentions"] + wrong["evidence"]:
            record["occurrence"] = 2
        result = evaluate_case(context.base_document, gold, compile_ok(wrong, context),
                               ingestion=context.ingestion)
        self.assertTrue(result["l0_structural_validity"])
        self.assertEqual(result["case_outcome"], "FAIL")
        self.assertIn("MISSING_ENTITY_RESOLUTION", result["failure_codes"])

    def test_consistently_wrong_mention_and_evidence_defeat_colocation_check(self):
        context, _, draft = build(TWO_NAMES, named_once)
        wrong = deepcopy(draft)
        for record in wrong["mentions"] + wrong["evidence"]:
            record["occurrence"] = 2
        self.assertTrue(colocated(compile_ok(wrong, context)))

    def test_inconsistent_mention_occurrence_is_caught_by_colocation_check(self):
        context, _, draft = build(TWO_NAMES, named_once)
        wrong = deepcopy(draft)
        wrong["evidence"][0]["quote"] = "真白は笑った"
        wrong["evidence"][0].pop("occurrence", None)
        wrong["mentions"][0]["occurrence"] = 2
        batch = compile_ok(wrong, context)
        self.assertFalse(colocated(batch))
        self.assertTrue(colocated(compile_ok(draft, context)))

    def test_wrong_passage_with_the_same_quote_is_structurally_valid(self):
        context, _, draft = build("真白は笑った。\n\n真白は窓を開けた。", named_once)
        wrong = deepcopy(draft)
        for record in wrong["mentions"] + wrong["evidence"]:
            record["passage_handle"] = "P2"
        right_segment = mention_span(compile_ok(draft, context))[0]
        wrong_segment = mention_span(compile_ok(wrong, context))[0]
        self.assertNotEqual(right_segment, wrong_segment)

    def test_wrong_evidence_occurrence_for_repeated_dialogue_is_structurally_valid(self):
        text = "真白は「はい」と答えた。遥も「はい」と答えた。"

        def author(builder):
            haruka = builder.named(1, "遥")
            builder.claim(builder.prop("NamedAs", entity=E(haruka), name=S("遥"),
                                       name_kind=TOK("name_kind", "GIVEN")),
                          [[builder.ev(1, "遥")]], validity=OPEN)

        context, _, draft = build(text, author)
        wrong = deepcopy(draft)
        wrong["evidence"].append({"handle": "EV9", "passage_handle": "P1", "quote": "「はい」",
                                  "occurrence": 1, "role": "DEPICTION"})
        named_as = next(item for item in wrong["assertions"]
                        if item["support"]["evidence_sets"][0]["evidence_handles"] != [])
        named_as["support"]["evidence_sets"].append(
            {"label": "CORROBORATING", "evidence_handles": ["EV9"]})
        self.assertIsNotNone(compile_ok(wrong, context))   # 真白's line cited for 遥


class CountingAndCopyTests(unittest.TestCase):
    def test_overlapping_count_diverges_from_non_overlapping_intuition(self):
        text = "あはははと笑った"
        self.assertEqual(len(_occurrences(text, "はは")), 2)
        self.assertEqual(text.count("はは"), 1)              # str.count is non-overlapping

    def test_unicode_normalization_difference_fails_closed(self):
        composed = "真白が笑った。"
        decomposed = unicodedata.normalize("NFD", composed)
        self.assertNotEqual(composed, decomposed)
        context, _, draft = build(decomposed, lambda b: b.named(1, "真白"))
        bad = deepcopy(draft)
        bad["evidence"].append({"handle": "EV9", "passage_handle": "P1", "quote": "が笑った",
                                "role": "DEPICTION"})
        self.assertEqual(blocker_codes(bad, context), {"QUOTE_NOT_FOUND"})

    def test_ruby_markup_must_be_copied_exactly_or_fails_closed(self):
        context, _, draft = build("｜真白《ましろ》は笑った。", lambda b: b.named(1, "真白"))
        bad = deepcopy(draft)
        bad["evidence"].append({"handle": "EV9", "passage_handle": "P1", "quote": "真白は笑った",
                                "role": "DEPICTION"})
        self.assertEqual(blocker_codes(bad, context), {"QUOTE_NOT_FOUND"})


class UngroundedValueTests(unittest.TestCase):
    def test_fabricated_name_literal_is_structurally_valid(self):
        def author(builder):
            entity = builder.named(1, "真白")
            builder.claim(builder.prop("NamedAs", entity=E(entity), name=S("真白"),
                                       name_kind=TOK("name_kind", "GIVEN")),
                          [[builder.ev(1, "真白")]], validity=OPEN)

        context, gold, draft = build("真白は笑った。", author)
        self.assertEqual(evaluate_case(context.base_document, gold, compile_ok(draft, context),
                                       ingestion=context.ingestion)["case_outcome"], "SUCCESS")
        fabricated = deepcopy(draft)
        for proposition in fabricated["propositions"]:
            if proposition.get("predicate") == "NamedAs":
                proposition["args"]["name"]["value"] = "真昼"
        batch = compile_ok(fabricated, context)
        result = evaluate_case(context.base_document, gold, batch, ingestion=context.ingestion)
        self.assertTrue(result["l0_structural_validity"])
        self.assertEqual(result["case_outcome"], "FAIL")

    def test_fabricated_surface_form_compiles_and_breaks_mention_alignment(self):
        context, gold, draft = build("真白は笑った。", named_once)
        self.assertEqual(evaluate_case(context.base_document, gold, compile_ok(draft, context),
                                       ingestion=context.ingestion)["case_outcome"], "SUCCESS")
        fabricated = deepcopy(draft)
        fabricated["mentions"][0]["surface_form"] = "真昼"
        result = evaluate_case(context.base_document, gold, compile_ok(fabricated, context),
                               ingestion=context.ingestion)
        self.assertTrue(result["l0_structural_validity"])
        self.assertEqual(result["case_outcome"], "FAIL")


def context_matches(text, quote, prefix, suffix):
    """Analysis aid only: starts whose exact surroundings equal prefix and suffix."""
    return [start for start in _occurrences(text, quote)
            if text[max(0, start - len(prefix)):start] == prefix
            and text[start + len(quote):start + len(quote) + len(suffix)] == suffix]


class ContextualAnchorLimitTests(unittest.TestCase):
    def test_context_disambiguates_distinct_surroundings(self):
        self.assertEqual(context_matches(TWO_NAMES, "真白", "。", "は窓"), [7])

    def test_identical_surroundings_stay_ambiguous_at_any_bounded_length(self):
        text = "「はい」" * 9
        middle = [start for start in _occurrences(text, "はい") if 12 <= start <= 20]
        for k in range(1, 9):
            prefix = text[middle[0] - k:middle[0]]
            suffix = text[middle[0] + 2:middle[0] + 2 + k]
            self.assertGreater(len(context_matches(text, "はい", prefix, suffix)), 1)

    def test_prefix_suffix_cannot_cross_a_passage_boundary(self):
        self.assertEqual(context_matches("真白は", "真白", "。", "は"), [])


if __name__ == "__main__":
    unittest.main()
