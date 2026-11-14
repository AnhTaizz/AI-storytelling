"""Public DEV evaluation and synthetic-only private adapter checks."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import yaml

from tools.story_retrieval.evaluate_v0 import DEFAULT_PROBES, evaluate_dev, evaluate_private, main
from tools.story_retrieval.retrieval_v0 import Bm25RetrieverV0, build_corpus, passage_chapter
from tools.story_retrieval.retrieve import DEFAULT_MANIFEST


class EvaluateV0Tests(unittest.TestCase):
    def test_dev_fixture_validity(self):
        """DEV gold is grounded in public passages within each varied cutoff."""
        probes = yaml.safe_load(DEFAULT_PROBES.read_text(encoding='utf-8'))['probes']
        self.assertTrue(8 <= len(probes) <= 12)
        self.assertEqual({p['language'] for p in probes}, {'ja', 'vi'})
        self.assertEqual({p['cutoff_chapter'] for p in probes}, set(range(1, 6)))
        self.assertEqual(len({p['probe_id'] for p in probes}), len(probes))
        ids = {p.passage_id for p in build_corpus(DEFAULT_MANIFEST, 5)}
        required = {'probe_id', 'language', 'query', 'cutoff_chapter', 'gold_evidence_sets', 'note'}
        for probe in probes:
            with self.subTest(probe_id=probe['probe_id']):
                self.assertTrue(required <= probe.keys())
                self.assertTrue(probe['query'].strip() and probe['note'].strip())
                self.assertTrue(probe['gold_evidence_sets'])
                for gold in probe['gold_evidence_sets']:
                    self.assertTrue(gold)
                    self.assertEqual(len(set(gold)), len(gold))
                    self.assertTrue(set(gold) <= ids)
                    self.assertTrue(all(passage_chapter(pid) <= probe['cutoff_chapter'] for pid in gold))

    def test_dev_metrics_and_safe_per_probe_rows(self):
        """Evaluation reports overall/language means and ranks without source text."""
        result = evaluate_dev(DEFAULT_PROBES, DEFAULT_MANIFEST, [Bm25RetrieverV0()])
        self.assertEqual(result['probe_count'], 10)
        values = result['retrievers']['bm25_v0']
        expected = {'mrr'} | {f'{metric}@{k}' for metric in ['hit', 'recall', 'success', 'spoiler_violation']
                              for k in [1, 5, 10]}
        for metrics in [values['overall'], *values['per_language'].values()]:
            with self.subTest(metrics=metrics):
                self.assertEqual(set(metrics), expected)
                self.assertTrue(all(0 <= score <= 1 for score in metrics.values()))
                self.assertTrue(all(metrics[f'spoiler_violation@{k}'] == 0 for k in [1, 5, 10]))
        for row in values['per_probe']:
            self.assertEqual(set(row), {'probe_id', 'language', 'ranking', 'metrics'})
            self.assertTrue(all(set(hit) == {'passage_id', 'rank'} for hit in row['ranking']))
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
            path.write_text('\n'.join(json.dumps(row) for row in chunks + [chunks[0]]), encoding='utf-8')
            with self.assertRaises(ValueError):
                evaluate_private(root)

    def test_cli_aggregate_output_and_errors(self):
        """CLI emits aggregate-only JSON/text and handles dependency/argument errors."""
        with tempfile.TemporaryDirectory() as tmp:
            for as_json in [True, False]:
                with self.subTest(as_json=as_json), redirect_stdout(io.StringIO()) as output:
                    args = ['--retriever', 'bm25', '--private-root', tmp] + (['--json'] if as_json else [])
                    self.assertEqual(main(args), 0)
                    text = output.getvalue()
                    self.assertNotIn('per_probe', text)
                    if as_json:
                        self.assertIsNone(json.loads(text)['private'])
                    else:
                        self.assertIn('private: not run', text)
        with patch('tools.story_retrieval.evaluate_v0.make_retriever', side_effect=ImportError('missing encoder')):
            with redirect_stderr(io.StringIO()) as error:
                self.assertEqual(main([]), 2)
                self.assertIn('missing encoder', error.getvalue())
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(['--retriever', 'unknown']), 2)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--help']), 0)


if __name__ == '__main__':
    unittest.main()
