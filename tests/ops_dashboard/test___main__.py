import contextlib
import io
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
                self.assertEqual(main(["--host", "::1", "--port", "0"]), 0)
            self.assertEqual(output.getvalue().strip(), "http://[::1]:43210/")
            make_server.assert_called_once_with("::1", 0)
            make_server.return_value.__exit__.assert_called_once()

    def test_cli_rejects_invalid_bind_arguments(self):
        for arguments in (["--host", "0.0.0.0"], ["--port", "65536"]):
            with self.subTest(arguments=arguments), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    main(arguments)
                self.assertEqual(caught.exception.code, 2)
