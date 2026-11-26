"""Loopback-only HTTP server for the dashboard and its read-only JSON API."""

import json
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import socket
from urllib.parse import parse_qs

from . import view_models
from .contract import HISTORY_LIMIT, HISTORY_MAX_OFFSET
from .data_source import DataSource, MockDataSource, utc_stamp
from .privacy import scrub


LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
_HTTP_HOSTS = ("127.0.0.1", "localhost", "[::1]")
_RUN_REF_PATTERN = r"[0-9a-f]{24}"
_RESULT_ROUTE = re.compile(rf"/results/({_RUN_REF_PATTERN})/([a-z]+)")
_RESULT_CSP = ("sandbox; default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; "
               "form-action 'none'; frame-ancestors 'none'")
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
    "/api/pipeline/run": view_models.run_detail,
}


def _query_arguments(path, query, data_mode="mock"):
    values = parse_qs(query, keep_blank_values=True, max_num_fields=8)
    allowed = {
        "/api/usage": {"range"},
        "/api/requests": {"limit", "offset", "provider", "stage", "outcome"},
        "/api/pipeline/run": {"ref"},
    }.get(path, set())
    if values.keys() - allowed or any(len(items) != 1 for items in values.values()):
        raise ValueError("Invalid query parameters.")
    params = {key: items[0] for key, items in values.items()}
    if path == "/api/pipeline/run":
        if not re.fullmatch(_RUN_REF_PATTERN, params.get("ref", "")):
            raise ValueError("Invalid run reference.")
        return params
    if path == "/api/usage":
        range_name = params.get("range", "24h")
        if range_name not in view_models.USAGE_RANGES:
            raise ValueError("Choose a range of 24h or 7d.")
        return {"range_name": range_name}
    if path == "/api/requests":
        maximum = HISTORY_LIMIT if data_mode == "live" else 200
        numbers = {}
        for key, default, low, high in (("limit", "50", 1, maximum), ("offset", "0", 0, HISTORY_MAX_OFFSET)):
            raw = params.pop(key, default)
            if not (raw.isascii() and raw.isdecimal() and len(raw) <= len(str(high))
                    and low <= int(raw) <= high):
                raise ValueError(f"Choose a request {key} from {low} to {high}.")
            numbers[key] = int(raw)
        return {**numbers, **{key: value for key, value in params.items() if value}}
    return {}


class DashboardHandler(BaseHTTPRequestHandler):
    def __init__(self, *args, source: DataSource, **kwargs):
        self.source = source
        super().__init__(*args, **kwargs)

    def _send(self, status, content_type, body, *, allow=None, result=False):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", _RESULT_CSP if result else "default-src 'self'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        if result:
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("Referrer-Policy", "no-referrer")
        if allow:
            self.send_header("Allow", allow)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status, payload, *, allow=None, source=None):
        source = self.source if source is None else source
        metadata = source.metadata() if hasattr(source, "metadata") else {}
        body = json.dumps(scrub({**payload, **metadata, "data_mode": source.data_mode,
                                 "generated_at": utc_stamp(source.now)}, getattr(source, "secrets", ())),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
        self._send(status, "application/json; charset=utf-8", body, allow=allow)

    def do_GET(self):
        # The base handler normalizes leading slashes. Match the original target exactly.
        path, _, query = self.requestline.split()[1].partition("?")
        if path in STATIC_ROUTES:
            filename, content_type = STATIC_ROUTES[path]
            self._send(200, content_type, (STATIC_DIR / filename).read_bytes())
        elif path in API_ROUTES:
            try:
                arguments = _query_arguments(path, query, self.source.data_mode)
            except ValueError as error:
                self._json(400, {"error": str(error)})
                return
            source = self.source.for_request() if hasattr(self.source, "for_request") else self.source
            payload = API_ROUTES[path](source, **arguments)
            if payload is None:
                self._json(404, {"error": "Run not found."}, source=source)
            else:
                self._json(200, payload, source=source)
        elif not query and (match := _RESULT_ROUTE.fullmatch(path)) is not None:
            self._stage_result(*match.groups())
        else:
            self._json(404, {"error": "Path not found."})

    def _stage_result(self, ref, stage):
        port = self.server.server_port
        accepted_hosts = {f"{host}:{port}" for host in _HTTP_HOSTS}
        if port == 80:
            accepted_hosts.update(_HTTP_HOSTS)
        hosts = self.headers.get_all("Host", ())
        site = self.headers.get("Sec-Fetch-Site")
        source = self.source.for_request() if hasattr(self.source, "for_request") else self.source
        reader = getattr(source, "stage_result", None)
        if (reader is not None and len(hosts) == 1 and hosts[0].lower() in accepted_hosts
                and site in (None, "same-origin", "none") and (result := reader(ref, stage)) is not None):
            self._send(200, *result, result=True)
        else:
            self._json(404, {"error": "Result not found."})

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
