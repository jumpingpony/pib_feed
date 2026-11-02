#!/usr/bin/env python3
"""EAC-PM: listing parse, fetch pacing, and failure signalling."""
import datetime as dt
import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from feeds import eacpm

import requests

NOW = dt.datetime(2026, 11, 1, 12, tzinfo=dt.timezone.utc)
PDF_A = "https://eacpm.gov.in/wp-content/uploads/2026/09/report-a.pdf"
PDF_B = "https://eacpm.gov.in/wp-content/uploads/2026/08/report-b.pdf"

CARD = (
    '<div class="col-lg-4 col-md-6 mb-5">'
    '<h2><a href="{link}">{title}</a></h2><p>{summary}</p></div>'
)


def listing(*cards: str) -> str:
    return (
        '<div class="tab-pane fade show active" id="nav-all-report">'
        + "".join(cards)
        + "</div>"
    )


def response(status: int = 200, text: str = "", encoding: str = "utf-8") -> Mock:
    return Mock(status_code=status, text=text, apparent_encoding=encoding)


class TestParseReports(unittest.TestCase):
    def test_category_tab_labels_the_all_tab_item(self):
        # The working-paper pane repeats the card; the All pane keeps one copy.
        page = listing(
            CARD.format(link=PDF_A, title="A", summary="Sum A"),
            CARD.format(link=PDF_B, title="B", summary="Sum B"),
        ) + (
            '<div class="tab-pane fade" id="nav-working-paper">'
            + CARD.format(link=PDF_B, title="B", summary="Sum B")
            + "</div>"
        )
        items = eacpm.parse_reports(page)

        self.assertEqual([item["link"] for item in items], [PDF_A, PDF_B])
        self.assertEqual([item["category"] for item in items], ["", "Working Papers"])


class TestFetchPacing(unittest.TestCase):
    def test_connect_and_read_timeouts_are_split(self):
        # A blocked host must fail inside the connect budget, not the read one.
        session = Mock()
        session.get.return_value = response(text="<html/>")

        eacpm.fetch(session, "https://eacpm.gov.in/reports/")

        timeout = session.get.call_args.kwargs["timeout"]
        self.assertEqual(timeout, (eacpm.CONNECT_TIMEOUT, eacpm.TIMEOUT))
        self.assertLess(eacpm.CONNECT_TIMEOUT, eacpm.TIMEOUT)

    def test_one_attempt_by_default(self):
        # The schedule is the retry mechanism for a monthly, single-page source.
        self.assertEqual(eacpm.RETRIES, 0)

    def test_connection_reset_is_retried_when_asked(self):
        session = Mock()
        session.get.side_effect = [
            requests.ConnectionError("reset"),
            response(text="<html>page</html>"),
        ]
        with patch.object(eacpm, "RETRIES", 1):
            self.assertEqual(eacpm.fetch(session, "u"), "<html>page</html>")
        self.assertEqual(session.get.call_count, 2)

    def test_gives_up_after_the_retry_budget(self):
        session = Mock()
        session.get.side_effect = requests.ConnectionError("reset")
        with patch.object(eacpm, "RETRIES", 2):
            self.assertIsNone(eacpm.fetch(session, "u"))
            self.assertEqual(session.get.call_count, 3)

    def test_missing_page_is_not_retried(self):
        session = Mock()
        session.get.return_value = response(status=404)
        self.assertIsNone(eacpm.fetch(session, "u"))
        self.assertEqual(session.get.call_count, 1)


class TestRunReports(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.out, True)

    def run_with(self, page: str | None, published: dict) -> tuple[int, bool]:
        with patch.object(eacpm, "OUT_DIR", self.out), patch.object(
            eacpm, "PUBLISHED_BASE_URL", "https://example.invalid"
        ), patch.object(eacpm, "load_published", return_value=dict(published)), patch.object(
            eacpm, "fetch", return_value=page
        ):
            return eacpm.run_reports(Mock(), NOW)

    def feed_path(self) -> str:
        return os.path.join(self.out, "eacpm-reports", "feed.xml")

    def published_item(self) -> dict:
        block = eacpm.render_item(PDF_A, "A", "<p>Sum A</p>", NOW).strip()
        return {PDF_A: (NOW, block)}

    def test_unreachable_listing_warns_and_keeps_published_history(self):
        # An upstream outage must not redden the build; the merged copy holds.
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            kept, ok = self.run_with(None, self.published_item())

        self.assertEqual(kept, 1)
        self.assertTrue(ok)
        self.assertIn("unreachable", stderr.getvalue())
        with open(self.feed_path(), encoding="utf-8") as handle:
            self.assertIn(PDF_A, handle.read())

    def test_unparsed_listing_reports_failure(self):
        # A redesign leaves the page reachable but the cards unmatched.
        kept, ok = self.run_with("<html><body>new layout</body></html>", self.published_item())

        self.assertEqual(kept, 1)
        self.assertFalse(ok)

    def test_unreachable_listing_without_history_writes_nothing(self):
        kept, ok = self.run_with(None, {})

        self.assertEqual(kept, 0)
        self.assertTrue(ok)
        self.assertFalse(os.path.exists(self.feed_path()))

    def test_new_cards_are_rendered_and_succeed(self):
        page = listing(CARD.format(link=PDF_A, title="A", summary="Sum A"))

        kept, ok = self.run_with(page, {})

        self.assertEqual(kept, 1)
        self.assertTrue(ok)
        with open(self.feed_path(), encoding="utf-8") as handle:
            body = handle.read()
        self.assertIn(f"<link>{PDF_A}</link>", body)


class TestMainExit(unittest.TestCase):
    def test_incomplete_build_exits_non_zero(self):
        with patch.object(eacpm, "make_session", return_value=Mock()), patch.object(
            eacpm, "run_reports", return_value=(1, False)
        ):
            self.assertEqual(eacpm.main(), 1)

    def test_complete_build_exits_zero(self):
        with patch.object(eacpm, "make_session", return_value=Mock()), patch.object(
            eacpm, "run_reports", return_value=(1, True)
        ):
            self.assertEqual(eacpm.main(), 0)


if __name__ == "__main__":
    unittest.main()
