from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest

from tools.ops_dashboard.contract import FIELDS
from tools.ops_dashboard.view_models import overview, request_history, summarize, usage


NOW = datetime(2026, 11, 24, 14, 15, tzinfo=timezone.utc)


def row(*, hours_ago=1, provider="gemini", stage="script", outcome="SUCCESS", token_source="reported",
        input_tokens=10, output_tokens=5, latency=100, error=None):
    return {FIELDS[key]: value for key, value in {
        "timestamp": (NOW - timedelta(hours=hours_ago)).isoformat(),
        "provider": provider, "stage": stage, "outcome": outcome, "tokenSource": token_source,
        "input": input_tokens, "output": output_tokens, "latency": latency, "error": error,
    }.items()}


class ViewModelTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            row(hours_ago=3),
            row(provider="groq", stage="utility", token_source="estimated", input_tokens=7,
                output_tokens=20, latency=None, outcome="SKIPPED", error="REQUEST_TOO_LARGE"),
            row(hours_ago=2, token_source="unknown", input_tokens=None, output_tokens=None,
                latency=250, outcome="FAILED", error="QUOTA_EXHAUSTED"),
            row(hours_ago=0, token_source="unknown", input_tokens=None, output_tokens=None,
                latency=900, outcome="FAILED", error="QUOTA_EXHAUSTED"),
        ]
        self.source = SimpleNamespace(now=NOW, requests=self.rows, estimated_cost_usd=0.0, providers=[
            {"slug": "gemini", "name": "Gemini", "status": "Cooldown",
             "cooldown_until": (NOW + timedelta(minutes=10)).isoformat()},
            {"slug": "groq", "name": "Groq", "status": "Healthy", "cooldown_until": None},
        ])

    def test_aggregation_preserves_provenance_and_outcomes(self):
        result = summarize(self.rows)
        self.assertEqual(result["requests"], 4)
        self.assertEqual(result["success_rate"], 1 / 3)
        self.assertEqual(result["tokens_by_source"], {"reported": 15, "estimated": 27, "unknown": None})
        self.assertEqual(result["latency"], {"p50": 250, "p95": 900})
        self.assertEqual(result["error_counts"], {"QUOTA_EXHAUSTED": 2, "REQUEST_TOO_LARGE": 1})
        self.assertEqual(result["stage_provider_mix"], {"script": {"gemini": 3}, "utility": {"groq": 1}})
        self.assertIsNone(summarize([])["success_rate"])
        self.assertIsNone(summarize([])["latency"]["p95"])

    def test_overview_uses_utc_day_and_latest_incidents(self):
        self.rows.append(row(hours_ago=15))
        result = overview(self.source)
        self.assertEqual(result["today"]["requests"], 4)
        self.assertEqual(result["active_cooldowns"], 1)
        self.assertEqual(result["estimated_cost_usd"], 0)
        self.assertEqual(result["incidents"][0], self.rows[3])

    def test_usage_range_bucket_boundaries_and_unknown_tokens(self):
        self.rows.extend([row(hours_ago=24), row(hours_ago=25), row(hours_ago=169), row(hours_ago=-1)])
        daily = usage(self.source, "24h")["buckets"]
        weekly = usage(self.source, "7d")["buckets"]
        self.assertEqual(len(daily), 24)
        self.assertEqual(len(weekly), 7)
        self.assertEqual(daily[0]["providers"]["gemini"]["requests"]["reported"], 1)
        self.assertEqual(daily[-1]["providers"]["gemini"]["requests"]["unknown"], 1)
        self.assertIsNone(daily[-1]["providers"]["gemini"]["tokens"]["unknown"])
        self.assertEqual(weekly[-2]["providers"]["gemini"]["tokens"]["reported"], 15)

    def test_request_limit_applies_after_filter_and_sort(self):
        result = request_history(self.source, 1, provider="gemini", stage="script", outcome="FAILED")
        self.assertEqual(result["matching"], 2)
        self.assertEqual(result["requests"], [self.rows[3]])
        self.assertEqual(result["options"]["stage"], ["script", "utility"])
