"""Synthetic offline tests for the deterministic Draft V1.1 compiler."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sys
import unittest


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixture_builder as fx

from tools.story_extraction.draft_compiler_v1 import DraftCompilerContext
from tools.story_extraction.draft_compiler_v1_1 import (
    DRAFT_VERSION,
    DraftCompilationErrorV1_1,
    bind_exact_mention_evidence_v1_1,
    collect_draft_structural_blockers_v1_1,
    compile_story_extraction_draft_v1_1,
)
from tools.story_extraction.draft_coverage_v1 import canonical_gold_to_draft_v1
from tools.story_extraction.extraction_contract_guard_v1 import validate_batch_guarded


def context(ingestion, base, gold, run_id="synthetic"):
    scope = gold["scope"]
    return DraftCompilerContext(
        base,
        scope["passage_inputs"],
        scope["as_of_position"],
        scope["profile_id"],
        "draft-v1-1-test",
        "v1.1",
        run_id,
        ingestion,
    )


def migrate(draft):
    value = deepcopy(draft)
    value["draft_version"] = DRAFT_VERSION
    for mention in value["mentions"]:
        mention.pop("evidence_handle", None)
    return value


def fixture(name="c02_two_mentions_one_entity"):
    ingestion, base, gold = fx.build(name)
    ctx = context(ingestion, base, gold, name)
    draft, _ = canonical_gold_to_draft_v1(gold, ctx)
    return ctx, migrate(draft)


class DraftCompilerV11Tests(unittest.TestCase):
    def test_all_26_synthetic_graphs_compile_source_exact(self):
        for name in fx.CASES:
            with self.subTest(name=name):
                ctx, draft = fixture(name)
                batch = compile_story_extraction_draft_v1_1(draft, ctx)
                self.assertTrue(
                    validate_batch_guarded(batch, ctx.base_document, ctx.ingestion)["pass"]
                )

    def test_exact_model_evidence_is_reused(self):
        ctx, draft = fixture("c01_named_character")
        bound, stats = bind_exact_mention_evidence_v1_1(draft, ctx)
        self.assertEqual(stats["reused_exact_model_evidence"], 1)
        self.assertEqual(stats["created_exact_mention_evidence"], 0)
        self.assertIn(bound["mentions"][0]["evidence_handle"], {
            item["handle"] for item in draft["evidence"]
        })

    def test_narrow_mention_never_aliases_broad_assertion_evidence(self):
        ctx, draft = fixture()
        mention = deepcopy(draft["mentions"][0])
        passage = next(
            item for item in ctx.passage_inputs
            if item["passage_ref"]["segment_id"]
            == ctx.passage_inputs[0]["passage_ref"]["segment_id"]
        )
        text = ctx.ingestion.resolve_passage_text(passage["passage_ref"])
        draft["evidence"] = [{
            "handle": "EV1",
            "passage_handle": mention["passage_handle"],
            "quote": text,
            "role": mention["role"],
        }]
        draft["assertions"] = []
        bound, stats = bind_exact_mention_evidence_v1_1(draft, ctx)
        linked = next(item for item in bound["mentions"] if item["handle"] == mention["handle"])
        self.assertNotEqual(linked["evidence_handle"], "EV1")
        self.assertGreaterEqual(stats["created_exact_mention_evidence"], 1)

    def test_repeated_quote_reports_all_ambiguous_mentions(self):
        ingestion, base = fx.ingest_text("Mira saw Mira.")
        builder = fx.Builder(ingestion, base)
        gold = builder.batch()
        ctx = context(ingestion, base, gold)
        draft = {
            "draft_version": DRAFT_VERSION,
            "evidence": [],
            "mentions": [
                {"handle": "M1", "passage_handle": "P1", "quote": "Mira", "role": "DEPICTION"},
                {"handle": "M2", "passage_handle": "P1", "quote": "Mira", "role": "DEPICTION"},
            ],
            "entities": [], "events": [], "anchors": [],
            "propositions": [], "assertions": [],
        }
        blockers = collect_draft_structural_blockers_v1_1(draft, ctx)
        self.assertEqual(
            [item.code for item in blockers],
            ["AMBIGUOUS_QUOTE", "AMBIGUOUS_QUOTE"],
        )

    def test_multiple_registry_and_handle_blockers_are_collected(self):
        ctx, draft = fixture("c05_event_occurred")
        draft["events"][0]["event_kind"] = "NOT_REGISTERED"
        draft["events"][0]["anchor_handle"] = "T99"
        draft["propositions"][0]["predicate"] = "InventedPredicate"
        draft["assertions"][0]["support"]["derivations"] = [
            {"rule_id": "INVENTED_RULE", "premise_handles": ["A99"]}
        ]
        codes = {item.code for item in collect_draft_structural_blockers_v1_1(draft, ctx)}
        self.assertEqual(
            codes,
            {"UNREGISTERED_EVENT_KIND", "UNKNOWN_HANDLE", "UNREGISTERED_PREDICATE", "UNREGISTERED_RULE"},
        )
        with self.assertRaises(DraftCompilationErrorV1_1) as raised:
            compile_story_extraction_draft_v1_1(draft, ctx)
        self.assertGreaterEqual(len(raised.exception.blockers), 5)

    def test_context_only_and_unicode_are_fail_closed_and_source_exact(self):
        ctx, draft = fixture("c01_named_character")
        inputs = deepcopy(ctx.passage_inputs)
        inputs[0]["use"] = "CONTEXT_ONLY"
        codes = {item.code for item in collect_draft_structural_blockers_v1_1(
            draft, replace(ctx, passage_inputs=inputs)
        )}
        self.assertIn("CONTEXT_ONLY_EVIDENCE", codes)

        text = "\U0001f600 \u30df\u30e9\u306f\u9580\u3092\u958b\u3051\u305f\u3002"
        ingestion, base = fx.ingest_text(text)
        builder = fx.Builder(ingestion, base)
        builder.named(1, "\u30df\u30e9")
        gold = builder.batch()
        unicode_ctx = context(ingestion, base, gold, "unicode")
        unicode_draft, _ = canonical_gold_to_draft_v1(gold, unicode_ctx)
        batch = compile_story_extraction_draft_v1_1(migrate(unicode_draft), unicode_ctx)
        self.assertEqual(batch["candidate_records"]["evidence_refs"][0]["span"]["char_start"], 2)

    def test_holder_relative_content_and_polarity_are_not_inferred(self):
        ctx, draft = fixture("c16_belief")
        expected_assertions = len(draft["assertions"])
        batch = compile_story_extraction_draft_v1_1(draft, ctx)
        self.assertEqual(len(batch["candidate_records"]["assertions"]), expected_assertions)

        ctx, draft = fixture("c25_negated_event")
        occurred = next(item for item in draft["propositions"] if item.get("predicate") == "Occurred")
        assertion = next(item for item in draft["assertions"] if item["proposition_handle"] == occurred["handle"])
        assertion["polarity"] = "AFFIRMED"
        batch = compile_story_extraction_draft_v1_1(draft, ctx)
        compiled = next(item for item in batch["candidate_records"]["assertions"] if item["id"].endswith("-" + assertion["handle"]))
        self.assertEqual(compiled["polarity"], "AFFIRMED")

    def test_deterministic_ids_and_no_input_mutation(self):
        ctx, draft = fixture()
        before = deepcopy(draft)
        first = compile_story_extraction_draft_v1_1(draft, ctx)
        second = compile_story_extraction_draft_v1_1(draft, ctx)
        self.assertEqual(first, second)
        self.assertEqual(draft, before)


if __name__ == "__main__":
    unittest.main()
