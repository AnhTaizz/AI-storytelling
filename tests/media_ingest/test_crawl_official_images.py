"""Guard against pulling sidebar adverts or unrelated manga into the collection."""
import csv
import io
import json
import unittest
import hashlib
import struct
import tempfile
import zlib
from pathlib import Path
from unittest.mock import patch

from tools.media_ingest import crawl_official_images as crawl
from tools.media_ingest.crawl_official_images import Asset, PageParser, download, gangan_pages


class SourceSelectionTests(unittest.TestCase):
    def test_interrupted_staging_file_is_repaired_before_ingest(self):
        def chunk(name, data):
            return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data))
        header = struct.pack(">IIBBBBB", 400, 400, 8, 0, 0, 0, 0)
        png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(b"\0" * (401 * 400))) + chunk(b"IEND", b"")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            digest = hashlib.sha256(png).hexdigest()
            stale = root / "test" / (digest + ".png")
            stale.parent.mkdir(); stale.write_bytes(png[:40])
            record = download(Asset("https://example.test/page.png", "https://example.test/chapter", "manga_panel", "test"), root, fetcher=lambda _: png)
            self.assertEqual((root / record["filename"]).read_bytes(), png)
            self.assertEqual(list(stale.parent.glob(".download-*.tmp")), [])

    def test_only_publisher_article_body_images(self):
        image = "https://cdn-ak.f.st-hatena.com/images/fotolife/m/magazine_pocket/20240708/page.png"
        parser = PageParser()
        parser.feed(f'<img src="{image}?sidebar"><div class="entry-content cf">'
                    f'<div><img src="{image}"></div>'
                    '<img src="https://advertiser.example/banner.png">'
                    f'</div><img src="{image}?footer">')
        self.assertEqual(parser.article_images, [image])

    def test_lookalike_image_host_is_excluded(self):
        parser = PageParser()
        parser.feed('<div class="entry-content"><img src="https://cdn-ak.f.st-hatena.com.evil.example/'
                    'images/fotolife/m/magazine_pocket/ad.png"></div>')
        self.assertEqual(parser.article_images, [])

    def test_only_requested_manga_pages_are_selected_in_order(self):
        first = "/secure/title/1480/chapter/62311/manga_page/high/1.webp?hash=abc&expires=123"
        second = "/secure/title/1480/chapter/62311/manga_page/high/2.webp?hash=def&expires=123"
        data = {"pages": [
            {"image": {"imageUrl": first}},
            {"image": {"imageUrl": "/secure/extra_manga_page/advert.webp"}},
            {"linkImage": {"imageUrl": "/secure/extra_manga_page/ad.webp", "url": "/title/99"}},
            {"image": {"imageUrl": "/secure/title/99/chapter/1/manga_page/high/wrong.webp"}},
            {"image": {"imageUrl": second}},
        ]}
        assets = gangan_pages(data, "https://www.ganganonline.com/title/1480/chapter/62311", 1480, "1-1")
        self.assertEqual([a.page for a in assets], [1, 2])
        self.assertEqual([a.url for a in assets], ["https://www.ganganonline.com" + first,
                                                 "https://www.ganganonline.com" + second])
        self.assertEqual([a.chapter for a in assets], ["1-1", "1-1"])


def png_image(colour=(10, 20, 30), size=(400, 400)):
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, "PNG")
    return buffer.getvalue()


class Response:
    def __init__(self, data):
        self.data = data

    def read(self, limit):
        return self.data[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def parser_with(images=(), next_data=None):
    parser = PageParser()
    parser.article_images = list(images)
    parser.next_data = json.dumps(next_data) if next_data is not None else ""
    return parser


class FetchAndDiscoveryTests(unittest.TestCase):
    def test_fetch_needs_https_and_bounds_the_response(self):
        with patch.object(crawl.time, "sleep"):
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                crawl.fetch("http://example.test/a")
            with patch.object(crawl, "urlopen", return_value=Response(b"x" * (crawl.MAX_BYTES + 1))), \
                    self.assertRaisesRegex(ValueError, "exceeds"):
                crawl.fetch("https://example.test/a")
            with patch.object(crawl, "urlopen", return_value=Response(b"<div class='entry-content'></div>")):
                self.assertEqual(crawl.page("https://example.test/a").article_images, [])

    def test_roshidere_articles_skip_the_heading_image_and_key_visuals_are_deduplicated(self):
        def page(url):
            if url.endswith("russia_20240701"):
                raise ValueError("layout changed")
            return parser_with(["https://img/heading.png", "https://img/1.png", "https://img/2.png"])

        html = b"core_sys/images/main/home/kv1.jpg core_sys/images/main/home/kv1.jpg core_sys/images/main/home/kv2.jpg"
        errors = []
        with patch.object(crawl, "page", page), patch.object(crawl, "fetch", return_value=html):
            assets = crawl.discover("roshidere", errors)
        self.assertEqual([(a.url, a.page) for a in assets if a.media == "manga"],
                         [("https://img/1.png", 1), ("https://img/2.png", 2)])
        self.assertEqual([a.url for a in assets if a.media == "anime"],
                         ["https://roshidere.com/core_sys/images/main/home/kv1.jpg",
                          "https://roshidere.com/core_sys/images/main/home/kv2.jpg"])
        self.assertEqual([e["error"] for e in errors], ["layout changed"])

    def test_angel_title_takes_covers_and_only_readable_chapters_of_title_1480(self):
        title = {"titleId": 1480, "volumeSections": {"volumes": [{"imageUrl": "/manga1.jpg"}]},
                 "originalSections": {"volumes": [{"imageUrl": "/novel1.jpg"}]},
                 "chapters": [{"id": 2}, {"id": 1}, {"id": 3, "status": "expired"}, {"id": 4, "appLaunchUrl": "app"}]}
        good = {"titleDetailUrl": "/title/1480", "chapterName": "1-1",
                "pages": [{"image": {"imageUrl": "/secure/title/1480/chapter/1/manga_page/high/1.webp"}}]}
        requested = []

        def page(url):
            requested.append(url)
            if url.endswith("/title/1480"):
                return parser_with(next_data={"props": {"pageProps": {"data": {"default": title}}}})
            data = good if url.endswith("/chapter/1") else {**good, "titleDetailUrl": "/title/99"}
            return parser_with(next_data={"props": {"pageProps": {"data": data}}})

        errors = []
        with patch.object(crawl, "page", page):
            assets = crawl.discover("otonari_no_tenshi", errors)
        self.assertEqual([r.rsplit("/", 1)[-1] for r in requested], ["1480", "1", "2"])
        self.assertEqual([a.media for a in assets], ["manga", "light_novel", "manga"])
        self.assertEqual(assets[-1].chapter, "1-1")
        self.assertEqual(len(errors), 1)
        errors = []
        title["titleId"] = 99
        with patch.object(crawl, "page", page):
            self.assertEqual(crawl.discover("otonari_no_tenshi", errors), [])
        self.assertIn("unexpected manga title", errors[0]["error"])


class SeriesRunTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for target, name, value in ((crawl, "ROOT", self.root), (crawl, "STAGING", self.root / ".local/official"),
                                    (crawl.local, "REPO_ROOT", self.root), (crawl.time, "sleep", lambda _: None)):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.assets = [Asset("https://img.test/1.png", "https://pub.test/ch1", "manga_panel", "gangan_1", 1, "1-1"),
                       Asset("https://img.test/2.png", "https://pub.test/ch1", "manga_panel", "gangan_1", 2, "1-1"),
                       Asset("https://img.test/bad.png", "https://pub.test/ch1", "manga_panel", "gangan_1", 3, "1-1")]
        self.bodies = {"https://img.test/1.png": png_image((1, 2, 3)), "https://img.test/2.png": png_image((4, 5, 6)),
                       "https://img.test/bad.png": png_image(size=(100, 100))}

    def run_series(self, apply):
        with patch.object(crawl, "discover", lambda series, errors: list(self.assets)), \
                patch.object(crawl, "urlopen", lambda url, timeout: Response(self.bodies[url])), \
                patch("sys.stdout", new_callable=io.StringIO):
            return crawl.run_series("otonari_no_tenshi", apply)

    def test_dry_run_only_lists_candidates(self):
        result = self.run_series(False)
        self.assertEqual(len(result["candidates"]), 3)
        self.assertFalse((self.root / "data").exists())

    def test_apply_ingests_the_batch_and_writes_a_page_ordered_index(self):
        result = self.run_series(True)
        self.assertEqual(len(result["downloaded"]), 2)
        self.assertIn("too small", result["errors"][0]["error"])
        images = self.root / "data/sample/otonari_no_tenshi/images"
        with (images / "IMAGES_INDEX.csv").open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual([(r["chapter"], r["source_page_number"], r["media"]) for r in rows],
                         [("1-1", "1", "manga"), ("1-1", "2", "manga")])
        self.assertEqual({r["rights_basis"] for r in rows}, {"official_promo"})
        self.assertEqual(Path(self.run_series(True)["manifest"]), Path("data/sample/otonari_no_tenshi/images/IMAGES_MANIFEST.yaml"))
        with (images / "IMAGES_INDEX.csv").open(encoding="utf-8-sig", newline="") as stream:
            self.assertEqual(len(list(csv.DictReader(stream))), 2)

    def test_main_reports_a_series_without_downloads_as_a_failure(self):
        runs = {"roshidere": {"downloaded": []}, "otonari_no_tenshi": {"downloaded": [{}]}}
        with patch.object(crawl, "run_series", lambda series, apply: runs[series]), \
                patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(crawl.main(["--series", "otonari_no_tenshi"]), 0)
            self.assertEqual(crawl.main(["--apply"]), 1)
        saved = json.loads((self.root / ".local/official/result.json").read_text(encoding="utf-8"))
        self.assertEqual(len(saved["collections"]), 2)


if __name__ == "__main__":
    unittest.main()
