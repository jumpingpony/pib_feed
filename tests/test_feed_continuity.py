#!/usr/bin/env python3
"""Continuity and gap detection tests for generated RSS feeds."""
from __future__ import annotations

import datetime as dt
import email.utils
import enum
import json
import os
import unittest
import xml.etree.ElementTree as ET

PUBLIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "public"))
INTENTIONAL_GAPS_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "intentional_gaps.json"))

MAX_GAP_DAILY_DAYS = 3
MAX_GAP_WEEKLY_DAYS = 10
MAX_GAP_MONTHLY_DAYS = 45


class Cadence(enum.Enum):
    DAILY = 1
    WEEKLY = 2
    MONTHLY = 3
    SEASONAL = 4


FEED_CADENCE = {
    "press_releases": Cadence.DAILY,
    "newsonair": Cadence.DAILY,
    "indianexpress-opinion": Cadence.DAILY,
    "indianexpress-explained": Cadence.DAILY,
    "indianexpress-delhi": Cadence.DAILY,
    "project-syndicate": Cadence.DAILY,
    "pmo": Cadence.DAILY,
    "madeeasy-weekly": Cadence.WEEKLY,
    "indiatoday_magazine": Cadence.WEEKLY,
    "economist-business": Cadence.WEEKLY,
    "economist-finance-and-economics": Cadence.WEEKLY,
    "economist-by-invitation": Cadence.WEEKLY,
    "economist-indicators": Cadence.MONTHLY,
    "ipcs-commentaries": Cadence.SEASONAL,
    "frontline_blog": Cadence.WEEKLY,
    "idsa-comments": Cadence.MONTHLY,
    "nextias-magazine": Cadence.MONTHLY,
    "frontline_magazine": Cadence.MONTHLY,
    "scobserver_cases": Cadence.SEASONAL,
    "scobserver-journal": Cadence.MONTHLY,
    "scobserver-reports": Cadence.SEASONAL,
    "niti-reports": Cadence.SEASONAL,
    "niti-policy-papers": Cadence.SEASONAL,
    "niti-research-papers": Cadence.SEASONAL,
    "niti-working-papers": Cadence.SEASONAL,
    "niti-annual-reports": Cadence.SEASONAL,
    "eacpm-reports": Cadence.SEASONAL,
    "prs-budgets": Cadence.SEASONAL,
    "prs-acts": Cadence.SEASONAL,
    "prs-bills": Cadence.SEASONAL,
    "mygov_mannkibaat": Cadence.SEASONAL,
    "mygov_pulse": Cadence.SEASONAL,
    "mygov_bharat_matters": Cadence.SEASONAL,
    "backgrounders": Cadence.SEASONAL,
    "faqs": Cadence.SEASONAL,
    "features": Cadence.SEASONAL,
    "factsheets": Cadence.SEASONAL,
    "idsa-issue-briefs": Cadence.SEASONAL,
    "idsa-monographs": Cadence.SEASONAL,
    "idsa-backgrounders": Cadence.SEASONAL,
    "indiasworld": Cadence.SEASONAL,
    "visionias-pt-365": Cadence.SEASONAL,
    "visionias-mains-365": Cadence.SEASONAL,
    "upsc-essentials": Cadence.MONTHLY,
}


def load_gaps() -> dict[str, list[tuple[str, str]]]:
    """Load intentional approved gap ranges from JSON config."""
    if not os.path.exists(INTENTIONAL_GAPS_FILE):
        return {}

    with open(INTENTIONAL_GAPS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_pubdate(text: str) -> dt.datetime:
    """Parse standard RFC 822 / 2822 date from RSS pubDate element."""
    parsed = email.utils.parsedate_to_datetime(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)

    return parsed.astimezone(dt.timezone.utc)


def max_gap_days(cadence: Cadence) -> int | None:
    """Determine maximum allowed interval gap for feed cadence."""
    if cadence == Cadence.DAILY:
        return MAX_GAP_DAILY_DAYS

    if cadence == Cadence.WEEKLY:
        return MAX_GAP_WEEKLY_DAYS

    if cadence == Cadence.MONTHLY:
        return MAX_GAP_MONTHLY_DAYS

    return None


class TestFeedContinuity(unittest.TestCase):
    def setUp(self):
        self.intentional_gaps = load_gaps()

    def test_all_generated_feeds(self):
        """Audit all generated feeds for valid XML, non-emptiness, and continuity."""
        if not os.path.exists(PUBLIC_DIR):
            self.skipTest("Public directory does not exist yet")

        feed_dirs = [
            d for d in os.listdir(PUBLIC_DIR)
            if os.path.isdir(os.path.join(PUBLIC_DIR, d)) and os.path.exists(os.path.join(PUBLIC_DIR, d, "feed.xml"))
        ]

        if not feed_dirs:
            self.skipTest("No feed.xml files found in public directory")

        for feed_key in sorted(feed_dirs):
            with self.subTest(feed=feed_key):
                feed_path = os.path.join(PUBLIC_DIR, feed_key, "feed.xml")
                self.assertGreater(os.path.getsize(feed_path), 0, f"Feed {feed_key} is empty")

                # Parse XML
                tree = ET.parse(feed_path)
                root = tree.getroot()
                channel = root.find("channel")
                self.assertIsNotNone(channel, f"Feed {feed_key} missing channel")

                items = channel.findall("item")
                self.assertGreater(len(items), 0, f"Feed {feed_key} contains zero items")

                dates: list[dt.datetime] = []
                for item in items:
                    pub_date = item.findtext("pubDate")
                    self.assertIsNotNone(pub_date, f"Item missing pubDate in {feed_key}")
                    dates.append(parse_pubdate(pub_date))

                # Reverse-chronological check
                for i in range(len(dates) - 1):
                    self.assertGreaterEqual(
                        dates[i],
                        dates[i + 1],
                        f"Items out of reverse-chronological order in {feed_key}: {dates[i]} < {dates[i+1]}",
                    )

                # Cadence gap check
                cadence = FEED_CADENCE.get(feed_key, Cadence.MONTHLY)
                limit_days = max_gap_days(cadence)
                if limit_days is None or len(dates) < 2:
                    continue

                for i in range(len(dates) - 1):
                    gap_days = (dates[i] - dates[i + 1]).total_seconds() / 86400.0
                    if gap_days <= limit_days:
                        continue

                    # Check intentional gaps
                    d_from = dates[i + 1].strftime("%Y-%m-%d")
                    d_to = dates[i].strftime("%Y-%m-%d")
                    is_whitelisted = False
                    for allowed_start, allowed_end in self.intentional_gaps.get(feed_key, []):
                        if allowed_start <= d_from and d_to <= allowed_end:
                            is_whitelisted = True
                            break

                    self.assertTrue(
                        is_whitelisted,
                        f"Unapproved gap in {feed_key}: {gap_days:.1f} days between {d_from} and {d_to}",
                    )


if __name__ == "__main__":
    unittest.main()
