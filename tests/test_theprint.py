#!/usr/bin/env python3
"""ThePrint: feed keys, promo stripping, item rendering, byline resolution."""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from feeds import theprint

POST = {
    "id": 3060655,
    "date": "2026-10-03T00:11:44",
    "link": "https://theprint.in/50-word-edit/some-piece/3060655/",
    "title": {"rendered": "India and Pakistan have shaken hands"},
    "content": {"rendered": "<p>Fifty words.</p>"},
}


class TestFeedKeys(unittest.TestCase):
    def test_keys_match_inoreader_subscriptions(self):
        # Renaming a key silently empties a subscription; this pins the set.
        self.assertEqual(
            {feed["key"] for feed in theprint.FEEDS},
            {
                "theprint-national-interest",
                "theprint-essential",
                "theprint-50-word-edit",
                "theprint-diplomacy",
                "theprint-past-forward",
            },
        )


class TestBodySanitizing(unittest.TestCase):
    def test_strips_promos_and_attributes_but_keeps_attribution(self):
        raw = (
            '<p><span style="font-weight: 400;">Opening <strong class="ep-highlight">word</strong>.</span></p>'
            '<p><em><strong>Also Read:</strong> <a href="https://theprint.in/x/">Related piece</a></em></p>'
            "<hr />"
            "<p>&nbsp;</p>"
            '<figure><img src="https://staticprintenglish.theprint.in/a.jpg" width="800" height="400" />'
            "<figcaption>A caption</figcaption></figure>"
            "<p><i>Disclaimer: This report is auto generated.</i></p>"
            "<p>Edited by Test Editor</p>"
        )
        body = theprint.sanitize_body(raw)

        self.assertIn("Opening <strong>word</strong>.", body)
        self.assertNotIn("Also Read", body)
        self.assertNotIn("Disclaimer", body)
        self.assertIn("Edited by Test Editor", body)  # attribution is kept
        self.assertNotIn("style=", body.replace('style="max-width:100%;height:auto;"', ""))
        self.assertNotIn("class=", body)
        self.assertNotIn("<hr", body)
        self.assertIn(
            '<figure><img src="https://staticprintenglish.theprint.in/a.jpg" alt="" '
            'style="max-width:100%;height:auto;" /><figcaption>A caption</figcaption></figure>',
            body,
        )


class TestItemRendering(unittest.TestCase):
    def test_item_guid_and_body_roundtrip(self):
        item = theprint.render_item(POST)
        self.assertIn("<title>India and Pakistan have shaken hands</title>", item)
        self.assertIn(
            '<guid isPermaLink="true">https://theprint.in/50-word-edit/some-piece/3060655/</guid>',
            item,
        )
        self.assertIn(
            "<content:encoded><![CDATA[<p>Fifty words.</p>]]></content:encoded>", item
        )
        match = theprint.GUID_ID_RE.search(POST["link"])
        self.assertIsNotNone(match)
        self.assertEqual(int(match.group(1)), 3060655)

    def test_author_and_bio_lead_the_body(self):
        item = theprint.render_item(POST, "Shekhar Gupta", "Editor-in-Chief.")

        self.assertIn("<dc:creator>Shekhar Gupta</dc:creator>", item)
        self.assertIn(
            "<content:encoded><![CDATA[<p><strong>Shekhar Gupta</strong></p>\n"
            "<p><em>Editor-in-Chief.</em></p>\n<p>Fifty words.</p>]]></content:encoded>",
            item,
        )
        xml = theprint.build_feed(theprint.FEEDS[0], {1: item})
        self.assertIn('xmlns:dc="http://purl.org/dc/elements/1.1/"', xml)


class TestAuthorResolution(unittest.TestCase):
    def test_primary_author_only(self):
        # The REST `coauthors` field lists internal contributors the site never
        # prints, so resolving it would add names readers do not see.
        users = {24: {"name": "Shekhar Gupta", "description": "Editor-in-Chief of ThePrint."}}
        post = {"author": 24, "coauthors": [10186]}

        with patch("feeds.theprint.fetch_user", side_effect=lambda s, uid: users[uid]), patch(
            "feeds.theprint.USER_DELAY", 0
        ):
            name, bio = theprint.resolve_author(MagicMock(), post, {})

        self.assertEqual((name, bio), ("Shekhar Gupta", "Editor-in-Chief of ThePrint."))

    def test_post_without_author_has_no_byline(self):
        self.assertEqual(theprint.resolve_author(MagicMock(), {"author": 0}, {}), ("", ""))


if __name__ == "__main__":
    unittest.main()
