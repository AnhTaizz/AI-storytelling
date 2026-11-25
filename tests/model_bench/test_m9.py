import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

from tools.model_bench.approval import LiveRefusal
from tools.model_bench.m9 import check_m9


class M9Tests(unittest.TestCase):
    def test_m9_lock_and_recent_season_file(self):
        now = time.time()
        for lock, status, hours, blocked in (
            (False, "RUNNING", 7, False),
            (False, "COMPLETED", 5, True),
            (True, None, 0, True),
            (True, "RUNNING", 30, True),
            (True, "COMPLETED", 5, True),
            (True, "COMPLETED", 7, False),
            (True, "FAILED", 23, True),
            (True, "FAILED", 25, False),
        ):
            with self.subTest(lock=lock, status=status, hours=hours), TemporaryDirectory() as temp:
                root = Path(temp)
                season = root / "nested" / "sample"
                season.mkdir(parents=True)
                if lock:
                    (season / "gate_lock.json").touch()
                if status is not None:
                    path = season / "season.json"
                    path.write_text(json.dumps({"status": status}), encoding="utf-8")
                    os.utime(path, (now, now - hours * 3600))
                check_m9("groq", root, False, now=now)
                check_m9("gemini", root, True, now=now)
                if blocked:
                    with self.assertRaisesRegex(LiveRefusal, "M9 có thể đang chạy"):
                        check_m9("gemini", root, False, now=now)
                else:
                    check_m9("gemini", root, False, now=now)
