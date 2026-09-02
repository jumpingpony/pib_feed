#!/usr/bin/env python3
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import archive_pdfs


class TestArchivePdfs(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.manifest_dir = os.path.join(self.test_dir, "archive")
        self.public_dir = os.path.join(self.test_dir, "public")
        os.makedirs(self.manifest_dir, exist_ok=True)
        os.makedirs(self.public_dir, exist_ok=True)

        archive_pdfs.MANIFEST_DIR = self.manifest_dir
        archive_pdfs.REFERENCE_DIR = self.public_dir

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_release_titles(self):
        self.assertEqual(archive_pdfs.release_title("pdf-archive"), "Archive")
        self.assertEqual(archive_pdfs.release_title("image-archive"), "Image Archive")
        self.assertEqual(archive_pdfs.release_title("mygov-2026"), "MyGov Archive 2026")
        self.assertEqual(archive_pdfs.release_title("niti-2026"), "NITI Aayog Archive 2026")
        self.assertEqual(archive_pdfs.release_title("indianexpress-delhi-2026"), "Indian Express Delhi 2026")
        self.assertEqual(archive_pdfs.release_title("upsc-essentials-2026"), "UPSC Essentials 2026")
        self.assertEqual(archive_pdfs.release_title("visionias-pt365-2026"), "Vision IAS PT 365 Archive 2026")
        self.assertEqual(archive_pdfs.release_title("visionias-mains365-2025"), "Vision IAS Mains 365 Archive 2025")
        self.assertEqual(archive_pdfs.release_title("madeeasy-weekly-2024"), "Made Easy Current Affairs Archive 2024")
        self.assertEqual(archive_pdfs.release_title("made-easy-ca-2024"), "Made Easy Current Affairs Archive 2024")
        self.assertEqual(archive_pdfs.release_title("nextias-magazine-2025"), "NextIAS Magazine Archive 2025")
        self.assertEqual(archive_pdfs.release_title("economist-images-2026"), "Economist Images Archive 2026")

    def test_load_manifests_multi_release(self):
        m1 = [
            {"name": "delhi_2026-06-01.pdf", "url": "https://example.com/d1", "tag": "indianexpress-delhi-2026"},
            {"name": "delhi_2026-06-02.pdf", "url": "https://example.com/d2", "tag": "indianexpress-delhi-2026"},
        ]
        m2 = [
            {"name": "mygov_doc_1.pdf", "url": "https://example.com/m1", "tag": "mygov-2026"},
            {"name": "legacy_doc.pdf", "url": "https://example.com/leg"},  # no tag -> DEFAULT_TAG (pdf-archive)
        ]
        with open(os.path.join(self.manifest_dir, "feed1.json"), "w") as f:
            json.dump(m1, f)
        with open(os.path.join(self.manifest_dir, "feed2.json"), "w") as f:
            json.dump(m2, f)

        wanted = archive_pdfs.load_manifests()
        self.assertEqual(len(wanted), 3)
        self.assertIn("indianexpress-delhi-2026", wanted)
        self.assertIn("mygov-2026", wanted)
        self.assertIn("pdf-archive", wanted)

        self.assertEqual(len(wanted["indianexpress-delhi-2026"]), 2)
        self.assertEqual(wanted["mygov-2026"]["mygov_doc_1.pdf"], "https://example.com/m1")
        self.assertEqual(wanted["pdf-archive"]["legacy_doc.pdf"], "https://example.com/leg")

    def test_referenced_assets_multi_tag(self):
        feed_dir = os.path.join(self.public_dir, "feed1")
        os.makedirs(feed_dir, exist_ok=True)
        now = dt.datetime.now(dt.timezone.utc)
        now_str = now.strftime("%a, %d %b %Y %H:%M:%S +0000")

        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Legacy Item</title>
      <pubDate>{now_str}</pubDate>
      <enclosure url="https://github.com/jumpingpony/pib_feed/releases/download/pdf-archive/legacy_file.pdf" />
    </item>
    <item>
      <title>New Delhi Item</title>
      <pubDate>{now_str}</pubDate>
      <enclosure url="https://github.com/jumpingpony/pib_feed/releases/download/indianexpress-delhi-2026/delhi_2026-06-01.pdf" />
    </item>
    <item>
      <title>MyGov Item</title>
      <pubDate>{now_str}</pubDate>
      <link>https://github.com/jumpingpony/pib_feed/releases/download/mygov-2026/mygov_2026_01.pdf</link>
    </item>
  </channel>
</rss>"""
        with open(os.path.join(feed_dir, "feed.xml"), "w") as f:
            f.write(xml)

        referenced = archive_pdfs.referenced_assets(now=now)
        self.assertIn("pdf-archive", referenced)
        self.assertIn("legacy_file.pdf", referenced["pdf-archive"])

        self.assertIn("indianexpress-delhi-2026", referenced)
        self.assertIn("delhi_2026-06-01.pdf", referenced["indianexpress-delhi-2026"])

        self.assertIn("mygov-2026", referenced)
        self.assertIn("mygov_2026_01.pdf", referenced["mygov-2026"])

    def test_parse_args(self):
        args_default = archive_pdfs.parse_args([])
        self.assertFalse(args_default.verify)

        args_verify = archive_pdfs.parse_args(["--verify"])
        self.assertTrue(args_verify.verify)

        args_verify_only = archive_pdfs.parse_args(["--verify-only"])
        self.assertTrue(args_verify_only.verify)

    def test_upload_manifests_success(self):
        m = [{"name": "doc1.pdf", "url": "https://example.com/doc1", "tag": "mygov-2026"}]
        with open(os.path.join(self.manifest_dir, "feed.json"), "w") as f:
            json.dump(m, f)

        original_ensure = archive_pdfs.ensure_release
        original_existing = archive_pdfs.existing_assets
        original_upload = archive_pdfs.upload
        try:
            archive_pdfs.ensure_release = lambda tag: None
            archive_pdfs.existing_assets = lambda tag: set()
            archive_pdfs.upload = lambda tag, name, url: True

            ret = archive_pdfs.upload_manifests()
            self.assertEqual(ret, 0)
        finally:
            archive_pdfs.ensure_release = original_ensure
            archive_pdfs.existing_assets = original_existing
            archive_pdfs.upload = original_upload

    def test_upload_manifests_failure(self):
        m = [{"name": "doc1.pdf", "url": "https://example.com/doc1", "tag": "mygov-2026"}]
        with open(os.path.join(self.manifest_dir, "feed.json"), "w") as f:
            json.dump(m, f)

        original_ensure = archive_pdfs.ensure_release
        original_existing = archive_pdfs.existing_assets
        original_upload = archive_pdfs.upload
        try:
            archive_pdfs.ensure_release = lambda tag: None
            archive_pdfs.existing_assets = lambda tag: set()
            archive_pdfs.upload = lambda tag, name, url: False

            ret = archive_pdfs.upload_manifests()
            self.assertEqual(ret, 1)
        finally:
            archive_pdfs.ensure_release = original_ensure
            archive_pdfs.existing_assets = original_existing
            archive_pdfs.upload = original_upload

    def test_verify_references_success(self):
        feed_dir = os.path.join(self.public_dir, "feed1")
        os.makedirs(feed_dir, exist_ok=True)
        now = dt.datetime.now(dt.timezone.utc)
        now_str = now.strftime("%a, %d %b %Y %H:%M:%S +0000")
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Test Item</title>
      <pubDate>{now_str}</pubDate>
      <enclosure url="https://github.com/jumpingpony/pib_feed/releases/download/mygov-2026/mygov_2026_01.pdf" />
    </item>
  </channel>
</rss>"""
        with open(os.path.join(feed_dir, "feed.xml"), "w") as f:
            f.write(xml)

        original_existing = archive_pdfs.existing_assets
        try:
            archive_pdfs.existing_assets = lambda tag: {"mygov_2026_01.pdf"}
            ret = archive_pdfs.verify_references(now=now)
            self.assertEqual(ret, 0)
        finally:
            archive_pdfs.existing_assets = original_existing

    def test_verify_references_missing(self):
        feed_dir = os.path.join(self.public_dir, "feed1")
        os.makedirs(feed_dir, exist_ok=True)
        now = dt.datetime.now(dt.timezone.utc)
        now_str = now.strftime("%a, %d %b %Y %H:%M:%S +0000")
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Test Item</title>
      <pubDate>{now_str}</pubDate>
      <enclosure url="https://github.com/jumpingpony/pib_feed/releases/download/mygov-2026/mygov_2026_01.pdf" />
    </item>
  </channel>
</rss>"""
        with open(os.path.join(feed_dir, "feed.xml"), "w") as f:
            f.write(xml)

        original_existing = archive_pdfs.existing_assets
        try:
            archive_pdfs.existing_assets = lambda tag: set()
            ret = archive_pdfs.verify_references(now=now)
            self.assertEqual(ret, 1)
        finally:
            archive_pdfs.existing_assets = original_existing

    def test_main_routing(self):
        original_upload = archive_pdfs.upload_manifests
        original_verify = archive_pdfs.verify_references
        try:
            archive_pdfs.upload_manifests = lambda: 42
            archive_pdfs.verify_references = lambda: 84

            self.assertEqual(archive_pdfs.main([]), 42)
            self.assertEqual(archive_pdfs.main(["--verify"]), 84)

            os.environ["ARCHIVE_VERIFY_ONLY"] = "true"
            self.assertEqual(archive_pdfs.main([]), 84)
            os.environ.pop("ARCHIVE_VERIFY_ONLY", None)
        finally:
            archive_pdfs.upload_manifests = original_upload
            archive_pdfs.verify_references = original_verify


if __name__ == "__main__":
    unittest.main()
