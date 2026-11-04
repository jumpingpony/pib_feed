#!/usr/bin/env python3
"""Tests for the Economist app-gateway builder. Network-free."""
import datetime as dt
import os
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from feeds import economist as ec

CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"


def article_teaser(teg_id="t1", section="Leaders", url="/leaders/2026/10/29/x"):
    return {
        "tegId": teg_id,
        "url": url,
        "headline": "Headline",
        "rubric": "Standfirst",
        "byline": "A Writer",
        "datePublished": "2026-10-29T11:00:00.000Z",
        "wordCount": 3,
        "section": {"name": section},
    }


def article_full(teg_id="t1", text="Body ■"):
    return {
        "tegId": teg_id,
        "body": [{"__typename": "ParagraphComponent", "text": text}],
        "tags": [{"name": "AI"}],
    }


class TestSigning(unittest.TestCase):
    def test_signature_is_stable(self):
        self.assertEqual(
            ec.sign("test-secret", "cid-123", "1700000000000"),
            "kXMPIx0JdoYSQ+qVDjK8nSdMmp6k5C7nzPKmV9rGtUk=",
        )

    def test_canonical_url(self):
        self.assertEqual(
            ec.canonical_url("https://www.economist.com/a/b?utm=x#frag"),
            "https://www.economist.com/a/b",
        )
        self.assertEqual(ec.canonical_url("/a/b"), "https://www.economist.com/a/b")


class TestInlineRendering(unittest.TestCase):
    def test_inline_ast(self):
        nodes = [
            {"type": "drop_caps", "children": [{"type": "text", "value": "N"}]},
            {"type": "scaps", "children": [{"type": "text", "value": "O TWO"}]},
            {"type": "text", "value": " lives "},
            {"type": "italic", "children": [{"type": "text", "value": "well"}]},
            {"type": "text", "value": " "},
            {
                "type": "internal_link",
                "attributes": [{"name": "href", "value": "https://example.test/a"}],
                "children": [{"type": "text", "value": "link"}],
            },
            {"type": "linebreak", "children": []},
            {"type": "ufinish", "children": [{"type": "text", "value": "■"}]},
        ]
        self.assertEqual(
            ec.render_inline(nodes),
            '<span class="drop-cap">N</span>'
            '<span class="small-caps">O TWO</span> lives <em>well</em> '
            '<a href="https://example.test/a">link</a><br>■',
        )

    def test_plain_inline_keeps_words_together(self):
        nodes = [
            {"type": "drop_caps", "children": [{"type": "text", "value": "A"}]},
            {"type": "text", "value": "nthropic"},
        ]
        self.assertEqual(ec.plain_inline(nodes), "Anthropic")

    def test_components(self):
        cases = [
            (
                "paragraph",
                {"__typename": "ParagraphComponent", "text": "Hello"},
                "<p>Hello</p>",
            ),
            (
                "crosshead",
                {"__typename": "CrossheadComponent", "text": "Head"},
                "<h2>Head</h2>",
            ),
            ("divider", {"__typename": "DividerComponent"}, "<hr>"),
            (
                "unordered list",
                {
                    "__typename": "UnorderedListComponent",
                    "items": [{"text": "One"}, {"text": "Two"}],
                },
                "<ul><li>One</li><li>Two</li></ul>",
            ),
        ]
        for label, node, expected in cases:
            with self.subTest(component=label):
                self.assertEqual(ec.render_component(node), expected)

    def test_image_component_is_absolute_and_captioned(self):
        figure = ec.render_component(
            {
                "__typename": "ImageComponent",
                "url": "/content-assets/x.png",
                "altText": "Chart",
                "caption": {"text": "A caption"},
                "credit": "The Economist",
            }
        )
        self.assertIn('src="https://www.economist.com/content-assets/x.png"', figure)
        self.assertIn("<figcaption>A caption", figure)

    def test_infobox_recurses(self):
        rendered = ec.render_component(
            {
                "__typename": "InfoboxComponent",
                "components": [
                    {"__typename": "ParagraphComponent", "text": "Dig deeper"},
                    {"__typename": "UnorderedListComponent", "items": [{"text": "One"}]},
                ],
            }
        )
        self.assertIn('<aside class="infobox">', rendered)
        self.assertIn("<p>Dig deeper</p>", rendered)
        self.assertIn("<li>One</li>", rendered)


class TestArticleRecord(unittest.TestCase):
    def test_record_fields(self):
        record = ec.article_record(article_teaser(), article_full())
        self.assertEqual(record["section"], "Leaders")
        self.assertEqual(record["headline"], "Headline")
        self.assertEqual(record["url"], "https://www.economist.com/leaders/2026/10/29/x")
        self.assertEqual(record["guid"], record["url"])
        self.assertTrue(record["permalink"])
        self.assertEqual(record["text"], "Body ■")
        self.assertEqual(record["tags"], ["AI"])

    def test_missing_body_is_empty(self):
        record = ec.article_record(article_teaser())
        self.assertEqual(record["html"], "")
        self.assertEqual(record["text"], "")

    def test_narration_audio_not_exposed(self):
        full = article_full()
        full["narration"] = {"url": "https://example.test/a.mp3"}
        record = ec.article_record(article_teaser(), full)
        xml = ec.feed_xml([record], "Title", "https://example.test/", "Desc")
        self.assertIsNone(ET.fromstring(xml).find("./channel/item/enclosure"))


class TestSelection(unittest.TestCase):
    body_text = "word " * 120

    def records(self):
        return [
            {**ec.article_record(article_teaser("a"), article_full("a", self.body_text)),
             "section": "Leaders"},
            {**ec.article_record(article_teaser("b"), article_full("b", self.body_text)),
             "section": "Business"},
            {**ec.article_record(
                article_teaser("c", "Podcasts", "/podcasts/2026/10/29/p"), article_full("c", self.body_text)),
             "section": "Podcasts"},
        ]

    def test_article_feeds_drop_podcasts(self):
        for sections in (None, {"Leaders"}, {"Business"}):
            kept = ec.select_article_records(self.records(), sections)
            self.assertTrue(kept)
            self.assertFalse(any(ec.is_podcast(
                record["section"], record["url"]) for record in kept))
            self.assertTrue(all(record["section"] != "Podcasts" for record in kept))

    def test_section_filter(self):
        kept = ec.select_article_records(self.records(), {"Business"})
        self.assertEqual([record["section"] for record in kept], ["Business"])

    def test_short_bodies_are_dropped(self):
        record = {**ec.article_record(article_teaser("d"), article_full("d", "one")),
                  "section": "Leaders"}
        self.assertEqual(ec.select_article_records([record], None), [])

    def test_merge_teasers_dedupes_and_drops_podcasts(self):
        podcast = article_teaser("p", "Podcasts", "/podcasts/2026/10/29/p")
        issue = [article_teaser("a")]
        latest = [article_teaser("a"), podcast, article_teaser("b", "Business")]
        merged = ec.merge_teasers(issue, latest)
        self.assertEqual([teaser["tegId"] for teaser in merged], ["a", "b"])

    def test_is_podcast(self):
        self.assertTrue(ec.is_podcast("Podcasts", ""))
        self.assertTrue(ec.is_podcast("", "https://www.economist.com/podcasts/2026/10/29/x"))
        self.assertFalse(ec.is_podcast("Leaders", "https://www.economist.com/leaders/2026/10/29/x"))


class TestImages(unittest.TestCase):
    def test_data_uri_is_resized_webp(self):
        buffer = __import__("io").BytesIO()
        __import__("PIL.Image", fromlist=["Image"]).new("RGB", (1440, 800), (200, 30, 30)).save(buffer, "PNG")

        class Response:
            status_code = 200
            content = buffer.getvalue()

        class Session:
            def get(self, url, headers=None, timeout=None):
                return Response()

        uri = ec.image_data_uri("https://example.test/x.png", Session())
        self.assertTrue(uri.startswith("data:image/webp;base64,"))
        payload = __import__("base64").b64decode(uri.split(",", 1)[1])
        image = __import__("PIL.Image", fromlist=["Image"]).open(__import__("io").BytesIO(payload))
        self.assertEqual(image.width, ec.IMAGE_WIDTH)

    def test_data_uris_are_left_alone(self):
        body, added, failed = ec.inline_html(
            '<img src="data:image/webp;base64,AAAA">', {}, None
        )
        self.assertEqual((body, added, failed), ('<img src="data:image/webp;base64,AAAA">', 0, 0))


class TestIndicators(unittest.TestCase):
    def record(self):
        teaser = article_teaser(
            "i", "Economic & financial indicators",
            "/economic-and-financial-indicators/2026/10/29/economic-data-commodities-and-markets",
        )
        full = {
            "tegId": "i",
            "body": [
                {
                    "__typename": "ImageComponent",
                    "url": "https://www.economist.com/content-assets/images/x.png",
                    "credit": "The Economist",
                }
            ],
        }
        return ec.article_record(teaser, full)

    def test_image_only_item_kept_only_without_word_floor(self):
        record = self.record()
        self.assertEqual(
            ec.select_article_records([record], {"Economic & financial indicators"}), []
        )
        kept = ec.select_article_records(
            [record], {"Economic & financial indicators"}, min_words=0
        )
        self.assertEqual(len(kept), 1)
        self.assertIn("<img", kept[0]["html"])


class TestTwib(unittest.TestCase):
    def payload(self):
        return {
            "id": "twib-1",
            "datePublished": "2026-10-30T03:19:39.000Z",
            "body": {
                "gobbet": [{"text": "Gobbet one."}],
                "chunk": [
                    {
                        "title": "Chunk head",
                        "components": [{"text": "Chunk text."}],
                        "leadImage": {"url": "/content-assets/x.png", "altText": "img"},
                    }
                ],
                "zinger": {"quote": {"text": "Quote"}, "author": "Someone"},
            },
        }

    def test_twib_record(self):
        record = ec.twib_record(self.payload())
        self.assertIn("30 October 2026", record["headline"])
        self.assertIn("Gobbet one.", record["text"])
        self.assertIn("Chunk head", record["text"])
        self.assertIn("Quote", record["text"])
        self.assertFalse(record["permalink"])
        self.assertEqual(record["guid"], "twib-1")

    def test_feed_guid_is_not_permalink(self):
        record = ec.twib_record(self.payload())
        xml = ec.feed_xml([record], "TWIB", "https://example.test/", "Desc")
        item = ET.fromstring(xml).find("./channel/item")
        self.assertEqual(item.find("guid").get("isPermaLink"), "false")


class TestFeedXml(unittest.TestCase):
    def test_feed_is_valid(self):
        record = ec.article_record(article_teaser(), article_full())
        xml = ec.feed_xml([record], "Title", "https://example.test/", "Desc")
        root = ET.fromstring(xml)
        channel = root.find("channel")
        self.assertEqual(len(channel.findall("item")), 1)
        item = channel.find("item")
        self.assertEqual(item.findtext("title"), "Headline")
        self.assertIn("Body ■", item.findtext(CONTENT))
        self.assertEqual(item.findtext("guid"), record["url"])

    def test_records_sort_newest_first(self):
        older = ec.article_record(article_teaser("a"), article_full("a", "one two three"))
        newer = ec.article_record(article_teaser("b"), article_full("b", "one two three"))
        older["headline"], newer["headline"] = "Older", "Newer"
        older["published"] = "2026-10-20T00:00:00.000Z"
        newer["published"] = "2026-10-30T00:00:00.000Z"

        xml = ec.feed_xml([older, newer], "Title", "https://example.test/", "Desc")
        titles = [item.findtext("title") for item in ET.fromstring(xml).findall("./channel/item")]

        self.assertEqual(titles, ["Newer", "Older"])


class TestFeedKeys(unittest.TestCase):
    def test_published_feed_keys_are_stable(self):
        # These keys are the subscription URLs; a rename re-subscribes readers.
        # ecnmst-podcasts was retired on 2026-11-04 and stays unpublished.
        self.assertEqual(
            set(ec.FEEDS),
            {
                "ecnmst-all",
                "ecnmst-leaders",
                "ecnmst-business",
                "ecnmst-finance-and-economics",
                "ecnmst-by-invitation",
                "ecnmst-indicators",
                "ecnmst-world-in-brief",
            },
        )

    def test_no_article_feed_targets_podcasts(self):
        for feed in ec.FEEDS.values():
            if feed["kind"] == "articles" and feed["sections"]:
                self.assertNotIn("Podcasts", feed["sections"])


if __name__ == "__main__":
    unittest.main()
