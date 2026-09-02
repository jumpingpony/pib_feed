#!/usr/bin/env python3
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import mygov

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

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


class TestMyGovChronologyAndGaps(unittest.TestCase):
    def test_parse_page_extracts_non_epoch_pdfs(self):
        """Ensure PDFs without mygov_<epoch> are not dropped and have proper date."""
        items = mygov.parse_page(SAMPLE_PAGE_HTML)
        self.assertEqual(len(items), 4)

        # December 2025 has filename Mann_ki_baat_december_2025_English.pdf
        dec = next((it for it in items if "December 2025" in it["title"]), None)
        self.assertIsNotNone(dec)
        self.assertIsNotNone(dec["date"], "December 2025 date must not be None")
        self.assertEqual(dec["date"].year, 2025)
        self.assertEqual(dec["date"].month, 12)
        self.assertEqual(dec["date"].day, 28)

    def test_chronological_ordering(self):
        """Ensure feed order is based on true publication date, not upload epoch."""
        items = mygov.parse_page(SAMPLE_PAGE_HTML)
        # Verify January 2026 is chronologically newer than October 2025,
        # even though October 2025 had a later S3 upload epoch.
        jan = next(it for it in items if "January 2026" in it["title"])
        oct_ = next(it for it in items if "October 2025" in it["title"])
        self.assertGreater(jan["date"], oct_["date"])

        # Build feed and ensure January 2026 appears before October 2025
        feed_dict = {it["pdf"]: (mygov.render_item("mygov_mannkibaat", it).strip(), it["date"]) for it in items}
        xml = mygov.build_feed(mygov.FEEDS[2], feed_dict)
        jan_pos = xml.find("January 2026")
        oct_pos = xml.find("October 2025")
        self.assertNotEqual(jan_pos, -1)
        self.assertNotEqual(oct_pos, -1)
        self.assertLess(jan_pos, oct_pos, "January 2026 must appear before October 2025 in XML")


if __name__ == "__main__":
    unittest.main()
