"""Tests for the deterministic fresh-holdout selection rules (M4_FRESH_HOLDOUT_SELECTION_V1).

Synthetic segment ids only. No source text, model, API or network.
"""
import hashlib
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.story_extraction import holdout_selection_v1 as H  # noqa: E402

FP = "f" * 64


def corpus(documents=6, segments=20):
    return {f"doc-{d}": [f"seg-{d}-{i:02d}" for i in range(segments)] for d in range(documents)}


def setup(documents, exposed):
    excluded = set(exposed) | H.exposure_halo(documents, set(exposed))
    windows = H.eligible_anchors(documents, excluded)
    order = H.ordered_anchors(windows, FP)
    document_of = {s: d for d, segs in documents.items() for s in segs}
    return excluded, windows, order, document_of


class TestExposureAndHalo(unittest.TestCase):
    def test_halo_is_two_segments_each_side_in_the_same_document(self):
        docs = corpus(2, 10)
        halo = H.exposure_halo(docs, {"seg-0-05"})
        self.assertEqual(halo, {"seg-0-03", "seg-0-04", "seg-0-06", "seg-0-07"})
        self.assertEqual(H.HALO, 2)

    def test_halo_does_not_cross_documents_and_clips_at_edges(self):
        docs = corpus(2, 10)
        self.assertEqual(H.exposure_halo(docs, {"seg-0-09"}), {"seg-0-07", "seg-0-08"})
        self.assertEqual(H.exposure_halo(docs, {"seg-1-00"}), {"seg-1-01", "seg-1-02"})

    def test_exposed_and_halo_segments_are_never_anchors_or_window_members(self):
        docs = corpus(3, 30)
        exposed = {"seg-0-10", "seg-1-00", "seg-2-29"}
        excluded, windows, order, _ = setup(docs, exposed)
        self.assertFalse(excluded & set(order))
        for window in windows.values():
            self.assertFalse(excluded & set(window))

    def test_mechanical_processing_is_not_an_input(self):
        # The functions take only an exposed set: nothing about ingestion, chunking or retrieval excludes a span.
        # With nothing exposed, only the window-size rule removes anchors (the first and last segment
        # of a 12-segment document have a 4-segment window).
        docs = corpus(1, 12)
        self.assertEqual(len(H.eligible_anchors(docs, set())), 10)


class TestWindow(unittest.TestCase):
    def test_three_before_and_three_after(self):
        docs = corpus(1, 20)["doc-0"]
        self.assertEqual(H.build_window(docs, "seg-0-10", set()), [f"seg-0-{i:02d}" for i in range(7, 14)])

    def test_clipped_by_document_boundary(self):
        docs = corpus(1, 20)["doc-0"]
        self.assertEqual(H.build_window(docs, "seg-0-01", set()), [f"seg-0-{i:02d}" for i in range(0, 5)])
        self.assertEqual(len(H.build_window(docs, "seg-0-19", set())), 4)

    def test_clipped_at_first_excluded_segment(self):
        docs = corpus(1, 20)["doc-0"]
        window = H.build_window(docs, "seg-0-10", {"seg-0-08", "seg-0-13"})
        self.assertEqual(window, ["seg-0-09", "seg-0-10", "seg-0-11", "seg-0-12"])

    def test_minimum_window_size(self):
        docs = corpus(1, 20)
        windows = H.eligible_anchors(docs, {"seg-0-08", "seg-0-13"})
        self.assertNotIn("seg-0-10", windows)                # only four consecutive free segments
        self.assertTrue(all(len(w) >= H.MIN_WINDOW_SEGMENTS for w in windows.values()))


class TestOrdering(unittest.TestCase):
    def test_order_is_the_documented_hash(self):
        segment = "seg-0-03"
        expected = hashlib.sha256((H.PROTOCOL_ID + FP + segment).encode("utf-8")).hexdigest()
        self.assertEqual(H.anchor_hash(FP, segment), expected)
        anchors = corpus(2, 10)["doc-0"]
        order = H.ordered_anchors(anchors, FP)
        self.assertEqual(order, sorted(anchors, key=lambda s: H.anchor_hash(FP, s)))
        self.assertEqual(order, H.ordered_anchors(reversed(anchors), FP))      # input order is irrelevant

    def test_order_depends_on_the_corpus_fingerprint_and_uses_no_random_state(self):
        anchors = corpus(1, 12)["doc-0"]
        self.assertNotEqual(H.ordered_anchors(anchors, FP), H.ordered_anchors(anchors, "0" * 64))
        source = Path(H.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import random", source)


class TestDocumentDiversity(unittest.TestCase):
    def test_first_pass_takes_one_anchor_per_document(self):
        docs = corpus(15, 20)
        _, windows, order, document_of = setup(docs, set())
        result = H.select_cases(order, document_of, windows)
        self.assertEqual(len(result["selected"]), H.TARGET_CASES)
        self.assertEqual(len({document_of[a] for a in result["selected"]}), 12)
        self.assertEqual({t["pass"] for t in result["trace"]}, {"FIRST_PASS"})

    def test_second_pass_adds_at_most_one_more_per_document(self):
        docs = corpus(8, 40)
        _, windows, order, document_of = setup(docs, set())
        result = H.select_cases(order, document_of, windows)
        self.assertEqual(len(result["selected"]), 12)
        per_document = {}
        for anchor in result["selected"]:
            per_document[document_of[anchor]] = per_document.get(document_of[anchor], 0) + 1
        self.assertEqual(max(per_document.values()), 2)
        self.assertEqual([t["pass"] for t in result["trace"]].count("FIRST_PASS"), 8)

    def test_selection_follows_hash_order_and_windows_do_not_overlap(self):
        docs = corpus(8, 40)
        _, windows, order, document_of = setup(docs, set())
        result = H.select_cases(order, document_of, windows)
        ranks = [t["hash_rank"] for t in result["trace"]]
        self.assertEqual(ranks[:8], sorted(ranks[:8]))
        used = [s for a in result["selected"] for s in windows[a]]
        self.assertEqual(len(used), len(set(used)))

    def test_fewer_cases_when_the_population_is_too_small(self):
        docs = corpus(3, 9)
        _, windows, order, document_of = setup(docs, set())
        self.assertLess(len(H.select_cases(order, document_of, windows)["selected"]), H.TARGET_CASES)

    def test_selection_is_deterministic(self):
        docs = corpus(15, 20)
        _, windows, order, document_of = setup(docs, {"seg-3-07"})
        self.assertEqual(H.select_cases(order, document_of, windows), H.select_cases(order, document_of, windows))


class TestReplacement(unittest.TestCase):
    def setUp(self):
        self.docs = corpus(15, 20)
        _, self.windows, self.order, self.document_of = setup(self.docs, set())
        self.initial = H.select_cases(self.order, self.document_of, self.windows)["selected"]

    def test_no_rejection_keeps_the_selection(self):
        result = H.replace_rejected(self.order, self.document_of, self.windows, self.initial, {})
        self.assertEqual(result["selected"], self.initial)
        self.assertEqual(result["replacement_trace"], [])

    def test_rejected_case_is_replaced_by_the_next_unused_anchor_in_hash_order(self):
        rejected = self.initial[4]
        result = H.replace_rejected(self.order, self.document_of, self.windows, self.initial,
                                    {rejected: "PURE_PARATEXT"})
        self.assertEqual(len(result["selected"]), 12)
        self.assertNotIn(rejected, result["selected"])
        trace = result["replacement_trace"][0]
        self.assertEqual(trace["reason"], "PURE_PARATEXT")
        replacement = self.order[trace["replacement_hash_rank"] - 1]
        self.assertNotIn(replacement, self.initial)
        # It is the earliest anchor in hash order that the diversity limit and window rule allow.
        kept_documents = {self.document_of[a] for a in self.initial if a != rejected}
        taken = {s for a in self.initial if a != rejected for s in self.windows[a]}
        expected = next(a for a in self.order if a not in self.initial
                        and self.document_of[a] not in kept_documents and not taken & set(self.windows[a]))
        self.assertEqual(replacement, expected)

    def test_rejected_anchor_is_never_reused_and_trace_records_ranks(self):
        rejections = {self.initial[0]: "NO_STORY_CONTENT", self.initial[1]: "SOURCE_CORRUPTION"}
        result = H.replace_rejected(self.order, self.document_of, self.windows, self.initial, rejections)
        self.assertFalse(set(rejections) & set(result["selected"]))
        self.assertEqual(len(result["replacement_trace"]), 2)
        for entry in result["replacement_trace"]:
            self.assertGreaterEqual(entry["replacement_hash_rank"], 1)
            self.assertIn(entry["reason"], H.REJECTION_REASONS)

    def test_only_preregistered_reasons_are_accepted(self):
        for reason in ("TOO_DIFFICULT", "AMBIGUOUS", "RARE_SEMANTICS", "MODEL_WOULD_FAIL", "INCONVENIENT"):
            with self.subTest(reason), self.assertRaises(ValueError):
                H.replace_rejected(self.order, self.document_of, self.windows, self.initial, {self.initial[0]: reason})

    def test_case_count_never_grows(self):
        result = H.replace_rejected(self.order, self.document_of, self.windows, self.initial,
                                    {self.initial[2]: "PURE_PARATEXT"})
        self.assertEqual(len(result["selected"]), len(self.initial))


if __name__ == "__main__":
    unittest.main()
