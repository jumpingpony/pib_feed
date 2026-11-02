#!/usr/bin/env python3
"""PIB: Oct 2026 title markup, English-twin resolution, PRID scan, cache versions."""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from feeds import pib_feed


def press_releases() -> dict:
    return next(feed for feed in pib_feed.FEEDS if feed["key"] == "press_releases")


class TestDetailParsing(unittest.TestCase):
    def test_title_comes_from_titleh2(self):
        # Oct 2026 template: the title moved into <h1 id="Titleh2"> and the old
        # <h2> is an empty placeholder.
        page = (
            "<html><body>"
            '<h1 id="Titleh2">Cabinet approves scheme</h1>'
            "<h2><br></h2>"
            "<div>03 Oct 2026 12:18 PM</div>"
            "</body></html>"
        )
        self.assertEqual(pib_feed.parse_detail(page)["title"], "Cabinet approves scheme")

    def test_title_falls_back_to_h2(self):
        page = "<h2>Legacy h2 title</h2><p>03 Oct 2026 12:18 PM</p>"
        self.assertEqual(pib_feed.parse_detail(page)["title"], "Legacy h2 title")


class TestTwinResolution(unittest.TestCase):
    def test_hindi_release_follows_english_twin(self):
        hindi = (
            '<h1 id="Titleh2">केंद्रीय मंत्री ने योजना को मंजूरी दी</h1>'
            '<a href="PressReleaseIframePage.aspx?PRID=200">English</a>'
            "<p>03 Oct 2026 12:18 PM</p>"
        )
        english = (
            '<h1 id="Titleh2">Union Minister approves scheme</h1>'
            "<p>03 Oct 2026 12:18 PM</p>"
            "<p>Body text.</p>"
        )

        def fake_fetch(session, url, **kwargs):
            return (hindi if "PRID=100" in url else english), False

        with patch("feeds.pib_feed.fetch", side_effect=fake_fetch):
            article, error = pib_feed.scrape_one(MagicMock(), press_releases(), 100)

        self.assertIsNotNone(article, f"expected twin article, err={error}")
        self.assertEqual(article["id"], 200)
        self.assertEqual(article["title"], "Union Minister approves scheme")
        self.assertIn("PRID=200", article["link"])


class TestPridScan(unittest.TestCase):
    def test_scans_forward_from_highest_checked(self):
        with patch("feeds.pib_feed.get_latest_prid", return_value=110):
            ids = pib_feed.collect_ids(MagicMock(), press_releases(), set(range(105, 109)))
        self.assertEqual(ids, [110, 109])

    def test_cold_start_is_bounded_by_scan_count(self):
        with patch("feeds.pib_feed.get_latest_prid", return_value=110), patch(
            "feeds.pib_feed.SCAN_COUNT", 5
        ):
            ids = pib_feed.collect_ids(MagicMock(), press_releases(), set())
        self.assertEqual(ids, [110, 109, 108, 107, 106])

    def test_forward_scan_drains_the_backlog_newest_first_per_batch(self):
        # After a quiet spell hundreds of ids can be new; queueing all of them
        # would blow the run's time budget, so the window is sliced to one batch
        # starting at the frontier, and later runs pick up the rest.
        with patch("feeds.pib_feed.get_latest_prid", return_value=9100), patch(
            "feeds.pib_feed.SCAN_COUNT", 5
        ):
            ids = pib_feed.collect_ids(MagicMock(), press_releases(), set(range(100, 105)))
        self.assertEqual(ids, [109, 108, 107, 106, 105])


class TestCacheVersioning(unittest.TestCase):
    """A parser fix must be able to force one rescan of the sources it broke."""

    def load(self, feed: dict) -> tuple[set, set]:
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            pib_feed, "OUT_DIR", tmp
        ), patch.object(pib_feed, "PUBLISHED_BASE_URL", ""):
            os.makedirs(os.path.join(tmp, feed["key"]), exist_ok=True)
            path = os.path.join(tmp, feed["key"], "cache.json")
            with open(path, "w") as f:
                json.dump({"checked": [1, 2, 3]}, f)
            _, checked, retry = pib_feed.load_published(MagicMock(), feed)
        return checked, retry

    def test_unversioned_cache_rescans_only_versioned_feeds(self):
        # press_releases and pmo bumped cache_version after the Oct 2026 parser
        # break; the year feeds kept their cache so a deploy is not a rescan.
        expected = {
            "press_releases": set(),
            "pmo": set(),
            "backgrounders": {1, 2, 3},
        }
        for key, checked in expected.items():
            feed = next(f for f in pib_feed.FEEDS if f["key"] == key)
            with self.subTest(feed=key):
                self.assertEqual(self.load(feed), (checked, set()))

    def test_roundtrip_keeps_retry(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            pib_feed, "OUT_DIR", tmp
        ), patch.object(pib_feed, "PUBLISHED_BASE_URL", ""):
            pib_feed.write_feed(press_releases(), "<rss/>", 0, {5, 6}, {7})
            _, checked, retry = pib_feed.load_published(MagicMock(), press_releases())
        self.assertEqual(checked, {5, 6})
        self.assertEqual(retry, {7})


if __name__ == "__main__":
    unittest.main()
