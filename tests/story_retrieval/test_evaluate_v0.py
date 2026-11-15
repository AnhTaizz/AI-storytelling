"""Public DEV evaluation and synthetic-only private adapter checks."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import yaml

from tools.story_benchmark.multi_gold_metrics import normalize_gold_evidence_sets
from tools.story_ingestion.light_novel_adapter_v0 import IngestionError
from tools.story_pipeline.source import Passage
from tools.story_retrieval.evaluate_v0 import DEFAULT_PROBES, evaluate_dev, evaluate_private, main
from tools.story_retrieval.retrieval_v0 import (
    RETRIEVER_NAMES, Bm25RetrieverV0, build_corpus, passage_chapter,
)
from tools.story_retrieval.retrieve import DEFAULT_MANIFEST


class EvaluateV0Tests(unittest.TestCase):
    def test_dev_fixture_validity(self):
        """DEV gold is grounded in public passages within each varied cutoff."""
        ids = {p.passage_id for p in build_corpus(DEFAULT_MANIFEST, 5)}
        required = {'probe_id', 'language', 'query', 'cutoff_chapter', 'gold_evidence_sets', 'note'}
        for version, lower, upper in [('v0', 8, 12), ('v1', 28, 32)]:
            with self.subTest(version=version):
                path = DEFAULT_PROBES.with_name(f'dev_probes_{version}.yaml')
                probes = yaml.safe_load(path.read_text(encoding='utf-8'))['probes']
                self.assertTrue(lower <= len(probes) <= upper)
                self.assertEqual({p['language'] for p in probes}, {'ja', 'vi'})
                self.assertEqual({p['cutoff_chapter'] for p in probes}, set(range(1, 6)))
                self.assertEqual(len({p['probe_id'] for p in probes}), len(probes))
                if version == 'v1':
                    self.assertEqual({p['category'] for p in probes},
                                     {'character_fact', 'event', 'relationship', 'recap', 'boundary'})
                    self.assertGreaterEqual(sum(all(len(g) >= 2 for g in p['gold_evidence_sets'])
                                                for p in probes), 8)
                    self.assertGreaterEqual(sum(p['category'] == 'boundary' for p in probes), 4)
                    self.assertLessEqual(sum('pair_of' in p for p in probes), 3)
                for probe in probes:
                    with self.subTest(probe_id=probe['probe_id']):
                        self.assertTrue((required | ({'category'} if version == 'v1' else set())) <= probe.keys())
                        self.assertTrue(probe['query'].strip() and probe['note'].strip())
                        self.assertIn(probe['cutoff_chapter'], range(1, 6))
                        if version == 'v1' and probe['category'] == 'boundary':
                            self.assertIsInstance(probe['tempting_chapter'], int)
                            self.assertGreater(probe['tempting_chapter'], probe['cutoff_chapter'])
                            self.assertLessEqual(probe['tempting_chapter'], 5)
                        for gold in normalize_gold_evidence_sets(probe):
                            self.assertTrue(set(gold) <= ids)
                            self.assertTrue(all(passage_chapter(pid) <= probe['cutoff_chapter'] for pid in gold))

    def test_dev_category_means_with_optional_categories(self):
        """Category means use only tagged probes, preserving language and overall means."""
        passages = [Passage('1.1', 'alpha'), Passage('1.2', 'beta')]
        probes = [dict(probe_id='hit', language='ja', category='event', query='alpha',
                       cutoff_chapter=1, gold_evidence_sets=[['1.1']]),
                  dict(probe_id='miss', language='vi', category='event', query='alpha',
                       cutoff_chapter=1, gold_evidence_sets=[['1.2']]),
                  dict(probe_id='partial', language='ja', category='recap', query='alpha',
                       cutoff_chapter=1, gold_evidence_sets=[['1.1', '1.2']]),
                  dict(probe_id='untagged', language='vi', query='beta',
                       cutoff_chapter=1, gold_evidence_sets=[['1.2']])]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'probes.yaml'
            for categorized in [False, True]:
                with self.subTest(categorized=categorized), patch(
                        'tools.story_retrieval.evaluate_v0.build_corpus', return_value=passages):
                    rows = [dict(p) for p in probes]
                    if not categorized:
                        for row in rows:
                            row.pop('category', None)
                    path.write_text(yaml.safe_dump(rows), encoding='utf-8')
                    values = evaluate_dev(path, DEFAULT_MANIFEST, [Bm25RetrieverV0()])['retrievers']['bm25_v0']
                    self.assertEqual(values['overall']['recall@10'], .625)
                    self.assertEqual(values['per_language']['ja']['recall@10'], .75)
                    self.assertEqual(values['per_language']['vi']['recall@10'], .5)
                    self.assertEqual('per_category' in values, categorized)
                    if categorized:
                        self.assertEqual(set(values['per_category']), {'event', 'recap'})
                        for category, metrics in values['per_category'].items():
                            for key, score in metrics.items():
                                expected = (0 if key.startswith('spoiler_violation') else
                                            .5 if category == 'event' or key.startswith('recall') else
                                            0 if key.startswith('success') else 1)
                                self.assertEqual(score, expected, (category, key))

    def test_dev_metrics_and_safe_per_probe_rows(self):
        """Evaluation reports overall/language means and ranks without source text."""
        result = evaluate_dev(DEFAULT_PROBES, DEFAULT_MANIFEST, [Bm25RetrieverV0()])
        self.assertEqual(result['probe_count'], 10)
        values = result['retrievers']['bm25_v0']
        self.assertEqual(values['version'], '0')
        expected = {'mrr', 'mrr@10'} | {f'{metric}@{k}' for metric in ['hit', 'recall', 'success', 'spoiler_violation']
                              for k in [1, 5, 10]}
        for metrics in [values['overall'], *values['per_language'].values()]:
            with self.subTest(metrics=metrics):
                self.assertEqual(set(metrics), expected)
                self.assertTrue(all(0 <= score <= 1 for score in metrics.values()))
                self.assertTrue(all(metrics[f'spoiler_violation@{k}'] == 0 for k in [1, 5, 10]))
        for row in values['per_probe']:
            self.assertEqual(set(row), {'probe_id', 'language', 'ranking', 'metrics'})
            self.assertTrue(all(set(hit) == {'passage_id', 'rank'} for hit in row['ranking']))
        # Gold after rank ten must contribute to full MRR at every requested depth.
        passages = [Passage(f'1.{i}', 'match') for i in range(1, 12)]
        probe = dict(probe_id='late', language='ja', query='match', cutoff_chapter=1,
                     gold_evidence_sets=[['1.11']])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'probes.yaml'
            path.write_text(yaml.safe_dump([probe]), encoding='utf-8')
            for depths in [(1,), (1, 5, 10), (11,)]:
                with self.subTest(depths=depths), patch(
                        'tools.story_retrieval.evaluate_v0.build_corpus', return_value=passages):
                    late = evaluate_dev(path, DEFAULT_MANIFEST, [Bm25RetrieverV0()], depths)
                    values = late['retrievers']['bm25_v0']
                    for metrics in [values['overall'], values['per_language']['ja'],
                                    values['per_probe'][0]['metrics']]:
                        self.assertAlmostEqual(metrics['mrr'], 1 / 11)
                        self.assertEqual(metrics['mrr@10'], 0)
                        for k in depths:
                            for metric in ['hit', 'recall', 'success']:
                                self.assertEqual(metrics[f'{metric}@{k}'], int(k >= 11))
                            self.assertEqual(metrics[f'spoiler_violation@{k}'], 0)
                    self.assertEqual(values['per_probe'][0]['ranking'],
                                     [{'passage_id': p.passage_id, 'rank': i}
                                      for i, p in enumerate(passages[:max(depths)], 1)])
        for k_values in [(), (0,), ('bad',)]:
            with self.subTest(k_values=k_values), self.assertRaises(ValueError):
                evaluate_dev(DEFAULT_PROBES, DEFAULT_MANIFEST, [Bm25RetrieverV0()], k_values)

    def test_private_synthetic_mapping_cutoff_and_missing_files(self):
        """Chunk IDs map back correctly and future-only lexical evidence cannot be returned."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIsNone(evaluate_private(root))
            (root / 'LONG_RANGE_PROBE_V1').mkdir()
            probes = [dict(probe_id='one', question='alpha', cutoff_chapter=1,
                           required_evidence_chunk_ids=['ch001_c0007'], category='fact'),
                      dict(probe_id='two', question='beta', cutoff_chapter=1,
                           required_evidence_chunk_ids=['ch001_c0007'], category='boundary')]
            (root / 'LONG_RANGE_PROBE_V1/probes.yaml').write_text(yaml.safe_dump({'probes': probes}),
                                                               encoding='utf-8')
            self.assertIsNone(evaluate_private(root))
            (root / 'PARAGRAPH_PACK_V1').mkdir()
            chunks = [dict(chunk_id='ch002_c0010', chapter_number=2, chunk_index=10, text='beta'),
                      dict(chunk_id='ch001_c0007', chapter_number=1, chunk_index=7, text='alpha')]
            path = root / 'PARAGRAPH_PACK_V1/chunks.jsonl'
            path.write_text('\n'.join(json.dumps(row) for row in chunks), encoding='utf-8')
            result = evaluate_private(root)
            self.assertEqual(result['mode'], 'CUTOFF_FILTERED')
            self.assertEqual(result['probe_count'], 2)
            metrics = result['retrievers']['bm25_v0']
            self.assertEqual(result['retriever_versions'], {'bm25_v0': '0'})
            self.assertTrue({'hit@20', 'recall@20', 'success@20', 'mrr@10'} <= metrics.keys())
            for key, value in metrics.items():
                with self.subTest(metric=key):
                    self.assertEqual(value, 0 if key.startswith('spoiler_violation') else .5)
            serialized = json.dumps(result)
            self.assertNotIn('ch001_c0007', serialized)
            self.assertNotIn('alpha', serialized)
            self.assertNotIn('per_probe', serialized)
            # Multi-evidence completion is distinct from a partial hit/recall.
            probes[0]['required_evidence_chunk_ids'].append('ch002_c0010')
            (root / 'LONG_RANGE_PROBE_V1/probes.yaml').write_text(yaml.safe_dump(probes), encoding='utf-8')
            partial = evaluate_private(root)['retrievers']['bm25_v0']
            self.assertEqual(partial['hit@10'], .5)
            self.assertEqual(partial['recall@10'], .25)
            self.assertEqual(partial['success@10'], 0)
            # Full MRR sees late gold; depth-20 metrics stop exactly at rank 20.
            late_chunks = [dict(chunk_id=f'chunk{i}', chapter_number=1, chunk_index=i, text='x')
                           for i in range(1, 22)]
            late_probe = dict(probe_id='late', question='x', cutoff_chapter=1,
                              required_evidence_chunk_ids=['chunk21'])
            for gold_rank in [11, 20, 21]:
                with self.subTest(first_gold_rank=gold_rank):
                    late_probe['required_evidence_chunk_ids'] = [f'chunk{gold_rank}']
                    (root / 'LONG_RANGE_PROBE_V1/probes.yaml').write_text(
                        yaml.safe_dump([late_probe]), encoding='utf-8')
                    path.write_text('\n'.join(json.dumps(row) for row in late_chunks), encoding='utf-8')
                    late = evaluate_private(root, [Bm25RetrieverV0()])['retrievers']['bm25_v0']
                    self.assertAlmostEqual(late['mrr'], 1 / gold_rank)
                    self.assertEqual(late['mrr@10'], 0)
                    for metric in ['hit', 'recall', 'success']:
                        self.assertEqual(late[f'{metric}@20'], int(gold_rank <= 20))
                    self.assertEqual(late['spoiler_violation@20'], 0)
            path.write_text('\n'.join(json.dumps(row) for row in chunks + [chunks[0]]), encoding='utf-8')
            with self.assertRaises(ValueError):
                evaluate_private(root)
            path.write_text('', encoding='utf-8')
            empty = evaluate_private(root)['retrievers']['bm25_v0']
            self.assertTrue(all(value == 0 for value in empty.values()))

    def test_cli_aggregate_output_and_errors(self):
        """CLI emits aggregate-only JSON/text and handles dependency/argument errors."""
        with tempfile.TemporaryDirectory() as tmp:
            for path, count in [(None, 10), (DEFAULT_PROBES.with_name('dev_probes_v1.yaml'), 30)]:
                for as_json in [True, False]:
                    with self.subTest(probes=path, as_json=as_json), redirect_stdout(io.StringIO()) as output:
                        args = ['--retriever', 'bm25', '--private-root', tmp] + (['--json'] if as_json else [])
                        self.assertEqual(main(args + (['--probes', str(path)] if path else [])), 0)
                        text = output.getvalue()
                        self.assertNotIn('per_probe', text)
                        if as_json:
                            summary = json.loads(text)
                            self.assertIsNone(summary['private'])
                            self.assertEqual(summary['dev']['probe_count'], count)
                            self.assertEqual('per_category' in summary['dev']['retrievers']['bm25_v0'], path is not None)
                        else:
                            self.assertIn('private: not run', text)
        for failure in [ImportError('missing encoder'), IngestionError('MANIFEST', 'invalid manifest')]:
            with self.subTest(failure=failure), patch(
                    'tools.story_retrieval.evaluate_v0.build_corpus', side_effect=failure):
                with redirect_stderr(io.StringIO()) as error:
                    self.assertEqual(main([]), 2)
                    self.assertTrue(error.getvalue().startswith('error: '))
                    self.assertIn(str(failure), error.getvalue())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'LONG_RANGE_PROBE_V1').mkdir()
            (root / 'PARAGRAPH_PACK_V1').mkdir()
            (root / 'LONG_RANGE_PROBE_V1/probes.yaml').write_text('probes: [', encoding='utf-8')
            (root / 'PARAGRAPH_PACK_V1/chunks.jsonl').write_text('', encoding='utf-8')
            with redirect_stderr(io.StringIO()) as error, redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(['--private-root', tmp]), 2)
                self.assertTrue(error.getvalue().startswith('error: '))
                self.assertIn('probes: [', error.getvalue())
                self.assertEqual(output.getvalue(), '')
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(['--retriever', 'unknown']), 2)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--help']), 0)
        with tempfile.TemporaryDirectory() as tmp:
            for name in RETRIEVER_NAMES:
                for cache in [None, Path(tmp) / 'embedding_cache']:
                    with self.subTest(retriever=name, cache=cache), patch(
                            'tools.story_retrieval.evaluate_v0.make_retriever', return_value=Bm25RetrieverV0()) as factory:
                        with redirect_stdout(io.StringIO()) as output:
                            args = ['--retriever', name, '--private-root', tmp, '--json']
                            self.assertEqual(main(args + (['--cache-dir', str(cache)] if cache else [])), 0)
                        factory.assert_called_once_with(name, cache_dir=cache)
                        self.assertEqual(json.loads(output.getvalue())['dev']['retrievers']['bm25_v0']['version'], '0')


if __name__ == '__main__':
    unittest.main()
