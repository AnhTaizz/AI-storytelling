import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import yaml

from tools.media_ingest import crawl_light_novel_art as art
from tools.media_ingest.crawl_light_novel_art import yen_art, kimdong_art


class PublisherArtworkIdentityTests(unittest.TestCase):
    def test_cover_selection_ignores_navigation_and_other_volumes(self):
        body = ('<h1>The Angel Next Door Spoils Me Rotten, Vol. 8.5 (light novel)</h1>'
                '<nav><img src="https://images.yenpress.com/other.jpg"></nav>'
                '<div class="book-cover-img"><img data-src="https://images.yenpress.com/cover.jpg"></div>'
                '<div class="related"><img src="https://images.yenpress.com/related.jpg"></div>').encode()
        result = yen_art(body, 'https://yenpress.com/titles/test')
        self.assertEqual((result.volume, result.url, result.role), ('8.5', 'https://images.yenpress.com/cover.jpg', 'book_cover'))

    def test_manga_or_another_series_cannot_be_labelled_as_ln(self):
        for title in ['The Angel Next Door Spoils Me Rotten, Vol. 1 (manga)', 'Another Series, Vol. 1 (light novel)']:
            with self.assertRaisesRegex(ValueError, 'book identity'):
                yen_art(('<h1>' + title + '</h1>').encode(), 'https://yenpress.com/titles/test')

    def test_ambiguous_cover_stops_selection(self):
        body = ('<h1>The Angel Next Door Spoils Me Rotten, Vol. 1 (light novel)</h1>'
                '<div class="book-cover-img"><img src="https://images.yenpress.com/a.jpg">'
                '<img src="https://images.yenpress.com/b.jpg"></div>').encode()
        with self.assertRaisesRegex(ValueError, 'ambiguous publisher cover'):
            yen_art(body, 'https://yenpress.com/titles/test')

    def test_volume_comes_from_variant_metadata_not_filename(self):
        url = 'https://bizweb.dktcdn.net/99-misleading-name.jpg'
        product = {'alias': 'tap-le-thien-su-nha-ben-light-novel', 'variants': [
            {'title': 'Tập 5.5 (2025)', 'image': {'src': url}}]}
        body = ('<script>const config={product:' + json.dumps(product) + '};</script>'
                '<div id="lightgallery"><img data-zoom="' + url + '">'
                '<img data-zoom="https://bizweb.dktcdn.net/2-unknown.jpg"></div>'
                '<aside><img data-zoom="https://bizweb.dktcdn.net/sidebar.jpg"></aside>').encode()
        arts = kimdong_art(body, 'https://nxbkimdong.com.vn/test')
        self.assertEqual(len(arts), 2)
        self.assertEqual(arts[0].volume, '5.5')
        self.assertEqual(arts[1].volume, '')
        self.assertEqual(arts[1].role, 'publisher_gallery')

    def test_different_product_metadata_is_rejected(self):
        body = b'<script>const x={product:{"alias":"unrelated","variants":[{}]}};</script>'
        with self.assertRaisesRegex(ValueError, 'LN product'):
            kimdong_art(body, 'https://nxbkimdong.com.vn/test')


def yen_page(volume, cover):
    return (f'<h1>The Angel Next Door Spoils Me Rotten, Vol. {volume} (light novel)</h1>'
            f'<div class="book-cover-img"><img src="{cover}"></div>').encode()


class Response:
    def __init__(self, url, data):
        self.url, self.data = url, data

    def read(self, limit):
        return self.data[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class PublisherFetchTests(unittest.TestCase):
    def test_requests_stay_on_publisher_hosts_and_retry_only_transient_errors(self):
        url = 'https://yenpress.com/titles/x'
        cases = (
            ('success after a transient error', [HTTPError(url, 503, 'busy', {}, None), Response(url, b'ok')], None),
            ('redirect outside the allowlist', [Response('https://elsewhere.example/x', b'x')], 'redirect outside'),
            ('oversized', [Response(url, b'x' * (30 * 1024 * 1024 + 1))], 'too large'),
            ('permanent error', [HTTPError(url, 404, 'gone', {}, None)], 'gone'),
            ('network down', [URLError('down')] * 3, 'down'),
        )
        for name, responses, error in cases:
            with self.subTest(name), patch.object(art, 'urlopen', side_effect=responses), patch.object(art.time, 'sleep'):
                if error:
                    with self.assertRaisesRegex(Exception, error):
                        art.fetch(url)
                else:
                    self.assertEqual(art.fetch(url), b'ok')
        for bad in ('http://yenpress.com/x', 'https://elsewhere.example/x'):
            with self.assertRaisesRegex(ValueError, 'allowlist'):
                art.fetch(bad)


class PublisherRunTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name, value in (('ROOT', self.root), ('STAGING', self.root / '.local/ln_art')):
            patcher = patch.object(art, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        second = '/titles/9781975319250-the-angel-next-door-spoils-me-rotten-vol-2-light-novel'
        broken = '/titles/9781975319267-the-angel-next-door-spoils-me-rotten-vol-3-light-novel'
        product = {'alias': 'tap-le-thien-su-nha-ben-light-novel', 'variants': [
            {'title': 'Tập 1', 'image': {'src': 'https://bizweb.dktcdn.net/v1.jpg'}}]}
        self.pages = {
            art.KIMDONG: ('<script>var p={product:' + json.dumps(product) + '};</script>'
                          '<div id="lightgallery"><img data-zoom="https://bizweb.dktcdn.net/v1.jpg"></div>').encode(),
            art.YEN: yen_page(1, 'https://images.yenpress.com/1.jpg')
            + f'<a href="{second}">2</a><a href="{broken}">3</a><a href="/titles/other">x</a>'.encode(),
            'https://yenpress.com' + second: yen_page(2, 'https://images.yenpress.com/2.jpg'),
            'https://yenpress.com' + broken: b'<h1>Unrelated</h1>',
        }
        from PIL import Image
        self.images = {}
        for index, url in enumerate(('https://bizweb.dktcdn.net/v1.jpg', 'https://images.yenpress.com/1.jpg',
                                     'https://images.yenpress.com/2.jpg')):
            buffer = io.BytesIO()
            Image.new('RGB', (400, 600), (index * 40, 10, 10)).save(buffer, 'PNG')
            self.images[url] = buffer.getvalue()

    def fetch(self, url):
        return self.pages.get(url) or self.images[url]

    def run_main(self, *argv):
        with patch.object(art, 'fetch', self.fetch), patch('sys.stdout', new_callable=io.StringIO):
            return art.main(list(argv))

    def test_discovery_follows_only_listed_ln_volumes(self):
        with patch.object(art, 'fetch', self.fetch):
            arts, errors = art.discover()
        self.assertEqual(sorted((a.publisher, a.volume) for a in arts),
                         [('kimdong', '1'), ('yenpress', '1'), ('yenpress', '2')])
        self.assertEqual(len(errors), 1)
        self.assertTrue((self.root / '.local/ln_art/sources/kimdong_ln.html').is_file())

    def test_apply_stores_reference_assets_and_a_rerun_adds_nothing(self):
        self.assertEqual(self.run_main(), 1)
        self.assertFalse((self.root / 'data').exists())
        self.assertEqual(self.run_main('--apply'), 1)
        images = self.root / 'data/sample/otonari_no_tenshi/images'
        manifest = yaml.safe_load((images / 'IMAGES_MANIFEST.yaml').read_text(encoding='utf-8'))
        self.assertEqual(len(manifest['images']), 3)
        self.assertEqual({r['usage_status'] for r in manifest['images']}, {'reference_only'})
        self.assertEqual(manifest['aggregate']['per_category']['other'], 3)
        self.assertTrue((images / 'reference_assets/light_novel_publishers/volume_002/yenpress/ASSET_MANIFEST.json').is_file())
        self.assertEqual(self.run_main('--apply'), 1)
        report = json.loads((images / 'LN_REFERENCE_ASSETS_INGEST_REPORT.json').read_text(encoding='utf-8'))
        self.assertEqual((report['new_images'], report['existing_images_preserved']), (0, 3))


if __name__ == '__main__':
    unittest.main()
