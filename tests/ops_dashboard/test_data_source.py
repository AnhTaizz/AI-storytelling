from datetime import datetime, timezone
import json
import unittest

from tools.ops_dashboard.contract import FIELDS, TELEMETRY_COLUMNS, VALUE_SOURCES
from tools.ops_dashboard.data_source import MockDataSource


class DataSourceTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 24, 14, 15, tzinfo=timezone.utc)
        self.source = MockDataSource(seed=42, now=self.now)

    def test_same_seed_and_clock_reproduce_snapshot(self):
        self.assertEqual(vars(self.source), vars(MockDataSource(seed=42, now=self.now)))
        self.assertNotEqual(self.source.requests, MockDataSource(seed=12, now=self.now).requests)
        with self.assertRaises(ValueError):
            MockDataSource(now=self.now.replace(tzinfo=None))

    def test_rows_match_phase_five_shape_and_provenance(self):
        token_sources = set()
        for row in self.source.requests:
            self.assertCountEqual(row, TELEMETRY_COLUMNS)
            self.assertLessEqual(datetime.fromisoformat(row[FIELDS["timestamp"]]), self.now)
            provenance = row[FIELDS["tokenSource"]]
            token_sources.add(provenance)
            self.assertIn(provenance, VALUE_SOURCES)
            self.assertIn(row[FIELDS["costSource"]], ("reported", "unknown"))
            counts = [row[FIELDS[key]] for key in ("input", "output", "reasoning")]
            self.assertEqual(all(value is None for value in counts), provenance == "unknown")
            self.assertIsNone(row[FIELDS["estimatedCost"]])
            self.assertIsInstance(json.loads(row[FIELDS["quotaRemaining"]]), dict)
            self.assertIsInstance(json.loads(row[FIELDS["skipReasons"]]), list)
        self.assertEqual(token_sources, set(VALUE_SOURCES))
        self.assertEqual({row[FIELDS["provider"]] for row in self.source.requests},
                         {"gemini", "groq", "cloudflare", "openrouter"})

    def test_mock_includes_quota_and_review_scenarios(self):
        incidents = {row[FIELDS["error"]] for row in self.source.requests if row[FIELDS["error"]]}
        self.assertEqual(incidents, {"QUOTA_EXHAUSTED", "REQUEST_TOO_LARGE", "EDGE_BLOCKED"})
        self.assertEqual({run["status"] for run in self.source.runs},
                         {"COMPLETED", "PAUSED_QUOTA", "FAILED", "NEEDS_REVIEW"})
        providers = {provider["slug"]: provider for provider in self.source.providers}
        self.assertEqual(providers["gemini"]["scope"], "project")
        self.assertGreater(datetime.fromisoformat(providers["gemini"]["cooldown_until"]), self.now)
        for slug, expected in {"groq": [1000, 8000], "openrouter": [50], "cloudflare": [10000]}.items():
            with self.subTest(slug=slug):
                self.assertEqual([quota["limit"] for quota in providers[slug]["limits"]], expected)
