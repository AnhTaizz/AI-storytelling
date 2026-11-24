import ast
from collections import Counter
import json
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory
import unittest

import yaml

from tools.model_bench.dataset import DATA, DIFFICULTIES, GROUPS, ROOT, case_sha256, gold_statuses, load_dataset


class DatasetTests(unittest.TestCase):
    def test_manifest_and_synthetic_evidence(self):
        dataset_hash, cases = load_dataset()
        self.assertRegex(dataset_hash, r"^[0-9a-f]{64}$")
        counts = Counter((case["group"], case["difficulty"]) for case in cases)
        forbidden = re.compile(r"holdout|benchmarks/|data/sample/|otonari|(?:chapter[_ -]?|chương (?:giả định )?)"
                               r"0*(?:[6-9]|1[0-7])\b", re.IGNORECASE)
        for case in cases:
            with self.subTest(case=case["id"]):
                self.assertEqual(case["source"], "synthetic")
                self.assertFalse(forbidden.search(str(case)))
                self.assertTrue(case["evidence_spans"])
                self.assertEqual(case["gold_status"], "draft_needs_owner_review")
                self.assertTrue(case["gold"] is not None or case["rubric"])
        for group in GROUPS:
            for difficulty in DIFFICULTIES:
                with self.subTest(group=group, difficulty=difficulty):
                    minimum = 1 if group in {"narrative_plan", "vietnamese_script"} else 3
                    self.assertGreaterEqual(counts[group, difficulty], minimum)

    def test_changed_file_rejected(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "dev"
            shutil.copytree(DATA, path)
            with (path / "event_extraction.jsonl").open("ab") as stream:
                stream.write(b"\n")
            with self.assertRaisesRegex(ValueError, "file hash mismatch"):
                load_dataset(path)

    def test_gold_review_requires_unchanged_case_and_dataset(self):
        dataset_hash, cases = load_dataset()
        case = cases[0]
        case_id = case["id"]
        draft = "draft_needs_owner_review"
        with TemporaryDirectory() as temp:
            path = Path(temp) / "GOLD_REVIEW.json"
            self.assertEqual(gold_statuses(dataset_hash, [case], path)[case_id], draft)
            for status in ("approved", "needs_change", "rejected"):
                with self.subTest(status=status):
                    review = {"dataset_sha256": dataset_hash, "cases": {case_id: {
                        "status": status, "reviewer": "Owner", "date": "2026-11-24", "case_sha256": case_sha256(case)}}}
                    path.write_text(json.dumps(review), encoding="utf-8")
                    self.assertEqual(gold_statuses(dataset_hash, [case], path)[case_id], status)
                    edited = case | {"expected_behaviour": "đã sửa"}
                    self.assertEqual(gold_statuses(dataset_hash, [edited], path)[case_id], draft)
                    self.assertEqual(gold_statuses("stale", [case], path)[case_id], draft)

    def test_taxonomy_covers_pipeline_stage_calls_and_cli(self):
        code = ROOT / "tools" / "story_pipeline"
        stages = set()
        for path in code.glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "run_json_stage":
                    stages.update(arg.value.value for arg in node.keywords if arg.arg == "stage")
                if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "STAGES" for t in node.targets):
                    stages.update(ast.literal_eval(node.value))
        taxonomy = yaml.safe_load((ROOT / "tools/model_bench/task_taxonomy_v1.yaml").read_text(encoding="utf-8"))
        self.assertEqual(stages, set(taxonomy["pipeline_stages"]))
        self.assertEqual({row["tier"] for row in taxonomy["pipeline_stages"].values()}, {"quality_critical"})
        utilities = taxonomy["utility_tasks"]
        for task in ("json_shape", "spoiler_cutoff_by_chapter_index", "length"):
            with self.subTest(task=task):
                self.assertTrue(utilities[task]["deterministic_candidate"])
