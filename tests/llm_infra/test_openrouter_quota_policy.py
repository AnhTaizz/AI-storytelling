from datetime import datetime, timezone
from email.utils import formatdate
import unittest

from tools.llm_infra.openrouter_quota_policy import decide_openrouter_rate_limit
from tools.llm_infra.openrouter_transport import OpenRouterHTTPError
from tools.llm_infra.quota_policy import REASONS


class OpenRouterQuotaPolicyTests(unittest.TestCase):
    def test_openrouter_limits_reset_at_ms_epoch_or_use_the_utc_day(self):
        now = datetime(2026, 11, 23, 23, 59, 45, tzinfo=timezone.utc).timestamp()
        for limit, message, reset, retry, reason, delay, source in [
            (50, "", 30.25, None, "RPD", 30.25, "headers"),
            (1000, "", -5, None, "RPD", 15, "headers"),
            (None, "Requests per day exhausted", None, 24, "RPD", 24, "message"),
            (None, "PER-DAY quota", 0, None, "RPD", 15, "message"),
            (20, "daily quota", None, None, "RPD", 15, "message"),
            (None, "DAILY quota", None, None, "RPD", 15, "message"),
            (20, "", 8, None, "RPM", 8, "headers"),
            (20, "", 8, 14, "RPM", 14, "headers"),
            (20, "", -1, 4, "RPM", 4, "headers"),
            (None, "Requests per minute reached", None, None, "RPM", 60, "message"),
        ]:
            with self.subTest(limit=limit, message=message, reset=reset, retry=retry):
                headers = {"X-RateLimit-Limit": limit, "Retry-After": retry}
                if reset is not None:
                    headers["X-RateLimit-Reset"] = str(int((now + reset) * 1000))
                decision = decide_openrouter_rate_limit(429, headers, {"error": {"message": message}}, now, 0)
                self.assertIn(decision.reason, REASONS)
                self.assertEqual((decision.reason, decision.blocked_until), (reason, now + delay))
                self.assertEqual(decision.evidence, {"cause_source": source, "retry_after_present": retry is not None})
        midnight = now + 15
        decision = decide_openrouter_rate_limit(429, {"X-RateLimit-Limit": 50}, {}, midnight, 0)
        self.assertEqual(decision.blocked_until, midnight + 86400)

    def test_upstream_429_ignores_quota_evidence_and_unknown_limits_back_off(self):
        now = 1000
        for upstream in (True, False):
            for streak, retry, delay, present in [
                (-1, None, 60, False), (0, None, 60, False), (1, "invalid", 120, False),
                (2, -1, 240, False), (3, "0", 480, True), (4, None, 900, False), (1000, None, 900, False),
                (5, "8", 8, True), (0, formatdate(now + 90, usegmt=True), 90, True),
            ]:
                with self.subTest(upstream=upstream, streak=streak, retry=retry):
                    headers = {"Retry-After": retry}
                    error = {}
                    if upstream:
                        headers.update({"X-RateLimit-Limit": "50", "X-RateLimit-Reset": "86400000"})
                        error = {"message": "daily quota", "metadata": {"provider_code": 429}}
                    failure = OpenRouterHTTPError(kind="RATE_LIMIT", headers=headers, body={"error": error})
                    decision = decide_openrouter_rate_limit(failure, None, None, now, streak)
                    self.assertEqual((decision.reason, decision.blocked_until), ("UNKNOWN_429", now + delay))
                    self.assertEqual(decision.evidence, {
                        "cause_source": "upstream_provider" if upstream else "unknown", "retry_after_present": present,
                    })

    def test_retry_after_and_reset_delays_are_capped_at_26_hours(self):
        now = 1000
        for headers, reason in [
            ({"Retry-After": "99999999"}, "UNKNOWN_429"),
            ({"X-RateLimit-Limit": 50, "Retry-After": formatdate(now + 100000, usegmt=True)}, "RPD"),
            ({"X-RateLimit-Limit": 20, "X-RateLimit-Reset": "900000000"}, "RPM"),
        ]:
            with self.subTest(reason=reason):
                decision = decide_openrouter_rate_limit(429, headers, {}, now, 0)
                self.assertEqual((decision.reason, decision.blocked_until), (reason, now + 26 * 3600))
