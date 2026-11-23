"""Synthetic header fixtures only; no private images or remote services are used."""
import csv
import hashlib
import io
import struct
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from tools.media_ingest import ingest_local_images as ingest  # noqa: E402


def png(width=800, height=1200):
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"
            + struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0) + b"\x00" * 4)


def jpeg(width=800, height=1200, marker=0xC0):
    # APP metadata before SOFn, including a marker-like byte sequence.
    app = b"\xff\xe1\x00\x06ab\xff\xc0"
    sof = b"\x08" + struct.pack(">HHB", height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8" + app + bytes((255, marker)) + struct.pack(">H", len(sof) + 2) + sof + b"\xff\xd9"


def gif(width=800, height=1200, version=b"GIF89a"):
    return version + struct.pack("<HHBBB", width, height, 0, 0, 0)


def riff_chunk(kind, data):
    return kind + struct.pack("<I", len(data)) + data + (b"\x00" if len(data) % 2 else b"")


def webp(width=800, height=1200, kind=b"VP8 ", metadata=False):
    if kind == b"VP8 ":
        data = b"\x00\x00\x00\x9d\x01\x2a" + struct.pack("<HH", width, height)
    elif kind == b"VP8L":
        data = b"\x2f" + ((width - 1) | ((height - 1) << 14)).to_bytes(4, "little")
    else:
        data = b"\x00" * 4 + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    chunks = (riff_chunk(b"JUNK", b"abc") if metadata else b"") + riff_chunk(kind, data)
    return b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WEBP" + chunks


class IngestTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.incoming = self.root / "incoming"
        self.incoming.mkdir()
        self.out = self.root / "output"

    def image(self, filename="nested/input.png", data=None):
        path = self.incoming / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png() if data is None else data)
        return path

    def run_cli(self, *options):
        stdout, stderr = io.StringIO(), io.StringIO()
        argv = ["--series", "otonari_no_tenshi", "--incoming", str(self.incoming),
                "--out", str(self.out), *options]
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = ingest.main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def manifest(self):
        return yaml.safe_load((self.out / "IMAGES_MANIFEST.yaml").read_text(encoding="utf-8"))

    def labels(self, rows):
        path = self.root / "labels.csv"
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=ingest.CSV_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        return str(path)


class HeaderTests(IngestTestCase):
    def test_png(self):
        self.assertEqual(ingest.read_dimensions(self.image(data=png(543, 876))), (543, 876))

    def test_all_jpeg_sof_markers(self):
        for marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                       0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            with self.subTest(marker=marker):
                path = self.image("image.jpeg", jpeg(1321, 746, marker))
                self.assertEqual(ingest.read_dimensions(path), (1321, 746))

    def test_gif_versions(self):
        for version in (b"GIF87a", b"GIF89a"):
            with self.subTest(version=version):
                self.assertEqual(ingest.read_dimensions(self.image("image.gif", gif(701, 901, version))), (701, 901))

    def test_all_webp_headers_with_padded_metadata(self):
        for kind in (b"VP8 ", b"VP8L", b"VP8X"):
            with self.subTest(kind=kind):
                self.assertEqual(ingest.read_dimensions(self.image("image.webp", webp(809, 1243, kind, True))),
                                 (809, 1243))

    def test_truncated_unknown_and_zero_headers(self):
        fixtures = [b"", b"unrecognized", png()[:20], gif()[:10], jpeg()[:15],
                    webp()[:-1], png(0, 500), gif(500, 0), jpeg(0, 500), webp(0, 500)]
        for data in fixtures:
            with self.subTest(data=data):
                with self.assertRaises(ValueError):
                    ingest.read_dimensions(self.image(data=data))

    def test_malformed_webp_chunks_and_jpeg_segments(self):
        fixtures = [b"\xff\xd8\xff\xe1\x00\x01", b"\xff\xd8\xff\xda",
                    b"\xff\xd8\xff\xc0\x00\x03\x08"]
        for kind in (b"VP8 ", b"VP8L", b"VP8X"):
            chunks = riff_chunk(kind, b"\x00" * 4)
            fixtures.append(b"RIFF" + struct.pack("<I", len(chunks) + 4) + b"WEBP" + chunks)
        for data in fixtures:
            with self.subTest(data=data):
                with self.assertRaises(ValueError):
                    ingest.read_dimensions(self.image(data=data))


class CliTests(IngestTestCase):
    def test_dry_run_writes_nothing(self):
        source = self.image()
        before = sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*"))
        code, plan, error = self.run_cli()
        self.assertEqual((code, error), (0, ""))
        self.assertIn("DRY RUN", plan)
        self.assertIn("accepted: nested/input.png -> other/otn_0001.png", plan)
        self.assertEqual(sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*")), before)
        self.assertEqual(source.read_bytes(), png())

    def test_apply_copies_and_complete_manifest(self):
        source = self.image()
        code, _, error = self.run_cli("--apply", "--source", "Personal book", "--rights-basis", "purchased_copy")
        self.assertEqual((code, error), (0, ""))
        self.assertEqual(source.read_bytes(), (self.out / "other/otn_0001.png").read_bytes())
        manifest = self.manifest()
        self.assertEqual(list(manifest), ["series", "schema_version", "policy", "aggregate", "images"])
        self.assertEqual(manifest["series"], "otonari_no_tenshi")
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["policy"], "local_private_only")
        record = manifest["images"][0]
        self.assertEqual(record, {
            "image_id": "otn-0001", "path": "other/otn_0001.png", "category": "other",
            "characters": [], "emotion": None, "volume": None, "chapter": None,
            "width": 800, "height": 1200, "byte_size": len(png()),
            "sha256": hashlib.sha256(png()).hexdigest(), "original_filename": "nested/input.png",
            "source": "Personal book", "rights_basis": "purchased_copy", "notes": None,
            "ingested_at": record["ingested_at"],
        })
        self.assertRegex(record["ingested_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(manifest["aggregate"]["total"], 1)
        self.assertEqual(manifest["aggregate"]["per_category"]["other"], 1)
        self.assertEqual(manifest["aggregate"]["per_rights_basis"]["purchased_copy"], 1)

    def test_duplicate_within_run_and_across_runs(self):
        self.image("a.png")
        self.image("nested/b.png")
        code, plan, _ = self.run_cli("--apply")
        self.assertEqual(code, 0)
        self.assertIn("skipped: nested/b.png (duplicate)", plan)
        first = self.manifest()["images"]
        code, plan, _ = self.run_cli("--apply")
        self.assertEqual(code, 0)
        self.assertEqual(plan.count("(duplicate)"), 2)
        self.assertEqual(self.manifest()["images"], first)
        self.assertEqual(self.manifest()["aggregate"]["total"], 1)

    def test_small_unreadable_and_unsupported(self):
        self.image("small.png", png(299, 900))
        self.image("broken.jpg", b"bad header")
        self.image("ignore.txt", b"not an image")
        self.image("edge.PNG", png(300, 300))
        code, plan, _ = self.run_cli("--apply")
        self.assertEqual(code, 0)
        self.assertIn("small.png (too_small)", plan)
        self.assertIn("broken.jpg (unreadable_header)", plan)
        self.assertNotIn("ignore.txt", plan)
        self.assertEqual(self.manifest()["images"][0]["path"], "other/otn_0001.png")

    def test_custom_minimum(self):
        self.image(data=gif(20, 20))
        code, plan, _ = self.run_cli("--min-side", "20")
        self.assertEqual(code, 0)
        self.assertIn("accepted=1", plan)

    def test_numbering_continues_from_manifest_and_existing_files(self):
        self.image("first.png")
        self.run_cli("--apply")
        self.image("second.jpg", jpeg())
        self.run_cli("--apply")
        self.assertEqual([row["image_id"] for row in self.manifest()["images"]], ["otn-0001", "otn-0002"])
        existing = self.out / "illustration/otn_0042.gif"
        existing.parent.mkdir()
        existing.write_bytes(gif())
        self.image("third.webp", webp())
        self.run_cli("--apply")
        self.assertEqual(self.manifest()["images"][-1]["image_id"], "otn-0043")
        self.assertEqual(existing.read_bytes(), gif())
        self.assertEqual(self.manifest()["aggregate"]["total"], 3)

    def test_labels_override_defaults_and_preserve_unicode(self):
        self.image("a.png")
        self.image("b.gif", gif())
        name = "Mahiru " + chr(0x771F)
        labels = self.labels([{"filename": "a.png", "category": "character_emotion", "characters": name + "; Amane ;",
                               "emotion": "shy", "volume": "2", "chapter": "extra-1", "source": "My art",
                               "rights_basis": "original_art", "notes": "private"}])
        code, _, error = self.run_cli("--apply", "--labels", labels, "--source", "CLI source",
                                      "--rights-basis", "purchased_copy")
        self.assertEqual((code, error), (0, ""))
        a, b = self.manifest()["images"]
        self.assertEqual(a["path"], "character_emotion/otn_0001.png")
        for field, value in {"characters": [name, "Amane"], "emotion": "shy", "volume": "2", "chapter": "extra-1",
                             "source": "My art", "rights_basis": "original_art", "notes": "private"}.items():
            self.assertEqual(a[field], value)
        self.assertIn(name, (self.out / "IMAGES_MANIFEST.yaml").read_text(encoding="utf-8"))
        self.assertEqual((b["source"], b["rights_basis"]), ("CLI source", "purchased_copy"))
        self.assertEqual(self.manifest()["aggregate"]["per_category"]["character_emotion"], 1)
        self.assertEqual(self.manifest()["aggregate"]["per_rights_basis"]["original_art"], 1)

    def test_invalid_labels_exit_two_before_any_writes(self):
        self.image("a.png")
        self.image("z.png", png(900, 900))
        for field in ("category", "rights_basis"):
            with self.subTest(field=field):
                labels = self.labels([{"filename": "a.png"}, {"filename": "z.png", field: "invalid"}])
                code, _, error = self.run_cli("--apply", "--labels", labels)
                self.assertEqual(code, 2)
                self.assertIn(f"unknown {field}", error)
                self.assertFalse(self.out.exists())

    def test_invalid_labels_leave_existing_output_unchanged(self):
        self.image("a.png")
        self.run_cli("--apply")
        before = {p.relative_to(self.out): p.read_bytes() for p in self.out.rglob("*") if p.is_file()}
        labels = self.labels([{"filename": "unused.png", "category": "invalid"}])
        self.assertEqual(self.run_cli("--apply", "--labels", labels)[0], 2)
        self.assertEqual({p.relative_to(self.out): p.read_bytes() for p in self.out.rglob("*") if p.is_file()}, before)

    def test_malformed_csv_and_missing_labels(self):
        self.image()
        labels = self.root / "malformed.csv"
        for contents in ("category\nother\n", "filename,category\na.png,other,extra\n",
                         "filename,category\na.png\n", "filename,category\n../a.png,other\n"):
            labels.write_text(contents, encoding="utf-8")
            self.assertEqual(self.run_cli("--apply", "--labels", str(labels))[0], 2)
            self.assertFalse(self.out.exists())
        self.assertEqual(self.run_cli("--apply", "--labels", str(self.root / "missing.csv"))[0], 2)

    def test_output_inside_incoming_is_excluded(self):
        self.out = self.incoming / "images"
        self.out.mkdir()
        (self.out / "existing.gif").write_bytes(gif())
        self.image()
        self.assertEqual(self.run_cli("--apply")[0], 0)
        self.assertEqual(self.manifest()["aggregate"]["total"], 1)

    def test_default_output_and_roshidere_prefix_in_temporary_repo(self):
        self.image()
        stdout = io.StringIO()
        with patch.object(ingest, "REPO_ROOT", self.root), redirect_stdout(stdout):
            self.assertEqual(ingest.main(["--series", "roshidere", "--incoming", str(self.incoming), "--apply"]), 0)
        out = self.root / "data/sample/roshidere/images"
        self.assertEqual((out / "other/rsd_0001.png").read_bytes(), png())
        manifest = yaml.safe_load((out / "IMAGES_MANIFEST.yaml").read_text(encoding="utf-8"))
        self.assertEqual(manifest["images"][0]["image_id"], "rsd-0001")

    def test_manifest_is_written_by_atomic_replace(self):
        self.image()
        real_replace = ingest.os.replace
        observations = []

        def observe(source, destination):
            observations.append((Path(source).parent, Path(destination), yaml.safe_load(Path(source).read_text(encoding="utf-8"))))
            real_replace(source, destination)

        with patch.object(ingest.os, "replace", side_effect=observe):
            self.assertEqual(self.run_cli("--apply")[0], 0)
        self.assertEqual(len(observations), 1)
        parent, destination, manifest = observations[0]
        self.assertEqual(parent, self.out)
        self.assertEqual(destination, self.out / "IMAGES_MANIFEST.yaml")
        self.assertEqual(manifest["aggregate"]["total"], 1)
        self.assertFalse(list(self.out.glob(".images-manifest-*.tmp")))

    def test_incompatible_manifest_fails_without_modification(self):
        self.image()
        self.run_cli("--apply")
        path = self.out / "IMAGES_MANIFEST.yaml"
        path.write_text("series: another_series\n", encoding="utf-8")
        self.assertEqual(self.run_cli("--apply")[0], 2)
        self.assertEqual(path.read_text(encoding="utf-8"), "series: another_series\n")

    def test_protected_tree_is_pruned_without_listing_it(self):
        protected = self.incoming / "private"
        protected.mkdir()
        self.image("private/do_not_read.png")
        self.image("allowed.png")
        with patch.object(ingest, "PROTECTED_ROOT", protected), patch.object(ingest, "ALLOWED_OUTPUT", protected / "images"):
            original_walk = ingest.os.walk

            def guarded_walk(*args, **kwargs):
                for directory, directories, files in original_walk(*args, **kwargs):
                    self.assertNotEqual(Path(directory), protected)
                    yield directory, directories, files

            with patch.object(ingest.os, "walk", side_effect=guarded_walk):
                code, plan, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("accepted=1", plan)

    def test_no_network_modules_in_tool_source(self):
        source = Path(ingest.__file__).read_text(encoding="utf-8")
        for forbidden in ("requests", "urllib.request", "http.client", "socket"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
