"""Read and fingerprint owner-editable routing preferences."""
from dataclasses import dataclass
import hashlib
from pathlib import Path

from jsonschema import Draft202012Validator
import yaml


PROVIDERS = ("gemini", "groq", "openrouter", "cloudflare")
DEFAULT_POLICY = Path(__file__).resolve().parents[2] / "configs" / "llm_routing" / "policy_v1.yaml"
DEFAULT_OUTPUT_TOKENS = 4096

_TIER = {
    "type": "object",
    "required": ["candidates", "cross_provider_fallback", "max_output_tokens"],
    "additionalProperties": False,
    "properties": {
        "candidates": {
            "type": "array", "minItems": 1, "uniqueItems": True,
            "items": {"type": "string", "pattern": r"^(gemini|groq|openrouter|cloudflare):(?:\*|[A-Za-z0-9@._:/-]+)$"},
        },
        "cross_provider_fallback": {"type": "boolean"},
        "max_output_tokens": {"type": "integer", "minimum": 1},
    },
}
_SCHEMA = {
    "type": "object",
    "required": ["version", "stages", "tiers"],
    "additionalProperties": False,
    "properties": {
        "version": {"type": "integer", "const": 1},
        "stages": {"type": "object", "required": ["default"], "additionalProperties": {"type": "string"}},
        "tiers": {"type": "object", "minProperties": 1, "additionalProperties": _TIER},
    },
}


@dataclass(frozen=True)
class Tier:
    candidates: tuple[str, ...]
    cross_provider_fallback: bool
    max_output_tokens: int

    def selectors(self):
        primary = self.candidates[0].split(":", 1)[0]
        for candidate in self.candidates:
            provider, model = candidate.split(":", 1)
            if self.cross_provider_fallback or provider == primary:
                yield provider, model


@dataclass(frozen=True)
class RoutingPolicy:
    stages: dict[str, str]
    tiers: dict[str, Tier]
    sha256: str | None = None

    def tier_for(self, stage):
        return self.tiers[self.stages.get(stage, self.stages["default"])]

    @classmethod
    def single_provider(cls, provider):
        # The only fallback candidates here are models of the same provider.
        return cls({"default": "single"}, {"single": Tier((f"{provider}:*",), True, DEFAULT_OUTPUT_TOKENS)})


def load_policy(path):
    try:
        content = Path(path).read_bytes()
        data = yaml.safe_load(content)
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ValueError(f"Cannot read routing policy ({type(error).__name__})") from None
    if not Draft202012Validator(_SCHEMA).is_valid(data):
        raise ValueError("Invalid routing policy v1 schema")
    if any(tier not in data["tiers"] for tier in data["stages"].values()):
        raise ValueError("Routing policy stage refers to an unknown tier")
    tiers = {name: Tier(tuple(tier["candidates"]), tier["cross_provider_fallback"], tier["max_output_tokens"])
             for name, tier in data["tiers"].items()}
    return RoutingPolicy(data["stages"], tiers, hashlib.sha256(content).hexdigest())
