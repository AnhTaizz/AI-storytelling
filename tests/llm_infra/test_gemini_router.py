from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from fixtures import Clock, Error, settings
from tools.llm_infra.gemini_config import load_routing_config
from tools.llm_infra.gemini_router import GeminiQuotaPaused, GeminiRouter
from tools.llm_infra.quota_state import QuotaStateStore
from tools.story_extraction.gemini_key_pool_v1 import GeminiKeyPool
from tools.story_extraction.gemini_transport_v1 import GeminiTransportError


class RouterTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "state"
        self.clock = Clock()
        self.calls = []
        self.actions = []

    def router(self, *groups, **kwargs):
        cfg = load_routing_config(self.path.with_name("absent"), settings(*groups))
        def factory(key):
            def generate(**args):
                self.calls.append((key, args["model"]))
                action = self.actions.pop(0) if self.actions else None
                if isinstance(action, Exception):
                    raise action
                return SimpleNamespace(text=key, model_version=key)
            return SimpleNamespace(generate=generate)
        return GeminiRouter(GeminiKeyPool(cfg.credentials, clock=self.clock),
                            QuotaStateStore(self.path, clock=self.clock), factory,
                            clock=self.clock, sleep=self.clock.sleep, **kwargs)

    def generate(self, router, model="model-a"):
        return router.generate("system", "user", model, {}, "test-key-not-real-1")

    def test_project_model_rotation_restart_and_expiry(self):
        router = self.router("shared", "shared", "other")
        self.actions = [Error(quota="GenerateRequestsPerDayPerProjectPerModel-FreeTier")]
        record = self.generate(router)
        self.assertEqual([a["slot_id"] for a in record["transport_attempts"]], ["gemini_slot_1", "gemini_slot_3"])
        self.assertEqual((record["transport"], record["quota_scope"]), ("GEMINI_ROUTER_V1", "project_model"))
        self.assertNotIn("test-key-not-real", repr(record))
        self.assertNotIn(b"test-key-not-real", self.path.read_bytes())
        router = self.router("shared", "shared", "other")
        self.assertEqual(self.generate(router)["project_label"], "other")
        self.assertEqual(self.generate(router, "model-b")["project_label"], "shared")
        self.assertEqual(self.clock.waits, [])
        self.clock.sleep(28800 - self.clock())
        self.assertEqual(self.generate(self.router("shared","other"))["project_label"], "shared")

    def test_pause_with_resume_time_and_one_inline_wait(self):
        router = self.router("", "")
        # Unlabeled keys are separate scopes: a 429 on one moves to the other.
        self.actions = [Error(delay="1.5s"), Error(quota="RequestsPerDay"), Error(quota="RequestsPerDay")]
        with self.assertRaises(GeminiQuotaPaused) as paused:
            self.generate(router)
        self.assertEqual((paused.exception.code, paused.exception.resume_after), ("QUOTA_EXHAUSTED", 28800))
        self.assertIn("08:00:00Z", str(paused.exception))
        self.assertNotIn("test-key-not-real", str(paused.exception))
        self.assertEqual(self.clock.waits, [1.5])
        with self.assertRaises(GeminiQuotaPaused):
            self.generate(self.router("", ""))
        self.assertEqual([key for key, _ in self.calls],
                         ["test-key-not-real-1", "test-key-not-real-2", "test-key-not-real-1"])

    def test_auth_disables_only_one_slot_and_exhaustion_is_distinct(self):
        router = self.router("p", "p")
        self.actions = [Error(401)]
        self.assertEqual(self.generate(router)["slot_id"], "gemini_slot_2")
        self.actions = [Error(403)]
        with self.assertRaises(GeminiTransportError) as caught:
            self.generate(router)
        self.assertEqual(caught.exception.code, "NO_USABLE_CREDENTIAL")
        self.assertEqual(self.clock.waits, [])

    def test_transport_retry_limit_and_call_cap(self):
        for error in (Error(503), TimeoutError(), ConnectionError(), Error(400)):
            with self.subTest(error=type(error)):
                self.actions = [error]*4
                self.clock.waits.clear()
                router = self.router("a")
                with self.assertRaises(GeminiTransportError) as caught:
                    self.generate(router)
                expected = [] if getattr(error, "code", None) == 400 else [1.0, 2.0]
                self.assertEqual(self.clock.waits, expected)
                self.assertEqual(caught.exception.attempts, len(expected)+1)
        self.actions = [Error(401)]*6
        with self.assertRaises(GeminiTransportError) as caught:
            self.generate(self.router(*(["a"]*6), max_transport_retries=0))
        self.assertEqual(caught.exception.attempts, 2)
