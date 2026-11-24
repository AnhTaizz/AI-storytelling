import unittest

from tools.ops_dashboard.provider_reader import configuration_counts


class ProviderReaderTests(unittest.TestCase):
    def test_offline_counts_share_gemini_scopes_and_hide_invalid_config(self):
        settings = {"GEMINI_API_KEY_1": "synthetic-key-one", "GEMINI_API_KEY_2": "synthetic-key-two",
                    "GEMINI_PROJECT_LABEL_1": "team", "GEMINI_PROJECT_LABEL_2": "team",
                    "CLOUDFLARE_API_TOKEN": "token-without-account"}
        counts = configuration_counts(settings)
        self.assertEqual(counts["gemini"], {"keys_configured": 2, "keys_eligible": 2, "key_scopes": 1,
                                           "source": "reported", "status": "configured"})
        self.assertEqual(counts["cloudflare"], {"keys_configured": None, "keys_eligible": None, "key_scopes": None,
                                               "source": "unknown", "status": "not_configured"})
