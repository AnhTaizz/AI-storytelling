"""Shared collection file helpers: confinement, atomic writes and manifest aggregates."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.media_ingest.collection_io import aggregate, safe, save_report, write_csv


class CollectionIoTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_paths_must_stay_strictly_inside_the_collection(self):
        self.assertEqual(safe(self.root, "a/b.png"), (self.root / "a/b.png").resolve())
        for relative in ("", ".", "../outside.png", "a/../../outside.png"):
            with self.subTest(relative=relative), self.assertRaisesRegex(ValueError, "outside collection"):
                safe(self.root, relative)

    def test_reports_and_csv_are_written_whole(self):
        report = self.root / "report.json"
        save_report(report, {"chapters": 2})
        self.assertEqual(json.loads(report.read_text(encoding="utf-8")), {"chapters": 2})
        rows = [{"image_id": "otn-1", "path": "a.png"}, {"image_id": "otn-2", "path": "b.png"}]
        index = self.root / "index.csv"
        write_csv(index, rows)
        with index.open(encoding="utf-8-sig", newline="") as stream:
            self.assertEqual(list(csv.DictReader(stream)), rows)
        write_csv(self.root / "empty.csv", [])
        self.assertFalse((self.root / "empty.csv").exists())
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_a_briefly_locked_report_is_retried_and_a_lasting_lock_is_raised(self):
        real = Path.replace
        calls = []

        def locked_once(self, target):
            calls.append(target)
            if len(calls) == 1:
                raise PermissionError("held by an indexer")
            return real(self, target)

        report = self.root / "report.json"
        with patch.object(Path, "replace", locked_once), patch("tools.media_ingest.collection_io.time.sleep"):
            save_report(report, {"ok": True})
        self.assertEqual((len(calls), json.loads(report.read_text(encoding="utf-8"))), (2, {"ok": True}))
        with patch.object(Path, "replace", side_effect=PermissionError("held")), \
                patch("tools.media_ingest.collection_io.time.sleep"), self.assertRaises(PermissionError):
            save_report(report, {"ok": False})

    def test_aggregate_counts_every_category_and_rights_basis(self):
        manifest = {"images": [{"category": "manga_panel", "rights_basis": "official_promo"},
                               {"category": "other", "rights_basis": "official_promo"}]}
        aggregate(manifest)
        totals = manifest["aggregate"]
        self.assertEqual(totals["total"], 2)
        self.assertEqual((totals["per_category"]["manga_panel"], totals["per_category"]["illustration"]), (1, 0))
        self.assertEqual(totals["per_rights_basis"]["official_promo"], 2)


if __name__ == "__main__":
    unittest.main()
