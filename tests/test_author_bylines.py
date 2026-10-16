#!/usr/bin/env python3
"""Author bylines: names and one-line bios at the top of new feed items."""
import datetime as dt
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import frontline
import indianexpress
import indiatoday
import theprint

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


class TestIndianExpressBylines(unittest.TestCase):
    def test_parse_api_items_keeps_byline_ids(self):
        items = indianexpress.parse_api_items(
            [
                {
                    "link": "https://indianexpress.com/article/x/",
                    "title": {"rendered": "A headline"},
                    "content": {"rendered": "<p>Body</p>"},
                    "date": "2026-10-16T08:42:35",
                    "ie_byline_authors": [22, 11],
                }
            ]
        )
        self.assertEqual(items[0]["author_ids"], [22, 11])

    def test_attach_authors_keeps_article_order_and_lead_bio(self):
        terms = json.dumps(
            [
                {"id": 11, "name": "A One", "slug": "a-one"},
                {"id": 22, "name": "B Two", "slug": "b-two"},
            ]
        )
        profile = json.dumps(
            {"list": [{"items": [{"user_description": "B Two is a correspondent."}]}]}
        )

        def fake_fetch(session, url, params=None):
            return terms if "ie_byline_authors" in url else profile

        items = [{"author_ids": [22, 11], "author": "", "author_bio": ""}]
        with patch("indianexpress.fetch", side_effect=fake_fetch):
            indianexpress.attach_authors(MagicMock(), items)

        self.assertEqual(items[0]["author"], "B Two, A One")
        self.assertEqual(items[0]["author_bio"], "B Two is a correspondent.")

    def test_render_body_opens_with_author_and_bio(self):
        item = {
            "author": "B Two",
            "author_bio": "B Two is a correspondent.",
            "link": "https://indianexpress.com/article/x/",
        }
        body, summary = indianexpress.render_body(item, "", [("p", "Story text.")])

        self.assertTrue(
            body.startswith(
                "<p><strong>B Two</strong></p>\n"
                "<p><em>B Two is a correspondent.</em></p>"
            )
        )
        self.assertNotIn("B Two", summary)


class TestThePrintBylines(unittest.TestCase):
    def test_resolve_author_uses_primary_author_only(self):
        users = {
            24: {"name": "Shekhar Gupta", "description": "Editor-in-Chief of ThePrint."}
        }
        # The site never prints the REST `coauthors` field (internal
        # contributors), so only the primary author is used.
        post = {"author": 24, "coauthors": [10186]}

        with patch("theprint.fetch_user", side_effect=lambda s, uid: users[uid]), patch(
            "theprint.USER_DELAY", 0
        ):
            name, bio = theprint.resolve_author(MagicMock(), post, {})

        self.assertEqual(name, "Shekhar Gupta")
        self.assertEqual(bio, "Editor-in-Chief of ThePrint.")

    def test_resolve_author_without_author_id(self):
        name, bio = theprint.resolve_author(MagicMock(), {"author": 0}, {})
        self.assertEqual((name, bio), ("", ""))

    def test_render_item_header_and_creator(self):
        post = {
            "id": 1,
            "date": "2026-10-03T00:11:44",
            "link": "https://theprint.in/x/1/",
            "title": {"rendered": "A headline"},
            "content": {"rendered": "<p>Fifty words.</p>"},
        }
        item = theprint.render_item(post, "Shekhar Gupta", "Editor-in-Chief.")

        self.assertIn("<dc:creator>Shekhar Gupta</dc:creator>", item)
        self.assertIn(
            "<content:encoded><![CDATA[<p><strong>Shekhar Gupta</strong></p>\n"
            "<p><em>Editor-in-Chief.</em></p>\n<p>Fifty words.</p>]]></content:encoded>",
            item,
        )
        xml = theprint.build_feed(theprint.FEEDS[0], {1: item})
        self.assertIn('xmlns:dc="http://purl.org/dc/elements/1.1/"', xml)


class TestFrontlineBylines(unittest.TestCase):
    ARTICLE = (
        '<meta property="og:title" content="A headline" />'
        '<meta property="og:description" content="A standfirst." />'
        '<div id="content-body-9" class="articlebodycontent" itemprop="articleBody">'
        "<p>First paragraph of the story.</p>"
        '<div class="comments-shares'
    )

    def setUp(self):
        frontline._PROFILE_LINES.clear()
        frontline._PROFILE_LOOKUPS[0] = 0

    def test_author_slugs_only_reads_byline_links(self):
        page = (
            '<a href="https://frontline.thehindu.com/profile/author/one-1/" '
            'class="person-name lnk">One</a>'
            '<a href="https://frontline.thehindu.com/profile/author/two-2/">Two</a>'
        )
        self.assertEqual(frontline.author_slugs(page), ["one-1"])

    def test_profile_line_prefers_bio_then_role(self):
        meta = '<meta name="description" content="Vaishna Roy is Editor, Frontline.">'
        role = (
            '<h1 class="author-name">Soni '
            '<span class="author-designation">Deputy Editor</span></h1>'
        )
        with patch("frontline.fetch", side_effect=[meta, role]):
            self.assertEqual(
                frontline.profile_line(MagicMock(), "vaishna-roy-16745"),
                "Vaishna Roy is Editor, Frontline.",
            )
            self.assertEqual(
                frontline.profile_line(MagicMock(), "soni-mishra-24635"),
                "Deputy Editor",
            )

    def test_build_article_adds_author_and_role(self):
        article = (
            '<a href="https://frontline.thehindu.com/profile/author/one-1/" '
            'class="person-name lnk">One Author</a>' + self.ARTICLE
        )
        profile = '<meta name="description" content="One Author is Deputy Editor.">'

        with patch("frontline.fetch", side_effect=[article, profile]):
            art = frontline.build_article(
                MagicMock(),
                "https://frontline.thehindu.com/x/a.ece",
                dt.datetime.now(IST),
            )

        self.assertIsNotNone(art)
        self.assertIn("<p><strong>One Author</strong></p>", art["body"])
        self.assertIn("<p><em>One Author is Deputy Editor.</em></p>", art["body"])


class TestIndiaTodayBylines(unittest.TestCase):
    def test_author_bio_prefers_short_description(self):
        pd = {
            "author": [
                {
                    "title": "A",
                    "short_description": "Editor, India Today",
                    "description": "A much longer biography paragraph.",
                }
            ]
        }
        self.assertEqual(indiatoday.author_bio(pd), "Editor, India Today")

    def test_author_bio_drops_group_name_junk(self):
        pd = {
            "author": [
                {
                    "title": "A",
                    "description": '<div class="text-formatted">\n India Today\n</div>',
                }
            ]
        }
        self.assertEqual(indiatoday.author_bio(pd), "")

    def test_build_article_bio_under_byline(self):
        page = json.dumps(
            {
                "props": {
                    "pageProps": {
                        "initialState": {
                            "server": {
                                "page_data": {
                                    "title": "A headline",
                                    "description": (
                                        "<p>Body paragraph one.</p>"
                                        "<p>Body paragraph two.</p>"
                                    ),
                                    "author": [
                                        {
                                            "title": "A Writer",
                                            "short_description": (
                                                "A Writer is a correspondent."
                                            ),
                                        }
                                    ],
                                    "datetime_published": "2026-10-10 09:00:00",
                                }
                            }
                        }
                    }
                }
            }
        )
        html = (
            '<script id="__NEXT_DATA__" type="application/json">' + page + "</script>"
        )

        with patch("indiatoday.fetch", return_value=html):
            art = indiatoday.build_article(
                MagicMock(),
                "https://www.indiatoday.in/magazine/x/story/1",
                dt.datetime.now(IST),
            )

        self.assertIsNotNone(art)
        self.assertIn("<p><strong>A Writer</strong></p>", art["body"])
        self.assertIn("<p><em>A Writer is a correspondent.</em></p>", art["body"])


if __name__ == "__main__":
    unittest.main()
