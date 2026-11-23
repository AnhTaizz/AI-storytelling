from email.utils import formatdate
import unittest

from tools.llm_infra.cloudflare_quota_policy import decide_cloudflare_limit


class CloudflareQuotaPolicyTests(unittest.TestCase):
    def test_daily_uses_next_midnight_independently_of_headers(self):
        for now, reset in [(86399, 86400), (86400, 172800)]:
            with self.subTest(now=now):
                decision = decide_cloudflare_limit("DAILY_ALLOCATION_EXHAUSTED", {"Retry-After": "999999"},
                                                   {}, now, 0)
                self.assertEqual((decision.reason, decision.blocked_until), ("RPD", reset))

    def test_minute_limit_accepts_seconds_or_http_date_and_caps_wait(self):
        for header, seconds in [(None, 60), ("invalid", 60), ("0", 60), ("22", 22),
                                (formatdate(1027, usegmt=True), 27), ("999999", 26 * 3600)]:
            with self.subTest(header=header):
                decision = decide_cloudflare_limit("RATE_LIMIT", {"Retry-After": header}, None, 1000, 0)
                self.assertEqual((decision.reason, decision.blocked_until), ("RPM", 1000 + seconds))

    def test_unknown_uses_phase_one_streak(self):
        for streak, seconds in [(-1, 60), (1, 120), (2, 240), (3, 480), (4, 900), (1000, 900)]:
            with self.subTest(streak=streak):
                decision = decide_cloudflare_limit("unknown", None, None, 1000, streak)
                self.assertEqual((decision.reason, decision.blocked_until), ("UNKNOWN_429", 1000 + seconds))
