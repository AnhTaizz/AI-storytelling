import unittest

from tools.ops_dashboard.privacy import label, scrub


class PrivacyTests(unittest.TestCase):
    def test_scrubs_values_dynamic_keys_and_encoded_paths(self):
        for text in ("AIza-abc", "gsk_abc", "sk-or-abc", "Bearer abc", "Authorization",
                     "0123456789abcdef" * 2, "C:\\Users\\me", "/Users/me", "/etc/test",
                     "C%3A%5CUsers%5Cme", "prefix:/.local/test", "//server/share", "myTokenWithoutPrefix"):
            with self.subTest(text=text):
                self.assertEqual(scrub({"wrapped": [text, {text: 5}]}, ("myTokenWithoutPrefix",)),
                                 {"wrapped": [None, {}]})

    def test_identifiers_and_documentation_retain_their_public_shape(self):
        for value in ("script:run-a:attempt1", "@cf/openai/gpt-oss-20b", "f" * 64, "run-a"):
            with self.subTest(value=value):
                self.assertEqual(label(value), value)
        self.assertIsNone(label("parent/child", basename=True))
        self.assertEqual(scrub("https://console.groq.com/docs/models"), "https://console.groq.com/docs/models")
