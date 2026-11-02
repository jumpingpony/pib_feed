#!/usr/bin/env python3
"""Build full-text RSS feeds from The Indian Express (indianexpress.com).

Indian Express publishes per-section feeds (…/section/<name>/feed/), but its
CloudFront distribution rejects GitHub-hosted runners. The site's public
WordPress REST API provides the same listings with rendered article content.
It is fetched through Google's translation relay because the relay is accepted
from GitHub Actions while direct requests from those runners receive HTTP 403.

The article pages themselves are served in full — the
"premium" wall is a client-side Evolok JavaScript overlay (the Bypass-Paywalls
rule for indianexpress.com simply blocks that script). A server-side fetch
never runs the JS, so the complete article is already in the HTML, inside
`<div id="pcl-full-content">` (part of it wrapped in an
`ev-meter-content ie-premium-content-block` div the overlay would hide). Reading
that container directly is the bypass; a JSON-LD `articleBody` in the page is
used only to sanity-check coverage.

The body is reconstructed from the container's block elements (paragraphs,
sub-headings and inline images), skipping the interleaved ad / Taboola /
"also read" / related-story widgets. Images sit on Indian Express's own CDN and
hotlink fine, so nothing is archived.

The listing's `ie_byline_authors` terms give each item its byline (names), and
the author's one-line profile bio comes from the IE profile API
(`/wp-json/wp/v3/profilebyslug/<slug>`); both open the item body when present.

  indianexpress-explained  /section/explained/feed/
  indianexpress-opinion    /section/opinion/feed/

Steady state is polite: only articles not already in the published feed are
fetched. Output: public/<key>/feed.xml + index.html, merged with the previously
published copy (IE_PUBLISHED_BASE_URL) so the feed grows past the RSS window and
survives a transient failure.
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

BASE = "https://indianexpress.com"
# GitHub runners are rejected by the origin's CloudFront, so every API call goes
# through Google's translation relay, which those runners may use.
API_ROOT = "https://indianexpress-com.translate.goog/wp-json"
REST_BASE = f"{API_ROOT}/wp/v2/article"
BYLINE_TERMS_API = f"{API_ROOT}/wp/v2/ie_byline_authors"
BYLINE_PROFILE_API = f"{API_ROOT}/wp/v3/profilebyslug"
# Language passthrough every relayed API call carries.
TRANSLATE_PARAMS = {"_x_tr_sl": "auto", "_x_tr_tl": "en", "_x_tr_hl": "en"}
UA = (
    "Mozilla/5.0 (Linux; Android 15; Pixel 8) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.7922.71 Mobile Safari/537.36"
)
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

# --- global tunables ----------------------------------------------------------
TIMEOUT = int(os.environ.get("IE_TIMEOUT", "60"))
RETRIES = int(os.environ.get("IE_RETRIES", "2"))
OUT_DIR = os.environ.get("IE_OUT_DIR", "public")
PUBLISHED_BASE_URL = os.environ.get("IE_PUBLISHED_BASE_URL", "").strip().rstrip("/")
# Fetch at most this many new articles per section per run (RSS carries ~200).
MAX_FETCH = int(os.environ.get("IE_MAX_FETCH", "60"))

FEEDS = {
    "indianexpress-explained": {
        "title": "Explained - Indian Express",
        "desc": "Unofficial full-text feed of The Indian Express Explained section.",
        "section_id": 442186323,
        "html": f"{BASE}/section/explained/",
        "max_items": 300,
    },
    "indianexpress-opinion": {
        "title": "Opinion - Indian Express",
        "desc": "Unofficial full-text feed of The Indian Express Opinion section.",
        "section_id": 352,
        "html": f"{BASE}/section/opinion/",
        "max_items": 300,
    },
}


# --- http ---------------------------------------------------------------------
def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    return s


def fetch(session: requests.Session, url: str, params: dict | None = None) -> str | None:
    last = None
    for _ in range(RETRIES + 1):
        try:
            r = session.get(url, params=params, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code == 200 and r.text:
                r.encoding = r.apparent_encoding or "utf-8"
                return r.text
            last = f"HTTP {r.status_code}"
            if r.status_code == 404:
                return None
        except requests.RequestException as e:  # pragma: no cover - network
            last = str(e)
    if last:
        print(f"  fetch failed {url}: {last}", file=sys.stderr)
    return None


def fetch_api_items(session: requests.Session, section_id: int) -> list[dict]:
    params = {
        "ie_section": section_id,
        "per_page": 100,
        "_fields": "id,date,link,title,content,featured_media,ie_byline_authors",
        **TRANSLATE_PARAMS,
    }
    last = None
    for _ in range(RETRIES + 1):
        try:
            response = session.get(REST_BASE, params=params, timeout=TIMEOUT)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list):
                    return data
                last = "unexpected JSON response"
            else:
                last = f"HTTP {response.status_code}"
        except (requests.RequestException, ValueError) as exc:
            last = str(exc)
    if last:
        print(f"  REST fetch failed for section {section_id}: {last}", file=sys.stderr)
    return []


# --- xml safety ---------------------------------------------------------------
XML_ILLEGAL_RE = re.compile(
    "[^\x09\x0a\x0d\x20-퟿-�\U00010000-\U0010ffff]"
)


def xml_safe(text: str) -> str:
    return XML_ILLEGAL_RE.sub("", text)


def cdata(text: str) -> str:
    return xml_safe(text).replace("]]>", "]]]]><![CDATA[>")


TAG_RE = re.compile(r"<[^>]+>")


def clean(text: str) -> str:
    return html.unescape(TAG_RE.sub(" ", text or "")).replace("\xa0", " ").strip()


# --- RSS parsing --------------------------------------------------------------
ITEM_RE = re.compile(r"<item>.*?</item>", re.S)


def parse_api_date(value: str) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=IST)


def parse_api_items(raw_items: list[dict]) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    for raw in raw_items:
        link = html.unescape(str(raw.get("link", ""))).strip()
        if not link or link in seen:
            continue
        seen.add(link)
        title = raw.get("title") or {}
        content = raw.get("content") or {}
        items.append(
            {
                "link": link,
                "title": clean(str(title.get("rendered", ""))),
                "author": "",
                "author_bio": "",
                "author_ids": [i for i in raw.get("ie_byline_authors") or [] if i],
                "date": parse_api_date(str(raw.get("date", ""))),
                "content": str(content.get("rendered", "")),
            }
        )
    return items


# --- bylines ------------------------------------------------------------------
# Profile bios vary from one line to several paragraphs; keep the lead sentence.
AUTHOR_BIO_LEN = 300


def fetch_author_terms(session: requests.Session, ids: list[int]) -> dict[int, dict]:
    """Resolve byline-term ids to {name, slug} in one batched call."""
    if not ids:
        return {}
    params = {
        "include": ",".join(str(i) for i in ids),
        "per_page": 100,
        "_fields": "id,name,slug",
        **TRANSLATE_PARAMS,
    }
    text = fetch(session, BYLINE_TERMS_API, params)
    if not text:
        return {}
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    if not isinstance(data, list):
        return {}
    return {int(t["id"]): t for t in data if isinstance(t, dict) and t.get("id")}


def fetch_author_bio(session: requests.Session, slug: str) -> str:
    """One-line author bio from the IE profile API; empty when none is set."""
    text = fetch(session, f"{BYLINE_PROFILE_API}/{slug}", TRANSLATE_PARAMS)
    if not text:
        return ""
    try:
        data = json.loads(text)
    except ValueError:
        return ""
    try:
        bio = clean(str(data["list"][0]["items"][0]["user_description"]))
    except (KeyError, IndexError, TypeError):
        return ""
    if len(bio) > AUTHOR_BIO_LEN:
        bio = bio[:AUTHOR_BIO_LEN].rsplit(" ", 1)[0] + "…"
    return bio


def attach_authors(session: requests.Session, items: list[dict]) -> None:
    """Fill each item's author names (term order kept) and lead-author bio."""
    terms = fetch_author_terms(
        session, sorted({i for it in items for i in it.get("author_ids") or []})
    )
    bios: dict[str, str] = {}
    for it in items:
        names: list[str] = []
        lead_slug = ""
        for uid in it.get("author_ids") or []:
            term = terms.get(uid) or {}
            name = str(term.get("name", "")).strip()
            if not name:
                continue
            names.append(name)
            if not lead_slug:
                lead_slug = str(term.get("slug", "")).strip()
        it["author"] = ", ".join(names)
        if not lead_slug:
            continue
        # One bio line per item: the lead author's.
        if lead_slug not in bios:
            bios[lead_slug] = fetch_author_bio(session, lead_slug)
        it["author_bio"] = bios[lead_slug]


# --- article body -------------------------------------------------------------
BLOCK_RE = re.compile(r"<p\b[^>]*>.*?</p>|<h[234]\b[^>]*>.*?</h[234]>|<img\b[^>]*>", re.S | re.I)
IMG_SRC_RE = re.compile(r'\b(?:data-lazy-src|data-src|src)="([^"]+)"')
# The site's generic lead-image placeholder, served when an article has no real
# image; it carries no content, so it is dropped from the body wherever it
# appears (inline image or og:image hero).
PLACEHOLDER_IMG_PATH = "/wp-content/themes/indianexpress/images/default-ie.jpg"


def _is_placeholder(src: str) -> bool:
    return src.split("?", 1)[0].rstrip("/").endswith(PLACEHOLDER_IMG_PATH)
STRIP_INLINE_RE = re.compile(r"<(script|style|ins|iframe)[^>]*>.*?</\1>", re.S | re.I)
PROMO_RE = re.compile(r"^\s*(also read|also in|read \||subscribe|sign up|newsletter)", re.I)
# Keep the readable structure (p / h3 / strong / em / a / img) but drop the
# publisher's inline styling noise so the body renders cleanly in any reader.
UNWRAP_RE = re.compile(r"</?(?:span|font|div|section)\b[^>]*>", re.I)
ATTR_STRIP_RE = re.compile(
    r'\s+(?:style|class|id|target|rel|onclick|width|height|data-[\w-]+)="[^"]*"', re.I
)


def tidy(inner: str) -> str:
    """Strip inline-style / class noise and stray wrappers, keeping basic tags."""
    inner = UNWRAP_RE.sub("", inner)
    inner = ATTR_STRIP_RE.sub("", inner)
    return re.sub(r"\s{2,}", " ", inner).strip()


def parse_content_blocks(content: str) -> list[tuple[str, str]]:
    """Extract readable paragraphs, headings, and images from article HTML."""
    blocks: list[tuple[str, str]] = []
    for m in BLOCK_RE.finditer(content):
        tag = m.group(0)
        low = tag.lower()
        if low.startswith("<img"):
            s = IMG_SRC_RE.search(tag)
            if s and "wp-content" in s.group(1) and not s.group(1).lower().endswith(".gif"):
                src = html.unescape(s.group(1))
                if not _is_placeholder(src):
                    blocks.append(("img", src))
            continue
        inner = STRIP_INLINE_RE.sub("", tag[tag.find(">") + 1 : tag.rfind("<")]).strip()
        txt = clean(inner)
        if len(txt) < 25 or PROMO_RE.match(txt):
            continue
        blocks.append(("h" if low.startswith("<h") else "p", tidy(inner)))
    return blocks


def render_body(it: dict, hero: str, blocks: list[tuple[str, str]]) -> tuple[str, str]:
    parts: list[str] = []
    if it["author"]:
        parts.append(f"<p><strong>{escape(it['author'])}</strong></p>")
    if it.get("author_bio"):
        parts.append(f"<p><em>{escape(it['author_bio'])}</em></p>")
    if hero:
        parts.append(f'<figure><img src="{escape(hero)}" alt="" /></figure>')
    text_bits: list[str] = []
    for kind, payload in blocks:
        if kind == "img":
            parts.append(f'<figure><img src="{escape(payload)}" alt="" /></figure>')
        elif kind == "h":
            parts.append(f"<h3>{payload}</h3>")
            text_bits.append(clean(payload))
        else:
            parts.append(f"<p>{payload}</p>")
            text_bits.append(clean(payload))
    if not blocks:
        parts.append(f'<p><a href="{escape(it["link"])}">Read on indianexpress.com</a></p>')
    summary = " ".join(text_bits).strip()
    if len(summary) > 500:
        summary = summary[:500].rsplit(" ", 1)[0] + "…"
    return "\n".join(parts), summary


# --- feed I/O -----------------------------------------------------------------
FEEDLINK_RE = re.compile(r"<link>([^<]+)</link>")
PUBDATE_RE = re.compile(r"<pubDate>([^<]+)</pubDate>")


def _block_link(block: str) -> str | None:
    m = FEEDLINK_RE.search(block)
    return html.unescape(m.group(1)).strip() if m else None


def _block_date(block: str) -> dt.datetime:
    m = PUBDATE_RE.search(block)
    if m:
        try:
            return parsedate_to_datetime(m.group(1).strip())
        except (TypeError, ValueError):
            pass
    return dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)


def load_published(session: requests.Session, key: str) -> dict[str, tuple[dt.datetime, str]]:
    if not PUBLISHED_BASE_URL:
        return {}
    body = fetch(session, f"{PUBLISHED_BASE_URL}/{key}/feed.xml")
    if not body:
        return {}
    items: dict[str, tuple[dt.datetime, str]] = {}
    for m in ITEM_RE.finditer(body):
        block = m.group(0).strip()
        link = _block_link(block)
        if link:
            items[link] = (_block_date(block), block)
    print(f"  {key}: loaded {len(items)} published items")
    return items


def render_item(it: dict, body: str, summary: str, when: dt.datetime) -> str:
    return (
        "    <item>\n"
        f"      <title>{escape(xml_safe(it['title']))}</title>\n"
        f"      <link>{escape(it['link'])}</link>\n"
        f"      <guid isPermaLink=\"true\">{escape(it['link'])}</guid>\n"
        + (f"      <dc:creator>{escape(xml_safe(it['author']))}</dc:creator>\n" if it["author"] else "")
        + f"      <pubDate>{format_datetime(when)}</pubDate>\n"
        f"      <description>{escape(xml_safe(summary))}</description>\n"
        f"      <content:encoded><![CDATA[{cdata(body)}]]></content:encoded>\n"
        "    </item>"
    )


def build_feed(key: str, items: dict[str, tuple[dt.datetime, str]]) -> tuple[str, int]:
    feed = FEEDS[key]
    ordered = sorted(items.values(), key=lambda t: t[0], reverse=True)[: feed["max_items"]]
    blocks = [b for _, b in ordered]
    now = format_datetime(dt.datetime.now(IST))
    self_url = f"{PUBLISHED_BASE_URL}/{key}/feed.xml" if PUBLISHED_BASE_URL else ""
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
        f"    <title>{escape(feed['title'])}</title>\n"
        f"    <link>{escape(feed['html'])}</link>\n"
        f"    <description>{escape(feed['desc'])}</description>\n"
        "    <language>en</language>\n"
        f"    <lastBuildDate>{now}</lastBuildDate>\n"
        f"{atom}"
        + "\n".join(blocks)
        + "\n  </channel>\n</rss>\n"
    )
    return xml, len(blocks)


def write_feed(key: str, xml: str, count: int) -> None:
    feed = FEEDS[key]
    d = os.path.join(OUT_DIR, key)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "feed.xml"), "w", encoding="utf-8") as f:
        f.write(xml)
    with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as f:
        f.write(
            "<!doctype html><meta charset='utf-8'>"
            f"<title>{escape(feed['title'])} (unofficial RSS)</title>"
            f"<h1>{escape(feed['title'])} (unofficial)</h1>"
            f"<p>{escape(feed['desc'])}</p>"
            "<p>Subscribe: <a href='feed.xml'>feed.xml</a></p>"
            f"<p>{count} items. Rebuilt automatically.</p>"
        )


# --- per-feed builder ---------------------------------------------------------
def run_feed(session: requests.Session, key: str, now: dt.datetime) -> int:
    print(f"[{key}]")
    merged = load_published(session, key)
    raw_items = fetch_api_items(session, FEEDS[key]["section_id"])
    items = parse_api_items(raw_items)
    print(f"  REST: {len(items)} items")
    new = full = 0
    pending: list[dict] = []
    for it in items:
        if it["link"] in merged:
            break
        if len(pending) >= MAX_FETCH:
            break
        pending.append(it)
    attach_authors(session, pending)
    for it in pending:
        hero = ""
        blocks = parse_content_blocks(it["content"])
        body, summary = render_body(it, hero, blocks)
        if len(blocks) >= 2:
            full += 1
        when = it["date"] or now
        merged[it["link"]] = (when, render_item(it, body, summary, when).strip())
        new += 1
    xml, kept = build_feed(key, merged)
    write_feed(key, xml, kept)
    print(f"  {key}: +{new} new ({full} with full body), feed now {kept}")
    return kept


def main() -> int:
    session = make_session()
    now = dt.datetime.now(IST)
    counts: dict[str, int] = {}
    for key in FEEDS:
        counts[key] = run_feed(session, key, now)
    print("Done:", counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
