"""Check read-only M9 season markers before a Gemini benchmark dispatch."""
import json
import os
from pathlib import Path
import time

from tools.model_bench.approval import LiveRefusal

SEASON_FILES = {"season.json", "season.md", "season.html", "season_script.md"}
MESSAGE = ("Tạm dừng benchmark Gemini: M9 có thể đang chạy hoặc chưa xác minh được trạng thái. "
           "Chờ M9 kết thúc hoặc dùng --m9-clear-attested-by-owner khi chủ dự án đã xác nhận.")


def _walk_error(error):
    raise error


def check_m9(provider, directory, attested, *, now=None):
    if provider != "gemini" or attested:
        return
    now = time.time() if now is None else now
    try:
        try:
            directory.stat()
        except FileNotFoundError:
            return
        for root, _, files in os.walk(directory, onerror=_walk_error):
            if any(now - (Path(root) / name).stat().st_mtime < 6 * 3600
                   for name in SEASON_FILES.intersection(files)):
                raise LiveRefusal(MESSAGE)
            if "gate_lock.json" in files:
                season = Path(root) / "season.json"
                status = json.loads(season.read_text(encoding="utf-8"))["status"]
                if status != "COMPLETED" and not (
                        status == "FAILED" and now - season.stat().st_mtime > 24 * 3600):
                    raise LiveRefusal(MESSAGE)
    except LiveRefusal:
        raise
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise LiveRefusal(MESSAGE) from error
