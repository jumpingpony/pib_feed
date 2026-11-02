#!/usr/bin/env python3
"""Feed audit rules: shape, ordering, cadence gaps, accepted gaps."""
import datetime as dt
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from tools import audit_feeds


def feed_xml(dates: list[dt.datetime], missing_date: bool = False) -> str:
    items = []
    for published in dates:
        stamp = "" if missing_date else f"<pubDate>{published.strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate>"
        items.append(f"<item><title>t</title>{stamp}</item>")
    return (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        "<title>t</title>" + "".join(items) + "</channel></rss>"
    )


class AuditTestCase(unittest.TestCase):
    def setUp(self):
        self.site = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.site, ignore_errors=True))

    def write(self, key: str, body: str) -> None:
        directory = os.path.join(self.site, key)
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, "feed.xml"), "w", encoding="utf-8") as f:
            f.write(body)

    def days_ago(self, *days: int) -> list[dt.datetime]:
        now = dt.datetime.now(dt.timezone.utc)
        return [now - dt.timedelta(days=day) for day in days]


class TestFeedShape(AuditTestCase):
    def test_healthy_feed_passes(self):
        self.write("press_releases", feed_xml(self.days_ago(0, 1, 2)))
        self.assertEqual(audit_feeds.audit(self.site, gaps={}), [])

    def test_empty_directory_fails(self):
        problems = audit_feeds.audit(self.site, gaps={})
        self.assertTrue(problems)
        self.assertIn("no feed.xml", problems[0])

    def test_broken_feeds_report_their_defect(self):
        cases = {
            "no items": (feed_xml([]), "feed has no items"),
            "missing pubDate": (feed_xml(self.days_ago(0, 1), missing_date=True), "without <pubDate>"),
            "malformed xml": ("<rss><channel><item>", "does not parse"),
            "no channel": ("<rss></rss>", "no <channel>"),
        }
        for label, (body, expected) in cases.items():
            with self.subTest(defect=label):
                self.write("press_releases", body)
                problems = audit_feeds.audit(self.site, gaps={})
                self.assertTrue(any(expected in p for p in problems), problems)


class TestOrdering(AuditTestCase):
    def test_out_of_order_items_fail(self):
        now = dt.datetime.now(dt.timezone.utc)
        self.write("press_releases", feed_xml([now - dt.timedelta(days=2), now]))
        problems = audit_feeds.audit(self.site, gaps={})
        self.assertTrue(any("out of order" in problem for problem in problems), problems)


class TestCadenceGaps(AuditTestCase):
    def test_gap_beyond_the_daily_limit_fails(self):
        self.write("press_releases", feed_xml(self.days_ago(0, 30)))
        problems = audit_feeds.audit(self.site, gaps={})
        self.assertTrue(any("gap between" in problem for problem in problems), problems)

    def test_accepted_gap_passes(self):
        self.write("press_releases", feed_xml(self.days_ago(0, 30)))
        older, newer = self.days_ago(30, 0)
        gaps = {"press_releases": [[older.strftime("%Y-%m-%d"), newer.strftime("%Y-%m-%d")]]}
        self.assertEqual(audit_feeds.audit(self.site, gaps=gaps), [])

    def test_historical_holes_are_not_checked(self):
        # Backfilled archives carry holes from before the feed was complete;
        # only the recent tail says whether the source is alive.
        now = dt.datetime.now(dt.timezone.utc)
        self.write(
            "press_releases",
            feed_xml([now - dt.timedelta(days=age) for age in (1, 200, 400, 600)]),
        )
        self.assertEqual(audit_feeds.audit(self.site, gaps={}), [])

    def test_seasonal_feeds_are_not_gap_checked(self):
        self.write("niti_reports", feed_xml(self.days_ago(0, 300)))
        self.assertEqual(audit_feeds.audit(self.site, gaps={}), [])

    def test_stale_feed_fails_even_when_evenly_spaced(self):
        # The silent failure mode: still parses, still sorted, stopped growing.
        now = dt.datetime.now(dt.timezone.utc)
        self.write(
            "press_releases",
            feed_xml([now - dt.timedelta(days=200 + offset) for offset in range(3)]),
        )
        problems = audit_feeds.audit(self.site, gaps={})
        self.assertTrue(any("days old" in problem for problem in problems), problems)

    def test_seasonal_feeds_are_not_freshness_checked(self):
        now = dt.datetime.now(dt.timezone.utc)
        self.write(
            "niti_reports",
            feed_xml([now - dt.timedelta(days=400 + offset) for offset in range(3)]),
        )
        self.assertEqual(audit_feeds.audit(self.site, gaps={}), [])

    def test_unknown_feeds_use_the_monthly_limit(self):
        # 30 days passes at monthly; 60 days is a real stop.
        self.write("some-new-feed", feed_xml(self.days_ago(0, 30)))
        self.assertEqual(audit_feeds.audit(self.site, gaps={}), [])

        self.write("some-new-feed", feed_xml(self.days_ago(0, 60)))
        self.assertTrue(any("gap between" in p for p in audit_feeds.audit(self.site, gaps={})))


class TestGapFile(AuditTestCase):
    def test_gaps_load_from_json_and_missing_file_is_empty(self):
        path = os.path.join(self.site, "gaps.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"press_releases": [["2026-08-22", "2026-09-02"]]}, f)

        self.assertEqual(
            audit_feeds.load_gaps(path), {"press_releases": [("2026-08-22", "2026-09-02")]}
        )
        self.assertEqual(audit_feeds.load_gaps(os.path.join(self.site, "absent.json")), {})

    def test_shipped_gap_file_is_valid_json(self):
        path = os.path.join(
            os.path.dirname(__file__), "..", ".github", "known-feed-gaps.json"
        )
        gaps = audit_feeds.load_gaps(os.path.abspath(path))
        self.assertIsInstance(gaps, dict)
        for key, ranges in gaps.items():
            with self.subTest(feed=key):
                for start, end in ranges:
                    self.assertLessEqual(start, end)


if __name__ == "__main__":
    unittest.main()
