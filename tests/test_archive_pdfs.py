#!/usr/bin/env python3
"""PDF archiver: release naming, manifest loading, reference verification."""
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from tools import archive_pdfs

FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    {items}
  </channel>
</rss>"""


def item(pub_date: dt.datetime, tag: str, name: str, element: str = "enclosure") -> str:
    stamp = pub_date.strftime("%a, %d %b %Y %H:%M:%S +0000")
    href = f"https://github.com/jumpingpony/pib_feed/releases/download/{tag}/{name}"
    if element == "enclosure":
        return f'<item><title>t</title><pubDate>{stamp}</pubDate><enclosure url="{href}" /></item>'
    return f'<item><title>t</title><pubDate>{stamp}</pubDate><link>{href}</link></item>'


class ArchiveTestCase(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.manifest_dir = os.path.join(self.test_dir, "archive")
        self.public_dir = os.path.join(self.test_dir, "public")
        os.makedirs(self.manifest_dir, exist_ok=True)
        os.makedirs(self.public_dir, exist_ok=True)

        self.addCleanup(shutil.rmtree, self.test_dir)
        for name, value in (("MANIFEST_DIR", self.manifest_dir), ("REFERENCE_DIR", self.public_dir)):
            original = getattr(archive_pdfs, name)
            setattr(archive_pdfs, name, value)
            self.addCleanup(setattr, archive_pdfs, name, original)

    def write_feed(self, body: str, key: str = "feed1") -> None:
        directory = os.path.join(self.public_dir, key)
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, "feed.xml"), "w", encoding="utf-8") as f:
            f.write(body)

    def write_manifest(self, entries: list[dict], name: str = "feed.json") -> None:
        with open(os.path.join(self.manifest_dir, name), "w", encoding="utf-8") as f:
            json.dump(entries, f)


class TestReleaseTitles(ArchiveTestCase):
    def test_release_titles_name_the_publisher(self):
        expected = {
            "pdf-archive": "Archive",
            "image-archive": "Image Archive",
            "mygov-2026": "MyGov Archive 2026",
            "niti-2026": "NITI Aayog Archive 2026",
            "indianexpress-delhi": "Indian Express Delhi",
            "upsc-essentials-2026": "UPSC Essentials 2026",
            "visionias-pt365-2026": "Vision IAS PT 365 Archive 2026",
            "visionias-mains365-2025": "Vision IAS Mains 365 Archive 2025",
            "madeeasy-weekly-2024": "Made Easy Current Affairs Archive 2024",
            "nextias-magazine-2025": "NextIAS Magazine Archive 2025",
        }
        for tag, title in expected.items():
            with self.subTest(tag=tag):
                self.assertEqual(archive_pdfs.release_title(tag), title)


class TestManifests(ArchiveTestCase):
    def test_tags_group_uploads_and_untagged_entries_fall_back(self):
        self.write_manifest(
            [
                {"name": "delhi_2026-06-01.pdf", "url": "https://example.com/d1", "tag": "indianexpress-delhi-2026"},
                {"name": "delhi_2026-06-02.pdf", "url": "https://example.com/d2", "tag": "indianexpress-delhi-2026"},
            ],
            name="feed1.json",
        )
        self.write_manifest(
            [
                {"name": "mygov_doc_1.pdf", "url": "https://example.com/m1", "tag": "mygov-2026"},
                {"name": "legacy_doc.pdf", "url": "https://example.com/leg"},
            ],
            name="feed2.json",
        )

        wanted = archive_pdfs.load_manifests()
        self.assertEqual(len(wanted), 3)
        self.assertEqual(len(wanted["indianexpress-delhi-2026"]), 2)
        self.assertEqual(wanted["mygov-2026"]["mygov_doc_1.pdf"], "https://example.com/m1")
        self.assertEqual(wanted["pdf-archive"]["legacy_doc.pdf"], "https://example.com/leg")


class TestUploads(ArchiveTestCase):
    def test_exit_code_reports_upload_failures(self):
        self.write_manifest([{"name": "doc1.pdf", "url": "https://example.com/doc1", "tag": "mygov-2026"}])

        for uploads, expected in ((True, 0), (False, 1)):
            with self.subTest(upload_succeeded=uploads), patch.multiple(
                archive_pdfs,
                ensure_release=lambda tag: None,
                existing_assets=lambda tag: set(),
                upload=lambda tag, name, url: uploads,
            ):
                self.assertEqual(archive_pdfs.upload_manifests(), expected)


class TestReferenceVerification(ArchiveTestCase):
    def test_referenced_assets_span_every_tag(self):
        now = dt.datetime.now(dt.timezone.utc)
        self.write_feed(
            FEED_XML.format(
                items="\n".join(
                    [
                        item(now, "pdf-archive", "legacy_file.pdf"),
                        item(now, "indianexpress-delhi-2026", "delhi_2026-06-01.pdf"),
                        item(now, "mygov-2026", "mygov_2026_01.pdf", element="link"),
                    ]
                )
            )
        )

        referenced = archive_pdfs.referenced_assets(now=now)
        for tag, name in (
            ("pdf-archive", "legacy_file.pdf"),
            ("indianexpress-delhi-2026", "delhi_2026-06-01.pdf"),
            ("mygov-2026", "mygov_2026_01.pdf"),
        ):
            with self.subTest(tag=tag):
                self.assertIn(name, referenced[tag])

    def test_verify_days_zero_audits_the_full_history(self):
        old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=400)
        self.write_feed(FEED_XML.format(items=item(old, "mygov-2024", "old_file.pdf")))

        original = archive_pdfs.VERIFY_DAYS
        self.addCleanup(setattr, archive_pdfs, "VERIFY_DAYS", original)

        archive_pdfs.VERIFY_DAYS = 1
        self.assertNotIn("mygov-2024", archive_pdfs.referenced_assets())

        archive_pdfs.VERIFY_DAYS = 0
        self.assertIn("old_file.pdf", archive_pdfs.referenced_assets()["mygov-2024"])

    def test_missing_assets_fail_unless_allowlisted(self):
        now = dt.datetime.now(dt.timezone.utc)
        self.write_feed(FEED_XML.format(items=item(now, "mygov-2026", "mygov_2026_01.pdf")))
        allowlist = os.path.join(self.test_dir, "allow.json")
        with open(allowlist, "w", encoding="utf-8") as f:
            json.dump({"mygov-2026": ["mygov_2026_01.pdf"]}, f)

        original = archive_pdfs.ALLOWLIST_PATH
        self.addCleanup(setattr, archive_pdfs, "ALLOWLIST_PATH", original)

        cases = (({"mygov_2026_01.pdf"}, "", 0), (set(), "", 1), (set(), allowlist, 0))
        for present, allow, expected in cases:
            with self.subTest(present=present, allowlisted=bool(allow)):
                archive_pdfs.ALLOWLIST_PATH = allow
                with patch.object(archive_pdfs, "existing_assets", return_value=present):
                    self.assertEqual(archive_pdfs.verify_references(now=now), expected)


class TestCli(unittest.TestCase):
    def test_flags_and_env_select_the_mode(self):
        with patch.multiple(
            archive_pdfs,
            upload_manifests=lambda: 42,
            verify_references=lambda: 84,
        ):
            self.assertEqual(archive_pdfs.main([]), 42)
            self.assertEqual(archive_pdfs.main(["--verify"]), 84)
            self.assertEqual(archive_pdfs.main(["--verify-only"]), 84)
            with patch.dict(os.environ, {"ARCHIVE_VERIFY_ONLY": "true"}):
                self.assertEqual(archive_pdfs.main([]), 84)


if __name__ == "__main__":
    unittest.main()
