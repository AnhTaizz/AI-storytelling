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
            with contextlib.redirect_stdout(output):
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
            self.assertNotIn(directory, lines)

    def test_cli_rejects_invalid_bind_arguments(self):
        for arguments in (["--host", "0.0.0.0"], ["--port", "65536"]):
            with self.subTest(arguments=arguments), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    main(arguments)
                self.assertEqual(caught.exception.code, 2)
