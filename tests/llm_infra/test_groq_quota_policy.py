import unittest

from tools.llm_infra.groq_quota_policy import decide_groq_rate_limit, parse_duration
from tools.llm_infra.groq_transport import GroqHTTPError


class GroqQuotaPolicyTests(unittest.TestCase):
    def test_duration_formats_and_garbage(self):
        for text, seconds in [
            ("2m59.56s", 179.56), ("7.66s", 7.66), ("1h2m3s", 3723),
            ("450ms", 0.45), ("1m450ms", 60.45), (" 17.5 ", 17.5),
            (8, 8), ("0", 0), (".5s", 0.5),
            (None, None), ("", None), ("-", None), ("-2s", None), ("3s?", None),
            ("1m2h", None), ("1.3.5s", None), ("5ms10s", None), ("4e2", None), ("9" * 400, None),
        ]:
            with self.subTest(text=text):
                parsed = parse_duration(text)
                if seconds is None:
                    self.assertIsNone(parsed)
                else:
                    self.assertAlmostEqual(parsed, seconds)

    def test_message_takes_precedence_then_headers(self):
        rpd = {"X-RateLimit-Remaining-Requests": "0"}
        tpm = {"X-RateLimit-Remaining-Tokens": 0}
        for message, headers, reason, source in [
            ("Rate limit on tokens per day (TPD)", rpd | tpm, "TPD", "message"),
            ("Rate limit on RPD", tpm, "RPD", "message"),
            ("Rate limit on tokens per minute", rpd, "TPM", "message"),
            ("Limit on requests per minute (RPM)", rpd | tpm, "RPM", "message"),
            ("No explanation", rpd | tpm, "RPD", "headers"),
            ("Rate limited", tpm, "TPM", "headers"),
            ("Not a marker: rpmx", {"x-ratelimit-limit-requests": "0"}, "UNKNOWN_429", "unknown"),
        ]:
            with self.subTest(message=message, headers=headers):
                error = GroqHTTPError(kind="RATE_LIMIT", status=429, headers=headers,
                                      body={"error": {"message": message}})
                decision = decide_groq_rate_limit(error, None, None, 1000, 0)
                self.assertEqual((decision.reason, decision.evidence["cause_source"]), (reason, source))

    def test_largest_matching_delay_and_fallbacks(self):
        requests = "x-ratelimit-reset-requests"
        tokens = "x-ratelimit-reset-tokens"
        for message, headers, streak, seconds in [
            ("RPD. Please try again in 7.66s.", {"Retry-After": "10", requests: "2m", tokens: "4h"}, 0, 120),
            ("TPM. Please try again in 2m59.56s.", {"Retry-After": "15", requests: "4h", tokens: "100s"}, 0, 179.56),
            ("RPM. Please try again in 450ms!", {"Retry-After": "1"}, 0, 1),
            ("Please try again in 450ms!", {}, 3, 0.45),
            ("TPD. Please try again in 7m12.5s.", {tokens: "4h", requests: "5h"}, 0, 432.5),
            ("TPD", {tokens: "450ms"}, 0, 3600),
            ("RPD", {requests: "bad"}, 0, 3600),
            ("RPM", {requests: "2m"}, 0, 60),
            ("TPM", {"Retry-After": "bad", tokens: "0s"}, 0, 60),
            ("RPD", {requests: "350h"}, 0, 93600),
            ("", {"Retry-After": "1000000000"}, 2, 93600),
            *(("", {}, streak, delay) for streak, delay in enumerate([60, 120, 240, 480, 900, 900])),
        ]:
            with self.subTest(message=message, headers=headers, streak=streak):
                body = {"error": {"message": message}}
                decision = decide_groq_rate_limit(429, headers, body, 1000, streak)
                self.assertAlmostEqual(decision.blocked_until, 1000 + seconds)
                self.assertEqual(decision.evidence["retry_after_present"], headers.get("Retry-After") not in (None, "bad"))
