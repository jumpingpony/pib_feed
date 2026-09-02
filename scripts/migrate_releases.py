#!/usr/bin/env python3
"""Mirror release tags and assets from nappingcats/pib_feed to jumpingpony/pib_feed."""
from __future__ import annotations

import argparse
import enum
import json
import os
import subprocess
import sys
import tempfile
import time
from typing import Optional

import requests

SOURCE_REPO = "nappingcats/pib_feed"
TARGET_REPO = "jumpingpony/pib_feed"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.76 Safari/537.36"
HTTP_TIMEOUT_SECONDS = 60
POLITENESS_DELAY_SECONDS = 0.5
SKIP_TAGS = {"pdf-archive", "image-archive"}


class DryRun(enum.Enum):
    ENABLED = 1
    DISABLED = 2


def run_cmd(args: list[str], token: Optional[str] = None) -> subprocess.CompletedProcess:
    """Run shell command with optional auth token."""
    env = os.environ.copy()
    if token:
        env["GH_TOKEN"] = token

    return subprocess.run(args, capture_output=True, text=True, env=env)


def get_token(user: str) -> str:
    """Fetch GitHub auth token for specified user."""
    res = subprocess.run(["gh", "auth", "token", "-u", user], capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Failed to get token for {user}: {res.stderr}", file=sys.stderr)
        sys.exit(1)

    return res.stdout.strip()


def list_releases(repo: str, token: str) -> list[dict]:
    """List all releases in repository."""
    cmd = ["gh", "release", "list", "-R", repo, "--limit", "100", "--json", "tagName,name"]
    res = run_cmd(cmd, token=token)
    if res.returncode != 0:
        print(f"Failed to list releases for {repo}: {res.stderr}", file=sys.stderr)
        return []

    return json.loads(res.stdout)


def get_release_assets(repo: str, tag: str, token: str) -> list[dict]:
    """Fetch assets list for a specific release."""
    cmd = ["gh", "release", "view", tag, "-R", repo, "--json", "assets"]
    res = run_cmd(cmd, token=token)
    if res.returncode != 0:
        return []

    data = json.loads(res.stdout)
    return data.get("assets", [])


def create_release(tag: str, title: str, token: str, mode: DryRun) -> None:
    """Create release on target repository if missing."""
    if mode == DryRun.ENABLED:
        print(f"  [dry-run] Would create release {tag} ({title})")
        return

    cmd = [
        "gh",
        "release",
        "create",
        tag,
        "-R",
        TARGET_REPO,
        "--title",
        title or tag,
        "--notes",
        f"Archived publication files for {tag}. Managed automatically.",
    ]
    res = run_cmd(cmd, token=token)
    if res.returncode != 0:
        print(f"  Failed to create release {tag}: {res.stderr.strip()}", file=sys.stderr)


def download_asset(api_url: str, dest_path: str, token: str) -> int:
    """Download release asset via GitHub API octet-stream."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/octet-stream",
        "User-Agent": USER_AGENT,
    }

    with requests.get(api_url, headers=headers, stream=True, timeout=HTTP_TIMEOUT_SECONDS) as r:
        r.raise_for_status()
        bytes_written = 0
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)
                bytes_written += len(chunk)

        return bytes_written


def upload_asset(tag: str, file_path: str, token: str, mode: DryRun) -> None:
    """Upload asset to target release."""
    if mode == DryRun.ENABLED:
        print(f"  [dry-run] Would upload {os.path.basename(file_path)} to {tag}")
        return

    cmd = ["gh", "release", "upload", tag, file_path, "-R", TARGET_REPO, "--clobber"]
    res = run_cmd(cmd, token=token)
    if res.returncode != 0:
        raise RuntimeError(f"Upload failed: {res.stderr.strip()}")


def migrate_single_release(
    tag: str,
    title: str,
    src_token: str,
    tgt_token: str,
    mode: DryRun,
) -> None:
    """Mirror one release tag and its missing assets."""
    print(f"\nProcessing release [{tag}]...")

    # Ensure release exists on target
    tgt_assets = get_release_assets(TARGET_REPO, tag, tgt_token)
    tgt_asset_names = {a["name"] for a in tgt_assets}

    if not tgt_assets and mode == DryRun.DISABLED:
        # Check if release actually exists or needs creation
        chk = run_cmd(["gh", "release", "view", tag, "-R", TARGET_REPO], token=tgt_token)
        if chk.returncode != 0:
            create_release(tag, title, tgt_token, mode)

    src_assets = get_release_assets(SOURCE_REPO, tag, src_token)
    missing = [a for a in src_assets if a["name"] not in tgt_asset_names]
    print(f"  Source: {len(src_assets)} assets, Target: {len(tgt_asset_names)} assets, Missing: {len(missing)}")

    # Sequentially migrate missing assets
    for idx, asset in enumerate(missing, 1):
        name = asset["name"]
        api_url = asset["apiUrl"]
        expected_size = asset.get("size", 0)
        print(f"  [{idx}/{len(missing)}] Migrating {name} ({expected_size} bytes)...", flush=True)

        if mode == DryRun.ENABLED:
            continue

        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, name)
            download_asset(api_url, file_path, src_token)
            upload_asset(tag, file_path, tgt_token, mode)

        time.sleep(POLITENESS_DELAY_SECONDS)


def main():
    parser = argparse.ArgumentParser(description="Migrate release assets between repositories")
    parser.add_argument("--dry-run", action="store_true", help="Inspect without copying")
    parser.add_argument("--tag", help="Migrate only a specific tag")
    args = parser.parse_args()

    mode = DryRun.ENABLED if args.dry_run else DryRun.DISABLED

    src_token = get_token("nappingcats")
    tgt_token = get_token("jumpingpony")

    print(f"Source repo: {SOURCE_REPO}")
    print(f"Target repo: {TARGET_REPO}")

    releases = list_releases(SOURCE_REPO, src_token)
    print(f"Found {len(releases)} releases in source repository")

    for rel in releases:
        tag = rel["tagName"]
        if tag in SKIP_TAGS:
            continue
        title = rel.get("name", tag)
        if args.tag and tag != args.tag:
            continue

        migrate_single_release(tag, title, src_token, tgt_token, mode)

    print("\nRelease migration finished.")


if __name__ == "__main__":
    main()
