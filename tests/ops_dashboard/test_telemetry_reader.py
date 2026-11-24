from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tools.llm_infra.telemetry import Telemetry
from tools.ops_dashboard.telemetry_reader import read_requests


class TelemetryReaderTests(unittest.TestCase):
    def test_preserves_nulls_and_filters_by_time_and_metadata(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "requests.db"
            writer = Telemetry(path)
            start = datetime.now(timezone.utc) - timedelta(minutes=1)
            writer.write(stage="utility", provider="groq", outcome="SUCCESS", tokens_source="reported",
                         input_tokens=7, cost_estimated=0.5, cost_source="estimated")
            writer.write(stage="script", provider="gemini", outcome="SKIPPED", tokens_source="unknown", input_tokens=9)
            end = datetime.now(timezone.utc) + timedelta(minutes=1)
            rows, matching = read_requests(path, start, end, limit=1, filters={"provider": "groq"})
            self.assertEqual(matching, 1)
            self.assertEqual((rows[0]["input_tokens"], rows[0]["output_tokens"]), (7, None))
            self.assertEqual((rows[0]["cost_source"], rows[0]["cost_estimated"]), ("estimated", 0.5))
            self.assertEqual(read_requests(path, start, end, limit=1, filters={"provider": "' OR 1=1 --"}), ([], 0))
            self.assertEqual(read_requests(path, end, end, limit=1), ([], 0))
