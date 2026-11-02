#!/usr/bin/env python3
"""Vision IAS: PT and Mains release tags and links."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from feeds import visioniaspt365

BASE = "https://github.com/jumpingpony/pib_feed/releases/download/{feed}-{year}"

PT_ARTICLE = {
    "id": 13229,
    "title": "Culture",
    "year": 2026,
    "archival_name": "visionias_pt-365_2026_pt-365-culture_13229.pdf",
    "pdf": "https://d23q0d0up5eccq.cloudfront.net/doc.pdf",
}
MAINS_ARTICLE = {
    "id": 9868,
    "title": "Economy",
    "year": 2025,
    "archival_name": "visionias_mains-365_2025_mains-365-economy_9868.pdf",
    "pdf": "https://d23q0d0up5eccq.cloudfront.net/doc2.pdf",
}


class TestArchiveUrls(unittest.TestCase):
    def test_pt_and_mains_releases_are_partitioned_per_year(self):
        pt_feed = next(feed for feed in visioniaspt365.FEEDS if feed["key"] == "visionias_pt-365")
        mains_feed = next(
            feed for feed in visioniaspt365.FEEDS if feed["key"] == "visionias_mains-365"
        )
        with patch.object(visioniaspt365, "ARCHIVE_MODE", "archive"), patch.object(
            visioniaspt365, "ARCHIVE_BASE_URL", BASE
        ):
            cases = [
                (pt_feed, PT_ARTICLE, "visionias_pt365-2026"),
                (mains_feed, MAINS_ARTICLE, "visionias_mains365-2025"),
            ]
            for feed, article, tag in cases:
                with self.subTest(feed=feed["key"]):
                    self.assertEqual(visioniaspt365.archive_tag_for(feed, article), tag)
                    self.assertEqual(
                        visioniaspt365.item_pdf_url(feed, article),
                        f"https://github.com/jumpingpony/pib_feed/releases/download/"
                        f"{tag}/{article['archival_name']}",
                    )


if __name__ == "__main__":
    unittest.main()
