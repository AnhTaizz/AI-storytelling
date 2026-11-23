from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fixtures import Clock
from tools.llm_infra.quota_state import QuotaStateError, QuotaStateStore


class StoreTests(unittest.TestCase):
    def test_lifecycle_and_validation(self):
        clock = Clock()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "state"
            store = QuotaStateStore(path, clock=clock)
            scope = ("gemini", "m", "alias")
            self.assertEqual(store.active_blocks(clock()), [])
            store.record_success(*scope, clock())
            self.assertFalse(path.parent.exists())
            store.block(*scope, 1200, "UNKNOWN_429", clock())
            store.block(*scope, 1190, "UNKNOWN_429", clock())
            self.assertEqual(store.unknown_streak(*scope), 2)
            self.assertEqual(store.blocked_until(*scope, clock()), 1200)
            store.record_success(*scope, clock())
            self.assertEqual(store.unknown_streak(*scope), 0)
            self.assertEqual(len(store.active_blocks(clock())), 1)
            clock.sleep(201)
            self.assertIsNone(store.blocked_until(*scope, clock()))
            self.assertEqual(QuotaStateStore(path, clock=clock).active_blocks(clock()), [])
            for alias in ("", "x"*129, "bad\nname"):
                with self.subTest(alias=alias), self.assertRaises(ValueError):
                    store.block("g", "m", alias, 100, "RPM", clock())
            with self.assertRaises(ValueError):
                store.block(*scope, 1201, "free text", clock())
            path.write_bytes(b"test-key-not-real-1")
            with self.assertRaisesRegex(QuotaStateError, "state.*deleted") as error:
                QuotaStateStore(path, clock=clock)
            self.assertNotIn("test-key", str(error.exception))
