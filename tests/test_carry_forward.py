#!/usr/bin/env python3
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from tools import carry_forward as carry

FEED = (
    "<rss><channel><title>Example feed</title>"
    "<item><title>a</title></item><item><title>b</title></item>"
    "</channel></rss>"
)


class TestCarryForward(unittest.TestCase):
    def test_keys_from_env_filters_blanks(self):
        with patch.object(carry.os, "environ", {"CARRY_KEYS": " a, ,b ,"}):
            self.assertEqual(carry.keys_from_env(), ["a", "b"])

    def test_write_feed_creates_both_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(carry, "OUT_DIR", tmp):
                carry.write_feed("key", FEED)
            directory = os.path.join(tmp, "key")
            self.assertTrue(os.path.exists(os.path.join(directory, "feed.xml")))
            with open(os.path.join(directory, "index.html"), encoding="utf-8") as handle:
                page = handle.read()
            self.assertIn("Example feed", page)
            self.assertIn("2 items", page)

    def test_main_without_base_url_is_noop(self):
        with patch.object(carry, "PUBLISHED_BASE_URL", ""), \
                patch.object(carry, "keys_from_env", return_value=["a"]):
            self.assertEqual(carry.main(), 0)

    def test_main_fails_when_a_feed_cannot_be_carried(self):
        session = MagicMock()
        session.get.side_effect = [
            MagicMock(status_code=404, text=""),
            MagicMock(status_code=200, text=FEED),
        ]
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(carry, "PUBLISHED_BASE_URL", "https://example.test"), \
                patch.object(carry, "OUT_DIR", tmp), \
                patch.object(carry, "keys_from_env", return_value=["missing", "ok"]), \
                patch.object(carry.requests, "Session", return_value=session):
            self.assertEqual(carry.main(), 1)
            self.assertTrue(os.path.exists(os.path.join(tmp, "ok", "feed.xml")))
            self.assertFalse(os.path.exists(os.path.join(tmp, "missing")))


if __name__ == "__main__":
    unittest.main()
