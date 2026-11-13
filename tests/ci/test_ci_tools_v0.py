"""Tests for the quality-gate tooling in tools/ci (runner, test policy, repository guards).

Fixtures are synthetic. Credential-looking strings are assembled at runtime so this file
does not trip the secret scan it tests.
"""
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.ci import check, guards, run_tests, test_policy  # noqa: E402
from tools.ci.config import Gate, gate_index, is_git_ignored, load_gates, suites  # noqa: E402


def write_test_file(directory: Path, name: str, source: str) -> Path:
    path = directory / name
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    return path


LONG_BODY = """
        data = {"alpha": 1, "beta": 2, "gamma": 3, "delta": 4}
        total = sum(value for value in data.values())
        self.assertEqual(total, 10)
        self.assertIn("alpha", data)
        self.assertEqual(sorted(data), ["alpha", "beta", "delta", "gamma"])
"""


class TestPolicyTests(unittest.TestCase):
    def test_shadowed_test_name_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_test_file(Path(tmp), "test_x.py", """
                import unittest
                class T(unittest.TestCase):
                    def test_a(self):
                        self.assertTrue(True)
                    def test_a(self):
                        self.assertFalse(False)
            """)
            tests, findings = test_policy.collect_tests([("demo", path)])
        self.assertEqual([f.code for f in findings], ["SHADOWED_TEST"])
        self.assertIn("demo/test_x.T.test_a", findings[0].message)
        self.assertEqual(len(tests), 2)

    def test_duplicate_bodies_grouped_and_trivial_ignored(self):
        source = "import unittest\nclass T(unittest.TestCase):\n"
        for name in ("test_one", "test_two"):
            source += f"    def {name}(self):\n        '''doc differs: {name}'''" + LONG_BODY
        source += "    def test_small_a(self):\n        self.assertTrue(1)\n"
        source += "    def test_small_b(self):\n        self.assertTrue(1)\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test_y.py"
            path.write_text(source, encoding="utf-8")
            tests, _ = test_policy.collect_tests([("demo", path)])
        groups = test_policy.duplicate_body_groups(tests)
        self.assertEqual(len(groups), 1)
        self.assertEqual(sorted(t.name for t in groups[0]), ["test_one", "test_two"])

    def test_repository_policy_passes(self):
        findings = test_policy.run_policy()
        self.assertEqual(findings, [], "\n".join(f"{f.code}: {f.message}" for f in findings))

    def test_catalog_lists_this_file(self):
        catalog = (REPO / "tests" / "TEST_CATALOG.md").read_text(encoding="utf-8")
        self.assertIn("### test_ci_tools_v0", catalog)
        self.assertIn("`tools.ci.test_policy`", catalog)


class GateTests(unittest.TestCase):
    def test_declared_gates_follow_policy(self):
        gates = load_gates()
        self.assertTrue(gates)
        index = gate_index(gates)
        self.assertIn("story_benchmark/test_dense_e5_small_v1", index)
        for gate in gates:
            for path in gate.requires_paths:
                self.assertTrue(is_git_ignored(path), path)

    def test_unmet_requirements_reported(self):
        gate = Gate(("s/t",), ("module_that_does_not_exist_xyz",), ("no/such/path",), "why")
        self.assertEqual(gate.unmet(), ["module module_that_does_not_exist_xyz", "path no/such/path"])
        self.assertEqual(Gate(("s/t",), ("json",), (), "why").unmet(), [])

    def test_gated_placeholder_skips_or_fails(self):
        result = unittest.TestResult()
        run_tests._Gated("s/t", "missing thing", fail=False).run(result)
        self.assertEqual(len(result.skipped), 1)
        self.assertTrue(result.skipped[0][1].startswith("GATED:"))
        strict = unittest.TestResult()
        run_tests._Gated("s/t", "missing thing", fail=True).run(strict)
        self.assertEqual(len(strict.failures), 1)


class RunnerTests(unittest.TestCase):
    def test_suites_discovered(self):
        self.assertIn("story_pipeline", suites())
        self.assertIn("ci", suites())

    def test_runs_one_suite_in_subprocess(self):
        lines = []
        report = run_tests.run_all(["story_pipeline"], echo=lines.append)
        self.assertTrue(report["ok"])
        self.assertGreater(report["suites"][0]["ran"], 0)
        self.assertIn("story_pipeline", lines[0])

    def test_check_command_parses_options(self):
        # Running the whole gate here would recurse into this suite; only the CLI is exercised.
        with self.assertRaises(SystemExit) as ctx:
            check.main(["--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_unknown_suite_rejected(self):
        with self.assertRaises(SystemExit):
            run_tests.run_all(["no_such_suite"], echo=lambda _: None)


class GuardTests(unittest.TestCase):
    PATTERNS = ["schemas/canonical_story/*", "benchmarks/*"]

    def test_protected_modification_needs_decision(self):
        changes = [("M", "schemas/canonical_story/canonical_story_v0.schema.json"), ("A", "benchmarks/new.yaml")]
        findings = guards.check_protected(changes, self.PATTERNS)
        self.assertEqual([f.code for f in findings], ["PROTECTED_PATH"])
        self.assertEqual(guards.check_protected(changes + [("M", guards.DECISIONS)], self.PATTERNS), [])

    def test_additions_and_unprotected_changes_allowed(self):
        changes = [("A", "benchmarks/m9/result.yaml"), ("M", "tools/story_pipeline/stages.py"),
                   ("D", "tools/story_pipeline/old.py")]
        self.assertEqual(guards.check_protected(changes, self.PATTERNS), [])
        self.assertEqual([f.code for f in guards.check_protected([("D", "benchmarks/m1/x.yaml"), ("R", "benchmarks/m2/y")],
                                                                  self.PATTERNS)], ["PROTECTED_PATH"] * 2)

    def test_private_paths(self):
        paths = [".env", ".env.example", "config/.env.local", ".local/run/x.json",
                 "data/sample/otonari_no_tenshi/wn_jp/raw/chapter_005.txt",
                 "data/sample/otonari_no_tenshi/wn_jp/raw/chapter_006.txt"]
        flagged = sorted(f.message.split(" ")[0] for f in guards.check_private_paths(paths))
        self.assertEqual(flagged, [".env", ".local/run/x.json", "config/.env.local",
                                   "data/sample/otonari_no_tenshi/wn_jp/raw/chapter_006.txt"])

    def test_secret_scan(self):
        fake_google = "AI" + "za" + "B" * 35
        fake_private = "-----BEGIN RSA " + "PRIVATE KEY-----"
        scratch = REPO / ".local" / "ci_test_scratch"
        scratch.mkdir(parents=True, exist_ok=True)
        try:
            (scratch / "a.txt").write_text(f"ok line\nkey = {fake_google}\n", encoding="utf-8")
            (scratch / "b.txt").write_text(fake_private, encoding="utf-8")
            (scratch / "c.txt").write_text("nothing to see", encoding="utf-8")
            rel = [str((scratch / n).relative_to(REPO)) for n in ("a.txt", "b.txt", "c.txt")]
            findings = guards.check_secrets(rel)
        finally:
            for item in scratch.iterdir():
                item.unlink()
            scratch.rmdir()
        self.assertEqual(len(findings), 2)
        self.assertIn("a.txt:2", findings[0].message)

    def test_repository_has_no_secrets_or_private_files(self):
        tracked = guards.tracked_files()
        self.assertEqual(guards.check_private_paths(tracked) + guards.check_secrets(tracked), [])

    def test_ranges(self):
        self.assertEqual(guards._ranges([1, 2, 3, 7, 9, 10]), "1-3,7,9-10")

    def test_protected_pattern_file_covers_frozen_layers(self):
        patterns = guards.read_patterns()
        for path in ("schemas/canonical_story/canonical_story_v0.schema.json",
                     "tools/story_ingestion/light_novel_adapter_v0.py",
                     "docs/contracts/SCRIPT_QUALITY_CONTRACT_V0.md",
                     "benchmarks/m4_extraction/anything.yaml",
                     "tests/environment_gates.yaml"):
            self.assertTrue(guards.is_protected(path, patterns), path)
        self.assertFalse(guards.is_protected("tools/story_pipeline/stages.py", patterns))


if __name__ == "__main__":
    unittest.main()
