"""Synthetic tests for the Task Q executor (no models, no fixture text)."""
import copy
import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import numpy as np
import yaml

from tools.story_benchmark import bge_reranker_v2_m3_top30_v1 as M
from tools.story_benchmark import fixture_freeze as ff
from tools.story_benchmark import km_consensus_rank_sum_v1 as O
from tools.story_benchmark import run_independent_validation_task_q_v1 as tq


def synthetic_probes(n=16, multi=2):
    probes = []
    for i in range(n):
        gold = [[f"D{i}a", f"D{i}b"]]
        if i < multi:
            gold.append([f"D{i}a", f"D{i}c"])
        probes.append({"probe_id": f"SYN{i:02d}", "category": "CHRONOLOGY", "question": f"q{i}",
                       "cutoff_chapter": 30, "gold_evidence_sets": gold})
    return probes


def write_frozen_zip(path: Path, probes, **flags):
    fixture = {"status": "FROZEN", "frozen": True, "evaluation_allowed": True,
               "task_q_executed": False, **flags, "probes": probes}
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("PKG/frozen_primary_fixture.yaml", yaml.safe_dump(fixture))
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestInputGates(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_01_correct_frozen_fixture_accepted(self):
        path = self.root / "frozen.zip"
        sha = write_frozen_zip(path, synthetic_probes())
        self.assertEqual(len(tq.load_frozen_probes(path, sha)), 16)

    def test_02_wrong_frozen_hash_rejected(self):
        path = self.root / "frozen.zip"
        write_frozen_zip(path, synthetic_probes())
        with self.assertRaises(tq.TaskQGateError):
            tq.load_frozen_probes(path, "0" * 64)

    def test_03_old_development_fixture_rejected(self):
        dev = self.root / "probes.yaml"
        dev.write_text(yaml.safe_dump({"probes": [
            {"probe_id": f"DEV{i}", "required_evidence_chunk_ids": ["A", "B"]} for i in range(15)]}))
        sha = hashlib.sha256(dev.read_bytes()).hexdigest()
        with self.assertRaises(tq.TaskQGateError):
            tq.load_frozen_probes(dev, sha)
        not_frozen = self.root / "dev.zip"
        sha = write_frozen_zip(not_frozen, synthetic_probes(), status="DRAFT", frozen=False)
        with self.assertRaises(tq.TaskQGateError):
            tq.load_frozen_probes(not_frozen, sha)

    def test_04_wrong_probe_count_rejected(self):
        path = self.root / "frozen.zip"
        sha = write_frozen_zip(path, synthetic_probes(n=15))
        with self.assertRaises(tq.TaskQGateError):
            tq.load_frozen_probes(path, sha)
        sha = write_frozen_zip(path, synthetic_probes(multi=3))
        with self.assertRaises(tq.TaskQGateError):
            tq.load_frozen_probes(path, sha)

    def plan(self):
        return ff.build_task_q_run_plan("a" * 64, "1" * 40, "c" * 64, "d" * 64)

    def test_05_candidate_depth_change_rejected(self):
        with self.assertRaises(tq.TaskQGateError):
            tq.check_core_matches_plan(dict(self.plan(), candidate_depth=50))
        fake_m = mock.MagicMock(MODEL_ID=M.MODEL_ID, MODEL_REVISION=M.MODEL_REVISION,
                                CANDIDATE_DEPTH=20, EXECUTION_DEVICE="cpu", DTYPE="float32")
        with self.assertRaises(tq.TaskQGateError):
            tq.check_core_matches_plan(self.plan(), m_core=fake_m)

    def test_06_wrong_model_revision_rejected(self):
        plan = copy.deepcopy(self.plan())
        plan["method_K"]["revision"] = "f" * 40
        with self.assertRaises(tq.TaskQGateError):
            tq.check_core_matches_plan(plan)
        plan = copy.deepcopy(self.plan())
        plan["method_M"]["revision"] = "f" * 40
        with self.assertRaises(tq.TaskQGateError):
            tq.check_core_matches_plan(plan)

    def test_core_constants_match_preregistered_plan(self):
        tq.check_core_matches_plan(self.plan())

    def test_11_run_plan_modification_rejected(self):
        frozen = self.root / "frozen.zip"
        sha = write_frozen_zip(frozen, synthetic_probes())
        plan_path = self.root / "plan.yaml"
        plan_path.write_text(yaml.safe_dump(ff.build_task_q_run_plan(sha, "1" * 40, "c" * 64, "d" * 64)))
        good_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()
        tq.verify_run_plan(plan_path, good_sha, frozen)
        plan_path.write_text(plan_path.read_text().replace("top_k: 10", "top_k: 20"))
        with self.assertRaises(tq.TaskQGateError):
            tq.verify_run_plan(plan_path, good_sha, frozen)
        new_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()
        with self.assertRaises(tq.TaskQGateError):
            tq.verify_run_plan(plan_path, new_sha, frozen)


class TestRankingStages(unittest.TestCase):
    def setUp(self):
        self.doc_ids = [f"C{i:02d}" for i in range(40)]
        self.chapters = {d: 1 + i // 4 for i, d in enumerate(self.doc_ids)}
        rng = np.random.default_rng(0)
        emb = rng.normal(size=(40, 8))
        self.emb = emb / np.linalg.norm(emb, axis=1, keepdims=True)
        self.q = self.emb[5] + 0.1

    def test_07_k_cutoff_enforced(self):
        query = tq.RankingQuery(0, "q", 3)
        ids = tq.k_rank(query, self.q, self.doc_ids, self.emb, self.chapters)
        self.assertEqual(set(ids), {d for d, c in self.chapters.items() if c <= 3})
        self.assertEqual(len(ids), 12)

    def test_08_m_candidate_equality_enforced(self):
        k_ids = self.doc_ids[:35]
        texts = {d: d for d in self.doc_ids}
        result = tq.m_rank(tq.RankingQuery(0, "q", 30), k_ids, texts, lambda q, p: -int(p[1:]))
        self.assertEqual(set(result["reranked_top"]), set(k_ids[:30]))
        self.assertEqual(result["evaluated_ranking"][30:], k_ids[30:])
        with mock.patch.object(M, "rerank_order", lambda c, s: [(x, s[x]) for x in c[:-1]]):
            with self.assertRaises(M.CandidateSetError):
                tq.m_rank(tq.RankingQuery(0, "q", 30), k_ids, texts, lambda q, p: 0.0)

    def test_m_small_pool_uses_whole_pool(self):
        k_ids = self.doc_ids[:10]
        result = tq.m_rank(tq.RankingQuery(0, "q", 3), k_ids, {d: d for d in k_ids}, lambda q, p: 0.0)
        self.assertEqual(result["candidates"], k_ids)

    def test_09_o_selector_receives_no_gold_metadata(self):
        self.assertEqual({f for f in tq.RankingQuery.__dataclass_fields__}, {"index", "question", "cutoff_chapter"})
        view = tq.ranking_view(synthetic_probes())
        self.assertFalse(any(hasattr(v, "gold_evidence_sets") for v in view))
        captured = {}
        real = O.select_consensus

        def spy(k, m, expected_depth):
            captured["args"] = (k, m, expected_depth)
            return real(k, m, expected_depth=expected_depth)

        k_ids = self.doc_ids[:35]
        m_top = list(reversed(k_ids[:30]))
        with mock.patch.object(O, "select_consensus", spy):
            result = tq.o_rank(k_ids, m_top)
        k_arg, m_arg, depth = captured["args"]
        self.assertTrue(all(isinstance(x, str) for x in k_arg + m_arg))
        self.assertEqual(depth, 30)
        self.assertEqual(result["evaluated_ranking"][30:], k_ids[30:])

    def test_o_small_pool_depth_is_pool_size(self):
        k_ids = self.doc_ids[:10]
        self.assertEqual(tq.o_rank(k_ids, list(reversed(k_ids)))["depth"], 10)


class TestMetricsAndStatistics(unittest.TestCase):
    def test_10_multi_gold_metrics_correct(self):
        probe = {"gold_evidence_sets": [["A", "B", "C"], ["A", "B", "D"]]}
        m = tq.probe_metrics(probe, ["X", "A", "B", "D"] + [f"Z{i}" for i in range(10)])
        self.assertEqual(m, {"success@10": 1, "recall@10": 1.0, "hit@10": 1, "mrr": 0.5})

    def test_descriptive_classes(self):
        self.assertEqual(tq.descriptive_class({"success@10": 0.1, "recall@10": 0.0, "hit@10": 0.0, "mrr": -1}),
                         "DESCRIPTIVE_SUPPORT")
        self.assertEqual(tq.descriptive_class({"success@10": 0.1, "recall@10": 0.0, "hit@10": -0.1, "mrr": 0}),
                         "MIXED_TRADE_OFF")
        self.assertEqual(tq.descriptive_class({"success@10": 0.0, "recall@10": -0.1, "hit@10": 0.0, "mrr": 1}),
                         "NO_OBSERVED_GAIN")
        self.assertEqual(tq.descriptive_class({"success@10": 0.0, "recall@10": 0.1, "hit@10": 0.0, "mrr": 0}),
                         "PREREGISTERED_RULES_DO_NOT_COVER")
        self.assertEqual(tq.descriptive_class({k: 0 for k in tq.METRIC_KEYS}, integrity_ok=False), "NOT_EVALUABLE")

    def test_mcnemar_exact(self):
        m = [0, 0, 0, 1, 1, 1, 1, 0]
        o = [1, 1, 1, 1, 1, 0, 1, 0]
        r = tq.mcnemar_exact(m, o)
        self.assertEqual((r["m_fail_o_success"], r["m_success_o_fail"]), (3, 1))
        self.assertAlmostEqual(r["p_value_two_sided"], 0.625)
        self.assertEqual(tq.mcnemar_exact([1, 0], [1, 0])["p_value_two_sided"], 1.0)

    def test_paired_permutation_exact(self):
        r = tq.paired_permutation_exact([0, 0, 0], [1, 1, 1])
        self.assertEqual(r["permutations"], 8)
        self.assertAlmostEqual(r["p_value_two_sided"], 0.25)

    def test_bootstrap_deterministic_and_paired(self):
        m, o = [0, 1, 0, 1, 0], [1, 1, 0, 1, 1]
        a = tq.paired_bootstrap(m, o, 1000, 42)
        self.assertEqual(a, tq.paired_bootstrap(m, o, 1000, 42))
        self.assertAlmostEqual(a["observed_delta"], 0.4)
        self.assertEqual(tq.paired_bootstrap(m, m, 1000, 42)["ci95_high"], 0.0)

    def test_12_private_leakage_in_public_summary_rejected(self):
        self.assertEqual(tq.check_public_summary({"aggregates": {"O": {"success@10": 0.5}}}), [])
        synthetic_japanese = "".join(map(chr, (0x30C6, 0x30B9, 0x30C8)))
        for bad in ({"note": "ch999_c9999"}, {"note": "V_SYNTH_99"}, {"note": synthetic_japanese},
                    {"per_probe": [1]}, {"x": {"evaluated_ranking": []}}):
            self.assertTrue(tq.check_public_summary(bad), bad)


if __name__ == "__main__":
    unittest.main()
