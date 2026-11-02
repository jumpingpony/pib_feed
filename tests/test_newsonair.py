#!/usr/bin/env python3
"""News On AIR: bulletin transcripts, item rendering, incremental collection."""
import datetime as dt
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from feeds import newsonair_feed

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

BULLETIN = {
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


class TestTranscriptParsing(unittest.TestCase):
    def test_keeps_lists_as_lists(self):
        # Transcripts are headline lists; flattening them to <p> loses the order
        # a reader scans.
        sample = """
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
        parsed = newsonair_feed.parse_transcript(sample)
        self.assertIn("<p>Opening paragraph.</p>", parsed)
        self.assertIn(
            "<ol>\n<li>First headline item</li>\n"
            "<li>Second headline with stray p</li>\n</ol>",
            parsed,
        )
        self.assertIn("<p>Mid paragraph.</p>", parsed)
        self.assertIn(
            "<ul>\n<li>History bullet point 1</li>\n<li>History bullet point 2</li>\n</ul>",
            parsed,
        )
        self.assertIn("<h3>Segment Heading</h3>", parsed)
        self.assertIn("<blockquote><p>Quoted statement</p></blockquote>", parsed)

    def test_parses_published_item_block(self):
        block = """    <item>
      <title>Morning News — 24 Aug 2026</title>
      <link>https://newsonair.gov.in/bulletins-detail/morning-news-827/</link>
      <guid isPermaLink="true">https://newsonair.gov.in/bulletins-detail/morning-news-827/</guid>
      <pubDate>Mon, 24 Aug 2026 08:30:00 +0530</pubDate>
      <description>Morning headlines summary...</description>
      <content:encoded><![CDATA[<p>Morning headlines full transcript.</p>]]></content:encoded>
    </item>"""
        parsed = newsonair_feed.parse_item_block(block)
        self.assertEqual(
            parsed["link"], "https://newsonair.gov.in/bulletins-detail/morning-news-827/"
        )
        self.assertEqual(parsed["title"], "Morning News — 24 Aug 2026")
        self.assertEqual(parsed["category"], "Morning News")
        self.assertEqual(parsed["duration"], "00:15:00")
        self.assertEqual(
            parsed["image"],
            "https://newsonair.gov.in/wp-content/uploads/2025/11/Akhashvani-1.png",
        )
        self.assertEqual(parsed["body_html"], "<p>Morning headlines full transcript.</p>")


class TestItemRendering(unittest.TestCase):
    def test_item_carries_podcast_tags(self):
        xml = newsonair_feed.render_item(BULLETIN)
        expected = {
            "enclosure": (
                '<enclosure url="https://newsonair.gov.in/wp-content/uploads/2026/08/'
                'FM-NEWSParikrama-1630-1700-16.mp3" length="10717193" type="audio/mpeg" />'
            ),
            "duration": "<itunes:duration>00:30:00</itunes:duration>",
            "image": '<itunes:image href="https://newsonair.gov.in/wp-content/uploads/2025/11/parikrama.jpg" />',
            "author": "<itunes:author>All India Radio News</itunes:author>",
            "category": "<category>Parikrama</category>",
            "episode title": "<itunes:title>Parikrama — 25 Aug 2026</itunes:title>",
            "explicit": "<itunes:explicit>no</itunes:explicit>",
            "body": "<content:encoded><![CDATA[<p>Transcript test paragraph.</p>]]></content:encoded>",
        }
        for label, fragment in expected.items():
            with self.subTest(field=label):
                self.assertIn(fragment, xml)

    def test_channel_declares_itunes_metadata(self):
        items = [BULLETIN]
        xml = newsonair_feed.build_feed(items)
        expected = {
            "namespace": 'xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"',
            "title": "<title>News On AIR - All India Radio</title>",
            "author": "<itunes:author>All India Radio / Prasar Bharati</itunes:author>",
            "image": '<itunes:image href="https://newsonair.gov.in/wp-content/uploads/2025/11/Akhashvani-1.png" />',
            "category": '<itunes:category text="News">\n      <itunes:category text="Daily News" />\n    </itunes:category>',
            "type": "<itunes:type>episodic</itunes:type>",
            "explicit": "<itunes:explicit>no</itunes:explicit>",
        }
        for label, fragment in expected.items():
            with self.subTest(field=label):
                self.assertIn(fragment, xml)


class TestCollection(unittest.TestCase):
    def test_scraped_bulletin_keeps_transcript_lists(self):
        html = """
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
        </body>
        </html>
        """
        with patch("feeds.newsonair_feed.fetch", return_value=html):
            bulletin = newsonair_feed.scrape_bulletin(
                MagicMock(),
                newsonair_feed.CATEGORIES["morning-news"],
                "https://newsonair.gov.in/bulletins-detail/morning-news-100/",
            )
        self.assertIsNotNone(bulletin)
        self.assertIn("<ol>\n<li>Headline 1</li>\n<li>Headline 2</li>\n</ol>", bulletin["body_html"])
        self.assertIn("<p>Intro news.</p>", bulletin["body_html"])
        self.assertIn("<p>Outro news.</p>", bulletin["body_html"])

    def test_published_bulletins_are_not_refetched(self):
        # The listing page still links older bulletins; only unseen ids may be
        # scraped, or every run refetches the whole first page.
        published = {"https://newsonair.gov.in/bulletins-detail/parikrama-900/"}
        listing = '<a href="/bulletins-detail/parikrama-902/">Details</a>'

        def fake_fetch(session, url, **kwargs):
            if "bulletins-detail-category" in url:
                return listing
            return None

        with patch("feeds.newsonair_feed.fetch", side_effect=fake_fetch), patch(
            "feeds.newsonair_feed.scrape_bulletin",
            side_effect=lambda session, cat, url: {"link": url},
        ):
            bulletins = newsonair_feed.collect_bulletins(
                MagicMock(), newsonair_feed.CATEGORIES["parikrama"], published
            )

        urls = [bulletin["link"] for bulletin in bulletins]
        self.assertNotIn("https://newsonair.gov.in/bulletins-detail/parikrama-900/", urls)
        self.assertIn("https://newsonair.gov.in/bulletins-detail/parikrama-901/", urls)
        self.assertIn("https://newsonair.gov.in/bulletins-detail/parikrama-902/", urls)


if __name__ == "__main__":
    unittest.main()
