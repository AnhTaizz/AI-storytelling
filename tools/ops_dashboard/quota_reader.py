"""Read active cooldowns and UTC-day Neuron estimates without the writers."""

from datetime import datetime, timezone

from tools.llm_infra.quota_policy import REASONS
from tools.llm_infra.routing_policy import PROVIDERS

from .data_source import SCOPES, utc_stamp
from .privacy import label, number
from .sqlite_reader import SourceUnavailable, read_database


def read_quota(path, now):
    with read_database(path) as db:
        db.execute("BEGIN")
        tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_schema WHERE type='table' AND name IN ('quota', 'estimated_neurons')")}
        version = db.execute("PRAGMA user_version").fetchone()[0]
        # The Neuron writer can create the file before the quota writer sets v1.
        if version != 1 and not (version == 0 and tables == {"estimated_neurons"}):
            raise SourceUnavailable("schema_mismatch")
        blocks = []
        scopes = {}
        if "quota" in tables:
            for provider, model, alias, reason, until in db.execute(
                    "SELECT provider, model, project_alias, reason, blocked_until FROM quota "
                    "WHERE blocked_until > ? ORDER BY provider, project_alias, model LIMIT 500",
                    (now.timestamp(),)):
                if provider not in PROVIDERS or reason not in REASONS or number(until) is None:
                    continue
                try:
                    stamp = utc_stamp(datetime.fromtimestamp(until, timezone.utc))
                except (ValueError, OverflowError, OSError):
                    continue
                # Scope aliases can be account IDs. Use per-provider opaque ordinals.
                provider_scopes = scopes.setdefault(provider, {})
                scope = provider_scopes.setdefault(alias, len(provider_scopes) + 1)
                blocks.append({"provider": provider, "model": label(model), "scope": SCOPES[provider],
                               "scope_ref": f"{SCOPES[provider]}-{scope}", "reason": reason, "until_utc": stamp})
        neurons = None
        if "estimated_neurons" in tables:
            neurons = db.execute(
                "SELECT SUM(neurons) FROM estimated_neurons WHERE provider=? AND day=?",
                ("cloudflare", now.date().isoformat()),
            ).fetchone()[0]
        return blocks, number(neurons)
