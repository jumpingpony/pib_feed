#!/usr/bin/env python3
"""Stagger historical feed dates for initial Inoreader archive ingestion."""
from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import enum
import os
import re
import sys
import xml.etree.ElementTree as ET

PUBLIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "public"))
DAYS_WINDOW = 7
SPACING_MINUTES = 5

UNSTAGGERED_FEEDS = {
    "press_releases",
    "indianexpress-delhi",
    "newsonair",
    "backgrounders",
    "faqs",
    "pmo",
    "features",
    "factsheets",
    "economist-indicators",
    "project-syndicate",
    "ipcs-commentaries",
}


class Mode(enum.Enum):
    DRY_RUN = 1
    APPLY = 2


def parse_date(date_str: str) -> dt.datetime:
    """Parse RFC 822 / 2822 datetime."""
    parsed = email.utils.parsedate_to_datetime(date_str)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)

    return parsed.astimezone(dt.timezone.utc)


def format_date(when: dt.datetime) -> str:
    """Format RFC 822 datetime for RSS pubDate."""
    return email.utils.format_datetime(when)


def prepend_banner(item: ET.Element, orig_date_str: str) -> None:
    """Prepend original publication date banner to description and content:encoded."""
    banner = f'<p class="feed-orig-date"><strong>Original Publication Date:</strong> {orig_date_str}</p>\n'

    # Update description
    desc_elem = item.find("description")
    if desc_elem is not None and desc_elem.text:
        if "feed-orig-date" not in desc_elem.text:
            desc_elem.text = banner + desc_elem.text

    # Update content:encoded if present
    content_elem = item.find("{http://purl.org/rss/1.0/modules/content/}encoded")
    if content_elem is not None and content_elem.text:
        if "feed-orig-date" not in content_elem.text:
            content_elem.text = banner + content_elem.text


def stagger_feed(feed_key: str, now: dt.datetime, mode: Mode) -> int:
    """Stagger publication dates within the last 7 days in chronological order."""
    feed_file = os.path.join(PUBLIC_DIR, feed_key, "feed.xml")
    if not os.path.exists(feed_file):
        return 0

    if feed_key in UNSTAGGERED_FEEDS:
        print(f"[{feed_key}] Skipping (configured as un-staggered real dates)")
        return 0

    ET.register_namespace("content", "http://purl.org/rss/1.0/modules/content/")
    ET.register_namespace("atom", "http://www.w3.org/2005/Atom")

    tree = ET.parse(feed_file)
    root = tree.getroot()
    channel = root.find("channel")
    if channel is None:
        return 0

    items = channel.findall("item")
    if not items:
        return 0

    parsed_items: list[tuple[dt.datetime, ET.Element]] = []
    for it in items:
        pub_elem = it.find("pubDate")
        if pub_elem is not None and pub_elem.text:
            parsed_items.append((parse_date(pub_elem.text), it))

    # Sort oldest first to assign advancing timestamps
    parsed_items.sort(key=lambda x: x[0])
    count = len(parsed_items)

    start_window = now - dt.timedelta(days=DAYS_WINDOW - 1)
    slot_seconds = (DAYS_WINDOW * 86400 * 0.85) / max(1, count)

    staggered_count = 0
    for idx, (orig_dt, it) in enumerate(parsed_items):
        orig_date_str = orig_dt.strftime("%Y-%m-%d")
        prepend_banner(it, orig_date_str)

        new_dt = start_window + dt.timedelta(seconds=idx * slot_seconds)
        pub_elem = it.find("pubDate")
        if pub_elem is not None:
            pub_elem.text = format_date(new_dt)
            staggered_count += 1

    print(f"[{feed_key}] Staggered {staggered_count} items across last {DAYS_WINDOW} days")

    if mode == Mode.APPLY:
        # Re-sort channel items newest-first for standard RSS ordering
        for it in items:
            channel.remove(it)

        parsed_items.sort(key=lambda x: parse_date(x[1].findtext("pubDate", "")), reverse=True)
        for _, it in parsed_items:
            channel.append(it)

        tree.write(feed_file, encoding="utf-8", xml_declaration=True)

    return staggered_count


def main():
    parser = argparse.ArgumentParser(description="Stagger feed publication dates for Inoreader")
    parser.add_argument("--feed", help="Specific feed key to stagger")
    parser.add_argument("--all", action="store_true", help="Stagger all applicable feeds in public/")
    parser.add_argument("--dry-run", action="store_true", help="Inspect without modifying files")
    args = parser.parse_args()

    mode = Mode.DRY_RUN if args.dry_run else Mode.APPLY
    now = dt.datetime.now(dt.timezone.utc)

    if not os.path.exists(PUBLIC_DIR):
        print(f"Public directory not found at {PUBLIC_DIR}", file=sys.stderr)
        sys.exit(1)

    if args.feed:
        stagger_feed(args.feed, now, mode)
    elif args.all:
        feed_keys = sorted([
            d for d in os.listdir(PUBLIC_DIR)
            if os.path.isdir(os.path.join(PUBLIC_DIR, d)) and os.path.exists(os.path.join(PUBLIC_DIR, d, "feed.xml"))
        ])
        for key in feed_keys:
            stagger_feed(key, now, mode)
    else:
        print("Specify --feed <key> or --all", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
