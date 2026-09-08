#!/usr/bin/env python3
"""Build full-text RSS feed for Swaminomics (Times of India).

Fetches Swaminathan S. Anklesaria Aiyar's columns from his TOI Plus author profile.
Article content is fetched unmetered via TOI's AUFS feed endpoint. The feed merges
with previously published XML copies to preserve history across runs.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import sys
from email.utils import format_datetime, parsedate_to_datetime
from xml.sax.saxutils import escape

import requests

HTTP_OK = 200
DEFAULT_TIMEOUT = 30
DEFAULT_RETRIES = 2
DEFAULT_MAX_FETCH = 30
DEFAULT_MAX_ITEMS = 250

FEED_KEY = "toi-swaminomics"
FEED_TITLE = "Swaminomics - Swaminathan S Anklesaria Aiyar"
FEED_DESC = "Unofficial full-text feed of Swaminomics columns by Swaminathan S. Anklesaria Aiyar."

BASE_URL = "https://timesofindia.indiatimes.com"
AUFS_ARTICLE_URL = "https://plus.timesofindia.com/aufs/feed/show/article/v1?id={}&fv=1495"
SWAMI_AUTHOR_URL = f"{BASE_URL}/toi-plus/author-swaminathansanklesariaaiyar-18032"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.7922.76 Safari/537.36"
)
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

TIMEOUT = int(os.environ.get("TOI_TIMEOUT", str(DEFAULT_TIMEOUT)))
RETRIES = int(os.environ.get("TOI_RETRIES", str(DEFAULT_RETRIES)))
OUT_DIR = os.environ.get("TOI_OUT_DIR", "public")
PUBLISHED_BASE_URL = os.environ.get("TOI_PUBLISHED_BASE_URL", "").strip().rstrip("/")
MAX_FETCH = int(os.environ.get("TOI_MAX_FETCH", str(DEFAULT_MAX_FETCH)))


# --- http helpers -------------------------------------------------------------
def make_session() -> requests.Session:
    """Create configured requests session with standard User-Agent."""
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    return s


def fetch_url(session: requests.Session, url: str) -> str | None:
    """Fetch text from URL with retries."""
    last_err = None
    for _ in range(RETRIES + 1):
        try:
            r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code == HTTP_OK and r.text:
                return r.text
            last_err = f"HTTP {r.status_code}"
            if r.status_code == 404:
                return None
        except requests.RequestException as e:
            last_err = str(e)

    if last_err:
        print(f"  fetch failed {url}: {last_err}", file=sys.stderr)
    return None


def fetch_json(session: requests.Session, url: str) -> dict | None:
    """Fetch JSON from URL with retries."""
    text = fetch_url(session, url)
    if not text:
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError) as e:
        print(f"  JSON parse failed {url}: {e}", file=sys.stderr)
        return None


# --- text & xml safety --------------------------------------------------------
TAG_RE = re.compile(r"<[^>]+>")
XML_ILLEGAL_RE = re.compile(
    "[^\x09\x0a\x0d\x20-퟿-\U00010000-\U0010ffff]"
)


def clean_text(text: str) -> str:
    """Strip HTML tags and unescape text."""
    return html.unescape(TAG_RE.sub(" ", text or "")).replace("\xa0", " ").strip()


def xml_safe(text: str) -> str:
    """Remove control characters invalid in XML 1.0."""
    return XML_ILLEGAL_RE.sub("", text)


def cdata(text: str) -> str:
    """Wrap content in CDATA block, escaping existing markers."""
    return xml_safe(text).replace("]]>", "]]]]><![CDATA[>")


def parse_date(upd: str | int | None) -> dt.datetime:
    """Parse timestamp from epoch ms."""
    if upd:
        try:
            return dt.datetime.fromtimestamp(int(upd) / 1000, tz=IST)
        except (ValueError, TypeError, OSError):
            pass
    return dt.datetime.now(IST)


# --- body extraction & formatting ---------------------------------------------
IMG_RE = re.compile(r"<img\b[^>]*>", re.I)
SRC_RE = re.compile(r'\bsrc="([^"]+)"', re.I)
CAP_RE = re.compile(r'\b(?:cap|caption|alt)="([^"]*)"', re.I)
VIDEO_RE = re.compile(r"<video\b[^>]*>(?:</video>)?", re.I)
EMBED_RE = re.compile(r"<embed\b[^>]*>", re.I)


def format_story(story_html: str, author: str) -> str:
    """Format raw AUFS Story HTML into clean text and occasional images only."""
    story = EMBED_RE.sub("", story_html or "")
    story = VIDEO_RE.sub("", story)

    def repl_img(m: re.Match) -> str:
        tag = m.group(0)
        src_m = SRC_RE.search(tag)
        if not src_m:
            return ""
        src = src_m.group(1)
        cap_m = CAP_RE.search(tag)
        caption = cap_m.group(1).strip() if cap_m else ""
        fig = (
            f'<figure><img src="{escape(src)}" alt="{escape(caption)}" '
            f'style="max-width:100%;height:auto;" />'
        )
        if caption:
            fig += f"<figcaption>{escape(caption)}</figcaption>"
        fig += "</figure>"
        return f"\n\n{fig}\n\n"

    story = IMG_RE.sub(repl_img, story)

    parts: list[str] = []
    if author:
        parts.append(f"<p><strong>{escape(author)}</strong></p>")

    for chunk in story.split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if chunk.startswith("<figure") or chunk.startswith("<p") or chunk.startswith("<h"):
            parts.append(chunk)
        else:
            inner = chunk.replace("\n", "<br />")
            parts.append(f"<p>{inner}</p>")

    return "\n".join(parts)


def fetch_article(session: requests.Session, aid: str, author: str) -> tuple[str, str]:
    """Fetch full article content from AUFS endpoint and return (body, summary)."""
    url = AUFS_ARTICLE_URL.format(aid)
    data = fetch_json(session, url)
    if not data or not isinstance(data, dict):
        return "", ""

    it = data.get("it", {})
    story_raw = it.get("Story", "")
    art_author = it.get("au") or author
    body = format_story(story_raw, art_author)

    syn = it.get("synopsys", {}).get("syn") or clean_text(story_raw[:500])
    if len(syn) > 500:
        syn = syn[:500].rsplit(" ", 1)[0] + "…"

    return body, syn


def extract_app_json(page: str) -> dict | None:
    """Extract and parse window.App JSON object from page HTML."""
    idx = page.find("window.App=")
    if idx < 0:
        return None
    end = page.find("</script>", idx)
    if end < 0:
        return None
    raw = page[idx + len("window.App=") : end].strip().rstrip(";")
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


# --- listing fetcher ----------------------------------------------------------
def fetch_swami_items(session: requests.Session) -> list[dict]:
    """Fetch Swaminathan S. Anklesaria Aiyar articles from author page."""
    page = fetch_url(session, SWAMI_AUTHOR_URL)
    if not page:
        return []

    app_data = extract_app_json(page)
    if not app_data:
        return []

    sections = app_data.get("state", {}).get("toiplusauthor", {}).get("sections", [])
    out: list[dict] = []
    seen: set[str] = set()

    for sec in sections:
        if sec.get("tn") != "sectionlisting":
            continue
        for it in sec.get("items", []):
            aid = str(it.get("id", "")).strip()
            link = it.get("wu") or (f"{BASE_URL}/articleshow/{aid}.cms" if aid else "")
            if not aid or not link or link in seen:
                continue
            seen.add(link)
            out.append(
                {
                    "id": aid,
                    "link": link,
                    "title": clean_text(it.get("hl", "")),
                    "author": "Swaminathan S Anklesaria Aiyar",
                    "date": parse_date(it.get("upd")),
                    "summary": clean_text(it.get("des", "")),
                }
            )

    return out


# --- feed persistence & rendering ---------------------------------------------
ITEM_RE = re.compile(r"<item>.*?</item>", re.S)
FEEDLINK_RE = re.compile(r"<link>([^<]+)</link>")
PUBDATE_RE = re.compile(r"<pubDate>([^<]+)</pubDate>")
STALE_VIDEO_RE = re.compile(r"<p><a\b[^>]*>(?:Watch Video|.*?videoshow.*?)</a></p>\s*", re.I)


def block_link(block: str) -> str | None:
    """Extract link from XML item block."""
    m = FEEDLINK_RE.search(block)
    return html.unescape(m.group(1)).strip() if m else None


def block_date(block: str) -> dt.datetime:
    """Extract publication date from XML item block."""
    m = PUBDATE_RE.search(block)
    if m:
        try:
            return parsedate_to_datetime(m.group(1).strip())
        except (TypeError, ValueError):
            pass
    return dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)


def sanitize_block(block: str) -> str:
    """Strip legacy video links from cached XML block."""
    return STALE_VIDEO_RE.sub("", block)


def load_published(session: requests.Session, key: str) -> dict[str, tuple[dt.datetime, str]]:
    """Load published feed XML to retain history across runs, stripping legacy videos."""
    if not PUBLISHED_BASE_URL:
        return {}

    body = fetch_url(session, f"{PUBLISHED_BASE_URL}/{key}/feed.xml")
    if not body:
        return {}

    items: dict[str, tuple[dt.datetime, str]] = {}
    for m in ITEM_RE.finditer(body):
        b = sanitize_block(m.group(0).strip())
        lnk = block_link(b)
        if lnk:
            items[lnk] = (block_date(b), b)

    print(f"  {key}: loaded {len(items)} published items")
    return items


def render_item(it: dict, body: str, summary: str, when: dt.datetime) -> str:
    """Render single RSS 2.0 item XML."""
    author_tag = (
        f"      <dc:creator>{escape(xml_safe(it['author']))}</dc:creator>\n"
        if it.get("author")
        else ""
    )
    return (
        "    <item>\n"
        f"      <title>{escape(xml_safe(it['title']))}</title>\n"
        f"      <link>{escape(it['link'])}</link>\n"
        f"      <guid isPermaLink=\"true\">{escape(it['link'])}</guid>\n"
        f"{author_tag}"
        f"      <pubDate>{format_datetime(when)}</pubDate>\n"
        f"      <description>{escape(xml_safe(summary))}</description>\n"
        f"      <content:encoded><![CDATA[{cdata(body)}]]></content:encoded>\n"
        "    </item>"
    )


def build_feed(items: dict[str, tuple[dt.datetime, str]]) -> tuple[str, int]:
    """Assemble complete RSS 2.0 channel XML."""
    ordered = sorted(items.values(), key=lambda t: t[0], reverse=True)[:DEFAULT_MAX_ITEMS]
    blocks = [b for _, b in ordered]
    now = format_datetime(dt.datetime.now(IST))
    self_url = f"{PUBLISHED_BASE_URL}/{FEED_KEY}/feed.xml" if PUBLISHED_BASE_URL else ""
    atom = (
        f'    <atom:link href="{escape(self_url)}" rel="self" type="application/rss+xml" />\n'
        if self_url
        else ""
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "  <channel>\n"
        f"    <title>{escape(FEED_TITLE)}</title>\n"
        f"    <link>{escape(SWAMI_AUTHOR_URL)}</link>\n"
        f"    <description>{escape(FEED_DESC)}</description>\n"
        "    <language>en</language>\n"
        f"    <lastBuildDate>{now}</lastBuildDate>\n"
        f"{atom}"
        + "\n".join(blocks)
        + "\n  </channel>\n</rss>\n"
    )
    return xml, len(blocks)


def write_feed(xml: str, count: int) -> None:
    """Write feed.xml and index.html to output directory."""
    d = os.path.join(OUT_DIR, FEED_KEY)
    os.makedirs(d, exist_ok=True)

    with open(os.path.join(d, "feed.xml"), "w", encoding="utf-8") as f:
        f.write(xml)

    with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as f:
        f.write(
            "<!doctype html><meta charset='utf-8'>"
            f"<title>{escape(FEED_TITLE)} (unofficial RSS)</title>"
            f"<h1>{escape(FEED_TITLE)} (unofficial)</h1>"
            f"<p>{escape(FEED_DESC)}</p>"
            "<p>Subscribe: <a href='feed.xml'>feed.xml</a></p>"
            f"<p>{count} items. Rebuilt automatically.</p>"
        )


def run_feed(session: requests.Session, now: dt.datetime) -> int:
    """Execute feed pipeline for Swaminomics feed."""
    print(f"[{FEED_KEY}]")
    merged = load_published(session, FEED_KEY)
    items = fetch_swami_items(session)
    print(f"  listing: {len(items)} items")

    new_count = 0
    full_count = 0

    for it in items:
        # Check if item is already cached cleanly without legacy video
        existing = merged.get(it["link"])
        if existing and "videoshow" not in existing[1] and "Watch Video" not in existing[1]:
            continue

        if new_count >= MAX_FETCH:
            break

        body, summary = fetch_article(session, it["id"], it["author"])
        if not body:
            body = f'<p>{escape(it["summary"])}</p><p><a href="{escape(it["link"])}">Read full article</a></p>'
            summary = it["summary"]
        else:
            full_count += 1

        when = it["date"] or now
        item_xml = render_item(it, body, summary, when).strip()
        merged[it["link"]] = (when, item_xml)
        new_count += 1

    xml_content, kept = build_feed(merged)
    write_feed(xml_content, kept)
    print(f"  {FEED_KEY}: +{new_count} new ({full_count} full body), total {kept}")
    return kept


def main() -> int:
    """Main builder entrypoint."""
    session = make_session()
    now = dt.datetime.now(IST)
    kept = run_feed(session, now)
    print("Done:", {FEED_KEY: kept})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
