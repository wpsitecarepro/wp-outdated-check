# WP Outdated Check

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
[![No dependencies](https://img.shields.io/badge/dependencies-none-brightgreen.svg)](wp_outdated_check.py)

**Find out which parts of a WordPress site are out of date, without logging in.**

Free and open source, made by [WP Site Care](https://wpsitecare.pro/). Project page and downloads: **[wpsitecare.pro/wp-outdated-check](https://wpsitecare.pro/wp-outdated-check/)**

The tool reads what the site already shows every visitor (the page source, the public feed and `readme.html`), works out the versions of WordPress, plugins and themes, and compares them with the latest releases on WordPress.org. You get a short table: what is outdated, what is fine, and what needs a manual look.

- One file, Python 3.8+ standard library only. Nothing to install.
- Read-only: it only requests public pages. No logins, no guessing of passwords or hidden paths.
- Meant for **sites you own or look after**.

## Quick start

```bash
python3 wp_outdated_check.py example.com
```

```
WP Outdated Check - https://example.com/

         name               installed  latest     status
core     WordPress          6.3.1      6.8.3      OUTDATED  major update available (found via generator tag)
plugin   contact-form-7     5.9.8      6.0.1      OUTDATED  major update available
plugin   akismet            5.3        5.3        ok        up to date

2 outdated, 1 up to date, 0 need a manual look.
```

## Get it

- Clone this repository, or download the single file: [wp_outdated_check.py](wp_outdated_check.py)
- Or download it from the project page: [wpsitecare.pro/wp-outdated-check](https://wpsitecare.pro/wp-outdated-check/), which also lists the SHA-256 checksum.

## Options

| Option | What it does |
|---|---|
| `--deep N` | Also reads up to N internal pages. Some plugins load only on certain pages, so this finds more. |
| `--json` | Prints JSON, handy for scripts and monitoring. |
| `--html report.html` | Writes a clean report you can send to a client or colleague. |
| `--timeout S` | Seconds per request (default 15). |

Check several sites at once: `python3 wp_outdated_check.py site-a.com site-b.com --json`

The exit code is `1` when something is outdated and `0` otherwise, so it fits cron jobs and CI.

## What it can and cannot tell you

- Versions are taken from asset URLs (`style.css?ver=1.2`), the generator tag, the feed and `readme.html`. Sites that hide version numbers show **unknown**; log in to the dashboard to check those.
- Premium and custom plugins are not on WordPress.org, so they show **check by hand**.
- Plugins that were not updated for two years are flagged as possibly abandoned.
- It cannot see plugins that load no public files, and a cache or security plugin may show older numbers than the real ones.
- It does not look for vulnerabilities. It tells you where updates are waiting.

## Responsible use

Run it against your own sites or sites you are asked to look after. It sends ordinary page requests and a small number of lookups to WordPress.org, and it identifies itself with a user agent that links back to this project.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The tests run against a local fake site and a fake WordPress.org API, so they need no internet.

## Contributing

Bug reports and pull requests are welcome. Open an [issue](../../issues) with the address of a site that is detected wrongly (or a snippet of its page source) and what you expected to see.

## Need a hand?

If the list is long, or you would rather not risk breaking the site while updating, **[WP Site Care](https://wpsitecare.pro/)** does updates, backups and security checks for a fixed monthly price. See the [plans](https://wpsitecare.pro/plans/) or ask for a [free site check](https://wpsitecare.pro/free-site-check/).

## License

MIT. See [LICENSE](LICENSE).
