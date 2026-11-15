"""Behavioural contract for retrieval_v0 and its retrieve CLI."""

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

from tools.story_benchmark.bm25_lexical_v1 import jp_simple_lexical_v1
from tools.story_pipeline.source import Chapter, Passage, StoryScope
from tools.story_retrieval.retrieval_v0 import (
    E5_LARGE_MODEL, E5_LARGE_REVISION, E5_SMALL_MODEL, E5_SMALL_REVISION, RETRIEVER_NAMES,
    Bm25RetrieverV0, DenseE5RetrieverV0, HybridRrfRetrieverV0, RetrievalRequest, StoryCorpus,
    build_corpus, make_retriever, natural_key, passage_chapter, result_to_dict, retrieve,
)
from tools.story_retrieval.retrieve import DEFAULT_MANIFEST, REPO, main


def character_encoder(texts):
    return [[text.split(': ', 1)[1].casefold().count(c) for c in 'abcdefghijklmnopqrstuvwxyz']
            for text in texts]


class CountingEncoder:
    """Record batches while retaining the deterministic character-vector fixture."""

    def __init__(self):
        self.calls = []

    def __call__(self, texts):
        self.calls.append(list(texts))
        return character_encoder(texts)

    @property
    def passages(self):
        return [text for batch in self.calls for text in batch if text.startswith('passage: ')]


class RankedRetriever:
    """A component with prescribed rankings, including deliberately unsafe candidates."""

    name = 'ranked_test'
    version = '0'

    def __init__(self, ranking):
        self.ranking = ranking
        self.index_calls = 0
        self.depths = []

    def index(self, passages):
        self.index_calls += 1

    def search(self, query, allowed_ids, k):
        self.depths.append(k)
        return self.ranking[:k]


class RetrievalV0Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = build_corpus(DEFAULT_MANIFEST, 5)
        schema = json.loads((REPO / 'schemas/story_retrieval/retrieval_result_v0.schema.json')
                            .read_text(encoding='utf-8'))
        Draft202012Validator.check_schema(schema)
        cls.validator = Draft202012Validator(schema)

    def test_story_isolation_api_cli_cache_and_deletion(self):
        """Same names/IDs stay in their story through reuse, CLI and warm caches."""
        import yaml

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpora = {}
            for story, text in [('story-a', 'Mira apple'), ('story-b', 'Mira banana')]:
                directory = root / story
                directory.mkdir()
                data = text.encode('utf-8')
                (directory / 'chapter.txt').write_bytes(data)
                manifest = dict(contract_version='LIGHT_NOVEL_INGESTION/v0', story_id=story,
                                stream_id='stream-synthetic', source_language='ja', documents=[dict(
                                    document_id='doc-synthetic', order=1, path='chapter.txt',
                                    expected_sha256=hashlib.sha256(data).hexdigest())])
                path = directory / 'manifest.yaml'
                path.write_text(yaml.safe_dump(manifest), encoding='utf-8')
                corpora[story] = build_corpus(path, 1)
                self.assertEqual((corpora[story].story_id, corpora[story].source_language), (story, 'ja'))
            for kind in ['bm25', 'dense', 'hybrid']:
                with self.subTest(kind=kind):
                    cache = root / ('cache-' + kind)
                    encoder = CountingEncoder()
                    dense = DenseE5RetrieverV0(encoder, cache_dir=cache)
                    retriever = (Bm25RetrieverV0() if kind == 'bm25' else dense if kind == 'dense'
                                 else HybridRrfRetrieverV0([Bm25RetrieverV0(), dense]))
                    for story in ['story-a', 'story-b', 'story-a']:
                        corpus = corpora[story]
                        request = RetrievalRequest('Mira', 1, story_id=story)
                        hits = retrieve(request, retriever, corpus)
                        self.assertEqual([h.text for h in hits], [corpus[0].text])
                        with patch('tools.story_retrieval.retrieve.make_retriever', return_value=retriever):
                            with redirect_stdout(io.StringIO()) as output:
                                self.assertEqual(main(['--manifest', str(root / story / 'manifest.yaml'),
                                                       '--story-id', story, '--cutoff', '1', '--query',
                                                       'Mira', '--json']), 0)
                            self.assertEqual([h['text'] for h in json.loads(output.getvalue())['hits']],
                                             [corpus[0].text])
                        with self.assertRaisesRegex(ValueError, 'does not match'):
                            retrieve(RetrievalRequest('Mira', 1, story_id='other'), retriever, corpus)
                    with redirect_stderr(io.StringIO()):
                        self.assertEqual(main(['--manifest', str(root / 'story-a/manifest.yaml'),
                                               '--story-id', 'story-b', '--cutoff', '1', '--query', 'Mira']), 2)
                    if kind != 'bm25':
                        self.assertEqual(set(p.name for p in cache.iterdir()), {'story-a', 'story-b'})
                        self.assertEqual(encoder.passages, ['passage: Mira apple', 'passage: Mira banana'])
                        survivor = next((cache / 'story-b').glob('*.json'))
                        before = survivor.read_bytes()
                        target = (cache / 'story-a').resolve()
                        self.assertEqual(target.parent, cache.resolve())
                        shutil.rmtree(target)
                        self.assertEqual(survivor.read_bytes(), before)
                        warm = CountingEncoder()
                        hits = retrieve(RetrievalRequest('Mira', 1, story_id='story-b'),
                                        DenseE5RetrieverV0(warm, cache_dir=cache), corpora['story-b'])
                        self.assertEqual([h.text for h in hits], ['Mira banana'])
                        self.assertEqual(warm.passages, [])
            # Even identical text/IDs in distinct stories must not share passage-derived data.
            encoder = CountingEncoder()
            dense = DenseE5RetrieverV0(encoder, cache_dir=root / 'identical')
            component = RankedRetriever([('1.1', 1)])
            hybrid = HybridRrfRetrieverV0([component, dense])
            for story in ['story-a', 'story-b']:
                corpus = StoryCorpus(corpora['story-a'], story_id=story, source_language='ja')
                retrieve(RetrievalRequest('Mira', 1, story_id=story), hybrid, corpus)
            self.assertEqual(component.index_calls, 2)
            self.assertEqual(encoder.passages, ['passage: Mira apple'] * 2)

    def test_story_identity_validation_and_tokenizer_selection(self):
        """Unsafe IDs fail; ja stays frozen, ko/zh use bigrams, dense accepts any language."""
        for story in ['', '.', '..', '../a', 'a/b', 'a\\b', 'C:bad', 'NUL', 'con.txt', 'x.', 'a b']:
            with self.subTest(story=story), self.assertRaisesRegex(ValueError, 'safe single path'):
                StoryCorpus([], story_id=story, source_language='ja')
        retriever = Bm25RetrieverV0()
        for language, text, query, match in [('ja', '日本語 Mira', '日本', True),
                                             ('ko', '미라의 사과 Mira', '미라', True),
                                             ('zh', '米拉吃苹果 Mira', '苹果', True),
                                             ('unknown', 'Mira', 'Mira', False),
                                             ('en', 'Mira', 'Mira', False)]:
            with self.subTest(language=language):
                corpus = StoryCorpus([Passage('1.1', text)], story_id='story', source_language=language)
                request = RetrievalRequest(query, 1, story_id='story')
                if match:
                    self.assertEqual([h.passage_id for h in retrieve(request, retriever, corpus)], ['1.1'])
                    if language == 'ja':
                        legacy = retrieve(RetrievalRequest(query, 1), Bm25RetrieverV0(), list(corpus))
                        self.assertEqual(retrieve(request, retriever, corpus), legacy)
                else:
                    with self.assertRaisesRegex(ValueError, 'source_language'):
                        retrieve(request, retriever, corpus)
                self.assertTrue(retrieve(RetrievalRequest('Mira', 1),
                                         DenseE5RetrieverV0(character_encoder), corpus))
        with self.assertRaisesRegex(ValueError, 'safe single path'):
            retrieve(RetrievalRequest('Mira', 1, story_id='../a'), retriever, self.corpus)

    def test_spoiler_boundary_and_narrower_window(self):
        """All retrievers filter a later exact match, even with an over-broad corpus."""
        passages = [Passage('1.1', 'apple'), Passage('2.1', 'banana'), Passage('3.1', 'secret banana')]
        factories = [Bm25RetrieverV0, lambda: DenseE5RetrieverV0(character_encoder),
                     lambda: HybridRrfRetrieverV0([Bm25RetrieverV0(), DenseE5RetrieverV0(character_encoder)])]
        for factory in factories:
            retriever = factory()
            with self.subTest(retriever=retriever.name):
                hits = retrieve(RetrievalRequest('secret banana', 2), retriever, passages)
                self.assertTrue(hits)
                self.assertTrue(all(h.chapter <= 2 for h in hits))
                window_hits = retrieve(RetrievalRequest('apple banana', 2, chapters=(2, 2)),
                                       retriever, passages)
                self.assertEqual([h.passage_id for h in window_hits], ['2.1'])

    def test_invalid_requests(self):
        """Invalid query, cutoff, depth and windows fail before search."""
        cases = [RetrievalRequest('q', 2, chapters=window) for window in [(1, 3), (2, 1), (0, 1)]]
        cases += [RetrievalRequest('q', 2, k=0), RetrievalRequest(' \n ', 2), RetrievalRequest('q', 0)]
        for request in cases:
            with self.subTest(request=request), self.assertRaises(ValueError):
                retrieve(request, Bm25RetrieverV0(), self.corpus)

    def test_corpus_loading_and_explicit_boundary_check(self):
        """The real loader bounds chapters; an invalid loader result fails explicitly."""
        actual = build_corpus(DEFAULT_MANIFEST, 2)
        self.assertEqual({passage_chapter(p.passage_id) for p in actual}, {1, 2})
        with self.assertRaises(ValueError):
            build_corpus(DEFAULT_MANIFEST, 0)
        chapters = tuple(Chapter(n, str(n), '', (Passage(f'{n}.1', 'text'),)) for n in [2, 1])
        with patch('tools.story_retrieval.retrieval_v0.load_scope',
                   return_value=StoryScope('s', 'ja', chapters)) as loader:
            self.assertEqual([p.passage_id for p in build_corpus('manifest', 2, 'root')], ['1.1', '2.1'])
            loader.assert_called_once_with('manifest', (1, 2), 'root')
            with self.assertRaises(RuntimeError):
                build_corpus('manifest', 1)

    def test_natural_order_determinism_and_zero_scores(self):
        """Tie-breaking happens before truncation; repeated indexing preserves scores."""
        passages = [Passage('1.10', 'match'), Passage('1.2', 'match')]
        retriever = Bm25RetrieverV0()
        request = RetrievalRequest('match', 1)
        hits = retrieve(request, retriever, passages)
        self.assertEqual([h.passage_id for h in hits], ['1.2', '1.10'])
        with patch('tools.story_retrieval.retrieval_v0.BM25LexicalV1',
                   side_effect=AssertionError('identical corpus must reuse its index')):
            self.assertEqual(hits, retrieve(request, retriever, list(passages)))
        self.assertEqual(retrieve(RetrievalRequest('match', 1, k=1), retriever, passages), hits[:1])
        self.assertEqual(retrieve(RetrievalRequest('unmatched', 1), retriever, passages), [])
        for ids, expected in [(['1.10', '1.2', '2.1'], ['1.2', '1.10', '2.1']),
                              (['ch002_c0010', 'ch002_c0002', 'ch010_c0001'],
                               ['ch002_c0002', 'ch002_c0010', 'ch010_c0001']),
                              (['a', '10', '2', '02', ''], ['', '02', '2', '10', 'a'])]:
            with self.subTest(ids=ids):
                self.assertEqual(sorted(ids, key=natural_key), expected)

    def test_defensive_filter_and_ranking(self):
        """Untrusted candidates cannot bypass eligibility, positive scores, or ordering."""
        retriever = RankedRetriever([('3.1', 100), ('missing', 50), ('1.10', 2),
                                     ('1.2', 2), ('2.1', 0), ('1.3', -1)])
        passages = [Passage(pid, 'text') for pid in ['1.2', '1.3', '1.10', '2.1', '3.1']]
        hits = retrieve(RetrievalRequest('q', 2, k=4), retriever, passages)
        self.assertEqual([(h.passage_id, h.rank) for h in hits], [('1.2', 1), ('1.10', 2)])
        result = result_to_dict(RetrievalRequest('q', 2), retriever, passages, hits)
        self.assertEqual(result['corpus_chapters'], {'first': 1, 'last': 2})
        empty = result_to_dict(RetrievalRequest('q', 2), retriever, [], [])
        self.assertEqual(empty['corpus_chapters'], {'first': None, 'last': None})
        self.validator.validate(empty)

    def test_tokenizer_scripts_and_sample_japanese_retrieval(self):
        """Frozen tokenizer keeps Vietnamese and Hangul words, and Japanese character ngrams."""
        for text, expected in [('ＦＯＯ Bar 123!', ['foo', 'bar', '123']),
                               ('TIẾNG Việt, cà-phê', ['tiếng', 'việt', 'cà', 'phê']),
                               ('한국어 단어!', ['한국어', '단어']),
                               ('日本語', ['日', '本', '日本', '語', '本語']),
                               ('あい カキ', ['あ', 'い', 'あい', 'カ', 'キ', 'カキ'])]:
            with self.subTest(text=text):
                self.assertEqual(jp_simple_lexical_v1(text), expected)
        hits = retrieve(RetrievalRequest('梅が入ったお粥 水分量', 3, k=3),
                        Bm25RetrieverV0(), self.corpus)
        self.assertIn('3.79', [h.passage_id for h in hits])

    def test_schema_and_cli_json_match_api(self):
        """JSON request echo, metadata and hits round-trip and validate against the schema."""
        for chapters in [None, (2, 3)]:
            with self.subTest(chapters=chapters):
                request = RetrievalRequest('お粥 梅', 3, 3, chapters)
                passages = build_corpus(DEFAULT_MANIFEST, 3)
                retriever = Bm25RetrieverV0()
                expected = result_to_dict(request, retriever, passages, retrieve(request, retriever, passages))
                args = ['--cutoff', '3', '--query', request.query, '--k', '3', '--json',
                        '--manifest', str(DEFAULT_MANIFEST), '--source-root', str(DEFAULT_MANIFEST.parent)]
                if chapters:
                    args += ['--chapters', '2-3']
                output = io.StringIO()
                with redirect_stdout(output):
                    code = main(args)
                self.assertEqual(code, 0)
                actual = json.loads(output.getvalue())
                self.assertEqual(actual, expected)
                self.validator.validate(actual)

    def test_cli_text_errors_help_and_windows_utf8(self):
        """Text snippets are single lines, errors return 2, and native stdout uses UTF-8."""
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['--cutoff', '1', '--query', 'ブランコ', '--k', '1']), 0)
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        self.assertRegex(output.getvalue(), r'^1\t1\.\d+\t[0-9.]+\t')
        with redirect_stdout(io.StringIO()) as empty_output:
            self.assertEqual(main(['--cutoff', '1', '--query', 'unmatchedword']), 0)
            self.assertEqual(empty_output.getvalue(), '')
        for args in [['--cutoff', '2', '--query', 'q', '--chapters', '1-3'],
                     ['--cutoff', '1', '--query', 'q', '--chapters', 'bad'],
                     ['--cutoff', '1', '--query', 'q', '--source-root', str(REPO)],
                     ['--cutoff', '1', '--query', 'q', '--k', 'bad']]:
            with self.subTest(args=args), redirect_stderr(io.StringIO()) as error:
                self.assertEqual(main(args), 2)
                self.assertTrue(error.getvalue())
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--help']), 0)
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1', PYTHONIOENCODING='ascii')
        process = subprocess.run([sys.executable, '-m', 'tools.story_retrieval.retrieve', '--cutoff', '1',
                                  '--query', 'ブランコ', '--json'], cwd=REPO, env=env, capture_output=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout.decode('utf-8'))['request']['query'], 'ブランコ')
        buffer = io.BytesIO()
        stream = io.TextIOWrapper(buffer, encoding='ascii')
        with redirect_stdout(stream):
            self.assertEqual(main(['--cutoff', '1', '--query', 'ブランコ', '--json']), 0)
        stream.flush()
        self.assertEqual(json.loads(buffer.getvalue().decode('utf-8'))['request']['query'], 'ブランコ')
        stream.detach()

    def test_dense_prefixes_cosine_and_index_reuse(self):
        """Injected encoders see E5 prefixes; cosine normalizes and excludes zero/negative scores."""
        calls = []
        vectors = {'best': [5, 0], 'next': [4, 3], 'zero': [0, 0], 'negative': [-1, 0], 'q': [2, 0]}

        def encoder(texts):
            calls.append(list(texts))
            return [vectors[text.split(': ', 1)[1]] for text in texts]

        passages = [Passage(f'1.{n}', text) for n, text in enumerate(list(vectors)[:-1], 1)]
        retriever = DenseE5RetrieverV0(encoder)
        request = RetrievalRequest('q', 1)
        hits = retrieve(request, retriever, passages)
        self.assertEqual([h.passage_id for h in hits], ['1.1', '1.2'])
        self.assertAlmostEqual(hits[0].score, 1)
        self.assertAlmostEqual(hits[1].score, .8)
        self.assertEqual(hits, retrieve(request, retriever, list(passages)))
        self.assertEqual(calls, [['passage: ' + p.text for p in passages], ['query: q'], ['query: q']])
        replacement = [Passage('1.9', 'next')]
        self.assertEqual([h.passage_id for h in retrieve(request, retriever, replacement)], ['1.9'])
        retriever.index([])
        self.assertEqual(retriever.search('q', set(), 10), [])
        for model, revision, name, batch in [
                (E5_SMALL_MODEL, E5_SMALL_REVISION, 'dense_e5_small_v0', 32),
                (E5_LARGE_MODEL, E5_LARGE_REVISION, 'dense_e5_large_v0', 4),
                ('local-test', 'abcdef123456', 'dense_e5_custom_v0', 2)]:
            with self.subTest(model=model), patch(
                    'tools.story_retrieval.retrieval_v0._default_encoder', return_value=encoder) as loader:
                options = {} if model in (E5_SMALL_MODEL, E5_LARGE_MODEL) else {'revision': revision}
                lazy = DenseE5RetrieverV0(model_name=model, batch_size=batch, **options)
                self.assertEqual((lazy.name, lazy.version), (name, '0+' + revision[:7]))
                loader.assert_not_called()
                lazy.index(replacement)
                loader.assert_called_once_with(model, revision, batch)
                self.assertEqual(lazy.search('q', set(), 10), [])
                metadata = result_to_dict(request, lazy, replacement, [])['retriever']
                self.assertEqual(metadata, {'name': name, 'version': '0+' + revision[:7]})

    def test_invalid_encoder_outputs(self):
        """Bad vector counts, dimensions and non-finite values fail clearly."""
        for options in [{'batch_size': 0}, {'model_name': 'custom'}, {'revision': ''}]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                DenseE5RetrieverV0(**options)
        passages = [Passage('1.1', 'a'), Passage('1.2', 'b')]
        for encoded in [[], [[1], [1, 2]], [[], []], [[float('nan')], [1]]]:
            with self.subTest(encoded=encoded), self.assertRaises(ValueError):
                DenseE5RetrieverV0(lambda texts: encoded).index(passages)
        retriever = DenseE5RetrieverV0(lambda texts: [[1, 0] for _ in texts]
                                     if texts[0].startswith('passage: ') else [[1]])
        retriever.index(passages)
        with self.assertRaises(ValueError):
            retriever.search('q', {'1.1'}, 10)

    def test_embedding_cache_reuse_updates_and_cutoff(self):
        """Cross-instance reuse preserves exact scores, text identity, batching and eligibility."""
        passages = [Passage('1.1', 'apple'), Passage('2.1', 'banana'), Passage('3.1', 'secret banana')]
        request = RetrievalRequest('secret banana', 2)
        expected = retrieve(request, DenseE5RetrieverV0(character_encoder), passages)
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / 'nested' / 'cache'
            for warm in [False, True]:
                with self.subTest(warm=warm):
                    encoder = CountingEncoder()
                    retriever = DenseE5RetrieverV0(encoder, cache_dir=str(cache))
                    self.assertEqual(retrieve(request, retriever, passages), expected)
                    self.assertEqual(encoder.passages, [] if warm else ['passage: ' + p.text for p in passages])
                    self.assertEqual(encoder.calls[:-1], [] if warm else [['passage: ' + p.text for p in passages]])
                    self.assertEqual(retrieve(request, retriever, list(passages)), expected)
                    self.assertEqual(encoder.calls[-2:], [['query: secret banana']] * 2)
                    self.assertTrue(expected)
                    self.assertTrue(all(h.chapter <= 2 for h in expected))
            # A smaller corpus must not resurrect cached IDs from later chapters.
            encoder = CountingEncoder()
            retriever = DenseE5RetrieverV0(encoder, cache_dir=cache)
            self.assertEqual(retrieve(request, retriever, passages[:2]), expected)
            self.assertEqual(encoder.passages, [])
            changed = [passages[0], Passage('2.1', 'pear'), passages[2], Passage('2.9', 'pear')]
            encoder = CountingEncoder()
            retriever = DenseE5RetrieverV0(encoder, cache_dir=cache)
            actual = retrieve(request, retriever, changed)
            self.assertEqual(encoder.passages, ['passage: pear'])
            self.assertEqual(actual, retrieve(request, DenseE5RetrieverV0(character_encoder), changed))
            renamed = [Passage('1.99', 'pear')]
            encoder.calls.clear()
            retriever.index(renamed)
            self.assertEqual(encoder.passages, [])
            self.assertEqual([pid for pid, _ in retriever.search('pear', {'1.99'}, 10)], ['1.99'])
            retriever.index([])
            self.assertEqual(retriever.search('pear', {'1.99'}, 10), [])
            data = json.loads(next((cache / 'unscoped').glob('*.json')).read_text(encoding='utf-8'))
            self.assertIn(hashlib.sha256(b'passage: pear').hexdigest(), data['vectors'])
            self.assertEqual(len(list(cache.iterdir())), 1)

    def test_embedding_cache_model_revision_isolation_and_opt_out(self):
        """Model/revision pairs use safe distinct filenames; opting out never writes files."""
        passages = [Passage('1.1', 'apple'), Passage('2.1', 'banana')]
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            with patch('tools.story_retrieval.retrieval_v0.Path.open', side_effect=AssertionError('cache disabled')):
                retriever = DenseE5RetrieverV0(character_encoder)
                retriever.index(passages)
                self.assertIsNone(retriever.cache_dir)
                self.assertEqual(list(cache.iterdir()), [])
            for model, revision in [('a/b', 'rev/one'), ('a/b', 'rev/two'), ('a_b', 'rev/one')]:
                with self.subTest(model=model, revision=revision):
                    before = set(cache.rglob('*.json'))
                    encoder = CountingEncoder()
                    retriever = DenseE5RetrieverV0(encoder, model_name=model, revision=revision, cache_dir=cache)
                    retriever.index(passages)
                    self.assertEqual(encoder.calls, [['passage: apple', 'passage: banana']])
                    added = set(cache.rglob('*.json')) - before
                    self.assertEqual(len(added), 1)
                    self.assertRegex(added.pop().name, r'^[0-9a-f]{64}\.json$')

    def test_embedding_cache_corruption_and_dimension_recovery(self):
        """Unreadable/invalid caches and stale dimensions rebuild without mixing vectors."""
        passages = [Passage('1.1', 'apple'), Passage('2.1', 'banana')]
        request = RetrievalRequest('apple', 2)
        expected = retrieve(request, DenseE5RetrieverV0(character_encoder), passages)
        key = hashlib.sha256(b'passage: apple').hexdigest()
        bad_files = [b'not JSON', b'\xff', b'[]', b'{"vectors": []}',
                     json.dumps({'dimension': 0, 'vectors': {}}).encode(),
                     json.dumps({'dimension': 1, 'vectors': {'bad': [1]}}).encode(),
                     json.dumps({'dimension': 1, 'vectors': {key: None}}).encode(),
                     json.dumps({'dimension': 1, 'vectors': {key: [None]}}).encode(),
                     json.dumps({'dimension': 1, 'vectors': {key: [10 ** 1000]}}).encode(),
                     json.dumps({'dimension': 2, 'vectors': {key: [1]}}).encode(),
                     json.dumps({'dimension': 1, 'vectors': {key: [float('inf')]}}).encode()]
        bad_files.extend(json.dumps({'dimension': 2, 'vectors': {key: row}}).encode()
                         for row in [[6, 8], [.3, .4], [1.000002, 0], [1e308, 1e308]])
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            DenseE5RetrieverV0(character_encoder, cache_dir=cache).index(passages)
            path = next(cache.rglob('*.json'))
            for bad in bad_files:
                with self.subTest(bad=bad):
                    path.write_bytes(bad)
                    encoder = CountingEncoder()
                    self.assertEqual(retrieve(request, DenseE5RetrieverV0(encoder, cache_dir=cache), passages), expected)
                    self.assertEqual(encoder.passages, ['passage: apple', 'passage: banana'])
            for row in [[0, 0], [.6, .8], [1.0000005, 0]]:
                with self.subTest(valid_cached_vector=row):
                    path.write_text(json.dumps({'dimension': 2, 'vectors': {key: row}}),
                                    encoding='utf-8')
                    encoder = CountingEncoder()
                    cached = DenseE5RetrieverV0(encoder, cache_dir=cache)
                    cached.index(passages[:1])
                    self.assertEqual(encoder.passages, [])
                    self.assertEqual(cached._vectors['1.1'], tuple(row))
            # A structurally valid cache may have the wrong dimension for this encoder.
            # Exercise detection via a new passage batch and via a warm query.
            for cached_passages in [passages[:1], passages]:
                with self.subTest(cached_count=len(cached_passages)):
                    path.unlink()
                    DenseE5RetrieverV0(lambda texts: [[1, 0] for _ in texts], cache_dir=cache).index(cached_passages)
                    encoder = CountingEncoder()
                    self.assertEqual(retrieve(request, DenseE5RetrieverV0(encoder, cache_dir=cache), passages), expected)
                    self.assertEqual(encoder.calls[-1 if len(cached_passages) == 2 else -2],
                                     ['passage: apple', 'passage: banana'])
                    rebuilt = json.loads(path.read_text(encoding='utf-8'))
                    self.assertEqual(rebuilt['dimension'], 26)
                    self.assertTrue(all(len(row) == 26 for row in rebuilt['vectors'].values()))
            with patch('tools.story_retrieval.retrieval_v0.Path.read_text', side_effect=PermissionError('unreadable')):
                encoder = CountingEncoder()
                self.assertEqual(retrieve(request, DenseE5RetrieverV0(encoder, cache_dir=cache), passages), expected)
                self.assertEqual(len(encoder.passages), 2)
            original = path.read_bytes()
            with patch('tools.story_retrieval.retrieval_v0.os.replace', side_effect=OSError('replace failed')):
                with self.assertRaises(OSError):
                    DenseE5RetrieverV0(character_encoder, cache_dir=cache).index([Passage('1.9', 'pear')])
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(cache.rglob('*.json')), [path])

    def test_rrf_hand_computed_ranks_depth_and_reindexing(self):
        """RRF K=60 fuses component ranks with natural ties and indexes each corpus once."""
        first = RankedRetriever([('1.2', 3), ('1.10', 2), ('1.3', 1), ('9.1', 99), ('1.4', 0)])
        second = RankedRetriever([('1.10', 3), ('1.2', 2)])
        hybrid = HybridRrfRetrieverV0([first, second])
        passages = [Passage(pid, 'match') for pid in ['1.2', '1.10', '1.3', '1.4']]
        request = RetrievalRequest('q', 1)
        hits = retrieve(request, hybrid, passages)
        self.assertEqual([h.passage_id for h in hits], ['1.2', '1.10', '1.3'])
        self.assertAlmostEqual(hits[0].score, 1/61 + 1/62)
        self.assertAlmostEqual(hits[2].score, 1/63)
        self.assertEqual(hits, retrieve(request, hybrid, list(passages)))
        self.assertEqual(first.index_calls, 1)
        retrieve(RetrievalRequest('q', 1, k=101), hybrid, passages + [Passage('1.5', 'new')])
        self.assertEqual(first.index_calls, 2)
        self.assertEqual(second.depths, [100, 100, 101])
        # A failed replacement leaves BM25 changed and dense on its original snapshot.
        dense = DenseE5RetrieverV0(character_encoder)
        hybrid = HybridRrfRetrieverV0([Bm25RetrieverV0(), dense])
        original = [Passage('1.1', 'apple')]
        apple_request = RetrievalRequest('apple', 1)
        expected = retrieve(apple_request, hybrid, original)
        self.assertAlmostEqual(expected[0].score, 2 / 61)
        with patch.object(dense, '_encoder', side_effect=RuntimeError('encoding failed')):
            with self.assertRaisesRegex(RuntimeError, 'encoding failed'):
                hybrid.index([Passage('1.1', 'banana')])
        self.assertEqual(retrieve(apple_request, hybrid, original), expected)
        bm25 = Bm25RetrieverV0()
        retrieve(RetrievalRequest('match', 1), bm25, passages)
        self.assertEqual(retrieve(RetrievalRequest('match', 1), bm25, [Passage('1.9', 'new')]), [])
        for components, rrf_k in [([], 60), ([first], 0)]:
            with self.subTest(components=components, rrf_k=rrf_k), self.assertRaises(ValueError):
                HybridRrfRetrieverV0(components, rrf_k)

    def test_factory_and_lightweight_import(self):
        """Construction and import do not require or import the optional model stack."""
        expected_names = ['bm25_v0', 'dense_e5_small_v0', 'dense_e5_large_v0',
                          'hybrid_rrf_v0', 'hybrid_rrf_large_v0']
        for name, expected in zip(RETRIEVER_NAMES, expected_names):
            for cache in [None, Path('.local/story_retrieval/embedding_cache')]:
                with self.subTest(name=name, cache=cache):
                    retriever = make_retriever(name, cache_dir=cache)
                    self.assertEqual(retriever.name, expected)
                    if name != 'bm25':
                        dense = retriever.retrievers[1] if name.startswith('hybrid') else retriever
                        large = name.endswith('large')
                        self.assertEqual(dense.model_name, E5_LARGE_MODEL if large else E5_SMALL_MODEL)
                        self.assertEqual(dense.revision, E5_LARGE_REVISION if large else E5_SMALL_REVISION)
                        self.assertEqual(dense.batch_size, 4 if large else 32)
                        self.assertIn(dense.version, retriever.version)
                        self.assertEqual(dense.cache_dir, cache)
                    with patch('tools.story_retrieval.retrieve.make_retriever', return_value=Bm25RetrieverV0()) as factory:
                        with redirect_stdout(io.StringIO()):
                            args = ['--cutoff', '1', '--query', 'q', '--retriever', name]
                            self.assertEqual(main(args + (['--cache-dir', str(cache)] if cache else [])), 0)
                        factory.assert_called_once_with(name, cache_dir=cache)
        overridden = DenseE5RetrieverV0(revision='123456789')
        self.assertEqual(overridden.version, '0+1234567')
        with self.assertRaises(ValueError):
            make_retriever('unknown')
        code = ('import sys; import tools.story_retrieval.retrieval_v0; '
                'assert not any(n.split(".")[0] in {"torch", "sentence_transformers"} for n in sys.modules)')
        result = subprocess.run([sys.executable, '-c', code], cwd=REPO, capture_output=True,
                                env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1'))
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
