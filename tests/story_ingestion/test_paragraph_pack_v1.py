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
    execute_corpus,
    sha256_bytes
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

if __name__ == "__main__":
    unittest.main()
