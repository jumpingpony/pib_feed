#!/usr/bin/env python3
"""Shared fetch decoding: never run chardet over multi-megabyte XML or JSON."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from feeds import newsonair_feed, pib_feed

MODULES = (pib_feed, newsonair_feed)


class FakeResponse:
    def __init__(self, content_type: str, text: str, encoding=None, sniffed=None):
        self.headers = {"Content-Type": content_type}
        self.text = text
        self.encoding = encoding
        self._sniffed = sniffed
        self.sniffed = False

    @property
    def apparent_encoding(self):
        self.sniffed = True
        if self._sniffed is None:
            raise AssertionError("chardet must not run for this response")
        return self._sniffed


class TestResponseDecoding(unittest.TestCase):
    def test_xml_without_charset_skips_sniffing(self):
        for module in MODULES:
            with self.subTest(module=module.__name__):
                response = FakeResponse("application/xml", "<rss/>")
                self.assertEqual(module._response_text(response), "<rss/>")
                self.assertFalse(response.sniffed)
                self.assertEqual(response.encoding, "utf-8")

    def test_json_without_charset_skips_sniffing(self):
        for module in MODULES:
            with self.subTest(module=module.__name__):
                response = FakeResponse("application/json", "{}")
                self.assertEqual(module._response_text(response), "{}")
                self.assertFalse(response.sniffed)

    def test_undeclared_html_uses_sniffed_encoding(self):
        for module in MODULES:
            with self.subTest(module=module.__name__):
                response = FakeResponse("text/html", "<html/>", sniffed="utf-8")
                self.assertEqual(module._response_text(response), "<html/>")
                self.assertTrue(response.sniffed)
                self.assertEqual(response.encoding, "utf-8")

    def test_preset_encoding_is_not_sniffed(self):
        # requests sets .encoding from a declared charset; the helper must not
        # second-guess it with a sniff.
        for module in MODULES:
            with self.subTest(module=module.__name__):
                response = FakeResponse(
                    "text/html; charset=iso-8859-1", "<html/>", encoding="iso-8859-1"
                )
                module._response_text(response)
                self.assertFalse(response.sniffed)
                self.assertEqual(response.encoding, "iso-8859-1")


if __name__ == "__main__":
    unittest.main()
