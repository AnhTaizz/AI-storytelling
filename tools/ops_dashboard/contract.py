"""Phase 5 telemetry field names and vocabulary used by the dashboard."""

from types import MappingProxyType


# Source: docs/engineering/LLM_TELEMETRY_SCHEMA.md and tools/llm_infra/telemetry.py
# at Phase 5 commit 4689167. Semantic keys also let the browser look up columns.
FIELDS = MappingProxyType({
    "id": "id",
    "timestamp": "timestamp_utc",
    "run": "run_id",
    "stage": "stage",
    "request": "request_id",
    "provider": "provider",
    "model": "model_requested",
    "responseModel": "model_reported",
    "outcome": "outcome",
    "error": "error_code",
    "input": "input_tokens",
    "output": "output_tokens",
    "reasoning": "reasoning_tokens",
    "tokenSource": "tokens_source",
    "latency": "latency_ms",
    "quotaScope": "quota_scope",
    "quotaRemaining": "quota_remaining",
    "reportedCost": "cost_reported",
    "estimatedCost": "cost_estimated",
    "costSource": "cost_source",
    "policyHash": "routing_policy_sha256",
    "skipReasons": "skip_reasons",
})
TELEMETRY_COLUMNS = tuple(FIELDS.values())
VALUE_SOURCES = ("reported", "estimated", "unknown")
DISPLAY_SOURCES = (*VALUE_SOURCES, "static")
OUTCOMES = ("SUCCESS", "FAILED", "SKIPPED")
PIPELINE_STAGES = ("brief", "plan", "script", "critic", "revise")
HISTORY_LIMIT = 500
HISTORY_MAX_OFFSET = 1_000_000
LIVE_WINDOW_DAYS = 7
