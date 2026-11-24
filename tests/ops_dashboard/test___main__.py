import contextlib
import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools.ops_dashboard.__main__ import main


class CommandLineTests(unittest.TestCase):
    def test_cli_prints_bound_port_and_stops_on_interrupt(self):
        with patch("tools.ops_dashboard.__main__.make_server") as make_server:
            server = make_server.return_value.__enter__.return_value
            server.server_port = 43210
            server.serve_forever.side_effect = KeyboardInterrupt
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["--mock", "--host", "::1", "--port", "0"]), 0)
            self.assertEqual(output.getvalue().strip(), "http://[::1]:43210/")
            self.assertEqual(make_server.call_args.args, ("::1", 0))
            self.assertEqual(make_server.call_args.kwargs["source"].data_mode, "mock")
            make_server.return_value.__exit__.assert_called_once()

    def test_cli_defaults_to_live_and_reports_only_basenames(self):
        with (TemporaryDirectory() as directory, patch.dict("os.environ", {}, clear=True),
              patch("tools.ops_dashboard.__main__.make_server") as make_server):
            root = Path(directory)
            policy = root / "policy.yaml"
            policy.touch()
            output = io.StringIO()
            with (contextlib.redirect_stdout(output),
                  patch("tools.ops_dashboard.__main__.DEFAULT_DOTENV", root / ".env")):
                self.assertEqual(main(["--telemetry", str(root / "requests.db"),
                                       "--quota-state", str(root / "quota.db"),
                                       "--runs-dir", str(root), "--seasons-dir", str(root),
                                       "--policy", str(policy)]), 0)
            source = make_server.call_args.kwargs["source"]
            self.assertEqual(source.data_mode, "live")
            self.assertEqual(source.paths.policy, policy)
            lines = output.getvalue()
            self.assertIn("requests.db · chưa tìm thấy", lines)
            self.assertIn("policy.yaml · đã tìm thấy", lines)
            self.assertIn(".env · chưa tìm thấy", lines)
            self.assertNotIn(directory, lines)

    def test_cli_dotenv_and_path_precedence(self):
        with TemporaryDirectory() as directory, patch("tools.ops_dashboard.__main__.make_server") as make_server:
            root = Path(directory)
            dotenv = root / "dashboard.env"
            dotenv.write_text("GEMINI_API_KEY_1=fixtureDotenvKey\n"
                              "LLM_TELEMETRY_PATH=fixture-telemetry.db\n"
                              "LLM_QUOTA_STATE_PATH=fixture-quota.db\n", encoding="utf-8")
            for suffix, environment, flags, paths, configured in (
                ("dotenv", {}, [], ("fixture-telemetry.db", "fixture-quota.db"), 1),
                ("environment", {"LLM_TELEMETRY_PATH": "env-telemetry.db", "GEMINI_API_KEY_1": ""},
                 [], ("env-telemetry.db", "fixture-quota.db"), 0),
                ("flags", {"LLM_QUOTA_STATE_PATH": "env-quota.db"},
                 ["--telemetry", "flag-telemetry.db", "--quota-state", "flag-quota.db"],
                 ("flag-telemetry.db", "flag-quota.db"), 1),
            ):
                output = io.StringIO()
                with (self.subTest(precedence=suffix), patch.dict("os.environ", environment, clear=True),
                      contextlib.redirect_stdout(output)):
                    self.assertEqual(main(["--dotenv", str(dotenv), "--runs-dir", directory,
                                           "--seasons-dir", directory, "--policy", str(root / "policy.yaml"),
                                           *flags]), 0)
                    source = make_server.call_args.kwargs["source"]
                    self.assertEqual((source.paths.telemetry, source.paths.quota_state), tuple(map(Path, paths)))
                    self.assertEqual(source.config["gemini"]["keys_configured"], configured)
                    self.assertIn("dashboard.env · đã tìm thấy", output.getvalue())
                    for value in ("fixtureDotenvKey", "fixture-telemetry.db", "fixture-quota.db", directory):
                        self.assertNotIn(value, output.getvalue())

    def test_cli_missing_dotenv_uses_environment_without_creating_file(self):
        with (TemporaryDirectory() as directory, patch("tools.ops_dashboard.__main__.make_server") as make_server,
              patch.dict("os.environ", {"GROQ_API_KEY_1": "fixtureEnvironmentKey"}, clear=True),
              contextlib.redirect_stdout(io.StringIO()) as output):
            root = Path(directory)
            dotenv = root / "missing.env"
            self.assertEqual(main(["--dotenv", str(dotenv), "--telemetry", str(root / "requests.db"),
                                   "--quota-state", str(root / "quota.db"), "--runs-dir", directory,
                                   "--seasons-dir", directory, "--policy", str(root / "policy.yaml")]), 0)
            source = make_server.call_args.kwargs["source"]
            self.assertEqual(source.config["groq"]["status"], "configured")
            self.assertEqual(source.config["gemini"]["status"], "not_configured")
            self.assertIn("missing.env · chưa tìm thấy", output.getvalue())
            self.assertNotIn("fixtureEnvironmentKey", output.getvalue())
            self.assertFalse(dotenv.exists())

    def test_cli_startup_error_hides_settings(self):
        with (TemporaryDirectory() as directory, patch("tools.ops_dashboard.__main__.make_server") as make_server,
              patch.dict("os.environ", {}, clear=True)):
            root = Path(directory)
            dotenv = root / "dashboard.env"
            secret = "fixtureErrorKey"
            make_server.side_effect = OSError(secret)
            for contents in (f"GEMINI_API_KEY_1={secret}\n", f"{secret}\n"):
                with (self.subTest(valid="=" in contents), contextlib.redirect_stdout(io.StringIO()) as output,
                      contextlib.redirect_stderr(io.StringIO()) as errors):
                    dotenv.write_text(contents, encoding="utf-8")
                    with self.assertRaises(SystemExit) as caught:
                        main(["--dotenv", str(dotenv), "--telemetry", str(root / "requests.db"),
                              "--quota-state", str(root / "quota.db"), "--runs-dir", directory,
                              "--seasons-dir", directory, "--policy", str(root / "policy.yaml")])
                    self.assertEqual(caught.exception.code, 1)
                    self.assertIn("Could not start dashboard", errors.getvalue())
                    self.assertNotIn(secret, output.getvalue() + errors.getvalue())
                    self.assertNotIn(directory, output.getvalue() + errors.getvalue())

    def test_cli_rejects_invalid_bind_arguments(self):
        for arguments in (["--host", "0.0.0.0"], ["--port", "65536"]):
            with self.subTest(arguments=arguments), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    main(arguments)
                self.assertEqual(caught.exception.code, 2)
