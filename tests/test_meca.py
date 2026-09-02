#!/usr/bin/env python3
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import meca

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


class TestMecaNextias(unittest.TestCase):
    def test_distinct_ids_for_standard_and_crux(self):
        """Ensure standard and Crux editions in the same month have distinct IDs and do not collide."""
        art_std = {
            "id": 2024110,
            "title": "Monthly Current Affairs — November 2024",
            "date": dt.datetime(2024, 11, 1, tzinfo=IST),
            "link": "https://example.com/nov-2024.pdf",
            "pdf": "https://example.com/nov-2024.pdf",
            "archival_name": "nextias_monthly-current-affairs_2024-11.pdf",
        }
        art_crux = {
            "id": 2024111,
            "title": "Monthly Current Affairs — November 2024 (The Crux)",
            "date": dt.datetime(2024, 11, 15, tzinfo=IST),
            "link": "https://example.com/nov-2024-crux.pdf",
            "pdf": "https://example.com/nov-2024-crux.pdf",
            "archival_name": "nextias_monthly-current-affairs_2024-11_crux.pdf",
        }

        # Mock items in feed building
        feed = meca.FEEDS[1]  # nextias-magazine
        items = {
            art_std["id"]: meca.render_item(feed["key"], art_std).strip(),
            art_crux["id"]: meca.render_item(feed["key"], art_crux).strip(),
        }

        # Ensure both items exist in feed and build_feed keeps both
        self.assertEqual(len(items), 2, "Items must not overwrite each other")
        xml = meca.build_feed(feed, items)
        self.assertIn("Monthly Current Affairs — November 2024</title>", xml)
        self.assertIn("Monthly Current Affairs — November 2024 (The Crux)</title>", xml)

    def test_legacy_guid_id_normalization(self):
        """Ensure 6-digit legacy NextIAS IDs normalize to distinct 7-digit IDs."""
        std_xml = """<item>
          <title>Monthly Current Affairs — November 2024</title>
          <guid isPermaLink="false">urn:meca:nextias-magazine:202411</guid>
        </item>"""
        crux_xml = """<item>
          <title>Monthly Current Affairs — December 2024 (The Crux)</title>
          <guid isPermaLink="false">urn:meca:nextias-magazine:202412</guid>
        </item>"""

        self.assertEqual(meca._guid_id(std_xml), 2024110)
        self.assertEqual(meca._guid_id(crux_xml), 2024121)


if __name__ == "__main__":
    unittest.main()
