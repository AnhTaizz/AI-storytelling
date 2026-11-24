import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from jsonschema import Draft202012Validator, ValidationError
import yaml

from tools.model_bench.registry import (FREE_LISTS, REGISTRY_PATH, REGISTRY_SCHEMA,
                                        load_registry, select_model)


class RegistryTests(unittest.TestCase):
    def test_snapshot_matches_code_and_preserves_unknowns(self):
        registry = load_registry()
        self.assertEqual(set(registry), {(p, m) for p, models in FREE_LISTS.items() for m in models})
        Draft202012Validator.check_schema(REGISTRY_SCHEMA)
        for key, entry in registry.items():
            with self.subTest(key=key):
                Draft202012Validator(REGISTRY_SCHEMA).validate(entry)
                for field, status in entry["status"].items():
                    value = entry["limits"][field.split(".")[1]] if field.startswith("limits.") else entry[field]
                    self.assertEqual(value is None, status == "unknown")
                for field in ("context_tokens", "max_output_tokens", "structured_output"):
                    self.assertIsNone(entry[field])
        self.assertIsNone(registry["cloudflare", "@cf/qwen/qwen3-30b-a3b-fp8"]["reasoning"])
        self.assertIsNone(registry["cloudflare", "@cf/openai/gpt-oss-120b"]["reasoning"])
        self.assertIsNone(registry["gemini", "gemini-3.8-flash"]["limits"]["tpm"])
        self.assertEqual(registry["groq", "openai/gpt-oss-20b"]["limits"]["tpm"], 8000)

    def test_registry_refuses_drift_and_malformed_values(self):
        for kind, error in (("missing model", ValueError), ("invalid count", ValidationError)):
            with self.subTest(kind=kind), TemporaryDirectory() as temp:
                source = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
                if kind == "missing model":
                    source["models"].pop()
                else:
                    source["documented_limits"]["openrouter"]["rpm"] = 0
                path = Path(temp) / "registry.yaml"
                path.write_text(yaml.safe_dump(source), encoding="utf-8")
                with self.assertRaises(error):
                    load_registry(path)

    def test_openrouter_named_variant_and_invalid_models(self):
        entry = select_model("openrouter", "demo/model:free")
        self.assertEqual(entry["model_id"], "demo/model:free")
        self.assertIsNone(entry["reasoning"])
        for provider, model in (("openrouter", "demo/model"), ("openrouter", "a:free,b:free"),
                                ("gemini", "gemini-unknown")):
            with self.subTest(provider=provider, model=model), self.assertRaises(ValueError):
                select_model(provider, model)
