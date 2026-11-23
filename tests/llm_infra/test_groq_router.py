from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fixtures import Clock, FakeGroq, GROQ_TEST_KEY, groq_settings
from tools.llm_infra.groq_config import inspect_groq_settings
from tools.llm_infra.groq_free_models_v1 import DEFAULT_MODEL_CHAIN
from tools.llm_infra.groq_router import GroqQuotaPaused, GroqRouter, GroqTransportError
from tools.llm_infra.groq_transport import GroqHTTPError, GroqResponse
from tools.llm_infra.quota_state import QuotaStateStore
from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError


MODEL, OTHER_MODEL = DEFAULT_MODEL_CHAIN


def refused(message="", headers=None):
    return GroqHTTPError(kind="RATE_LIMIT", status=429, headers=headers, body={"error": {"message": message}})


class GroqRouterTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "state"
        self.clock = Clock()
        self.store = QuotaStateStore(self.path, clock=self.clock)
        self.client = FakeGroq()

    def router(self, *labels, hops="3", **options):
        config = inspect_groq_settings(groq_settings(*labels) | {"GROQ_MAX_RATE_LIMIT_HOPS": hops})
        return GroqRouter(config, self.store, self.client.factory, clock=self.clock,
                          sleep=self.clock.sleep, **options)

    def generate(self, router, model=MODEL):
        return router.generate("system", "user", model, {}, GROQ_TEST_KEY)

    def test_rate_limit_hops_by_scope_and_persists_per_model(self):
        self.client.actions = [refused("Tokens per day (TPD). Please try again in 7m12.5s.")]
        record = self.generate(self.router("shared", "shared", "other"))
        self.assertEqual((record["provider"], record["transport"], record["quota_scope"]),
                         ("Groq", "GROQ_ROUTER_V1", "organization_model"))
        self.assertEqual((record["model_requested"], record["model_reported_if_available"]), (MODEL, MODEL))
        self.assertEqual((record["slot_id"], record["scope"]), ("groq_slot_3", "other"))
        self.assertEqual([(entry["slot_id"], entry["outcome"]) for entry in record["transport_attempts"]],
                         [("groq_slot_1", "RATE_LIMIT"), ("groq_slot_3", "SUCCESS")])
        self.assertEqual(record["usage_metadata"], {"total_tokens": 14})
        self.assertEqual(record["raw_content"], '{"status":"ok"}')
        self.assertEqual(self.store.active_blocks(self.clock())[0]["reason"], "TPD")
        self.assertNotIn(GROQ_TEST_KEY.encode(), self.path.read_bytes())
        self.store = QuotaStateStore(self.path, clock=self.clock)
        self.assertEqual(self.generate(self.router("shared", "other"))["scope"], "other")
        self.assertEqual(self.generate(self.router("shared", "other"), OTHER_MODEL)["scope"], "shared")
        self.clock.sleep(432.5)
        self.assertEqual(self.generate(self.router("shared", "other"))["scope"], "shared")

    def test_hop_cap_uses_earliest_refusal_and_leaves_untried_slots_available(self):
        self.client.actions = [refused(headers={"retry-after": str(delay)}) for delay in (30, 10, 20)]
        router = self.router("", "", "", "", hops="3")
        with self.assertRaises(GroqQuotaPaused) as caught:
            self.generate(router)
        error = caught.exception
        self.assertEqual((error.code, error.attempts, error.resume_after), ("QUOTA_EXHAUSTED", 3, 1010))
        self.assertIn("1970-01-01T00:16:50Z", str(error))
        self.assertEqual(self.clock.waits, [])
        self.assertEqual(self.generate(router)["slot_id"], "groq_slot_4")

    def test_all_blocked_waits_once_then_pauses_or_succeeds(self):
        for outcome in ("pause_after_wait", "pause_without_wait", "success"):
            with self.subTest(outcome=outcome):
                self.store = QuotaStateStore(None, clock=self.clock)
                self.clock.waits.clear()
                self.client.calls.clear()
                now = self.clock()
                first = 61 if outcome == "pause_without_wait" else 3
                self.store.block("groq", MODEL, "same", now + first, "RPM", now)
                self.store.block("groq", MODEL, "second", now + 120, "RPD", now)
                router = self.router("same", "same", "second")
                if outcome == "success":
                    self.assertEqual(self.generate(router)["scope"], "same")
                else:
                    self.client.actions = [refused(headers={"retry-after": "5"})] if first == 3 else []
                    with self.assertRaises(GroqQuotaPaused) as caught:
                        self.generate(router)
                    expected = (1, now + 8) if first == 3 else (0, now + 61)
                    self.assertEqual((caught.exception.attempts, caught.exception.resume_after), expected)
                    self.assertEqual(len(self.client.calls), expected[0])
                self.assertEqual(self.clock.waits, [3] if first == 3 else [])

    def test_auth_disables_one_slot_until_router_restart(self):
        self.client.actions = [GroqHTTPError(kind="AUTH_FAILURE", status=401)]
        router = self.router("team", "team")
        self.assertEqual(self.generate(router)["slot_id"], "groq_slot_2")
        self.client.actions = [GroqHTTPError(kind="AUTH_FAILURE", status=403)]
        with self.assertRaises(GroqTransportError) as caught:
            self.generate(router)
        self.assertEqual((caught.exception.code, caught.exception.attempts), ("NO_USABLE_CREDENTIAL", 1))
        self.assertEqual(self.clock.waits, [])
        self.assertEqual(self.generate(self.router("team", "team"))["slot_id"], "groq_slot_1")

    def test_bounded_transport_retries_and_immediate_request_failures(self):
        for kind, delays in [
            ("SERVER_FAILURE", [0.25, 0.5]), ("TRANSPORT_FAILURE", [0.25, 0.5]),
            ("MODEL_UNAVAILABLE", []), ("REQUEST_FAILURE", []), ("MALFORMED_RESPONSE", []),
        ]:
            with self.subTest(kind=kind):
                self.client.calls.clear()
                self.clock.waits.clear()
                self.client.actions = [GroqHTTPError(kind=kind, body={"error": {"message": GROQ_TEST_KEY}})] * 4
                with self.assertRaises(GroqTransportError) as caught:
                    self.generate(self.router("", base_backoff_seconds=0.25))
                self.assertEqual((caught.exception.code, caught.exception.attempts), (kind, len(delays) + 1))
                self.assertEqual(len(self.client.calls), len(delays) + 1)
                self.assertEqual(self.clock.waits, delays)
                self.assertNotIn(GROQ_TEST_KEY, repr(caught.exception))
                self.assertIsNone(caught.exception.__context__)

    def test_success_clears_unknown_streak_and_proactively_blocks_daily_requests(self):
        self.store.block("groq", MODEL, "shared", self.clock(), "UNKNOWN_429", self.clock())
        self.client.actions = [GroqResponse("ok", {}, MODEL, {"x-ratelimit-remaining-requests": "0",
                                                             "x-ratelimit-reset-requests": "1h2m3s"})]
        router = self.router("shared", "shared", "other")
        self.assertEqual(self.generate(router)["scope"], "shared")
        self.assertEqual(self.store.unknown_streak("groq", MODEL, "shared"), 0)
        block, = self.store.active_blocks(self.clock())
        self.assertEqual((block["reason"], block["blocked_until"]), ("RPD", self.clock() + 3723))
        self.assertEqual(self.generate(router)["scope"], "other")
        self.assertEqual(self.generate(router, OTHER_MODEL)["scope"], "shared")

    def test_round_robin_and_record_redaction(self):
        self.client.actions = [GroqResponse(GROQ_TEST_KEY, {GROQ_TEST_KEY: [GROQ_TEST_KEY]},
                                            GROQ_TEST_KEY, {}, GROQ_TEST_KEY)]
        router = self.router("", "")
        records = [self.generate(router) for _ in range(3)]
        self.assertEqual([record["slot_id"] for record in records], ["groq_slot_1", "groq_slot_2", "groq_slot_1"])
        self.assertEqual(records[0]["raw_content"], "[REDACTED]")
        self.assertNotIn(GROQ_TEST_KEY, repr(records))
        for model, message in ((f"model-{GROQ_TEST_KEY}", "credential material"),
                               ("model-preview", "MODEL_NOT_FREE_TIER")):
            with self.subTest(model=model), self.assertRaisesRegex(GeminiConfigError, message) as caught:
                self.generate(router, model)
            self.assertNotIn(GROQ_TEST_KEY, str(caught.exception))
        self.assertEqual(len(self.client.calls), 3)
