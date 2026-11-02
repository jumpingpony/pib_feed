#!/usr/bin/env python3
"""Frontline: byline slugs, profile line, author block at the top of the body."""
import datetime as dt
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from feeds import frontline

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

ARTICLE = (
    '<meta property="og:title" content="A headline" />'
    '<meta property="og:description" content="A standfirst." />'
    '<div id="content-body-9" class="articlebodycontent" itemprop="articleBody">'
    "<p>First paragraph of the story.</p>"
    '<div class="comments-shares'
)


class TestBylines(unittest.TestCase):
    def setUp(self):
        frontline._PROFILE_LINES.clear()
        frontline._PROFILE_LOOKUPS[0] = 0

    def test_only_byline_links_count_as_authors(self):
        # Profile links appear in navigation too; only the byline class is a name.
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
        with patch("feeds.frontline.fetch", side_effect=[meta, role]):
            self.assertEqual(
                frontline.profile_line(MagicMock(), "vaishna-roy-16745"),
                "Vaishna Roy is Editor, Frontline.",
            )
            self.assertEqual(
                frontline.profile_line(MagicMock(), "soni-mishra-24635"),
                "Deputy Editor",
            )

    def test_article_body_opens_with_author(self):
        article = (
            '<a href="https://frontline.thehindu.com/profile/author/one-1/" '
            'class="person-name lnk">One Author</a>' + ARTICLE
        )
        profile = '<meta name="description" content="One Author is Deputy Editor.">'

        with patch("feeds.frontline.fetch", side_effect=[article, profile]):
            built = frontline.build_article(
                MagicMock(),
                "https://frontline.thehindu.com/x/a.ece",
                dt.datetime.now(IST),
            )

        self.assertIsNotNone(built)
        self.assertIn("<p><strong>One Author</strong></p>", built["body"])
        self.assertIn("<p><em>One Author is Deputy Editor.</em></p>", built["body"])


if __name__ == "__main__":
    unittest.main()
