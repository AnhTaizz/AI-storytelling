from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tools.llm_infra.neuron_ledger import NeuronLedger
from tools.ops_dashboard.quota_reader import read_quota


class QuotaReaderTests(unittest.TestCase):
    def test_ledger_without_quota_table_provides_today_only(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "quota.db"
            now = datetime(2026, 11, 24, 10, tzinfo=timezone.utc)
            ledger = NeuronLedger(path)
            ledger.add("cloudflare", "scope", "2026-11-23", 1000, now.timestamp())
            ledger.add("cloudflare", "scope", "2026-11-24", 40, now.timestamp())
            ledger.add("other", "scope", "2026-11-24", 25, now.timestamp())
            self.assertEqual(read_quota(path, now), ([], 40))
