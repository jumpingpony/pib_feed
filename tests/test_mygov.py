#!/usr/bin/env python3
"""MyGov: card parsing, publication dates, archival names, release links."""
import datetime as dt
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from feeds import mygov

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
BASE = "https://github.com/jumpingpony/pib_feed/releases/download/mygov-{year}"

SAMPLE_PAGE_HTML = """
<div class="views-row">
  <div class="news-item">
    <div class="content-detail">
      <h3>Mann Ki Baat Highlights - June 2026</h3>
      <div class="date-size">
        <span class="publish-time">12/08/2026</span>
        <span class="file-size">Size: 0.33 MB</span>
      </div>
      <div class="group-btn-wrapper">
        <a class="border-btn" href="https://static.mygov.in/static/resources/s3fs-public/2026-08/mygov_1786515514_3692480a.pdf">View PDF</a>
        <a class="btn" href="https://www.mygov.in/mygov-ebook/mann-ki-baat-highlights-june-2026">Read eBook</a>
      </div>
    </div>
  </div>
</div>
<div class="views-row">
  <div class="news-item">
    <div class="content-detail">
      <h3>Mann Ki Baat Highlights - January 2026</h3>
      <div class="date-size">
        <span class="publish-time">25/01/2026</span>
      </div>
      <div class="group-btn-wrapper">
        <a class="border-btn" href="https://static.mygov.in/static/resources/s3fs-public/2026-04/mygov_1776160943_69757ac3.pdf">View PDF</a>
      </div>
    </div>
  </div>
</div>
<div class="views-row">
  <div class="news-item">
    <div class="content-detail">
      <h3>Mann Ki Baat Highlights - December 2025</h3>
      <div class="date-size">
        <span class="publish-time">28/12/2025</span>
      </div>
      <div class="group-btn-wrapper">
        <a class="border-btn" href="https://static.mygov.in/static/resources/s3fs-public/ebook/Mann_ki_baat_december_2025_English.pdf">View PDF</a>
      </div>
    </div>
  </div>
</div>
<div class="views-row">
  <div class="news-item">
    <div class="content-detail">
      <h3>Mann Ki Baat Highlights - October 2025</h3>
      <div class="date-size">
        <span class="publish-time">26/10/2025</span>
      </div>
      <div class="group-btn-wrapper">
        <!-- Uploaded in late April 2026 with an epoch higher than January 2026 -->
        <a class="border-btn" href="https://static.mygov.in/static/resources/s3fs-public/2026-04/mygov_1776934971_72fbfb8a.pdf">View PDF</a>
      </div>
    </div>
  </div>
</div>
"""

# Real card markup: the ebook slug carries a percent-encoded apostrophe
# (’ arrives as %E2%80%99) and is linked from the share buttons.
SAMPLE_ENCODED_EBOOK_HTML = """
<div class="news-item">
  <div class="content-detail">
    <h3>From SAPTADHARA to YOUTH POWER, India’s Roadmap for Viksit Bharat</h3>
    <div class="date-size">
      <span class="publish-time">26/08/2026</span>
    </div>
    <div class="share-on-sm">
      <a href="https://www.facebook.com/sharer/sharer.php?u=https://www.mygov.in/mygov-ebook/saptadhara-youth-power-india%E2%80%99s-roadmap-viksit-bharat">Facebook</a>
      <a href="https://twitter.com/intent/tweet?url=https://www.mygov.in/mygov-ebook/saptadhara-youth-power-india%E2%80%99s-roadmap-viksit-bharat">X</a>
    </div>
    <div class="group-btn-wrapper">
      <a class="border-btn" href="https://static.mygov.in/static/resources/s3fs-public/2026-08/mygov_1787817548_7432af04.pdf">View PDF</a>
    </div>
  </div>
</div>
"""


class TestCardParsing(unittest.TestCase):
    def test_percent_encoded_ebook_slug_kept_whole(self):
        # Stopping at the first '%' truncates the ebook link.
        items = mygov.parse_page(SAMPLE_ENCODED_EBOOK_HTML)
        self.assertEqual(len(items), 1)
        self.assertEqual(
            items[0]["link"],
            "https://www.mygov.in/mygov-ebook/saptadhara-youth-power-india"
            "%E2%80%99s-roadmap-viksit-bharat",
        )

    def test_pdf_without_epoch_still_dated(self):
        items = mygov.parse_page(SAMPLE_PAGE_HTML)
        self.assertEqual(len(items), 4)

        december = next(item for item in items if "December 2025" in item["title"])
        self.assertIsNotNone(december["date"], "December 2025 date must not be None")
        self.assertEqual(
            (december["date"].year, december["date"].month, december["date"].day),
            (2025, 12, 28),
        )

    def test_order_follows_publication_not_upload_epoch(self):
        items = mygov.parse_page(SAMPLE_PAGE_HTML)
        january = next(item for item in items if "January 2026" in item["title"])
        october = next(item for item in items if "October 2025" in item["title"])
        self.assertGreater(january["date"], october["date"])

        feed_items = {
            item["pdf"]: (mygov.render_item("mygov_mannkibaat", item).strip(), item["date"])
            for item in items
        }
        xml = mygov.build_feed(mygov.FEEDS[2], feed_items)
        january_at = xml.find("January 2026")
        october_at = xml.find("October 2025")
        self.assertNotEqual(january_at, -1)
        self.assertNotEqual(october_at, -1)
        self.assertLess(january_at, october_at, "January 2026 must precede October 2025")


class TestArchiveUrls(unittest.TestCase):
    def test_archival_name_slugifies_the_title(self):
        pulse = {
            "id": 1234567890,
            "title": "Good Governance Pathway 2026 and Viksit Bharat 2047",
            "date": dt.datetime(2026, 1, 8, tzinfo=IST),
            "link": "https://www.mygov.in/pulse/good-governance-pathway-2026-and-viksit-bharat-2047",
            "pdf": "https://static.mygov.in/pdf1.pdf",
        }
        nep = {
            "id": 1234567891,
            "title": "5 Years NEP 2020",
            "date": dt.datetime(2025, 8, 21, tzinfo=IST),
            "link": "https://www.mygov.in/pulse/5-years-nep-2020",
            "pdf": "https://static.mygov.in/pdf2.pdf",
        }
        self.assertEqual(
            mygov.archival_name("mygov_pulse", pulse),
            "mygov_pulse_2026-01-08_good-governance-pathway-2026-and-viksit-bharat-2047.pdf",
        )
        self.assertEqual(
            mygov.archival_name("mygov_pulse", nep),
            "mygov_pulse_2025-08-21_5-years-nep-2020.pdf",
        )

    def test_release_link_follows_item_year(self):
        article = {
            "id": 2,
            "title": "Pulse 2026",
            "date": dt.datetime(2026, 3, 15, tzinfo=IST),
            "pdf": "https://static.mygov.in/mygov_1773500000_def.pdf",
            "link": "https://www.mygov.in/pulse-2026",
        }
        with patch.object(mygov, "ARCHIVE_MODE", "archive"), patch.object(
            mygov, "ARCHIVE_BASE_URL", BASE
        ):
            self.assertEqual(mygov.archive_tag_for(article), "mygov-2026")
            self.assertEqual(
                mygov.item_pdf_url("mygov_pulse", article),
                "https://github.com/jumpingpony/pib_feed/releases/download/mygov-2026/"
                + mygov.archival_name("mygov_pulse", article),
            )


if __name__ == "__main__":
    unittest.main()
