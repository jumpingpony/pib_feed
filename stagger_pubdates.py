#!/usr/bin/env python3
"""Pull item pubDates older than ~2 weeks into the last 12 days.

Inoreader imports only a feed's ~100 newest items, and drops items whose
pubDate is older than roughly two weeks before the subscription is (re)added.
Every item in the NITI/Vision IAS feeds predates that window (NITI back to
2019), so Inoreader imported nothing at all. This dispatch-gated, one-off
step re-dates those stale items into the last 12 days — newest source item
first — so Inoreader can import them; the builders' published-base merge then
keeps the re-dated blocks on later runs. Items already inside the window keep
their real dates. Hindi items are left untouched (ignore Hindi posts). Dates
are approximate: item titles and bodies still carry the real month/year.

Usage:
    python stagger_pubdates.py       # rewrites <OUT_DIR>/<key>/feed.xml
"""
from __future__ import annotations

import datetime as dt
import os
import re
from email.utils import format_datetime, parsedate_to_datetime

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
OUT_DIR = os.environ.get("STAGGER_OUT_DIR", "public")
# Old items are spread from `now - TOP_OFFSET_HOURS` down to `now - WINDOW_DAYS`.
WINDOW_DAYS = int(os.environ.get("STAGGER_WINDOW_DAYS", "12"))
TOP_OFFSET_HOURS = int(os.environ.get("STAGGER_TOP_OFFSET_HOURS", "6"))

# The feeds whose subscribers hit Inoreader's import window.
KEYS = [
    "niti_reports",
    "niti_working-papers",
    "niti_research-papers",
    "niti_policy-papers",
    "niti_annual-reports",
    "visionias_pt-365",
    "visionias_mains-365",
]

ITEM_RE = re.compile(r"<item>.*?</item>", re.S)
PUBDATE_RE = re.compile(r"<pubDate>([^<]+)</pubDate>")
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
HINDI_RE = re.compile(r"\bhindi\b|[\u0900-\u097F]", re.I)


def is_hindi(block: str) -> bool:
    title = TITLE_RE.search(block)
    return bool(title and HINDI_RE.search(title.group(1)))


def parse_pub(block: str) -> dt.datetime | None:
    match = PUBDATE_RE.search(block)
    if not match:
        return None
    try:
        return parsedate_to_datetime(match.group(1).strip())
    except (TypeError, ValueError):
        return None


def stagger(key: str, now: dt.datetime) -> None:
    path = os.path.join(OUT_DIR, key, "feed.xml")
    with open(path, encoding="utf-8") as f:
        xml = f.read()

    spans = list(ITEM_RE.finditer(xml))
    blocks = [m.group(0) for m in spans]
    cutoff = now - dt.timedelta(days=WINDOW_DAYS)
    dates: list[dt.datetime] = []
    stale: list[int] = []
    kept, hindi = 0, 0
    for i, block in enumerate(blocks):
        when = parse_pub(block)
        if when is None or when >= cutoff:
            kept += 1
            dates.append(when or dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc))
            continue
        if is_hindi(block):
            hindi += 1
            dates.append(when)
            continue
        stale.append(i)
        dates.append(when)

    # Newest source item (first in the file) gets the most recent date.
    span = dt.timedelta(days=WINDOW_DAYS) - dt.timedelta(hours=TOP_OFFSET_HOURS)
    step = span / max(len(stale) - 1, 1)
    new_blocks = list(blocks)
    for rank, i in enumerate(stale):
        dates[i] = now - dt.timedelta(hours=TOP_OFFSET_HOURS) - step * rank
        new_blocks[i] = PUBDATE_RE.sub(f"<pubDate>{format_datetime(dates[i])}</pubDate>", blocks[i], count=1)

    # Keep the file date-descending: re-dated items on top, skipped Hindi
    # items (old real dates) at the bottom.
    order = sorted(range(len(blocks)), key=lambda i: dates[i], reverse=True)
    xml = xml[: spans[0].start()] + "\n".join(new_blocks[i] for i in order) + xml[spans[-1].end():]

    with open(path, "w", encoding="utf-8") as f:
        f.write(xml)
    print(
        f"{key}: {len(blocks)} items, re-dated {len(stale)}, "
        f"kept {kept}, hindi skipped {hindi}"
    )


def main() -> int:
    now = dt.datetime.now(IST)
    for key in KEYS:
        stagger(key, now)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
