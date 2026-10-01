"""Tests for the Light Novel source adapter v0 (LIGHT_NOVEL_INGESTION/v0).

All fixtures are synthetic and built in temporary directories. No private corpus,
model, API or network is used. One smoke test reads tracked sample documents and
records mechanical facts only.
"""
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import yaml  # noqa: E402

from tools.canonical_story.conformance_v0 import validate_document  # noqa: E402
from tools.story_ingestion import light_novel_adapter_v0 as adapter  # noqa: E402
from tools.story_ingestion.light_novel_adapter_v0 import IngestionError  # noqa: E402

# Non-ASCII test text is built from code points so this file stays ASCII.
HIRAGANA = "".join(chr(cp) for cp in (0x3042, 0x3044, 0x3046))          # 3 bytes each
IDEOGRAPHIC_SPACE = chr(0x3000)
EMOJI = chr(0x1F600)                                                      # 4 bytes, outside the BMP
ACCENTED = "caf" + chr(0x00E9)                                            # 2-byte character


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Corpus:
    """Writes synthetic source files and the matching manifest into a temporary directory."""

    def __init__(self, documents, story_id="story-syn-01", stream_id="stream-syn-01", subdir="src"):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.manifest = {"contract_version": "LIGHT_NOVEL_INGESTION/v0", "story_id": story_id,
                         "stream_id": stream_id, "source_language": "en", "documents": []}
        for index, (document_id, order, data) in enumerate(documents):
            relative = f"{subdir}/unit_{index}.txt"
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            self.manifest["documents"].append({"document_id": document_id, "order": order, "path": relative,
                                               "expected_sha256": sha(data)})

    def ingest(self):
        return adapter.ingest(self.manifest, self.root)

    def close(self):
        self._tmp.cleanup()


class AdapterTestCase(unittest.TestCase):
    def corpus(self, documents, **kwargs):
        corpus = Corpus(documents, **kwargs)
        self.addCleanup(corpus.close)
        return corpus

    def assertRejected(self, code, fn, *args, **kwargs):
        with self.assertRaises(IngestionError) as ctx:
            fn(*args, **kwargs)
        self.assertEqual(ctx.exception.code, code)

    def assertRoundTrip(self, result):
        for doc in result.documents:
            for seg in doc.segments:
                loc = seg["locator"]
                text = doc.text[loc["char_start"]:loc["char_end_exclusive"]]
                self.assertTrue(text)
                self.assertEqual(doc.source_bytes[loc["byte_start"]:loc["byte_end_exclusive"]].decode("utf-8"), text)
                self.assertEqual(sha(text.encode("utf-8")), loc["segment_text_sha256"])
                self.assertEqual(loc["source_sha256"], doc.version)
                self.assertEqual(result.segment_text(seg["id"]), text)


TWO_DOCS = [("doc-a", 1, b"First paragraph.\n\nSecond paragraph.\n"),
            ("doc-b", 2, b"Third paragraph.\n\nFourth paragraph.\n\nFifth paragraph.\n")]


class TestSegmentation(AdapterTestCase):
    def test_01_one_document_one_paragraph(self):
        result = self.corpus([("doc-a", 1, b"Only paragraph.")]).ingest()
        self.assertEqual(len(result.documents), 1)
        self.assertEqual(len(result.documents[0].segments), 1)
        self.assertEqual(result.segment_text(result.documents[0].segments[0]["id"]), "Only paragraph.")

    def test_02_multiple_paragraphs(self):
        result = self.corpus([("doc-a", 1, b"One.\n\nTwo.\n\n\nThree.\n")]).ingest()
        texts = [result.segment_text(s["id"]) for s in result.documents[0].segments]
        self.assertEqual(texts, ["One.", "Two.", "Three."])
        self.assertEqual([s["locator"]["paragraph_ordinal"] for s in result.documents[0].segments], [1, 2, 3])

    def test_03_multiple_ordered_documents(self):
        corpus = self.corpus([("doc-b", 20, b"Later.\n"), ("doc-a", 10, b"Earlier.\n")])
        result = corpus.ingest()
        self.assertEqual([d.document_id for d in result.documents], ["doc-a", "doc-b"])
        keys = [s["position"]["key"] for d in result.documents for s in d.segments]
        self.assertEqual(keys, [[10, 1], [20, 1]])
        self.assertEqual(keys, sorted(keys))

    def test_04_crlf_is_preserved(self):
        data = b"Line one.\r\nLine two.\r\n\r\nNext paragraph.\r\n"
        result = self.corpus([("doc-a", 1, data)]).ingest()
        texts = [result.segment_text(s["id"]) for s in result.documents[0].segments]
        self.assertEqual(texts, ["Line one.\r\nLine two.", "Next paragraph."])
        self.assertEqual(result.documents[0].text.encode("utf-8"), data)
        self.assertEqual(result.ingestion_report()["documents"][0]["line_endings"], {"LF": 0, "CRLF": 4, "CR": 0})
        self.assertRoundTrip(result)

    def test_05_unicode_multibyte(self):
        text = f"{IDEOGRAPHIC_SPACE}{HIRAGANA} {ACCENTED} {EMOJI}\n\n{HIRAGANA}{EMOJI}\n"
        result = self.corpus([("doc-a", 1, text.encode("utf-8"))]).ingest()
        first, second = result.documents[0].segments
        self.assertEqual(result.segment_text(first["id"]), f"{IDEOGRAPHIC_SPACE}{HIRAGANA} {ACCENTED} {EMOJI}")
        self.assertGreater(first["locator"]["byte_end_exclusive"] - first["locator"]["byte_start"],
                           first["locator"]["char_end_exclusive"] - first["locator"]["char_start"])
        self.assertNotEqual(second["locator"]["char_start"], second["locator"]["byte_start"])
        self.assertRoundTrip(result)

    def test_06_leading_and_trailing_blank_regions(self):
        data = f"\n \n{IDEOGRAPHIC_SPACE}\n\tBody text.  \n\n \n".encode("utf-8")
        result = self.corpus([("doc-a", 1, data)]).ingest()
        self.assertEqual(len(result.documents[0].segments), 1)
        # Leading and trailing whitespace of the paragraph line itself is source text and is kept.
        self.assertEqual(result.segment_text(result.documents[0].segments[0]["id"]), "\tBody text.  ")
        self.assertEqual(result.documents[0].text.encode("utf-8"), data)

    def test_07_multi_line_paragraph(self):
        result = self.corpus([("doc-a", 1, b"a\nb\nc\n\nd\n")]).ingest()
        texts = [result.segment_text(s["id"]) for s in result.documents[0].segments]
        self.assertEqual(texts, ["a\nb\nc", "d"])

    def test_08_very_long_paragraph_stays_one_segment(self):
        long_paragraph = ("word " * 2000).strip()
        self.assertGreater(len(long_paragraph), 1200 * 5)
        result = self.corpus([("doc-a", 1, (long_paragraph + "\n\nshort\n").encode("utf-8"))]).ingest()
        self.assertEqual(len(result.documents[0].segments), 2)
        self.assertEqual(result.segment_text(result.documents[0].segments[0]["id"]), long_paragraph)

    def test_lone_cr_terminates_a_line(self):
        result = self.corpus([("doc-a", 1, b"one\r\rtwo\r")]).ingest()
        self.assertEqual([result.segment_text(s["id"]) for s in result.documents[0].segments], ["one", "two"])

    def test_unicode_separators_do_not_end_a_line(self):
        text = "left" + chr(0x2028) + "right\n"
        result = self.corpus([("doc-a", 1, text.encode("utf-8"))]).ingest()
        self.assertEqual(result.segment_text(result.documents[0].segments[0]["id"]), "left" + chr(0x2028) + "right")

    def test_segments_do_not_overlap_and_gaps_are_blank(self):
        result = self.corpus([("doc-a", 1, f"A\n\n {IDEOGRAPHIC_SPACE}\nB\r\n\r\nC".encode("utf-8"))]).ingest()
        doc = result.documents[0]
        cursor = 0
        for seg in doc.segments:
            loc = seg["locator"]
            self.assertGreaterEqual(loc["char_start"], cursor)
            self.assertEqual(doc.text[cursor:loc["char_start"]].strip(), "")
            cursor = loc["char_end_exclusive"]
        self.assertEqual(doc.text[cursor:].strip(), "")

    def test_no_retrieval_size_is_part_of_the_contract(self):
        source = Path(adapter.__file__).read_text(encoding="utf-8")
        self.assertNotIn("1200", source)
        self.assertNotIn("paragraph_pack_v1", source)


class TestFailClosed(AdapterTestCase):
    def test_09_bad_utf8_is_rejected(self):
        self.assertRejected("INVALID_UTF8", self.corpus([("doc-a", 1, b"ok \xff\xfe bad")]).ingest)

    def test_10_sha_mismatch_is_rejected(self):
        corpus = self.corpus([("doc-a", 1, b"text\n")])
        corpus.manifest["documents"][0]["expected_sha256"] = "0" * 64
        self.assertRejected("SHA256_MISMATCH", corpus.ingest)

    def test_11_duplicate_document_id_is_rejected(self):
        corpus = self.corpus([("doc-a", 1, b"x\n"), ("doc-a", 2, b"y\n")])
        self.assertRejected("DUPLICATE_DOCUMENT_ID", corpus.ingest)

    def test_12_duplicate_order_is_rejected(self):
        corpus = self.corpus([("doc-a", 1, b"x\n"), ("doc-b", 1, b"y\n")])
        self.assertRejected("DUPLICATE_DOCUMENT_ORDER", corpus.ingest)

    def test_missing_file_is_rejected(self):
        corpus = self.corpus([("doc-a", 1, b"x\n")])
        (corpus.root / corpus.manifest["documents"][0]["path"]).unlink()
        self.assertRejected("SOURCE_NOT_FOUND", corpus.ingest)

    def test_invalid_manifests_are_rejected(self):
        base = self.corpus([("doc-a", 1, b"x\n")])
        mutations = {
            "wrong contract": lambda m: m.update(contract_version="LIGHT_NOVEL_INGESTION/v9"),
            "missing stream": lambda m: m.pop("stream_id"),
            "bad id": lambda m: m.update(story_id="has space"),
            "unknown field": lambda m: m.update(chapter_count=1),
            "no documents": lambda m: m.update(documents=[]),
            "negative order": lambda m: m["documents"][0].update(order=-1),
            "bad hash format": lambda m: m["documents"][0].update(expected_sha256="ABC"),
        }
        for name, mutate in mutations.items():
            manifest = copy.deepcopy(base.manifest)
            mutate(manifest)
            with self.subTest(name):
                self.assertRejected("INVALID_MANIFEST", adapter.ingest, manifest, base.root)

    def test_unsafe_paths_are_rejected(self):
        base = self.corpus([("doc-a", 1, b"x\n")])
        for path in ("../outside.txt", "/abs/file.txt", "C:/abs/file.txt", "a\\b.txt"):
            manifest = copy.deepcopy(base.manifest)
            manifest["documents"][0]["path"] = path
            with self.subTest(path):
                self.assertRejected("INVALID_SOURCE_PATH", adapter.ingest, manifest, base.root)

    def test_id_collisions_are_rejected(self):
        self.assertRejected("ID_COLLISION", self.corpus([("story-syn-01", 1, b"x\n")]).ingest)
        self.assertRejected("ID_COLLISION", self.corpus([("doc-a", 1, b"x\n")], stream_id="story-syn-01").ingest)

    def test_document_without_text_is_rejected(self):
        self.assertRejected("EMPTY_DOCUMENT", self.corpus([("doc-a", 1, b"\n \n\t\n")]).ingest)
        self.assertRejected("EMPTY_DOCUMENT", self.corpus([("doc-a", 1, b"")]).ingest)

    def test_source_is_never_repaired(self):
        # A byte-order mark is source content: it is kept, reported, and not stripped.
        data = b"\xef\xbb\xbfText.\n"
        result = self.corpus([("doc-a", 1, data)]).ingest()
        self.assertEqual(result.documents[0].text.encode("utf-8"), data)
        self.assertTrue(result.ingestion_report()["documents"][0]["begins_with_bom_character"])
        self.assertFalse(result.ingestion_report()["text_normalization_applied"])


class TestIdentity(AdapterTestCase):
    def test_document_version_is_the_source_sha256(self):
        result = self.corpus(TWO_DOCS).ingest()
        for doc, (_, _, data) in zip(result.documents, TWO_DOCS):
            self.assertEqual(doc.version, sha(data))
            self.assertEqual(len(doc.version), 64)

    def test_13_changed_bytes_change_version_and_fingerprint(self):
        before = self.corpus(TWO_DOCS).ingest()
        changed = [TWO_DOCS[0], ("doc-b", 2, TWO_DOCS[1][2].replace(b"Fourth", b"FOURTH"))]
        after = self.corpus(changed).ingest()
        self.assertEqual(before.documents[0].version, after.documents[0].version)
        self.assertNotEqual(before.documents[1].version, after.documents[1].version)
        self.assertNotEqual(before.fingerprint, after.fingerprint)
        # Same logical document identity, new version.
        self.assertEqual(before.documents[1].document_id, after.documents[1].document_id)

    def test_14_changed_document_order_changes_fingerprint(self):
        before = self.corpus(TWO_DOCS).ingest()
        swapped = self.corpus([("doc-a", 2, TWO_DOCS[0][2]), ("doc-b", 1, TWO_DOCS[1][2])]).ingest()
        self.assertNotEqual(before.fingerprint, swapped.fingerprint)

    def test_changed_document_identity_changes_fingerprint(self):
        before = self.corpus(TWO_DOCS).ingest()
        renamed = self.corpus([("doc-x", 1, TWO_DOCS[0][2]), TWO_DOCS[1]]).ingest()
        other_story = self.corpus(TWO_DOCS, story_id="story-syn-02").ingest()
        other_stream = self.corpus(TWO_DOCS, stream_id="stream-syn-02").ingest()
        fingerprints = {before.fingerprint, renamed.fingerprint, other_story.fingerprint, other_stream.fingerprint}
        self.assertEqual(len(fingerprints), 4)

    def test_15_relocation_does_not_change_fingerprint_or_canonical_output(self):
        here = self.corpus(TWO_DOCS, subdir="location_one")
        there = self.corpus(TWO_DOCS, subdir="somewhere/else/entirely")
        a, b = here.ingest(), there.ingest()
        self.assertNotEqual(here.root, there.root)
        self.assertEqual(a.fingerprint, b.fingerprint)
        self.assertEqual(adapter.canonical_json_bytes(a.canonical_skeleton()),
                         adapter.canonical_json_bytes(b.canonical_skeleton()))

    def test_fingerprint_serialization_is_documented_form(self):
        result = self.corpus(TWO_DOCS).ingest()
        payload = {"contract_version": "LIGHT_NOVEL_INGESTION/v0", "story_id": "story-syn-01",
                   "stream_id": "stream-syn-01",
                   "documents": [{"order": 1, "document_id": "doc-a", "version": sha(TWO_DOCS[0][2])},
                                 {"order": 2, "document_id": "doc-b", "version": sha(TWO_DOCS[1][2])}]}
        expected = sha(b"LIGHT_NOVEL_CORPUS_FINGERPRINT_V0\n"
                       + json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii"))
        self.assertEqual(result.fingerprint, expected)

    def test_16_repeated_runs_are_byte_identical(self):
        corpus = self.corpus(TWO_DOCS)
        first, second = corpus.ingest(), corpus.ingest()
        self.assertEqual(adapter.canonical_json_bytes(first.canonical_skeleton()),
                         adapter.canonical_json_bytes(second.canonical_skeleton()))
        self.assertEqual(adapter.canonical_json_bytes(first.ingestion_report()),
                         adapter.canonical_json_bytes(second.ingestion_report()))

    def test_manifest_listing_order_does_not_matter(self):
        forward = self.corpus(TWO_DOCS).ingest()
        backward = self.corpus(list(reversed(TWO_DOCS))).ingest()
        self.assertEqual(forward.fingerprint, backward.fingerprint)
        self.assertEqual([s["id"] for d in forward.documents for s in d.segments],
                         [s["id"] for d in backward.documents for s in d.segments])

    def test_segment_ids_are_opaque_stable_and_unique(self):
        result = self.corpus(TWO_DOCS).ingest()
        ids = [s["id"] for d in result.documents for s in d.segments]
        self.assertEqual(len(ids), len(set(ids)))
        for value in ids:
            self.assertRegex(value, r"^seg-[0-9a-f]{40}$")
            self.assertRegex(value, adapter.ID_PATTERN.pattern)
            self.assertNotIn("unit_", value)
        self.assertEqual(ids, [s["id"] for d in self.corpus(TWO_DOCS).ingest().documents for s in d.segments])

    def test_identical_text_in_two_places_gets_distinct_ids(self):
        result = self.corpus([("doc-a", 1, b"Same.\n\nSame.\n"), ("doc-b", 2, b"Same.\n")]).ingest()
        ids = [s["id"] for d in result.documents for s in d.segments]
        self.assertEqual(len(set(ids)), 3)

    def test_reingestion_after_change_invalidates_segment_ids_of_that_document(self):
        before = self.corpus(TWO_DOCS).ingest()
        changed = [TWO_DOCS[0], ("doc-b", 2, TWO_DOCS[1][2] + b"\nAppended paragraph.\n")]
        after = self.corpus(changed).ingest()
        self.assertEqual([s["id"] for s in before.documents[0].segments],
                         [s["id"] for s in after.documents[0].segments])
        self.assertFalse({s["id"] for s in before.documents[1].segments}
                         & {s["id"] for s in after.documents[1].segments})


class TestLocatorsAndPositions(AdapterTestCase):
    def test_17_exact_character_round_trip(self):
        text = f"{HIRAGANA}\r\n{EMOJI} tail\r\n\r\n{ACCENTED}\n"
        result = self.corpus([("doc-a", 1, text.encode("utf-8"))]).ingest()
        self.assertRoundTrip(result)
        first = result.documents[0].segments[0]["locator"]
        self.assertEqual(text[first["char_start"]:first["char_end_exclusive"]], f"{HIRAGANA}\r\n{EMOJI} tail")

    def test_18_exact_byte_round_trip(self):
        text = f"{IDEOGRAPHIC_SPACE}{HIRAGANA}{EMOJI}\n\n{ACCENTED}{HIRAGANA}"
        data = text.encode("utf-8")
        result = self.corpus([("doc-a", 1, data)]).ingest()
        for seg in result.documents[0].segments:
            loc = seg["locator"]
            self.assertEqual(data[loc["byte_start"]:loc["byte_end_exclusive"]],
                             text[loc["char_start"]:loc["char_end_exclusive"]].encode("utf-8"))
        last = result.documents[0].segments[-1]["locator"]
        self.assertEqual(last["byte_end_exclusive"], len(data))
        self.assertEqual(last["char_end_exclusive"], len(text))

    def test_locator_shape(self):
        result = self.corpus(TWO_DOCS).ingest()
        locator = result.documents[0].segments[0]["locator"]
        self.assertEqual(locator["kind"], "TEXT_RANGE_V0")
        self.assertEqual(set(locator), {"kind", "source_sha256", "char_start", "char_end_exclusive", "byte_start",
                                        "byte_end_exclusive", "segment_text_sha256", "document_order",
                                        "paragraph_ordinal"})
        # No filesystem path and no source text in canonical records.
        skeleton_text = json.dumps(result.canonical_skeleton())
        self.assertNotIn("unit_", skeleton_text)
        self.assertNotIn("paragraph.", skeleton_text)

    def test_discourse_positions_follow_reading_order(self):
        result = self.corpus([("doc-b", 7, b"x\n\ny\n"), ("doc-a", 3, b"p\n\nq\n\nr\n")]).ingest()
        segments = [s for d in result.documents for s in d.segments]
        keys = [s["position"]["key"] for s in segments]
        self.assertEqual(keys, [[3, 1], [3, 2], [3, 3], [7, 1], [7, 2]])
        self.assertEqual(keys, sorted(keys))
        self.assertEqual({s["position"]["stream_id"] for s in segments}, {"stream-syn-01"})


class TestPassageRefs(AdapterTestCase):
    def setUp(self):
        text = f"{HIRAGANA} first {EMOJI} sentence. Second sentence.\n\nOther paragraph.\n"
        self.result = self.corpus([("doc-a", 4, text.encode("utf-8"))]).ingest()
        self.segment = self.result.documents[0].segments[0]
        self.text = self.result.segment_text(self.segment["id"])

    def test_whole_segment_reference(self):
        ref = self.result.passage_ref(self.segment["id"])
        self.assertEqual(ref["kind"], "SOURCE_PASSAGE_REF_V0")
        self.assertEqual(self.result.resolve_passage_text(ref), self.text)
        self.assertEqual(ref["position"], self.segment["position"])
        self.assertEqual(ref["span"]["span_text_sha256"], self.segment["locator"]["segment_text_sha256"])
        self.assertNotIn("role", ref)

    def test_sub_span_derives_global_range(self):
        start = self.text.index("Second")
        end = start + len("Second sentence.")
        ref = self.result.passage_ref(self.segment["id"], start, end)
        self.assertEqual(self.result.resolve_passage_text(ref), "Second sentence.")
        doc = self.result.documents[0]
        span = ref["span"]
        self.assertEqual(span["char_start"], self.segment["locator"]["char_start"] + start)
        self.assertEqual(doc.source_bytes[span["byte_start"]:span["byte_end_exclusive"]].decode("utf-8"),
                         "Second sentence.")
        self.assertEqual(span["span_text_sha256"], sha(b"Second sentence."))

    def test_sub_span_over_multibyte_text(self):
        ref = self.result.passage_ref(self.segment["id"], 1, self.text.index("sentence"))
        resolved = self.result.resolve_passage_text(ref)
        self.assertEqual(resolved, self.text[1:self.text.index("sentence")])
        self.assertIn(EMOJI, resolved)

    def test_19_invalid_spans_are_rejected(self):
        length = len(self.text)
        for start, end in ((-1, 3), (0, 0), (5, 5), (5, 4), (0, length + 1), (length, length + 2)):
            with self.subTest(span=(start, end)):
                self.assertRejected("INVALID_SPAN", self.result.passage_ref, self.segment["id"], start, end)
        self.assertRejected("INVALID_SPAN", self.result.passage_ref, self.segment["id"], 0.0, 3)
        self.assertRejected("UNKNOWN_SEGMENT", self.result.passage_ref, "seg-does-not-exist")

    def test_tampered_or_stale_references_are_rejected(self):
        ref = self.result.passage_ref(self.segment["id"], 0, 4)
        tampered = copy.deepcopy(ref)
        tampered["span"]["char_end_exclusive"] += 1
        self.assertRejected("INVALID_PASSAGE_REF", self.result.verify_passage_ref, tampered)
        stale = copy.deepcopy(ref)
        stale["document_version"] = "0" * 64
        self.assertRejected("STALE_PASSAGE_REF", self.result.verify_passage_ref, stale)
        changed = self.corpus([("doc-a", 4, b"Different source now.\n")]).ingest()
        self.assertRejected("UNKNOWN_SEGMENT", changed.verify_passage_ref, ref)

    def test_evidence_ref_needs_a_caller_supplied_role(self):
        ref = self.result.passage_ref(self.segment["id"], 0, 4)
        evidence = adapter.materialize_evidence_ref(ref, "IN_WORLD_REPORT", "ev-syn-001")
        self.assertEqual(evidence, {"id": "ev-syn-001", "segment_id": self.segment["id"],
                                    "position": self.segment["position"], "span": ref["span"],
                                    "role": "IN_WORLD_REPORT"})
        self.assertRejected("INVALID_EVIDENCE_ROLE", adapter.materialize_evidence_ref, ref, None, "ev-syn-002")
        self.assertRejected("INVALID_EVIDENCE_ROLE", adapter.materialize_evidence_ref, ref, "depiction", "ev-syn-002")
        self.assertRejected("INVALID_ID", adapter.materialize_evidence_ref, ref, "DEPICTION", "bad id")
        self.assertRejected("INVALID_PASSAGE_REF", adapter.materialize_evidence_ref, {}, "DEPICTION", "ev-syn-002")
        with self.assertRaises(TypeError):
            adapter.materialize_evidence_ref(ref)          # no default role exists

    def test_materialized_evidence_ref_is_canonically_valid(self):
        skeleton = self.result.canonical_skeleton()
        ref = self.result.passage_ref(self.segment["id"], 0, 4)
        skeleton["evidence_refs"].append(adapter.materialize_evidence_ref(ref, "DEPICTION", "ev-syn-001"))
        self.assertTrue(validate_document(skeleton)["pass"])


class TestCanonicalSkeleton(AdapterTestCase):
    def test_20_skeleton_validates_against_canonical_story_v0(self):
        result = self.corpus(TWO_DOCS).ingest()
        skeleton = result.canonical_skeleton()
        report = validate_document(skeleton)
        self.assertTrue(report["pass"], report)
        self.assertEqual(skeleton["schema_version"], "canonical_story/v0")
        self.assertEqual(skeleton["story"], {"id": "story-syn-01", "discourse_stream_id": "stream-syn-01"})
        self.assertEqual(len(skeleton["source_documents"]), 2)
        self.assertEqual(len(skeleton["source_segments"]), 5)
        self.assertEqual({d["media_kind"] for d in skeleton["source_documents"]}, {"LIGHT_NOVEL_TEXT"})

    def test_no_story_interpretation_is_emitted(self):
        skeleton = self.corpus(TWO_DOCS).ingest().canonical_skeleton()
        for collection in ("evidence_refs", "mentions", "entities", "events", "temporal_anchors", "propositions",
                           "extraction_provenance", "assertions"):
            self.assertEqual(skeleton[collection], [], collection)

    def test_report_contains_no_source_text(self):
        result = self.corpus(TWO_DOCS).ingest()
        report_text = json.dumps(result.ingestion_report())
        for word in ("First", "Second", "Third", "Fourth", "Fifth"):
            self.assertNotIn(word, report_text)
        report = result.ingestion_report()
        self.assertEqual((report["document_count"], report["segment_count"]), (2, 5))
        self.assertFalse(report["model_invoked"])

    def test_manifest_file_and_cli(self):
        corpus = self.corpus(TWO_DOCS)
        manifest_path = corpus.root / "manifest.yaml"
        manifest_path.write_text(yaml.safe_dump(corpus.manifest), encoding="utf-8")
        result = adapter.ingest_manifest_file(manifest_path)
        self.assertEqual(result.fingerprint, corpus.ingest().fingerprint)
        out = corpus.root / "out"
        self.assertEqual(adapter.main([str(manifest_path), "--out", str(out)]), 0)
        written = json.loads((out / "canonical_source_layer.json").read_text(encoding="utf-8"))
        self.assertEqual(written, result.canonical_skeleton())
        self.assertEqual(adapter.main([str(corpus.root / "missing.yaml")]), 1)


class TestHistoricalParagraphPackIsUntouched(unittest.TestCase):
    def test_adapter_does_not_import_or_alter_paragraph_pack(self):
        from tools.story_ingestion import paragraph_pack_v1
        self.assertFalse(hasattr(adapter, "chunk_chapter"))
        self.assertEqual(paragraph_pack_v1.ChunkInfo.__dataclass_fields__["contract_id"].default,
                         "OTONARI_LOCAL_PASSAGE_V1")
        self.assertEqual(
            hashlib.sha256((REPO / "tools/story_ingestion/paragraph_pack_v1.py").read_bytes()
                           .replace(b"\r\n", b"\n")).hexdigest(),
            "fbb68e91bc1d12aa267acb1069e3efafa08bb448510ec16c8784bf4c8349873f")


class TestTrackedSampleSmoke(unittest.TestCase):
    """Mechanical smoke test over tracked sample documents. Records no prose."""

    MANIFEST = REPO / "data/sample/otonari_no_tenshi/wn_jp/LIGHT_NOVEL_SOURCE_MANIFEST_SAMPLE_V0.yaml"

    def test_tracked_sample_ingests_and_round_trips(self):
        manifest = adapter.load_manifest(self.MANIFEST)
        for entry in manifest["documents"]:
            data = (self.MANIFEST.parent / entry["path"]).read_bytes()
            if sha(data) != entry["expected_sha256"]:
                self.skipTest("tracked sample bytes differ in this checkout (line-ending conversion)")
        result = adapter.ingest_manifest_file(self.MANIFEST)
        skeleton = result.canonical_skeleton()
        self.assertTrue(validate_document(skeleton)["pass"])
        self.assertEqual(len(result.documents), 5)
        for doc in result.documents:
            self.assertEqual(doc.text.encode("utf-8"), doc.source_bytes)
            for seg in doc.segments:
                ref = result.passage_ref(seg["id"])
                self.assertEqual(result.resolve_passage_text(ref), result.segment_text(seg["id"]))
        expected = yaml.safe_load((REPO / "benchmarks/m3_ingestion/M3_01_LIGHT_NOVEL_ADAPTER_BASELINE_RESULT.yaml")
                                  .read_text(encoding="utf-8"))["tracked_source_smoke"]
        report = result.ingestion_report()
        self.assertEqual(report["corpus_fingerprint_sha256"], expected["corpus_fingerprint_sha256"])
        self.assertEqual(report["segment_count"], expected["segment_count"])
        self.assertEqual([d["segment_count"] for d in report["documents"]],
                         [d["segment_count"] for d in expected["documents"]])


if __name__ == "__main__":
    unittest.main()
