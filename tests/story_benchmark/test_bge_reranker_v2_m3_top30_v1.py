import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

import yaml

import tools.story_benchmark.bge_reranker_v2_m3_top30_v1 as m_mod
from tools.story_benchmark.bge_reranker_v2_m3_top30_v1 import (
    CANDIDATE_DEPTH,
    MODEL_ID,
    MODEL_REVISION,
    MODEL_WEIGHT_SHA256,
    PASSAGE_MAX_LENGTH,
    QUERY_MAX_LENGTH,
    TOKENIZER_SHA256,
    CandidateSetError,
    ModelIdentityError,
    build_pair_input,
    check_candidate_equality,
    evaluated_ranking,
    extract_candidates,
    interpret_verdict,
    rerank_order,
    transition_type,
    verify_model_identity,
)
from tools.story_benchmark.dense_e5_large_v1 import calculate_metrics as k_metrics
from tools.story_benchmark.dense_e5_small_v1 import calculate_metrics as f_metrics
from tools.story_benchmark.run_bge_reranker_v2_m3_top30_v1 import (
    GateFailure,
    aggregate,
    finalize,
    find_private_leaks,
    run_once,
    verify_determinism,
)
from tools.story_benchmark.run_bm25_lexical_v1 import compute_spoiler_violations

REPO = Path(__file__).resolve().parents[2]


class FakeTokenizer:
    """Whitespace tokenizer with XLM-R style pair specials: <s>=0, </s>=2."""
    def __call__(self, text, add_special_tokens=False):
        return {"input_ids": [10 + (hash(w) % 1000) for w in text.split()]}

    cls_token_id, sep_token_id = 0, 2

    def prepare_for_model(self, a, b, add_special_tokens=True, truncation=False):
        ids = [0] + list(a) + [2, 2] + list(b) + [2]
        return {"input_ids": ids, "attention_mask": [1] * len(ids)}


class TestContract(unittest.TestCase):

    def test_identity_constants(self):
        self.assertEqual(MODEL_ID, "BAAI/bge-reranker-v2-m3")
        self.assertRegex(MODEL_REVISION, r"^[0-9a-f]{40}$")
        self.assertRegex(MODEL_WEIGHT_SHA256, r"^[0-9a-f]{64}$")
        self.assertRegex(TOKENIZER_SHA256, r"^[0-9a-f]{64}$")
        self.assertEqual((m_mod.EXECUTION_DEVICE, m_mod.DTYPE), ("cpu", "float32"))
        self.assertEqual(CANDIDATE_DEPTH, 30)
        self.assertEqual((QUERY_MAX_LENGTH, PASSAGE_MAX_LENGTH), (256, 512))

    def test_identity_gate(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ModelIdentityError):
                verify_model_identity(d)
            snap = Path(d) / MODEL_REVISION
            snap.mkdir()
            (snap / "model.safetensors").write_bytes(b"x")
            (snap / "tokenizer.json").write_bytes(b"{}")
            with self.assertRaisesRegex(ModelIdentityError, "weight sha256 mismatch"):
                verify_model_identity(str(snap))

    def test_candidate_extraction_top30(self):
        ranking = [f"c{i}" for i in range(97)]
        self.assertEqual(extract_candidates(ranking), ranking[:30])
        small = [f"c{i}" for i in range(12)]
        self.assertEqual(extract_candidates(small), small)  # no padding
        with self.assertRaises(CandidateSetError):
            extract_candidates(["a", "a"])

    def test_candidate_equality_gate(self):
        c = [f"c{i}" for i in range(30)]
        check_candidate_equality(c, list(reversed(c)), 97)
        with self.assertRaises(CandidateSetError):
            check_candidate_equality(c, c[:-1] + ["intruder"], 97)
        with self.assertRaises(CandidateSetError):
            check_candidate_equality(c, c[:-1] + [c[0]], 97)
        with self.assertRaises(CandidateSetError):
            check_candidate_equality(c[:29], c[:29], 97)          # must be 30 when pool >= 30
        check_candidate_equality(c[:12], c[:12][::-1], 12)        # fewer-than-30 pool preserved

    def test_pair_input_budgets(self):
        tok = FakeTokenizer()
        q = " ".join(f"q{i}" for i in range(300))
        p = " ".join(f"p{i}" for i in range(600))
        pair = build_pair_input(tok, q, p)
        self.assertEqual(len(pair["input_ids"]), 1 + 256 + 2 + 512 + 1)
        self.assertTrue(pair["query_truncated"] and pair["passage_truncated"])
        short = build_pair_input(tok, "short question", "short passage")
        self.assertFalse(short["query_truncated"] or short["passage_truncated"])
        self.assertEqual(short["input_ids"][0], 0)
        self.assertEqual(short["input_ids"][3:5], [2, 2])

    def test_sort_and_tie_breaks(self):
        cands = ["z", "b", "a", "c"]  # original K ranks 1..4
        order = rerank_order(cands, {"z": 0.1, "b": 2.0, "a": 2.0, "c": 5.0})
        self.assertEqual([x for x, _ in order], ["c", "b", "a", "z"])   # tie b/a -> original rank (b=2 < a=3)
        order2 = rerank_order(["a", "a2"], {"a": 1.0, "a2": 1.0})
        self.assertEqual([x for x, _ in order2], ["a", "a2"])
        # chunk_id final tie-break is only reachable if original ranks tie, which cannot happen for distinct
        # positions; verify the key is (-score, orig_rank, chunk_id) by construction:
        self.assertEqual([x for x, _ in rerank_order(["m", "k"], {"m": 1.0, "k": 1.0})], ["m", "k"])

    def test_evaluated_ranking_keeps_tail(self):
        k = [f"c{i}" for i in range(40)]
        top = list(reversed(k[:30]))
        full = evaluated_ranking(top, k)
        self.assertEqual(full[:30], top)
        self.assertEqual(full[30:], k[30:])

    def test_metric_equivalence(self):
        probe = {"required_evidence_chunk_ids": ["a", "b"]}
        for r in (["x", "a", "b"], ["b", "y", "z", "a"], ["q"]):
            self.assertEqual(k_metrics(probe, r), f_metrics(probe, r))

    def test_transitions(self):
        self.assertEqual(transition_type(3, 9), "STAY_TOP10")
        self.assertEqual(transition_type(10, 11), "K_TOP10_LOST_BY_RERANK")
        self.assertEqual(transition_type(25, 2), "RERANK_TOP10_GAIN_FROM_K")
        self.assertEqual(transition_type(40, 40), "STAY_OUTSIDE_TOP10")

    def test_verdict_rule(self):
        self.assertEqual(interpret_verdict(0.07, 0.05, 0.0, 4, 5, True), "SUPPORTED")
        self.assertEqual(interpret_verdict(0.07, 0.05, -0.07, 4, 5, True), "PARTIALLY_SUPPORTED")
        self.assertEqual(interpret_verdict(0.0, 0.05, 0.0, 4, 4, True), "PARTIALLY_SUPPORTED")
        self.assertEqual(interpret_verdict(0.0, 0.0, 0.07, 4, 4, True), "PARTIALLY_SUPPORTED")
        self.assertEqual(interpret_verdict(0.0, 0.0, 0.0, 4, 4, True), "NOT_SUPPORTED")
        self.assertEqual(interpret_verdict(-0.1, -0.1, -0.1, 4, 2, True), "NOT_SUPPORTED")
        self.assertEqual(interpret_verdict(0.5, 0.5, 0.5, 4, 9, False), "NOT_EVALUABLE")

    def test_privacy_scan(self):
        self.assertEqual(find_private_leaks("hit@10: 0.8", ["secret q?"]), [])
        self.assertIn("<chunk-id pattern>", find_private_leaks("ch001_c0001", []))
        self.assertIn("<probe-id pattern>", find_private_leaks("P_TEST_99", []))


# ---------------------------------------------------------------------------
# End-to-end with synthetic artifacts and a mock reranker
# ---------------------------------------------------------------------------

class MockReranker:
    """Deterministic: prefers passages whose text shares the question's number token."""
    def get_model_info(self):
        return {"model_id": MODEL_ID, "model_revision": MODEL_REVISION, "num_labels": 1, "dtype": "torch.float32"}

    def score(self, query, passage):
        qn = query.split()[-1].rstrip("?")
        s = 10.0 if f"topic{qn} " in passage + " " else float(int(hashlib.sha256(passage.encode()).hexdigest()[:4], 16)) / 65535
        return s, {"query_truncated": False, "passage_truncated": len(passage.split()) > 512,
                   "query_tokens": len(query.split()), "passage_tokens": len(passage.split())}


class TestEndToEnd(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        ids = [f"ch{c:03d}_c{i:04d}" for c in range(1, 16) for i in range(1, 5)]  # 60 chunks, chapters 1..15
        meta = {cid: int(cid[2:5]) for cid in ids}
        # Required units: probe n needs ids[n] (topic n) and ids[25 + n] (topic n).
        texts = {cid: f"passage {cid}" for cid in ids}
        self.probes = []
        for n in range(15):
            req = [ids[n], ids[25 + n]]
            for c in req:
                texts[c] = f"passage {c} topic{n} "
            self.probes.append({"probe_id": f"SYN_{n:02d}", "category": f"CAT{n % 5}",
                                "question": f"synthetic question {n}?", "expected_answer": f"answer {n}",
                                "cutoff_chapter": 15, "required_evidence_chunk_ids": req})
        # add one extra unit to reach 35
        self.probes[0]["required_evidence_chunk_ids"].append(ids[50])
        self.probes[1]["required_evidence_chunk_ids"].append(ids[51])
        self.probes[2]["required_evidence_chunk_ids"].append(ids[52])
        self.probes[3]["required_evidence_chunk_ids"].append(ids[53])
        self.probes[4]["required_evidence_chunk_ids"].append(ids[54])
        self.paths = {k: root / v for k, v in {
            "probes": "probes.yaml", "chunks": "chunks.jsonl", "freeze": "freeze.yaml", "k_result": "K.yaml",
            "k_detail": "K.jsonl", "f_result": "F.yaml", "f_detail": "F.jsonl", "l_result": "L.yaml", "out_dir": "out"}.items()}
        with open(self.paths["probes"], "w", encoding="utf-8") as f:
            yaml.dump({"probes": self.probes}, f)
        self.paths["chunks"].write_text("".join(json.dumps({"chunk_id": c, "chapter_number": meta[c], "text": texts[c],
                                                            "corpus_fingerprint_sha256": "fp"}) + "\n" for c in ids), encoding="utf-8")
        f_rank = ids
        k_rank = ids[1:] + ids[:1]
        self.k_rank = k_rank
        for key, r in (("f_detail", f_rank), ("k_detail", k_rank)):
            self.paths[key].write_text("".join(json.dumps({"probe_id": p["probe_id"], "retrieved_chunk_ids": r}) + "\n"
                                               for p in self.probes), encoding="utf-8")
        sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
        with open(self.paths["freeze"], "w") as f:
            yaml.dump({"status": "FROZEN", "probe_count": 15, "probe_file_sha256": sha(self.paths["probes"]),
                       "chunks_jsonl_sha256": sha(self.paths["chunks"]), "corpus_fingerprint_sha256": "fp"}, f)

        def overall(r):
            ml = []
            for p in self.probes:
                m = k_metrics(p, r)
                m.update(compute_spoiler_violations(p, r, meta))
                ml.append((p["category"], m))
            return aggregate(ml)

        for key, det, r in (("k_result", "k_detail", k_rank), ("f_result", "f_detail", f_rank)):
            with open(self.paths[key], "w") as f:
                yaml.dump({"detailed_results_sha256": {"cutoff_filtered_per_probe.jsonl": sha(self.paths[det])},
                           "CUTOFF_FILTERED": overall(r)}, f)
        lost = sum(1 for p in self.probes for c in p["required_evidence_chunk_ids"]
                   if f_rank.index(c) < 10 and k_rank.index(c) >= 10)
        self.l_res = {"artifact_integrity": {"source_sha256": {"k_cutoff_ranking": sha(self.paths["k_detail"]),
                                                               "f_cutoff_ranking": sha(self.paths["f_detail"])}},
                      "all_required_evidence_transition_counts": {"counts": {"F_TOP10_LOST_BY_K": lost}}}
        with open(self.paths["l_result"], "w") as f:
            yaml.dump(self.l_res, f)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self):
        return run_once(self.paths, reranker_factory=MockReranker)

    def test_end_to_end(self):
        a1, forbidden = self._run()
        a2, _ = self._run()
        self.assertTrue(verify_determinism(a1, a2))
        res = finalize(a1, a2)
        self.assertEqual(res["deterministic_reproduction_status"], "PASS")
        self.assertEqual(res["candidate_set_integrity"]["total_pairs_scored"], 15 * 30)
        self.assertEqual(res["RERANKED"]["overall"]["spoiler_violation@10"], 0.0)
        ce = res["candidate_ceiling"]
        expected_complete = sum(1 for p in self.probes if all(c in self.k_rank[:30] for c in p["required_evidence_chunk_ids"]))
        self.assertEqual(ce["candidate_complete_probes"], expected_complete)
        self.assertEqual(sum(res["required_evidence_transitions"]["counts"].values()), 35)
        text = yaml.dump(res, sort_keys=False, allow_unicode=True)
        self.assertEqual(find_private_leaks(text, forbidden), [])
        self.assertNotIn("reranked_top_candidates", text)

    def test_k_control_gate(self):
        k = yaml.safe_load(self.paths["k_result"].read_text())
        k["CUTOFF_FILTERED"]["overall"]["mrr"] += 0.01
        self.paths["k_result"].write_text(yaml.dump(k))
        with self.assertRaisesRegex(GateFailure, "K control does not reproduce"):
            self._run()

    def test_l_population_gate(self):
        self.l_res["all_required_evidence_transition_counts"]["counts"]["F_TOP10_LOST_BY_K"] += 1
        self.paths["l_result"].write_text(yaml.dump(self.l_res))
        with self.assertRaisesRegex(GateFailure, "L F_TOP10_LOST_BY_K"):
            self._run()

    def test_source_sha_failure(self):
        self.paths["k_detail"].write_text(self.paths["k_detail"].read_text() + "\n", encoding="utf-8")
        with self.assertRaisesRegex(GateFailure, "k_cutoff_ranking sha256 mismatch"):
            self._run()

    def test_missing_artifact(self):
        self.paths["f_detail"].unlink()
        with self.assertRaisesRegex(GateFailure, "missing required artifact"):
            self._run()

    def test_nondeterminism_not_evaluable(self):
        a1, _ = self._run()
        a2 = json.loads(json.dumps(a1))
        a2["detailed_results_sha256"]["pair_scores.jsonl"] = "0" * 64
        self.assertEqual(finalize(a1, a2)["verdict"], "NOT_EVALUABLE")


class TestPublicArtifacts(unittest.TestCase):

    def test_public_private(self):
        pub = REPO / "benchmarks/m1_script_quality/long_range_probe"
        files = [pub / "BGE_RERANKER_V2_M3_TOP30_V1_RESULT.yaml", pub / "BGE_RERANKER_V2_M3_TOP30_V1_METHOD.md"]
        present = [f for f in files if f.exists()]
        if not present:
            self.skipTest("public artifacts not generated yet")
        for f in present:
            text = f.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"ch\d{3}_c\d{4}", text), f.name)
            self.assertIsNone(re.search(r"\bP_[A-Z]+_\d{2}\b", text), f.name)
            self.assertNotIn("pair_scores:", text)
            self.assertNotIn("reranked_top_candidates", text)
        if files[0].exists():
            data = yaml.safe_load(files[0].read_text(encoding="utf-8"))
            self.assertEqual(data["privacy_status"], "PASS")
            self.assertEqual(data["model_info"]["model_revision"], MODEL_REVISION)
            self.assertEqual(data["candidate_set_integrity"]["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
