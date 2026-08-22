#!/usr/bin/env python3
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import economist
import ie_epaper
import meca
import mygov
import niti
import visioniaspt365

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


class TestBuildersUrlTemplating(unittest.TestCase):
    def test_mygov_templating(self):
        mygov.ARCHIVE_MODE = "archive"
        mygov.ARCHIVE_BASE_URL = "https://github.com/nappingcats/pib_feed/releases/download/mygov-{year}"

        art_2024 = {
            "id": 1,
            "title": "Booklet 2024",
            "date": dt.datetime(2024, 6, 1, tzinfo=IST),
            "pdf": "https://static.mygov.in/mygov_1717200000_abc.pdf",
            "link": "https://www.mygov.in/bharat-matters-2024",
        }
        art_2026 = {
            "id": 2,
            "title": "Pulse 2026",
            "date": dt.datetime(2026, 3, 15, tzinfo=IST),
            "pdf": "https://static.mygov.in/mygov_1773500000_def.pdf",
            "link": "https://www.mygov.in/pulse-2026",
        }

        self.assertEqual(
            mygov.archive_tag_for(art_2024),
            "mygov-2024",
        )
        self.assertEqual(
            mygov.archive_tag_for(art_2026),
            "mygov-2026",
        )
        self.assertEqual(
            mygov.item_pdf_url("mygov_pulse", art_2026),
            f"https://github.com/nappingcats/pib_feed/releases/download/mygov-2026/{mygov.archival_name('mygov_pulse', art_2026)}",
        )

    def test_niti_templating(self):
        niti.ARCHIVE_MODE = "archive"
        niti.ARCHIVE_BASE_URL = "https://github.com/nappingcats/pib_feed/releases/download/niti-{year}"

        art_2025 = {
            "title": "Division Report 2025",
            "date": dt.datetime(2025, 8, 1, tzinfo=IST),
            "pdf": "https://www.niti.gov.in/sites/default/files/2025-08/Report_2025.pdf",
            "category": "Economy",
            "author": "NITI",
        }
        art_2026 = {
            "title": "Working Paper 2026",
            "date": dt.datetime(2026, 1, 10, tzinfo=IST),
            "pdf": "https://www.niti.gov.in/sites/default/files/2026-01/WP_2026.pdf",
            "category": "Health",
            "author": "NITI",
        }

        self.assertEqual(niti.archive_tag_for(art_2025), "niti-2025")
        self.assertEqual(niti.archive_tag_for(art_2026), "niti-2026")
        self.assertEqual(
            niti.item_link(art_2026),
            f"https://github.com/nappingcats/pib_feed/releases/download/niti-2026/{niti.archival_name_of(art_2026)}",
        )

    def test_ie_epaper_templating(self):
        ie_epaper.ARCHIVE_MODE = "archive"
        ie_epaper.ARCHIVE_BASE_URL = "https://github.com/nappingcats/pib_feed/releases/download/{feed}-{year}"

        feed_delhi = ie_epaper.FEEDS[1]  # indianexpress-delhi
        art_delhi = {
            "id": 1001,
            "title": "Delhi Edition",
            "date": dt.datetime(2026, 6, 15, tzinfo=IST),
            "archival_name": "indianexpress-delhi_2026-06-15.pdf",
        }

        self.assertEqual(
            ie_epaper.archive_tag_for(feed_delhi, art_delhi),
            "indianexpress-delhi-2026",
        )
        self.assertEqual(
            ie_epaper.item_pdf_url(feed_delhi, art_delhi),
            "https://github.com/nappingcats/pib_feed/releases/download/indianexpress-delhi-2026/indianexpress-delhi_2026-06-15.pdf",
        )

    def test_visionias_templating(self):
        visioniaspt365.ARCHIVE_MODE = "archive"
        visioniaspt365.ARCHIVE_BASE_URL = "https://github.com/nappingcats/pib_feed/releases/download/{feed}-{year}"

        feed_pt = {"key": "visionias-pt365", "section": "pt-365"}
        art_pt = {
            "id": 13229,
            "title": "Culture",
            "year": 2026,
            "archival_name": "visionias_pt-365_2026_pt-365-culture_13229.pdf",
            "pdf": "https://d23q0d0up5eccq.cloudfront.net/doc.pdf",
        }

        self.assertEqual(
            visioniaspt365.archive_tag_for(feed_pt, art_pt),
            "visionias-pt365-2026",
        )
        self.assertEqual(
            visioniaspt365.item_pdf_url(feed_pt, art_pt),
            "https://github.com/nappingcats/pib_feed/releases/download/visionias-pt365-2026/visionias_pt-365_2026_pt-365-culture_13229.pdf",
        )

    def test_meca_templating(self):
        meca.ARCHIVE_MODE = "archive"
        meca.ARCHIVE_BASE_URL = "https://github.com/nappingcats/pib_feed/releases/download/{feed}-{year}"

        art_me = {
            "id": 501,
            "title": "Weekly CA",
            "date": dt.datetime(2025, 4, 10, tzinfo=IST),
            "pdf": "https://madeeasy.in/doc.pdf",
            "archival_name": "madeeasy_weekly_2025-04-10_501.pdf",
        }

        self.assertEqual(
            meca.archive_tag_for("made-easy-ca", art_me),
            "made-easy-ca-2025",
        )
        self.assertEqual(
            meca.item_pdf_url("made-easy-ca", art_me),
            "https://github.com/nappingcats/pib_feed/releases/download/made-easy-ca-2025/madeeasy_weekly_2025-04-10_501.pdf",
        )

    def test_economist_templating(self):
        economist.ARCHIVE_MODE = "archive"
        economist.ARCHIVE_BASE_URL = "https://github.com/nappingcats/pib_feed/releases/download/economist-images-{year}"

        manifest = []
        url = "https://www.economist.com/content-assets/images/20260321_FBP001.jpg"
        rewritten = economist.archive_image(url, manifest)

        now_year = dt.datetime.now(dt.timezone.utc).year
        self.assertEqual(
            rewritten,
            f"https://github.com/nappingcats/pib_feed/releases/download/economist-images-{now_year}/20260321_FBP001.jpg",
        )
        self.assertEqual(len(manifest), 1)
        self.assertEqual(manifest[0]["tag"], f"economist-images-{now_year}")
        self.assertEqual(manifest[0]["name"], "20260321_FBP001.jpg")


if __name__ == "__main__":
    unittest.main()
