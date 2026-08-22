#!/usr/bin/env python3
import unittest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts.backfill_releases import classify_asset, release_title


class TestBackfillClassification(unittest.TestCase):
    def test_indianexpress_delhi(self):
        self.assertEqual(classify_asset("indianexpress-delhi_2026-06-01.pdf"), "indianexpress-delhi-2026")
        self.assertEqual(classify_asset("indianexpress-delhi_2025-12-31.pdf"), "indianexpress-delhi-2025")

    def test_upsc_essentials(self):
        self.assertEqual(classify_asset("upsc-essentials_2026-01-13.pdf"), "upsc-essentials-2026")

    def test_indianexpress_eye_omitted(self):
        # Eye is legacy/untracked; remains exclusively on pdf-archive
        self.assertIsNone(classify_asset("indianexpress-eye_2026-06-01.pdf"))

    def test_visionias_pt365(self):
        self.assertEqual(
            classify_asset("visionias_pt-365_2025_species-in-news_7918.pdf"),
            "visionias-pt365-2025",
        )
        self.assertEqual(
            classify_asset("visionias_pt-365_2026_pt-365-culture_13229.pdf"),
            "visionias-pt365-2026",
        )

    def test_visionias_mains365(self):
        self.assertEqual(
            classify_asset("visionias_mains-365_2025_key-data-facts_9754.pdf"),
            "visionias-mains365-2025",
        )
        self.assertEqual(
            classify_asset("visionias_mains-365_2026_mains-365-economy_15173.pdf"),
            "visionias-mains365-2026",
        )

    def test_made_easy_ca(self):
        self.assertEqual(
            classify_asset("madeeasy_weekly_2024-05-10_abc.pdf"),
            "made-easy-ca-2024",
        )
        self.assertEqual(
            classify_asset("madeeasy_weekly_2025-11-20_def.pdf"),
            "made-easy-ca-2025",
        )
        self.assertEqual(
            classify_asset("madeeasy_weekly_2026-01-15_ghi.pdf"),
            "made-easy-ca-2026",
        )

    def test_nextias_magazine(self):
        self.assertEqual(
            classify_asset("nextias_monthly-current-affairs-apr-2026.pdf"),
            "nextias-magazine-2026",
        )
        self.assertEqual(
            classify_asset("nextias_monthly-current-affairs_2025-08-01.pdf"),
            "nextias-magazine-2025",
        )
        self.assertEqual(
            classify_asset("nextias_monthly-current-affairs-dec-2024.pdf"),
            "nextias-magazine-2024",
        )

    def test_mygov_merged_per_year(self):
        # 1718000000 = June 2024
        self.assertEqual(classify_asset("mygov_bharat_matters_1718000000_abc.pdf"), "mygov-2024")
        # 1740000000 = Feb 2025
        self.assertEqual(classify_asset("mygov_pulse_1740000000_def.pdf"), "mygov-2025")
        # 1775000000 = April 2026
        self.assertEqual(classify_asset("mygov_mann_ki_baat_1775000000_ghi.pdf"), "mygov-2026")
        # Date in filename with future/past year in slug
        self.assertEqual(
            classify_asset("mygov_pulse_2026-01-08_good-governance-pathway-2026-and-viksit-bharat-2047.pdf"),
            "mygov-2026",
        )
        self.assertEqual(
            classify_asset("mygov_pulse_2025-08-21_5-years-nep-2020.pdf"),
            "mygov-2025",
        )
        self.assertEqual(
            classify_asset("mygov_pulse_2026-08-18_six-years-nep-2020.pdf"),
            "mygov-2026",
        )

    def test_niti_merged_per_year(self):
        self.assertEqual(classify_asset("niti_2023-05_policy_report.pdf"), "niti-2023")
        self.assertEqual(classify_asset("niti_2024-10_working_paper.pdf"), "niti-2024")
        self.assertEqual(classify_asset("niti_2025-06_division_report.pdf"), "niti-2025")
        self.assertEqual(classify_asset("niti_2026-01_NITI_WORKING_PAPER_Report.pdf"), "niti-2026")

    def test_economist_images(self):
        self.assertEqual(classify_asset("sample_chart.jpg", "image-archive"), "economist-images-2026")
        self.assertEqual(classify_asset("sample_photo.png", "image-archive"), "economist-images-2026")

    def test_release_titles(self):
        self.assertEqual(release_title("mygov-2026"), "MyGov Archive 2026")
        self.assertEqual(release_title("niti-2026"), "NITI Aayog Archive 2026")
        self.assertEqual(release_title("indianexpress-delhi-2026"), "Indian Express Delhi 2026")
        self.assertEqual(release_title("upsc-essentials-2026"), "UPSC Essentials 2026")
        self.assertEqual(release_title("visionias-pt365-2026"), "Vision IAS PT 365 Archive 2026")
        self.assertEqual(release_title("made-easy-ca-2026"), "Made Easy Current Affairs Archive 2026")
        self.assertEqual(release_title("nextias-magazine-2026"), "NextIAS Magazine Archive 2026")
        self.assertEqual(release_title("economist-images-2026"), "Economist Images Archive 2026")


if __name__ == "__main__":
    unittest.main()
