#!/usr/bin/env python3
"""Probe RSS feeds, retrieve the latest 5 entries for each, and generate a report.

Reads feed.xml from local public/ if present, or fetches from the published
GitHub Pages base URL. For each feed, extracts up to 5 newest items, probes
their target link/enclosure via HTTP, and compiles an inspection report.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import html
import os
import re
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import certifi
import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.7922.76 Safari/537.36"
)

DEFAULT_BASE_URL = "https://jumpingpony.github.io/pib_feed"
LOCAL_DIR = os.environ.get("PROBE_LOCAL_DIR", "public")
BASE_URL = os.environ.get("PROBE_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
MAX_ENTRIES = int(os.environ.get("PROBE_MAX_ENTRIES", "5"))
PROBE_TIMEOUT = int(os.environ.get("PROBE_TIMEOUT", "12"))
MAX_WORKERS = int(os.environ.get("PROBE_WORKERS", "10"))
OUTPUT_REPORT = os.environ.get("PROBE_REPORT_PATH", "probe_report.md")

FEED_KEYS = [
    "press_releases",
    "pmo",
    "backgrounders",
    "factsheets",
    "features",
    "faqs",
    "newsonair",
    "visionias-pt-365",
    "visionias-mains-365",
    "madeeasy-weekly",
    "nextias-magazine",
    "mygov_bharatmatters",
    "mygov_pulsenewsletter",
    "mygov_mannkibaat",
    "scobserver_cases",
    "scobserver-journal",
    "scobserver-reports",
    "prs-bills",
    "prs-acts",
    "prs-budgets",
    "idsa-comments",
    "idsa-issue-briefs",
    "idsa-monographs",
    "idsa-backgrounders",
    "eacpm-reports",
    "project-syndicate",
    "indianexpress-explained",
    "indianexpress-opinion",
    "upsc-essentials",
    "indianexpress-delhi",
    "indiatoday_magazine",
    "niti-reports",
    "niti-working-papers",
    "niti-research-papers",
    "niti-policy-papers",
    "niti-annual-reports",
    "ipcs-commentaries",
    "indiasworld",
    "frontline_magazine",
    "frontline_blog",
]


@dataclass
class EntryProbe:
    index: int
    title: str
    pub_date: str
    link: str
    target_url: str
    enclosure_url: str | None
    enclosure_type: str | None
    http_status: int | str = "UNCHECKED"
    content_type: str = ""
    latency_ms: int = 0
    has_body: bool = False
    error: str | None = None


@dataclass
class FeedProbeResult:
    feed_key: str
    feed_title: str
    source_origin: str
    status: str  # PASS, DEGRADED, FAIL
    entries: list[EntryProbe] = field(default_factory=list)
    total_feed_entries: int = 0
    error_message: str | None = None
    duration_sec: float = 0.0


def make_ca_bundle() -> str | None:
    root_pem = Path(__file__).resolve().parent.parent / "certs" / "isrg-root-yr.pem"
    if not root_pem.is_file():
        return None
    bundle = Path(tempfile.gettempdir()) / "probe_ca_bundle.pem"
    bundle.write_bytes(Path(certifi.where()).read_bytes() + root_pem.read_bytes())
    return str(bundle)


CA_BUNDLE = make_ca_bundle()


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    if CA_BUNDLE:
        s.verify = CA_BUNDLE
    return s


def load_feed_xml(session: requests.Session, feed_key: str) -> tuple[str | None, str]:
    # Check local filesystem first
    local_path = os.path.join(LOCAL_DIR, feed_key, "feed.xml")
    if os.path.isfile(local_path):
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                return f.read(), f"local:{local_path}"
        except OSError as e:
            return None, f"local_error:{e}"

    # Fall back to remote published URL
    url = f"{BASE_URL}/{feed_key}/feed.xml"
    try:
        r = session.get(url, timeout=PROBE_TIMEOUT)
        if r.status_code == 200 and r.text:
            return r.text, f"remote:{url}"
        return None, f"remote_http_{r.status_code}"
    except requests.RequestException as e:
        return None, f"remote_err:{e}"


def check_target_url(session: requests.Session, url: str) -> tuple[int | str, str, int, str | None]:
    if not url:
        return "MISSING_URL", "", 0, "No URL provided"

    start = time.perf_counter()
    headers = {"User-Agent": UA}

    # Try HEAD first
    try:
        r = session.head(url, timeout=PROBE_TIMEOUT, allow_redirects=True, headers=headers)
        duration_ms = int((time.perf_counter() - start) * 1000)
        ctype = r.headers.get("Content-Type", "").split(";")[0].strip()

        if r.status_code in (200, 206):
            return r.status_code, ctype, duration_ms, None

        # If origin disallows HEAD (e.g. 401 on PIB, 403, 405), fall back to GET 1 byte
        if r.status_code in (401, 403, 405):
            r_get = session.get(
                url,
                headers={"Range": "bytes=0-1", **headers},
                timeout=PROBE_TIMEOUT,
                stream=True,
            )
            duration_ms = int((time.perf_counter() - start) * 1000)
            ctype = r_get.headers.get("Content-Type", "").split(";")[0].strip()
            return r_get.status_code, ctype, duration_ms, None

        return r.status_code, ctype, duration_ms, None
    except requests.RequestException as e:
        duration_ms = int((time.perf_counter() - start) * 1000)
        return "ERR", "", duration_ms, str(e)[:60]


def parse_feed_entries(xml_content: str) -> tuple[str, list[dict]]:
    feed_title = "Unknown Feed"
    items_data: list[dict] = []

    try:
        root = ET.fromstring(xml_content)
        channel = root.find("channel")
        if channel is not None:
            t_el = channel.find("title")
            if t_el is not None and t_el.text:
                feed_title = t_el.text.strip()

            for it in channel.findall("item"):
                t = (it.findtext("title") or "").strip()
                p = (it.findtext("pubDate") or "").strip()
                lnk = (it.findtext("link") or "").strip()
                desc = (it.findtext("description") or "").strip()

                enc_url = None
                enc_type = None
                enc = it.find("enclosure")
                if enc is not None:
                    enc_url = enc.get("url")
                    enc_type = enc.get("type")

                items_data.append({
                    "title": t,
                    "pub_date": p,
                    "link": lnk,
                    "enclosure_url": enc_url,
                    "enclosure_type": enc_type,
                    "has_body": len(desc) > 50,
                })
    except ET.ParseError:
        tm = re.search(r"<channel[^>]*>.*?<title>(.*?)</title>", xml_content, re.S)
        if tm:
            feed_title = html.unescape(tm.group(1)).strip()

        for chunk in re.findall(r"<item>(.*?)</item>", xml_content, re.S):
            it_t = re.search(r"<title>(.*?)</title>", chunk, re.S)
            it_p = re.search(r"<pubDate>(.*?)</pubDate>", chunk, re.S)
            it_l = re.search(r"<link>(.*?)</link>", chunk, re.S)
            it_enc = re.search(r'<enclosure[^>]+url="([^"]+)"[^>]*type="([^"]*)"', chunk)
            it_desc = re.search(r"<description>(.*?)</description>", chunk, re.S)

            items_data.append({
                "title": html.unescape(it_t.group(1)).strip() if it_t else "",
                "pub_date": it_p.group(1).strip() if it_p else "",
                "link": it_l.group(1).strip() if it_l else "",
                "enclosure_url": it_enc.group(1) if it_enc else None,
                "enclosure_type": it_enc.group(2) if it_enc else None,
                "has_body": len(it_desc.group(1)) > 50 if it_desc else False,
            })

    return feed_title, items_data


def probe_single_feed(session: requests.Session, feed_key: str) -> FeedProbeResult:
    start_time = time.perf_counter()
    xml_text, origin = load_feed_xml(session, feed_key)

    if not xml_text:
        return FeedProbeResult(
            feed_key=feed_key,
            feed_title=feed_key,
            source_origin=origin,
            status="FAIL",
            error_message=f"Could not load feed.xml ({origin})",
            duration_sec=round(time.perf_counter() - start_time, 2),
        )

    title, all_items = parse_feed_entries(xml_text)
    selected_items = all_items[:MAX_ENTRIES]
    entry_probes: list[EntryProbe] = []

    for i, it in enumerate(selected_items, 1):
        target = it["enclosure_url"] or it["link"]
        entry = EntryProbe(
            index=i,
            title=it["title"] or f"Entry #{i}",
            pub_date=it["pub_date"] or "No date",
            link=it["link"],
            target_url=target,
            enclosure_url=it["enclosure_url"],
            enclosure_type=it["enclosure_type"],
            has_body=it["has_body"],
        )
        entry_probes.append(entry)

    # Check targets concurrently for this feed
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(entry_probes) or 1, 5)) as pool:
        future_map = {
            pool.submit(check_target_url, session, e.target_url): e
            for e in entry_probes
        }
        for future in concurrent.futures.as_completed(future_map):
            e = future_map[future]
            try:
                code, ctype, lat, err = future.result()
                e.http_status = code
                e.content_type = ctype
                e.latency_ms = lat
                e.error = err
            except Exception as ex:
                e.http_status = "EXC"
                e.error = str(ex)[:60]

    # Determine status
    if not entry_probes:
        status = "FAIL"
        err_msg = "Feed XML contains 0 items"
    else:
        err_count = sum(1 for e in entry_probes if e.http_status not in (200, 206, 301, 302))
        if err_count == 0:
            status = "PASS"
            err_msg = None
        elif err_count < len(entry_probes):
            status = "DEGRADED"
            err_msg = f"{err_count}/{len(entry_probes)} item targets returned non-200"
        else:
            status = "FAIL"
            err_msg = f"All {len(entry_probes)} item targets failed probe"

    return FeedProbeResult(
        feed_key=feed_key,
        feed_title=title,
        source_origin=origin,
        status=status,
        entries=entry_probes,
        total_feed_entries=len(all_items),
        error_message=err_msg,
        duration_sec=round(time.perf_counter() - start_time, 2),
    )


def run_probes(filter_key: str | None = None) -> list[FeedProbeResult]:
    session = make_session()
    targets = FEED_KEYS
    if filter_key and filter_key != "all":
        targets = [k for k in FEED_KEYS if filter_key in k]
        if not targets:
            print(f"Warning: No feeds matched filter '{filter_key}', probing all.", file=sys.stderr)
            targets = FEED_KEYS

    results: list[FeedProbeResult] = []
    print(f"Probing {len(targets)} feeds (max {MAX_ENTRIES} entries each, workers={MAX_WORKERS})...")
    start = time.perf_counter()

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_feed = {
            executor.submit(probe_single_feed, session, key): key
            for key in targets
        }
        for future in concurrent.futures.as_completed(future_to_feed):
            key = future_to_feed[future]
            try:
                res = future.result()
                results.append(res)
                print(f"  [{res.status:<8}] {key} ({len(res.entries)} entries, {res.duration_sec}s)")
            except Exception as exc:
                print(f"  [ERROR   ] {key}: {exc}", file=sys.stderr)
                results.append(
                    FeedProbeResult(
                        feed_key=key,
                        feed_title=key,
                        source_origin="unknown",
                        status="FAIL",
                        error_message=str(exc),
                    )
                )

    order_map = {k: i for i, k in enumerate(targets)}
    results.sort(key=lambda r: order_map.get(r.feed_key, 999))
    total_time = round(time.perf_counter() - start, 2)
    print(f"Completed probe of {len(results)} feeds in {total_time}s\n")
    return results


def build_markdown_report(results: list[FeedProbeResult]) -> str:
    now_str = dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d %H:%M:%S IST")
    total = len(results)
    passed = sum(1 for r in results if r.status == "PASS")
    degraded = sum(1 for r in results if r.status == "DEGRADED")
    failed = sum(1 for r in results if r.status == "FAIL")
    total_items = sum(len(r.entries) for r in results)

    lines = [
        "# Feed Health & 5-Entry Probe Report",
        "",
        f"**Generated:** {now_str}  ",
        f"**Total Feeds Probed:** {total} | **Passed:** {passed} | **Degraded:** {degraded} | **Failed:** {failed} | **Total Entries Audited:** {total_items}",
        "",
        "---",
        "",
        "## Summary Overview",
        "",
        "| Feed Key | Title | Status | Entries | Latest Entry Title | Latest Date | Target HTTP | Duration |",
        "|---|---|:---:|:---:|---|---|:---:|:---:|",
    ]

    for r in results:
        badge = "🟢 PASS" if r.status == "PASS" else ("🟡 DEGRADED" if r.status == "DEGRADED" else "🔴 FAIL")
        first = r.entries[0] if r.entries else None
        latest_title = (first.title[:35] + "…") if first and len(first.title) > 35 else (first.title if first else "—")
        latest_date = first.pub_date[:16] if first else "—"
        latest_http = str(first.http_status) if first else "—"
        count_str = f"{len(r.entries)}/{r.total_feed_entries}" if r.total_feed_entries else f"{len(r.entries)}"

        lines.append(
            f"| `{r.feed_key}` | {r.feed_title} | {badge} | {count_str} | {latest_title} | {latest_date} | {latest_http} | {r.duration_sec}s |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## Detailed 5-Entry Inspection per Feed",
        "",
    ])

    for r in results:
        badge = "🟢 PASS" if r.status == "PASS" else ("🟡 DEGRADED" if r.status == "DEGRADED" else "🔴 FAIL")
        lines.append(f"<details><summary><strong>{r.feed_key}</strong> — {r.feed_title} ({badge}, {len(r.entries)} entries)</summary>")
        lines.append("")
        if r.error_message:
            lines.append(f"> **Warning / Error:** {r.error_message}\n")

        if not r.entries:
            lines.append("_No entries found in feed._\n")
        else:
            lines.append("| # | Entry Title | Published Date | Target URL (PDF / Web) | HTTP Status | Content-Type | Latency |")
            lines.append("|:---:|---|---|---|:---:|:---:|:---:|")
            for e in r.entries:
                short_title = e.title.replace("|", "\\|")
                target_cell = f"[{urlparse(e.target_url).netloc}…]({e.target_url})" if e.target_url else "—"
                code_badge = f"`{e.http_status}`"
                lines.append(
                    f"| {e.index} | {short_title} | {e.pub_date} | {target_cell} | {code_badge} | `{e.content_type or '—'}` | {e.latency_ms}ms |"
                )
            lines.append("")
        lines.append("</details>\n")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe RSS feeds and audit latest 5 entries.")
    parser.add_argument("--feed", default=os.environ.get("PROBE_FILTER", "all"), help="Filter by feed key substring")
    args = parser.parse_args()

    results = run_probes(filter_key=args.feed)
    report_md = build_markdown_report(results)

    with open(OUTPUT_REPORT, "w", encoding="utf-8") as f:
        f.write(report_md)
    print(f"Report written to {OUTPUT_REPORT}")

    # Append to GITHUB_STEP_SUMMARY if running in GitHub Actions
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path and os.path.isdir(os.path.dirname(summary_path)):
        try:
            with open(summary_path, "a", encoding="utf-8") as sf:
                sf.write("\n" + report_md + "\n")
            print("Report appended to $GITHUB_STEP_SUMMARY")
        except OSError as e:
            print(f"Could not write to GITHUB_STEP_SUMMARY: {e}", file=sys.stderr)

    failed_count = sum(1 for r in results if r.status == "FAIL")
    return 1 if failed_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
