import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

import yaml

from tools.story_benchmark.analyze_m_failure_modes_v1 import (
    GateFailure,
    M_FILES,
    enrichment_statement,
    find_private_leaks,
    is_truncation_exposed,
    missing_bucket,
    probe_label,
    rank_of,
    run,
    score_gap_to_top10,
    stats,
    truncation_summary,
    verify_determinism,
)
from tools.story_benchmark.dense_e5_large_v1 import calculate_metrics
from tools.story_benchmark.run_bm25_lexical_v1 import compute_spoiler_violations

REPO = Path(__file__).resolve().parents[2]


class TestHelpers(unittest.TestCase):

    def test_rank_extraction(self):
        self.assertEqual(rank_of("b", ["a", "b"]), 2)
        self.assertIsNone(rank_of("z", ["a"]))

    def test_bucket_boundaries(self):
        with self.assertRaises(ValueError):
            missing_bucket(10)
        self.assertEqual(missing_bucket(11), "11-15")
        self.assertEqual(missing_bucket(15), "11-15")
        self.assertEqual(missing_bucket(16), "16-20")
        self.assertEqual(missing_bucket(20), "16-20")
        self.assertEqual(missing_bucket(21), "21-30")
        self.assertEqual(missing_bucket(30), "21-30")
        with self.assertRaises(GateFailure):
            missing_bucket(31)
        with self.assertRaises(GateFailure):
            missing_bucket(None)

    def test_score_gap_and_truncation_flag(self):
        self.assertAlmostEqual(score_gap_to_top10(2.5, 1.0), 1.5)
        self.assertLessEqual(score_gap_to_top10(2.5, 3.0), 0)
        self.assertFalse(is_truncation_exposed(512))
        self.assertTrue(is_truncation_exposed(513))

    def test_labels_and_flag_orthogonal(self):
        self.assertEqual(probe_label([11, 15]), "NEAR_BOUNDARY_ORDERING")
        self.assertEqual(probe_label([11, 16]), "MID_POOL_ORDERING")
        self.assertEqual(probe_label([30]), "MID_POOL_ORDERING")
        with self.assertRaises(ValueError):
            probe_label([])

    def test_stats_truncation_enrichment(self):
        s = stats([3, 1, 2, 10])
        self.assertEqual((s["min"], s["median"], s["max"], s["mean"]), (1.0, 2.5, 10.0, 4.0))
        t = truncation_summary([True, False, True])
        self.assertEqual((t["truncated_count"], t["non_truncated_count"]), (2, 1))
        self.assertEqual(enrichment_statement(0.9, 0.6)["statement"], "associated with truncation exposure")
        self.assertEqual(enrichment_statement(0.7, 0.6)["statement"], "no clear enrichment in truncation exposure")
        self.assertEqual(enrichment_statement(None, 0.6)["statement"], "insufficient data")

    def test_privacy_scan(self):
        self.assertEqual(find_private_leaks("n: 3", ["secret?"]), [])
        self.assertIn("<chunk-id pattern>", find_private_leaks("ch001_c0001", []))
        self.assertIn("<probe-id pattern>", find_private_leaks("P_TEST_99", []))


# ---------------------------------------------------------------------------
# End-to-end with synthetic M artifacts
# ---------------------------------------------------------------------------

def _move(lst, item, pos):
    lst = [x for x in lst if x != item]
    lst.insert(pos - 1, item)
    return lst


class TestEndToEnd(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        ids = [f"ch{(i // 3) + 1:03d}_c{(i % 3) + 1:04d}" for i in range(60)]
        meta = {c: int(c[2:5]) for c in ids}
        k_rank = ids  # K rank of ids[i] is i+1
        # A: failure, missing unit K2 -> M12 (near boundary, truncation exposed, worsened)
        # B: failure, missing unit K20 -> M18 (mid pool, not truncated, improved)
        # C: not candidate-complete (K40)
        # D: candidate-complete success
        spec = {
            "SYN_A": ([ids[0], ids[1]], {ids[0]: 1, ids[1]: 12}),
            "SYN_B": ([ids[4], ids[19], ids[24]], {ids[4]: 3, ids[19]: 18, ids[24]: 4}),
            "SYN_C": ([ids[2], ids[39]], {}),
            "SYN_D": ([ids[5], ids[6]], {ids[5]: 1, ids[6]: 2}),
        }
        self.probes = [{"probe_id": pid, "category": f"CAT{i}", "question": f"synthetic question {i}?",
                        "expected_answer": f"synthetic answer {i}", "cutoff_chapter": 20,
                        "required_evidence_chunk_ids": req} for i, (pid, (req, _)) in enumerate(spec.items())]
        tokens = {c: 300 for c in ids}
        tokens[ids[1]] = 700      # A's missing unit: truncation-exposed
        tokens[ids[0]] = 900      # A's promoted unit also exposed
        self.paths = {k: root / v for k, v in {
            "probes": "probes.yaml", "chunks": "chunks.jsonl", "freeze": "freeze.yaml", "k_result": "K.yaml",
            "k_detail": "K.jsonl", "m_result": "M.yaml", "m_dir": "M", "out_dir": "out"}.items()}
        self.paths["m_dir"].mkdir()
        with open(self.paths["probes"], "w", encoding="utf-8") as f:
            yaml.dump({"probes": self.probes}, f)
        self.paths["chunks"].write_text("".join(json.dumps({"chunk_id": c, "chapter_number": meta[c]}) + "\n" for c in ids), encoding="utf-8")
        self.paths["k_detail"].write_text("".join(json.dumps({"probe_id": p["probe_id"], "retrieved_chunk_ids": k_rank}) + "\n"
                                                  for p in self.probes), encoding="utf-8")
        reranked, trans, ptrans, pairs, mrows = [], [], [], [], []
        for p in self.probes:
            pid, req = p["probe_id"], p["required_evidence_chunk_ids"]
            top = k_rank[:30]
            for c, pos in sorted(spec[pid][1].items(), key=lambda x: x[1]):
                top = _move(top, c, pos)
            scores = [float(30 - i) for i in range(30)]
            full = top + k_rank[30:]
            m = calculate_metrics(p, full)
            m.update(compute_spoiler_violations(p, full, meta))
            mrows.append(m)
            reranked.append({"probe_id": pid, "category": p["category"], "reranked_top_candidates": top,
                             "scores": scores, "evaluated_ranking": full, "metrics": m})
            for c in top:
                pairs.append({"probe_id": pid, "chunk_id": c, "k_rank": k_rank.index(c) + 1,
                              "score": scores[top.index(c)], "query_tokens": 5, "passage_tokens": tokens[c]})
            kin, rin = [], []
            for c in req:
                kr, rr = k_rank.index(c) + 1, full.index(c) + 1
                t = ("STAY_TOP10" if kr <= 10 and rr <= 10 else "K_TOP10_LOST_BY_RERANK" if kr <= 10
                     else "RERANK_TOP10_GAIN_FROM_K" if rr <= 10 else "STAY_OUTSIDE_TOP10")
                trans.append({"probe_id": pid, "category": p["category"], "chunk_id": c, "k_rank": kr,
                              "reranked_rank": rr, "transition": t})
                kin.append(kr <= 10)
                rin.append(rr <= 10)
            ptrans.append({"probe_id": pid, "k_hit": any(kin), "r_hit": any(rin), "k_full": all(kin),
                           "r_full": all(rin), "candidate_complete": all(c in k_rank[:30] for c in req)})
        for name, rows in zip(M_FILES, (reranked, trans, ptrans, pairs)):
            (self.paths["m_dir"] / name).write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
        sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
        keys = list(mrows[0].keys())
        overall = {k: sum(r[k] for r in mrows) / len(mrows) for k in keys}
        self.m_res = {
            "detailed_results_sha256": {n: sha(self.paths["m_dir"] / n) for n in M_FILES},
            "RERANKED": {"overall": overall},
            "required_evidence_transitions": {"counts": {t: sum(1 for r in trans if r["transition"] == t) for t in
                                                         ("STAY_TOP10", "K_TOP10_LOST_BY_RERANK", "RERANK_TOP10_GAIN_FROM_K", "STAY_OUTSIDE_TOP10")}},
            "candidate_ceiling": {"candidate_complete_probes": sum(1 for r in ptrans if r["candidate_complete"])},
            "probe_transitions": {"reranked_full_success_probes": sum(1 for r in ptrans if r["r_full"])},
            "truncation_diagnostics": {"passage_truncation_count": sum(1 for r in pairs if r["passage_tokens"] > 512)},
        }
        with open(self.paths["m_result"], "w") as f:
            yaml.dump(self.m_res, f)
        with open(self.paths["k_result"], "w") as f:
            yaml.dump({"detailed_results_sha256": {"cutoff_filtered_per_probe.jsonl": sha(self.paths["k_detail"])}}, f)
        with open(self.paths["freeze"], "w") as f:
            yaml.dump({"status": "FROZEN", "probe_file_sha256": sha(self.paths["probes"]),
                       "chunks_jsonl_sha256": sha(self.paths["chunks"])}, f)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self):
        return run(self.paths, expected_population=(4, 9))

    def test_population_and_diagnostics(self):
        pub, forbidden = self._run()
        pop = pub["population"]
        self.assertEqual((pop["candidate_complete_probes"], pop["candidate_complete_failure_probes"]), (3, 2))
        self.assertEqual(pop["missing_required_units"], 2)
        self.assertEqual(pop["promoted_required_units"], 3)
        b = pub["missing_required_rank_distribution"]["buckets"]
        self.assertEqual((b["11-15"]["count"], b["16-20"]["count"], b["21-30"]["count"]), (1, 1, 0))
        mv = pub["rank_movement"]
        self.assertEqual((mv["improved_m_lt_k"], mv["unchanged"], mv["worsened_m_gt_k"]), (1, 0, 1))
        # scores = 30 - (rank-1): rank-10 score 21; rank 12 -> 19 (gap 2); rank 18 -> 13 (gap 8)
        gap = pub["top10_score_gap"]["missing_units"]
        self.assertEqual((gap["min"], gap["max"], gap["median"]), (2.0, 8.0, 5.0))
        tr = pub["truncation_exposure"]
        self.assertEqual((tr["missing_required_units"]["truncated_count"], tr["missing_required_units"]["count"]), (1, 2))
        self.assertEqual((tr["promoted_required_units_same_probes"]["truncated_count"],
                          tr["promoted_required_units_same_probes"]["count"]), (1, 3))
        fm = pub["probe_failure_modes"]
        self.assertEqual((fm["all_missing_rank_11_15"], fm["any_missing_rank_16_30"]), (1, 1))
        self.assertEqual(fm["label_counts"], {"MID_POOL_ORDERING+NOT_TRUNCATION_EXPOSED": 1,
                                              "NEAR_BOUNDARY_ORDERING+TRUNCATION_EXPOSED": 1})
        ctx = pub["candidate_complete_transition_context"]
        self.assertEqual((ctx["k_top10_to_m_top10"], ctx["k_top10_to_m_outside"], ctx["k_outside_to_m_top10"],
                          ctx["outside_both"]), (2, 1, 1, 1))
        self.assertIn("not the exact evidence token span", pub["interpretation_limit"])
        text = yaml.dump(pub, sort_keys=False, allow_unicode=True)
        self.assertEqual(find_private_leaks(text, forbidden), [])

    def test_deterministic_rerun(self):
        a, _ = self._run()
        b, _ = self._run()
        self.assertTrue(verify_determinism(a, b))

    def test_source_sha_mismatch(self):
        p = self.paths["m_dir"] / "pair_scores.jsonl"
        p.write_text(p.read_text() + "\n", encoding="utf-8")
        with self.assertRaisesRegex(GateFailure, "m_pair_scores.jsonl sha256 mismatch"):
            self._run()

    def test_missing_artifact(self):
        (self.paths["m_dir"] / "probe_transitions.jsonl").unlink()
        with self.assertRaisesRegex(GateFailure, "missing required artifact"):
            self._run()

    def test_m_reproduction_gate(self):
        self.m_res["candidate_ceiling"]["candidate_complete_probes"] = 9
        with open(self.paths["m_result"], "w") as f:
            yaml.dump(self.m_res, f)
        with self.assertRaisesRegex(GateFailure, "candidate-complete count not reproduced"):
            self._run()

    def test_population_gate(self):
        with self.assertRaisesRegex(GateFailure, "population"):
            run(self.paths)  # default expects 15 / 35


class TestPublicResult(unittest.TestCase):

    def test_public_aggregate_only(self):
        pub = REPO / "benchmarks/m1_script_quality/long_range_probe"
        files = [pub / "M_FAILURE_MODE_DIAGNOSTIC_V1_RESULT.yaml", pub / "M_FAILURE_MODE_DIAGNOSTIC_V1_METHOD.md"]
        present = [f for f in files if f.exists()]
        if not present:
            self.skipTest("not generated yet")
        for f in present:
            text = f.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"ch\d{3}_c\d{4}", text), f.name)
            self.assertIsNone(re.search(r"\bP_[A-Z]+_\d{2}\b", text), f.name)
            self.assertNotIn("TRUNCATION_CAUSED", text)
        if files[0].exists():
            data = yaml.safe_load(files[0].read_text(encoding="utf-8"))
            self.assertEqual((data["determinism_status"], data["privacy_status"]), ("PASS", "PASS"))
            self.assertIn("not the exact evidence token span", data["interpretation_limit"])
            self.assertNotIn("verdict", data)


if __name__ == "__main__":
    unittest.main()
