#!/usr/bin/env python3
"""Indian Express epaper: release links, partitioned tags, rolling window."""
import datetime as dt
import os
import re
import sys
import unittest
from email.utils import format_datetime
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from feeds import ie_epaper

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
BASE = "https://github.com/jumpingpony/pib_feed/releases/download/{feed}-{year}"


def delhi_feed() -> dict:
    return next(feed for feed in ie_epaper.FEEDS if feed["key"] == "indianexpress-delhi")


class TestArchiveUrls(unittest.TestCase):
    def test_issue_link_targets_the_release_asset(self):
        article = {
            "id": 1001,
            "title": "Delhi Edition",
            "date": dt.datetime(2026, 6, 15, tzinfo=IST),
            "archival_name": "indianexpress-delhi_2026-06-15.pdf",
        }
        with patch.object(ie_epaper, "ARCHIVE_MODE", "archive"), patch.object(
            ie_epaper, "ARCHIVE_BASE_URL", BASE
        ):
            self.assertEqual(ie_epaper.archive_tag_for(delhi_feed(), article), "indianexpress-delhi")
            self.assertEqual(
                ie_epaper.item_pdf_url(delhi_feed(), article),
                "https://github.com/jumpingpony/pib_feed/releases/download/indianexpress-delhi/"
                "indianexpress-delhi_2026-06-15.pdf",
            )


class TestArchiveTags(unittest.TestCase):
    def test_delhi_stays_unpartitioned(self):
        # Delhi is a rolling daily release; the titles are partitioned by year.
        year = dt.datetime.now(IST).year
        with patch.object(ie_epaper, "ARCHIVE_BASE_URL", BASE):
            tags = ie_epaper.archive_tags_to_check()

        self.assertIn("indianexpress-delhi", tags)
        self.assertNotIn(f"indianexpress-delhi-{year}", tags)
        self.assertIn(f"upsc-essentials-{year}", tags)
        self.assertIn(f"upsc-essentials-{year - 1}", tags)


class TestRollingWindow(unittest.TestCase):
    def test_window_rolls_but_a_static_floor_does_not(self):
        today = dt.datetime.now(IST).date()
        delhi = delhi_feed()
        window = dt.timedelta(days=ie_epaper.DELHI_WINDOW_DAYS)

        self.assertEqual(
            ie_epaper.min_date_for(delhi),
            max(delhi["min_date"], (today - window).isoformat()),
        )
        self.assertEqual(
            ie_epaper.min_date_for({"window_days": 10}),
            (today - dt.timedelta(days=10)).isoformat(),
        )
        self.assertEqual(ie_epaper.min_date_for({"min_date": "2025-05-01"}), "2025-05-01")


class TestOrdering(unittest.TestCase):
    def test_a_higher_id_with_an_earlier_stamp_keeps_chronology(self):
        # What broke the 2026-11-03 build: a new issue (4217181, 03:51) arrived
        # while the issue already stored below it (4217073) still carried an
        # earlier stamp of 03:59, so descending-id order inverted the pair.
        stamped_later = {
            "id": 4217073,
            "date": dt.datetime(2026, 11, 3, 3, 59, tzinfo=IST),
            "title": "Delhi — November 3, 2026",
            "reader": "https://epaper.indianexpress.com/r/4217073",
            "archival_name": "indianexpress-delhi_2026-11-03.pdf",
        }
        higher_id = {
            **stamped_later,
            "id": 4217181,
            "date": dt.datetime(2026, 11, 3, 3, 51, tzinfo=IST),
            "reader": "https://epaper.indianexpress.com/r/4217181",
        }
        items = {
            4217181: ie_epaper.render_item(delhi_feed(), higher_id),
            4217073: ie_epaper.render_item(delhi_feed(), stamped_later),
        }
        with patch.object(ie_epaper, "ARCHIVE_MODE", "link"):
            xml = ie_epaper.build_feed(delhi_feed(), items)

        self.assertEqual(
            re.findall(r"<pubDate>([^<]+)</pubDate>", xml),
            [format_datetime(stamped_later["date"]), format_datetime(higher_id["date"])],
        )


if __name__ == "__main__":
    unittest.main()
