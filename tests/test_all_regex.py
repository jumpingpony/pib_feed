#!/usr/bin/env python3
import datetime as dt
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import archive_pdfs
import economist
import ie_epaper
import meca
import mygov
import niti
from scripts.backfill_releases import classify_asset, get_existing_assets, release_title
import visioniaspt365

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


class TestRegexImplementations(unittest.TestCase):
    def test_mygov_slug_and_archival_name_regex(self):
        art_pulse = {
            "id": 1234567890,
            "title": "Good Governance Pathway 2026 and Viksit Bharat 2047",
            "date": dt.datetime(2026, 1, 8, tzinfo=IST),
            "link": "https://www.mygov.in/pulse/good-governance-pathway-2026-and-viksit-bharat-2047",
            "pdf": "https://static.mygov.in/pdf1.pdf",
        }
        name = mygov.archival_name("mygov_pulse", art_pulse)
        self.assertEqual(name, "mygov_pulse_2026-01-08_good-governance-pathway-2026-and-viksit-bharat-2047.pdf")
        self.assertEqual(classify_asset(name), "mygov-2026")

        art_nep2020 = {
            "id": 1234567891,
            "title": "5 Years NEP 2020",
            "date": dt.datetime(2025, 8, 21, tzinfo=IST),
            "link": "https://www.mygov.in/pulse/5-years-nep-2020",
            "pdf": "https://static.mygov.in/pdf2.pdf",
        }
        name_nep = mygov.archival_name("mygov_pulse", art_nep2020)
        self.assertEqual(name_nep, "mygov_pulse_2025-08-21_5-years-nep-2020.pdf")
        self.assertEqual(classify_asset(name_nep), "mygov-2025")

    def test_niti_archival_name_regex(self):
        path = "sites/default/files/2026-01/NITI_WORKING_PAPER_Report.pdf"
        name = niti.archival_name(path)
        self.assertEqual(name, "niti_2026-01_NITI_WORKING_PAPER_Report.pdf")
        self.assertEqual(classify_asset(name), "niti-2026")

    def test_ie_epaper_archival_name_and_repo_regex(self):
        base_url = "https://github.com/jumpingpony/pib_feed/releases/download/{feed}-{year}"
        ie_epaper.ARCHIVE_BASE_URL = base_url
        match = re.search(r"github\.com/([^/]+/[^/]+)/releases/download", base_url)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "jumpingpony/pib_feed")

        feed_delhi = {"key": "indianexpress-delhi"}
        art_delhi = {
            "id": 100,
            "title": "Delhi Edition",
            "date": dt.datetime(2026, 8, 22, tzinfo=IST),
            "archival_name": "indianexpress-delhi_2026-08-22.pdf",
        }
        self.assertEqual(ie_epaper.archive_tag_for(feed_delhi, art_delhi), "indianexpress-delhi")
        self.assertEqual(classify_asset(art_delhi["archival_name"]), "indianexpress-delhi")

    def test_visionias_and_meca_regex(self):
        vis_name = "visionias_pt-365_2026_pt-365-culture_13229.pdf"
        self.assertEqual(classify_asset(vis_name), "visionias-pt365-2026")

        mains_name = "visionias_mains-365_2025_mains-365-economy_9868.pdf"
        self.assertEqual(classify_asset(mains_name), "visionias-mains365-2025")

        meca_name = "madeeasy_weekly_2026-01-15_current_affairs.pdf"
        self.assertEqual(classify_asset(meca_name), "madeeasy-weekly-2026")

        nextias_name = "nextias_monthly-current-affairs_2026-03_crux.pdf"
        self.assertEqual(classify_asset(nextias_name), "nextias-magazine-2026")

    def test_archive_pdfs_marker_regex(self):
        sample_xml = """<item>
            <title>Test Item</title>
            <link>https://github.com/jumpingpony/pib_feed/releases/download/mygov-2026/mygov_pulse_2026-01-08_test.pdf</link>
            <enclosure url="https://github.com/jumpingpony/pib_feed/releases/download/indianexpress-delhi/indianexpress-delhi_2026-08-22.pdf" type="application/pdf" />
        </item>"""
        marker = re.compile(r"/releases/download/([^/\s<>'\"?#]+)/([^/\s<>'\"?#]+)", re.I)
        matches = [(m.group(1), m.group(2)) for m in marker.finditer(sample_xml)]
        self.assertEqual(len(matches), 2)
        self.assertEqual(matches[0], ("mygov-2026", "mygov_pulse_2026-01-08_test.pdf"))
        self.assertEqual(matches[1], ("indianexpress-delhi", "indianexpress-delhi_2026-08-22.pdf"))

    def test_asset_classification(self):
        """Test classification of asset names into partitioned release tags."""
        sample_assets = [
            ("niti_2026-07_Investment-Friendliness-Index.pdf", "niti-2026"),
            ("upsc-essentials_2026-01-13.pdf", "upsc-essentials-2026"),
            ("visionias_mains-365_2025_key-data-facts_9754.pdf", "visionias-mains365-2025"),
            ("visionias_pt-365_2026_pt-365-culture_13229.pdf", "visionias-pt365-2026"),
            ("chart_1.jpg", "economist-images-2026"),
            ("indianexpress-eye_2026.pdf", None),
        ]
        for name, expected in sample_assets:
            self.assertEqual(classify_asset(name), expected)


if __name__ == "__main__":
    unittest.main()
