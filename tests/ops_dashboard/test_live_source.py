from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch

from tools.llm_infra.neuron_ledger import NeuronLedger
from tools.llm_infra.quota_state import QuotaStateStore
from tools.llm_infra.telemetry import Telemetry
from tools.ops_dashboard.live_source import LiveDataSource, LivePaths
from tools.ops_dashboard.server import make_server


NOW = datetime(2026, 11, 24, 10, tzinfo=timezone.utc)
ENDPOINTS = ("overview", "providers", "usage?range=24h", "usage?range=7d", "requests",
             "routing-policy", "pipeline")
SECRETS = ("AIza_example", "gsk_example", "sk-or-example", "Bearer_example",
           "0123456789abcdef0123456789abcdef", "privateToken123",
           "Authorization", "C:\\Users\\private", "/Users/private", "/var/private")


class LiveSourceTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.paths = LivePaths(root / "telemetry #.db", root / "quota.db", root / "runs",
                               root / "seasons", root / "policy.yaml")
        self.now = NOW
        settings = {"GROQ_API_KEY_1": SECRETS[1], "CLOUDFLARE_ACCOUNT_ID": SECRETS[4],
                    "CLOUDFLARE_API_TOKEN": SECRETS[5], "CLOUDFLARE_PLAN_STATUS": "WORKERS_FREE_CONFIRMED",
                    "GEMINI_API_KEY_1": SECRETS[0], "GEMINI_PROJECT_LABEL_1": "project-one"}
        self.source = LiveDataSource(self.paths, lambda: self.now, environ=settings)
        self.server = make_server(port=0, source=self.source)
        thread = Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)

    def get(self, endpoint, status=200):
        conn = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            conn.request("GET", "/api/" + endpoint)
            with conn.getresponse() as response:
                self.assertEqual(response.status, status)
                self.assertEqual(response.headers["Content-Security-Policy"], "default-src 'self'")
                raw = response.read().decode("utf-8")
        finally:
            conn.close()
        for secret in SECRETS:
            self.assertNotIn(secret, raw)
            self.assertNotIn(json.dumps(secret)[1:-1], raw)
        self.assertNotIn("private", raw)
        data = json.loads(raw)
        self.assertEqual(data["data_mode"], "live")
        return data

    def write_telemetry(self, rows, timestamp=None):
        with patch("tools.llm_infra.telemetry.datetime") as clock:
            clock.now.return_value = timestamp or (NOW - timedelta(minutes=10))
            writer = Telemetry(self.paths.telemetry)
            for row in rows:
                writer.write(**row)

    def write_json(self, file, payload):
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(payload), encoding="utf-8")
        os.utime(file, (NOW.timestamp(), NOW.timestamp()))

    def fixture(self):
        self.write_telemetry([
            dict(run_id="run-a", request_id="script:run-a:attempt1", stage="script", provider="groq",
                 model_requested="openai/gpt-oss-20b", outcome="SUCCESS", tokens_source="reported",
                 input_tokens=10, output_tokens=5, reasoning_tokens=3, latency_ms=100, cost_reported=0.01,
                 cost_source="reported", quota_scope="org",
                 quota_remaining={"x-ratelimit-remaining-requests": "12", "Authorization": SECRETS[5]}),
            dict(run_id=SECRETS[0], request_id=SECRETS[1], stage="script", provider="gemini",
                 model_requested=SECRETS[2], model_reported=SECRETS[4], error_code="REQUEST_TOO_LARGE",
                 outcome="SKIPPED", tokens_source="estimated", input_tokens=30, output_tokens=60,
                 skip_reasons=["gemini:REQUEST_TOO_LARGE", SECRETS[5], SECRETS[8], SECRETS[9]]),
            dict(run_id="run-a", request_id=SECRETS[3], stage="script", provider="groq",
                 error_code="QUOTA_EXHAUSTED", outcome="FAILED", tokens_source="unknown", latency_ms=900),
        ])
        self.write_telemetry([dict(stage="brief", provider="gemini", outcome="SUCCESS")], NOW - timedelta(days=2))
        self.write_telemetry([dict(stage="old", provider="gemini", outcome="SUCCESS")], NOW - timedelta(days=8))
        now = NOW.timestamp()
        store = QuotaStateStore(self.paths.quota_state, clock=lambda: now)
        store.block("groq", "openai/gpt-oss-20b", SECRETS[4], now + 300, "TPM", now)
        store.block("groq", "openai/gpt-oss-120b", SECRETS[4], now + 600, "RPM", now)
        store.block("gemini", "gemini-3.8-flash", "expired", now - 10, "RPD", now)
        ledger = NeuronLedger(self.paths.quota_state)
        ledger.add("cloudflare", SECRETS[4], "2026-11-24", 72, now)
        ledger.add("cloudflare", "second", "2026-11-24", 5, now)
        ledger.add("cloudflare", SECRETS[4], "2026-11-23", 200, now)
        self.paths.policy.write_text(
            "version: 1\nstages: {default: utility}\ntiers:\n"
            "  utility: {candidates: ['groq:*'], cross_provider_fallback: true, max_output_tokens: 4096}\n",
            encoding="utf-8",
        )
        manifest = {"run_id": SECRETS[3], "status": "FAILED", "model_calls": 1, "seconds": 5,
                    "usage": {"total": {"total": 15}}, "started_utc": NOW.isoformat(),
                    "error": f"GroqTransportError: QUOTA_EXHAUSTED {SECRETS[5]}",
                    "profile": {"script": "private script"}, "path": SECRETS[7]}
        self.write_json(self.paths.runs_dir / "run-a" / "run_manifest.json", manifest)
        call_file = self.paths.runs_dir / "run-a" / "calls.jsonl"
        call_file.write_text(json.dumps({"provider": "groq", "model": "openai/gpt-oss-20b", "stage": "brief",
                                         "seconds": 1.5, "valid": True, "raw_content": "private response"}) + "\n",
                             encoding="utf-8")
        season = self.paths.seasons_dir / "season-a"
        self.write_json(season / "season.json", {
            "status": "COMPLETED", "totals": {"calls": 1, "seconds": 5, "tokens": 15},
            "episodes": [{"dir": "ep01_ch1"}, {"dir": SECRETS[8]}],
        })
        self.write_json(season / "ep01_ch1" / "run_manifest.json", {**manifest, "status": "STOPPED_AFTER_BRIEF",
                                                                     "error": None})
        locked = self.paths.seasons_dir / "hidden-id"
        self.write_json(locked / "gate_lock.json", {"account": SECRETS[4]})
        self.write_json(locked / "season.json", {"status": "RUNNING", "episodes": [{"dir": "locked-ep"}]})
        self.write_json(locked / "locked-ep" / "run_manifest.json", manifest)
        self.write_json(self.paths.seasons_dir / "locked-before-first-episode" / "gate_lock.json", {})

    def test_live_endpoints_aggregate_and_scrub_real_writer_metadata(self):
        self.fixture()
        result = {}
        for endpoint in ENDPOINTS:
            with self.subTest(endpoint=endpoint):
                result[endpoint] = self.get(endpoint)
        today = result["overview"]["today"]
        self.assertEqual(today["requests"], 3)
        self.assertEqual(today["outcomes"], {"SUCCESS": 1, "FAILED": 1, "SKIPPED": 1})
        self.assertEqual(today["tokens_by_source"], {"reported": 15, "estimated": 90, "unknown": None})
        self.assertEqual(today["reasoning_by_source"]["reported"], 3)
        self.assertEqual(today["cost_by_source"], {"reported": 0.01, "estimated": None, "unknown": None})
        self.assertEqual(today["stage_provider_mix"], {"script": {"groq": 2, "gemini": 1}})
        self.assertEqual(today["error_counts"], {"QUOTA_EXHAUSTED": 1, "REQUEST_TOO_LARGE": 1})
        self.assertEqual(today["latency"], {"p50": 100, "p95": 900})
        self.assertEqual(today["skip_reason_counts"], {"gemini:REQUEST_TOO_LARGE": 1})
        self.assertEqual(result["overview"]["active_cooldowns"], 2)
        self.assertIsNotNone(result["overview"]["last_data_at"])
        providers = {provider["slug"]: provider for provider in result["providers"]["providers"]}
        self.assertEqual(providers["groq"]["quota_counters"][0]["value"], 12)
        self.assertEqual(providers["groq"]["quota_counters"][0]["source"], "reported")
        self.assertEqual({block["reason"] for block in providers["groq"]["blocks"]}, {"TPM", "RPM"})
        self.assertEqual(len({block["scope_ref"] for block in providers["groq"]["blocks"]}), 1)
        self.assertEqual(providers["gemini"]["configuration"]["keys_configured"], 1)
        self.assertEqual(providers["openrouter"]["configuration"]["status"], "not_configured")
        neurons = providers["cloudflare"]["limits"][0]
        self.assertEqual((neurons["used"], neurons["limit"], neurons["remaining"]), (77, 10000, None))
        self.assertEqual(neurons["sources"], {"used": "estimated", "limit": "static", "remaining": "unknown"})
        self.assertEqual(providers["groq"]["model_details"][0]["max_request_tokens"], 8000)
        for name, count in (("24h", 3), ("7d", 4)):
            buckets = result[f"usage?range={name}"]["buckets"]
            self.assertEqual(sum(sum(p["requests"].values()) for b in buckets for p in b["providers"].values()), count)
        history = result["requests"]
        self.assertEqual(history["matching"], 4)
        self.assertEqual({row["tokens_source"] for row in history["requests"]}, {"reported", "estimated", "unknown"})
        policy = result["routing-policy"]
        self.assertEqual(policy["sha256"], sha256(self.paths.policy.read_bytes()).hexdigest())
        self.assertEqual(policy["tiers"]["utility"]["candidates"], ["groq:*"])
        runs = result["pipeline"]["runs"]
        self.assertIn({"label": "đợt chạy đã khóa (M9)", "status": "RUNNING"}, runs)
        self.assertIn({"label": "đợt chạy đã khóa (M9)", "status": "UNKNOWN"}, runs)
        self.assertEqual({run.get("id") for run in runs}, {None, "run-a", "season-a", "ep01_ch1"})
        run = next(run for run in runs if run.get("id") == "run-a")
        self.assertEqual((run["status"], run["current"], run["tokens"]), ("PAUSED_QUOTA", "plan", 15))
        self.assertEqual(run["stages"]["brief"], {"seconds": 1.5, "status": "COMPLETED", "source": "reported"})

    def test_missing_sources_are_explained_without_creating_files(self):
        for endpoint, source, code in (
            ("overview", "telemetry", "telemetry_missing"), ("providers", "quota_state", "quota_missing"),
            ("usage", "telemetry", "telemetry_missing"), ("requests", "telemetry", "telemetry_missing"),
            ("pipeline", "pipeline", "pipeline_empty"), ("routing-policy", "policy", "policy_unavailable"),
        ):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(self.get(endpoint)["source_states"][source]["code"], code)
        self.assertFalse(any(path.exists() for path in vars(self.paths).values()))

    def test_schema_mismatch_and_refresh(self):
        self.write_telemetry([dict(stage="script", outcome="SUCCESS")])
        with closing(sqlite3.connect(self.paths.telemetry)) as db:
            db.execute("PRAGMA user_version=999")
        data = self.get("overview")
        self.assertIn("schema không khớp", data["source_states"]["telemetry"]["message"])
        self.assertEqual(data["today"]["requests"], 0)
        with closing(sqlite3.connect(self.paths.telemetry)) as db:
            db.execute("PRAGMA user_version=1")
        self.now += timedelta(seconds=30)
        updated = self.get("overview")
        self.assertEqual(updated["today"]["requests"], 1)
        self.assertGreater(updated["generated_at"], data["generated_at"])

    def test_many_reads_preserve_bytes_times_and_directory_entries(self):
        self.fixture()
        root = self.paths.telemetry.parent
        def files():
            return {path.relative_to(root): (path.read_bytes(), path.stat().st_mtime_ns)
                    for path in root.rglob("*") if path.is_file()}
        before = files()
        for _ in range(3):
            for endpoint in ENDPOINTS:
                self.get(endpoint)
        self.assertEqual(files(), before)

    def test_history_caps_and_paginates_with_same_timestamp(self):
        self.write_telemetry([dict(stage="script", outcome="SUCCESS", provider="groq")] * 502)
        first = self.get("requests?limit=500&provider=groq")
        second = self.get("requests?limit=500&offset=500&provider=groq")
        self.assertEqual((len(first["requests"]), first["next_offset"]), (500, 500))
        self.assertEqual((len(second["requests"]), second["next_offset"]), (2, None))
        self.assertFalse({row["id"] for row in first["requests"]} & {row["id"] for row in second["requests"]})
        self.get("requests?limit=501", status=400)

    def test_path_precedence(self):
        env = {"LLM_TELEMETRY_PATH": "env.db", "LLM_QUOTA_STATE_PATH": "quota-env.db"}
        paths = LivePaths.from_environment({"telemetry": "flag.db"}, env)
        self.assertEqual(paths, replace(LivePaths(), telemetry=Path("flag.db"), quota_state=Path("quota-env.db")))
