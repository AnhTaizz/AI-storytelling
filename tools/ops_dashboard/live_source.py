"""Connect dashboard views to local read-only data sources."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import cached_property
import os
from pathlib import Path
import sqlite3

from tools.llm_infra.gemini_config import DEFAULT_STATE
from tools.llm_infra.routing_policy import DEFAULT_POLICY, load_policy
from tools.llm_infra.telemetry import DEFAULT_TELEMETRY

from .contract import FIELDS, LIVE_WINDOW_DAYS
from .data_source import utc_stamp
from .privacy import configured_secrets, label, scrub
from .provider_reader import configuration_counts, provider_summaries
from .quota_reader import read_quota
from .run_reader import read_runs
from .sqlite_reader import SourceUnavailable
from .telemetry_reader import AGGREGATE_LIMIT, read_history, read_requests


_LOCAL = DEFAULT_TELEMETRY.parent
MESSAGES = {
    "telemetry_missing": "Chưa có dữ liệu telemetry — chạy pipeline một lần "
                         "(`python -m tools.story_pipeline.run_pipeline --chapters 1`) rồi quay lại.",
    "telemetry_empty": "Chưa có yêu cầu trong khoảng này — chạy pipeline rồi quay lại.",
    "telemetry_capped": "Chỉ tính các yêu cầu mới nhất trong giới hạn đọc của bảng điều khiển.",
    "quota_missing": "Chưa có dữ liệu quota — chạy pipeline một lần rồi quay lại.",
    "pipeline_empty": "Chưa có lượt chạy — chạy pipeline hoặc kiểm tra --runs-dir và --seasons-dir.",
    "policy_unavailable": "Chưa đọc được quy tắc chọn model — kiểm tra tệp cấu hình hoặc --policy.",
    "schema_mismatch": "Dữ liệu SQLite có schema không khớp — chọn tệp do Phase 5 tạo.",
    "wal_snapshot_required": "Cơ sở dữ liệu dùng WAL — chọn bản sao SQLite dùng rollback journal.",
    "sqlite_unavailable": "Chưa đọc được SQLite — kiểm tra quyền đọc hoặc thử lại sau.",
}


@dataclass(frozen=True)
class LivePaths:
    telemetry: Path = DEFAULT_TELEMETRY
    quota_state: Path = DEFAULT_STATE
    runs_dir: Path = _LOCAL / "story_pipeline_runs"
    seasons_dir: Path = _LOCAL / "story_seasons"
    policy: Path = DEFAULT_POLICY

    @classmethod
    def from_environment(cls, overrides, environ=None):
        env = os.environ if environ is None else environ
        defaults = cls()
        env_names = {"telemetry": "LLM_TELEMETRY_PATH", "quota_state": "LLM_QUOTA_STATE_PATH"}
        return cls(**{
            name: Path(overrides.get(name) or (env.get(env_names[name]) if name in env_names else None) or value)
            for name, value in vars(defaults).items()
        })

    def describe(self, secrets=()):
        for name, path in vars(self).items():
            try:
                found = path.is_dir() if name.endswith("_dir") else path.is_file()
            except OSError:
                found = False
            public_name = scrub(path.name, secrets) if path.name.isprintable() else None
            public_name = public_name or "—"
            yield f"{name} · {public_name} · {'đã tìm thấy' if found else 'chưa tìm thấy'}"


def _now():
    return datetime.now(timezone.utc)


class LiveDataSource:
    data_mode = "live"
    estimated_cost_usd = None

    def __init__(self, paths, clock=_now, *, environ=None):
        self.paths = paths
        self.clock = clock
        settings = dict(os.environ if environ is None else environ)
        self.secrets = configured_secrets(settings)
        self.config = configuration_counts(settings)

    @property
    def now(self):
        return self.clock().astimezone(timezone.utc)

    def for_request(self):
        return _LiveSnapshot(self.paths, self.now, self.config, self.secrets)

    @property
    def requests(self):
        return self.for_request().requests

    @property
    def providers(self):
        return self.for_request().providers

    @property
    def routing_policy(self):
        return self.for_request().routing_policy

    @property
    def runs(self):
        return self.for_request().runs


class _LiveSnapshot:
    data_mode = LiveDataSource.data_mode
    estimated_cost_usd = None

    def __init__(self, paths, now, config, secrets):
        self.paths, self.now, self.config, self.secrets = paths, now, config, secrets
        self.states = {}
        self.latest = None

    def _timestamp(self, stamp):
        if stamp is not None:
            self.latest = max(self.latest or stamp, stamp)

    def _mtime(self, path):
        try:
            self._timestamp(utc_stamp(datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)))
        except OSError:
            pass

    def _sqlite(self, name, fallback, read, *args, **kwargs):
        try:
            return read(getattr(self.paths, name), *args, **kwargs)
        except FileNotFoundError:
            self.states[name] = "quota_missing" if name == "quota_state" else "telemetry_missing"
        except SourceUnavailable as error:
            self.states[name] = str(error)
        except (OSError, sqlite3.Error):
            self.states[name] = "sqlite_unavailable"
        return fallback

    def window(self, start, *, limit=AGGREGATE_LIMIT, offset=0, filters=None):
        rows, count = self._sqlite("telemetry", ([], 0), read_requests,
                                   start, self.now, limit=limit, offset=offset, filters=filters, secrets=self.secrets)
        if rows:
            self._timestamp(rows[0][FIELDS["timestamp"]])
        return rows, count

    @cached_property
    def requests(self):
        return self.window(self.now - timedelta(days=LIVE_WINDOW_DAYS))[0]

    def history(self, limit, offset, filters):
        rows, count, stages = self._sqlite("telemetry", ([], 0, []), read_history,
                                           self.now - timedelta(days=LIVE_WINDOW_DAYS), self.now,
                                           limit=limit, offset=offset, filters=filters, secrets=self.secrets)
        self.telemetry_state(len(stages))
        if rows:
            self._timestamp(rows[0][FIELDS["timestamp"]])
        return rows, count, stages

    def telemetry_state(self, count, *, capped=False):
        if "telemetry" not in self.states:
            if not count:
                self.states["telemetry"] = "telemetry_empty"
            elif capped and count > AGGREGATE_LIMIT:
                self.states["telemetry"] = "telemetry_capped"

    @cached_property
    def providers(self):
        blocks, neurons = self._sqlite("quota_state", ([], None), read_quota, self.now)
        if "quota_state" not in self.states:
            self._mtime(self.paths.quota_state)
        return list(provider_summaries(self.config, self.requests, blocks, neurons))

    @cached_property
    def routing_policy(self):
        try:
            policy = load_policy(self.paths.policy)
        except (ValueError, RecursionError):
            self.states["policy"] = "policy_unavailable"
            return {"version": None, "sha256": None, "stages": {}, "tiers": {}}
        self._mtime(self.paths.policy)
        tiers = {
            name: {"candidates": [item for item in tier.candidates
                                  if label(item) or item in ("gemini:*", "groq:*", "openrouter:*", "cloudflare:*")],
                   "cross_provider_fallback": tier.cross_provider_fallback,
                   "max_output_tokens": tier.max_output_tokens, "source": "reported"}
            for name, tier in policy.tiers.items() if label(name)
        }
        return {"version": 1, "sha256": policy.sha256, "tiers": tiers, "sources": {"version": "reported"},
                "stages": {stage: tier for stage, tier in policy.stages.items() if label(stage) and tier in tiers}}

    @cached_property
    def runs(self):
        runs = read_runs(self.paths.runs_dir, self.paths.seasons_dir)
        if not runs:
            self.states["pipeline"] = "pipeline_empty"
        for run in runs:
            self._timestamp(run.get("updated_at"))
        return runs

    def metadata(self):
        return {"last_data_at": self.latest, "source_states": {
            name: {"code": state, "message": MESSAGES[state]} for name, state in self.states.items()
        }}
