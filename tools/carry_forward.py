#!/usr/bin/env python3
"""Carry already-published feeds into the Pages artifact.

The four-hourly build skips low-frequency sources. Their directories must still
exist in `public/`, or the next Pages deploy would drop them, so this copies the
previous feed and a minimal index from the live site.

Keys come from CARRY_KEYS (comma-separated). A missing or unreachable feed is
reported and skipped: the run continues, and the source's next real build
restores it.
"""
from __future__ import annotations

import html
import os
import re
import sys

import requests

PUBLISHED_BASE_URL = os.environ.get("PUBLISHED_BASE_URL", "").strip().rstrip("/")
OUT_DIR = os.environ.get("CARRY_OUT_DIR", "public")
TIMEOUT = int(os.environ.get("CARRY_TIMEOUT", "30"))
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.7922.76 Safari/537.36"
)
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
ITEM_RE = re.compile(r"<item>")


def keys_from_env() -> list[str]:
    raw = os.environ.get("CARRY_KEYS", "")
    return [key.strip() for key in raw.split(",") if key.strip()]


def feed_title(xml: str) -> str:
    match = TITLE_RE.search(xml)
    return html.unescape(match.group(1)).strip() if match else "Feed"


def write_feed(key: str, xml: str) -> None:
    directory = os.path.join(OUT_DIR, key)
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, "feed.xml"), "w", encoding="utf-8") as handle:
        handle.write(xml)
    count = len(ITEM_RE.findall(xml))
    title = feed_title(xml)
    with open(os.path.join(directory, "index.html"), "w", encoding="utf-8") as handle:
        handle.write(
            "<!doctype html><meta charset='utf-8'>"
            f"<title>{html.escape(title)} (unofficial RSS)</title>"
            f"<h1>{html.escape(title)} (unofficial)</h1>"
            f"<p>{count} items. Low-frequency source; refreshed on its own schedule.</p>"
            "<p>Subscribe: <a href='feed.xml'>feed.xml</a></p>"
        )


def main() -> int:
    keys = keys_from_env()
    if not keys:
        print("  no CARRY_KEYS; nothing to carry")
        return 0
    if not PUBLISHED_BASE_URL:
        print("  no PUBLISHED_BASE_URL; skipped feeds are not carried")
        return 0

    session = requests.Session()
    session.headers.update({"User-Agent": UA})
    carried = 0
    failed: list[str] = []
    for key in keys:
        url = f"{PUBLISHED_BASE_URL}/{key}/feed.xml"
        try:
            response = session.get(url, timeout=TIMEOUT)
        except requests.RequestException as exc:
            print(f"  carry {key}: {exc}", file=sys.stderr)
            failed.append(key)
            continue
        if response.status_code != 200 or "<rss" not in response.text[:400]:
            print(f"  carry {key}: HTTP {response.status_code}", file=sys.stderr)
            failed.append(key)
            continue
        write_feed(key, response.text)
        carried += 1
    print(f"  carried {carried}/{len(keys)} skipped feeds")
    if failed:
        # A missing directory would be dropped by the Pages deploy, so refuse
        # to publish a partial site; the previous deployment stays live.
        print(f"  carry failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
