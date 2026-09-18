import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import yaml

import tools.story_benchmark.dense_e5_large_v1 as k_mod
from tools.story_benchmark.dense_e5_large_v1 import (
    MAX_SEQ_LENGTH,
    MODEL_ID,
    MODEL_REVISION,
    MODEL_WEIGHT_SHA256,
    PASSAGE_PREFIX,
    QUERY_PREFIX,
    TOKENIZER_SHA256,
    DenseE5LargeV1,
    ModelIdentityError,
    calculate_metrics,
    completeness_curve,
    eligible_doc_ids,
    f_missed_population,
    interpret_verdict,
    rank_bucket,
    rank_by_cosine,
    rank_of,
    rank_shift_aggregate,
    rank_shift_rows,
    verify_model_identity,
)
from tools.story_benchmark.dense_e5_small_v1 import calculate_metrics as f_calculate_metrics
from tools.story_benchmark.run_dense_e5_large_v1 import (
    GateFailure,
    find_private_leaks,
    finalize,
    reconstruct_j,
    run_once,
    verify_determinism,
    load_f_control,
    verify_inputs,
)

REPO = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Offline mock encoder (synthetic text only)
# ---------------------------------------------------------------------------

class MockTokenizer:
    def __call__(self, texts, add_special_tokens=True, truncation=False):
        return {"input_ids": [[0] * len(t.split()) for t in texts]}


class HashModel:
    def __init__(self):
        self.tokenizer = MockTokenizer()
        self.max_seq_length = MAX_SEQ_LENGTH
        self.calls = []

    def get_embedding_dimension(self):
        return 1024

    def encode(self, texts, batch_size=32, convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False):
        self.calls.append(list(texts))
        out = []
        for t in texts:
            seed = int(hashlib.sha256(t.encode("utf-8")).hexdigest()[:8], 16)
            v = np.random.default_rng(seed).standard_normal(1024)
            out.append(v / np.linalg.norm(v) if normalize_embeddings else v)
        return np.array(out, dtype=np.float32)

    def eval(self):
        pass


class MockLarge(DenseE5LargeV1):
    def __init__(self):
        self.identity = {"model_weight_sha256": "mock", "tokenizer_sha256": "mock"}
        self.model_name, self.model_revision, self.device = MODEL_ID, MODEL_REVISION, "cpu"
        self.model = HashModel()
        self._reset_state()


class TestContract(unittest.TestCase):

    def test_model_identity_constants(self):
        self.assertEqual(MODEL_ID, "intfloat/multilingual-e5-large")
        self.assertRegex(MODEL_REVISION, r"^[0-9a-f]{40}$")
        self.assertRegex(MODEL_WEIGHT_SHA256, r"^[0-9a-f]{64}$")
        self.assertRegex(TOKENIZER_SHA256, r"^[0-9a-f]{64}$")
        self.assertEqual(k_mod.EXECUTION_DEVICE, "cpu")
        self.assertEqual(k_mod.EXPECTED_EMBEDDING_DIMENSION, 1024)

    def test_max_length_and_prefixes(self):
        self.assertEqual(MAX_SEQ_LENGTH, 512)
        self.assertEqual(QUERY_PREFIX, "query: ")
        self.assertEqual(PASSAGE_PREFIX, "passage: ")
        m = MockLarge()
        m.encode_documents(["d1"], ["some passage"])
        m.encode_queries(["a question"])
        self.assertEqual(m.model.calls[0], ["passage: some passage"])
        self.assertEqual(m.model.calls[1], ["query: a question"])

    def test_normalized_embeddings(self):
        m = MockLarge()
        emb = m.encode_documents(["d1", "d2"], ["alpha", "beta"])
        np.testing.assert_allclose(np.linalg.norm(emb, axis=1), 1.0, rtol=1e-5)
        np.testing.assert_allclose(np.linalg.norm(m.encode_queries(["q"])[0]), 1.0, rtol=1e-5)

    def test_truncation_counting(self):
        m = MockLarge()
        m.encode_documents(["d1", "d2"], ["w " * 600, "short"])
        m.encode_queries(["tiny"])
        self.assertEqual((m.passage_truncation_count, m.query_truncation_count), (1, 0))

    def test_cosine_ranking_and_tie_break(self):
        docs = ["z_doc", "a_doc", "b_doc"]
        embs = np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
        res = rank_by_cosine(docs, embs, np.array([1.0, 0.0]))
        self.assertEqual([d for d, _ in res], ["a_doc", "z_doc", "b_doc"])
        self.assertEqual(res[0][1], 1.0)

    def test_cutoff_filtering(self):
        meta = {"c1": 1, "c2": 4, "c3": 9}
        self.assertEqual(eligible_doc_ids(meta, 4), {"c1", "c2"})
        res = rank_by_cosine(["c1", "c2", "c3"], np.eye(3), np.array([0, 0, 1.0]), eligible_doc_ids(meta, 4))
        self.assertNotIn("c3", [d for d, _ in res])

    def test_metrics_identical_to_f(self):
        probe = {"required_evidence_chunk_ids": ["c1", "c2", "c5"]}
        for ranked in (["c3", "c1", "c2", "c4"], ["c5", "c2", "c1"], ["x"] * 0 + ["c9", "c8"]):
            self.assertEqual(calculate_metrics(probe, ranked), f_calculate_metrics(probe, ranked))
        m = calculate_metrics({"required_evidence_chunk_ids": ["c1", "c2"]}, ["c3", "c1", "c2"])
        self.assertEqual((m["hit@1"], m["hit@3"], m["success@3"]), (0, 1, 1))
        self.assertAlmostEqual(m["mrr"], 0.5)

    @patch("sentence_transformers.SentenceTransformer")
    def test_offline_identity_gate_before_model_load(self, mock_st):
        mock_st.side_effect = RuntimeError("must not load")
        with tempfile.TemporaryDirectory() as d:
            snap = Path(d) / "not_the_revision"
            snap.mkdir()
            with self.assertRaises(ModelIdentityError):
                verify_model_identity(str(snap))
            snap2 = Path(d) / MODEL_REVISION
            snap2.mkdir()
            (snap2 / "model.safetensors").write_bytes(b"tampered")
            (snap2 / "tokenizer.json").write_bytes(b"{}")
            with self.assertRaisesRegex(ModelIdentityError, "weight sha256 mismatch"):
                verify_model_identity(str(snap2))


class TestRankDiagnostics(unittest.TestCase):

    def test_rank_extraction_and_buckets(self):
        self.assertEqual(rank_of("b", ["a", "b"]), 2)
        self.assertIsNone(rank_of("z", ["a"]))
        for r, b in ((1, "1-10"), (10, "1-10"), (11, "11-20"), (20, "11-20"), (21, "21-50"),
                     (50, "21-50"), (51, ">50"), (None, "missing")):
            self.assertEqual(rank_bucket(r), b)

    def test_population_and_rank_shift(self):
        probes = [{"probe_id": "A", "category": "X", "required_evidence_chunk_ids": ["c2", "c15", "c30"]},
                  {"probe_id": "B", "category": "Y", "required_evidence_chunk_ids": ["c60", "c1"]}]
        ids = [f"c{i}" for i in range(1, 71)]
        f_rank = {"A": ids, "B": ids}
        pop = f_missed_population(probes, f_rank)
        self.assertEqual([(u["probe_id"], u["f_rank"]) for u in pop], [("A", 15), ("A", 30), ("B", 60)])
        k_a = ["c30"] + [x for x in ids if x != "c30"]            # c30: 30 -> 1, c15: 15 -> 16 (worse)
        k_b = [x for x in ids if x != "c60"][:44] + ["c60"] + [x for x in ids if x != "c60"][44:]  # c60 -> 45
        rows = rank_shift_rows(pop, {"A": k_a, "B": k_b})
        self.assertEqual([r["k_rank"] for r in rows], [16, 1, 45])
        self.assertEqual([r["rank_delta_f_minus_k"] for r in rows], [-1, 29, 15])
        agg = rank_shift_aggregate(rows)
        self.assertEqual((agg["rank_improved"], agg["rank_same"], agg["rank_worsened"]), (2, 0, 1))
        self.assertEqual((agg["f_gt10_to_k_le10"], agg["f_gt20_to_k_le20"], agg["f_gt50_to_k_le50"]), (1, 1, 1))
        self.assertEqual(agg["median_f_rank"], 30.0)
        self.assertEqual(agg["median_k_rank"], 16.0)
        self.assertEqual(agg["k_rank_distribution"]["1-10"]["count"], 1)
        self.assertEqual(agg["k_rank_distribution"]["missing"]["count"], 0)

    def test_completeness_curve(self):
        ids = [f"c{i}" for i in range(1, 61)]
        probes = [{"probe_id": "A", "required_evidence_chunk_ids": ["c1", "c15"]},
                  {"probe_id": "B", "required_evidence_chunk_ids": ["c40", "c55"]}]
        c = completeness_curve(probes, {"A": ids, "B": ids})
        self.assertAlmostEqual(c["K10"]["recall"], 0.25)
        self.assertAlmostEqual(c["K20"]["full_evidence_success"], 0.5)
        self.assertAlmostEqual(c["K50"]["recall"], 0.75)
        self.assertAlmostEqual(c["K50"]["full_evidence_success"], 0.5)

    def test_interpretation_rule(self):
        self.assertEqual(interpret_verdict(0.1, 0.07, 0.0, 1, True), "SUPPORTED")
        self.assertEqual(interpret_verdict(0.1, 0.07, 0.0, 0, True), "PARTIALLY_SUPPORTED")   # no deep rescue
        self.assertEqual(interpret_verdict(0.1, 0.07, -0.2, 1, True), "PARTIALLY_SUPPORTED")  # hit collapse
        self.assertEqual(interpret_verdict(0.1, 0.0, 0.0, 0, True), "PARTIALLY_SUPPORTED")
        self.assertEqual(interpret_verdict(0.0, 0.07, 0.0, 0, True), "PARTIALLY_SUPPORTED")
        self.assertEqual(interpret_verdict(0.0, 0.0, 0.0, 3, True), "PARTIALLY_SUPPORTED")
        self.assertEqual(interpret_verdict(0.0, 0.0, 0.0, 2, True), "NOT_SUPPORTED")
        self.assertEqual(interpret_verdict(-0.1, -0.1, -0.3, 0, True), "NOT_SUPPORTED")
        self.assertEqual(interpret_verdict(0.5, 0.5, 0.0, 9, False), "NOT_EVALUABLE")

    def test_privacy_scan(self):
        self.assertEqual(find_private_leaks("recall: 0.5", ["secret?"]), [])
        self.assertIn("<chunk-id pattern>", find_private_leaks("ch001_c0002", []))
        self.assertIn("<probe-id pattern>", find_private_leaks("P_TEST_99", []))
        self.assertIn("secret?", find_private_leaks("x secret? y", ["secret?"]))


# ---------------------------------------------------------------------------
# End-to-end with synthetic artifacts
# ---------------------------------------------------------------------------

class TestEndToEnd(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.ids = [f"ch{c:03d}_c{i:04d}" for c in range(1, 21) for i in range(1, 4)]  # 60 chunks
        chunks = [{"chunk_id": cid, "chapter_number": int(cid[2:5]), "text": f"synthetic passage {cid}",
                   "corpus_fingerprint_sha256": "fp"} for cid in self.ids]
        self.probes = []
        for n in range(15):
            self.probes.append({"probe_id": f"SYN_{n:02d}", "category": f"CAT{n % 5}",
                                "question": f"synthetic question number {n}?", "expected_answer": f"answer {n}",
                                "cutoff_chapter": 20 if n % 2 else 12,
                                "required_evidence_chunk_ids": [self.ids[n], self.ids[20 + n]]})
        self.paths = {"probes": root / "probes.yaml", "chunks": root / "chunks.jsonl", "freeze": root / "freeze.yaml",
                      "f_result": root / "F.yaml", "f_detail": root / "F.jsonl", "j_result": root / "J.yaml",
                      "out_dir": root / "out"}
        with open(self.paths["probes"], "w", encoding="utf-8") as f:
            yaml.dump({"probes": self.probes}, f)
        self.paths["chunks"].write_text("".join(json.dumps(c) + "\n" for c in chunks), encoding="utf-8")
        sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
        with open(self.paths["freeze"], "w") as f:
            yaml.dump({"status": "FROZEN", "probe_count": 15, "probe_file_sha256": sha(self.paths["probes"]),
                       "chunks_jsonl_sha256": sha(self.paths["chunks"]), "corpus_fingerprint_sha256": "fp"}, f)
        meta = {c["chunk_id"]: c["chapter_number"] for c in chunks}
        f_rows = []
        for p in self.probes:
            allowed = [cid for cid in self.ids if meta[cid] <= p["cutoff_chapter"]]
            f_rows.append({"probe_id": p["probe_id"], "retrieved_chunk_ids": allowed})
        self.paths["f_detail"].write_text("".join(json.dumps(r) + "\n" for r in f_rows), encoding="utf-8")
        f_rankings = {r["probe_id"]: r["retrieved_chunk_ids"] for r in f_rows}
        from tools.story_benchmark.run_dense_e5_large_v1 import aggregate
        from tools.story_benchmark.run_bm25_lexical_v1 import compute_spoiler_violations
        ml = []
        for p in self.probes:
            m = calculate_metrics(p, f_rankings[p["probe_id"]])
            m.update(compute_spoiler_violations(p, f_rankings[p["probe_id"]], meta))
            ml.append((p["category"], m))
        self.f_res = {"CUTOFF_FILTERED": aggregate(ml),
                      "detailed_results_sha256": {"cutoff_filtered_per_probe.jsonl": sha(self.paths["f_detail"])},
                      "dense_diagnostics": {"query_truncation_count": 0, "passage_truncation_count": 0}}
        with open(self.paths["f_result"], "w") as f:
            yaml.dump(self.f_res, f)
        # Build a committed-J-like result from the same F ranking.
        pop = f_missed_population(self.probes, f_rankings)
        b = {k: sum(1 for u in pop if rank_bucket(u["f_rank"]) == k) for k in ("11-20", "21-50", ">50", "missing")}
        curve = completeness_curve(self.probes, f_rankings)
        self.j_res = {
            "artifact_integrity": {"source_sha256": {"f_cutoff_ranking": sha(self.paths["f_detail"])}},
            "required_evidence_unit_count": 30,
            "candidate_reachability": {"f_top10_missed_units": len(pop)},
            "f_missed_evidence_bucket_distribution": {
                "rank_11_20": {"count": b["11-20"]}, "rank_21_50": {"count": b["21-50"]},
                "rank_gt_50": {"count": b[">50"]}, "missing": {"count": b["missing"]}},
            "probe_completeness_by_k": curve,
        }
        with open(self.paths["j_result"], "w") as f:
            yaml.dump(self.j_res, f)

    def tearDown(self):
        self.tmp.cleanup()

    def test_run_twice_deterministic_and_private(self):
        a1, private = run_once(self.paths, dense_factory=MockLarge)
        a2, _ = run_once(self.paths, dense_factory=MockLarge)
        self.assertTrue(verify_determinism(a1, a2))
        res = finalize(a1, a2, self.f_res)
        self.assertEqual(res["deterministic_reproduction_status"], "PASS")
        self.assertIn(res["verdict"], {"SUPPORTED", "PARTIALLY_SUPPORTED", "NOT_SUPPORTED"})
        self.assertEqual(res["J_MISSED_EVIDENCE_RANK_DIAGNOSTIC"]["population_size"],
                         self.j_res["candidate_reachability"]["f_top10_missed_units"])
        text = yaml.dump(res, sort_keys=False, allow_unicode=True)
        self.assertEqual(find_private_leaks(text, private["forbidden_strings"]), [])
        self.assertNotIn("retrieved_chunk_ids", text)
        rows = (self.paths["out_dir"] / "f_missed_rank_shift.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(rows), res["J_MISSED_EVIDENCE_RANK_DIAGNOSTIC"]["population_size"])

    def test_nondeterminism_is_not_evaluable(self):
        a1, _ = run_once(self.paths, dense_factory=MockLarge)
        a2 = json.loads(json.dumps(a1))
        a2["detailed_results_sha256"]["cutoff_filtered_per_probe.jsonl"] = "0" * 64
        res = finalize(a1, a2, self.f_res)
        self.assertEqual(res["deterministic_reproduction_status"], "FAIL")
        self.assertEqual(res["verdict"], "NOT_EVALUABLE")

    def test_f_sha_gate(self):
        self.paths["f_detail"].write_text(self.paths["f_detail"].read_text() + "\n", encoding="utf-8")
        with self.assertRaisesRegex(GateFailure, "F detailed ranking sha256 mismatch"):
            run_once(self.paths, dense_factory=MockLarge)

    def test_missing_f_artifact(self):
        self.paths["f_detail"].unlink()
        with self.assertRaisesRegex(GateFailure, "missing required artifact"):
            run_once(self.paths, dense_factory=MockLarge)

    def test_freeze_gate(self):
        fr = yaml.safe_load(self.paths["freeze"].read_text())
        fr["chunks_jsonl_sha256"] = "0" * 64
        self.paths["freeze"].write_text(yaml.dump(fr))
        with self.assertRaisesRegex(GateFailure, "chunks sha256 mismatch"):
            run_once(self.paths, dense_factory=MockLarge)

    def test_j_reconstruction_gate(self):
        self.j_res["candidate_reachability"]["f_top10_missed_units"] += 1
        with open(self.paths["j_result"], "w") as f:
            yaml.dump(self.j_res, f)
        with self.assertRaisesRegex(GateFailure, "J population reconstruction mismatch"):
            run_once(self.paths, dense_factory=MockLarge)


class TestRealJReconstruction(unittest.TestCase):
    """Uses the real local artifacts when present (LOCAL_PRIVATE); skipped otherwise."""

    def test_real_j_population(self):
        from tools.story_benchmark.run_dense_e5_large_v1 import default_paths
        paths = default_paths(REPO)
        if not paths["f_detail"].exists() or not paths["probes"].exists():
            self.skipTest("local private artifacts not available")
        inp = verify_inputs(paths)
        f_ctl = load_f_control(paths)
        j_res = yaml.safe_load(paths["j_result"].read_text(encoding="utf-8"))
        pop = reconstruct_j(inp["probes"], f_ctl["rankings"], j_res, f_ctl["detail_sha256"])
        self.assertEqual(len(pop), 15)
        self.assertEqual(sum(len(p["required_evidence_chunk_ids"]) for p in inp["probes"]), 35)


class TestPublicResult(unittest.TestCase):

    def test_public_artifacts_private(self):
        pub = REPO / "benchmarks/m1_script_quality/long_range_probe"
        files = [pub / "DENSE_E5_LARGE_V1_RESULT.yaml", pub / "DENSE_E5_LARGE_V1_METHOD.md"]
        present = [f for f in files if f.exists()]
        if not present:
            self.skipTest("public artifacts not generated yet")
        for f in present:
            text = f.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"ch\d{3}_c\d{4}", text), f.name)
            self.assertIsNone(re.search(r"\bP_[A-Z]+_\d{2}\b", text), f.name)
            self.assertNotIn("retrieved_chunk_ids", text)
        res = pub / "DENSE_E5_LARGE_V1_RESULT.yaml"
        if res.exists():
            data = yaml.safe_load(res.read_text(encoding="utf-8"))
            self.assertEqual(data["privacy_status"], "PASS")
            self.assertEqual(data["model_info"]["model_revision"], MODEL_REVISION)
            self.assertEqual(data["model_info"]["model_weight_sha256"], MODEL_WEIGHT_SHA256)


if __name__ == "__main__":
    unittest.main()
