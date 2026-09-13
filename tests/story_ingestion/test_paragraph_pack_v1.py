import unittest
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tools.story_ingestion.paragraph_pack_v1 import (
    split_lines_with_offsets,
    parse_paragraphs,
    chunk_chapter,
    validate_chapter_chunks,
    validate_corpus_chunks,
    execute_corpus,
    sha256_bytes,
    ChunkInfo
)

class TestParagraphPack(unittest.TestCase):

    # T1: Simple paragraphs fit in one chunk
    def test_simple_paragraphs(self):
        text = "Paragraph 1 is here.\n\nParagraph 2 is here.\n\nParagraph 3 is here.\n"
        lines = split_lines_with_offsets(text)
        paras = parse_paragraphs(lines, text)
        chunks = chunk_chapter(paras, text, 1, "test.txt", "abc", "def")
        
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].text, text)
        self.assertEqual(chunks[0].char_count, len(text))
        self.assertEqual(chunks[0].first_paragraph_index, 1)
        self.assertEqual(chunks[0].last_paragraph_index, 3)
        self.assertIn("\n\n", chunks[0].text)

    # T2: Greedy boundary
    def test_greedy_boundary(self):
        text = "First paragraph.\n\n" + "A" * 1180 + "\n\n" + "Next paragraph.\n"
        lines = split_lines_with_offsets(text)
        paras = parse_paragraphs(lines, text)
        chunks = chunk_chapter(paras, text, 1, "test.txt", "abc", "def")
        
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].last_paragraph_index, 2)
        self.assertEqual(chunks[1].first_paragraph_index, 3)
        self.assertIn("Next paragraph.", chunks[1].text)
        
    # T3: Oversized 2401
    def test_oversized_2401(self):
        text = "B" * 2401 + "\n"
        lines = split_lines_with_offsets(text)
        paras = parse_paragraphs(lines, text)
        chunks = chunk_chapter(paras, text, 1, "test.txt", "abc", "def")
        
        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[0].char_count, 1200)
        self.assertEqual(chunks[1].char_count, 1200)
        self.assertEqual(chunks[2].char_count, 2)
        
    # T4: Oversized isolation
    def test_oversized_isolation(self):
        text = "Normal one.\n\n" + "O" * 1250 + "\n\nNormal two.\n"
        lines = split_lines_with_offsets(text)
        paras = parse_paragraphs(lines, text)
        chunks = chunk_chapter(paras, text, 1, "test.txt", "abc", "def")
        
        self.assertEqual(len(chunks), 4)
        self.assertLessEqual(chunks[0].char_count, 1200)
        self.assertIn("Normal one.", chunks[0].text)
        self.assertEqual(chunks[0].boundary_reason, "PARAGRAPH_PACK")
        
        self.assertEqual(chunks[1].char_count, 1200)
        self.assertEqual(chunks[1].boundary_reason, "OVERSIZED_PARAGRAPH_HARD_SPLIT")
        
        self.assertEqual(chunks[2].char_count, 51)
        self.assertEqual(chunks[2].boundary_reason, "OVERSIZED_PARAGRAPH_HARD_SPLIT")
        
        self.assertEqual(chunks[3].boundary_reason, "PARAGRAPH_PACK")
        self.assertIn("Normal two.", chunks[3].text)

    # T5: Edge blank regions
    def test_edge_blank_regions(self):
        text = "\n\n  \n\nContent here.\n\n  \n\n"
        lines = split_lines_with_offsets(text)
        paras = parse_paragraphs(lines, text)
        chunks = chunk_chapter(paras, text, 1, "test.txt", "abc", "def")
        
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].text, "Content here.\n")
        
        val = validate_chapter_chunks(chunks, paras, text)
        self.assertTrue(val["pass"])

    # T6: CRLF
    def test_crlf(self):
        text = "Line one.\r\n\r\nLine two.\r\n"
        lines = split_lines_with_offsets(text)
        paras = parse_paragraphs(lines, text)
        chunks = chunk_chapter(paras, text, 1, "test.txt", "abc", "def")
        
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].text, text)
        self.assertEqual(chunks[0].char_count, len(text))
        self.assertEqual(chunks[0].char_start, 0)
        self.assertEqual(chunks[0].char_end_exclusive, len(text))

    # T7: Unicode
    def test_unicode(self):
        text = "こんにちは\n\n世界\n"
        lines = split_lines_with_offsets(text)
        paras = parse_paragraphs(lines, text)
        chunks = chunk_chapter(paras, text, 1, "test.txt", "abc", "def")
        
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].char_count, 10)
        self.assertEqual(chunks[0].text, text)

    # T8: Chunk IDs
    def test_chunk_ids(self):
        text = "P1\n\nP2\n\nP3\n"
        lines = split_lines_with_offsets(text)
        paras = parse_paragraphs(lines, text)
        chunks1 = chunk_chapter(paras, text, 1, "test.txt", "abc", "def")
        chunks2 = chunk_chapter(paras, text, 2, "test.txt", "abc", "def")
        
        self.assertEqual(chunks1[0].chunk_id, "ch001_c0001")
        self.assertEqual(chunks2[0].chunk_id, "ch002_c0001")

    # T9: Hash invariant
    def test_hash_invariant(self):
        text = "Some text to hash."
        lines = split_lines_with_offsets(text)
        paras = parse_paragraphs(lines, text)
        chunks = chunk_chapter(paras, text, 1, "test.txt", "abc", "def")
        
        chunk = chunks[0]
        expected_hash = sha256_bytes(text.encode("utf-8"))
        self.assertEqual(chunk.chunk_text_sha256, expected_hash)
        self.assertEqual(chunk.text, text)

    # T10: Input identity failure
    @patch("tools.story_ingestion.paragraph_pack_v1.sha256_bytes")
    def test_input_identity_failure(self, mock_sha256):
        mock_sha256.return_value = "wrong_hash"
        result = execute_corpus()
        self.assertFalse(result)

    def test_validation_fails_on_overlap(self):
        text = "P1\n\n" + "A" * 1200 + "\n\nP2\n"
        lines = split_lines_with_offsets(text)
        paras = parse_paragraphs(lines, text)
        chunks = chunk_chapter(paras, text, 1, "test.txt", "abc", "def")
        # Force overlap
        chunks[1].char_start = chunks[0].char_end_exclusive - 1
        val = validate_chapter_chunks(chunks, paras, text)
        self.assertFalse(val["pass"])
        self.assertTrue(any("OVERLAPPING_CHUNK_SPANS" in issue for issue in val["issues"]))
        self.assertGreater(val["metrics"]["overlap_count"], 0)

    def test_validation_fails_on_hash_mismatch(self):
        text = "P1\n\nP2\n"
        lines = split_lines_with_offsets(text)
        paras = parse_paragraphs(lines, text)
        chunks = chunk_chapter(paras, text, 1, "test.txt", "abc", "def")
        # Force mismatch
        chunks[0].chunk_text_sha256 = "wrong"
        val = validate_chapter_chunks(chunks, paras, text)
        self.assertFalse(val["pass"])
        self.assertTrue(any("CHUNK_HASH_MISMATCH" in issue for issue in val["issues"]))

    def test_validation_fails_on_duplicate_coverage(self):
        text = "P1\n\n" + "A" * 1200 + "\n\nP2\n"
        lines = split_lines_with_offsets(text)
        paras = parse_paragraphs(lines, text)
        chunks = chunk_chapter(paras, text, 1, "test.txt", "abc", "def")
        # Duplicate coverage of the first char
        chunks[1].char_start = chunks[0].char_start
        chunks[1].text = text[chunks[1].char_start:chunks[1].char_end_exclusive]
        chunks[1].char_count = chunks[1].char_end_exclusive - chunks[1].char_start
        chunks[1].chunk_text_sha256 = sha256_bytes(chunks[1].text.encode("utf-8"))
        val = validate_chapter_chunks(chunks, paras, text)
        self.assertFalse(val["pass"])
        self.assertTrue(any("PARAGRAPH_CHARACTER_DUPLICATED" in issue for issue in val["issues"]))
        self.assertGreater(val["metrics"]["paragraph_character_duplicated"], 0)

    def test_validation_fails_on_illegal_gap(self):
        text = "P1\n\n" + "A" * 1200 + "\n\nP2\n"
        lines = split_lines_with_offsets(text)
        paras = parse_paragraphs(lines, text)
        chunks = chunk_chapter(paras, text, 1, "test.txt", "abc", "def")
        # Make chunk 1 skip the 'P' in P2
        chunks[1].char_start += 1
        chunks[1].text = text[chunks[1].char_start:chunks[1].char_end_exclusive]
        chunks[1].char_count = chunks[1].char_end_exclusive - chunks[1].char_start
        chunks[1].chunk_text_sha256 = sha256_bytes(chunks[1].text.encode("utf-8"))
        val = validate_chapter_chunks(chunks, paras, text)
        self.assertFalse(val["pass"])
        self.assertTrue(any("ILLEGAL_GAP" in issue for issue in val["issues"]))
        self.assertGreater(val["metrics"]["illegal_gap_count"], 0)

    def test_corpus_validator_duplicate_id(self):
        c1 = ChunkInfo(chunk_id="ch001_c0001", chapter_number=1, chunk_index=1, char_count=100, boundary_reason="PARAGRAPH_PACK", source_logical_path="p1", source_chapter_sha256="h1")
        c2 = ChunkInfo(chunk_id="ch001_c0001", chapter_number=1, chunk_index=1, char_count=100, boundary_reason="PARAGRAPH_PACK", source_logical_path="p1", source_chapter_sha256="h1")
        ch_info = [{"number": 1, "logical_path": "p1", "sha256": "h1", "text": ""}]
        val = validate_corpus_chunks([c1, c2], ch_info)
        self.assertFalse(val["pass"])
        self.assertFalse(val["metrics"]["chunk_id_unique"])
        self.assertTrue(any("DUPLICATE_CHUNK_ID" in i for i in val["issues"]))

    def test_corpus_validator_first_index_not_1(self):
        c1 = ChunkInfo(chunk_id="ch001_c0002", chapter_number=1, chunk_index=2, char_count=100, boundary_reason="PARAGRAPH_PACK", source_logical_path="p1", source_chapter_sha256="h1")
        ch_info = [{"number": 1, "logical_path": "p1", "sha256": "h1", "text": ""}]
        val = validate_corpus_chunks([c1], ch_info)
        self.assertFalse(val["pass"])
        self.assertFalse(val["metrics"]["chunk_indices_sequential"])
        self.assertTrue(any("FIRST_INDEX_NOT_1" in i for i in val["issues"]))

    def test_corpus_validator_non_sequential(self):
        c1 = ChunkInfo(chunk_id="ch001_c0001", chapter_number=1, chunk_index=1, char_count=100, boundary_reason="PARAGRAPH_PACK", source_logical_path="p1", source_chapter_sha256="h1")
        c2 = ChunkInfo(chunk_id="ch001_c0003", chapter_number=1, chunk_index=3, char_count=100, boundary_reason="PARAGRAPH_PACK", source_logical_path="p1", source_chapter_sha256="h1")
        ch_info = [{"number": 1, "logical_path": "p1", "sha256": "h1", "text": ""}]
        val = validate_corpus_chunks([c1, c2], ch_info)
        self.assertFalse(val["pass"])
        self.assertFalse(val["metrics"]["chunk_indices_sequential"])
        self.assertTrue(any("NON_SEQUENTIAL_INDEX" in i for i in val["issues"]))

    def test_corpus_validator_malformed_id(self):
        c1 = ChunkInfo(chunk_id="bad_id", chapter_number=1, chunk_index=1, char_count=100, boundary_reason="PARAGRAPH_PACK", source_logical_path="p1", source_chapter_sha256="h1")
        ch_info = [{"number": 1, "logical_path": "p1", "sha256": "h1", "text": ""}]
        val = validate_corpus_chunks([c1], ch_info)
        self.assertFalse(val["pass"])
        self.assertFalse(val["metrics"]["chunk_id_format_valid"])
        self.assertTrue(any("MALFORMED_CHUNK_ID" in i for i in val["issues"]))

    def test_corpus_validator_cross_chapter(self):
        # path mismatch
        c1 = ChunkInfo(chunk_id="ch001_c0001", chapter_number=1, chunk_index=1, char_count=100, boundary_reason="PARAGRAPH_PACK", source_logical_path="wrong", source_chapter_sha256="h1")
        ch_info = [{"number": 1, "logical_path": "p1", "sha256": "h1", "text": ""}]
        val = validate_corpus_chunks([c1], ch_info)
        self.assertFalse(val["pass"])
        self.assertFalse(val["metrics"]["no_cross_chapter_chunks"])
        self.assertTrue(any("PATH_MISMATCH" in i for i in val["issues"]))

    @patch("tools.story_ingestion.paragraph_pack_v1.validate_corpus_chunks")
    def test_aggregate_failure_returns_false(self, mock_val):
        mock_val.return_value = {
            "pass": False,
            "issues": ["FAKE_CORPUS_ISSUE"],
            "metrics": {
                "chunk_id_unique": False,
                "chunk_id_format_valid": True,
                "chunk_indices_sequential": True,
                "no_cross_chapter_chunks": True,
                "boundary_reason_enum_valid": True,
                "max_chunk_size_valid": True
            }
        }
        result = execute_corpus(".local/test_aggregate")
        self.assertFalse(result)

if __name__ == "__main__":
    unittest.main()
