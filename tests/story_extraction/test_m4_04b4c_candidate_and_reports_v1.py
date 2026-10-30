"""M4-04B4C: prompt P4, manifest completeness, adversarial suite and recorded reports."""
from pathlib import Path
import re
import subprocess
import sys
import unittest

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import generate_m4_04b4c_reports_v1 as reports  # noqa: E402
import m4_v1_2_adversarial_harness as harness  # noqa: E402

from tools.story_extraction.m4_draft_v1_2_candidate_p4_v1 import (  # noqa: E402
    LIVE_PATH_FILES, RUNTIME_FILES, TOOLING_FILES, candidate_definition,
    candidate_definition_sha256, prompt_material,
)

PROMPTS = REPO / "tools/story_extraction/prompts"
P4 = ("story_extraction_draft_p4_system_v1_2.txt", "story_extraction_draft_p4_user_v1_2.txt",
      "story_extraction_draft_p4_repair_user_v1_2.txt")
MANIFEST = REPO / "benchmarks/m4_extraction/M4_04B4C_DRAFT_V1_2_CANDIDATE_MANIFEST.yaml"


class PromptTests(unittest.TestCase):
    def test_p4_targets_v1_2_only(self):
        for name in P4:
            text = (PROMPTS / name).read_text(encoding="utf-8")
            with self.subTest(name=name):
                self.assertIsNone(re.search(r"STORY_EXTRACTION_DRAFT_V1(?!_2)", text))
                for forbidden in ("evidence_handle", "DEV2", "holdout", '"occurrence"',
                                  "occurrence field", "surface_form"):
                    self.assertNotIn(forbidden, text)

    def test_top_level_count_and_core_rules_are_stated(self):
        text = (PROMPTS / P4[0]).read_text(encoding="utf-8")
        for required in ("nine required top-level", "eight arrays", "unresolved_locators",
                         "Do not count occurrences", "context_before", "context_after",
                         "1 to 32 characters", "Never guess a location", "REPEATED_IDENTICAL_CONTEXT",
                         "NO FABRICATION", "ruby marker"):
            self.assertIn(required, text)

    def test_materialized_schema_section_has_no_obsolete_interface(self):
        schema_part = prompt_material()["primary_system"].split("EXACT PREDICATE REGISTRY")[0]
        self.assertIsNone(re.search(r"evidence_handle(?!s)", schema_part))
        self.assertNotIn('"occurrence"', schema_part)
        self.assertNotIn('"surface_form"', schema_part)
        self.assertIsNone(re.search(r"STORY_EXTRACTION_DRAFT_V1(?!_2)", schema_part))


class ManifestTests(unittest.TestCase):
    def test_import_closure_of_runtime_and_live_path_is_bound(self):
        code = (
            "import sys, pathlib, json\n"
            "import tools.story_extraction.run_m4_draft_v1_2_predictions_v1\n"
            "import tools.story_extraction.run_m4_04b2_dev_predictions_v1\n"
            "import tools.story_extraction.draft_v1_2_oracle_projection_v1\n"
            "root = pathlib.Path('.').resolve()\n"
            "out = sorted({pathlib.Path(m.__file__).resolve().relative_to(root).as_posix()\n"
            "  for m in list(sys.modules.values()) if getattr(m, '__file__', None)\n"
            "  and str(pathlib.Path(m.__file__).resolve()).startswith(str(root))})\n"
            "print(json.dumps(out))\n")
        loaded = subprocess.run([sys.executable, "-c", code], cwd=REPO, check=True,
                                capture_output=True, text=True).stdout
        import json
        modules = {path for path in json.loads(loaded) if not path.endswith("__init__.py")}
        bound = {path for _, path in RUNTIME_FILES + LIVE_PATH_FILES + TOOLING_FILES}
        self.assertEqual(sorted(modules - bound), [])
        for required in ("tools/story_extraction/gemini_errors_v1.py",
                         "tools/story_extraction/m4_04b2_dev_protocol_v1.py"):
            self.assertIn(required, bound)

    def test_committed_manifest_matches_current_candidate(self):
        committed = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(committed["candidate_definition_sha256"], candidate_definition_sha256())
        self.assertEqual(committed["definition"], candidate_definition())
        self.assertIn("python", committed["environment_observed_at_lock"])


class AdversarialTests(unittest.TestCase):
    def test_every_case_meets_its_expectation(self):
        records = harness.run_all()
        failing = [item["id"] for item in records if not item["pass"]]
        self.assertEqual(failing, [])
        summary = harness.summary(records)
        self.assertEqual(summary["resolver_false_resolution"], 0)
        self.assertGreaterEqual(summary["cases"], 30)

    def test_identical_context_is_never_valid(self):
        records = {item["id"]: item for item in harness.run_all()}
        self.assertEqual(records["ADV-04"]["actual"], "INVALID")
        self.assertEqual(records["ADV-05"]["actual"], "EXPLICITLY_UNRESOLVED")

    def test_recorded_reports_are_reproducible(self):
        for path, build in ((reports.ADVERSARIAL, reports.adversarial_record),
                            (reports.METRICS, reports.metrics_record)):
            with self.subTest(path=path.name):
                self.assertEqual(path.read_text(encoding="utf-8").replace("\r\n", "\n"),
                                 reports.render(build()))


if __name__ == "__main__":
    unittest.main()
