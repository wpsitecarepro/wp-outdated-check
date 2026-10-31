"""Tests use a local fake WordPress site and a fake WordPress.org API. No internet needed."""
import json, os, sys, threading, unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import wp_outdated_check as w

SITE = """<html><head><meta name="generator" content="WordPress 6.3.1" />
<link rel="stylesheet" href="/wp-content/plugins/contact-form-7/includes/css/styles.css?ver=5.9.8">
<link rel="stylesheet" href="/wp-content/plugins/akismet/_inc/akismet.css?ver=5.3">
<script src="/wp-content/plugins/old-abandoned/js/a.js?ver=1.0"></script>
<script src="/wp-content/plugins/premium-thing/x.js?ver=2.1"></script>
<script src="/wp-content/plugins/hidden-ver/x.js"></script>
<link rel="stylesheet" href="/wp-content/themes/twentytwentythree/style.css?ver=1.2">
</head><body><a href="/about/">About</a><a href="https://other.example/">x</a></body></html>"""
ABOUT = '<html><body><script src="/wp-content/plugins/only-on-about/a.js?ver=3.0"></script></body></html>'

PLUGINS = {
    "contact-form-7": {"version": "6.0.1", "last_updated": "2026-09-01 10:00am GMT"},
    "akismet": {"version": "5.3", "last_updated": "2026-08-01 10:00am GMT"},
    "old-abandoned": {"version": "1.0", "last_updated": "2019-01-01 10:00am GMT"},
    "hidden-ver": {"version": "4.0", "last_updated": "2026-01-01 10:00am GMT"},
    "only-on-about": {"version": "3.1", "last_updated": "2026-01-01 10:00am GMT"},
}
THEMES = {"twentytwentythree": {"version": "1.5", "last_updated": "2026-05-01"}}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, body, ctype="text/html"):
        b = body.encode(); self.send_response(code)
        self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if u.path == "/": return self._send(200, SITE)
        if u.path == "/about/": return self._send(200, ABOUT)
        if u.path == "/api/core/version-check/1.7/":
            return self._send(200, json.dumps({"offers": [{"current": "6.8.3"}]}), "application/json")
        if u.path == "/api/plugins/info/1.2/":
            d = PLUGINS.get(q["request[slug]"][0])
            return self._send(200, json.dumps(d or {"error": "Plugin not found."}), "application/json")
        if u.path == "/api/themes/info/1.2/":
            d = THEMES.get(q["request[slug]"][0])
            return self._send(200, json.dumps(d or {"error": "Theme not found."}), "application/json")
        self._send(404, "nope")


class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_port}"
    @classmethod
    def tearDownClass(cls): cls.srv.shutdown()

    def rows(self, deep=0):
        r = w.check_site(self.base + "/", w.Api(self.base + "/api"), deep)
        return r, {x["slug"]: x for x in r["rows"]}

    def test_versions(self):
        self.assertEqual(w.compare("6.3.1", "6.8.3"), -1)
        self.assertEqual(w.compare("6.8", "6.8.0"), 0)
        self.assertEqual(w.compare("10.0", "9.9"), 1)
        self.assertEqual(w.compare("1.0-beta", "1.0"), 0)

    def test_core_outdated(self):
        r, rows = self.rows()
        self.assertEqual(rows["WordPress"]["status"], "outdated")
        self.assertEqual(r["core"], "6.3.1")

    def test_plugin_states(self):
        _, rows = self.rows()
        self.assertEqual(rows["contact-form-7"]["status"], "outdated")
        self.assertEqual(rows["akismet"]["status"], "ok")
        self.assertEqual(rows["premium-thing"]["status"], "not-listed")
        self.assertEqual(rows["hidden-ver"]["status"], "unknown")
        self.assertTrue(rows["old-abandoned"].get("stale"))
        self.assertEqual(rows["twentytwentythree"]["status"], "outdated")

    def test_deep_finds_more(self):
        _, a = self.rows(0); _, b = self.rows(5)
        self.assertNotIn("only-on-about", a)
        self.assertEqual(b["only-on-about"]["status"], "outdated")

    def test_not_wordpress(self):
        r = w.check_site(self.base + "/about/x", w.Api(self.base + "/api"))
        self.assertFalse(r["is_wordpress"])

    def test_unreachable(self):
        r = w.check_site("http://127.0.0.1:1/", w.Api(self.base + "/api"), timeout=2)
        self.assertFalse(r["reachable"])

    def test_outputs(self):
        r, _ = self.rows()
        self.assertIn("OUTDATED", w.render_text(r))
        self.assertIn("<table>", w.render_html(r))
        self.assertNotIn("<script", w.render_html(r))

    def test_exit_code(self):
        self.assertEqual(w.main([self.base + "/", "--api", self.base + "/api"]), 1)


if __name__ == "__main__":
    unittest.main()
