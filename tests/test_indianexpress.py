#!/usr/bin/env python3
"""Indian Express: byline ids, lead-author bio, body header."""
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from feeds import indianexpress


class TestBylines(unittest.TestCase):
    def test_api_items_keep_byline_ids(self):
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

    def test_names_keep_term_order_and_bio_comes_from_lead_author(self):
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
        with patch("feeds.indianexpress.fetch", side_effect=fake_fetch):
            indianexpress.attach_authors(MagicMock(), items)

        self.assertEqual(items[0]["author"], "B Two, A One")
        self.assertEqual(items[0]["author_bio"], "B Two is a correspondent.")

    def test_body_opens_with_author_and_bio(self):
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


if __name__ == "__main__":
    unittest.main()
