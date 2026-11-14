"""Behavioural contract for retrieval_v0 and its retrieve CLI."""

import io
import json
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from jsonschema import Draft202012Validator

from tools.story_benchmark.bm25_lexical_v1 import jp_simple_lexical_v1
from tools.story_pipeline.source import Chapter, Passage, StoryScope
from tools.story_retrieval.retrieval_v0 import (
    Bm25RetrieverV0, DenseE5RetrieverV0, HybridRrfRetrieverV0, RetrievalRequest,
    build_corpus, make_retriever, natural_key, passage_chapter, result_to_dict, retrieve,
)
from tools.story_retrieval.retrieve import DEFAULT_MANIFEST, REPO, main


def character_encoder(texts):
    return [[text.split(': ', 1)[1].casefold().count(c) for c in 'abcdefghijklmnopqrstuvwxyz']
            for text in texts]


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
        with patch('tools.story_retrieval.retrieval_v0._default_encoder', return_value=encoder) as loader:
            lazy = DenseE5RetrieverV0(model_name='local-test')
            loader.assert_not_called()
            lazy.index(replacement)
            loader.assert_called_once_with('local-test')
            self.assertEqual(lazy.search('q', set(), 10), [])

    def test_invalid_encoder_outputs(self):
        """Bad vector counts, dimensions and non-finite values fail clearly."""
        passages = [Passage('1.1', 'a'), Passage('1.2', 'b')]
        for encoded in [[], [[1], [1, 2]], [[], []], [[float('nan')], [1]]]:
            with self.subTest(encoded=encoded), self.assertRaises(ValueError):
                DenseE5RetrieverV0(lambda texts: encoded).index(passages)
        retriever = DenseE5RetrieverV0(lambda texts: [[1, 0] for _ in texts]
                                     if texts[0].startswith('passage: ') else [[1]])
        retriever.index(passages)
        with self.assertRaises(ValueError):
            retriever.search('q', {'1.1'}, 10)

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
        bm25 = Bm25RetrieverV0()
        retrieve(RetrievalRequest('match', 1), bm25, passages)
        self.assertEqual(retrieve(RetrievalRequest('match', 1), bm25, [Passage('1.9', 'new')]), [])
        for components, rrf_k in [([], 60), ([first], 0)]:
            with self.subTest(components=components, rrf_k=rrf_k), self.assertRaises(ValueError):
                HybridRrfRetrieverV0(components, rrf_k)

    def test_factory_and_lightweight_import(self):
        """Construction and import do not require or import the optional model stack."""
        for name, expected in [('bm25', 'bm25_v0'), ('dense_e5', 'dense_e5_small_v0'),
                               ('hybrid', 'hybrid_rrf_v0')]:
            with self.subTest(name=name):
                self.assertEqual(make_retriever(name).name, expected)
        with self.assertRaises(ValueError):
            make_retriever('unknown')
        code = ('import sys; import tools.story_retrieval.retrieval_v0; '
                'assert not any(n.split(".")[0] in {"torch", "sentence_transformers"} for n in sys.modules)')
        result = subprocess.run([sys.executable, '-c', code], cwd=REPO, capture_output=True,
                                env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1'))
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
