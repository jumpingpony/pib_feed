#!/usr/bin/env python3
"""Made Easy and NextIAS: edition ids, crux detection, release links."""
import datetime as dt
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from feeds import meca

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
BASE = "https://github.com/jumpingpony/pib_feed/releases/download/{feed}-{year}"

STANDARD = {
    "id": 2024110,
    "title": "Monthly Current Affairs — November 2024",
    "date": dt.datetime(2024, 11, 1, tzinfo=IST),
    "link": "https://example.com/nov-2024.pdf",
    "pdf": "https://example.com/nov-2024.pdf",
    "archival_name": "nextias_monthly-current-affairs_2024-11.pdf",
}
CRUX = {
    "id": 2024111,
    "title": "Monthly Current Affairs — November 2024 (The Crux)",
    "date": dt.datetime(2024, 11, 15, tzinfo=IST),
    "link": "https://example.com/nov-2024-crux.pdf",
    "pdf": "https://example.com/nov-2024-crux.pdf",
    "archival_name": "nextias_monthly-current-affairs_2024-11_crux.pdf",
}


def nextias_feed() -> dict:
    return next(feed for feed in meca.FEEDS if feed["key"] == "nextias-magazine")


class TestArchiveUrls(unittest.TestCase):
    def test_release_link_follows_edition_year(self):
        with patch.object(meca, "ARCHIVE_MODE", "archive"), patch.object(
            meca, "ARCHIVE_BASE_URL", BASE
        ):
            self.assertEqual(meca.archive_tag_for("madeeasy-weekly", STANDARD), "madeeasy-weekly-2024")
            self.assertEqual(
                meca.item_pdf_url("madeeasy-weekly", STANDARD),
                "https://github.com/jumpingpony/pib_feed/releases/download/madeeasy-weekly-2024/"
                + STANDARD["archival_name"],
            )


class TestEditionIds(unittest.TestCase):
    def test_standard_and_crux_editions_do_not_collide(self):
        feed = nextias_feed()
        items = {
            STANDARD["id"]: meca.render_item(feed["key"], STANDARD).strip(),
            CRUX["id"]: meca.render_item(feed["key"], CRUX).strip(),
        }

        self.assertEqual(len(items), 2, "items must not overwrite each other")
        xml = meca.build_feed(feed, items)
        self.assertIn("Monthly Current Affairs — November 2024</title>", xml)
        self.assertIn("Monthly Current Affairs — November 2024 (The Crux)</title>", xml)

    def test_six_digit_guids_normalize_to_distinct_ids(self):
        standard_xml = """<item>
          <title>Monthly Current Affairs — November 2024</title>
          <guid isPermaLink="false">urn:meca:nextias-magazine:202411</guid>
        </item>"""
        crux_xml = """<item>
          <title>Monthly Current Affairs — December 2024 (The Crux)</title>
          <guid isPermaLink="false">urn:meca:nextias-magazine:202412</guid>
        </item>"""

        self.assertEqual(meca._guid_id(standard_xml), 2024110)
        self.assertEqual(meca._guid_id(crux_xml), 2024121)

    def test_untitled_august_issue_is_detected_as_crux(self):
        # The August 2026 edition ships without "(THE CRUX)" in the listing
        # title; the month itself marks it.
        record = {
            "title": "August, 2026",
            "pdf": "https://www.nextias.com/magazines/monthly-current-affairs-august-2026.pdf",
        }
        pages = {(2026, 0): [record]}
        with patch.object(
            meca, "_nx_page", side_effect=lambda session, year, start: pages.get((year, start), [])
        ):
            articles = meca.collect_nextias(None, newest_id=0)

        self.assertEqual(len(articles), 1)
        article = articles[0]
        self.assertEqual(article["id"], 2026081)
        self.assertEqual(article["title"], "Monthly Current Affairs — August 2026 (The Crux)")
        self.assertEqual(article["archival_name"], "nextias_monthly-current-affairs_2026-08_crux.pdf")
        self.assertEqual(article["date"].day, 15)


if __name__ == "__main__":
    unittest.main()
