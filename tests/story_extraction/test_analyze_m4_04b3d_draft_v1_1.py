"""Synthetic offline tests for the B3D V1-to-V1.1 migration diagnostic."""
import inspect
import json
from pathlib import Path
import sys
import unittest


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixture_builder as fx

from tools.story_extraction.analyze_m4_04b3d_draft_v1_1 import (
    MigrationDiagnosticError,
    _attempt,
    _guard_path,
    analyze,
)
from tools.story_extraction.draft_compiler_v1 import DraftCompilerContext
from tools.story_extraction.draft_coverage_v1 import canonical_gold_to_draft_v1


def fixture():
    ingestion, base, gold = fx.build("c02_two_mentions_one_entity")
    scope = gold["scope"]
    context = DraftCompilerContext(
        base,
        scope["passage_inputs"],
        scope["as_of_position"],
        scope["profile_id"],
        "synthetic",
        "v1",
        "synthetic",
        ingestion,
    )
    draft, _ = canonical_gold_to_draft_v1(gold, context)
    return context, draft


class M404B3DDiagnosticTests(unittest.TestCase):
    def test_analyzer_has_only_prediction_artifact_and_input_parameters(self):
        self.assertEqual(
            list(inspect.signature(analyze).parameters),
            ["artifact_root", "input_archive", "input_root"],
        )

    def test_gold_and_holdout_paths_fail_before_access(self):
        for path in (Path("private") / "dev2_gold", Path("sealed_holdout")):
            with self.subTest(path=path):
                with self.assertRaises(MigrationDiagnosticError):
                    _guard_path(path)

    def test_attempt_is_mechanical_public_safe_and_compiles(self):
        context, draft = fixture()
        private_quote = draft["mentions"][0]["quote"]
        removed = sum("evidence_handle" in item for item in draft["mentions"])
        result = _attempt(
            "SYNTHETIC_01",
            "primary",
            draft,
            context,
            {
                "pass": False,
                "category": "DRAFT_COMPILER_FAILURE",
                "code": "MENTION_EVIDENCE_MISMATCH",
            },
        )
        self.assertTrue(result["v1_1_validation"]["pass"])
        self.assertEqual(
            result["migration"]["removed_mention_evidence_handle_count"], removed
        )
        self.assertEqual(result["migration"]["other_field_changes"], 0)
        self.assertNotIn(private_quote, json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
