#!/usr/bin/env python3
"""Audit and prune non-referenced release artifacts from GitHub releases."""
from __future__ import annotations

import argparse
import enum
import glob
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from typing import Optional
from urllib.parse import unquote

PUBLIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "public"))
REPO = "jumpingpony/pib_feed"


class RunMode(enum.Enum):
    DRY_RUN = 1
    EXECUTE = 2


def gh_cmd(args: list[str]) -> subprocess.CompletedProcess:
    """Execute GitHub CLI command with UTF-8 decoding."""
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=False)


def collect_referenced_assets() -> dict[str, set[str]]:
    """Scan all generated feeds under public/ to find referenced release assets."""
    marker = re.compile(r"/releases/download/([^/\s<>'\"?#]+)/([^/\s<>'\"?#]+)", re.I)
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


def list_releases() -> list[str]:
    """Retrieve list of release tags from GitHub repository."""
    res = gh_cmd(["release", "list", "-R", REPO, "--json", "tagName", "--limit", "100"])
    if res.returncode != 0:
        print(f"Error fetching releases: {res.stderr.strip()}", file=sys.stderr)
        return []

    try:
        data = json.loads(res.stdout)
        return [r["tagName"] for r in data]
    except ValueError:
        return []


def list_release_assets(tag: str) -> set[str]:
    """Retrieve all asset filenames for a specific release tag."""
    res = gh_cmd(["release", "view", tag, "-R", REPO, "--json", "assets"])
    if res.returncode != 0:
        return set()

    try:
        data = json.loads(res.stdout)
        return {a["name"] for a in data.get("assets", [])}
    except ValueError:
        return set()


def delete_asset(tag: str, asset_name: str, mode: RunMode) -> bool:
    """Delete a specific asset from a release tag."""
    if mode == RunMode.DRY_RUN:
        print(f"  [dry-run] Would delete: {tag} / {asset_name}")
        return True

    print(f"  Deleting unreferenced asset: {tag} / {asset_name}...")
    res = gh_cmd(["release", "delete-asset", tag, asset_name, "-y", "-R", REPO])
    if res.returncode == 0:
        return True

    print(f"  Error deleting {asset_name} from {tag}: {res.stderr.strip()}", file=sys.stderr)
    return False


def prune_unreferenced(mode: RunMode) -> None:
    """Audit all releases and remove assets not referenced in public/ feeds."""
    referenced = collect_referenced_assets()
    total_referenced = sum(len(s) for s in referenced.values())
    print(f"Found {total_referenced} referenced assets across {len(referenced)} tags in public/")

    releases = list_releases()
    print(f"Found {len(releases)} releases on {REPO}")

    pruned_count = 0
    kept_count = 0

    for tag in sorted(releases):
        assets = list_release_assets(tag)
        ref_in_tag = referenced.get(tag, set())

        unref = sorted(assets - ref_in_tag)
        kept = sorted(assets & ref_in_tag)
        kept_count += len(kept)

        if not unref:
            continue

        print(f"Release [{tag}]: {len(kept)} referenced, {len(unref)} unreferenced to prune")
        for asset in unref:
            if delete_asset(tag, asset, mode):
                pruned_count += 1

    print(f"\nAudit complete. Kept: {kept_count} referenced assets. Pruned: {pruned_count} unreferenced assets.")


def main():
    parser = argparse.ArgumentParser(description="Prune non-referenced release artifacts")
    parser.add_argument("--dry-run", action="store_true", help="Audit without deleting assets")
    args = parser.parse_args()

    mode = RunMode.DRY_RUN if args.dry_run else RunMode.EXECUTE
    prune_unreferenced(mode)


if __name__ == "__main__":
    main()
