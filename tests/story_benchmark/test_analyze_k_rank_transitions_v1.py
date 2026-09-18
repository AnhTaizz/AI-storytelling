import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

import yaml

from tools.story_benchmark.analyze_k_rank_transitions_v1 import (
    GateFailure,
    bool_transition,
    build_probe_rows,
    build_units,
    classify,
    find_private_leaks,
    gain_origin,
    lost_destination,
    macro_at,
    rank_bucket,
    rank_of,
    run,
    transition_type,
    verify_determinism,
)

REPO = Path(__file__).resolve().parents[2]


class TestHelpers(unittest.TestCase):

    def test_rank_extraction(self):
        self.assertEqual(rank_of("b", ["a", "b", "c"]), 2)
        self.assertIsNone(rank_of("z", ["a"]))

    def test_bucket_boundaries(self):
        for r, b in ((10, "TOP_10"), (11, "NEAR_11_20"), (20, "NEAR_11_20"), (21, "MID_21_30"),
                     (30, "MID_21_30"), (31, "MID_31_50"), (50, "MID_31_50"), (51, "DEEP_GT_50"), (None, "MISSING")):
            self.assertEqual(rank_bucket(r), b)
        for r, b in ((11, "11-15"), (15, "11-15"), (16, "16-20"), (20, "16-20"), (21, "21-30"),
                     (30, "21-30"), (31, "31-50"), (50, "31-50"), (51, ">50"), (None, "missing")):
            self.assertEqual(lost_destination(r), b)
        for r, b in ((11, "11-20"), (20, "11-20"), (21, "21-30"), (31, "31-50"), (51, ">50"), (None, "missing")):
            self.assertEqual(gain_origin(r), b)
        with self.assertRaises(ValueError):
            lost_destination(10)
        with self.assertRaises(ValueError):
            gain_origin(10)

    def test_transition_classification(self):
        self.assertEqual(transition_type(3, 10), "STAY_TOP10")
        self.assertEqual(transition_type(10, 11), "F_TOP10_LOST_BY_K")
        self.assertEqual(transition_type(11, 10), "K_TOP10_GAIN_FROM_F")
        self.assertEqual(transition_type(40, 11), "STAY_OUTSIDE_TOP10")
        self.assertEqual(transition_type(5, None), "F_TOP10_LOST_BY_K")

    def test_bool_transitions(self):
        self.assertEqual(bool_transition("HIT", True, True), "HIT_STABLE")
        self.assertEqual(bool_transition("HIT", False, True), "HIT_GAINED")
        self.assertEqual(bool_transition("HIT", True, False), "HIT_LOST")
        self.assertEqual(bool_transition("FULL_SUCCESS", False, False), "FULL_SUCCESS_STABLE")

    def test_macro_raw_and_access(self):
        # probe1 (2 units): ranks 1, 15 ; probe2 (3 units): 2, 3, 40
        pr = [[1, 15], [2, 3, 40]]
        m10 = macro_at(pr, 10)
        self.assertEqual(m10["raw_required_units"], 3)
        self.assertAlmostEqual(m10["recall"], (0.5 + 2 / 3) / 2)
        self.assertEqual((m10["probes_with_any_required"], m10["probes_with_all_required"]), (2, 0))
        m20 = macro_at(pr, 20)
        self.assertEqual((m20["probes_with_all_required"], m20["full_evidence_success"]), (1, 0.5))
        m30 = macro_at(pr, 30)
        self.assertEqual(m30["probes_with_all_required"], 1)
        m50 = macro_at(pr, 50)
        self.assertEqual((m50["probes_with_all_required"], m50["recall"]), (2, 1.0))
        # Same raw count, different macro recall: move a unit from the 3-unit probe to the 2-unit probe.
        alt = macro_at([[1, 5], [2, 30, 40]], 10)
        self.assertEqual(alt["raw_required_units"], m10["raw_required_units"])
        self.assertNotAlmostEqual(alt["recall"], m10["recall"])

    def test_classification(self):
        self.assertEqual(classify(0.75, 0.8, 2, 35)["classification"], "ORDERING_CONSISTENT")
        self.assertEqual(classify(0.4, 0.8, 5, 35)["classification"], "DEEP_RELEVANCE_CONSISTENT")
        self.assertEqual(classify(0.75, 0.8, 4, 35)["classification"], "MIXED")          # 4/35 >= 10%
        self.assertEqual(classify(0.75, 0.8, 3, 35)["classification"], "ORDERING_CONSISTENT")  # 3/35 < 10%
        self.assertEqual(classify(0.50, 0.8, 0, 35)["classification"], "MIXED_INCONCLUSIVE")  # needs > 50%
        self.assertEqual(classify(0.75, 0.4, 0, 35)["classification"], "MIXED_INCONCLUSIVE")
        self.assertEqual(classify(None, 0.8, 0, 35)["classification"], "MIXED_INCONCLUSIVE")

    def test_privacy_scan(self):
        self.assertEqual(find_private_leaks("count: 3", ["hidden?"]), [])
        self.assertIn("<chunk-id pattern>", find_private_leaks("ch001_c0001", []))
        self.assertIn("<probe-id pattern>", find_private_leaks("P_TEST_99", []))


class TestPopulations(unittest.TestCase):

    def setUp(self):
        ids = [f"d{i:03d}" for i in range(1, 61)]
        self.probes = [
            {"probe_id": "A", "category": "C1", "required_evidence_chunk_ids": ["d001", "d002"]},
            {"probe_id": "B", "category": "C2", "required_evidence_chunk_ids": ["d003", "d025", "d055"]},
        ]
        f = {"A": ids, "B": ids}

        def move(lst, item, pos):
            lst = [x for x in lst if x != item]
            lst.insert(pos - 1, item)
            return lst

        k_a = move(move(ids, "d002", 14), "d001", 1)      # d002: 2 -> 14 (lost)
        k_b = move(move(ids, "d025", 4), "d055", 52)      # d025: 25 -> 4 (gain), d055 stays deep
        self.units = build_units(self.probes, f, {"A": k_a, "B": k_b})
        self.rows = build_probe_rows(self.probes, self.units)

    def test_units_and_transitions(self):
        t = {u["required_chunk_id"]: u["transition"] for u in self.units}
        self.assertEqual(t, {"d001": "STAY_TOP10", "d002": "F_TOP10_LOST_BY_K", "d003": "STAY_TOP10",
                             "d025": "K_TOP10_GAIN_FROM_F", "d055": "STAY_OUTSIDE_TOP10"})
        lost = [u for u in self.units if u["transition"] == "F_TOP10_LOST_BY_K"][0]
        self.assertEqual((lost["f_rank"], lost["k_rank"], lost_destination(lost["k_rank"])), (2, 14, "11-15"))
        gain = [u for u in self.units if u["transition"] == "K_TOP10_GAIN_FROM_F"][0]
        self.assertEqual((gain["f_rank"], gain_origin(gain["f_rank"])), (25, "21-30"))

    def test_probe_transitions(self):
        a, b = self.rows
        self.assertEqual((a["f_full_success10"], a["k_full_success10"], a["full_success_transition"]),
                         (True, False, "FULL_SUCCESS_LOST"))
        self.assertEqual(a["hit_transition"], "HIT_STABLE")
        self.assertEqual((b["f_required_in_top10"], b["k_required_in_top10"]), (1, 2))
        self.assertEqual(b["k_worst_required_rank"], 52)


# ---------------------------------------------------------------------------
# End-to-end with synthetic artifacts
# ---------------------------------------------------------------------------

class TestEndToEnd(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        ids = [f"ch{(i // 3) + 1:03d}_c{(i % 3) + 1:04d}" for i in range(60)]
        self.probes = [{"probe_id": f"SYN_{n}", "category": f"CAT{n % 2}", "question": f"synthetic question {n}?",
                        "expected_answer": f"synthetic answer {n}", "cutoff_chapter": 20,
                        "required_evidence_chunk_ids": [ids[n], ids[12 + n]]} for n in range(4)]
        self.paths = {"probes": root / "probes.yaml", "chunks": root / "chunks.jsonl", "freeze": root / "freeze.yaml",
                      "f_result": root / "F.yaml", "f_detail": root / "F.jsonl", "k_result": root / "K.yaml",
                      "k_detail": root / "K.jsonl", "out_dir": root / "out"}
        with open(self.paths["probes"], "w", encoding="utf-8") as f:
            yaml.dump({"probes": self.probes}, f)
        self.paths["chunks"].write_text("".join(json.dumps({"chunk_id": c}) + "\n" for c in ids), encoding="utf-8")
        k_ids = list(reversed(ids[:20])) + ids[20:]
        for key, ranking in (("f_detail", ids), ("k_detail", k_ids)):
            self.paths[key].write_text("".join(json.dumps({"probe_id": p["probe_id"], "retrieved_chunk_ids": ranking}) + "\n"
                                               for p in self.probes), encoding="utf-8")
        sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
        with open(self.paths["freeze"], "w") as f:
            yaml.dump({"status": "FROZEN", "probe_count": 4, "probe_file_sha256": sha(self.paths["probes"]),
                       "chunks_jsonl_sha256": sha(self.paths["chunks"])}, f)

        def ov(ranking):
            pr = [[rank_of(c, ranking) for c in p["required_evidence_chunk_ids"]] for p in self.probes]
            m = macro_at(pr, 10)
            return {"recall@10": m["recall"], "success@10": m["full_evidence_success"], "hit@10": m["hit"]}

        for key, det, ranking in (("f_result", "f_detail", ids), ("k_result", "k_detail", k_ids)):
            with open(self.paths[key], "w") as f:
                yaml.dump({"detailed_results_sha256": {"cutoff_filtered_per_probe.jsonl": sha(self.paths[det])},
                           "CUTOFF_FILTERED": {"overall": ov(ranking)}}, f)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self):
        return run(self.paths, expected_population=(4, 8))

    def test_end_to_end_deterministic_private(self):
        p1, forbidden = self._run()
        p2, _ = self._run()
        self.assertTrue(verify_determinism(p1, p2))
        self.assertEqual(p1["population"], {"probe_count": 4, "required_evidence_units": 8})
        c = p1["all_required_evidence_transition_counts"]["counts"]
        self.assertEqual(sum(c.values()), 8)
        # F ranks: 1-4 and 13-16; K reverses the first 20 -> ranks 20-17 and 8-5.
        self.assertEqual(c["F_TOP10_LOST_BY_K"], 4)
        self.assertEqual(c["K_TOP10_GAIN_FROM_F"], 4)
        lp = p1["f_top10_lost_population"]
        self.assertEqual(lp["k_destination"]["16-20"]["count"], 4)
        self.assertEqual(lp["fraction_within_k_top20"], 1.0)
        text = yaml.dump(p1, sort_keys=False, allow_unicode=True)
        self.assertEqual(find_private_leaks(text, forbidden), [])
        self.assertNotIn("retrieved_chunk_ids", text)
        self.assertTrue((self.paths["out_dir"] / "required_evidence_transitions.jsonl").exists())

    def test_population_gate(self):
        with self.assertRaisesRegex(GateFailure, "population"):
            run(self.paths)  # default expects 15 / 35

    def test_source_sha_mismatch(self):
        self.paths["k_detail"].write_text(self.paths["k_detail"].read_text() + "\n", encoding="utf-8")
        with self.assertRaisesRegex(GateFailure, "k_cutoff_ranking sha256 mismatch"):
            self._run()

    def test_missing_source(self):
        self.paths["f_detail"].unlink()
        with self.assertRaisesRegex(GateFailure, "missing required source"):
            self._run()

    def test_committed_metric_reproduction_gate(self):
        k = yaml.safe_load(self.paths["k_result"].read_text())
        k["CUTOFF_FILTERED"]["overall"]["hit@10"] = 0.123
        self.paths["k_result"].write_text(yaml.dump(k))
        with self.assertRaisesRegex(GateFailure, "does not reproduce"):
            self._run()


class TestPublicResult(unittest.TestCase):

    def test_public_aggregate_only(self):
        pub = REPO / "benchmarks/m1_script_quality/long_range_probe"
        files = [pub / "K_RANK_TRANSITION_DIAGNOSTIC_V1_RESULT.yaml", pub / "K_RANK_TRANSITION_DIAGNOSTIC_V1_METHOD.md"]
        present = [f for f in files if f.exists()]
        if not present:
            self.skipTest("public artifacts not generated yet")
        for f in present:
            text = f.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"ch\d{3}_c\d{4}", text), f.name)
            self.assertIsNone(re.search(r"\bP_[A-Z]+_\d{2}\b", text), f.name)
            self.assertNotIn("retrieved_chunk_ids", text)
            self.assertNotIn("required_chunk_id", text)
        res = files[0]
        if res.exists():
            data = yaml.safe_load(res.read_text(encoding="utf-8"))
            self.assertEqual(data["determinism_status"], "PASS")
            self.assertEqual(data["privacy_status"], "PASS")
            self.assertNotIn("verdict", data)


if __name__ == "__main__":
    unittest.main()
