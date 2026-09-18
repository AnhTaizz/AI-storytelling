import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

import yaml

from tools.story_benchmark.analyze_missing_evidence_ranks_v1 import (
    GateFailure,
    analyze,
    best_query_rank,
    classify,
    completeness_at_k,
    find_private_leaks,
    is_fusion_bottleneck,
    rank_bucket,
    rank_of,
    run,
    verify_determinism,
    worst_required_rank,
    F_DETAIL,
    I_FUSED,
    I_PER_QUERY,
)


class TestPureHelpers(unittest.TestCase):

    def test_exact_rank_extraction(self):
        ranking = ["c1", "c2", "c3"]
        self.assertEqual(rank_of("c1", ranking), 1)
        self.assertEqual(rank_of("c3", ranking), 3)
        self.assertIsNone(rank_of("zz", ranking))

    def test_bucket_boundaries(self):
        self.assertEqual(rank_bucket(1), "TOP_10")
        self.assertEqual(rank_bucket(10), "TOP_10")
        self.assertEqual(rank_bucket(11), "NEAR_MISS")
        self.assertEqual(rank_bucket(20), "NEAR_MISS")
        self.assertEqual(rank_bucket(21), "MID_RANK")
        self.assertEqual(rank_bucket(50), "MID_RANK")
        self.assertEqual(rank_bucket(51), "DEEP_RANK")
        self.assertEqual(rank_bucket(None), "MISSING")
        with self.assertRaises(ValueError):
            rank_bucket(0)

    def test_worst_required_rank(self):
        self.assertEqual(worst_required_rank([3, 17, 9]), 17)
        self.assertIsNone(worst_required_rank([3, None]))

    def test_completeness_at_k(self):
        probe_ranks = [[1, 15], [2, 3], [40, 60]]
        c10 = completeness_at_k(probe_ranks, 10)
        self.assertAlmostEqual(c10["recall"], (0.5 + 1.0 + 0.0) / 3)
        self.assertAlmostEqual(c10["full_evidence_success"], 1 / 3)
        c20 = completeness_at_k(probe_ranks, 20)
        self.assertAlmostEqual(c20["full_evidence_success"], 2 / 3)
        c50 = completeness_at_k(probe_ranks, 50)
        self.assertAlmostEqual(c50["recall"], (1.0 + 1.0 + 0.5) / 3)
        self.assertAlmostEqual(c50["full_evidence_success"], 2 / 3)

    def test_best_query_rank(self):
        self.assertEqual(best_query_rank([12, 4, 4, 30]), (4, 1))
        self.assertEqual(best_query_rank([None, 7]), (7, 1))
        self.assertEqual(best_query_rank([None, None]), (None, None))

    def test_fusion_bottleneck_condition(self):
        self.assertTrue(is_fusion_bottleneck(15, 5, 12))
        self.assertFalse(is_fusion_bottleneck(15, 5, 9))    # fusion kept it
        self.assertFalse(is_fusion_bottleneck(15, 11, 12))  # no subquery surfaced it
        self.assertFalse(is_fusion_bottleneck(8, 5, 12))    # F already had it
        self.assertTrue(is_fusion_bottleneck(15, 10, 11))   # boundaries

    def test_classification(self):
        self.assertEqual(classify([11, 12, 13, 14, 15, 16, 17, 30, 40, 60]), "SHALLOW_RANKING_BOTTLENECK")  # 70%
        self.assertEqual(classify([11, 12, 13, 14, 15, 16, 30, 40, 60, 70]), "MIXED_REACHABILITY")          # 60/40
        self.assertEqual(classify([11, 12, 13, 14, 21, 22, 23, 24, 25, 26]), "DEEP_RELEVANCE_BOTTLENECK")   # 60% >20
        self.assertEqual(classify([11, 12, 13, 14, 15, 21, 22, 23, 24, 25]), "MIXED_REACHABILITY")          # exactly 50% >20
        self.assertEqual(classify([11, None]), "MIXED_REACHABILITY")
        self.assertEqual(classify([None, None, 12]), "DEEP_RELEVANCE_BOTTLENECK")
        self.assertEqual(classify([]), "NO_MISSED_EVIDENCE")

    def test_privacy_scan(self):
        self.assertEqual(find_private_leaks("recall: 0.5", ["P_X_01"]), [])
        self.assertIn("P_X_01", find_private_leaks("id: P_X_01", ["P_X_01"]))
        self.assertIn("<chunk-id pattern>", find_private_leaks("x: ch001_c0001", []))


# ---------------------------------------------------------------------------
# Synthetic end-to-end fixture
# ---------------------------------------------------------------------------

def _ids(n):
    return [f"ch{(i // 3) + 1:03d}_c{(i % 3) + 1:04d}" for i in range(n)]


class TestEndToEnd(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.root = root
        ids = _ids(60)
        # Probe A: required at F ranks 2 and 15; subquery puts rank-15 unit at 4, fused at 12 -> fusion bottleneck
        # Probe B: required at F ranks 1 and 5 -> success@10
        # Probe C: required at F ranks 30 and 55
        f_rank = {"SYN_A": [ids[1], ids[14]], "SYN_B": [ids[0], ids[4]], "SYN_C": [ids[29], ids[54]]}
        self.probes = [
            {"probe_id": pid, "category": cat, "question": f"synthetic question {pid}?",
             "expected_answer": f"synthetic answer {pid}", "cutoff_chapter": 30,
             "required_evidence_chunk_ids": req}
            for (pid, req), cat in zip(f_rank.items(), ["CAT1", "CAT1", "CAT2"])
        ]
        self.paths = {
            "probes": root / "probes.yaml", "chunks": root / "chunks.jsonl", "freeze": root / "freeze.yaml",
            "f_result": root / "F.yaml", "f_detail": root / "F" / F_DETAIL,
            "i_result": root / "I.yaml", "i_fused": root / "I" / I_FUSED, "i_per_query": root / "I" / I_PER_QUERY,
        }
        (root / "F").mkdir(); (root / "I").mkdir()
        with open(self.paths["probes"], "w", encoding="utf-8") as f:
            yaml.dump({"probes": self.probes}, f)
        self.paths["chunks"].write_text("".join(json.dumps({"chunk_id": c}) + "\n" for c in ids), encoding="utf-8")

        def move(lst, item, pos):
            lst = [x for x in lst if x != item]
            lst.insert(pos - 1, item)
            return lst

        f_rows, fused_rows, q_rows = [], [], []
        for p in self.probes:
            f_rows.append({"probe_id": p["probe_id"], "retrieved_chunk_ids": ids,
                           "scores": [1.0 - i * 0.01 for i in range(len(ids))]})
            q0 = ids
            q1 = move(ids, ids[14], 4) if p["probe_id"] == "SYN_A" else list(reversed(ids))
            fused = move(ids, ids[14], 12) if p["probe_id"] == "SYN_A" else ids
            fused_rows.append({"probe_id": p["probe_id"], "query_count": 2, "retrieved_chunk_ids": fused})
            for qi, r in enumerate([q0, q1]):
                q_rows.append({"probe_id": p["probe_id"], "mode": "CUTOFF_FILTERED", "query_index": qi,
                               "retrieved_chunk_ids": r})
                q_rows.append({"probe_id": p["probe_id"], "mode": "GLOBAL_DIAGNOSTIC", "query_index": qi,
                               "retrieved_chunk_ids": list(reversed(r))})
        for key, rows in (("f_detail", f_rows), ("i_fused", fused_rows), ("i_per_query", q_rows)):
            self.paths[key].write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

        sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
        with open(self.paths["freeze"], "w") as f:
            yaml.dump({"status": "FROZEN", "probe_count": 3, "probe_file_sha256": sha(self.paths["probes"]),
                       "chunks_jsonl_sha256": sha(self.paths["chunks"])}, f)
        with open(self.paths["f_result"], "w") as f:
            yaml.dump({"detailed_results_sha256": {F_DETAIL: sha(self.paths["f_detail"])},
                       "CUTOFF_FILTERED": {"overall": {"recall@10": (0.5 + 1.0 + 0.0) / 3, "success@10": 1 / 3}}}, f)
        with open(self.paths["i_result"], "w") as f:
            yaml.dump({"detailed_results_sha256": {I_FUSED: sha(self.paths["i_fused"]),
                                                   I_PER_QUERY: sha(self.paths["i_per_query"])}}, f)
        self.out = root / "out"

    def tearDown(self):
        self.tmp.cleanup()

    def test_end_to_end_values(self):
        pub, private = run(self.paths, self.out)
        self.assertEqual(pub["required_evidence_unit_count"], 6)
        self.assertEqual(pub["candidate_reachability"]["f_top10_missed_units"], 3)
        md = pub["f_missed_evidence_bucket_distribution"]
        self.assertEqual((md["rank_11_20"]["count"], md["rank_21_50"]["count"], md["rank_gt_50"]["count"],
                          md["missing"]["count"]), (1, 1, 1, 0))
        self.assertTrue(pub["missing_verified_zero"])
        r = pub["candidate_reachability"]
        self.assertEqual((r["probes_all_required_within_top20"], r["probes_all_required_within_top50"]), (2, 2))
        self.assertAlmostEqual(pub["probe_completeness_by_k"]["K20"]["full_evidence_success"], 2 / 3)
        mq = pub["multiquery_rank_diagnostic"]
        # SYN_A rank-15 unit (subquery 4, fused 12) and SYN_C rank-55 unit (reversed subquery -> 6, fused 55).
        self.assertEqual(mq["fusion_bottleneck_condition_count"], 2)
        self.assertEqual(mq["f_rank_gt10_and_some_i_query_top10"], 2)
        self.assertEqual(mq["f_rank_gt20_and_some_i_query_top20"], 1)
        self.assertFalse(mq["fusion_bottleneck_signal"])
        self.assertEqual(pub["classification"], "DEEP_RELEVANCE_BOTTLENECK")  # 2/3 > 20

        rows = [json.loads(l) for l in (self.out / "required_evidence_ranks.jsonl").read_text(encoding="utf-8").splitlines()]
        a = [u for u in rows if u["probe_id"] == "SYN_A" and u["f_rank"] == 15][0]
        self.assertEqual((a["i_best_query_rank"], a["i_best_query_index"], a["i_fused_rank"]), (4, 1, 12))
        self.assertAlmostEqual(a["f_score_gap_to_rank10"], 0.05)

    def test_deterministic_rerun(self):
        p1, _ = run(self.paths, self.out)
        p2, _ = run(self.paths, self.out)
        self.assertTrue(verify_determinism(p1, p2))
        self.assertFalse(verify_determinism(p1, dict(p2, classification="X")))

    def test_public_privacy(self):
        pub, private = run(self.paths, self.out)
        text = yaml.dump(pub, sort_keys=False, allow_unicode=True)
        self.assertEqual(find_private_leaks(text, private["forbidden_strings"]), [])
        self.assertIsNone(re.search(r"ch\d{3}_c\d{4}", text))
        for p in self.probes:
            self.assertNotIn(p["probe_id"], text)
            self.assertNotIn(p["question"], text)
            self.assertNotIn(p["expected_answer"], text)
        self.assertNotIn("retrieved_chunk_ids", text)

    def test_source_hash_gate(self):
        self.paths["i_per_query"].write_text(self.paths["i_per_query"].read_text(encoding="utf-8") + "\n ", encoding="utf-8")
        with self.assertRaisesRegex(GateFailure, "i_per_query_rankings sha256 mismatch"):
            run(self.paths, self.out)

    def test_missing_artifact(self):
        self.paths["f_detail"].unlink()
        with self.assertRaisesRegex(GateFailure, "missing required artifact"):
            run(self.paths, self.out)

    def test_k10_consistency_gate(self):
        with open(self.paths["f_result"]) as f:
            fr = yaml.safe_load(f)
        fr["CUTOFF_FILTERED"]["overall"]["success@10"] = 0.9
        with open(self.paths["f_result"], "w") as f:
            yaml.dump(fr, f)
        with self.assertRaisesRegex(GateFailure, "K=10"):
            run(self.paths, self.out)


class TestCommittedPublicResult(unittest.TestCase):

    def test_public_result_aggregate_only(self):
        pub = Path(__file__).resolve().parents[2] / "benchmarks/m1_script_quality/long_range_probe/MISSING_EVIDENCE_RANK_DIAGNOSTIC_V1_RESULT.yaml"
        if not pub.exists():
            self.skipTest("public result not generated yet")
        text = pub.read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"ch\d{3}_c\d{4}", text))
        self.assertIsNone(re.search(r"\bP_[A-Z]+_\d{2}\b", text))
        self.assertNotIn("?", text)
        self.assertNotIn("retrieved_chunk_ids", text)
        self.assertNotIn("required_chunk_id", text)
        data = yaml.safe_load(text)
        self.assertEqual(data["determinism_status"], "PASS")
        self.assertEqual(data["privacy_status"], "PASS")


if __name__ == "__main__":
    unittest.main()
