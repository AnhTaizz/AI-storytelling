"""Synthetic, offline tests for STORY_EXTRACTION_DRAFT_V1_1."""
from copy import deepcopy
from pathlib import Path
import hashlib
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
    migrate_draft_v1_to_v1_1,
    prepare_story_extraction_draft_v1_1,
    validate_draft_v1_1,
)
from tools.story_extraction.draft_coverage_v1 import canonical_gold_to_draft_v1
from tools.story_extraction.extraction_contract_guard_v1 import validate_batch_guarded


def fixture(name="c02_two_mentions_one_entity"):
    ingestion, base, gold = fx.build(name)
    scope = gold["scope"]
    context = DraftCompilerContext(
        base,
        scope["passage_inputs"],
        scope["as_of_position"],
        scope["profile_id"],
        "synthetic-v1-1",
        "v1.1",
        name,
        ingestion,
    )
    draft, _ = canonical_gold_to_draft_v1(gold, context)
    return context, draft


class DraftCompilerV11Tests(unittest.TestCase):
    def test_v1_history_is_byte_identical(self):
        expected = {
            "schemas/story_extraction/story_extraction_draft_v1.schema.json":
                "498edf8dba8d45b80380a180d1383787f5c0e4ecea5060254883cc27c7d83e80",
            "tools/story_extraction/draft_compiler_v1.py":
                "bcd15328cefafe86dd8e686fb35a155b2cb2c261b20017486ed106e85371d836",
        }
        for relative, digest in expected.items():
            with self.subTest(path=relative):
                self.assertEqual(
                    hashlib.sha256((REPO / relative).read_bytes()).hexdigest(), digest
                )

    def test_migration_is_mechanical_and_does_not_mutate_v1(self):
        context, draft = fixture()
        before = deepcopy(draft)
        migrated = migrate_draft_v1_to_v1_1(draft)
        self.assertEqual(draft, before)
        self.assertEqual(migrated["draft_version"], DRAFT_VERSION)
        self.assertTrue(all("evidence_handle" not in item for item in migrated["mentions"]))
        expected = deepcopy(before)
        expected["draft_version"] = DRAFT_VERSION
        for mention in expected["mentions"]:
            mention.pop("evidence_handle", None)
        self.assertEqual(migrated, expected)
        validate_draft_v1_1(migrated)
        self.assertEqual(prepare_story_extraction_draft_v1_1(context)["draft_version"], DRAFT_VERSION)

    def test_schema_rejects_model_facing_mention_evidence_handle(self):
        _, draft = fixture()
        migrated = migrate_draft_v1_to_v1_1(draft)
        migrated["mentions"][0]["evidence_handle"] = "EV1"
        with self.assertRaises(DraftCompilationErrorV1_1) as raised:
            validate_draft_v1_1(migrated)
        self.assertEqual(raised.exception.code, "DRAFT_SCHEMA_FAILURE")

    def test_all_authored_synthetic_graphs_compile_source_exact(self):
        for name in fx.CASES:
            with self.subTest(name=name):
                context, draft = fixture(name)
                migrated = migrate_draft_v1_to_v1_1(draft)
                batch = compile_story_extraction_draft_v1_1(migrated, context)
                self.assertTrue(
                    validate_batch_guarded(batch, context.base_document, context.ingestion)[
                        "pass"
                    ]
                )

    def test_broad_assertion_evidence_is_not_reused_for_mention(self):
        context, draft = fixture()
        migrated = migrate_draft_v1_to_v1_1(draft)
        prepared = prepare_story_extraction_draft_v1_1(context)
        mention = deepcopy(migrated["mentions"][0])
        passage_text = next(
            item["text"]
            for item in prepared["passages"]
            if item["handle"] == mention["passage_handle"]
        )
        migrated["evidence"] = [
            {
                "handle": "EV1",
                "passage_handle": mention["passage_handle"],
                "quote": passage_text,
                "role": mention["role"],
            }
        ]
        migrated["assertions"] = []
        duplicate = deepcopy(mention)
        duplicate["handle"] = "M99"
        migrated["mentions"].append(duplicate)

        bound, stats = bind_exact_mention_evidence_v1_1(migrated, context)
        by_handle = {item["handle"]: item for item in bound["mentions"]}
        self.assertNotEqual(by_handle[mention["handle"]]["evidence_handle"], "EV1")
        self.assertEqual(
            by_handle[mention["handle"]]["evidence_handle"],
            by_handle[duplicate["handle"]]["evidence_handle"],
        )
        self.assertGreaterEqual(stats["created_exact_mention_evidence"], 1)
        self.assertGreaterEqual(stats["reused_exact_prior_mention_evidence"], 1)

    def test_assertion_support_never_gains_implicit_mention_evidence(self):
        context, draft = fixture()
        migrated = migrate_draft_v1_to_v1_1(draft)
        support_before = [deepcopy(item["support"]) for item in migrated["assertions"]]
        bound, _ = bind_exact_mention_evidence_v1_1(migrated, context)
        self.assertEqual(
            [item["support"] for item in bound["assertions"]], support_before
        )

    def test_collects_all_feasible_same_class_quote_blockers(self):
        context, draft = fixture()
        migrated = migrate_draft_v1_to_v1_1(draft)
        migrated["mentions"][0]["quote"] = "__missing_quote_one__"
        migrated["mentions"][1]["quote"] = "__missing_quote_two__"
        blockers = collect_draft_structural_blockers_v1_1(migrated, context)
        quote_blockers = [item for item in blockers if item.phase == "QUOTE"]
        self.assertEqual(len(quote_blockers), 2)
        self.assertEqual({item.code for item in quote_blockers}, {"QUOTE_NOT_FOUND"})
        with self.assertRaises(DraftCompilationErrorV1_1) as raised:
            compile_story_extraction_draft_v1_1(migrated, context)
        self.assertEqual(len(raised.exception.blockers), 2)

    def test_collects_independent_handle_blockers(self):
        context, draft = fixture("c05_event_occurred")
        migrated = migrate_draft_v1_to_v1_1(draft)
        migrated["events"][0]["anchor_handle"] = "T99"
        migrated["assertions"][0]["proposition_handle"] = "PROP99"
        blockers = collect_draft_structural_blockers_v1_1(migrated, context)
        paths = {item.path for item in blockers if item.code == "UNKNOWN_HANDLE"}
        self.assertIn("events/EVT1/anchor_handle", paths)
        self.assertIn("assertions/A1/proposition_handle", paths)


if __name__ == "__main__":
    unittest.main()
