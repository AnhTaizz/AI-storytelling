from contextlib import redirect_stdout
from datetime import date
from hashlib import sha256
from io import StringIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools.llm_infra.dev_gemini_preflight import main, preflight
from tools.llm_infra.quota_state import QuotaStateStore
from tools.story_extraction.gemini_key_pool_v1 import UNKNOWN_PROJECT_LABEL


MODEL = "gemini-3.5-flash-lite"


class DevGeminiPreflightTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.request_lock = self.root / "requests.lock.json"
        self.dotenv = self.root / ".env"
        self.attestation = self.root / ".local" / "gemini-dev-owner-attestation.json"
        self.attestation.parent.mkdir()
        self.payload = self.root / "requests" / "S01.json"
        self.payload.parent.mkdir()
        self.request = {"contents": [], "systemInstruction": {},
                        "generationConfig": {"candidateCount": 1, "maxOutputTokens": 16}}
        self.lock = {"model": MODEL, "max_dispatches": 1, "max_output_tokens": 16,
                     "retry": 0, "repair": 0, "fallback": 0, "cases": []}
        self.write_request()
        self.entry = {"scope": "ai-storytelling:gemini-dev", "source": "owner_project_review",
                      "confirmed_on": "2025-06-01", "pool_revision": "1", "credential_access": "active",
                      "free_tier": "active", "operator_eligibility": "active"}
        self.write_attestation()
        self.write_config()

    def write_request(self):
        data = json.dumps(self.request).encode()
        self.payload.write_bytes(data)
        self.lock["cases"] = [{"id": "S01", "request": "requests/S01.json", "request_bytes": len(data),
                               "request_sha256": sha256(data).hexdigest()}]

    def write_config(self, extra=""):
        self.dotenv.write_text("GEMINI_API_KEY_1=fake-slot-first\nGEMINI_API_KEY_2=fake-slot-first\n"
                               "GEMINI_API_KEY_3=fake-slot-second\n" + extra, encoding="utf-8")

    def write_attestation(self, **changes):
        self.attestation.write_text(json.dumps(self.entry | changes), encoding="utf-8")

    def lock_hash(self):
        raw = json.dumps(self.lock).encode()
        self.request_lock.write_bytes(raw)
        return sha256(raw).hexdigest()

    def report(self, environ=None, **overrides):
        expected = {"expected_hash": self.lock_hash(), "model": MODEL, "dispatch_budget": 1, "output_cap": 16}
        return preflight(self.request_lock, **(expected | overrides), dotenv=self.dotenv,
                         attestation=self.attestation, environ=environ or {}, today=date(2026, 11, 27),
                         clock=lambda: 100)

    def test_cli_redacts_settings_and_reports_offline_only(self):
        argv = [str(self.request_lock), "--requests-sha256", self.lock_hash(), "--model", MODEL,
                "--dispatch-budget", "1", "--output-cap", "16", "--dotenv", str(self.dotenv)]
        with patch.dict(os.environ, clear=True), redirect_stdout(StringIO()) as output:
            self.assertEqual(main(argv), 0)
        self.assertEqual(json.loads(output.getvalue()), {
            "status": "PASSED_OFFLINE", "verified_payloads": 1, "selected_slot": "gemini_slot_1",
            "provider_status": "NOT_CONTACTED", "environment_status": "NOT_VERIFIED", "dispatches": 0,
        })
        self.attestation.unlink()
        with patch.dict(os.environ, clear=True), redirect_stdout(StringIO()) as output:
            self.assertEqual(main(argv), 2)
        self.assertEqual(json.loads(output.getvalue())["reason"], "MISSING")

    def test_binds_model_budget_and_locked_payload(self):
        for changes in ({"expected_hash": "bad"}, {"model": "different"}, {"dispatch_budget": 0},
                        {"output_cap": 17}):
            with self.subTest(changes=changes):
                self.assertEqual(self.report(**changes)["status"], "BLOCKED_PLAN")
        for key in ("retry", "repair", "fallback"):
            with self.subTest(key=key):
                self.lock[key] = 1
                self.assertEqual(self.report()["status"], "BLOCKED_PLAN")
                self.lock[key] = 0
        self.payload.write_bytes(b"changed")
        self.assertEqual(self.report()["status"], "BLOCKED_PLAN")
        self.request["generationConfig"]["candidateCount"] = 2
        self.write_request()
        self.assertEqual(self.report()["status"], "BLOCKED_PLAN")
        self.lock["cases"][0]["request"] = "../gold.json"
        self.assertEqual(self.report()["status"], "BLOCKED_PLAN")

    def test_attestation_reuses_valid_record_and_blocks_changes(self):
        cases = [({"credential_access": "revoked"}, "credential_access"), ({"free_tier": "unverified"}, "free_tier"),
                 ({"operator_eligibility": "unverified"}, "operator_eligibility"), ({"scope": "other"}, "INVALID"),
                 ({"confirmed_on": "2027-01-01"}, "INVALID"), ({"pool_revision": "2"}, "POOL_CHANGED")]
        for changes, reason in cases:
            with self.subTest(changes=changes):
                self.write_attestation(**changes)
                report = self.report()
                self.assertEqual((report["status"], report["reason"]), ("BLOCKED_OWNER_ATTESTATION", reason))
        self.write_attestation()
        self.assertEqual(self.report()["status"], "PASSED_OFFLINE")
        self.assertEqual(self.report({"GEMINI_API_KEY_1": "replacement"})["reason"], "POOL_CHANGED")
        self.assertEqual(self.report({"GOOGLE_GENAI_USE_VERTEXAI": "true"})["reason"], "ENDPOINT_OVERRIDE")

    def test_honors_billing_and_free_model_exclusions(self):
        self.write_config("GEMINI_PROJECT_BILLING_2=BILLING_ENABLED\n")
        self.assertEqual(self.report()["selected_slot"], "gemini_slot_3")
        for extra in ("GEMINI_KEYS_FREE_TIER_CONFIRMED=false\n", "LLM_ALLOW_PAID=true\n",
                      "GEMINI_FREE_MODELS=gemini-3.6-flash\n"):
            with self.subTest(extra=extra):
                self.write_config(extra)
                self.assertEqual(self.report()["status"], "BLOCKED_CREDENTIAL_OR_CONFIG")
        self.dotenv.unlink()
        self.assertEqual(self.report()["reason"], "NO_ELIGIBLE_KEY")

    def test_known_quota_block_does_not_switch_slots(self):
        store = QuotaStateStore(self.root / ".local" / "llm_quota_state.sqlite3", clock=lambda: 100)
        store.block("gemini", MODEL, f"{UNKNOWN_PROJECT_LABEL}:gemini_slot_1", 200, "UNKNOWN_429", 100)
        report = self.report()
        self.assertEqual(report["status"], "BLOCKED_LOCAL_QUOTA")
        self.assertNotIn("selected_slot", report)

    def test_duplicate_with_conflicting_project_billing_excludes_the_billed_project(self):
        declarations = (
            "GEMINI_PROJECT_LABEL_1=declared-free\n"
            "GEMINI_PROJECT_BILLING_1=FREE_TIER_CONFIRMED\n"
            "GEMINI_PROJECT_LABEL_2=billed-project\n"
            "GEMINI_PROJECT_BILLING_2=BILLING_ENABLED\n"
            "GEMINI_PROJECT_LABEL_3=billed-project\n"
        )
        for backup in (False, True):
            with self.subTest(backup=backup):
                self.write_config(declarations + ("GEMINI_API_KEY_4=fake-slot-safe\n" if backup else ""))
                report = self.report()
                if backup:
                    self.assertEqual(report["selected_slot"], "gemini_slot_4")
                else:
                    self.assertEqual(report["status"], "BLOCKED_CREDENTIAL_OR_CONFIG")
                    self.assertEqual(report["reason"], "NO_ELIGIBLE_KEY")
