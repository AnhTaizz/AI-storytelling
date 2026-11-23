import unittest

from fixtures import Error
from tools.llm_infra.quota_policy import decide_rate_limit


class DecisionTests(unittest.TestCase):
    def test_quota_windows_and_evidence(self):
        for quota, delay, header, streak, reason, seconds in [
            ("GenerateRequestsPerDayPerProjectPerModel-FreeTier", None, None, 0, "RPD", 28800-1000),
            ("RequestsPerDay", "90000s", None, 0, "RPD", 90000),
            ("InputTokensPerMinute", "1.5s", None, 0, "TPM", 1.5),
            ("GenerateRequestsPerMinute", None, None, 0, "RPM", 60),
            ("REQUESTS_PER_MINUTE", "0s", None, 0, "RPM", 60),
            ("", "0s", None, 0, "UNKNOWN_429", 60),
            ("", None, "33", 0, "UNKNOWN_429", 33), ("", "999999s", None, 0, "UNKNOWN_429", 93600),
            *(("", None, None, n, "UNKNOWN_429", sec) for n, sec in enumerate([60,120,240,480,900,900]))]:
            with self.subTest(quota=quota, delay=delay, streak=streak):
                d = decide_rate_limit(Error(quota=quota, delay=delay, header=header), 1000, streak)
                self.assertEqual((d.reason, d.blocked_until), (reason, 1000+seconds))
                self.assertEqual(d.evidence["retry_after_present"], bool(delay or header))

    def test_body_sources_and_legacy_markers(self):
        for source in ("response_json", "response", "legacy"):
            with self.subTest(source=source):
                e = Error(quota="RequestsPerMinute")
                body = e.details["error"]
                del e.details
                if source == "response":
                    e.response.json = lambda: body
                else:
                    e.response_json = body if source != "legacy" else {"reason": "REQUESTS_PER_MINUTE"}
                self.assertEqual(decide_rate_limit(e, 0, 0).reason, "RPM")
