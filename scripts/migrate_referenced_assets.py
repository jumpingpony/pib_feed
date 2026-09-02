#!/usr/bin/env python3
"""Migrate ONLY referenced release assets from nappingcats to jumpingpony."""
from __future__ import annotations

import argparse
import enum
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from urllib.parse import unquote

import requests

SRC_REPO = "nappingcats/pib_feed"
TARGET_REPO = "jumpingpony/pib_feed"
PUBLIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "public"))
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.7922.76 Safari/537.36"
)

HTTP_TIMEOUT_SECONDS = 60
POLITENESS_DELAY_SECONDS = 0.5


class RunMode(enum.Enum):
    DRY_RUN = 1
    EXECUTE = 2


def gh_cmd(args: list[str]) -> subprocess.CompletedProcess:
    """Run GitHub CLI command."""
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=False)


def get_gh_token(account: str) -> str:
    """Retrieve auth token for GitHub CLI account."""
    res = gh_cmd(["auth", "token", "-u", account])
    if res.returncode != 0:
        print(f"Failed to get token for {account}: {res.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    return res.stdout.strip()


def collect_referenced_assets() -> dict[str, set[str]]:
    """Scan all generated feeds under public/ to find referenced release assets."""
    marker = re.compile(r"/releases/download/([^/\s<>\x27\"?#]+)/([^/\s<>\x27\"?#]+)", re.I)
    referenced: dict[str, set[str]] = defaultdict(set)

    for feed_xml in glob.glob(os.path.join(PUBLIC_DIR, "**", "feed.xml"), recursive=True):
        try:
            with open(feed_xml, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError as e:
            print(f"Warning: could not read {feed_xml}: {e}", file=sys.stderr)
            continue

        for m in marker.finditer(content):
            tag = unquote(m.group(1))
            asset = unquote(m.group(2))
            referenced[tag].add(asset)

    return referenced


def get_target_assets(tag: str) -> set[str]:
    """Retrieve set of asset filenames already on target release."""
    res = gh_cmd(["release", "view", tag, "-R", TARGET_REPO, "--json", "assets"])
    if res.returncode != 0:
        return set()

    try:
        data = json.loads(res.stdout)
        return {a["name"] for a in data.get("assets", [])}
    except ValueError:
        return set()


def ensure_target_release(tag: str) -> None:
    """Create target release if it does not exist."""
    res = gh_cmd(["release", "view", tag, "-R", TARGET_REPO])
    if res.returncode == 0:
        return

    title = tag.replace("-", " ").title()
    print(f"Creating release [{tag}] on {TARGET_REPO}...")
    gh_cmd(["release", "create", tag, "-R", TARGET_REPO, "--title", title, "--notes", f"Archive for {title}"])


def download_from_nappingcats(src_tag: str, asset_name: str, src_token: str, dest_path: str, retries: int = 3) -> bool:
    """Download asset from source repository via GitHub API with retry on network error."""
    url = f"https://api.github.com/repos/{SRC_REPO}/releases/tags/{src_tag}"
    headers = {
        "Authorization": f"Bearer {src_token}",
        "User-Agent": USER_AGENT,
    }

    delay = 2.0
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT_SECONDS)
            if r.status_code != 200:
                return False

            assets = r.json().get("assets", [])
            asset_id = None
            for a in assets:
                if a.get("name") == asset_name:
                    asset_id = a.get("id")
                    break

            if not asset_id:
                return False

            download_url = f"https://api.github.com/repos/{SRC_REPO}/releases/assets/{asset_id}"
            dl_headers = {
                "Authorization": f"Bearer {src_token}",
                "Accept": "application/octet-stream",
                "User-Agent": USER_AGENT,
            }

            dl_resp = requests.get(download_url, headers=dl_headers, stream=True, timeout=HTTP_TIMEOUT_SECONDS)
            if dl_resp.status_code != 200:
                return False

            with open(dest_path, "wb") as f:
                for chunk in dl_resp.iter_content(chunk_size=1 << 20):
                    if chunk:
                        f.write(chunk)

            return True
        except Exception as e:
            if attempt < retries:
                time.sleep(delay)
                delay *= 2
                continue
            print(f"    nappingcats download error after {retries} attempts: {e}", file=sys.stderr)
            return False

    return False


def upload_asset(tag: str, file_path: str) -> bool:
    """Upload asset to target release on jumpingpony."""
    res = gh_cmd(["release", "upload", tag, file_path, "-R", TARGET_REPO, "--clobber"])
    return res.returncode == 0


def migrate_referenced_assets(mode: RunMode) -> None:
    """Migrate all missing referenced assets."""
    referenced = collect_referenced_assets()
    src_token = get_gh_token("nappingcats")

    total_referenced = sum(len(s) for s in referenced.values())
    print(f"Found {total_referenced} referenced assets across {len(referenced)} release tags")

    migrated_count = 0
    skipped_count = 0
    failed_count = 0

    for tag in sorted(referenced):
        ensure_target_release(tag)
        existing = get_target_assets(tag)
        missing = sorted(referenced[tag] - existing)

        skipped_count += len(referenced[tag] & existing)
        if not missing:
            continue

        print(f"\nProcessing release [{tag}]: {len(missing)} missing referenced assets")

        # Map source tag if renamed (e.g. indianexpress-delhi was indianexpress-delhi-2026 on nappingcats)
        src_tag = "indianexpress-delhi-2026" if tag == "indianexpress-delhi" else tag

        for idx, asset_name in enumerate(missing, 1):
            print(f"  [{idx}/{len(missing)}] Migrating {asset_name} to [{tag}]...")

            if mode == RunMode.DRY_RUN:
                migrated_count += 1
                continue

            with tempfile.TemporaryDirectory() as tmp_dir:
                dest_path = os.path.join(tmp_dir, asset_name)
                downloaded = download_from_nappingcats(src_tag, asset_name, src_token, dest_path)

                if not downloaded:
                    print(f"    ERROR: Could not retrieve {asset_name}", file=sys.stderr)
                    failed_count += 1
                    continue

                if upload_asset(tag, dest_path):
                    migrated_count += 1
                else:
                    print(f"    ERROR: Failed to upload {asset_name} to {tag}", file=sys.stderr)
                    failed_count += 1

            time.sleep(POLITENESS_DELAY_SECONDS)

    print(f"\nMigration complete. Migrated: {migrated_count}, Existing: {skipped_count}, Failed: {failed_count}")


def main():
    parser = argparse.ArgumentParser(description="Migrate referenced release assets")
    parser.add_argument("--dry-run", action="store_true", help="Audit without downloading/uploading")
    args = parser.parse_args()

    mode = RunMode.DRY_RUN if args.dry_run else RunMode.EXECUTE
    migrate_referenced_assets(mode)


if __name__ == "__main__":
    main()
