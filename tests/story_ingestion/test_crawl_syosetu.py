"""Offline checks for episode identity and lossless local-source caching."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from tools.story_ingestion import crawl_syosetu as crawl


def episode(number=31, content=None):
    content = content or '<p id="L1">　本文。</p><p id="L2"><br></p><p id="L3">次。</p>'
    return (f'<meta property="og:url" content="{crawl.SOURCE}{number}/">'
            f'<div class="p-novel__number">{number}/327</div>'
            f'<h1 class="p-novel__title">{number}　題</h1>'
            '<div class="js-novel-text js-novel-text--preface"><p>前書き</p></div>'
            f'<div class="js-novel-text p-novel__text">{content}</div>'
            '<div class="js-novel-text js-novel-text--afterword"><p>後書き</p></div>'
            '<p>広告</p>').encode('utf-8')


class ChapterIdentityTests(unittest.TestCase):
    def test_main_body_order_ruby_and_notes(self):
        body = episode(content='<p>　<ruby>本文<rt>ほんぶん</rt><rp>）</rp></ruby>。</p><p><br></p><p>次&amp;次<br>終。</p>')
        text, meta = crawl.parse_episode(body, 31, '31　題')
        self.assertEqual(text.decode(), '31　題\n\n　本文。\n\n\n次&次\n終。\n')
        self.assertEqual(meta['body_paragraph_count'], 3)
        self.assertEqual([m['paragraphs'] for m in meta['paratext']], [['前書き'], ['後書き']])
        self.assertNotIn('広告', text.decode())

    def test_wrong_episode_url_rejected(self):
        with self.assertRaisesRegex(ValueError, 'canonical URL mismatch'):
            crawl.parse_episode(episode(32), 31, '32　題')

    def test_index_title_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError, 'title differs'):
            crawl.parse_episode(episode(), 31, '別の章')

    def test_display_number_must_agree_with_url(self):
        body = episode().replace(b'31/327', b'32/327')
        with self.assertRaisesRegex(ValueError, 'number mismatch'):
            crawl.parse_episode(body, 31, '31　題')

    def test_empty_or_duplicate_main_body_rejected(self):
        for body in [episode(content='<p><br></p>'), episode() + b'<div class="js-novel-text"><p>extra</p></div>']:
            with self.assertRaises(ValueError):
                crawl.parse_episode(body, 31, '31　題')

    def test_inline_image_is_not_silently_lost(self):
        with self.assertRaisesRegex(ValueError, 'illustration'):
            crawl.parse_episode(episode(content='<p>Text<img src="x.jpg"></p>'), 31, '31　題')

    def test_index_excludes_other_works_and_non_episode_links(self):
        body = ('<h1 class="p-novel__title">題</h1>'
                '<a class="p-eplist__subtitle" href="/n8440fe/31/">31　題</a>'
                '<a class="p-eplist__subtitle" href="/n0000xx/99/">Other</a>'
                '<a href="/n8440fe/32/">not an episode entry</a>'
                '<a href="/n8440fe/?p=4">Last</a>').encode()
        entries, pages = crawl.parse_index(body, crawl.SOURCE)
        self.assertEqual(set(entries), {31})
        self.assertEqual(pages, {crawl.SOURCE + '?p=4'})


class CachedSourceTests(unittest.TestCase):
    def test_resume_validates_source_and_does_not_fetch_or_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(crawl, 'ROOT', root), patch.object(crawl, 'CORPUS', root / 'corpus'), patch.object(crawl, 'STAGING', root / 'stage'):
                entry = {'chapter': 31, 'title': '31　題', 'source_url': crawl.SOURCE + '31/'}
                metadata = crawl.ingest_one(entry, lambda url: episode())
                path = root / 'corpus/raw/chapter_031.txt'
                before = path.stat().st_mtime_ns
                def no_fetch(url):
                    self.fail('a verified cached chapter should not be fetched')
                self.assertEqual(crawl.ingest_one(entry, no_fetch), metadata)
                self.assertEqual(path.stat().st_mtime_ns, before)
                path.write_text('damaged', encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'cached chapter'):
                    crawl.ingest_one(entry, no_fetch)
                self.assertEqual(path.read_text(), 'damaged')

    def test_existing_unproven_text_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(crawl, 'CORPUS', root):
                path = root / 'raw/chapter_031.txt'; path.parent.mkdir()
                path.write_bytes(b'existing text')
                with self.assertRaisesRegex(ValueError, 'refusing to overwrite'):
                    crawl.ingest_one({'chapter': 31}, lambda url: episode())
                self.assertEqual(path.read_bytes(), b'existing text')


def index(numbers, pages=(), title='題'):
    links = ''.join(f'<a class="p-eplist__subtitle" href="/n8440fe/{n}/">{n}　{title}</a>' for n in numbers)
    more = ''.join(f'<a href="/n8440fe/?p={p}">{p}</a>' for p in pages)
    return f'<h1 class="p-novel__title">題</h1>{links}{more}'.encode('utf-8')


class Response:
    def __init__(self, url, data):
        self.url, self.data = url, data

    def read(self, limit):
        return self.data[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class CorpusRunTests(unittest.TestCase):
    """The whole run against a temporary corpus with one historical chapter and a fake source."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        corpus = self.root / 'corpus'
        (corpus / 'raw').mkdir(parents=True)
        first = '1　題\n\n本文。\n'.encode('utf-8')
        (corpus / 'raw/chapter_001.txt').write_bytes(first)
        (corpus / 'CORPUS_30CH_LOCAL_MANIFEST.yaml').write_text(json.dumps({'chapters': [
            {'chapter_number': 1, 'filename': 'chapter_001.txt', 'sha256': crawl.digest(first)}]}), encoding='utf-8')
        (corpus / 'LIGHT_NOVEL_SOURCE_MANIFEST_SAMPLE_V0.yaml').write_text(json.dumps({
            'contract_version': 'v0', 'story_id': 'story', 'stream_id': 'stream', 'source_language': 'ja',
            'documents': [{'order': 1, 'document_id': 'doc-1'}]}), encoding='utf-8')
        for name, value in (('ROOT', self.root), ('CORPUS', corpus), ('STAGING', self.root / 'stage')):
            patcher = patch.object(crawl, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.corpus = corpus
        self.pages = {crawl.SOURCE: index([1], [2]), crawl.SOURCE + '?p=2': index([2]),
                      crawl.SOURCE + '2/': episode(2)}

    def run_main(self, *argv):
        with patch.object(crawl, 'Fetcher', lambda: (lambda url: self.pages[url])), \
                patch('sys.stdout', new_callable=io.StringIO):
            return crawl.main(list(argv))

    def test_paginated_index_is_merged_and_saved(self):
        episodes = crawl.discover(lambda url: self.pages[url])
        self.assertEqual(sorted(episodes), [1, 2])
        self.assertTrue((self.root / 'stage/index_2.html').is_file())
        saved = json.loads((self.root / 'stage/source_index.json').read_text(encoding='utf-8'))
        self.assertEqual(len(saved['episodes']), 2)

    def test_inconsistent_indexes_are_rejected(self):
        cases = (('missing episode numbers', {crawl.SOURCE: index([1, 3])}),
                 ('conflicting', {crawl.SOURCE: index([1], [2]), crawl.SOURCE + '?p=2': index([1], title='別')}))
        for message, pages in cases:
            with self.subTest(message), self.assertRaisesRegex(ValueError, message):
                crawl.discover(lambda url: pages[url])

    def test_apply_adds_missing_chapters_and_writes_manifests(self):
        self.assertEqual(self.run_main(), 0)
        self.assertFalse((self.corpus / 'raw/chapter_002.txt').exists())
        self.assertEqual(self.run_main('--apply'), 0)
        self.assertEqual((self.corpus / 'raw/chapter_002.txt').read_text(encoding='utf-8').splitlines()[0], '2　題')
        manifest = json.loads((self.corpus / 'LIGHT_NOVEL_SOURCE_MANIFEST_LATEST_LOCAL.json').read_text(encoding='utf-8'))
        self.assertEqual([d['order'] for d in manifest['documents']], [1, 2])
        self.assertEqual(manifest['documents'][0]['document_id'], 'doc-1')
        self.assertTrue(manifest['documents'][1]['document_id'].startswith('srcdoc-'))
        report = json.loads((self.corpus / 'syosetu_local/INGEST_REPORT.json').read_text(encoding='utf-8'))
        self.assertEqual((report['chapter_count'], report['added_chapters'], report['preserved_chapters']), (2, 1, 1))
        self.assertTrue((self.corpus / 'syosetu_local/CHAPTERS_INDEX.csv').is_file())

    def test_failures_stop_before_the_manifests_are_written(self):
        self.pages[crawl.SOURCE + '2/'] = episode(3)
        self.assertEqual(self.run_main('--apply'), 1)
        batch = json.loads((self.root / 'stage/batch_report.json').read_text(encoding='utf-8'))
        self.assertEqual([e['chapter'] for e in batch['errors']], [2])
        self.assertFalse((self.corpus / 'LIGHT_NOVEL_SOURCE_MANIFEST_LATEST_LOCAL.json').exists())

    def test_a_source_index_that_changes_during_the_crawl_is_rejected(self):
        calls = []

        def fetch(url):
            if url == crawl.SOURCE:
                calls.append(url)
                return index([1], [2]) if len(calls) == 1 else index([1, 2, 3])
            return self.pages[url]

        with patch.object(crawl, 'Fetcher', lambda: fetch), patch('sys.stdout', new_callable=io.StringIO), \
                self.assertRaisesRegex(ValueError, 'index changed'):
            crawl.main(['--apply'])

    def test_a_changed_historical_chapter_stops_the_run(self):
        (self.corpus / 'raw/chapter_001.txt').write_text('edited', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'historical chapter differs'):
            self.run_main()


class FetcherTests(unittest.TestCase):
    def test_requests_stay_on_the_work_and_retry_only_transient_errors(self):
        url = crawl.SOURCE + '1/'
        busy = HTTPError(url, 503, 'busy', {}, None)
        cases = (
            ('success after a transient error', [busy, Response(url, b'ok')], b'ok', None),
            ('redirect away', [Response(crawl.SOURCE, b'x')], None, 'redirected'),
            ('oversized', [Response(url, b'x' * (8 * 1024 * 1024 + 1))], None, 'size limit'),
            ('permanent error', [HTTPError(url, 404, 'gone', {}, None)], None, 'gone'),
            ('network down', [URLError('down')] * 4, None, 'down'),
        )
        for name, responses, expected, error in cases:
            with self.subTest(name), patch.object(crawl, 'urlopen', side_effect=responses), \
                    patch.object(crawl.time, 'sleep'):
                fetch = crawl.Fetcher(interval=0)
                if error:
                    with self.assertRaisesRegex(Exception, error):
                        fetch(url)
                else:
                    self.assertEqual(fetch(url), expected)
        with self.assertRaisesRegex(ValueError, 'outside the requested work'):
            crawl.Fetcher()('https://ncode.syosetu.com/n0000xx/1/')


if __name__ == '__main__':
    unittest.main()
