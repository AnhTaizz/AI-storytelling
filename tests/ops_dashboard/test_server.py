from html.parser import HTMLParser
from http.client import HTTPConnection
import json
import re
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import build_opener, ProxyHandler, Request

from tools.ops_dashboard.contract import FIELDS
from tools.ops_dashboard.data_source import MockDataSource
from tools.ops_dashboard.server import STATIC_DIR, make_server


ENDPOINTS = (
    "/api/overview", "/api/providers", "/api/usage?range=24h", "/api/usage?range=7d",
    "/api/requests?limit=200&provider=gemini", "/api/requests?limit=200&provider=groq",
    "/api/requests?limit=200&provider=openrouter", "/api/requests?limit=200&provider=cloudflare",
    "/api/routing-policy", "/api/pipeline",
)
SECRET_PATTERN = re.compile(r"AIza|gsk_|sk-or-|Bearer|(?<![a-f\d])[a-f\d]{32}(?![a-f\d])", re.I)


class Anchors(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = set()
        self.controls = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a":
            self.hrefs.add(attrs.get("href"))
        if tag in ("button", "select") and "id" in attrs:
            self.controls[attrs["id"]] = attrs


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = make_server(port=0)
        thread = Thread(target=cls.server.serve_forever, daemon=True)
        thread.start()
        cls.addClassCleanup(cls.server.server_close)
        cls.addClassCleanup(thread.join)
        cls.addClassCleanup(cls.server.shutdown)
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.opener = build_opener(ProxyHandler({}))

    def fetch(self, path, method="GET"):
        try:
            response = self.opener.open(Request(self.url + path, method=method), timeout=3)
        except HTTPError as error:
            response = error
        with response:
            self.assertEqual(response.headers["Content-Security-Policy"], "default-src 'self'")
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            return response.status, response.read(), response.headers

    def mock_json(self, body):
        self.assertNotRegex(body.decode("utf-8"), SECRET_PATTERN)
        data = json.loads(body)
        self.assertEqual(data["data_mode"], "mock")
        self.assertTrue(data["generated_at"].endswith("+00:00"))
        return data

    def test_every_endpoint_returns_mock_json_with_security_headers(self):
        for path in ENDPOINTS:
            with self.subTest(path=path):
                status, body, headers = self.fetch(path)
                self.assertEqual(status, 200)
                self.assertEqual(headers.get_content_type(), "application/json")
                self.mock_json(body)

    def test_methods_and_invalid_query_parameters(self):
        for method in ("POST", "PUT", "DELETE", "OPTIONS", "PATCH", "HEAD", "BREW"):
            with self.subTest(method=method):
                status, body, headers = self.fetch("/api/overview", method)
                self.assertEqual(status, 405)
                self.assertEqual(headers["Allow"], "GET")
                if method == "HEAD":
                    self.assertEqual(body, b"")
                else:
                    self.mock_json(body)
        for path in ("/api/usage?range=1h", "/api/usage?range=24h&range=7d",
                     "/api/requests?limit=-1", "/api/requests?limit=0",
                     "/api/requests?limit=201", "/api/providers?extra=1"):
            with self.subTest(path=path):
                status, body, _ = self.fetch(path)
                self.assertEqual(status, 400)
                self.mock_json(body)

    def test_unknown_and_traversal_paths_are_rejected(self):
        for path in ("/missing", "/../", "/../app.js", "/%2e%2e/app.js", "/%2e%2e%2fapp.js",
                     "/%252e%252e/app.js", "/..%5capp.js", "//app.js"):
            with self.subTest(path=path):
                connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
                try:
                    connection.request("GET", path)
                    with connection.getresponse() as response:
                        self.assertEqual(response.status, 404)
                        self.mock_json(response.read())
                finally:
                    connection.close()

    def test_start_rejects_non_loopback_host(self):
        for host in ("0.0.0.0", "::", "example.invalid", "127.0.0.2"):
            with self.subTest(host=host), self.assertRaises(ValueError):
                make_server(host, port=0)
        with make_server("localhost", port=0) as server:
            self.assertEqual(server.server_address[0], "127.0.0.1")

    def test_static_assets_are_served_and_offline(self):
        status, body, _ = self.fetch("/")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        anchors = Anchors()
        anchors.feed(html)
        self.assertTrue({"#overview", "#providers", "#usage", "#requests", "#routing-policy",
                         "#pipeline"} <= anchors.hrefs)
        self.assertIn("MOCK DATA — not connected", html)
        self.assertIn("DỮ LIỆU MẪU — chưa kết nối hệ thống thật", html)
        for control in ("language", "theme"):
            with self.subTest(control=control):
                self.assertTrue(anchors.controls[control]["aria-label"].strip())
        self.assertEqual(anchors.controls["menu"]["aria-expanded"], "false")
        self.assertEqual(anchors.controls["menu"]["aria-controls"], "navigation")
        fetch_calls = []
        for path in sorted(STATIC_DIR.iterdir()):
            with self.subTest(path=path.name):
                status, served, _ = self.fetch("/" + path.name)
                self.assertEqual(status, 200)
                self.assertEqual(served, path.read_bytes())
                content = served.decode("utf-8")
                self.assertNotRegex(content, SECRET_PATTERN)
                self.assertNotRegex(content, r"https?://|(?:src|href)=[\"']//")
                fetch_calls.extend(re.findall(r"\bfetch\s*\(\s*([^\n;]+)", content))
        self.assertTrue(fetch_calls)
        for expression in fetch_calls:
            self.assertRegex(expression, r"^[\"']/api/")

    def test_both_locales_cover_mock_outcomes_and_errors(self):
        script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
        strings = {}
        for locale in ("vi", "en"):
            match = re.search(rf"^  {locale}: \{{\n(.*?)^  \}},", script, re.M | re.S)
            self.assertIsNotNone(match, locale)
            pairs = re.findall(r'(\w+|"[\w-]+"):\s*"([^"\n]+)"', match[1])
            strings[locale] = {key.strip('"'): label for key, label in pairs}
            self.assertEqual(len(pairs), len(strings[locale]), locale)
        self.assertEqual(strings["vi"].keys(), strings["en"].keys())

        source = MockDataSource()
        codes = {row[FIELDS[key]] for row in source.requests for key in ("outcome", "error")} - {None}
        codes.update(run["status"] for run in source.runs)
        codes.update(provider["last_error"] for provider in source.providers if provider["last_error"])
        codes.update(("RATE_LIMIT", "AUTH_FAILURE", "SERVER_FAILURE"))
        for code in sorted(codes):
            with self.subTest(code=code):
                self.assertIn(code, strings["vi"])
                self.assertNotEqual(strings["vi"][code], code)

    def test_provider_palette_is_fixed_in_automatic_and_explicit_themes(self):
        css = (STATIC_DIR / "app.css").read_text(encoding="utf-8")
        light, auto_dark, forced_dark = (
            re.search(selector + r"\s*\{([^}]+)\}", css)[1] for selector in
            (r"^:root", r':root:not\(\[data-theme="light"\]\)', r':root\[data-theme="dark"\]')
        )
        palette = {
            "gemini": ("#2a78d6", "#3987e5"),
            "groq": ("#eb6834", "#d95926"),
            "openrouter": ("#1baf7a", "#199e70"),
            "cloudflare": ("#eda100", "#c98500"),
        }
        for provider, (light_color, dark_color) in palette.items():
            with self.subTest(provider=provider):
                for block, expected in ((light, light_color), (auto_dark, dark_color), (forced_dark, dark_color)):
                    self.assertRegex(block, rf"--provider-{provider}:\s*{expected};")
