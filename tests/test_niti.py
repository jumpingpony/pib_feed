#!/usr/bin/env python3
"""NITI Aayog: archival names and release links."""
import datetime as dt
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from feeds import niti

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
BASE = "https://github.com/jumpingpony/pib_feed/releases/download/niti-{year}"

ARTICLE = {
    "title": "Working Paper 2026",
    "date": dt.datetime(2026, 1, 10, tzinfo=IST),
    "pdf": "https://www.niti.gov.in/sites/default/files/2026-01/WP_2026.pdf",
    "category": "Health",
    "author": "NITI",
}


class TestArchivalNames(unittest.TestCase):
    def test_name_keeps_the_source_folder(self):
        # The month folder disambiguates same-named PDFs across months.
        path = "sites/default/files/2026-01/NITI_WORKING_PAPER_Report.pdf"
        self.assertEqual(niti.archival_name(path), "niti_2026-01_NITI_WORKING_PAPER_Report.pdf")


class TestArchiveUrls(unittest.TestCase):
    def test_release_tag_and_link_follow_the_item_year(self):
        with patch.object(niti, "ARCHIVE_MODE", "archive"), patch.object(
            niti, "ARCHIVE_BASE_URL", BASE
        ):
            self.assertEqual(niti.archive_tag_for(ARTICLE), "niti-2026")
            self.assertEqual(
                niti.item_link(ARTICLE),
                "https://github.com/jumpingpony/pib_feed/releases/download/niti-2026/"
                + niti.archival_name_of(ARTICLE),
            )

    def test_link_mode_keeps_the_source_pdf(self):
        with patch.object(niti, "ARCHIVE_MODE", "link"):
            self.assertEqual(niti.item_link(ARTICLE), ARTICLE["pdf"])


if __name__ == "__main__":
    unittest.main()
