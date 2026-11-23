"""Run the local operations dashboard."""

import argparse

from .server import LOOPBACK_HOSTS, make_server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", choices=LOOPBACK_HOSTS)
    parser.add_argument("--port", default=8765, type=int)
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("port must be between 0 and 65535")
    try:
        with make_server(args.host, args.port) as server:
            hostname = "[::1]" if args.host == "::1" else args.host
            print(f"http://{hostname}:{server.server_port}/", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        return 0
    except OSError as error:
        parser.exit(1, f"Could not start dashboard: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
