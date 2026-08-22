#!/usr/bin/env python3
"""Backfill legacy assets from pdf-archive and image-archive into partitioned releases.

Copies assets into cleanly organized per-feed and per-year releases without deleting
or modifying anything in the legacy releases, preserving 100% link durability.

Usage:
    python3 scripts/backfill_releases.py --dry-run
    python3 scripts/backfill_releases.py
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import requests

REPO = os.environ.get("GITHUB_REPOSITORY", "nappingcats/pib_feed")
LEGACY_PDF_TAG = "pdf-archive"
LEGACY_IMG_TAG = "image-archive"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.76 Safari/537.36"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def gh(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=check)


def gh_retry(*args: str, tries: int = 4) -> subprocess.CompletedProcess:
    delay = 2.0
    res = gh(*args, check=False)
    for attempt in range(1, tries):
        if res.returncode == 0:
            return res
        print(
            f"  gh {' '.join(args)} failed (attempt {attempt}/{tries}): "
            f"{res.stderr.strip()[:200]}",
            file=sys.stderr,
            flush=True,
        )
        time.sleep(delay)
        delay *= 2
        res = gh(*args, check=False)
    return res


def classify_asset(name: str, source_release: str = LEGACY_PDF_TAG) -> Optional[str]:
    """Determine the target partitioned release tag for a given asset name.

    Returns None if the asset should remain exclusively in the legacy release.
    """
    if source_release == LEGACY_IMG_TAG or name.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
        return "economist-images-2026"

    # Untracked legacy feed: leave on pdf-archive
    if name.startswith("indianexpress-eye_"):
        return None

    # Indian Express Delhi
    m = re.search(r"indianexpress-delhi_(\d{4})", name)
    if m:
        return f"indianexpress-delhi-{m.group(1)}"

    # UPSC Essentials
    m = re.search(r"upsc-essentials_(\d{4})", name)
    if m:
        return f"upsc-essentials-{m.group(1)}"

    # Vision IAS PT 365
    m = re.search(r"visionias_pt-365_(\d{4})", name)
    if m:
        return f"visionias-pt365-{m.group(1)}"

    # Vision IAS Mains 365
    m = re.search(r"visionias_mains-365_(\d{4})", name)
    if m:
        return f"visionias-mains365-{m.group(1)}"

    # Made Easy Current Affairs
    m = re.search(r"madeeasy_weekly_(\d{4})", name)
    if m:
        return f"made-easy-ca-{m.group(1)}"

    # NextIAS Magazine
    m = re.search(r"nextias.*(?:-|_)(\d{4})", name)
    if m:
        return f"nextias-magazine-{m.group(1)}"

    # MyGov (merged across all MyGov publications per year)
    # 1. Standard format: mygov_{src}_{YYYY-MM-DD}_{slug}.pdf
    m = re.search(r"mygov_.*?_(\d{4})-\d{2}-\d{2}", name)
    if m:
        return f"mygov-{m.group(1)}"

    # 2. Legacy timestamp format: mygov_..._{10-digit-timestamp}_...
    m = re.search(r"mygov_.*_(\d{10})_", name)
    if m:
        try:
            year = dt.datetime.fromtimestamp(int(m.group(1)), tz=IST).year
            return f"mygov-{year}"
        except (ValueError, OSError):
            pass

    # NITI Aayog (merged across all NITI publications per year)
    m = re.search(r"niti_(\d{4})", name)
    if m:
        return f"niti-{m.group(1)}"

    return None


def release_title(tag: str) -> str:
    """Generate a clean, human-readable title for a release tag."""
    if tag.startswith("mygov-"):
        return f"MyGov Archive {tag.split('-', 1)[1]}"
    if tag.startswith("niti-"):
        return f"NITI Aayog Archive {tag.split('-', 1)[1]}"
    if tag.startswith("indianexpress-delhi-"):
        return f"Indian Express Delhi {tag.split('-', 2)[2]}"
    if tag.startswith("upsc-essentials-"):
        return f"UPSC Essentials {tag.split('-', 2)[2]}"
    if tag.startswith("visionias-pt365-"):
        return f"Vision IAS PT 365 Archive {tag.split('-', 2)[2]}"
    if tag.startswith("visionias-mains365-"):
        return f"Vision IAS Mains 365 Archive {tag.split('-', 2)[2]}"
    if tag.startswith("made-easy-ca-"):
        return f"Made Easy Current Affairs Archive {tag.split('-', 3)[3]}"
    if tag.startswith("nextias-magazine-"):
        return f"NextIAS Magazine Archive {tag.split('-', 2)[2]}"
    if tag.startswith("economist-images-"):
        return f"Economist Images Archive {tag.split('-', 2)[2]}"
    return tag.replace("-", " ").title()


def get_existing_assets(tag: str) -> set[str]:
    res = gh("release", "view", tag, "--repo", REPO, "--json", "assets", check=False)
    if res.returncode != 0:
        return set()
    try:
        data = json.loads(res.stdout)
        return {a["name"] for a in data.get("assets", [])}
    except ValueError:
        return set()


def ensure_release(tag: str, dry_run: bool = False) -> bool:
    res = gh("release", "view", tag, "--repo", REPO, check=False)
    if res.returncode == 0:
        return True
    title = release_title(tag)
    print(f"Creating release {tag} ({title})...", flush=True)
    if dry_run:
        return True
    res = gh(
        "release",
        "create",
        tag,
        "--repo",
        REPO,
        "--title",
        title,
        "--notes",
        f"Archived publication files for {title}. Managed automatically.",
        check=False,
    )
    return res.returncode == 0


def copy_asset(source_tag: str, target_tag: str, name: str, dry_run: bool = False) -> bool:
    url = f"https://github.com/{REPO}/releases/download/{source_tag}/{name}"
    if dry_run:
        print(f"  [dry-run] copy {name} -> {target_tag}", flush=True)
        return True

    try:
        with requests.get(url, stream=True, timeout=120, allow_redirects=True, headers={"User-Agent": UA}) as r:
            if r.status_code != 200:
                print(f"  download failed HTTP {r.status_code}: {url}", file=sys.stderr, flush=True)
                return False
            with tempfile.TemporaryDirectory() as td:
                fp = os.path.join(td, name)
                with open(fp, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
                res = gh("release", "upload", target_tag, fp, "--repo", REPO, "--clobber", check=False)
                if res.returncode != 0:
                    print(f"  upload failed {name} to {target_tag}: {res.stderr.strip()}", file=sys.stderr, flush=True)
                    return False
                print(f"  + [{target_tag}] {name}", flush=True)
                return True
    except requests.RequestException as e:
        print(f"  error copying {name}: {e}", file=sys.stderr, flush=True)
        return False


def process_release_items(tag: str, items: list[tuple[str, str]], dry_run: bool = False) -> tuple[int, int, int]:
    if not ensure_release(tag, dry_run=dry_run):
        print(f"Failed to ensure release {tag}", file=sys.stderr, flush=True)
        return 0, 0, len(items)

    existing = get_existing_assets(tag)
    todo = sorted([(src, name) for src, name in items if name not in existing], key=lambda x: x[1])
    skipped = len(items) - len(todo)

    if not todo:
        print(f"[{tag}] all {len(items)} items already present.", flush=True)
        return 0, skipped, 0

    print(f"[{tag}] {skipped} already present, copying {len(todo)} items in sorted order...", flush=True)
    copied = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {
            ex.submit(copy_asset, src, tag, name, dry_run): name
            for src, name in todo
        }
        for fut in as_completed(futures):
            if fut.result():
                copied += 1
            else:
                failed += 1

    return copied, skipped, failed


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill legacy assets to partitioned releases")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without modifying releases")
    args = parser.parse_args()

    print(f"Reading legacy assets from {REPO}...", flush=True)
    pdf_assets = sorted(get_existing_assets(LEGACY_PDF_TAG))
    img_assets = sorted(get_existing_assets(LEGACY_IMG_TAG))
    print(f"Found {len(pdf_assets)} assets in {LEGACY_PDF_TAG}, {len(img_assets)} assets in {LEGACY_IMG_TAG}", flush=True)

    plan: dict[str, list[tuple[str, str]]] = defaultdict(list)
    unmapped = []

    for name in pdf_assets:
        target = classify_asset(name, LEGACY_PDF_TAG)
        if target:
            plan[target].append((LEGACY_PDF_TAG, name))
        else:
            if not name.startswith("indianexpress-eye_"):
                unmapped.append(name)

    for name in img_assets:
        target = classify_asset(name, LEGACY_IMG_TAG)
        if target:
            plan[target].append((LEGACY_IMG_TAG, name))
        else:
            unmapped.append(name)

    if unmapped:
        print(f"Warning: {len(unmapped)} assets could not be classified:", file=sys.stderr, flush=True)
        for u in unmapped[:10]:
            print(f"  - {u}", file=sys.stderr, flush=True)

    print("\nTarget Releases Breakdown:", flush=True)
    for tag in sorted(plan.keys()):
        print(f"  - {tag:30s} : {len(plan[tag]):4d} assets", flush=True)
    print(f"  - (Remaining in {LEGACY_PDF_TAG} only) : {len(pdf_assets) - sum(len(v) for k, v in plan.items() if k != 'economist-images-2026'):4d} assets", flush=True)

    if args.dry_run:
        print("\nDry-run complete. No changes were made.", flush=True)
        return 0

    print("\nExecuting backfill migration...", flush=True)
    total_copied = 0
    total_skipped = 0
    total_failed = 0

    for tag in sorted(plan.keys()):
        c, s, f = process_release_items(tag, plan[tag], dry_run=args.dry_run)
        total_copied += c
        total_skipped += s
        total_failed += f

    print(f"\nBackfill Complete: {total_copied} copied, {total_skipped} already present, {total_failed} failed.", flush=True)
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
