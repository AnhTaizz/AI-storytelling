"""Synthetic sign-off / freeze-gate / Task Q plan tests (no fixture text)."""
import csv
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

import yaml

from test_probe_consistency import build_bundle, make_probe
from tools.story_benchmark import fixture_freeze as ff

V1_HASH = "ff8833b9071d478ac2834535a184c1465150e71e5fb1a6c69ac5d6fc4c632c12"


class FreezeCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.src_dir = self.root / "SRC_PKG"
        self.src_dir.mkdir()
        build_bundle(self.src_dir, make_probe())
        self.src_zip = self.root / "SRC_PKG.zip"
        self.pkg_sha = ff._deterministic_zip(self.src_dir, self.src_zip)

    def tearDown(self):
        self._tmp.cleanup()

    def write_signoff(self, decisions=None, package_sha=None, blank=()):
        decisions = decisions or {"V_SYNTH_01": "APPROVED", "V_SYNTH_02": "DEFERRED"}
        template = (self.src_dir / "human_signoff_template_v3.csv").read_text(encoding="utf-8")
        rows = list(csv.DictReader(io.StringIO(template)))
        for row in rows:
            row.update({
                "human_decision": decisions[row["probe_id"]],
                "human_notes": "synthetic",
                "reviewed_at": "2026-01-01T00:00:00+00:00",
                "reviewer_role": "Product Owner",
                "source_package_sha256": package_sha or self.pkg_sha,
            })
            for field in blank:
                row[field] = ""
        path = self.root / "human_signoff_v3.csv"
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        return path

    def gate(self, signoff, expected=None):
        return ff.check_freeze_eligibility(
            self.src_zip, signoff, expected or self.pkg_sha,
            technical_gate_pass=True, privacy_pass=True, task_q_executed=False,
        )

    def freeze(self, signoff):
        return ff.build_frozen_package(
            self.root / "FROZEN", self.src_zip, signoff, self.pkg_sha,
            technical_gate_pass=True, privacy_pass=True, task_q_executed=False,
            fixture_id="SYN_FROZEN", fixture_version="1",
            frozen_at="2026-01-01T00:00:00+00:00", frozen_from_git_sha="0" * 40,
        )


class TestFreezeGate(FreezeCase):
    def test_01_valid_signoff_is_eligible(self):
        self.assertEqual(self.gate(self.write_signoff())["status"], "ELIGIBLE")

    def test_02_missing_signoff_waits_for_product_owner(self):
        result = self.gate(self.root / "absent.csv")
        self.assertEqual(result["status"], "WAITING_FOR_PRODUCT_OWNER")

    def test_03_stale_package_hash_in_signoff_is_rejected(self):
        result = self.gate(self.write_signoff(package_sha="a" * 64))
        self.assertEqual(result["status"], "INCOMPLETE_HUMAN_SIGNOFF")

    def test_04_old_v1_hash_cannot_be_used(self):
        self.assertEqual(self.gate(self.write_signoff(package_sha=V1_HASH))["status"],
                         "INCOMPLETE_HUMAN_SIGNOFF")
        self.assertEqual(self.gate(self.write_signoff(), expected=V1_HASH)["status"], "BLOCKED")

    def test_05_missing_primary_decision_is_incomplete(self):
        signoff = self.write_signoff({"V_SYNTH_01": "PENDING_REVIEW", "V_SYNTH_02": "DEFERRED"})
        self.assertEqual(self.gate(signoff)["status"], "INCOMPLETE_HUMAN_SIGNOFF")

    def test_05b_blank_reviewer_metadata_is_incomplete(self):
        signoff = self.write_signoff(blank=("reviewer_role",))
        self.assertEqual(self.gate(signoff)["status"], "INCOMPLETE_HUMAN_SIGNOFF")

    def test_06_non_approved_primary_requires_post_review_fix(self):
        signoff = self.write_signoff({"V_SYNTH_01": "NEEDS_REVISION", "V_SYNTH_02": "DEFERRED"})
        result = self.gate(signoff)
        self.assertEqual(result["status"], "POST_REVIEW_FIX_REQUIRED")
        with self.assertRaises(ff.FreezeNotEligible):
            self.freeze(signoff)

    def test_07_fixture_mutation_after_signoff_blocks(self):
        signoff = self.write_signoff()
        fixture_path = self.src_dir / "canonical_primary_fixture.yaml"
        fixture = yaml.safe_load(fixture_path.read_text(encoding="utf-8"))
        fixture["probes"][0]["question"] = "Mutated after sign-off."
        fixture_path.write_text(yaml.safe_dump(fixture, allow_unicode=True, sort_keys=False), encoding="utf-8")
        self.src_zip.unlink()
        ff._deterministic_zip(self.src_dir, self.src_zip)
        self.assertEqual(self.gate(signoff)["status"], "BLOCKED")

    def test_gate_failures_block(self):
        signoff = self.write_signoff()
        for kwargs in ({"technical_gate_pass": False}, {"privacy_pass": False}, {"task_q_executed": True}):
            args = {"technical_gate_pass": True, "privacy_pass": True, "task_q_executed": False, **kwargs}
            result = ff.check_freeze_eligibility(self.src_zip, signoff, self.pkg_sha, **args)
            self.assertEqual(result["status"], "BLOCKED", kwargs)


class TestFrozenPackage(FreezeCase):
    def test_08_valid_freeze_validates(self):
        built = self.freeze(self.write_signoff())
        result = ff.validate_frozen_fixture(built["zip_path"], self.src_zip, self.pkg_sha, 1)
        self.assertTrue(result["pass"], result["issues"])
        self.assertEqual(built["record"]["task_q_executed"], False)
        self.assertEqual(built["record"]["evaluation_allowed"], True)
        self.assertEqual(built["record"]["multi_gold_count"], 1)

    def rewrite_member(self, zip_path, name, transform):
        with zipfile.ZipFile(zip_path) as zf:
            members = {n: zf.read(n) for n in zf.namelist()}
        target = next(n for n in members if n.endswith(name))
        members[target] = transform(members[target])
        with zipfile.ZipFile(zip_path, "w") as zf:
            for n, data in members.items():
                zf.writestr(n, data)

    def test_09_frozen_fixture_mutation_fails(self):
        built = self.freeze(self.write_signoff())
        self.rewrite_member(built["zip_path"], "frozen_primary_fixture.yaml",
                            lambda b: b.replace(b"Order the synthetic events.", b"Changed."))
        result = ff.validate_frozen_fixture(built["zip_path"], self.src_zip, self.pkg_sha, 1)
        self.assertFalse(result["pass"])
        self.assertTrue(any("manifest hash mismatch" in i for i in result["issues"]))
        self.assertTrue(any("differ from the approved" in i for i in result["issues"]))

    def test_09b_embedded_results_fail(self):
        built = self.freeze(self.write_signoff())

        def inject(data):
            fixture = yaml.safe_load(data.decode("utf-8"))
            fixture["probes"][0]["metrics"] = {"success@10": 1}
            return yaml.safe_dump(fixture, allow_unicode=True, sort_keys=False).encode("utf-8")

        self.rewrite_member(built["zip_path"], "frozen_primary_fixture.yaml", inject)
        result = ff.validate_frozen_fixture(built["zip_path"], self.src_zip, self.pkg_sha, 1)
        self.assertTrue(any("results embedded" in i for i in result["issues"]), result["issues"])

    def test_09c_unexpected_primary_count_fails(self):
        built = self.freeze(self.write_signoff())
        result = ff.validate_frozen_fixture(built["zip_path"], self.src_zip, self.pkg_sha, 2)
        self.assertFalse(result["pass"])

    def test_10_task_q_plan_bound_to_wrong_hash_fails(self):
        built = self.freeze(self.write_signoff())
        good = ff.build_task_q_run_plan(built["zip_sha256"], "1" * 40, "c" * 64, "d" * 64)
        self.assertTrue(ff.validate_task_q_run_plan(good, built["zip_path"])["pass"])
        wrong = dict(good, frozen_fixture_sha256="e" * 64)
        self.assertFalse(ff.validate_task_q_run_plan(wrong, built["zip_path"])["pass"])

    def test_task_q_plan_rejects_protocol_drift_and_scores(self):
        built = self.freeze(self.write_signoff())
        good = ff.build_task_q_run_plan(built["zip_sha256"], "1" * 40, "c" * 64, "d" * 64)
        self.assertFalse(ff.validate_task_q_run_plan(dict(good, candidate_depth=50), built["zip_path"])["pass"])
        self.assertFalse(ff.validate_task_q_run_plan(dict(good, bootstrap_seed=7), built["zip_path"])["pass"])
        self.assertFalse(ff.validate_task_q_run_plan(dict(good, results={"O": 0.5}), built["zip_path"])["pass"])


if __name__ == "__main__":
    unittest.main()
