from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tools.model_bench.dataset import case_sha256, load_dataset
from tools.model_bench.review_sheet import generate


class ReviewSheetTests(unittest.TestCase):
    def test_standalone_html_includes_all_case_hashes_and_review_controls(self):
        dataset_hash, cases = load_dataset()
        with TemporaryDirectory() as temp:
            path = Path(temp) / "nested" / "review.html"
            generate(path)
            raw = path.read_bytes()
            html = raw.decode("utf-8")
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertNotIn(b"\r", raw)
        self.assertEqual(html.count("<article "), 78)
        self.assertIn(dataset_hash, html)
        for case in cases:
            with self.subTest(case=case["id"]):
                self.assertIn(f'<article id="{case["id"]}" data-sha256="{case_sha256(case)}"', html)
        for fragment in ("<mark>", "GOLD_REVIEW.json", 'value="approved"', 'value="needs_change"',
                         'value="rejected"', "URL.createObjectURL", "prefers-color-scheme: dark"):
            self.assertIn(fragment, html)
        self.assertNotRegex(html, r"https?://|(?:src|href)=[\"']?//")
