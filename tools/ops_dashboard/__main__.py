"""Run the local operations dashboard."""

import argparse
from pathlib import Path

from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError

from .data_source import MockDataSource
from .live_source import DEFAULT_DOTENV, LiveDataSource

from .server import LOOPBACK_HOSTS, make_server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", choices=LOOPBACK_HOSTS)
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--mock", action="store_true", help="Use the Phase 6A example data.")
    parser.add_argument("--dotenv", type=Path, default=DEFAULT_DOTENV, metavar="PATH",
                        help="Read provider settings from this file (default: repository .env).")
    for option in ("telemetry", "quota-state", "runs-dir", "seasons-dir", "policy"):
        parser.add_argument(f"--{option}", type=Path, metavar="PATH")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("port must be between 0 and 65535")
    try:
        if args.mock:
            source = MockDataSource()
        else:
            source = LiveDataSource(dotenv_path=args.dotenv, overrides=vars(args))
            for description in source.describe_sources():
                print(description, flush=True)
        with make_server(args.host, args.port, source=source) as server:
            hostname = "[::1]" if args.host == "::1" else args.host
            print(f"http://{hostname}:{server.server_port}/", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        return 0
    except (OSError, UnicodeError, GeminiConfigError):
        parser.exit(1, "Could not start dashboard. Check the dotenv file and server settings.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
