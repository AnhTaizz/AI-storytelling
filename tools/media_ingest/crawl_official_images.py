"""Collect public publisher images, then ingest into the local private collection.

Only URLs present in public source pages are fetched. No login, guessed page
numbers, image unscrambling, or access-control workarounds are used.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import time
import tempfile
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import urlopen

from PIL import Image
import yaml

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.media_ingest import ingest_local_images as local


ROOT = Path(__file__).resolve().parents[2]
GANGAN = "https://www.ganganonline.com"
POCKET = "https://pocket.shonenmagazine.com/article/entry/"
STAGING = ROOT / ".local/media_ingest/official"
OFFICIAL_SERIES = ("roshidere", "otonari_no_tenshi")
NOTE = "Public official image; video reuse clearance not established; LN scene mapping unverified."
MAX_BYTES = 30 * 1024 * 1024


@dataclass(frozen=True)
class Asset:
    url: str
    source_page: str
    category: str
    collection: str
    page: int | None = None
    chapter: str = ""
    volume: str = ""
    media: str = "manga"


class PageParser(HTMLParser):
    """Read article images only inside entry-content; ignore sidebar/ads."""

    def __init__(self):
        super().__init__()
        self.depth = 0
        self.article_images = []
        self.next_data = ""
        self.in_next_data = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div":
            if self.depth:
                self.depth += 1
            elif "entry-content" in attrs.get("class", "").split():
                self.depth = 1
        if tag == "img" and self.depth:
            src = attrs.get("src", "")
            parsed = urlsplit(src)
            if (parsed.hostname == "cdn-ak.f.st-hatena.com"
                    and parsed.path.startswith("/images/fotolife/m/magazine_pocket/")):
                self.article_images.append(src)
        if tag == "script" and attrs.get("id") == "__NEXT_DATA__":
            self.in_next_data = True

    def handle_endtag(self, tag):
        if tag == "div" and self.depth:
            self.depth -= 1
        if tag == "script":
            self.in_next_data = False

    def handle_data(self, data):
        if self.in_next_data:
            self.next_data += data


def fetch(url: str) -> bytes:
    if urlsplit(url).scheme != "https":
        raise ValueError("HTTPS is required")
    with urlopen(url, timeout=30) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("response exceeds 30 MiB")
    time.sleep(0.2)
    return data


def page(url: str) -> PageParser:
    parser = PageParser()
    parser.feed(fetch(url).decode("utf-8"))
    return parser


def gangan_pages(data: dict, source: str, title_id: int, chapter: str) -> list[Asset]:
    assets = []
    prefix = f"/secure/title/{title_id}/chapter/"
    for item in data.get("pages", []):
        image_url = item.get("image", {}).get("imageUrl", "")
        # Exclude extra_manga_page and linkImage cross-promotions.
        if not image_url.startswith(prefix) or "/manga_page/" not in image_url:
            continue
        assets.append(Asset(urljoin(GANGAN, image_url), source, "manga_panel",
                            f"gangan_{source.rsplit('/', 1)[-1]}", len(assets) + 1, chapter))
    return assets


def discover(series: str, errors: list[dict]) -> list[Asset]:
    assets = []
    if series == "roshidere":
        for slug, category, chapter in (
            ("russia_20240710_1", "manga_panel", "special-2024-07-10"),
            ("russia_20240701", "illustration", ""),
        ):
            source = POCKET + slug
            try:
                images = page(source).article_images
                if not images:
                    raise ValueError("no article images found; source layout may have changed")
                # First article image is a promotional heading/collage.
                for index, url in enumerate(images[1:], 1):
                    assets.append(Asset(url, source, category, slug, index, chapter))
            except Exception as error:
                errors.append({"url": source, "error": str(error)})
        source = "https://roshidere.com/"
        try:
            html = fetch(source).decode("utf-8")
            for relative in dict.fromkeys(re.findall(r'core_sys/images/main/home/kv\d+\.jpg', html)):
                assets.append(Asset(urljoin(source, relative), source, "illustration",
                                    "anime_key_visuals", media="anime"))
        except Exception as error:
            errors.append({"url": source, "error": str(error)})
    else:
        source = GANGAN + "/title/1480"
        try:
            title = json.loads(page(source).next_data)["props"]["pageProps"]["data"]["default"]
            if title.get("titleId") != 1480:
                raise ValueError("unexpected manga title ID")
            for section, media in (("volumeSections", "manga"), ("originalSections", "light_novel")):
                for volume in title.get(section, {}).get("volumes", []):
                    assets.append(Asset(urljoin(GANGAN, volume["imageUrl"]), source,
                                        "illustration", section, media=media))
            # Only chapters currently linked as readable on the public title page.
            chapters = [c for c in title.get("chapters", [])
                        if not c.get("status") and not c.get("appLaunchUrl")]
            for chapter in sorted(chapters, key=lambda c: c["id"]):
                chapter_url = source + "/chapter/" + str(chapter["id"])
                try:
                    data = json.loads(page(chapter_url).next_data)["props"]["pageProps"]["data"]
                    if data.get("titleDetailUrl") != "/title/1480":
                        raise ValueError("chapter belongs to a different title")
                    assets.extend(gangan_pages(data, chapter_url, 1480, data["chapterName"]))
                except Exception as error:
                    errors.append({"url": chapter_url, "error": str(error)})
        except Exception as error:
            errors.append({"url": source, "error": str(error)})
    return list({asset.url: asset for asset in assets}.values())


def download(asset: Asset, folder: Path, *, fetcher=fetch) -> dict:
    data = fetcher(asset.url)
    with Image.open(io.BytesIO(data)) as image:
        image.verify()
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        width, height = image.size
        extension = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp", "GIF": ".gif"}[image.format]
    if min(width, height) < 300:
        raise ValueError(f"image too small: {width}x{height}")
    digest = hashlib.sha256(data).hexdigest()
    # Stable names allow resuming without creating duplicate staging files.
    filename = asset.collection + "/" + digest + extension
    target = folder / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".download-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
    return {**asdict(asset), "filename": filename, "sha256": digest,
            "width": width, "height": height, "byte_size": len(data)}


def export_index(manifest_path: Path) -> Path:
    """Keep every manifest image searchable in source chapter/page order."""
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    fields = ("image_id", "path", "category", "media", "chapter", "source_page_number",
              "width", "height", "source_page", "source_image_url", "rights_basis", "notes")
    rows = []
    for record in manifest["images"]:
        notes = record.get("notes") or ""
        meta = re.search(r"media=([^;]+); page=(None|\d+); image_url=(.+)$", notes)
        rows.append({"image_id": record["image_id"], "path": record["path"],
                     "category": record["category"], "media": meta[1] if meta else "",
                     "chapter": record.get("chapter") or "",
                     "source_page_number": int(meta[2]) if meta and meta[2] != "None" else "",
                     "width": record["width"], "height": record["height"],
                     "source_page": record.get("source", ""),
                     "source_image_url": meta[3] if meta else "",
                     "rights_basis": record["rights_basis"], "notes": notes})
    rows.sort(key=lambda r: (r["category"] != "manga_panel",
                            tuple(map(int, re.findall(r"\d+", r["chapter"]))),
                            r["source_page"], r["source_page_number"] or 0, r["image_id"]))
    target = manifest_path.with_name("IMAGES_INDEX.csv")
    with target.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return target


def run_series(series: str, apply: bool) -> dict:
    errors = []
    assets = discover(series, errors)
    result = {"series": series, "discovered": len(assets), "downloaded": [], "errors": errors}
    print(f"{series}: discovered {len(assets)} images", flush=True)
    if not apply:
        result["candidates"] = [asdict(a) for a in assets]
        return result
    folder = STAGING / series
    folder.mkdir(parents=True, exist_ok=True)
    for index, asset in enumerate(assets, 1):
        try:
            result["downloaded"].append(download(asset, folder / "incoming"))
            print(f"{series}: downloaded {index}/{len(assets)}", flush=True)
        except Exception as error:
            errors.append({"url": asset.url, "source_page": asset.source_page, "error": str(error)})
            print(f"{series}: skipped {index}: {error}", flush=True)
        (folder / "crawl_report.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    if not result["downloaded"]:
        return result
    labels = folder / "labels.csv"
    with labels.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=local.CSV_FIELDS)
        writer.writeheader()
        for item in result["downloaded"]:
            writer.writerow({"filename": item["filename"], "category": item["category"],
                             "chapter": item["chapter"], "volume": item["volume"],
                             "source": item["source_page"], "rights_basis": "official_promo",
                             "notes": f"{NOTE} media={item['media']}; page={item['page']}; image_url={item['url']}"})
    # Ingest only this successful batch; do not sweep stale/unlabelled staging files.
    incoming = folder / "incoming"
    batch = folder / "batch"
    batch.mkdir(exist_ok=True)
    import shutil
    import tempfile
    with tempfile.TemporaryDirectory(prefix="run-", dir=batch) as temporary:
        for item in result["downloaded"]:
            target = Path(temporary) / item["filename"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(incoming / item["filename"], target)
        code = local.main(["--series", series, "--incoming", temporary,
                           "--labels", str(labels), "--apply"])
        if code:
            raise RuntimeError(f"local ingest failed: exit {code}")
    manifest = ROOT / "data/sample" / series / "images/IMAGES_MANIFEST.yaml"
    result["manifest"] = str(manifest.relative_to(ROOT))
    result["index"] = str(export_index(manifest).relative_to(ROOT))
    (folder / "crawl_report.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--series", choices=["all", *OFFICIAL_SERIES], default="all")
    parser.add_argument("--apply", action="store_true", help="Download and ingest; default only discovers URLs")
    args = parser.parse_args(argv)
    series = list(OFFICIAL_SERIES) if args.series == "all" else [args.series]
    result = {"started_at": datetime.now(timezone.utc).isoformat(), "applied": args.apply,
              "collections": [run_series(s, args.apply) for s in series]}
    if args.apply:
        STAGING.mkdir(parents=True, exist_ok=True)
        (STAGING / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        print(json.dumps(result, indent=2, ensure_ascii=True))
    return 1 if any(not c.get("downloaded") for c in result["collections"]) and args.apply else 0


if __name__ == "__main__":
    raise SystemExit(main())
