#!/usr/bin/env python3
"""Build full-text RSS feeds of Frontline (frontline.thehindu.com).

Frontline is The Hindu group's national fortnightly magazine. Its official
feeders (`/<section>/feeder/default.rss`) are headline + standfirst only — no
body — so this rebuilds them as full-text feeds. Two disjoint feeds are built:

  frontline_magazine  the print fortnightly's contents (current-issue + magazine
                      feeders). This is the issue's editorial table of contents;
                      nothing is dropped.
  frontline_blog      "Digital Exclusives" — web-only pieces under /blog/. A
                      separate path and feeder, with zero overlap with the
                      magazine feed.

The paywall is Piano.io, a purely client-side gate: the Bypass-Paywalls rule for
thehindu.com just blocks piano.io / cxense / amp-subscriptions JS. A server-side
fetch never runs that JS, and the complete article ships in the HTML anyway,
inside `<div id="content-body-<ID>" class="articlebodycontent" itemprop=
"articleBody">`. So there is no bypass to perform — a plain GET gets full text.

Discovery uses the official feeders (item URLs, ids, categories, pubDates); only
articles not already in the published feed are fetched. Images live on the
fl-i.thgim.com CDN (lazy-loaded via `data-original`) and hotlink fine, so no
archive mode is needed. Output: public/<key>/{feed.xml,index.html}, merged with
the previously published copy (FL_PUBLISHED_BASE_URL) so each feed grows past the
feeder window and survives a transient failure.
"""
from __future__ import annotations

import datetime as dt
import html
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime, format_datetime
from xml.sax.saxutils import escape

import requests

BASE = "https://frontline.thehindu.com"
UA = os.environ.get(
    "FL_UA",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.7922.76 Safari/537.36",
)
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

# --- tunables -----------------------------------------------------------------
TIMEOUT = int(os.environ.get("FL_TIMEOUT", "60"))
RETRIES = int(os.environ.get("FL_RETRIES", "2"))
WORKERS = int(os.environ.get("FL_WORKERS", "6"))
OUT_DIR = os.environ.get("FL_OUT_DIR", "public")
PUBLISHED_BASE_URL = os.environ.get("FL_PUBLISHED_BASE_URL", "").strip().rstrip("/")
# Fetch at most this many new articles per feed per run.
MAX_FETCH = int(os.environ.get("FL_MAX_FETCH", "120"))
MAX_ITEMS = int(os.environ.get("FL_MAX_ITEMS", "400"))

# The magazine feeder is already the print issue's curated table of contents —
# no advertorial supplements like India Today has — so nothing is dropped by
# default. Set FL_MAG_DROP_SECTIONS (comma-separated first-path-segments, e.g.
# "photo-essay") to filter anyway; the blog feed is never filtered.
MAG_DROP = {
    s.strip() for s in os.environ.get("FL_MAG_DROP_SECTIONS", "").split(",") if s.strip()
}
SECTION_RE = re.compile(r"^https?://[^/]+/([a-z0-9-]+)/")


def section_of(url: str) -> str:
    m = SECTION_RE.match(url or "")
    return m.group(1) if m else ""


# --- feed table ---------------------------------------------------------------
FEEDS = [
    {
        "key": "frontline_magazine",
        "title": "Magazine - Frontline",
        "desc": "Unofficial full-text feed of Frontline, India's national fortnightly magazine.",
        "html": f"{BASE}/current-issue/",
        # Union of the current-issue and magazine section feeders.
        "feeders": [
            f"{BASE}/current-issue/feeder/default.rss",
            f"{BASE}/magazine/feeder/default.rss",
        ],
        "drop": MAG_DROP,
    },
    {
        "key": "frontline_blog",
        "title": "Digital Exclusives - Frontline",
        "desc": "Unofficial full-text feed of Frontline's web-only Digital Exclusives.",
        "html": f"{BASE}/blog/",
        "feeders": [f"{BASE}/blog/feeder/default.rss"],
        "drop": set(),
    },
]


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


def fetch(session: requests.Session, url: str) -> str | None:
    last = None
    for _ in range(RETRIES + 1):
        try:
            r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
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


# --- xml / text safety --------------------------------------------------------
XML_ILLEGAL_RE = re.compile(
    "[^\x09\x0a\x0d\x20-퟿-�\U00010000-\U0010ffff]"
)


def xml_safe(text: str) -> str:
    return XML_ILLEGAL_RE.sub("", text or "")


def cdata(text: str) -> str:
    return xml_safe(text).replace("]]>", "]]]]><![CDATA[>")


TAG_RE = re.compile(r"<[^>]+>")


def clean(text: str) -> str:
    return html.unescape(TAG_RE.sub(" ", text or "")).replace("\xa0", " ").strip()


# --- article parsing ----------------------------------------------------------
BODY_RE = re.compile(
    r'<div id="content-body-\d+"[^>]*itemprop="articleBody"[^>]*>(.*?)'
    r'<div class="comments-shares',
    re.S | re.I,
)
OG_TITLE_RE = re.compile(r'property="og:title"\s*content="([^"]*)"', re.I)
OG_DESC_RE = re.compile(r'property="og:description"\s*content="([^"]*)"', re.I)
OG_IMAGE_RE = re.compile(r'property="og:image"\s*content="([^"]*)"', re.I)
PUB_RE = re.compile(r'"datePublished"\s*content="([^"]*)"', re.I)
UPD_RE = re.compile(r'"dateModified"\s*content="([^"]*)"', re.I)
AUTHOR_RE = re.compile(
    r'<a[^>]*/profile/author/[^>]*class="person-name[^"]*"[^>]*>(.*?)</a>', re.I | re.S
)

BLOCK_RE = re.compile(
    r"<p\b[^>]*>.*?</p>|<h[234]\b[^>]*>.*?</h[234]>|"
    r"<blockquote\b[^>]*>.*?</blockquote>|<img\b[^>]*>",
    re.S | re.I,
)
IMG_URL_RE = re.compile(r'\bdata-original="([^"]+)"|\bdata-src-template="([^"]+)"', re.I)
STRIP_INLINE_RE = re.compile(r"<(script|style|ins|iframe)[^>]*>.*?</\1>", re.S | re.I)
PROMO_RE = re.compile(
    r"^\s*(also read|also watch|subscribe|sign up|newsletter|read more|"
    r"featured comment|commented by|click to reply)",
    re.I,
)
UNWRAP_RE = re.compile(
    r"</?(?:span|font|div|section|article|figure|figcaption|picture)\b[^>]*>", re.I
)
ATTR_STRIP_RE = re.compile(
    r'\s+(?:style|class|id|target|rel|onclick|width|height|title|loading|data-[\w-]+)="[^"]*"',
    re.I,
)


def tidy(inner: str) -> str:
    inner = UNWRAP_RE.sub("", inner)
    inner = ATTR_STRIP_RE.sub("", inner)
    return re.sub(r"\s{2,}", " ", inner).strip()


def parse_blocks(body_html: str) -> list[tuple[str, str]]:
    """Return [(kind, html)] over the body's p / h / blockquote / img blocks."""
    blocks: list[tuple[str, str]] = []
    seen_img: set[str] = set()
    for m in BLOCK_RE.finditer(body_html or ""):
        tag = m.group(0)
        low = tag.lower()
        if low.startswith("<img"):
            u = IMG_URL_RE.search(tag)
            src = html.unescape((u.group(1) or u.group(2)).strip()) if u else ""
            if src and "thgim.com" in src and not src.lower().endswith(".gif"):
                if src not in seen_img:
                    seen_img.add(src)
                    blocks.append(("img", src))
            continue
        inner = STRIP_INLINE_RE.sub("", tag[tag.find(">") + 1 : tag.rfind("<")]).strip()
        txt = clean(inner)
        if len(txt) < 8 or PROMO_RE.match(txt):
            continue
        kind = "q" if low.startswith("<blockquote") else "h" if low.startswith("<h") else "p"
        blocks.append((kind, tidy(inner)))
    return blocks


def authors(page: str) -> str:
    out: list[str] = []
    for raw in AUTHOR_RE.findall(page or ""):
        name = re.sub(r"\s+", " ", clean(raw)).rstrip(",").strip()
        if name and name not in out:
            out.append(name)
    return ", ".join(out)


def pub_date(page: str, fallback: dt.datetime) -> dt.datetime:
    for rx in (PUB_RE, UPD_RE):
        m = rx.search(page or "")
        if m:
            raw = m.group(1).strip()
            for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
                try:
                    return dt.datetime.strptime(raw, fmt)
                except ValueError:
                    continue
    return fallback


def _meta(rx: re.Pattern, page: str) -> str:
    m = rx.search(page or "")
    return html.unescape(m.group(1)).strip() if m else ""


def build_article(session: requests.Session, url: str, fallback: dt.datetime) -> dict | None:
    page = fetch(session, url)
    if not page:
        return None
    mb = BODY_RE.search(page)
    if not mb:
        return None
    title = _meta(OG_TITLE_RE, page)
    if not title:
        return None
    # Drop inline <script>/<style> first: a comment-loader script inside the body
    # div builds markup with template literals, whose <p> strings would otherwise
    # be picked up as body paragraphs.
    blocks = parse_blocks(STRIP_INLINE_RE.sub("", mb.group(1)))
    hero = _meta(OG_IMAGE_RE, page)
    author = authors(page)
    when = pub_date(page, fallback)
    summary = clean(_meta(OG_DESC_RE, page))
    if not summary:
        summary = " ".join(clean(h) for k, h in blocks if k == "p")[:500]

    parts: list[str] = []
    if author:
        parts.append(f"<p><strong>{escape(author)}</strong></p>")
    first_img = next((h for k, h in blocks if k == "img"), None)
    if hero and hero != first_img:
        parts.append(f'<figure><img src="{escape(hero)}" alt="" /></figure>')
    for kind, payload in blocks:
        if kind == "img":
            parts.append(f'<figure><img src="{escape(payload)}" alt="" /></figure>')
        elif kind == "h":
            parts.append(f"<h3>{payload}</h3>")
        elif kind == "q":
            parts.append(f"<blockquote>{payload}</blockquote>")
        else:
            parts.append(f"<p>{payload}</p>")
    if not blocks:
        parts.append(f'<p><a href="{escape(url)}">Read on frontline.thehindu.com</a></p>')
    return {
        "link": url,
        "title": title,
        "author": author,
        "section": section_of(url),
        "date": when,
        "body": "\n".join(parts),
        "summary": summary,
    }


# --- feeder discovery ---------------------------------------------------------
FEED_ITEM_RE = re.compile(r"<item>(.*?)</item>", re.S)
FEED_LINK_RE = re.compile(r"<link>\s*(?:<!\[CDATA\[)?\s*([^<\]]+?)\s*(?:\]\]>)?\s*</link>", re.S)
FEED_DATE_RE = re.compile(r"<pubDate>\s*(?:<!\[CDATA\[)?\s*([^<\]]+?)\s*(?:\]\]>)?\s*</pubDate>", re.S)


def discover(session: requests.Session, feed: dict) -> list[tuple[str, dt.datetime]]:
    """Return [(article_url, feeder_pubdate)] for a feed's feeders, de-duped."""
    found: dict[str, dt.datetime] = {}
    for feeder in feed["feeders"]:
        body = fetch(session, feeder)
        if not body:
            continue
        for block in FEED_ITEM_RE.findall(body):
            ml = FEED_LINK_RE.search(block)
            if not ml:
                continue
            url = html.unescape(ml.group(1)).strip()
            if not url.endswith(".ece"):
                continue
            if feed["drop"] and section_of(url) in feed["drop"]:
                continue
            md = FEED_DATE_RE.search(block)
            when = dt.datetime(1970, 1, 1, tzinfo=IST)
            if md:
                try:
                    when = parsedate_to_datetime(md.group(1).strip())
                except (TypeError, ValueError):
                    pass
            if url not in found:
                found[url] = when
    return list(found.items())


# --- feed I/O -----------------------------------------------------------------
ITEM_RE = re.compile(r"<item>.*?</item>", re.S)
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


def load_published(session: requests.Session, feed: dict) -> dict[str, tuple[dt.datetime, str]]:
    if not PUBLISHED_BASE_URL:
        return {}
    body = fetch(session, f"{PUBLISHED_BASE_URL}/{feed['key']}/feed.xml")
    if not body:
        return {}
    items: dict[str, tuple[dt.datetime, str]] = {}
    for m in ITEM_RE.finditer(body):
        block = m.group(0).strip()
        link = _block_link(block)
        if link and not (feed["drop"] and section_of(link) in feed["drop"]):
            items[link] = (_block_date(block), block)
    print(f"  [{feed['key']}] loaded {len(items)} published items")
    return items


def render_item(art: dict) -> str:
    cat = f"      <category>{escape(xml_safe(art['section']))}</category>\n" if art["section"] else ""
    creator = (
        f"      <dc:creator>{escape(xml_safe(art['author']))}</dc:creator>\n"
        if art["author"]
        else ""
    )
    return (
        "    <item>\n"
        f"      <title>{escape(xml_safe(art['title']))}</title>\n"
        f"      <link>{escape(art['link'])}</link>\n"
        f"      <guid isPermaLink=\"true\">{escape(art['link'])}</guid>\n"
        + creator
        + cat
        + f"      <pubDate>{format_datetime(art['date'])}</pubDate>\n"
        f"      <description>{escape(xml_safe(art['summary']))}</description>\n"
        f"      <content:encoded><![CDATA[{cdata(art['body'])}]]></content:encoded>\n"
        "    </item>"
    )


def build_feed(feed: dict, items: dict[str, tuple[dt.datetime, str]]) -> tuple[str, int]:
    ordered = sorted(items.values(), key=lambda t: t[0], reverse=True)[:MAX_ITEMS]
    blocks = [b for _, b in ordered]
    now = format_datetime(dt.datetime.now(IST))
    self_url = f"{PUBLISHED_BASE_URL}/{feed['key']}/feed.xml" if PUBLISHED_BASE_URL else ""
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


def write_feed(feed: dict, xml: str, count: int) -> None:
    d = os.path.join(OUT_DIR, feed["key"])
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


# --- main ---------------------------------------------------------------------
def build_one(session: requests.Session, feed: dict, now: dt.datetime) -> None:
    print(f"[{feed['key']}]")
    merged = load_published(session, feed)
    candidates = discover(session, feed)
    print(f"  {len(candidates)} feeder candidates"
          + (f" (dropping sections: {', '.join(sorted(feed['drop']))})" if feed["drop"] else ""))

    newest_published = max((when for when, _ in merged.values()), default=None)
    newer = [
        (url, when)
        for url, when in candidates
        if url not in merged and (newest_published is None or when >= newest_published)
    ]
    todo = newer[:MAX_FETCH]
    if len(newer) > MAX_FETCH:
        print(f"  capping new fetches at MAX_FETCH={MAX_FETCH}")

    new = full = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        arts = list(ex.map(lambda uw: build_article(session, uw[0], uw[1]), todo))
    for art in arts:
        new += 1
        if not art:
            continue
        if art["body"].count("<p>") >= 2:
            full += 1
        merged[art["link"]] = (art["date"], render_item(art).strip())

    xml, kept = build_feed(feed, merged)
    write_feed(feed, xml, kept)
    print(f"  +{len(todo)} fetched ({full} with full body), feed now {kept}")


def main() -> int:
    session = make_session()
    now = dt.datetime.now(IST)
    only = {k.strip() for k in os.environ.get("FL_ONLY", "").split(",") if k.strip()}
    for feed in FEEDS:
        if only and feed["key"] not in only:
            continue
        build_one(session, feed, now)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
