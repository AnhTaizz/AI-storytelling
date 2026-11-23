from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from tools.llm_infra.routing_policy import DEFAULT_POLICY, load_policy


class PolicyTests(unittest.TestCase):
    def test_raw_hash_and_stage_settings(self):
        policy = load_policy(DEFAULT_POLICY)
        self.assertEqual(policy.sha256, sha256(DEFAULT_POLICY.read_bytes()).hexdigest())
        self.assertEqual(policy.tier_for("patch").candidates, ("gemini:*",))
        self.assertEqual(policy.tier_for("clip").max_output_tokens, 4096)
        self.assertFalse(policy.tier_for("plan").cross_provider_fallback)

    def test_rejects_bad_policy_without_echoing_input(self):
        base = DEFAULT_POLICY.read_text(encoding="utf-8")
        variants = ["[", base.replace("version: 1", "version: 2"), base.replace("groq:*", "other:model"),
                    base.replace("default: utility", "default: typo"), base.replace("4096", "-1")]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.yaml"
            for index, variant in enumerate(variants):
                with self.subTest(variant=index):
                    path.write_text(variant, encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "(?i)routing policy"):
                        load_policy(path)
            path.unlink()
            with self.assertRaisesRegex(ValueError, "Cannot read routing policy"):
                load_policy(path)
