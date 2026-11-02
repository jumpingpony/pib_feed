#!/usr/bin/env python3
"""Audit the generated site: parseable, non-empty, newest-first, no silent gaps.

A builder break rarely shows up as a traceback. It shows up as a feed that still
parses and still serves, but stopped growing three weeks ago. The builders cannot
see the deployed tree, so this runs against ``public/`` after every build and
fails the run when a rule breaks.

Rules per feed directory:

- ``feed.xml`` exists, is non-empty, parses, and has a ``<channel>``.
- The channel carries at least one ``<item>``, each with a valid ``<pubDate>``.
- Items are in reverse-chronological order.
- The newest item is no older than the feed's cadence allows, so a feed that
  silently stopped publishing is caught.
- No interval between consecutive items published in the last
  ``AUDIT_HISTORY_DAYS`` (default 120) exceeds the feed's cadence limit, unless
  ``.github/known-feed-gaps.json`` lists that range as accepted. Older gaps come
  from backfilled archives and are not checked.

Feeds absent from ``FEED_CADENCE`` are checked as monthly: lenient, because a
wrong guess here fails a healthy build.

Usage:
    python tools/audit_feeds.py
    AUDIT_OUT_DIR=/tmp/site AUDIT_GAPS=/tmp/gaps.json python tools/audit_feeds.py
"""
from __future__ import annotations

import datetime as dt
import email.utils
import json
import os
import sys
import xml.etree.ElementTree as ET

OUT_DIR = os.environ.get("AUDIT_OUT_DIR", "public")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAPS_PATH = os.environ.get(
    "AUDIT_GAPS", os.path.join(REPO_ROOT, ".github", "known-feed-gaps.json")
)

# Cadence name -> longest accepted interval between consecutive items. SEASONAL
# feeds have no limit: their publication schedules are genuinely irregular.
CADENCE_LIMIT_DAYS = {
    "DAILY": 3,
    "WEEKLY": 10,
    "MONTHLY": 45,
}
# How old the newest item may be. Deliberately looser than the gap limit: the
# tail runs from the last post to now, and a build at 09:00 already looks a day
# old, while a long weekend or a source-side pause must not fail the build.
FRESH_LIMIT_DAYS = {
    "DAILY": 7,
    "WEEKLY": 21,
    "MONTHLY": 60,
}
DEFAULT_CADENCE = "MONTHLY"

# Gap checks cover only the recent tail. Every builder merges years of published
# history, and a backfilled archive has holes where the builder never reached;
# those say nothing about whether the source is alive today.
HISTORY_DAYS = int(os.environ.get("AUDIT_HISTORY_DAYS", "120"))

FEED_CADENCE = {
    "press_releases": "DAILY",
    "newsonair": "DAILY",
    "indianexpress-opinion": "DAILY",
    "indianexpress-explained": "DAILY",
    "indianexpress-delhi": "DAILY",
    "pmo": "DAILY",
    "madeeasy-weekly": "WEEKLY",
    "indiatoday_magazine": "WEEKLY",
    "ipcs-commentaries": "SEASONAL",
    "frontline_blog": "SEASONAL",
    "idsa-comments": "MONTHLY",
    "nextias-magazine": "MONTHLY",
    "frontline_magazine": "MONTHLY",
    # Podcast releases come in seasons: daily inside a run, silent for months.
    "ecnmst-podcasts": "SEASONAL",
    "scobserver_cases": "SEASONAL",
    "scobserver-journal-full": "MONTHLY",
    "scobserver-reports-full": "SEASONAL",
    "niti_reports": "SEASONAL",
    "niti_policy-papers": "SEASONAL",
    "niti_research-papers": "SEASONAL",
    "niti_working-papers": "SEASONAL",
    "niti_annual-reports": "SEASONAL",
    "eacpm-reports": "SEASONAL",
    "prs-budgets": "SEASONAL",
    "prs-acts": "SEASONAL",
    "prs-bills": "SEASONAL",
    "mygov_mannkibaat": "SEASONAL",
    "mygov_pulsenewsletter": "SEASONAL",
    "mygov_bharatmatters": "SEASONAL",
    "backgrounders": "SEASONAL",
    "faqs": "SEASONAL",
    "features": "SEASONAL",
    "factsheets": "SEASONAL",
    "idsa-issue-briefs": "SEASONAL",
    "idsa-monographs": "SEASONAL",
    "idsa-backgrounders": "SEASONAL",
    "indiasworld": "SEASONAL",
    "visionias_pt-365": "SEASONAL",
    "visionias_mains-365": "SEASONAL",
    "upsc-essentials": "MONTHLY",
}


def parse_pubdate(text: str) -> dt.datetime:
    """RFC 822 pubDate as an aware UTC datetime; naive values are read as UTC."""
    parsed = email.utils.parsedate_to_datetime(text)
    if parsed is None:
        raise ValueError(f"unparseable pubDate: {text!r}")
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def load_gaps(path: str = GAPS_PATH) -> dict[str, list[tuple[str, str]]]:
    """Accepted gap ranges per feed, as `{feed_key: [[start, end], ...]}`."""
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return {key: [tuple(pair) for pair in ranges] for key, ranges in raw.items()}


def gap_is_accepted(key: str, start: str, end: str, gaps: dict) -> bool:
    """True when a start..end range falls inside one accepted range for the feed."""
    return any(
        allowed_start <= start and end <= allowed_end
        for allowed_start, allowed_end in gaps.get(key, [])
    )


def audit_feed(key: str, path: str, gaps: dict, now: dt.datetime | None = None) -> list[str]:
    """Violations for one feed.xml; an empty list means the feed is healthy."""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return [f"{key}: feed.xml is missing or empty"]

    try:
        channel = ET.parse(path).getroot().find("channel")
    except ET.ParseError as exc:
        return [f"{key}: feed.xml does not parse ({exc})"]
    if channel is None:
        return [f"{key}: feed.xml has no <channel>"]

    items = channel.findall("item")
    if not items:
        return [f"{key}: feed has no items"]

    problems: list[str] = []
    dates: list[dt.datetime] = []
    for item in items:
        raw = item.findtext("pubDate")
        if not raw:
            problems.append(f"{key}: item without <pubDate>")
            continue
        try:
            dates.append(parse_pubdate(raw))
        except (TypeError, ValueError):
            problems.append(f"{key}: unparseable pubDate {raw!r}")

    if problems:
        return problems

    for newer, older in zip(dates, dates[1:]):
        if newer < older:
            problems.append(f"{key}: items out of order at {newer} -> {older}")

    cadence = FEED_CADENCE.get(key, DEFAULT_CADENCE)
    limit = CADENCE_LIMIT_DAYS.get(cadence)
    if limit is None:
        return problems

    # A feed that stopped publishing still parses and still has evenly spaced
    # items, so freshness is checked separately from the gaps between them.
    now = now or dt.datetime.now(dt.timezone.utc)
    age_days = (now - dates[0]).total_seconds() / 86400.0
    fresh_limit = FRESH_LIMIT_DAYS[cadence]
    if age_days > fresh_limit:
        problems.append(
            f"{key}: newest item is {age_days:.0f} days old, over the "
            f"{fresh_limit}-day {cadence} freshness limit"
        )

    # Gaps only matter between items that are actually in the file, and only for
    # the recent tail: a backfilled archive's holes predate the feed and cannot
    # be fixed by a rebuild.
    recent = [when for when in dates if (now - when).days <= HISTORY_DAYS]
    for newer, older in zip(recent, recent[1:]):
        gap_days = (newer - older).total_seconds() / 86400.0
        if gap_days <= limit:
            continue
        start, end = older.strftime("%Y-%m-%d"), newer.strftime("%Y-%m-%d")
        if gap_is_accepted(key, start, end, gaps):
            continue
        problems.append(
            f"{key}: {gap_days:.1f} day gap between {start} and {end} "
            f"exceeds the {limit}-day {cadence} limit"
        )

    return problems


def audit(out_dir: str = OUT_DIR, gaps: dict | None = None, now: dt.datetime | None = None) -> list[str]:
    """Violations for every feed directory in out_dir; empty means healthy."""
    if gaps is None:
        gaps = load_gaps()
    if not os.path.isdir(out_dir):
        return [f"{out_dir}: directory does not exist"]

    keys = sorted(
        entry
        for entry in os.listdir(out_dir)
        if os.path.exists(os.path.join(out_dir, entry, "feed.xml"))
    )
    if not keys:
        return [f"{out_dir}: no feed.xml files found"]

    problems: list[str] = []
    for key in keys:
        problems.extend(audit_feed(key, os.path.join(out_dir, key, "feed.xml"), gaps, now))
    return problems


def main() -> int:
    problems = audit()
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"feed audit failed: {len(problems)} problem(s)", file=sys.stderr)
        return 1
    print("feed audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
