"""Resolve the versioned registry against read-only provider snapshots."""
from pathlib import Path

from jsonschema import Draft202012Validator
import yaml

from tools.llm_infra import cloudflare_free_models_v1 as cloudflare
from tools.llm_infra import gemini_free_models_v1 as gemini
from tools.llm_infra import groq_free_models_v1 as groq
from tools.llm_infra import openrouter_free_models_v1 as openrouter
from tools.llm_infra.model_capabilities_v1 import model_capability

REGISTRY_PATH = Path(__file__).with_name("model_registry_v1.yaml")
PROVIDERS = ("gemini", "groq", "openrouter", "cloudflare")
FREE_LISTS = dict(zip(PROVIDERS, (gemini.FREE_TIER_TEXT_MODELS, groq.FREE_TIER_TEXT_MODELS,
                                tuple(model for model in openrouter.DEFAULT_MODEL_CHAIN if model.endswith(":free")),
                                cloudflare.NEURON_PRICES)))
UNAVAILABLE_OPENROUTER_MODELS = {"openai/gpt-oss-20b:free": "not in catalog 2026-11-24"}
QUOTA_SCOPES = dict(zip(PROVIDERS, ("project_model", "organization_model", "account", "account_neurons")))
LIMITS = ("rpm", "tpm", "rpd", "tpd", "neurons_per_day", "free_requests_per_day")
_STATUS = {"enum": ["verified", "estimated", "unknown"]}
_COUNT = {"type": ["integer", "null"], "minimum": 1}
_BOOL = {"type": ["boolean", "null"]}
_KEYS = {"provider": {"enum": list(PROVIDERS)},
         "model_id": {"type": "string", "pattern": r"^[A-Za-z0-9@._:/-]{1,128}$"}}


def _object(properties, optional=()):
    return {"type": "object", "properties": properties, "additionalProperties": False,
            "required": [name for name in properties if name not in optional]}


_FIELDS = _KEYS | {
    "context_tokens": _COUNT, "max_output_tokens": _COUNT,
    "limits": _object(dict.fromkeys(LIMITS, _COUNT)),
    "quota_scope": {"enum": list(QUOTA_SCOPES.values())},
    "json_mode": {"enum": ["native", "prompt", "none"]},
    "structured_output": _BOOL, "reasoning": _BOOL, "free_tier_eligible": _BOOL,
    "source_url": {"type": "string", "format": "uri"},
    "verified_on": {"type": "string", "format": "date"},
}
_CATALOG_FIELDS = {
    **{key: _FIELDS[key] for key in ("context_tokens", "json_mode", "structured_output", "reasoning",
                                     "source_url", "verified_on")},
    "pricing": _object(dict.fromkeys(("prompt", "completion"), {"const": 0})),
    "note": {"type": "string"},
}
_FILE_SCHEMA = _object({
    "version": {"const": 1},
    "models": {"type": "array", "minItems": 1, "uniqueItems": True,
               "items": _object(_KEYS | {"benchmark_results": {"type": "string"},
                                         "catalog": _object(_CATALOG_FIELDS)}, ("benchmark_results", "catalog"))},
    "documented_limits": _object({
        "openrouter": _object({"rpm": _COUNT, "free_requests_per_day": _COUNT}),
        "cloudflare": _object({"rpm": _COUNT}),
    }),
})
_OPTIONAL_FIELDS = ("pricing", "note", "benchmark_results")
REGISTRY_SCHEMA = _object(_FIELDS | {
    "status": _object(dict.fromkeys((*[key for key in _FIELDS if key != "limits"],
                                    *[f"limits.{key}" for key in LIMITS], *_OPTIONAL_FIELDS), _STATUS),
                      _OPTIONAL_FIELDS),
    "benchmark_results": {"type": "string"},
    **{key: _CATALOG_FIELDS[key] for key in ("pricing", "note")},
}, _OPTIONAL_FIELDS)


def _resolve(identity, documented):
    provider, model = identity["provider"], identity["model_id"]
    cap = model_capability(provider, model)
    limits = dict.fromkeys(LIMITS) | documented.get(provider, {})
    if provider == "groq":
        limits["tpm"] = groq.FREE_PLAN_TPM
    if provider == "cloudflare":
        limits["neurons_per_day"] = cloudflare.DAILY_FREE_NEURONS
    # The Cloudflare snapshot derives its reasoning flag from a name substring.
    reasoning = None if provider == "cloudflare" else cap.reasoning
    entry = identity | {
        "context_tokens": cap.context_tokens, "max_output_tokens": None, "limits": limits,
        "quota_scope": QUOTA_SCOPES[provider], "json_mode": cap.json_mode,
        # Native JSON does not establish provider-enforced JSON Schema.
        "structured_output": None, "reasoning": reasoning, "free_tier_eligible": True,
        "source_url": cap.source, "verified_on": cap.verified_on,
    }
    entry.update(entry.pop("catalog", {}))
    values = {key: value for key, value in entry.items() if key != "limits"}
    values.update({f"limits.{key}": value for key, value in limits.items()})
    estimates = {f"limits.{key}" for key in documented.get(provider, {})}
    entry["status"] = {key: ("unknown" if value is None else "estimated" if key in estimates else "verified")
                       for key, value in values.items()}
    Draft202012Validator(REGISTRY_SCHEMA, format_checker=Draft202012Validator.FORMAT_CHECKER).validate(entry)
    return entry


def _snapshot(path):
    source = yaml.safe_load(path.read_text(encoding="utf-8"))
    Draft202012Validator(_FILE_SCHEMA).validate(source)
    rows = {(row["provider"], row["model_id"]): row for row in source["models"]}
    expected = {(provider, model) for provider, models in FREE_LISTS.items() for model in models}
    catalog = {key for key, row in rows.items() if "catalog" in row
               and key[0] == "openrouter" and key[1].endswith(":free")
               and openrouter.is_free_model(key[1]) and key[1] not in UNAVAILABLE_OPENROUTER_MODELS}
    if rows.keys() != expected | catalog or len(rows) != len(source["models"]):
        raise ValueError("Model registry identities drifted from the provider free lists")
    return rows, source["documented_limits"]


def load_registry(path=REGISTRY_PATH):
    rows, documented = _snapshot(path)
    return {key: _resolve(row, documented) for key, row in rows.items()}


def select_model(provider, model, path=REGISTRY_PATH):
    if provider == "openrouter" and model in UNAVAILABLE_OPENROUTER_MODELS:
        raise ValueError(f"{model} is unavailable ({UNAVAILABLE_OPENROUTER_MODELS[model]})")
    rows, documented = _snapshot(path)
    if (provider, model) in rows:
        return _resolve(rows[provider, model], documented)
    # OpenRouter maintains an eligibility rule rather than a finite variant catalog.
    if (provider == "openrouter" and len(model) <= 128
            and model.endswith(":free") and openrouter.is_free_model(model) and "/" in model):
        return _resolve({"provider": provider, "model_id": model}, documented)
    raise ValueError("Select a model from the free registry or a named OpenRouter :free variant")
