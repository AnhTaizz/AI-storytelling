from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from tools.ops_dashboard.sqlite_reader import SourceUnavailable, read_database


class SQLiteReaderTests(unittest.TestCase):
    def test_connection_is_read_only_even_if_query_only_is_disabled(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "requests #.db"
            with closing(sqlite3.connect(path)) as db:
                db.execute("CREATE TABLE samples (value)")
            before = path.read_bytes(), path.stat().st_mtime_ns
            with read_database(path) as db:
                self.assertEqual(db.execute("PRAGMA query_only").fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT count(*) FROM samples").fetchone()[0], 0)
                for disable in (False, True):
                    with self.subTest(disable_query_only=disable), self.assertRaises(sqlite3.OperationalError):
                        if disable:
                            db.execute("PRAGMA query_only=OFF")
                        db.execute("INSERT INTO samples VALUES (1)")
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_wal_file_is_left_untouched_even_when_sidecars_are_absent(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "wal.db"
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
                db.execute("CREATE TABLE samples (value)")
            self.assertEqual(list(Path(directory).iterdir()), [path])
            with self.assertRaisesRegex(SourceUnavailable, "wal_snapshot_required"), read_database(path):
                self.fail("The dashboard must never open a WAL database")
            self.assertEqual(list(Path(directory).iterdir()), [path])
