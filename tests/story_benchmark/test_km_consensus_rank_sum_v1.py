"""
Unit tests for KM_CONSENSUS_RANK_SUM_V1 (TASK M1-30CH-O)
"""
import inspect
import tempfile
import unittest
from pathlib import Path

from tools.story_benchmark.km_consensus_rank_sum_v1 import (
    CANDIDATE_DEPTH,
    CandidateSetError,
    evaluated_ranking,
    interpret_verdict,
    rank_bucket,
    rank_of,
    rank_sum_details,
    select_consensus,
    transition_type,
    within,
)
from tools.story_benchmark.run_km_consensus_rank_sum_v1 import (
    GateFailure,
    find_private_leaks,
    run_experiment,
    verify_inputs,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class TestConsensusSelector(unittest.TestCase):

    def test_rank_sum_calculation(self):
        # 30 unique dummy IDs
        cands = [f"c_{i:02d}" for i in range(1, 31)]
        k_cands = list(cands)
        # Reverse in M: c_01 is k_rank 1, m_rank 30 -> sum 31
        # c_15 is k_rank 15, m_rank 16 -> sum 31
        m_cands = list(reversed(cands))

        details = rank_sum_details(k_cands, m_cands)
        self.assertEqual(details["c_01"]["k_rank"], 1)
        self.assertEqual(details["c_01"]["m_rank"], 30)
        self.assertEqual(details["c_01"]["rank_sum"], 31)

        # Candidate with both rank 1
        c_k = ["c_a", "c_b"] + [f"c_{i}" for i in range(28)]
        c_m = ["c_b", "c_a"] + [f"c_{i}" for i in range(28)]
        det = rank_sum_details(c_k, c_m)
        self.assertEqual(det["c_a"]["rank_sum"], 3)  # k=1, m=2 -> 3
        self.assertEqual(det["c_b"]["rank_sum"], 3)  # k=2, m=1 -> 3

    def test_symmetry(self):
        # Swapping K and M rankings MUST produce the exact same consensus ordering
        k_cands = [f"c_{i:02d}" for i in range(1, 31)]
        import random
        rng = random.Random(12345)
        m_cands = list(k_cands)
        rng.shuffle(m_cands)

        order_km = select_consensus(k_cands, m_cands)
        order_mk = select_consensus(m_cands, k_cands)
        self.assertEqual(order_km, order_mk)

    def test_tie_break(self):
        # 1. Primary: lower rank_sum
        # 2. Tie 1: lower max(k_rank, m_rank)
        # 3. Tie 2: lower min(k_rank, m_rank)
        # 4. Tie 3: chunk_id ASC

        # Create 4 candidates with specific ranks:
        # cand_A: k=1, m=9 -> sum=10, max=9, min=1
        # cand_B: k=5, m=5 -> sum=10, max=5, min=5
        # cand_C: k=2, m=2 -> sum=4,  max=2, min=2
        # cand_D1: k=3, m=7 -> sum=10, max=7, min=3, id="chunk_x"
        # cand_D2: k=7, m=3 -> sum=10, max=7, min=3, id="chunk_a"
        pool = ["chunk_c", "cand_a", "cand_b", "chunk_x", "chunk_a"] + [f"pad_{i:02d}" for i in range(25)]
        
        # Build k_list and m_list to assign exact desired ranks (1-based)
        k_list = [""] * 30
        m_list = [""] * 30

        # Keep test items strictly in indices 0..4 so all pads occupy indices 5..29 (sum >= 12)
        # cand_c:  k=1, m=1 -> sum=2, max=1, min=1
        # cand_b:  k=2, m=2 -> sum=4, max=2, min=2
        # chunk_x: k=4, m=4 -> sum=8, max=4, min=4
        # cand_a:  k=3, m=5 -> sum=8, max=5, min=3 (id="cand_a")
        # chunk_a: k=5, m=3 -> sum=8, max=5, min=3 (id="chunk_a")

        k_list = ["cand_c", "cand_b", "cand_a", "chunk_x", "chunk_a"] + [f"pad_{i:02d}" for i in range(25)]
        m_list = ["cand_c", "cand_b", "chunk_a", "chunk_x", "cand_a"] + [f"pad_{i:02d}" for i in range(25)]

        res = select_consensus(k_list, m_list)
        # 1. cand_c has sum=2 -> rank 1
        self.assertEqual(res[0], "cand_c")
        # 2. cand_b has sum=4 -> rank 2
        self.assertEqual(res[1], "cand_b")
        # 3. chunk_x has sum=8, max=4 < 5 -> rank 3
        self.assertEqual(res[2], "chunk_x")
        # 4. cand_a and chunk_a both have sum=8, max=5, min=3
        #    chunk_id tie-break: "cand_a" < "chunk_a"
        self.assertEqual(res[3], "cand_a")
        self.assertEqual(res[4], "chunk_a")

    def test_candidate_set_equality(self):
        cands1 = [f"c_{i:02d}" for i in range(1, 31)]
        cands2 = [f"c_{i:02d}" for i in range(2, 32)]  # different elements
        with self.assertRaises(CandidateSetError):
            select_consensus(cands1, cands2)

    def test_candidate_count_30(self):
        cands = [f"c_{i:02d}" for i in range(1, 25)]  # only 24
        with self.assertRaises(CandidateSetError):
            select_consensus(cands, cands, expected_depth=30)

    def test_duplicate_candidate_rejection(self):
        cands = [f"c_{i:02d}" for i in range(1, 30)] + ["c_01"]  # duplicate c_01
        with self.assertRaises(CandidateSetError):
            select_consensus(cands, cands)

    def test_selector_api_contains_no_gold_inputs(self):
        # Pure selector function signature inspection
        sig = inspect.signature(select_consensus)
        param_names = list(sig.parameters.keys())
        # Must only contain candidate lists and optional depth
        self.assertEqual(param_names, ["k_candidate_ids", "m_candidate_ids", "expected_depth"])
        for forbidden in ("probe", "gold", "answer", "question", "category", "label", "failure"):
            self.assertFalse(any(forbidden in p for p in param_names))


class TestEvaluatorHelpers(unittest.TestCase):

    def test_rank_of_and_within(self):
        ranking = ["a", "b", "c", "d"]
        self.assertEqual(rank_of("a", ranking), 1)
        self.assertEqual(rank_of("c", ranking), 3)
        self.assertIsNone(rank_of("z", ranking))
        self.assertTrue(within(1, 10))
        self.assertTrue(within(10, 10))
        self.assertFalse(within(11, 10))
        self.assertFalse(within(None, 10))

    def test_evaluated_ranking_tail(self):
        top30 = [f"c_{i:02d}" for i in range(1, 31)]
        k_ranking = top30 + [f"tail_{i:02d}" for i in range(1, 11)]
        # Reorder top30
        rev_top30 = list(reversed(top30))
        full = evaluated_ranking(rev_top30, k_ranking)
        self.assertEqual(len(full), 40)
        self.assertEqual(full[:30], rev_top30)
        self.assertEqual(full[30:], [f"tail_{i:02d}" for i in range(1, 11)])

    def test_transition_types(self):
        self.assertEqual(transition_type(5, 5), "STAY_TOP10")
        self.assertEqual(transition_type(5, 12), "M_TOP10_LOST_BY_CONSENSUS")
        self.assertEqual(transition_type(12, 5), "CONSENSUS_TOP10_GAIN_FROM_M")
        self.assertEqual(transition_type(12, 12), "STAY_OUTSIDE_TOP10")

    def test_rank_buckets(self):
        self.assertEqual(rank_bucket(None), "missing")
        self.assertEqual(rank_bucket(5), "<=10")
        self.assertEqual(rank_bucket(10), "<=10")
        self.assertEqual(rank_bucket(11), "11-15")
        self.assertEqual(rank_bucket(15), "11-15")
        self.assertEqual(rank_bucket(16), "16-20")
        self.assertEqual(rank_bucket(20), "16-20")
        self.assertEqual(rank_bucket(21), "21-30")
        self.assertEqual(rank_bucket(30), "21-30")
        self.assertEqual(rank_bucket(35), ">30")

    def test_verdict_rules(self):
        # SUPPORTED
        self.assertEqual(
            interpret_verdict(
                delta_success10=0.0667, delta_recall10=0.01, delta_hit10=0.0,
                full_success_gained=2, full_success_lost=1, gates_passed=True
            ),
            "SUPPORTED"
        )
        # PARTIALLY_SUPPORTED: success up, but lost >= gained
        self.assertEqual(
            interpret_verdict(
                delta_success10=0.0667, delta_recall10=0.01, delta_hit10=0.0,
                full_success_gained=1, full_success_lost=1, gates_passed=True
            ),
            "PARTIALLY_SUPPORTED"
        )
        # PARTIALLY_SUPPORTED: success flat, recall up
        self.assertEqual(
            interpret_verdict(
                delta_success10=0.0, delta_recall10=0.05, delta_hit10=0.0,
                full_success_gained=0, full_success_lost=0, gates_passed=True
            ),
            "PARTIALLY_SUPPORTED"
        )
        # NOT_SUPPORTED: all <= 0
        self.assertEqual(
            interpret_verdict(
                delta_success10=0.0, delta_recall10=0.0, delta_hit10=0.0,
                full_success_gained=0, full_success_lost=0, gates_passed=True
            ),
            "NOT_SUPPORTED"
        )
        self.assertEqual(
            interpret_verdict(
                delta_success10=-0.05, delta_recall10=-0.02, delta_hit10=0.0,
                full_success_gained=0, full_success_lost=1, gates_passed=True
            ),
            "NOT_SUPPORTED"
        )
        # NOT_EVALUABLE
        self.assertEqual(
            interpret_verdict(
                delta_success10=0.1, delta_recall10=0.1, delta_hit10=0.1,
                full_success_gained=2, full_success_lost=0, gates_passed=False
            ),
            "NOT_EVALUABLE"
        )


class TestPrivacyAndIntegrityGates(unittest.TestCase):

    def test_privacy_leak_detection(self):
        text_clean = "candidate_complete_probes: 12\nverdict: SUPPORTED\n"
        self.assertEqual(find_private_leaks(text_clean, ["secret question?"]), [])

        text_leak_probe = "probe: P_CHRONO_01 failed"
        self.assertIn("<probe-id pattern>", find_private_leaks(text_leak_probe, []))

        text_leak_chunk = "evidence chunk ch005_c0012 was selected"
        self.assertIn("<chunk-id pattern>", find_private_leaks(text_leak_chunk, []))

        text_leak_question = "We asked: What was Mahiru's umbrella color?"
        self.assertIn("What was Mahiru's umbrella color?", find_private_leaks(text_leak_question, ["What was Mahiru's umbrella color?"]))

    def test_input_gate_missing_artifact(self):
        paths = {
            "freeze": REPO_ROOT / "nonexistent_file.yaml",
            "probes": REPO_ROOT / ".local" / "story_integration" / "otonari_30ch" / "LONG_RANGE_PROBE_V1" / "probes.yaml",
            "chunks": REPO_ROOT / ".local" / "story_integration" / "otonari_30ch" / "PARAGRAPH_PACK_V1" / "chunks.jsonl",
            "k_detail": REPO_ROOT / ".local" / "story_integration" / "otonari_30ch" / "DENSE_E5_LARGE_V1" / "cutoff_filtered_per_probe.jsonl",
            "m_detail": REPO_ROOT / ".local" / "story_integration" / "otonari_30ch" / "BGE_RERANKER_V2_M3_TOP30_V1" / "reranked_per_probe.jsonl",
            "k_result": REPO_ROOT / "benchmarks" / "m1_script_quality" / "long_range_probe" / "DENSE_E5_LARGE_V1_RESULT.yaml",
            "m_result": REPO_ROOT / "benchmarks" / "m1_script_quality" / "long_range_probe" / "BGE_RERANKER_V2_M3_TOP30_V1_RESULT.yaml",
            "n_result": REPO_ROOT / "benchmarks" / "m1_script_quality" / "long_range_probe" / "M_FAILURE_MODE_DIAGNOSTIC_V1_RESULT.yaml",
            "out_dir": REPO_ROOT / ".local" / "story_integration" / "otonari_30ch" / "KM_CONSENSUS_RANK_SUM_V1",
        }
        with self.assertRaises(GateFailure):
            verify_inputs(paths)


class TestFullExperimentRun(unittest.TestCase):

    def test_real_artifacts_execution_and_determinism(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "test_out"
            paths = {
                "freeze": REPO_ROOT / "benchmarks" / "m1_script_quality" / "long_range_probe" / "LONG_RANGE_PROBE_V1_FREEZE.yaml",
                "probes": REPO_ROOT / ".local" / "story_integration" / "otonari_30ch" / "LONG_RANGE_PROBE_V1" / "probes.yaml",
                "chunks": REPO_ROOT / ".local" / "story_integration" / "otonari_30ch" / "PARAGRAPH_PACK_V1" / "chunks.jsonl",
                "k_detail": REPO_ROOT / ".local" / "story_integration" / "otonari_30ch" / "DENSE_E5_LARGE_V1" / "cutoff_filtered_per_probe.jsonl",
                "m_detail": REPO_ROOT / ".local" / "story_integration" / "otonari_30ch" / "BGE_RERANKER_V2_M3_TOP30_V1" / "reranked_per_probe.jsonl",
                "k_result": REPO_ROOT / "benchmarks" / "m1_script_quality" / "long_range_probe" / "DENSE_E5_LARGE_V1_RESULT.yaml",
                "m_result": REPO_ROOT / "benchmarks" / "m1_script_quality" / "long_range_probe" / "BGE_RERANKER_V2_M3_TOP30_V1_RESULT.yaml",
                "n_result": REPO_ROOT / "benchmarks" / "m1_script_quality" / "long_range_probe" / "M_FAILURE_MODE_DIAGNOSTIC_V1_RESULT.yaml",
                "out_dir": out_dir,
            }

            run1 = run_experiment(paths)
            run2 = run_experiment(paths)

            # Determinism
            self.assertEqual(run1["local_hashes"], run2["local_hashes"])
            res = run1["result"]

            # Candidate ceiling check:
            self.assertEqual(res["candidate_ceiling"]["candidate_complete_probes"], 12)

            # Transition count check:
            trans_sum = sum(res["required_evidence_transitions"]["counts"].values())
            self.assertEqual(trans_sum, 35)

            # N population check:
            self.assertEqual(res["n_failure_population"]["population_size"], 8)
            self.assertEqual(res["n_failure_population"]["missing_units_analysis"]["count"], 8)

            # Check primary metrics structure exists
            self.assertIn("Full_Evidence_Success@10", res["M_COMPARISON"]["overall"])
            self.assertIn("Recall@10", res["M_COMPARISON"]["overall"])
            self.assertIn("Hit@10", res["M_COMPARISON"]["overall"])
            self.assertIn("MRR", res["M_COMPARISON"]["overall"])


if __name__ == "__main__":
    unittest.main()
