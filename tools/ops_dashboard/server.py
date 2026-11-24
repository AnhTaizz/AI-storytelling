"""Loopback-only HTTP server for the dashboard and its read-only JSON API."""

import json
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
from urllib.parse import parse_qs

from . import view_models
from .data_source import DataSource, MockDataSource, utc_stamp


LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
STATIC_DIR = Path(__file__).with_name("static")
STATIC_ROUTES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}
API_ROUTES = {
    "/api/overview": view_models.overview,
    "/api/providers": view_models.providers,
    "/api/usage": view_models.usage,
    "/api/requests": view_models.request_history,
    "/api/routing-policy": view_models.routing_policy,
    "/api/pipeline": view_models.pipeline,
}


def _query_arguments(path, query):
    values = parse_qs(query, keep_blank_values=True, max_num_fields=8)
    allowed = {
        "/api/usage": {"range"},
        "/api/requests": {"limit", "provider", "stage", "outcome"},
    }.get(path, set())
    if values.keys() - allowed or any(len(items) != 1 for items in values.values()):
        raise ValueError("Invalid query parameters.")
    params = {key: items[0] for key, items in values.items()}
    if path == "/api/usage":
        range_name = params.get("range", "24h")
        if range_name not in view_models.USAGE_RANGES:
            raise ValueError("Choose a range of 24h or 7d.")
        return {"range_name": range_name}
    if path == "/api/requests":
        raw_limit = params.pop("limit", "50")
        if not (raw_limit.isascii() and raw_limit.isdecimal() and len(raw_limit) <= 3):
            raise ValueError("Choose a request limit from 1 to 200.")
        limit = int(raw_limit)
        if not 1 <= limit <= 200:
            raise ValueError("Choose a request limit from 1 to 200.")
        return {"limit": limit, **{key: value for key, value in params.items() if value}}
    return {}


class DashboardHandler(BaseHTTPRequestHandler):
    def __init__(self, *args, source: DataSource, **kwargs):
        self.source = source
        super().__init__(*args, **kwargs)

    def _send(self, status, content_type, body, *, allow=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", "default-src 'self'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        if allow:
            self.send_header("Allow", allow)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status, payload, *, allow=None):
        body = json.dumps({**payload, "data_mode": self.source.data_mode,
                           "generated_at": utc_stamp(self.source.now)}).encode("utf-8")
        self._send(status, "application/json; charset=utf-8", body, allow=allow)

    def do_GET(self):
        # The base handler normalizes leading slashes. Match the original target exactly.
        path, _, query = self.requestline.split()[1].partition("?")
        if path in STATIC_ROUTES:
            filename, content_type = STATIC_ROUTES[path]
            self._send(200, content_type, (STATIC_DIR / filename).read_bytes())
        elif path in API_ROUTES:
            try:
                arguments = _query_arguments(path, query)
            except ValueError as error:
                self._json(400, {"error": str(error)})
                return
            self._json(200, API_ROUTES[path](self.source, **arguments))
        else:
            self._json(404, {"error": "Path not found."})

    def __getattr__(self, name):
        if name.startswith("do_"):
            return self._method_not_allowed
        raise AttributeError(name)

    def _method_not_allowed(self):
        self._json(405, {"error": "Only GET is supported."}, allow="GET")

    def log_request(self, code="-", size="-"):
        # Avoid logging raw request targets, including filter values.
        pass


class _IPv6Server(ThreadingHTTPServer):
    address_family = socket.AF_INET6


def make_server(host="127.0.0.1", port=8765, *, source: DataSource | None = None):
    if host not in LOOPBACK_HOSTS:
        raise ValueError("Host must be 127.0.0.1, localhost, or ::1.")
    if source is None:
        source = MockDataSource()
    server_class = _IPv6Server if host == "::1" else ThreadingHTTPServer
    bind_host = "127.0.0.1" if host == "localhost" else host
    return server_class((bind_host, port), partial(DashboardHandler, source=source))
