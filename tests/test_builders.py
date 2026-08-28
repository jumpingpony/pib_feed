#!/usr/bin/env python3
import datetime as dt
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import economist
import ie_epaper
import meca
import mygov
import newsonair_feed
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

        feed_pt = visioniaspt365.FEEDS[0]  # key: "visionias-pt-365"
        feed_mains = visioniaspt365.FEEDS[1]  # key: "visionias-mains-365"
        art_pt = {
            "id": 13229,
            "title": "Culture",
            "year": 2026,
            "archival_name": "visionias_pt-365_2026_pt-365-culture_13229.pdf",
            "pdf": "https://d23q0d0up5eccq.cloudfront.net/doc.pdf",
        }
        art_mains = {
            "id": 9868,
            "title": "Economy",
            "year": 2025,
            "archival_name": "visionias_mains-365_2025_mains-365-economy_9868.pdf",
            "pdf": "https://d23q0d0up5eccq.cloudfront.net/doc2.pdf",
        }

        self.assertEqual(
            visioniaspt365.archive_tag_for(feed_pt, art_pt),
            "visionias-pt365-2026",
        )
        self.assertEqual(
            visioniaspt365.item_pdf_url(feed_pt, art_pt),
            "https://github.com/nappingcats/pib_feed/releases/download/visionias-pt365-2026/visionias_pt-365_2026_pt-365-culture_13229.pdf",
        )
        self.assertEqual(
            visioniaspt365.archive_tag_for(feed_mains, art_mains),
            "visionias-mains365-2025",
        )
        self.assertEqual(
            visioniaspt365.item_pdf_url(feed_mains, art_mains),
            "https://github.com/nappingcats/pib_feed/releases/download/visionias-mains365-2025/visionias_mains-365_2025_mains-365-economy_9868.pdf",
        )

    def test_meca_templating(self):
        meca.ARCHIVE_MODE = "archive"
        meca.ARCHIVE_BASE_URL = "https://github.com/nappingcats/pib_feed/releases/download/{feed}-{year}"

        feed_me = meca.FEEDS[0]  # key: "madeeasy-weekly"
        art_me = {
            "id": 501,
            "title": "Weekly CA",
            "date": dt.datetime(2025, 4, 10, tzinfo=IST),
            "pdf": "https://madeeasy.in/doc.pdf",
            "archival_name": "madeeasy_weekly_2025-04-10_501.pdf",
        }

        self.assertEqual(
            meca.archive_tag_for(feed_me["key"], art_me),
            "madeeasy-weekly-2025",
        )
        self.assertEqual(
            meca.item_pdf_url(feed_me["key"], art_me),
            "https://github.com/nappingcats/pib_feed/releases/download/madeeasy-weekly-2025/madeeasy_weekly_2025-04-10_501.pdf",
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


class TestNewsOnAirPodcast(unittest.TestCase):
    def test_categories_configuration(self):
        expected_slugs = {
            "morning-news",
            "midday-news",
            "evening-news",
            "parikrama",
            "aaj-savere",
        }
        self.assertEqual(set(newsonair_feed.CATEGORIES.keys()), expected_slugs)

        for slug, cat in newsonair_feed.CATEGORIES.items():
            self.assertEqual(cat["slug"], slug)
            self.assertTrue(cat["title"])
            self.assertTrue(cat["label"])
            self.assertTrue(cat["image"].startswith("https://"))
            self.assertTrue(re.match(r"^\d{2}:\d{2}:\d{2}$", cat["duration"]))
            self.assertTrue(len(cat["keywords"]) > 0)

    def test_render_item_with_enclosure(self):
        item = {
            "link": "https://newsonair.gov.in/bulletins-detail/parikrama-829/",
            "title": "Parikrama — 25 Aug 2026",
            "date": dt.datetime(2026, 8, 25, 16, 30, tzinfo=IST),
            "body_html": "<p>Transcript test paragraph.</p>",
            "summary": "Transcript test paragraph.",
            "enclosure": (
                "https://newsonair.gov.in/wp-content/uploads/2026/08/FM-NEWSParikrama-1630-1700-16.mp3",
                10717193,
                "audio/mpeg",
            ),
            "duration": "00:30:00",
            "image": "https://newsonair.gov.in/wp-content/uploads/2025/11/parikrama.jpg",
            "author": "All India Radio News",
            "category": "Parikrama",
            "itunes_title": "Parikrama — 25 Aug 2026",
            "slug": "parikrama",
        }
        xml = newsonair_feed.render_item(item)

        self.assertIn('<enclosure url="https://newsonair.gov.in/wp-content/uploads/2026/08/FM-NEWSParikrama-1630-1700-16.mp3" length="10717193" type="audio/mpeg" />', xml)
        self.assertIn("<itunes:duration>00:30:00</itunes:duration>", xml)
        self.assertIn('<itunes:image href="https://newsonair.gov.in/wp-content/uploads/2025/11/parikrama.jpg" />', xml)
        self.assertIn("<itunes:author>All India Radio News</itunes:author>", xml)
        self.assertIn("<category>Parikrama</category>", xml)
        self.assertIn("<itunes:title>Parikrama — 25 Aug 2026</itunes:title>", xml)
        self.assertIn("<itunes:explicit>no</itunes:explicit>", xml)
        self.assertIn("<content:encoded><![CDATA[<p>Transcript test paragraph.</p>]]></content:encoded>", xml)

    def test_parse_legacy_item_block(self):
        legacy_block = """    <item>
      <title>Morning News — 24 Aug 2026</title>
      <link>https://newsonair.gov.in/bulletins-detail/morning-news-827/</link>
      <guid isPermaLink="true">https://newsonair.gov.in/bulletins-detail/morning-news-827/</guid>
      <pubDate>Mon, 24 Aug 2026 08:30:00 +0530</pubDate>
      <description>Morning headlines summary...</description>
      <content:encoded><![CDATA[<p>Morning headlines full transcript.</p>]]></content:encoded>
    </item>"""
        parsed = newsonair_feed.parse_item_block(legacy_block)

        self.assertEqual(parsed["link"], "https://newsonair.gov.in/bulletins-detail/morning-news-827/")
        self.assertEqual(parsed["title"], "Morning News — 24 Aug 2026")
        self.assertEqual(parsed["category"], "Morning News")
        self.assertEqual(parsed["duration"], "00:15:00")
        self.assertEqual(parsed["image"], "https://newsonair.gov.in/wp-content/uploads/2025/11/Akhashvani-1.png")
        self.assertEqual(parsed["body_html"], "<p>Morning headlines full transcript.</p>")

    def test_build_feed_structure(self):
        items = [
            {
                "link": "https://newsonair.gov.in/bulletins-detail/parikrama-829/",
                "title": "Parikrama — 25 Aug 2026",
                "date": dt.datetime(2026, 8, 25, 16, 30, tzinfo=IST),
                "body_html": "<p>Transcript 1</p>",
                "slug": "parikrama",
                "category": "Parikrama",
                "duration": "00:30:00",
                "image": "https://newsonair.gov.in/wp-content/uploads/2025/11/parikrama.jpg",
            },
            {
                "link": "https://newsonair.gov.in/bulletins-detail/morning-news-828/",
                "title": "Morning News — 25 Aug 2026",
                "date": dt.datetime(2026, 8, 25, 8, 30, tzinfo=IST),
                "body_html": "<p>Transcript 2</p>",
                "slug": "morning-news",
                "category": "Morning News",
                "duration": "00:15:00",
                "image": "https://newsonair.gov.in/wp-content/uploads/2025/11/Akhashvani-1.png",
            },
        ]
        xml = newsonair_feed.build_feed(items)

        self.assertIn('xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"', xml)
        self.assertIn("<title>News On AIR - All India Radio</title>", xml)
        self.assertIn("<itunes:author>All India Radio / Prasar Bharati</itunes:author>", xml)
        self.assertIn('<itunes:image href="https://newsonair.gov.in/wp-content/uploads/2025/11/Akhashvani-1.png" />', xml)
        self.assertIn('<itunes:category text="News">\n      <itunes:category text="Daily News" />\n    </itunes:category>', xml)
        self.assertIn("<itunes:type>episodic</itunes:type>", xml)
        self.assertIn("<itunes:explicit>no</itunes:explicit>", xml)


if __name__ == "__main__":
    unittest.main()

