"""Collect reference-only Angel Next Door LN covers and publisher product artwork.

Only image URLs supplied by the publisher pages are downloaded. Volume labels
come from the product title/variant, never from guesses about image filenames.
Publisher galleries are not assumed to contain complete interior illustrations.
This tool never adds publisher covers to the scene-illustration collection.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import re
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.media_ingest import ingest_local_images as local
from tools.media_ingest.collection_io import aggregate, safe, save_report, write_csv
from tools.media_ingest.crawl_official_images import Asset, download, export_index

ROOT = Path(__file__).resolve().parents[2]
STAGING = ROOT / '.local/media_ingest/ln_art'
KIMDONG = 'https://nxbkimdong.com.vn/tap-le-thien-su-nha-ben-light-novel'
YEN = 'https://yenpress.com/titles/9781975319243-the-angel-next-door-spoils-me-rotten-vol-1-light-novel'
HOSTS = {'nxbkimdong.com.vn', 'yenpress.com', 'images.yenpress.com', 'bizweb.dktcdn.net'}
VOID = {'img', 'meta', 'link', 'input', 'br', 'hr', 'source', 'wbr', 'area', 'base', 'embed', 'param', 'track', 'col'}
_lock = threading.Lock()
_next_request = 0.0


def fetch(url):
    global _next_request
    if urlsplit(url).scheme != 'https' or urlsplit(url).hostname not in HOSTS:
        raise ValueError('URL outside publisher allowlist')
    for attempt in range(3):
        with _lock:
            time.sleep(max(0, _next_request - time.monotonic()))
            _next_request = time.monotonic() + 0.35
        try:
            with urlopen(Request(url, headers={'User-Agent': 'AI-storytelling-media-ingest/1.0'}), timeout=35) as response:
                if urlsplit(response.url).hostname not in HOSTS:
                    raise ValueError('redirect outside publisher allowlist')
                body = response.read(30 * 1024 * 1024 + 1)
            if len(body) > 30 * 1024 * 1024:
                raise ValueError('response too large')
            return body
        except (HTTPError, URLError, TimeoutError, ConnectionError) as error:
            if isinstance(error, HTTPError) and error.code not in {429, 500, 502, 503, 504}:
                raise
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


class Page(HTMLParser):
    def __init__(self, body):
        super().__init__(); self.stack = []; self.images = []; self.links = []; self.titles = []; self.heading = None
        self.feed(body.decode('utf-8'))

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'h1':
            self.heading = []
        if tag == 'img':
            self.images.append((a, tuple(self.stack)))
        if tag == 'a' and a.get('href'):
            self.links.append(a['href'])
        if tag not in VOID:
            self.stack.append((tag, a.get('id', ''), a.get('class', '')))

    def handle_endtag(self, tag):
        if tag == 'h1' and self.heading is not None:
            self.titles.append(''.join(self.heading).strip()); self.heading = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]; break

    def handle_data(self, text):
        if self.heading is not None:
            self.heading.append(text)


@dataclass(frozen=True)
class Art:
    url: str
    source_page: str
    publisher: str
    volume: str
    role: str
    source_sequence: int
    edition_label: str


def yen_art(body, source):
    page = Page(body)
    titles = set(page.titles)
    if len(titles) != 1:
        raise ValueError('ambiguous book title')
    title = next(iter(titles))
    match = re.fullmatch(r'The Angel Next Door Spoils Me Rotten, Vol\. (\d+(?:\.\d+)?) \(light novel\)', title)
    if not match:
        raise ValueError('unexpected LN book identity')
    images = [a.get('data-src') or a.get('src') for a, context in page.images
              if any('book-cover-img' in c.split() for _, _, c in context)]
    if len(images) != 1 or urlsplit(images[0]).hostname != 'images.yenpress.com':
        raise ValueError('missing or ambiguous publisher cover')
    return Art(images[0], source, 'yenpress', match[1], 'book_cover', 1, title)


def kimdong_art(body, source):
    text = body.decode('utf-8'); page = Page(body); products = []
    for match in re.finditer(r'\bproduct\s*[:=]\s*(\{)', text):
        try:
            obj, _ = json.JSONDecoder().raw_decode(text[match.start(1):])
        except ValueError:
            continue
        if obj.get('alias') == 'tap-le-thien-su-nha-ben-light-novel' and obj.get('variants'):
            products.append(obj)
    if not products or any(p != products[0] for p in products):
        raise ValueError('missing or conflicting LN product variants')
    labels = {}
    for variant in products[0]['variants']:
        label = variant['title']; match = re.match(r'Tập\s+(\d+(?:\.\d+)?)(?=\s|$)', label)
        if not match:
            raise ValueError('unrecognized volume label')
        url = variant.get('image', {}).get('src')
        if url:
            volume = str(int(match[1])) if '.' not in match[1] else match[1]
            labels[url] = (volume, label)
    result = []
    for attrs, context in page.images:
        if not any(node_id == 'lightgallery' for _, node_id, _ in context):
            continue
        url = attrs.get('data-zoom')
        if not url or urlsplit(url).hostname != 'bizweb.dktcdn.net':
            raise ValueError('missing original gallery image URL')
        volume, label = labels.get(url, ('', 'Publisher gallery; volume not established'))
        result.append(Art(url, source, 'kimdong', volume, 'publisher_product_art' if volume else 'publisher_gallery', len(result) + 1, label))
    if not result:
        raise ValueError('empty product gallery')
    return result


def discover():
    arts, errors = [], []
    for source, key in [(KIMDONG, 'kimdong_ln'), (YEN, 'yen_ln_v1')]:
        try:
            body = fetch(source)
            (STAGING / 'sources').mkdir(parents=True, exist_ok=True)
            (STAGING / 'sources' / (key + '.html')).write_bytes(body)
            if source == KIMDONG:
                arts.extend(kimdong_art(body, source)); continue
            urls = {urljoin(source, link) for link in Page(body).links
                    if re.fullmatch(r'/titles/\d+-the-angel-next-door-spoils-me-rotten-vol-\d+(?:-\d+)?-light-novel', link)}
            urls.add(source)
            for url in sorted(urls):
                try:
                    chapter = body if url == source else fetch(url)
                    arts.append(yen_art(chapter, url))
                    name = re.search(r'/titles/(\d+)', url)[1]
                    (STAGING / 'sources' / (name + '.html')).write_bytes(chapter)
                except Exception as e:
                    errors.append({'source': url, 'error': str(e)})
        except Exception as e:
            errors.append({'source': source, 'error': str(e)})
    return list({a.url: a for a in arts}.values()), errors


def folder(art):
    volume = ('volume_' + art.volume.replace('.', '_').zfill(3)) if art.volume else 'volume_unassigned'
    return f'reference_assets/light_novel_publishers/{volume}/{art.publisher}'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--apply', action='store_true'); args = parser.parse_args(argv)
    STAGING.mkdir(parents=True, exist_ok=True)
    arts, errors = discover()
    print('Discovered', len(arts), 'publisher LN artwork images', flush=True)
    save_report(STAGING / 'discovery.json', {'assets': [asdict(a) for a in arts], 'errors': errors})
    if not args.apply:
        return int(bool(errors))
    downloaded = []
    def get(art):
        return art, download(Asset(art.url, art.source_page, 'illustration', folder(art), art.source_sequence, volume=art.volume, media='light_novel'), STAGING / 'incoming', fetcher=fetch)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(get, art): art for art in arts}
        for future in as_completed(futures):
            try:
                downloaded.append(future.result())
                print('Downloaded', len(downloaded), '/', len(arts), flush=True)
            except Exception as e:
                errors.append({'asset': asdict(futures[future]), 'error': str(e)})
    out = ROOT / 'data/sample/otonari_no_tenshi/images'; manifest_path = out / 'IMAGES_MANIFEST.yaml'
    manifest = local._manifest(manifest_path, 'otonari_no_tenshi'); previous = copy.deepcopy(manifest['images'])
    number = local._highest_number(out, manifest, 'otn'); by_hash = {r['sha256']: r for r in manifest['images']}
    if manifest_path.exists():
        shutil.copyfile(manifest_path, STAGING / ('manifest_before_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.yaml'))
    out.mkdir(parents=True, exist_ok=True)
    added = []; art_rows = []
    for art, item in sorted(downloaded, key=lambda pair: (pair[0].publisher, pair[0].volume, pair[0].source_sequence)):
        record = by_hash.get(item['sha256'])
        if not record:
            relative = folder(art) + f'/{art.role}_{art.source_sequence:03d}' + Path(item['filename']).suffix
            dest = safe(out, relative); dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest() != item['sha256']:
                raise ValueError('destination conflict')
            if not dest.exists():
                shutil.copyfile(STAGING / 'incoming' / item['filename'], dest)
            number += 1
            record = {'image_id': f'otn-{number:05d}', 'path': relative, 'category': 'other', 'characters': [], 'emotion': None,
                      'volume': art.volume or None, 'chapter': None, 'width': item['width'], 'height': item['height'],
                      'byte_size': item['byte_size'], 'sha256': item['sha256'], 'source': art.source_page, 'rights_basis': 'official_promo',
                      'original_filename': Path(urlsplit(art.url).path).name, 'media': 'light_novel', 'asset_role': art.role,
                      'edition_label': art.edition_label, 'publisher': art.publisher, 'scene_mapping_status': 'unverified',
                      'usage_status': 'reference_only',
                      'ingested_at': datetime.now(timezone.utc).isoformat(),
                      'notes': f'Public publisher artwork; edition={art.edition_label}; media=light_novel; page={art.source_sequence}; image_url={art.url}'}
            manifest['images'].append(record); by_hash[item['sha256']] = record; added.append(record)
        art_rows.append({'image_id': record['image_id'], 'path': record['path'], 'volume': art.volume, 'publisher': art.publisher,
                         'asset_role': art.role, 'edition_label': art.edition_label, 'source_sequence': art.source_sequence,
                         'width': record['width'], 'height': record['height'], 'sha256': record['sha256'], 'source_page': art.source_page, 'image_url': art.url})
    if manifest['images'][:len(previous)] != previous:
        raise ValueError('existing image records changed')
    aggregate(manifest); local._atomic_manifest(manifest_path, manifest); export_index(manifest_path)
    write_csv(out / 'LN_REFERENCE_ASSETS_INDEX.csv', art_rows)
    groups = {}
    for row in art_rows:
        groups.setdefault(str(Path(row['path']).parent), []).append(row)
    for relative, rows in groups.items():
        save_report(safe(out, relative + '/ASSET_MANIFEST.json'), {'media': 'light_novel', 'usage_status': 'reference_only', 'assets': rows, 'chapter_mapping': 'unverified'})
    report = {'verified_at': datetime.now(timezone.utc).isoformat(), 'discovered': len(arts), 'downloaded': len(downloaded),
              'new_images': len(added), 'existing_images_preserved': len(previous), 'total_collection_images': len(manifest['images']),
              'all_new_files_hash_and_pixels_verified': True, 'indexed_assets': len(art_rows),
              'scope': 'Public publisher covers/product artwork; not a complete interior-illustration set', 'errors': errors}
    save_report(out / 'LN_REFERENCE_ASSETS_INGEST_REPORT.json', report); save_report(STAGING / 'result.json', report)
    print(json.dumps(report, ensure_ascii=True, indent=2), flush=True)
    return int(bool(errors))


if __name__ == '__main__':
    sys.exit(main())
