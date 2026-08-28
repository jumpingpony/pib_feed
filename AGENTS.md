# Repository Guidelines

## Project Structure & Module Organization

This repository builds and publishes unofficial, full-text RSS feeds for Indian public-affairs and news sources. Each top-level Python file is a standalone scraper and feed builder; for example, `pib_feed.py` builds PIB feeds, `newsonair_feed.py` builds News On AIR feeds, and `economist.py` builds Economist feeds. Keep source-specific parsing, feed definitions, and environment-variable configuration in that source's script.

`OPML/` contains importable feed collections. `certs/` holds the bundled certificate needed by affected sources. Generated site output belongs in `public/` (normally ignored). `.github/workflows/build-feeds.yml` runs every builder and deploys the resulting site.

## Build, Test, and Development Commands

Install dependencies with:

```bash
python -m pip install -r requirements.txt
```

Run an individual builder locally, using its documented environment variables to keep network work small:

```bash
PIB_YEARS=2024 PIB_SCAN_COUNT=40 python pib_feed.py
NOA_BULLETIN_PAGES=1 python newsonair_feed.py
```

Inspect generated XML under `public/<feed-key>/feed.xml`. The workflow runs `python <builder>.py` for every source; preserve this standalone entry-point pattern.

## Coding Style & Naming Conventions

Use Python 3.12-compatible code, four-space indentation, `snake_case` for functions and variables, and `UPPER_CASE` for module constants and environment-variable names. Follow the existing layout: module docstring, standard-library imports before third-party imports, configuration constants near the top, and small helpers for HTTP, parsing, and rendering. Prefer explicit regexes and source-specific comments when a site behavior is non-obvious. Do not add a formatter or linter without also documenting and wiring it into CI.

## Testing Guidelines

There is no automated test suite. Make a narrow local run for the modified source, confirm it exits successfully, and validate that the expected `feed.xml` files are non-empty and parseable. Avoid broad production-like scans during development; builders scrape external services, so keep worker counts and page/year ranges conservative.

Before adding or changing a source's full-article extraction, inspect the local Bypass Paywalls Chrome Clean rules at `/home/slawpper/.local/share/bypass-paywalls-chrome-clean-master` for source-specific ways to identify the complete article body.

## HTTP User-Agent

For crawlers, scrapers, `wget`, `curl`, and scripted HTTP requests, always use:

`Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.76 Safari/537.36`

For example, use `curl -A '<UA>'`, `wget --user-agent='<UA>'`, or the equivalent request header.

## GitHub Runner HTTP Probe Heuristic

When a production scraper runs on GitHub Actions and local results may not represent the runner's network path, consider adding a temporary `.github/workflows/probe.yml`. Use it to reproduce the smallest relevant requests from the same runner family as production, compare HTTP status codes and short response diagnostics, dispatch it with `gh`, inspect its logs, and remove it after the diagnosis. This is a heuristic, not a required step for every HTTP failure.

Examples of useful probes include:

- A simple GET with the standard UA: `curl -A "$UA" -o response.html -w '%{http_code}\n' "$URL"`.
- A simple GET with `wget`: `wget --user-agent="$UA" --server-response -O response.html "$URL"`.
- A browser-like sequence that first loads a page into a cookie jar and then replays a POST with its current nonce, `Referer`, `Origin`, `X-Requested-With`, cookies, and exact form field names.
- A Python `requests.Session` probe with `session.headers['User-Agent'] = UA` when redirects, cookies, or response parsing are easier to diagnose in Python.
- Side-by-side control requests, such as the old request versus the current browser request, a listing endpoint versus a detail page, or the direct origin versus an official alternate endpoint.
- Logging status, final URL, content type, response size, selected headers, a short body excerpt, and parsed result counts without printing credentials, complete cookie values, or full protected content.
- Running and watching the temporary workflow with `gh workflow run probe.yml` and `gh run watch <run-id> --exit-status`, then deleting the probe workflow once the production path is understood.

## Commit & Pull Request Guidelines

Use short, imperative commit subjects consistent with history, such as `Add Frontline magazine and blog feeds` or `Fix PS body regex`. Keep each commit scoped to one source or infrastructure concern. Pull requests should state the affected feeds, explain parser or output changes, include a sample generated feed path or URL, and note any new environment variables, archive behavior, or source-site assumptions. Update `DOCS.md` and relevant `OPML/` files when adding or removing published feeds.
