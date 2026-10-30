"""Offline tests for the V1.2 schema, contextual resolver, compiler and oracle projection."""
from copy import deepcopy
import json
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixture_builder as fx  # noqa: E402
from m4_v1_2_adversarial_harness import TWO, context_for, refers  # noqa: E402

from tools.story_extraction import draft_compiler_v1, draft_compiler_v1_1, draft_compiler_v1_2  # noqa: E402
from tools.story_extraction.contextual_anchor_resolver_v1 import (  # noqa: E402
    AMBIGUOUS, INVALID, NOT_FOUND, RESOLVED, candidate_starts, minimal_unique_context,
    occurrence_of, resolve_anchor,
)
from tools.story_extraction.draft_compiler_v1 import DraftCompilerContext  # noqa: E402
from tools.story_extraction.draft_compiler_v1_1 import (  # noqa: E402
    compile_story_extraction_draft_v1_1, migrate_draft_v1_to_v1_1,
)
from tools.story_extraction.draft_compiler_v1_2 import (  # noqa: E402
    DraftCompilationErrorV1_2, compile_story_extraction_draft_v1_2,
)
from tools.story_extraction.draft_coverage_v1 import (  # noqa: E402
    canonical_gold_to_draft_v1, canonical_representation_signature,
)
from tools.story_extraction.draft_v1_2_oracle_projection_v1 import project_gold_to_draft_v1_2  # noqa: E402

SCHEMA_V1 = REPO / "schemas/story_extraction/story_extraction_draft_v1.schema.json"
SCHEMA_V1_2 = REPO / "schemas/story_extraction/story_extraction_draft_v1_2.schema.json"


def fixture_context(name):
    ingestion, base, gold = fx.build(name)
    scope = gold["scope"]
    return DraftCompilerContext(base, scope["passage_inputs"], scope["as_of_position"],
                                scope["profile_id"], "v12-test", "v1", name, ingestion), gold


class ResolverTests(unittest.TestCase):
    def test_unique_ambiguous_missing_and_invalid(self):
        self.assertEqual(resolve_anchor(TWO, "窓").status, RESOLVED)
        self.assertEqual(resolve_anchor(TWO, "真白").status, AMBIGUOUS)
        self.assertEqual(resolve_anchor(TWO, "真昼").detail, "QUOTE_ABSENT")
        self.assertEqual(resolve_anchor(TWO, "真白", "x").detail, "CONTEXT_MISMATCH")
        self.assertEqual(resolve_anchor(TWO, "").status, INVALID)
        self.assertEqual(resolve_anchor(TWO, "真白", "。" * 33).status, INVALID)
        self.assertEqual(resolve_anchor(TWO, "真白", "\ud800").status, INVALID)

    def test_context_selects_without_order_bias(self):
        first = resolve_anchor(TWO, "真白", None, "は笑")
        second = resolve_anchor(TWO, "真白", "。", "は窓")
        self.assertEqual((first.start, second.start), (0, 7))
        self.assertEqual(occurrence_of(TWO, "真白", second.start), 2)

    def test_overlapping_candidates(self):
        self.assertEqual(candidate_starts("あははは", "はは"), [1, 2])
        self.assertEqual(resolve_anchor("あははは", "はは", "あ").start, 1)
        self.assertEqual(resolve_anchor("あははは", "はは", None, "は").start, 1)
        self.assertEqual(resolve_anchor("あははは", "はは", "は").start, 2)

    def test_context_never_crosses_passage_boundaries(self):
        self.assertEqual(resolve_anchor("真白は", "真白", "。").status, NOT_FOUND)
        self.assertEqual(resolve_anchor("は真白", "真白", None, "は").status, NOT_FOUND)

    def test_hints_never_resolve(self):
        import unicodedata
        nfd = unicodedata.normalize("NFD", "真白が笑った")
        result = resolve_anchor(nfd, "が笑")
        self.assertEqual((result.status, result.hints), (NOT_FOUND, ("NORMALIZATION_VARIANT_PRESENT",)))
        self.assertEqual(resolve_anchor("１２時", "12時").hints, ("COMPATIBILITY_VARIANT_PRESENT",))

    def test_periodic_text_is_unrepresentable_even_at_passage_edges(self):
        """Known limitation L1: a context cannot say "at the passage start/end"."""
        text = "「はい」" * 25
        starts = candidate_starts(text, "はい")
        for start in (starts[0], starts[12], starts[-1]):
            self.assertIsNone(minimal_unique_context(text, start, start + 2))
        varied = "真白「はい」" + "「はい」" * 3
        first = candidate_starts(varied, "はい")[0]
        self.assertEqual(minimal_unique_context(varied, first, first + 2), ("白「", None))


class SchemaTests(unittest.TestCase):
    def test_shared_definitions_equal_v1_exactly(self):
        v1 = json.loads(SCHEMA_V1.read_text(encoding="utf-8"))["$defs"]
        v12 = json.loads(SCHEMA_V1_2.read_text(encoding="utf-8"))["$defs"]
        for name in ("Handle", "EvidenceRole", "EntityKind", "EditorialLabel", "Argument",
                     "EvidenceSet", "Derivation", "Support", "Bound", "ValidityInterval",
                     "Entity", "Event", "TemporalAnchor", "Proposition", "Assertion"):
            with self.subTest(name=name):
                self.assertEqual(v12[name], v1[name])

    def test_k1_no_counting_offset_or_surface_field_exists(self):
        text = SCHEMA_V1_2.read_text(encoding="utf-8")
        for forbidden in ('"occurrence"', '"surface_form"', '"evidence_handle"', "char_start",
                          "byte_start"):
            self.assertNotIn(forbidden, text)
        schema = json.loads(text)
        self.assertEqual(len([key for key in schema["required"] if key != "draft_version"]), 8)
        self.assertEqual(schema["$defs"]["Context"]["maxLength"], 32)
        self.assertNotIn("$ref\": \"urn", text)


class CompilerTests(unittest.TestCase):
    def test_all_synthetic_fixtures_compile_identically_to_v1_1(self):
        for name in fx.CASES:
            with self.subTest(name=name):
                context, gold = fixture_context(name)
                draft, mapping, report = project_gold_to_draft_v1_2(gold, context)
                self.assertEqual(report["unrepresentable"], [])
                batch, _ = compile_story_extraction_draft_v1_2(draft, context)
                v1, _ = canonical_gold_to_draft_v1(gold, context)
                expected = compile_story_extraction_draft_v1_1(migrate_draft_v1_to_v1_1(v1), context)
                self.assertEqual(batch, expected)
                reverse = {record["id"]: next(h for h in mapping.values()
                                              if record["id"].endswith("-" + h))
                           for coll in draft_compiler_v1.COLLECTIONS.values()
                           for record in batch["candidate_records"][coll]}
                self.assertEqual(canonical_representation_signature(gold, mapping),
                                 canonical_representation_signature(batch, reverse))

    def test_deterministic_under_record_reordering(self):
        context = context_for(TWO)
        from m4_v1_2_adversarial_harness import add_refers
        draft = add_refers(refers("P1", "真白", None, "は笑"), "P1", "窓", n=2)
        expected, _ = compile_story_extraction_draft_v1_2(deepcopy(draft), context)
        rng = random.Random(7)
        for _ in range(5):
            shuffled = deepcopy(draft)
            for value in shuffled.values():
                if isinstance(value, list):
                    rng.shuffle(value)
            self.assertEqual(compile_story_extraction_draft_v1_2(shuffled, context)[0], expected)

    def test_surface_form_and_utf8_bytes_come_from_source(self):
        text = "🌸真白は笑った。🌸真白は窓を開けた。"
        context = context_for(text)
        batch, _ = compile_story_extraction_draft_v1_2(refers("P1", "真白", "🌸", "は窓"), context)
        records = batch["candidate_records"]
        mention = records["mentions"][0]
        ref = next(item for item in records["evidence_refs"] if item["id"] == mention["evidence_ref_id"])
        self.assertEqual(mention["surface_form"], "真白")
        doc = context.ingestion.documents[0]
        span = ref["span"]
        self.assertEqual(doc.source_bytes[span["byte_start"]:span["byte_end_exclusive"]],
                         "真白".encode("utf-8"))
        self.assertEqual(span["char_start"], text.index("🌸真白は窓") + 1)

    def test_partial_extraction_is_never_produced(self):
        context = context_for(TWO)
        draft = refers("P1", "真白", "。", "は窓")
        draft["evidence"].append({"handle": "EV9", "passage_handle": "P1", "quote": "真白",
                                  "role": "DEPICTION"})
        with self.assertRaises(DraftCompilationErrorV1_2) as raised:
            compile_story_extraction_draft_v1_2(draft, context)
        self.assertEqual({item.code for item in raised.exception.blockers}, {"LOCATOR_AMBIGUOUS"})
        self.assertEqual(raised.exception.report["counts"]["resolved"], 2)

    def test_post_invariant_catches_a_backend_span_change(self):
        context = context_for(TWO)
        draft = refers("P1", "真白", "。", "は窓")
        original = draft_compiler_v1_2.to_internal_v1_1_draft

        def corrupt(value, resolved):
            internal = original(value, resolved)
            for record in internal["mentions"]:
                record["occurrence"] = 1
            return internal

        with mock.patch.object(draft_compiler_v1_2, "to_internal_v1_1_draft", corrupt):
            with self.assertRaises(DraftCompilationErrorV1_2) as raised:
                compile_story_extraction_draft_v1_2(draft, context)
        self.assertIn("GROUNDING_INVARIANT_VIOLATION", {b.code for b in raised.exception.blockers})

    def test_line_endings_of_schema_files_do_not_change_compilation(self):
        context = context_for(TWO)
        draft = refers("P1", "真白", "。", "は窓")
        expected, _ = compile_story_extraction_draft_v1_2(deepcopy(draft), context)
        with tempfile.TemporaryDirectory() as tmp:
            copies = {}
            for path in (SCHEMA_V1, SCHEMA_V1_2,
                         REPO / "schemas/story_extraction/story_extraction_draft_v1_1.schema.json"):
                target = Path(tmp) / path.name
                target.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
                copies[path.name] = target
            with mock.patch.object(draft_compiler_v1, "SCHEMA_PATH", copies[SCHEMA_V1.name]), \
                    mock.patch.object(draft_compiler_v1_1, "SCHEMA_PATH",
                                      copies["story_extraction_draft_v1_1.schema.json"]), \
                    mock.patch.object(draft_compiler_v1_1, "V1_SCHEMA_PATH", copies[SCHEMA_V1.name]), \
                    mock.patch.object(draft_compiler_v1_2, "SCHEMA_PATH", copies[SCHEMA_V1_2.name]):
                actual, _ = compile_story_extraction_draft_v1_2(deepcopy(draft), context)
        self.assertEqual(actual, expected)


class ProjectionTests(unittest.TestCase):
    def test_unrepresentable_spans_are_declared_counted_and_pruned(self):
        text = "「はい」" * 25
        ingestion, base = fx.ingest_text(text)
        builder = fx.Builder(ingestion, base)
        builder.named(1, "「はい」「はい」「はい」「はい」「はい」「はい」「はい」「はい」「はい」「はい」"
                         "「はい」「はい」「はい」「はい」", kind="OTHER")
        gold = builder.batch()
        scope = gold["scope"]
        context = DraftCompilerContext(base, scope["passage_inputs"], scope["as_of_position"],
                                       scope["profile_id"], "p", "v1", "r", ingestion)
        draft, _, report = project_gold_to_draft_v1_2(gold, context)
        self.assertEqual(report["representable"], 0)
        self.assertEqual(report["representability_coverage"], 0.0)
        self.assertEqual(len(draft["unresolved_locators"]), report["locators_total"])
        self.assertTrue(report["pruned_dependants"])
        batch, compiled = compile_story_extraction_draft_v1_2(draft, context)
        self.assertEqual(compiled["counts"]["declared_unresolved"], report["locators_total"])
        self.assertEqual(compiled["counts"]["declared_unresolved_unjustified"], 0)


if __name__ == "__main__":
    unittest.main()
