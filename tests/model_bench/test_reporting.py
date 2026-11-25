import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tools.model_bench.reporting import METRICS, write_reports


class ReportingTests(unittest.TestCase):
    def test_unknown_efficiency_is_not_zero_and_true_zero_is_preserved(self):
        cases = [{"id": "case-1", "group": "dev"}, {"id": "case-2", "group": "dev"},
                 {"id": "case-3", "group": "waiting"}]
        base = {"group": "dev", "review": None, **dict.fromkeys(METRICS)}
        rows = [base | {"outcome": "complete", "score": 0, "repairs": 0, "requests": 2},
                base | {"outcome": "error", "score": None, "repairs": 0}]
        with TemporaryDirectory() as temp:
            path = Path(temp)
            write_reports(path, {"mode": "offline-fake"}, cases, rows)
            with (path / "summary.csv").open(encoding="utf-8", newline="") as stream:
                total, group, waiting = csv.DictReader(stream)
            self.assertEqual((total["requests"], total["input_tokens"], total["repairs"]),
                             ("unknown", "unknown", "0"))
            self.assertEqual((total["mean_score"], total["errors"], group["completion_rate"]),
                             ("0", "1", "0.5"))
            self.assertEqual(waiting["repairs"], "unknown")
            self.assertIn("unknown", (path / "report.md").read_text(encoding="utf-8"))
