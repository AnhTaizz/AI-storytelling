from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from fixtures import CF_MODEL
from tools.llm_infra.neuron_ledger import NeuronLedger, estimate_neurons, estimate_prompt_neurons, utc_day
from tools.llm_infra.quota_state import QuotaStateError, QuotaStateStore


class NeuronLedgerTests(unittest.TestCase):
    def test_sqlite_ledger_coexists_with_quota_schema_in_either_creation_order(self):
        for quota_first in (True, False):
            with self.subTest(quota_first=quota_first), TemporaryDirectory() as tmp:
                path = Path(tmp) / "folder" / "quota.sqlite"
                store = QuotaStateStore(path, clock=lambda: 0)
                ledger = NeuronLedger(path)
                self.assertEqual(ledger.used("cloudflare", "account", "1970-01-01"), 0)
                ledger.purge_before("1970-01-01")
                self.assertFalse(path.exists())
                if quota_first:
                    store.block("cloudflare", "*", "account", 86400, "RPD", 1)
                ledger.add("cloudflare", "account", "1970-01-01", 2, 1)
                with closing(sqlite3.connect(path)) as db:
                    self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], int(quota_first))
                if not quota_first:
                    store.block("cloudflare", "*", "account", 86400, "RPD", 1)
                self.assertEqual(NeuronLedger(path).add("cloudflare", "account", "1970-01-01", 3, 2), 5)
                self.assertEqual(store.blocked_until("cloudflare", "*", "account", 2), 86400)
                with closing(sqlite3.connect(path)) as db, db:
                    self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
                    db.execute("PRAGMA user_version=77")
                self.assertEqual(ledger.used("cloudflare", "account", "1970-01-01"), 5)
                with closing(sqlite3.connect(path)) as db:
                    self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 77)

    def test_totals_are_isolated_by_provider_scope_and_utc_day_and_old_days_purge(self):
        ledger = NeuronLedger(":memory:")
        yesterday, today = utc_day(86399), utc_day(86400)
        self.assertEqual((yesterday, today), ("1970-01-01", "1970-01-02"))
        for provider, scope, day, count in [
            ("cloudflare", "one", yesterday, 1), ("cloudflare", "one", today, 2),
            ("cloudflare", "two", today, 3), ("test-provider", "one", today, 4),
        ]:
            ledger.add(provider, scope, day, count, 86400)
            self.assertEqual(ledger.used(provider, scope, day), count)
        ledger.purge_before(today)
        self.assertEqual(ledger.used("cloudflare", "one", yesterday), 0)
        self.assertEqual(ledger.used("cloudflare", "one", today), 2)
        with self.assertRaises(ValueError):
            ledger.add("cloudflare", "one", today, -1, 86400)

    def test_unusable_state_is_a_config_error(self):
        with TemporaryDirectory() as tmp:
            bad = Path(tmp) / "broken"
            bad.write_bytes(b"not a database")
            for path in (bad, bad / "blocked"):
                with self.subTest(path=path), self.assertRaisesRegex(QuotaStateError, "Cannot use quota state"):
                    NeuronLedger(path).add("cloudflare", "account", "1970-01-01", 1, 0)

    def test_estimates_use_combined_prices_and_ceiling(self):
        for prompt, completion, estimate in [(0, 0, 0), (1, 1, 1), (200, 100, 14), (1000000, 1000000, 100000)]:
            with self.subTest(prompt=prompt, completion=completion):
                self.assertEqual(estimate_neurons(CF_MODEL, prompt, completion), estimate)
        self.assertEqual(estimate_prompt_neurons(CF_MODEL, 0), 0)
        self.assertEqual(estimate_prompt_neurons(CF_MODEL, 93), 1)
        self.assertEqual(estimate_prompt_neurons(CF_MODEL, 94), 2)
