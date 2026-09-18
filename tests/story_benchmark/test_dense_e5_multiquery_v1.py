import hashlib
import json
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

import numpy as np
import yaml

from tools.story_benchmark.dense_e5_multiquery_v1 import (
    K_RRF,
    MAX_QUERIES_PER_PROBE,
    MIN_CONTENT_TOKENS,
    FORBIDDEN_DECOMPOSITION_FIELDS,
    DecompositionLeakageError,
    DenseE5MultiQueryV1,
    calculate_metrics,
    change_diagnostics,
    content_token_count,
    decompose_probe,
    decompose_question,
    decomposition_diagnostics,
    eligible_doc_ids,
    find_private_leaks,
    interpret_verdict,
    normalize_text,
    rrf_fuse,
    split_range,
)
from tools.story_benchmark.run_dense_e5_multiquery_v1 import (
    GateFailure,
    aggregate,
    check_control_aggregate,
    check_control_rankings,
    compare_with_f,
    run_multiquery,
    verify_multiquery_determinism,
)
from tools.story_benchmark.run_bm25_lexical_v1 import compute_spoiler_violations


# ---------------------------------------------------------------------------
# Offline mocks (synthetic text only; no private probe content)
# ---------------------------------------------------------------------------

class MockTokenizer:
    def __call__(self, texts, add_special_tokens=True, truncation=False):
        if isinstance(texts, str):
            texts = [texts]
        return {"input_ids": [[0] * len(t.split()) for t in texts]}


class HashEncoderModel:
    """Deterministic text -> unit vector encoder."""
    def __init__(self, dim=16):
        self.tokenizer = MockTokenizer()
        self.max_seq_length = 512
        self.dim = dim

    def get_sentence_embedding_dimension(self):
        return self.dim

    def encode(self, texts, convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False):
        out = []
        for t in texts:
            seed = int(hashlib.sha256(t.encode("utf-8")).hexdigest()[:8], 16)
            v = np.random.default_rng(seed).standard_normal(self.dim)
            out.append(v / np.linalg.norm(v))
        return np.array(out, dtype=np.float32)

    def eval(self):
        pass


class MockMultiQuery(DenseE5MultiQueryV1):
    def __init__(self):
        self.model = HashEncoderModel()
        self.model_name = "mock"
        self.model_revision = "mock"
        self.device = "cpu"
        self.passage_truncation_count = 0
        self.query_truncation_count = 0
        self.doc_ids = []
        self.doc_embeddings = None


class GuardedProbe(dict):
    """Raises if anything other than `question` is read."""
    def __getitem__(self, key):
        if key != "question":
            raise DecompositionLeakageError(f"decomposition read forbidden field: {key}")
        return super().__getitem__(key)

    def get(self, key, default=None):
        return self[key]

    def keys(self):
        raise DecompositionLeakageError("decomposition enumerated probe keys")

    def items(self):
        raise DecompositionLeakageError("decomposition enumerated probe items")

    def values(self):
        raise DecompositionLeakageError("decomposition enumerated probe values")

    def __iter__(self):
        raise DecompositionLeakageError("decomposition iterated probe")


# ---------------------------------------------------------------------------
# Decomposition
# ---------------------------------------------------------------------------

class TestDecomposition(unittest.TestCase):

    def test_frozen_constants(self):
        self.assertEqual(K_RRF, 60)
        self.assertEqual(MIN_CONTENT_TOKENS, 2)
        self.assertEqual(MAX_QUERIES_PER_PROBE, 8)

    def test_normalization(self):
        self.assertEqual(normalize_text("  Ｔｅｓｔ　 text\n\twith   spaces  "), "Test text with spaces")
        self.assertEqual(normalize_text("a b"), "a b")

    def test_q0_is_always_normalized_original(self):
        q = "  Where   did the  blue lantern go?  "
        self.assertEqual(decompose_question(q)[0], "Where did the blue lantern go?")

    def test_enumeration_with_directive(self):
        q = "Sort these scenes: the knight crosses the river, the dragon burns the mill, the queen signs the treaty."
        qs = decompose_question(q)
        self.assertEqual(qs[0], normalize_text(q))
        self.assertIn("the knight crosses the river", qs)
        self.assertIn("the dragon burns the mill", qs)
        self.assertIn("the queen signs the treaty", qs)
        self.assertNotIn("Sort these scenes", qs)

    def test_sentence_split(self):
        q = "The baker opens a new shop. What did the baker say earlier about moving towns?"
        qs = decompose_question(q)
        self.assertIn("The baker opens a new shop", qs)
        self.assertIn("What did the baker say earlier about moving towns", qs)

    def test_range_split_keeps_stem(self):
        self.assertEqual(
            split_range("How does the garden change between Season 2 and Season 9"),
            ["How does the garden change Season 2", "How does the garden change Season 9"],
        )
        self.assertEqual(
            split_range("from the first quarrel to the final reunion"),
            ["the first quarrel", "the final reunion"],
        )
        self.assertEqual(split_range("no range marker here"), ["no range marker here"])

    def test_scoping_fragment_dropped(self):
        qs = decompose_question("As of Part 7, where does the old clockmaker keep his tools?")
        self.assertEqual(qs, ["As of Part 7, where does the old clockmaker keep his tools?",
                              "where does the old clockmaker keep his tools"])
        self.assertLess(content_token_count("As of Part 7"), MIN_CONTENT_TOKENS)

    def test_single_query_when_no_facets(self):
        q = "How does the sailors' trust change over time?"
        self.assertEqual(decompose_question(q), [q])

    def test_duplicate_removal(self):
        q = "the red door opens, The red door opens; the red door opens."
        qs = decompose_question(q)
        keys = [x.casefold().strip(" .?!,;:") for x in qs]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(len(qs), 2)

    def test_no_empty_subqueries(self):
        qs = decompose_question("A, , ;: , the lighthouse keeper waves; ,")
        self.assertTrue(all(q.strip() for q in qs))
        with self.assertRaises(ValueError):
            decompose_question("   \n\t ")

    def test_query_cap(self):
        items = ", ".join(f"item{i} alpha{i} beta{i}" for i in range(20))
        self.assertEqual(len(decompose_question(f"List: {items}.")), MAX_QUERIES_PER_PROBE)

    def test_deterministic(self):
        q = "Sort: the fox runs home, the owl sleeps late. What changed from spring rain to winter snow?"
        runs = [decompose_question(q) for _ in range(5)]
        self.assertTrue(all(r == runs[0] for r in runs))

    def test_decomposition_diagnostics(self):
        d = decomposition_diagnostics([["q"], ["q", "a", "b"], ["q", "a"]])
        self.assertEqual(d["probe_count"], 3)
        self.assertEqual(d["probes_with_multiple_queries"], 2)
        self.assertEqual(d["probes_with_single_query_only"], 1)
        self.assertAlmostEqual(d["mean_queries_per_probe"], 2.0)
        self.assertEqual((d["min_queries_per_probe"], d["max_queries_per_probe"]), (1, 3))
        self.assertEqual(d["queries_per_probe_histogram"], {1: 1, 2: 1, 3: 1})


class TestAntiLeakage(unittest.TestCase):

    def _probe(self):
        return {
            "probe_id": "SYN_01",
            "question": "Sort these: the knight crosses the river, the dragon burns the mill.",
            "category": "CHRONOLOGY",
            "cutoff_chapter": 5,
            "required_evidence_chunk_ids": ["x1", "x2"],
            "supporting_evidence_chunk_ids": ["x3"],
            "expected_answer": "the dragon first",
            "expected_facts": ["dragon", "knight"],
            "earliest_required_chapter": 1,
            "latest_required_chapter": 4,
            "chapter_span": 4,
            "requires_multi_chunk": True,
            "requires_multi_chapter": True,
            "forbidden_future_chapters": [6],
            "difficulty_notes": "the mill burns in chapter 1",
        }

    def test_guarded_probe_only_question_read(self):
        p = self._probe()
        self.assertEqual(decompose_probe(GuardedProbe(p)), decompose_question(p["question"]))

    def test_gold_fields_do_not_affect_decomposition(self):
        p = self._probe()
        base = decompose_probe(p)
        for field in FORBIDDEN_DECOMPOSITION_FIELDS:
            mutated = dict(p)
            mutated[field] = "MUTATED knight river mill dragon burns"
            self.assertEqual(decompose_probe(mutated), base, field)
        self.assertEqual(decompose_probe({"question": p["question"]}), base)

    def test_probe_id_not_special_cased(self):
        p = self._probe()
        other = dict(p, probe_id="P_CHRONO_01")
        self.assertEqual(decompose_probe(p), decompose_probe(other))

    def test_decomposition_source_does_not_reference_gold_fields(self):
        import inspect
        import tools.story_benchmark.dense_e5_multiquery_v1 as mod
        src = "".join(inspect.getsource(f) for f in (
            mod.decompose_question, mod.decompose_probe, mod.question_only_view,
            mod.split_sentences, mod.strip_directive, mod.split_enumeration, mod.split_range,
            mod.clean_facet, mod.content_token_count, mod.normalize_text))
        for field in FORBIDDEN_DECOMPOSITION_FIELDS + ("probe_id",):
            self.assertNotIn(f'"{field}"', src)
            self.assertNotIn(f"'{field}'", src)


# ---------------------------------------------------------------------------
# Fusion, filtering, metrics
# ---------------------------------------------------------------------------

class TestFusion(unittest.TestCase):

    def test_rrf_calculation(self):
        fused = dict(rrf_fuse([["a", "b", "c"], ["b", "c", "a"]]))
        self.assertAlmostEqual(fused["a"], float(Fraction(1, 61) + Fraction(1, 63)))
        self.assertAlmostEqual(fused["b"], float(Fraction(1, 62) + Fraction(1, 61)))
        self.assertAlmostEqual(fused["c"], float(Fraction(1, 63) + Fraction(1, 62)))
        self.assertEqual([d for d, _ in rrf_fuse([["a", "b", "c"], ["b", "c", "a"]])], ["b", "a", "c"])

    def test_rrf_rank_is_one_based(self):
        (doc, score), = rrf_fuse([["only"]])
        self.assertEqual(doc, "only")
        self.assertEqual(score, 1 / 61)

    def test_rrf_tie_break_chunk_id_asc(self):
        # Symmetric rankings -> exact ties, broken by chunk_id ASC.
        self.assertEqual([d for d, _ in rrf_fuse([["z", "a"], ["a", "z"]])], ["a", "z"])
        self.assertEqual([d for d, _ in rrf_fuse([["m", "b"], ["b", "m"], ["c"]])], ["b", "m", "c"])

    def test_rrf_single_query_preserves_order(self):
        ranking = ["d3", "d1", "d2", "d0"]
        self.assertEqual([d for d, _ in rrf_fuse([ranking])], ranking)

    def test_rrf_order_independent(self):
        r = [["a", "b", "c", "d"], ["c", "d", "a", "b"], ["b", "a", "d", "c"]]
        self.assertEqual(rrf_fuse(r), rrf_fuse(list(reversed(r))))

    def test_rrf_rejects_duplicates(self):
        with self.assertRaises(ValueError):
            rrf_fuse([["a", "a"]])

    def test_cutoff_filtering(self):
        meta = {"c1": 1, "c2": 3, "c3": 5, "c4": 6}
        self.assertEqual(eligible_doc_ids(meta, 5), {"c1", "c2", "c3"})
        self.assertEqual(eligible_doc_ids(meta, None), set(meta))

    def test_multiquery_rank_respects_cutoff(self):
        m = MockMultiQuery()
        m.encode_documents(["c1", "c2", "c3"], ["alpha", "beta", "gamma"])
        embs = [m.encode_query_independent(q) for q in ["one", "two"]]
        fused, per_query = m.multiquery_rank(embs, allowed_doc_ids={"c1", "c3"})
        self.assertEqual({d for d, _ in fused}, {"c1", "c3"})
        self.assertEqual(len(per_query), 2)

    def test_metric_calculation(self):
        probe = {"required_evidence_chunk_ids": ["c1", "c2"], "cutoff_chapter": 1}
        ranked = ["c3", "c1", "c2", "c4"]
        m = calculate_metrics(probe, ranked)
        self.assertEqual((m["hit@1"], m["hit@3"]), (0, 1))
        self.assertAlmostEqual(m["recall@1"], 0.0)
        self.assertAlmostEqual(m["recall@3"], 1.0)
        self.assertEqual((m["success@1"], m["success@3"]), (0, 1))
        self.assertAlmostEqual(m["mrr"], 0.5)
        sv = compute_spoiler_violations(probe, ranked, {"c1": 1, "c2": 1, "c3": 2, "c4": 3})
        self.assertEqual(sv["spoiler_violation@1"], 1)

    def test_change_diagnostics(self):
        control = [["a", "b"], ["c", "d"]]
        mq = [["a", "x"], ["c", "d"]]
        cm = [{"recall@10": 0.5, "success@10": 0}, {"recall@10": 1.0, "success@10": 1}]
        mm = [{"recall@10": 1.0, "success@10": 1}, {"recall@10": 1.0, "success@10": 1}]
        d = change_diagnostics(control, mq, cm, mm)
        self.assertAlmostEqual(d["mean_unique_chunks_introduced_top10"], 0.5)
        self.assertAlmostEqual(d["mean_top10_jaccard_overlap"], (1 / 3 + 1.0) / 2)
        self.assertEqual(d["probes_top10_changed"], 1)
        self.assertEqual((d["probes_recall10_improved"], d["probes_recall10_decreased"],
                          d["probes_recall10_unchanged"]), (1, 0, 1))
        self.assertEqual((d["full_evidence_success10_0_to_1"], d["full_evidence_success10_1_to_0"]), (1, 0))


class TestVerdictAndGates(unittest.TestCase):

    def test_verdict_rules(self):
        self.assertEqual(interpret_verdict(0.1, 0.07, 0.0, 10, True), "SUPPORTED")
        self.assertEqual(interpret_verdict(0.1, 0.07, -0.2, 10, True), "PARTIALLY_SUPPORTED")
        self.assertEqual(interpret_verdict(0.1, 0.0, 0.0, 10, True), "PARTIALLY_SUPPORTED")
        self.assertEqual(interpret_verdict(0.0, 0.07, 0.0, 10, True), "PARTIALLY_SUPPORTED")
        self.assertEqual(interpret_verdict(0.0, 0.0, 0.0, 10, True), "NOT_SUPPORTED")
        self.assertEqual(interpret_verdict(-0.1, -0.07, 0.0, 10, True), "NOT_SUPPORTED")
        self.assertEqual(interpret_verdict(0.3, 0.3, 0.0, 2, True), "NOT_EVALUABLE")
        self.assertEqual(interpret_verdict(0.3, 0.3, 0.0, 10, False), "NOT_EVALUABLE")

    def test_exact_control_rank_comparison(self):
        f = {"p1": ["c1", "c2"], "p2": ["c3", "c4"]}
        self.assertEqual(check_control_rankings({"p1": ["c1", "c2"], "p2": ["c3", "c4"]}, f), [])
        self.assertEqual(check_control_rankings({"p1": ["c2", "c1"], "p2": ["c3", "c4"]}, f), ["p1"])
        self.assertEqual(check_control_rankings({"p1": ["c1", "c2"]}, f), ["p2"])

    def test_control_aggregate_comparison(self):
        base = {k: 0.5 for k in ["hit@1", "hit@3", "hit@5", "hit@10", "recall@1", "recall@3",
                                 "recall@5", "recall@10", "success@1", "success@3", "success@5",
                                 "success@10", "spoiler_violation@1", "spoiler_violation@3",
                                 "spoiler_violation@5", "spoiler_violation@10", "mrr"]}
        self.assertEqual(check_control_aggregate(base, dict(base)), [])
        self.assertEqual(check_control_aggregate(base, dict(base, mrr=0.51)), ["mrr"])

    def test_determinism_verification(self):
        a1 = {"detailed_results_sha256": {"x": "1"}, "m": 0.5,
              "dense_diagnostics": {"encoding_runtime_sec": 1.0, "retrieval_evaluation_runtime_sec": 2.0}}
        a2 = {"detailed_results_sha256": {"x": "1"}, "m": 0.5,
              "dense_diagnostics": {"encoding_runtime_sec": 9.0, "retrieval_evaluation_runtime_sec": 8.0}}
        self.assertTrue(verify_multiquery_determinism(a1, a2))
        self.assertFalse(verify_multiquery_determinism(a1, dict(a2, detailed_results_sha256={"x": "2"})))
        self.assertFalse(verify_multiquery_determinism(a1, dict(a2, m=0.6)))

    def test_privacy_scan(self):
        self.assertEqual(find_private_leaks("hit@10: 0.9", ["ch001_c0001", "secret question?"]), [])
        self.assertEqual(find_private_leaks("id: ch001_c0001", ["ch001_c0001"]), ["ch001_c0001"])

    @patch("tools.story_benchmark.dense_e5_small_v1.SentenceTransformer")
    def test_offline_proof(self, mock_st):
        mock_st.side_effect = RuntimeError("SentenceTransformer must not load in unit tests")
        self.assertIsInstance(MockMultiQuery().model, HashEncoderModel)
        with self.assertRaises(RuntimeError):
            DenseE5MultiQueryV1()


# ---------------------------------------------------------------------------
# End-to-end runner (synthetic corpus, mock encoder)
# ---------------------------------------------------------------------------

class TestRunnerEndToEnd(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.probes_path = root / "probes.yaml"
        self.chunks_path = root / "chunks.jsonl"
        self.freeze_path = root / "freeze.yaml"
        self.f_detail = root / "F" / "cutoff_filtered_per_probe.jsonl"
        self.f_result = root / "F_RESULT.yaml"
        self.out_dir = root / "out"

        chunks = [{"chunk_id": f"ch{c:03d}_c{i:04d}", "chapter_number": c, "text": f"synthetic passage {c}-{i}"}
                  for c in range(1, 6) for i in range(1, 4)]
        with open(self.chunks_path, "w", encoding="utf-8", newline="\n") as f:
            for c in chunks:
                f.write(json.dumps(c) + "\n")
        self.probes = [
            {"probe_id": "SYN_A", "category": "CAT1", "cutoff_chapter": 5,
             "question": "Sort: the fox runs home, the owl sleeps late, the crow steals bread.",
             "required_evidence_chunk_ids": ["ch001_c0001", "ch003_c0002"]},
            {"probe_id": "SYN_B", "category": "CAT1", "cutoff_chapter": 3,
             "question": "As of Part 3, what did the miller hide beneath the stairs?",
             "required_evidence_chunk_ids": ["ch002_c0001", "ch003_c0003"]},
            {"probe_id": "SYN_C", "category": "CAT2", "cutoff_chapter": 4,
             "question": "How does the sailors' trust change over time?",
             "required_evidence_chunk_ids": ["ch004_c0001", "ch001_c0002"]},
            {"probe_id": "SYN_D", "category": "CAT2", "cutoff_chapter": 5,
             "question": "How does the garden change between Season 2 and Season 9?",
             "required_evidence_chunk_ids": ["ch005_c0001", "ch002_c0002"]},
        ]
        with open(self.probes_path, "w", encoding="utf-8") as f:
            yaml.dump({"probes": self.probes}, f, allow_unicode=True)

        def sha(p):
            return hashlib.sha256(p.read_bytes()).hexdigest()

        with open(self.freeze_path, "w", encoding="utf-8") as f:
            yaml.dump({"status": "FROZEN", "probe_count": len(self.probes),
                       "probe_file_sha256": sha(self.probes_path),
                       "chunks_jsonl_sha256": sha(self.chunks_path)}, f)

        # Simulate F with the same mock encoder: single-query cosine ranking.
        f_model = MockMultiQuery()
        f_model.encode_documents([c["chunk_id"] for c in chunks], [c["text"] for c in chunks])
        meta = {c["chunk_id"]: c["chapter_number"] for c in chunks}
        rows, mlist = [], []
        for p in self.probes:
            q = f_model.encode_queries([p["question"]])[0]
            ranked = f_model.score_embedding(q, eligible_doc_ids(meta, p["cutoff_chapter"]))
            ids = [d for d, _ in ranked]
            m = calculate_metrics(p, ids)
            m.update(compute_spoiler_violations(p, ids, meta))
            rows.append({"probe_id": p["probe_id"], "retrieved_chunk_ids": ids})
            mlist.append((p["category"], m))
        self.f_detail.parent.mkdir(parents=True)
        with open(self.f_detail, "w", encoding="utf-8", newline="\n") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        self.f_agg = {"CUTOFF_FILTERED": aggregate(mlist),
                      "detailed_results_sha256": {"cutoff_filtered_per_probe.jsonl": sha(self.f_detail)}}
        with open(self.f_result, "w", encoding="utf-8") as f:
            yaml.dump(self.f_agg, f)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self):
        return run_multiquery(self.probes_path, self.chunks_path, self.out_dir, self.freeze_path,
                              self.f_detail, self.f_result, dense=MockMultiQuery())

    def test_end_to_end_control_gate_determinism_privacy(self):
        agg1, private = self._run()
        agg2, _ = self._run()
        self.assertTrue(verify_multiquery_determinism(agg1, agg2))
        self.assertEqual(agg1["relevance_control"]["exact_ranking_reproduction"], "PASS")
        self.assertEqual(agg1["spoiler_cutoff_status"], "PASS")
        self.assertEqual(agg1["DECOMPOSITION_DIAGNOSTICS"]["probe_count"], 4)
        self.assertEqual(agg1["DECOMPOSITION_DIAGNOSTICS"]["probes_with_single_query_only"], 1)

        agg1["DENSE_E5_SMALL_V1_COMPARISON"] = compare_with_f(agg1, self.f_agg)
        serialized = yaml.dump(agg1, sort_keys=False, allow_unicode=True)
        self.assertEqual(find_private_leaks(serialized, private["forbidden_strings"]), [])
        for p in self.probes:
            self.assertIn(p["question"], private["forbidden_strings"])
            self.assertNotIn(p["question"], serialized)

        # Single-query probe: fused ranking must equal the control ranking.
        cutoff_rows = [json.loads(l) for l in (self.out_dir / "multiquery_cutoff_per_probe.jsonl").read_text(encoding="utf-8").splitlines()]
        control_rows = [json.loads(l) for l in (self.out_dir / "relevance_control_per_probe.jsonl").read_text(encoding="utf-8").splitlines()]
        for c, m in zip(control_rows, cutoff_rows):
            if m["query_count"] == 1:
                self.assertEqual(c["retrieved_chunk_ids"], m["retrieved_chunk_ids"])

    def test_missing_f_artifact_stops(self):
        self.f_detail.unlink()
        with self.assertRaises(GateFailure):
            self._run()

    def test_tampered_f_ranking_fails_fast(self):
        lines = self.f_detail.read_text(encoding="utf-8").splitlines()
        row = json.loads(lines[0])
        row["retrieved_chunk_ids"] = list(reversed(row["retrieved_chunk_ids"]))
        lines[0] = json.dumps(row)
        self.f_detail.write_text("\n".join(lines) + "\n", encoding="utf-8")
        # Keep the sha consistent so the ranking comparison itself is what fails.
        self.f_agg["detailed_results_sha256"]["cutoff_filtered_per_probe.jsonl"] = \
            hashlib.sha256(self.f_detail.read_bytes()).hexdigest()
        with open(self.f_result, "w", encoding="utf-8") as f:
            yaml.dump(self.f_agg, f)
        with self.assertRaisesRegex(GateFailure, "exact-ranking"):
            self._run()

    def test_freeze_mismatch_fails(self):
        with open(self.freeze_path, "r", encoding="utf-8") as f:
            fr = yaml.safe_load(f)
        fr["probe_file_sha256"] = "0" * 64
        with open(self.freeze_path, "w", encoding="utf-8") as f:
            yaml.dump(fr, f)
        with self.assertRaises(GateFailure):
            self._run()


class TestPublicArtifact(unittest.TestCase):
    """If the public result exists, it must be aggregate-only."""

    def test_public_result_has_no_private_identifiers(self):
        pub = Path(__file__).resolve().parents[2] / "benchmarks/m1_script_quality/long_range_probe/DENSE_E5_MULTIQUERY_V1_RESULT.yaml"
        if not pub.exists():
            self.skipTest("public result not generated yet")
        text = pub.read_text(encoding="utf-8")
        import re
        self.assertIsNone(re.search(r"ch\d{3}_c\d{4}", text))
        self.assertIsNone(re.search(r"\bP_[A-Z]+_\d{2}\b", text))
        self.assertNotIn("?", text)


if __name__ == "__main__":
    unittest.main()
