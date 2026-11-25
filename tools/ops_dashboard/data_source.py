"""Read-only data interface and a synthetic snapshot of operations."""

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from random import Random
from typing import Protocol

from .contract import FIELDS, PIPELINE_STAGES


class DataSource(Protocol):
    @property
    def now(self) -> datetime: ...
    @property
    def data_mode(self) -> str: ...
    @property
    def estimated_cost_usd(self) -> float | None: ...
    @property
    def requests(self) -> Sequence[Mapping]: ...
    @property
    def providers(self) -> Sequence[Mapping]: ...
    @property
    def routing_policy(self) -> Mapping: ...
    @property
    def runs(self) -> Sequence[Mapping]: ...


# Model chains and quotas from the repository's reviewed Free routing snapshots.
# Keep these fixture values independent of the provider clients at runtime.
MODELS = {
    "gemini": ("gemini-3.8-flash", "gemini-3.6-flash"),
    "groq": ("openai/gpt-oss-120b", "openai/gpt-oss-20b"),
    "openrouter": ("openrouter/free",),
    "cloudflare": ("@cf/openai/gpt-oss-120b", "@cf/zai-org/glm-4.7-flash"),
}
SCOPES = dict(zip(MODELS, ("project", "org", "account", "account")))
PROVIDER_NAMES = dict(zip(MODELS, ("Gemini", "Groq", "OpenRouter", "Cloudflare")))
INCIDENTS = (
    ("gemini", "script", "FAILED", "QUOTA_EXHAUSTED"),
    ("groq", "utility", "SKIPPED", "REQUEST_TOO_LARGE"),
    ("openrouter", "utility", "FAILED", "EDGE_BLOCKED"),
)


def utc_stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def _policy():
    stages = dict.fromkeys(
        ("brief", "brief_check", "plan", "script", "critic", "source_check", "revise", "patch"),
        "quality_critical",
    )
    stages["default"] = "utility"
    tiers = {
        "quality_critical": {
            "candidates": ["gemini:*"], "cross_provider_fallback": False, "max_output_tokens": 8192,
        },
        "utility": {
            "candidates": ["groq:*", "cloudflare:*", "openrouter:*", "gemini:*"],
            "cross_provider_fallback": True, "max_output_tokens": 4096,
        },
    }
    policy = {"version": 1, "stages": stages, "tiers": tiers}
    digest = sha256(json.dumps(policy, sort_keys=True).encode("utf-8")).hexdigest()
    return {**policy, "sha256": digest}


def _row(rng, row_id, timestamp, policy_hash, provider, stage, outcome="SUCCESS", error=None):
    model = rng.choice(MODELS[provider])
    successful = outcome == "SUCCESS"
    source = rng.choice(("reported", "reported", "estimated")) if successful else "unknown"
    if outcome == "SKIPPED":
        source = "estimated"
    input_tokens = rng.randint(180, 1800) if source != "unknown" else None
    if error == "REQUEST_TOO_LARGE":
        input_tokens = 4600
    output_tokens = None
    if source == "estimated":
        output_tokens = 8192 if stage in PIPELINE_STAGES else 4096
    elif source == "reported":
        output_tokens = rng.randint(80, 650)
    reported_cost = 0.0 if successful and provider == "openrouter" and source == "reported" else None
    fields = {
        "id": row_id,
        "timestamp": utc_stamp(timestamp),
        "run": f"mock-run-{(row_id - 1) // 8 + 1:03}",
        "stage": stage,
        "request": f"{stage}:mock-{row_id:04}",
        "provider": provider,
        "model": model,
        "responseModel": model if successful and provider != "openrouter" else None,
        "outcome": outcome,
        "error": error,
        "input": input_tokens,
        "output": output_tokens,
        "reasoning": None,
        "tokenSource": source,
        "latency": rng.randint(350, 5200) if outcome != "SKIPPED" else None,
        "quotaScope": SCOPES[provider] if successful else None,
        "quotaRemaining": "{}",
        "reportedCost": reported_cost,
        "estimatedCost": None,
        "costSource": "reported" if reported_cost is not None else "unknown",
        "policyHash": policy_hash,
        "skipReasons": json.dumps([f"{provider}:{error}"] if outcome == "SKIPPED" else []),
    }
    return {FIELDS[key]: value for key, value in fields.items()}


def _quota(label, unit, limit=None, used=None, source="unknown"):
    return {"label": label, "unit": unit, "limit": limit, "used": used, "source": source,
            "remaining": limit - used if limit is not None and used is not None else None}


class MockDataSource:
    data_mode = "mock"
    estimated_cost_usd = 0.0

    def __init__(self, seed=42, now=None):
        if now is None:
            now = datetime.now(timezone.utc)
        if now.utcoffset() is None:
            raise ValueError("now must include a timezone")
        self.now = now.astimezone(timezone.utc)
        self.routing_policy = _policy()
        rng = Random(seed)
        digest = self.routing_policy["sha256"]
        rows = []
        for hour in reversed(range(7 * 24)):
            for _ in range(rng.randint(0, 4)):
                provider = rng.choice(tuple(MODELS))
                stage = rng.choice((*PIPELINE_STAGES, "utility")) if provider == "gemini" else "utility"
                timestamp = self.now - timedelta(hours=hour, seconds=rng.randint(1500, 3599))
                rows.append(_row(rng, len(rows) + 1, timestamp, digest, provider, stage))
        for offset, provider in enumerate(MODELS):
            rows.append(_row(rng, len(rows) + 1, self.now - timedelta(minutes=24 - offset),
                             digest, provider, "brief" if provider == "gemini" else "utility"))
        for offset, incident in enumerate(INCIDENTS):
            timestamp = self.now - timedelta(minutes=3 + offset * 4)
            row = _row(rng, len(rows) + 1, timestamp, digest, *incident)
            if offset == 0:
                row[FIELDS["run"]] = "mock-run-paused"
            rows.append(row)
        self.requests = tuple(sorted(rows, key=lambda row: row[FIELDS["timestamp"]], reverse=True))

        cooldown = utc_stamp(self.now + timedelta(minutes=42))
        limits = {
            "gemini": [_quota("Per project and model", "requests")],
            "groq": [_quota("Requests per day", "requests", 1000, 132, "estimated"),
                     _quota("Tokens per minute", "tokens", 8000, 1640, "reported")],
            "openrouter": [_quota("Free requests per UTC day", "requests", 50, 31, "reported")],
            "cloudflare": [_quota("Neurons per UTC day", "Neurons", 10000, 6140, "estimated")],
        }
        errors = {provider: error for provider, _, _, error in INCIDENTS}
        self.providers = tuple({
            "slug": provider,
            "name": PROVIDER_NAMES[provider],
            "status": "Cooldown" if provider == "gemini" else "Degraded" if provider == "openrouter" else "Healthy",
            "scope": SCOPES[provider],
            "models": MODELS[provider],
            "limits": limits[provider],
            "last_error": errors.get(provider),
            "cooldown_until": cooldown if provider == "gemini" else None,
        } for provider in MODELS)
        self.runs = (
            {"id": "mock-run-paused", "status": "PAUSED_QUOTA", "completed": ("brief", "plan"),
             "current": "script", "resume_at": cooldown,
             "hint": "After the cooldown, resume in the same output directory to reuse completed stages."},
            {"id": "mock-run-review", "status": "NEEDS_REVIEW", "completed": ("brief", "plan", "script", "critic"),
             "current": "revise", "resume_at": None, "hint": "Review the flagged revision before continuing."},
            {"id": "mock-run-complete", "status": "COMPLETED", "completed": PIPELINE_STAGES,
             "current": None, "resume_at": None, "hint": "All five stages finished."},
            {"id": "mock-run-failed", "status": "FAILED", "completed": ("brief",),
             "current": "plan", "resume_at": None, "hint": "Inspect the plan failure in the run manifest."},
        )
