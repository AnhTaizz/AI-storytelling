"""Offline tests for the B3D3 locked terminal-draft migration diagnostic."""
from copy import deepcopy
import inspect
from pathlib import Path
import sys
import unittest


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixture_builder as fx

from tools.story_extraction.analyze_m4_04b3d3_dev2_migration_v1 import (
    MigrationDiagnosticError,
    _guard_path,
    analyze,
    migrate_terminal_draft_v1_to_v1_1,
)
from tools.story_extraction.draft_coverage_v1 import canonical_gold_to_draft_v1
from tools.story_extraction.draft_compiler_v1 import DraftCompilerContext
from tools.story_extraction.draft_compiler_v1_1 import compile_story_extraction_draft_v1_1


class M404B3D3DiagnosticTests(unittest.TestCase):
    def _fixture(self):
        ingestion, base, gold = fx.build("c02_two_mentions_one_entity")
        scope = gold["scope"]
        context = DraftCompilerContext(
            base, scope["passage_inputs"], scope["as_of_position"], scope["profile_id"],
            "synthetic", "v1", "synthetic", ingestion,
        )
        draft, _ = canonical_gold_to_draft_v1(gold, context)
        return context, draft

    def test_analyzer_exposes_no_gold_or_evaluator_parameter(self):
        self.assertEqual(
            list(inspect.signature(analyze).parameters),
            ["artifact_root", "input_archive", "input_root"],
        )

    def test_gold_and_holdout_paths_fail_closed(self):
        for path in (Path("private") / "dev2_gold", Path("sealed_holdout")):
            with self.subTest(path=path):
                with self.assertRaises(MigrationDiagnosticError):
                    _guard_path(path)

    def test_migration_is_exact_nonmutating_and_compilable(self):
        context, draft = self._fixture()
        before = deepcopy(draft)
        removed = sum("evidence_handle" in mention for mention in draft["mentions"])
        migrated, count = migrate_terminal_draft_v1_to_v1_1(draft)
        self.assertEqual(draft, before)
        self.assertEqual(count, removed)
        self.assertEqual(migrated["draft_version"], "STORY_EXTRACTION_DRAFT_V1_1")
        self.assertTrue(all("evidence_handle" not in mention for mention in migrated["mentions"]))
        expected = deepcopy(before)
        expected["draft_version"] = "STORY_EXTRACTION_DRAFT_V1_1"
        for mention in expected["mentions"]:
            mention.pop("evidence_handle", None)
        self.assertEqual(migrated, expected)
        compile_story_extraction_draft_v1_1(migrated, context)

    def test_non_v1_input_is_rejected(self):
        _, draft = self._fixture()
        draft["draft_version"] = "STORY_EXTRACTION_DRAFT_V1_1"
        with self.assertRaises(MigrationDiagnosticError):
            migrate_terminal_draft_v1_to_v1_1(draft)


if __name__ == "__main__":
    unittest.main()
