#!/usr/bin/env python3
"""India Today magazine: author bio selection and the byline block."""
import datetime as dt
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from feeds import indiatoday

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


class TestAuthorBio(unittest.TestCase):
    def test_prefers_short_description(self):
        page_data = {
            "author": [
                {
                    "title": "A",
                    "short_description": "Editor, India Today",
                    "description": "A much longer biography paragraph.",
                }
            ]
        }
        self.assertEqual(indiatoday.author_bio(page_data), "Editor, India Today")

    def test_drops_group_name_junk(self):
        # Some bylines carry only the desk name in the description; printing it
        # as a bio would attribute the story to "India Today".
        page_data = {
            "author": [
                {
                    "title": "A",
                    "description": '<div class="text-formatted">\n India Today\n</div>',
                }
            ]
        }
        self.assertEqual(indiatoday.author_bio(page_data), "")


class TestArticleBody(unittest.TestCase):
    def test_bio_sits_under_the_byline(self):
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
                                            "short_description": "A Writer is a correspondent.",
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
        html = '<script id="__NEXT_DATA__" type="application/json">' + page + "</script>"

        with patch("feeds.indiatoday.fetch", return_value=html):
            built = indiatoday.build_article(
                MagicMock(),
                "https://www.indiatoday.in/magazine/x/story/1",
                dt.datetime.now(IST),
            )

        self.assertIsNotNone(built)
        self.assertIn("<p><strong>A Writer</strong></p>", built["body"])
        self.assertIn("<p><em>A Writer is a correspondent.</em></p>", built["body"])


if __name__ == "__main__":
    unittest.main()
