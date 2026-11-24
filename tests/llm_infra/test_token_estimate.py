import unittest

from tools.llm_infra.token_estimate import estimate_input_tokens


class EstimateTests(unittest.TestCase):
    def test_rounds_total_utf8_bytes_up(self):
        for parts, expected in [((), 0), (("ab", "cd"), 2), (("漢字",), 2), (("Việt",), 2)]:
            with self.subTest(parts=parts):
                self.assertEqual(estimate_input_tokens(*parts), expected)
