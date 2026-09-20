#!/usr/bin/env python3
import datetime as dt
import json
import os
import re
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import economist
import ie_epaper
import meca
import mygov
import newsonair_feed
import niti
import toi
import visioniaspt365

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


class TestBuildersUrlTemplating(unittest.TestCase):
    def test_mygov_templating(self):
        mygov.ARCHIVE_MODE = "archive"
        mygov.ARCHIVE_BASE_URL = "https://github.com/jumpingpony/pib_feed/releases/download/mygov-{year}"

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
            f"https://github.com/jumpingpony/pib_feed/releases/download/mygov-2026/{mygov.archival_name('mygov_pulse', art_2026)}",
        )

    def test_niti_templating(self):
        niti.ARCHIVE_MODE = "archive"
        niti.ARCHIVE_BASE_URL = "https://github.com/jumpingpony/pib_feed/releases/download/niti-{year}"

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
            f"https://github.com/jumpingpony/pib_feed/releases/download/niti-2026/{niti.archival_name_of(art_2026)}",
        )

    def test_ie_epaper_templating(self):
        ie_epaper.ARCHIVE_MODE = "archive"
        ie_epaper.ARCHIVE_BASE_URL = "https://github.com/jumpingpony/pib_feed/releases/download/{feed}-{year}"

        feed_delhi = ie_epaper.FEEDS[1]  # indianexpress-delhi
        art_delhi = {
            "id": 1001,
            "title": "Delhi Edition",
            "date": dt.datetime(2026, 6, 15, tzinfo=IST),
            "archival_name": "indianexpress-delhi_2026-06-15.pdf",
        }

        self.assertEqual(
            ie_epaper.archive_tag_for(feed_delhi, art_delhi),
            "indianexpress-delhi",
        )
        self.assertEqual(
            ie_epaper.item_pdf_url(feed_delhi, art_delhi),
            "https://github.com/jumpingpony/pib_feed/releases/download/indianexpress-delhi/indianexpress-delhi_2026-06-15.pdf",
        )

    def test_visionias_templating(self):
        visioniaspt365.ARCHIVE_MODE = "archive"
        visioniaspt365.ARCHIVE_BASE_URL = "https://github.com/jumpingpony/pib_feed/releases/download/{feed}-{year}"

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
            "https://github.com/jumpingpony/pib_feed/releases/download/visionias-pt365-2026/visionias_pt-365_2026_pt-365-culture_13229.pdf",
        )
        self.assertEqual(
            visioniaspt365.archive_tag_for(feed_mains, art_mains),
            "visionias-mains365-2025",
        )
        self.assertEqual(
            visioniaspt365.item_pdf_url(feed_mains, art_mains),
            "https://github.com/jumpingpony/pib_feed/releases/download/visionias-mains365-2025/visionias_mains-365_2025_mains-365-economy_9868.pdf",
        )

    def test_meca_templating(self):
        meca.ARCHIVE_MODE = "archive"
        meca.ARCHIVE_BASE_URL = "https://github.com/jumpingpony/pib_feed/releases/download/{feed}-{year}"

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
            "https://github.com/jumpingpony/pib_feed/releases/download/madeeasy-weekly-2025/madeeasy_weekly_2025-04-10_501.pdf",
        )

    def test_economist_templating(self):
        economist.ARCHIVE_MODE = "archive"
        economist.ARCHIVE_BASE_URL = "https://github.com/jumpingpony/pib_feed/releases/download/economist-images-{year}"

        manifest = []
        url = "https://www.economist.com/content-assets/images/20260321_FBP001.jpg"
        rewritten = economist.archive_image(url, manifest)

        now_year = dt.datetime.now(dt.timezone.utc).year
        self.assertEqual(
            rewritten,
            f"https://github.com/jumpingpony/pib_feed/releases/download/economist-images-{now_year}/20260321_FBP001.jpg",
        )
        self.assertEqual(len(manifest), 1)
        self.assertEqual(manifest[0]["tag"], f"economist-images-{now_year}")
        self.assertEqual(manifest[0]["name"], "20260321_FBP001.jpg")


class TestEconomistBuilder(unittest.TestCase):
    def test_extract_build_id(self):
        sample = '<script id="__NEXT_DATA__" type="application/json">{"buildId":"abc-123","props":{}}</script>'
        self.assertEqual(economist.extract_build_id(sample), "abc-123")
        self.assertIsNone(economist.extract_build_id("<html>no data</html>"))

    def test_article_data_url(self):
        url = "https://www.economist.com/finance-and-economics/2026/09/02/central-banking?ref=rss"
        expected = "https://www.economist.com/_next/data/test-id/finance-and-economics/2026/09/02/central-banking.json"
        self.assertEqual(economist.article_data_url("test-id", url), expected)

    def test_fetch_article_next_data(self):
        mock_session = MagicMock()
        mock_payload = {
            "pageProps": {
                "content": {
                    "headline": "Test Title",
                    "body": [{"type": "PARAGRAPH", "textHtml": "<p>Body text</p>"}],
                }
            }
        }
        with patch("economist.fetch", return_value=json.dumps(mock_payload)):
            content = economist.fetch_article(mock_session, "https://www.economist.com/test", "test-id")
            self.assertIsNotNone(content)
            self.assertEqual(content.get("headline"), "Test Title")

    def test_fetch_article_fallback(self):
        mock_session = MagicMock()
        html_payload = '<script id="__NEXT_DATA__">{"props":{"pageProps":{"content":{"headline":"Fallback Title"}}}}</script>'
        # First call for data_url fails, second call for HTML page succeeds
        with patch("economist.fetch", side_effect=[None, html_payload]):
            content = economist.fetch_article(mock_session, "https://www.economist.com/test", "test-id")
            self.assertIsNotNone(content)
            self.assertEqual(content.get("headline"), "Fallback Title")

    def test_resolve_build_id_podcasts(self):
        mock_session = MagicMock()
        podcasts_html = '<script id="__NEXT_DATA__">{"buildId":"pod-build-456"}</script>'

        def fake_fetch(session, url):
            if url.endswith("/podcasts"):
                return podcasts_html
            return None

        with patch("economist.fetch", side_effect=fake_fetch):
            build_id = economist.resolve_build_id(mock_session)
            self.assertEqual(build_id, "pod-build-456")

    def test_fetch_listing_default_next_data(self):
        mock_session = MagicMock()
        mock_payload = {
            "pageProps": {
                "content": {
                    "articles": [
                        {
                            "url": "/finance-and-economics/2026/09/15/test-ipo",
                            "headline": "Test IPO Article",
                            "datePublished": "2026-09-15T20:00:00.000Z",
                        }
                    ]
                }
            }
        }
        called_urls = []

        def fake_fetch(session, url):
            called_urls.append(url)
            if url.endswith(".json"):
                return json.dumps(mock_payload)
            return None

        with patch("economist.fetch", side_effect=fake_fetch):
            listing = economist.fetch_listing(
                mock_session, "economist-finance-and-economics", "build-123"
            )
            self.assertEqual(len(listing), 1)
            self.assertEqual(listing[0]["headline"], "Test IPO Article")
            # Default behavior must call Next.js data endpoint directly, not HTML
            self.assertEqual(len(called_urls), 1)
            self.assertTrue(called_urls[0].endswith("/finance-and-economics.json"))

    def test_fetch_listing_fallback_html(self):
        mock_session = MagicMock()
        html_payload = (
            '<script id="__NEXT_DATA__">{"props":{"pageProps":{"content":'
            '{"articles":[{"url":"/fallback","headline":"Fallback Headline"}]}}}}</script>'
        )
        called_urls = []

        def fake_fetch(session, url):
            called_urls.append(url)
            if url.endswith(".json"):
                return None
            return html_payload

        with patch("economist.fetch", side_effect=fake_fetch):
            listing = economist.fetch_listing(
                mock_session, "economist-finance-and-economics", "build-123"
            )
            self.assertEqual(len(listing), 1)
            self.assertEqual(listing[0]["headline"], "Fallback Headline")
            self.assertEqual(len(called_urls), 2)
            self.assertTrue(called_urls[0].endswith(".json"))
            self.assertEqual(called_urls[1], "https://www.economist.com/finance-and-economics")

    def test_parse_rss_listing(self):
        rss_payload = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <title>Latest Updates</title>
            <link>https://www.economist.com/latest</link>
            <item>
              <title>Article One Headline</title>
              <description>Article one summary</description>
              <link>https://www.economist.com/finance-and-economics/2026/09/20/article-one</link>
              <pubDate>Sun, 20 Sep 2026 12:00:00 +0000</pubDate>
            </item>
            <item>
              <title>Article Two Headline</title>
              <description>Article two summary</description>
              <link>https://www.economist.com/business/2026/09/19/article-two</link>
              <pubDate>Sat, 19 Sep 2026 10:00:00 +0000</pubDate>
            </item>
          </channel>
        </rss>"""
        items = economist.parse_rss_listing(rss_payload)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["headline"], "Article One Headline")
        self.assertEqual(items[0]["link"], "https://www.economist.com/finance-and-economics/2026/09/20/article-one")
        self.assertEqual(items[0]["rubric"], "Article one summary")
        self.assertEqual(items[0]["date"].day, 20)

    def test_fetch_listing_rss(self):
        mock_session = MagicMock()
        rss_payload = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <item>
              <title>RSS Headline</title>
              <link>https://www.economist.com/world/article</link>
              <pubDate>Sun, 20 Sep 2026 14:00:00 +0000</pubDate>
            </item>
          </channel>
        </rss>"""
        with patch("economist.fetch", return_value=rss_payload):
            listing = economist.fetch_listing(mock_session, "economist-all", "build-123")
            self.assertEqual(len(listing), 1)
            self.assertEqual(listing[0]["headline"], "RSS Headline")
            self.assertEqual(listing[0]["link"], "https://www.economist.com/world/article")

    def test_all_articles_feed_configured(self):
        self.assertIn("economist-all", economist.FEEDS)
        feed = economist.FEEDS["economist-all"]
        self.assertEqual(feed["title"], "All articles - Economist")
        self.assertTrue(feed["rss"].endswith("/latest/rss.xml"))
        self.assertGreaterEqual(feed["max_items"], 200)
        self.assertEqual(feed["days"], 14)


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

    def test_parse_transcript_lists_and_blocks(self):
        sample_html = """
        <p>Opening paragraph.</p>
        <ol>
          <li><span><strong>First headline item</strong><br /></span></li>
          <li><strong>Second headline with stray p<p></strong></li>
        </ol>
        <p>Mid paragraph.</p>
        <ul>
          <li>History bullet point 1</li>
          <li>History bullet point 2</li>
        </ul>
        <h3>Segment Heading</h3>
        <blockquote>Quoted statement</blockquote>
        """
        parsed = newsonair_feed.parse_transcript(sample_html)
        self.assertIn("<p>Opening paragraph.</p>", parsed)
        self.assertIn("<ol>\n<li>First headline item</li>\n<li>Second headline with stray p</li>\n</ol>", parsed)
        self.assertIn("<p>Mid paragraph.</p>", parsed)
        self.assertIn("<ul>\n<li>History bullet point 1</li>\n<li>History bullet point 2</li>\n</ul>", parsed)
        self.assertIn("<h3>Segment Heading</h3>", parsed)
        self.assertIn("<blockquote><p>Quoted statement</p></blockquote>", parsed)

    def test_scrape_bulletin_includes_lists(self):
        cat_info = newsonair_feed.CATEGORIES["morning-news"]
        mock_html = """
        <html>
        <body>
          <span class="detail-date">September 03, 2026 08:30 AM</span>
          <div class="entry-content">
            <p>Intro news.</p>
            <ol>
              <li>Headline 1</li>
              <li>Headline 2</li>
            </ol>
            <p>Outro news.</p>
          </div>
          <!-- .entry-content -->
        </body>
        </html>
        """
        mock_session = MagicMock()
        with patch("newsonair_feed.fetch", return_value=mock_html):
            bulletin = newsonair_feed.scrape_bulletin(
                mock_session,
                cat_info,
                "https://newsonair.gov.in/bulletins-detail/morning-news-100/",
            )
        self.assertIsNotNone(bulletin)
        self.assertIn("<ol>\n<li>Headline 1</li>\n<li>Headline 2</li>\n</ol>", bulletin["body_html"])
        self.assertIn("<p>Intro news.</p>", bulletin["body_html"])
        self.assertIn("<p>Outro news.</p>", bulletin["body_html"])


class TestToiBuilder(unittest.TestCase):
    """Verify Swaminomics feed constants and references."""

    def test_toi_feed_key(self):
        # Ensure active feed key is toi-swami-nomics and legacy key is absent.
        self.assertEqual(toi.FEED_KEY, "toi-swami-nomics")
        self.assertFalse(hasattr(toi, "LEGACY_FEED_KEY"))

    def test_toi_no_legacy_refs(self):
        # Ensure no legacy toi-swaminomics string remains in toi.py.
        toi_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "toi.py"))
        with open(toi_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertNotIn("toi-swaminomics", content)


if __name__ == "__main__":
    unittest.main()

