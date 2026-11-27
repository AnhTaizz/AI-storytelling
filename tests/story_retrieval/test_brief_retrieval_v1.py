"""Behavioural contract for brief retrieval (M6 Phase 2, DEC-021) and its evaluation."""

import contextlib
import copy
import io
import json
import unittest

from tools.story_pipeline.source import Passage
from tools.story_retrieval import brief_retrieval_v1 as br
from tools.story_retrieval import evaluate_brief_v1


def brief(n, events, facts=(), relationships=()):
    """A minimal brief for chapter n: events (id, summary, evidence), facts for CH1."""
    return {
        "chapter_order": n,
        "characters": [{"id": "CH1", "name": "真昼", "romanized_name": "Mahiru", "aliases": ["Thiên sứ"],
                        "facts": [{"text": t, "evidence": ev, "quote": "q", "epistemic": "EXPLICIT"} for t, ev in facts]},
                       {"id": "CH2", "name": "周", "romanized_name": "Amane", "aliases": [], "facts": []}],
        "relationships": [{"between": ["CH1", "CH2"], "state": s, "evidence": ev, "quote": "q", "epistemic": "EXPLICIT"}
                          for s, ev in relationships],
        "events": [{"id": eid, "summary": s, "participants": ["CH1", "CH2"], "location": "công viên",
                    "importance": "CORE", "motivation": {"text": None, "status": "UNKNOWN"}, "consequence": None,
                    "evidence": ev, "quote": "q", "epistemic": "EXPLICIT"} for eid, s, ev in events],
    }


BRIEFS = [
    brief(1, [("E1", "Amane đưa chiếc ô cho Mahiru dưới mưa", ["1.1"])],
          facts=[("Mahiru luôn đứng đầu kỳ thi", ["1.2"])], relationships=[("hàng xóm xa lạ", ["1.2"])]),
    brief(2, [("E1", "Mahiru trả lại chiếc ô và mang thuốc cảm", ["2.1", "2.2"])]),
    brief(3, [("E1", "Mahiru nấu cháo cho Amane đang ốm", ["3.1"])]),
]
PASSAGES = [Passage(pid, f"source {pid}") for pid in ("1.1", "1.2", "2.1", "2.2", "3.1")]


def corpus(cutoff=3, briefs=BRIEFS):
    return br.build_brief_corpus("story-x", briefs, PASSAGES, cutoff, "vi")


class BriefCorpusTests(unittest.TestCase):
    def test_items_have_snapshot_bound_refs_and_their_own_words(self):
        c = corpus()
        self.assertEqual([(i.ref, i.kind) for i in c.items],
                         [("c1.E1", "event"), ("c1.CH1.F1", "fact"), ("c1.R1", "relationship"),
                          ("c2.E1", "event"), ("c3.E1", "event")])
        self.assertTrue(all(br.is_item_ref(i.ref) for i in c.items))
        self.assertIn("Mahiru / 真昼 / Thiên sứ: Mahiru luôn đứng đầu kỳ thi", c.items[1].text)
        self.assertEqual(c.items[2].text, "Mahiru – Amane: hàng xóm xa lạ")
        self.assertIn("Địa điểm: công viên", c.items[0].text)
        changed = copy.deepcopy(BRIEFS)
        changed[0]["events"][0]["summary"] = "khác"
        self.assertNotEqual(corpus(briefs=changed).snapshot, c.snapshot)  # content-bound identity
        self.assertEqual(corpus().snapshot, c.snapshot)

    def test_later_chapters_never_enter_and_bad_evidence_rejects_the_corpus(self):
        self.assertEqual({i.chapter for i in corpus(cutoff=2).items}, {1, 2})
        self.assertNotIn("3.1", corpus(cutoff=2).passages)
        bad_cases = {
            "missing chapter": (BRIEFS[1:], r"no brief for chapters \[1\]"),
            "evidence of another chapter": ([brief(1, [("E1", "x", ["2.1"])]), *BRIEFS[1:]], "outside chapter 1"),
            "unknown passage": ([brief(1, [("E1", "x", ["1.9"])]), *BRIEFS[1:]], "not a passage"),
            "no evidence": ([brief(1, [("E1", "x", [])]), *BRIEFS[1:]], "no evidence"),
            "duplicate ids": ([brief(1, [("E1", "x", ["1.1"]), ("E1", "y", ["1.1"])]), *BRIEFS[1:]], "duplicate"),
        }
        for label, (briefs, message) in bad_cases.items():
            with self.subTest(label), self.assertRaisesRegex(ValueError, message):
                corpus(briefs=briefs)
        with self.assertRaises(ValueError):
            corpus(cutoff=0)


class RetrievalTests(unittest.TestCase):
    def test_hits_carry_their_complete_evidence_and_respect_the_cutoff(self):
        c = corpus()
        hits = br.retrieve_briefs("Mahiru trả lại chiếc ô", c, k=3)
        self.assertEqual(hits[0].item.ref, "c2.E1")
        self.assertEqual(hits[0].evidence, (("2.1", "source 2.1"), ("2.2", "source 2.2")))
        self.assertEqual([h.rank for h in hits], list(range(1, len(hits) + 1)))
        early = br.retrieve_briefs("Mahiru nấu cháo", c, cutoff_chapter=2, k=5)
        self.assertTrue(all(h.item.chapter <= 2 for h in early))
        self.assertEqual([h.item.ref for h in br.retrieve_briefs("hàng xóm", c, kinds=("relationship",))], ["c1.R1"])
        self.assertEqual(br.retrieve_briefs("chiếc ô", c, chapters=(2, 2))[0].item.ref, "c2.E1")
        self.assertEqual(br.retrieve_briefs("không liên quan gì", c), [])

    def test_bad_requests_are_rejected(self):
        c = corpus(cutoff=2)
        for label, kwargs in {"empty query": {"query": " "}, "k": {"k": 0}, "after corpus": {"cutoff_chapter": 3},
                              "window": {"chapters": (2, 3)}, "kind": {"kinds": ("scene",)}}.items():
            with self.subTest(label), self.assertRaises(ValueError):
                br.retrieve_briefs(**{"query": "ô", "corpus": c, **kwargs})

    def test_an_unsafe_retriever_cannot_leak_later_content(self):
        class Leaky:
            name, version = "leaky", "0"

            def index(self, passages):
                pass

            def search(self, query, allowed, k):
                return [("c3.E1", 9.0), ("c1.E1", 1.0)]  # ignores `allowed`

        hits = br.retrieve_briefs("ô", corpus(), cutoff_chapter=2, retriever=Leaky())
        self.assertEqual([h.item.ref for h in hits], ["c1.E1"])

    def test_delivery_dossier_and_callbacks(self):
        c = corpus()
        hits = br.retrieve_briefs("Mahiru chiếc ô", c, k=5)
        delivered = br.delivery(hits, budget=2)
        self.assertEqual(len(delivered["passage_ids"]), 2)
        self.assertTrue(delivered["overflow"])  # support that did not fit is reported
        dossier = br.entity_evidence(c, ["Thiên sứ"])
        self.assertEqual((dossier["status"], dossier["items"]), ("partial", ["c1.CH1.F1"]))
        self.assertEqual(br.entity_evidence(c, ["Mahiru"])["passage_ids"], ["1.1", "1.2", "2.1", "2.2", "3.1"])
        with self.assertRaises(ValueError):
            br.entity_evidence(c, [" "])
        callbacks = br.callback_candidates(corpus(cutoff=2), ["Mahiru đưa lại chiếc ô", ""], per_query=1,
                                           exclude={"c2.E1"})
        self.assertEqual([(cb["ref"], cb["evidence"]) for cb in callbacks], [("c1.E1", ["1.1"])])
        self.assertEqual(callbacks[0]["summary"], "Amane đưa chiếc ô cho Mahiru dưới mưa")

    def test_tokenizers_follow_the_brief_language(self):
        self.assertEqual(br.latin_words_bigrams_v1("Hàng xóm"), ["hàng", "xóm", "hàng_xóm"])
        for language in ("ja", "zh", "vi"):
            with self.subTest(language):
                retriever = br.BriefLexicalRetrieverV1(language)
                retriever.index([Passage("c1.E1", "真昼 傘 Mahiru"), Passage("c1.E2", "別")])
                retriever.index([Passage("c1.E1", "真昼 傘 Mahiru"), Passage("c1.E2", "別")])  # reused
                self.assertEqual(retriever.search("Mahiru 真昼", {"c1.E1", "c1.E2"}, 2)[0][0], "c1.E1")

    def test_hybrid_brief_retriever_and_passage_rrf_fuse_cross_lingual_and_respect_cutoff(self):
        class FakeDense:
            name, version = "fake_dense", "0"

            def __init__(self, ranked):
                self._ranked = ranked
                self.indexed = None

            def index(self, passages):
                self.indexed = [p.passage_id for p in passages]

            def search(self, query, allowed, k):
                return [(ref, score) for ref, score in self._ranked if ref in allowed][:k]

        c = corpus(cutoff=2)
        hybrid = br.BriefHybridRetrieverV1("vi", FakeDense([("c2.E1", 0.9), ("c1.E1", 0.7), ("c3.E1", 0.99)]))
        # Cross-lingual query has zero Vietnamese lexical hits, so dense bridges it without leaking c3.E1.
        ja_hits = br.retrieve_briefs("傘を返した", c, k=5, retriever=hybrid)
        self.assertEqual([h.item.ref for h in ja_hits], ["c2.E1", "c1.E1"])
        # Vietnamese query fuses lexical and dense rankings.
        vi_hits = br.retrieve_briefs("Mahiru trả lại chiếc ô", c, k=5, retriever=hybrid)
        self.assertEqual(vi_hits[0].item.ref, "c2.E1")
        self.assertIn("fake_dense", vi_hits[0].retriever)

        # Passage-level RRF deduplicates within each list, breaks ties deterministically and enforces budget.
        fused = br.rrf_fuse_passages([["2.1", "2.1", "1.1"], ["1.1", "2.2"]], budget=2)
        self.assertEqual(fused, ["1.1", "2.1"])
        self.assertEqual(br.rrf_fuse_passages([[], ["1.2", "1.10", "1.2"]]), ["1.2", "1.10"])
        for label, fn in {
            "bad hybrid k_rrf": lambda: br.BriefHybridRetrieverV1("vi", FakeDense([]), k_rrf=0),
            "bad rrf k_rrf": lambda: br.rrf_fuse_passages([["1.1"]], k_rrf=0),
            "negative budget": lambda: br.rrf_fuse_passages([["1.1"]], budget=-1),
        }.items():
            with self.subTest(label), self.assertRaises(ValueError):
                fn()


class EvaluationTests(unittest.TestCase):
    def test_pinned_briefs_beat_passage_bm25_on_vietnamese_probes_without_leaks(self):
        result = evaluate_brief_v1.evaluate(k_values=(10, 30))
        self.assertEqual(result["probe_count"], 30)
        routes = result["routes"]
        self.assertGreater(routes["brief_bm25"]["per_language"]["vi"]["success@10"],
                           routes["passage_bm25"]["per_language"]["vi"]["success@10"])
        self.assertGreaterEqual(routes["brief_then_passage"]["overall"]["success@30"],
                                routes["passage_bm25"]["overall"]["success@30"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(evaluate_brief_v1.main(["--k-values", "10", "--json"]), 0)
        self.assertIn("brief_then_passage", json.loads(out.getvalue())["routes"])
        self.assertIn("| brief_bm25 | vi |", evaluate_brief_v1.table(result, (10, 30)))
        with self.assertRaises(ValueError):
            evaluate_brief_v1.evaluate(k_values=())


if __name__ == "__main__":
    unittest.main()
