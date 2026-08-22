#!/usr/bin/env python3
"""Mirror archived files (current-affairs PDFs, Economist images, epapers)
into GitHub Releases, so RSS feeds can link to durable copies without bloating
the repo or GitHub Pages site.

Supports multi-release tagging (e.g. newspaper-2026, mygov-2026, niti-2026,
visionias-pt365-2026, made-easy-ca-2026, economist-images-2026) alongside legacy
pdf-archive and image-archive releases.

Inputs: the `archive/<key>.json` manifests written by feed builders. Each is a
list of {name, url, tag?}: `name` is the archival filename, `url` is the source
asset, and `tag` is the target release tag (defaults to ARCHIVE_RELEASE_TAG).

Requires the `gh` CLI authenticated with a token that can edit releases
(GITHUB_TOKEN in Actions). Configure via env:
    ARCHIVE_RELEASE_TAG   default release tag (default pdf-archive)
    ARCHIVE_MANIFEST_DIR  where the *.json manifests live (default archive)
    ARCHIVE_REFERENCE_DIR generated feeds to verify (default public)
    ARCHIVE_VERIFY_DAYS   recent publication window to verify (default 1)
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from email.utils import parsedate_to_datetime
from urllib.parse import unquote

import requests

DEFAULT_TAG = os.environ.get("ARCHIVE_RELEASE_TAG", "pdf-archive")
MANIFEST_DIR = os.environ.get("ARCHIVE_MANIFEST_DIR", "archive")
REFERENCE_DIR = os.environ.get("ARCHIVE_REFERENCE_DIR", "public")
VERIFY_DAYS = max(1, int(os.environ.get("ARCHIVE_VERIFY_DAYS", "1")))
# Overridable because some sources (e.g. Economist content-assets images) are
# Cloudflare-protected and only serve to a specific whitelisted UA.
UA = os.environ.get(
    "ARCHIVE_UA",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.7922.76 Safari/537.36",
)
TIMEOUT = int(os.environ.get("ARCHIVE_TIMEOUT", "120"))
# GitHub rejects release assets over 2 GB; skip anything absurd defensively.
MAX_BYTES = int(os.environ.get("ARCHIVE_MAX_BYTES", str(2 * 1024**3 - 1)))


def gh(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=check)


def gh_retry(*args: str, tries: int = 4) -> subprocess.CompletedProcess:
    """Run a `gh` command, retrying transient failures with exponential backoff."""
    delay = 2.0
    res = gh(*args, check=False)
    for attempt in range(1, tries):
        if res.returncode == 0:
            return res
        print(
            f"  gh {' '.join(args)} failed (attempt {attempt}/{tries}): "
            f"{res.stderr.strip()[:200]}",
            file=sys.stderr,
        )
        time.sleep(delay)
        delay *= 2
        res = gh(*args, check=False)
    return res


def release_title(tag: str) -> str:
    """Derive a human-readable title for a release tag."""
    if tag == "pdf-archive":
        return "Archive"
    if tag == "image-archive":
        return "Image Archive"
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


def ensure_release(tag: str) -> None:
    if gh_retry("release", "view", tag).returncode == 0:
        return
    title = release_title(tag)
    print(f"creating release {tag} ({title})")
    res = gh_retry(
        "release",
        "create",
        tag,
        "--title",
        title,
        "--notes",
        f"Archived files for {title}. Managed automatically by archive_pdfs.py.",
    )
    if res.returncode == 0:
        return
    # A transient `release view` above can route us here even though the release
    # exists; `create` then fails with "already exists". Re-check before dying.
    if gh_retry("release", "view", tag).returncode == 0:
        return
    raise SystemExit(f"cannot create release {tag}: {res.stderr.strip()}")


def existing_assets(tag: str) -> set[str]:
    res = gh_retry("release", "view", tag, "--json", "assets")
    if res.returncode != 0:
        print(f"  warning: cannot read existing assets for {tag}: {res.stderr.strip()}", file=sys.stderr)
        return set()
    try:
        data = json.loads(res.stdout)
    except ValueError:
        return set()
    return {a["name"] for a in data.get("assets", [])}


def load_manifests() -> dict[str, dict[str, str]]:
    """Load manifests grouped by release tag -> {filename: url}."""
    wanted: dict[str, dict[str, str]] = defaultdict(dict)
    for path in sorted(glob.glob(os.path.join(MANIFEST_DIR, "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                entries = json.load(f)
        except (ValueError, OSError) as e:
            print(f"  skip {path}: {e}", file=sys.stderr)
            continue
        for e in entries:
            name = e.get("name")
            url = e.get("url")
            tag = e.get("tag") or DEFAULT_TAG
            if name and url:
                wanted[tag].setdefault(name, url)
    return wanted


def referenced_assets(now: dt.datetime | None = None) -> dict[str, set[str]]:
    """Return release assets linked by recently published feed items grouped by tag."""
    marker = re.compile(r"/releases/download/([^/\s<>'\"?#]+)/([^/\s<>'\"?#]+)", re.I)
    item_marker = re.compile(r"<item\b.*?</item>", re.S | re.I)
    date_marker = re.compile(r"<pubDate>([^<]+)</pubDate>", re.I)
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    cutoff = now - dt.timedelta(days=VERIFY_DAYS)
    referenced: dict[str, set[str]] = defaultdict(set)
    for path in glob.glob(os.path.join(REFERENCE_DIR, "**", "feed.xml"), recursive=True):
        try:
            with open(path, encoding="utf-8") as f:
                body = f.read()
        except OSError as e:
            print(f"  cannot inspect {path}: {e}", file=sys.stderr)
            continue
        for item in item_marker.findall(body):
            date_match = date_marker.search(item)
            if date_match:
                try:
                    published = parsedate_to_datetime(date_match.group(1))
                    if published.tzinfo is None:
                        published = published.replace(tzinfo=dt.timezone.utc)
                    if published < cutoff:
                        continue
                except (TypeError, ValueError):
                    pass
            for m in marker.finditer(item):
                tag = unquote(m.group(1))
                name = unquote(m.group(2))
                referenced[tag].add(name)
    return referenced


def upload(tag: str, name: str, url: str) -> bool:
    try:
        with requests.get(url, stream=True, timeout=TIMEOUT, headers={"User-Agent": UA}) as r:
            if r.status_code != 200:
                print(f"  download HTTP {r.status_code}: {url}", file=sys.stderr)
                return False
            with tempfile.TemporaryDirectory() as td:
                fp = os.path.join(td, name)
                size = 0
                with open(fp, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        size += len(chunk)
                        if size > MAX_BYTES:
                            print(f"  too large, skip: {name}", file=sys.stderr)
                            return False
                        f.write(chunk)
                # clobber lets a re-run replace a partial/failed asset of the same name
                res = gh("release", "upload", tag, fp, "--clobber", check=False)
                if res.returncode != 0:
                    print(f"  upload failed {name} to {tag}: {res.stderr.strip()}", file=sys.stderr)
                    return False
                print(f"  + [{tag}] {name} ({size // 1024} KiB)")
                return True
    except requests.RequestException as e:  # pragma: no cover - network
        print(f"  error {name}: {e}", file=sys.stderr)
        return False


def main() -> int:
    wanted_by_tag = load_manifests()
    total_wanted = sum(len(v) for v in wanted_by_tag.values())
    print(f"manifest: {total_wanted} items across {len(wanted_by_tag)} releases")

    have_by_tag: dict[str, set[str]] = {}
    total_uploaded = 0
    total_todo = 0
    failed: list[tuple[str, str]] = []

    for tag in sorted(wanted_by_tag.keys()):
        ensure_release(tag)
        have = existing_assets(tag)
        have_by_tag[tag] = have
        todo = {n: u for n, u in wanted_by_tag[tag].items() if n not in have}
        total_todo += len(todo)
        print(f"[{tag}] present={len(have)} to-upload={len(todo)}")
        for name, url in todo.items():
            if upload(tag, name, url):
                total_uploaded += 1
                have.add(name)
            else:
                failed.append((tag, name))

    print(f"done: uploaded {total_uploaded}/{total_todo}")

    ref_by_tag = referenced_assets()
    missing: list[tuple[str, str]] = []
    tags_to_verify = sorted(wanted_by_tag.keys() if wanted_by_tag else ref_by_tag.keys())
    for tag in tags_to_verify:
        if tag not in have_by_tag:
            have_by_tag[tag] = existing_assets(tag)
        tag_missing = sorted(ref_by_tag.get(tag, set()) - have_by_tag[tag])
        for name in tag_missing:
            print(f"  missing release asset: [{tag}] {name}", file=sys.stderr)
            missing.append((tag, name))

    if failed or missing:
        print(
            f"archive incomplete: {len(failed)} upload failures, "
            f"{len(missing)} referenced assets missing",
            file=sys.stderr,
        )
        return 1
    print("archive references verified across all releases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
