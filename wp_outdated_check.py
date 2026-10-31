#!/usr/bin/env python3
"""WP Outdated Check - find outdated WordPress core, plugins and themes from the outside.

Reads only what a site already shows to every visitor (page source, the public
feed and the public readme.html) and compares the versions it finds with the
latest releases published on WordPress.org. Python standard library only.

Use it on sites you own or look after.

Made by WP Site Care - https://wpsitecare.pro/
License: MIT
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

__version__ = "1.0.0"

API_BASE = "https://api.wordpress.org"
USER_AGENT = f"wp-outdated-check/{__version__} (+https://wpsitecare.pro/)"
MAX_BYTES = 3_000_000
STALE_DAYS = 730          # not updated for 2 years: probably abandoned
HELP_URL = "https://wpsitecare.pro/free-site-check/"

# ------------------------------------------------------------------ helpers

def fetch(url: str, timeout: float = 15.0) -> tuple[int, str, dict]:
    """GET a URL. Returns (status, body text, headers). Status 0 means network error."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(MAX_BYTES)
            charset = r.headers.get_content_charset() or "utf-8"
            return r.status, raw.decode(charset, "replace"), dict(r.headers)
    except urllib.error.HTTPError as e:
        try:
            body = e.read(MAX_BYTES).decode("utf-8", "replace")
        except Exception:
            body = ""
        return e.code, body, dict(e.headers or {})
    except Exception as e:  # DNS, TLS, timeout, ...
        return 0, str(e), {}


def parse_version(v: str) -> tuple:
    """'6.4.2' -> (6, 4, 2). Text after the numbers (-beta1, .x) is ignored."""
    nums = re.findall(r"\d+", re.split(r"[-+ ]", v.strip(), maxsplit=1)[0])
    return tuple(int(n) for n in nums) or (0,)


def compare(current: str, latest: str) -> int:
    a, b = list(parse_version(current)), list(parse_version(latest))
    n = max(len(a), len(b))
    a += [0] * (n - len(a))
    b += [0] * (n - len(b))
    return (a > b) - (a < b)


def gap(current: str, latest: str) -> str:
    """How far behind: 'major', 'minor' or 'patch'."""
    a, b = list(parse_version(current)), list(parse_version(latest))
    a += [0] * (3 - len(a))
    b += [0] * (3 - len(b))
    if a[0] != b[0]:
        return "major"
    return "minor" if a[1] != b[1] else "patch"


def days_since(date_text: str) -> int | None:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", date_text or "")
    if not m:
        return None
    d = datetime(int(m[1]), int(m[2]), int(m[3]), tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - d).days


def normalize_url(u: str) -> str:
    u = u.strip()
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    p = urllib.parse.urlparse(u)
    if not p.netloc:
        raise ValueError(f"Not a valid address: {u}")
    return u.rstrip("/") + "/" if not p.path or p.path == "/" else u

# ------------------------------------------------------------------ detection

def detect(pages: list[str], base: str) -> dict:
    """Pull WordPress core, plugin and theme versions out of page sources."""
    found = {"core": None, "core_source": None, "plugins": {}, "themes": {}}
    blob = "\n".join(pages)

    m = re.search(r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']WordPress\s+([\d.]+[^"\']*)["\']', blob, re.I)
    if m:
        found["core"], found["core_source"] = m.group(1).strip(), "generator tag"

    # The word "WordPress" in the text proves nothing (a static site can write about it),
    # so only look for the files and tags that WordPress itself puts in a page.
    is_wp = bool(found["core"]) or bool(re.search(
        r"/wp-(content|includes)/|/wp-json[/\"']|rel=[\"']https://api\.w\.org/", blob, re.I))
    found["is_wordpress"] = is_wp

    def collect(kind: str, folder: str):
        pat = re.compile(rf"/wp-content/{folder}/([A-Za-z0-9_.-]+)/([^\s\"'<>)]*)")
        for slug, rest in pat.findall(blob):
            slug = slug.lower()
            entry = found[kind].setdefault(slug, None)
            v = re.search(r"[?&](?:ver|v)=(\d+(?:\.\d+){0,3})", rest)
            if v and (entry is None):
                found[kind][slug] = v.group(1)
            else:
                found[kind].setdefault(slug, entry)

    collect("plugins", "plugins")
    collect("themes", "themes")
    return found


def core_from_assets(pages: list[str]) -> str | None:
    """wp-includes assets are versioned with the core version (?ver=6.4.2)."""
    blob = "\n".join(pages)
    for m in re.finditer(r"/wp-includes/[^\s\"'<>]*?\?ver=(\d+\.\d+(?:\.\d+)?)", blob):
        return m.group(1)
    return None


def internal_links(page: str, base: str, limit: int) -> list[str]:
    host = urllib.parse.urlparse(base).netloc
    out: list[str] = []
    for href in re.findall(r'<a[^>]+href=["\']([^"\'#]+)["\']', page, re.I):
        u = urllib.parse.urljoin(base, html.unescape(href))
        p = urllib.parse.urlparse(u)
        if p.netloc == host and p.scheme in ("http", "https") and u not in out and u != base \
           and not re.search(r"\.(jpg|jpeg|png|gif|svg|webp|pdf|zip|css|js)$", p.path, re.I) \
           and "wp-login" not in u and "wp-admin" not in u:
            out.append(u)
        if len(out) >= limit:
            break
    return out

# ------------------------------------------------------------------ WordPress.org lookups

class Api:
    def __init__(self, base: str = API_BASE, timeout: float = 15.0):
        self.base, self.timeout = base.rstrip("/"), timeout
        self._cache: dict = {}

    def _json(self, path: str):
        if path in self._cache:
            return self._cache[path]
        status, body, _ = fetch(self.base + path, self.timeout)
        data = None
        if status == 200:
            try:
                data = json.loads(body)
            except ValueError:
                data = None
        self._cache[path] = (status, data)
        return status, data

    def core_latest(self) -> str | None:
        status, data = self._json("/core/version-check/1.7/")
        try:
            return data["offers"][0]["current"]
        except Exception:
            return None

    def plugin(self, slug: str) -> dict | None:
        q = urllib.parse.urlencode({"action": "plugin_information", "request[slug]": slug})
        status, data = self._json(f"/plugins/info/1.2/?{q}")
        if status == 0:
            return {"_error": "network"}
        if isinstance(data, dict) and data.get("version"):
            return data
        return None

    def theme(self, slug: str) -> dict | None:
        q = urllib.parse.urlencode({"action": "theme_information", "request[slug]": slug,
                                    "request[fields][last_updated]": "1"})
        status, data = self._json(f"/themes/info/1.2/?{q}")
        if status == 0:
            return {"_error": "network"}
        if isinstance(data, dict) and data.get("version"):
            return data
        return None

# ------------------------------------------------------------------ checking

def judge(name: str, kind: str, current: str | None, info: dict | None) -> dict:
    row = {"kind": kind, "slug": name, "installed": current, "latest": None,
           "status": "unknown", "note": "", "last_updated": None}
    if info is None:
        row["status"] = "not-listed"
        row["note"] = "Not found on WordPress.org: a premium or custom " + kind + ", or one that was removed. Check it by hand."
        return row
    if info.get("_error"):
        row["status"] = "error"
        row["note"] = "Could not reach WordPress.org."
        return row
    row["latest"] = str(info.get("version"))
    lu = info.get("last_updated") or info.get("last_updated_time") or ""
    row["last_updated"] = lu[:10] if lu else None
    age = days_since(lu)
    if current is None:
        row["status"] = "unknown"
        row["note"] = "Version is hidden. Latest is " + row["latest"] + "; check it in the dashboard."
    else:
        c = compare(current, row["latest"])
        if c < 0:
            row["status"] = "outdated"
            row["note"] = f"{gap(current, row['latest'])} update available"
        else:
            row["status"] = "ok"
            row["note"] = "up to date"
    if age is not None and age > STALE_DAYS:
        row["stale"] = True
        row["note"] += f"; not updated for {age // 365} years (possibly abandoned)"
    return row


def check_site(url: str, api: Api, deep: int = 0, timeout: float = 15.0) -> dict:
    base = normalize_url(url)
    status, body, headers = fetch(base, timeout)
    report = {"url": base, "checked": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
              "reachable": status in range(200, 400) or bool(body and status), "http_status": status,
              "is_wordpress": False, "core": None, "rows": [], "errors": [], "tool": __version__}
    if status == 0:
        report["reachable"] = False
        report["errors"].append(f"Could not open the site: {body}")
        return report
    pages = [body]
    for link in internal_links(body, base, deep) if deep else []:
        s, b, _ = fetch(link, timeout)
        if s == 200:
            pages.append(b)

    found = detect(pages, base)
    report["is_wordpress"] = found["is_wordpress"]
    if not found["is_wordpress"]:
        report["errors"].append("No sign of WordPress in the page source. Nothing to compare.")
        return report

    core_v, core_src = found["core"], found["core_source"]
    if not core_v:
        s, b, _ = fetch(urllib.parse.urljoin(base, "feed/"), timeout)
        m = re.search(r"<generator>https?://wordpress\.org/\?v=([\d.]+)", b) if s == 200 else None
        if m:
            core_v, core_src = m.group(1), "RSS feed"
    if not core_v:
        s, b, _ = fetch(urllib.parse.urljoin(base, "readme.html"), timeout)
        m = re.search(r"Version\s+(\d+\.\d+(?:\.\d+)?)", b) if s == 200 else None
        if m:
            core_v, core_src = m.group(1), "readme.html"
    if not core_v:
        core_v = core_from_assets(pages)
        core_src = "asset version numbers" if core_v else None

    latest_core = api.core_latest()
    row = {"kind": "core", "slug": "WordPress", "installed": core_v, "latest": latest_core,
           "status": "unknown", "note": "", "last_updated": None}
    if latest_core is None:
        row["status"], row["note"] = "error", "Could not read the latest version from WordPress.org."
    elif core_v is None:
        row["note"] = "Version is hidden. Latest is " + latest_core + "."
    elif compare(core_v, latest_core) < 0:
        row["status"], row["note"] = "outdated", f"{gap(core_v, latest_core)} update available (found via {core_src})"
    else:
        row["status"], row["note"] = "ok", f"up to date (found via {core_src})"
    report["core"] = core_v
    report["rows"].append(row)

    for slug, ver in sorted(found["plugins"].items()):
        report["rows"].append(judge(slug, "plugin", ver, api.plugin(slug)))
    for slug, ver in sorted(found["themes"].items()):
        report["rows"].append(judge(slug, "theme", ver, api.theme(slug)))
    return report

# ------------------------------------------------------------------ output

ORDER = {"outdated": 0, "error": 1, "not-listed": 2, "unknown": 3, "ok": 4}
LABEL = {"outdated": "OUTDATED", "ok": "ok", "unknown": "unknown", "not-listed": "check by hand", "error": "error"}


def summary(report: dict) -> dict:
    c = {k: 0 for k in LABEL}
    for r in report["rows"]:
        c[r["status"]] += 1
    return c


def render_text(report: dict, color: bool = False) -> str:
    def paint(s, code):
        return f"\033[{code}m{s}\033[0m" if color else s
    out = [f"WP Outdated Check - {report['url']}", f"Checked {report['checked']}", ""]
    for e in report["errors"]:
        out.append(e)
    if report["rows"]:
        rows = sorted(report["rows"], key=lambda r: (ORDER[r["status"]], r["kind"] != "core", r["slug"]))
        w = max(len(r["slug"]) for r in rows)
        out.append(f"{'':9}{'name':<{w}}  {'installed':<10} {'latest':<10} status")
        for r in rows:
            col = {"outdated": "31;1", "ok": "32", "error": "31"}.get(r["status"], "33")
            out.append(f"{r['kind']:<9}{r['slug']:<{w}}  {(r['installed'] or '?'):<10} {(r['latest'] or '?'):<10} "
                       + paint(LABEL[r["status"]], col) + (f"  {r['note']}" if r["note"] else ""))
        s = summary(report)
        out += ["", f"{s['outdated']} outdated, {s['ok']} up to date, {s['unknown'] + s['not-listed']} need a manual look."]
        if s["outdated"]:
            out.append(f"Want someone to update and test it safely? {HELP_URL}")
    return "\n".join(out)


def render_html(report: dict) -> str:
    e = html.escape
    s = summary(report)
    rows = sorted(report["rows"], key=lambda r: (ORDER[r["status"]], r["kind"] != "core", r["slug"]))
    trs = "".join(
        f"<tr class='{r['status']}'><td>{e(r['kind'])}</td><td>{e(r['slug'])}</td><td>{e(r['installed'] or '?')}</td>"
        f"<td>{e(r['latest'] or '?')}</td><td><b>{e(LABEL[r['status']])}</b></td><td>{e(r['note'])}</td></tr>" for r in rows)
    errs = "".join(f"<p class='err'>{e(x)}</p>" for x in report["errors"])
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>WordPress update report - {e(report['url'])}</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;color:#1b2430}}
table{{border-collapse:collapse;width:100%}}th,td{{text-align:left;padding:.5rem .6rem;border-bottom:1px solid #dde3ea}}
th{{background:#f1f5fb}}tr.outdated td{{background:#fff1ef}}tr.ok td{{background:#f2faf4}}tr.not-listed td,tr.unknown td{{background:#fff9e8}}
.err{{color:#b3261e}}.sum{{display:flex;gap:1rem;flex-wrap:wrap;margin:1rem 0}}.sum div{{background:#f1f5fb;padding:.6rem 1rem;border-radius:8px}}
a{{color:#2f5fb3}}small{{color:#5b6877}}</style></head><body>
<h1>WordPress update report</h1><p>{e(report['url'])}<br><small>Checked {e(report['checked'])}</small></p>{errs}
<div class="sum"><div><b>{s['outdated']}</b> outdated</div><div><b>{s['ok']}</b> up to date</div><div><b>{s['unknown'] + s['not-listed']}</b> need a manual look</div></div>
<table><tr><th>Type</th><th>Name</th><th>Installed</th><th>Latest</th><th>Status</th><th>Note</th></tr>{trs}</table>
<p><small>Versions are read from the public page source and compared with WordPress.org. Hidden versions and premium extensions
cannot be checked from the outside.</small></p>
<p>Need these updated and tested without breaking the site? <a href="{HELP_URL}">Ask WP Site Care for a free site check</a>.</p>
</body></html>"""

# ------------------------------------------------------------------ CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="wp-outdated-check",
        description="Find outdated WordPress core, plugins and themes on a site, from the outside. Use it on your own sites.")
    ap.add_argument("url", nargs="+", help="site address, e.g. example.com")
    ap.add_argument("--deep", type=int, default=0, metavar="N", help="also read up to N internal pages (finds more plugins)")
    ap.add_argument("--json", action="store_true", help="print JSON instead of a table")
    ap.add_argument("--html", metavar="FILE", help="also write an HTML report to FILE (one site only)")
    ap.add_argument("--timeout", type=float, default=15.0, help="seconds per request (default 15)")
    ap.add_argument("--api", default=API_BASE, help=argparse.SUPPRESS)
    ap.add_argument("--version", action="version", version=__version__)
    a = ap.parse_args(argv)

    if a.html and len(a.url) > 1:
        ap.error("--html works with one site at a time")
    api = Api(a.api, a.timeout)
    reports, bad = [], False
    for u in a.url:
        try:
            r = check_site(u, api, a.deep, a.timeout)
        except ValueError as ex:
            print(ex, file=sys.stderr)
            return 2
        reports.append(r)
        bad = bad or summary(r)["outdated"] > 0
        if not a.json:
            print(render_text(r, color=sys.stdout.isatty()), end="\n\n")
    if a.json:
        print(json.dumps(reports if len(reports) > 1 else reports[0], indent=2))
    if a.html:
        with open(a.html, "w", encoding="utf-8") as f:
            f.write(render_html(reports[0]))
        print(f"HTML report written to {a.html}", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
