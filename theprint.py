#!/usr/bin/env python3
"""Build full-text RSS feeds for ThePrint sections (theprint.in).

ThePrint's own RSS feeds are summary-only ("ThePrint view on the most
important issues.") and occasionally answer with an anti-robot page. The
WordPress REST API at /wp-json/wp/v2/posts returns the same posts with the
complete `content.rendered` body and is served by CloudFront without
challenges, so it is used as the discovery and full-text source.

Feeds (matching the sections subscribed in Inoreader):

    theprint-national-interest
    theprint-essential
    theprint-50-word-edit
    theprint-diplomacy
    theprint-past-forward

Each feed backfills the last TP_DAYS (default 21) and merges the published
copy so history survives beyond the window. Bodies keep paragraphs, headings,
quotes, lists, links and responsive images; "Also Read:" / "Read More:"
related-link blocks and auto-generated disclaimers are dropped. Output:
public/<key>/feed.xml + index.html.
"""
from __future__ import annotations

import datetime as dt
import html
import os
import re
import sys
import time
from email.utils import format_datetime, parsedate_to_datetime
from xml.sax.saxutils import escape

import requests

BASE = "https://theprint.in"
REST = BASE + "/wp-json/wp/v2/posts"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.7922.76 Safari/537.36"
)
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

# --- global tunables ----------------------------------------------------------
DAYS = int(os.environ.get("TP_DAYS", "21"))
TIMEOUT = int(os.environ.get("TP_TIMEOUT", "30"))
RETRIES = int(os.environ.get("TP_RETRIES", "2"))
MAX_ITEMS = int(os.environ.get("TP_MAX_ITEMS", "300"))
PER_PAGE = 100
OUT_DIR = os.environ.get("TP_OUT_DIR", "public")
PUBLISHED_BASE_URL = os.environ.get("TP_PUBLISHED_BASE_URL", "").strip().rstrip("/")

FEEDS = [
    {
        "key": "theprint-national-interest",
        "cat": 5,
        "title": "National Interest - ThePrint",
        "desc": "Unofficial full-text feed of ThePrint National Interest.",
        "section": BASE + "/category/national-interest/",
    },
    {
        "key": "theprint-essential",
        "cat": 63904,
        "title": "Essential - ThePrint",
        "desc": "Unofficial full-text feed of ThePrint Essential explainers.",
        "section": BASE + "/category/theprint-essential/",
    },
    {
        "key": "theprint-50-word-edit",
        "cat": 109887,
        "title": "50-Word Edit - ThePrint",
        "desc": "Unofficial full-text feed of ThePrint 50-Word Edit.",
        "section": BASE + "/category/50-word-edit/",
    },
    {
        "key": "theprint-diplomacy",
        "cat": 102046,
        "title": "Diplomacy - ThePrint",
        "desc": "Unofficial full-text feed of ThePrint Diplomacy.",
        "section": BASE + "/category/diplomacy/",
    },
    {
        "key": "theprint-past-forward",
        "cat": 8606,
        "title": "PastForward - ThePrint",
        "desc": "Unofficial full-text feed of ThePrint PastForward.",
        "section": BASE + "/category/past-forward/",
    },
]


# --- http ---------------------------------------------------------------------
def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "en"})
    return s


def fetch_json(session: requests.Session, url: str, params: dict) -> list | None:
    last = None
    for _ in range(RETRIES + 1):
        try:
            r = session.get(url, params=params, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code}"
        except (requests.RequestException, ValueError) as e:
            last = str(e)
    if last:
        print(f"  fetch failed {url}: {last}", file=sys.stderr)
    return None


def fetch_text(session: requests.Session, url: str) -> str | None:
    last = None
    for _ in range(RETRIES + 1):
        try:
            r = session.get(url, timeout=TIMEOUT)
            if r.status_code == 200 and r.text:
                return r.text
            if r.status_code == 404:
                return None
            last = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            last = str(e)
    if last:
        print(f"  fetch failed {url}: {last}", file=sys.stderr)
    return None


# --- sanitizing ---------------------------------------------------------------
TAG_RE = re.compile(r"<[^>]+>")
# Related-reading promos and wire-copy disclaimers; "Edited by ..." credits are
# attribution and stay.
PROMO_RE = re.compile(r"^\s*(also read|read more|related|disclaimer)\s*:", re.I)
ALLOWED = {
    "p", "h2", "h3", "h4", "blockquote", "ul", "ol", "li", "a", "em", "strong",
    "b", "i", "br", "figure", "img", "figcaption",
}


def strip_tags(s: str) -> str:
    return html.unescape(TAG_RE.sub(" ", s)).strip()


def _clean_img(m: re.Match) -> str:
    src = re.search(r'\bsrc="([^"]+)"', m.group(0))
    if not src:
        return ""
    alt = re.search(r'\balt="([^"]*)"', m.group(0))
    alt_attr = escape(html.unescape(alt.group(1))) if alt else ""
    return (
        f'<img src="{escape(html.unescape(src.group(1)))}" alt="{alt_attr}" '
        'style="max-width:100%;height:auto;" />'
    )


def _figure(fragment: str) -> str:
    img = re.search(r"<img\b[^>]*>", fragment, re.I)
    if not img:
        return ""
    out = _clean_img(img)
    cap = re.search(r"<figcaption[^>]*>(.*?)</figcaption>", fragment, re.S | re.I)
    if cap:
        text = strip_tags(cap.group(1))
        if text:
            out += f"<figcaption>{escape(text)}</figcaption>"
    return f"<figure>{out}</figure>"


def _drop_promos(s: str) -> str:
    def repl(m: re.Match) -> str:
        return "" if PROMO_RE.match(strip_tags(m.group(0))) else m.group(0)

    return re.sub(r"<p\b.*?</p>", repl, s, flags=re.S | re.I)


def sanitize_body(raw: str) -> str:
    s = re.sub(r"<!--.*?-->", "", raw, flags=re.S)
    s = re.sub(r"<(script|style|iframe|ins|embed)\b.*?</\1>", "", s, flags=re.S | re.I)
    s = _drop_promos(s)
    s = re.sub(r"<figure\b.*?</figure>", lambda m: _figure(m.group(0)), s, flags=re.S | re.I)
    s = re.sub(r"</?span\b[^>]*>", "", s, flags=re.I)
    s = re.sub(r"<(strong|em|b|i|br|figure|figcaption)\b[^>]*>", r"<\1>", s, flags=re.I)
    s = re.sub(r"<img\b[^>]*>", _clean_img, s, flags=re.I)
    s = re.sub(r"<(p|h2|h3|h4|blockquote|ul|ol|li)\b[^>]*>", r"<\1>", s, flags=re.I)
    s = re.sub(
        r'<a\b[^>]*\bhref="([^"]+)"[^>]*>(.*?)</a>',
        lambda m: f'<a href="{escape(html.unescape(m.group(1)))}">{m.group(2)}</a>',
        s,
        flags=re.S | re.I,
    )
    s = re.sub(
        r"</?([a-zA-Z0-9]+)[^>]*>",
        lambda m: m.group(0) if m.group(1).lower() in ALLOWED else "",
        s,
    )
    s = re.sub(r"<hr\b[^>]*/?>", "", s, flags=re.I)
    s = re.sub(r"<p>\s*(?:&nbsp;|\s)*</p>", "", s, flags=re.I)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


# --- feed I/O -----------------------------------------------------------------
ITEM_RE = re.compile(r"<item>.*?</item>", re.S)
GUID_ID_RE = re.compile(r"/(\d+)/?\s*$")
PUBDATE_RE = re.compile(r"<pubDate>([^<]+)</pubDate>")


def _block_date(block: str) -> dt.datetime:
    m = PUBDATE_RE.search(block)
    if m:
        try:
            return parsedate_to_datetime(m.group(1).strip())
        except (TypeError, ValueError):
            pass
    return dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)


def load_published(session: requests.Session, key: str) -> dict[int, str]:
    body = None
    local_path = os.path.join(OUT_DIR, key, "feed.xml")
    if os.path.exists(local_path):
        try:
            with open(local_path, encoding="utf-8") as f:
                body = f.read()
        except Exception:
            pass
    if not body and PUBLISHED_BASE_URL:
        body = fetch_text(session, f"{PUBLISHED_BASE_URL}/{key}/feed.xml")
    if not body:
        return {}
    items: dict[int, str] = {}
    for m in ITEM_RE.finditer(body):
        block = m.group(0)
        g = re.search(r"<guid[^>]*>([^<]+)</guid>", block)
        id_m = GUID_ID_RE.search(g.group(1).strip()) if g else None
        if id_m:
            items[int(id_m.group(1))] = block.strip()
    print(f"  {key}: loaded {len(items)} published items")
    return items


def render_item(post: dict) -> str:
    title = strip_tags(post["title"]["rendered"])
    link = post["link"]
    date = dt.datetime.fromisoformat(post["date"]).replace(tzinfo=IST)
    body = sanitize_body(post["content"]["rendered"])
    summary = strip_tags(body)
    if len(summary) > 500:
        summary = summary[:500].rsplit(" ", 1)[0] + "…"
    return (
        "    <item>\n"
        f"      <title>{escape(title)}</title>\n"
        f"      <link>{escape(link)}</link>\n"
        f'      <guid isPermaLink="true">{escape(link)}</guid>\n'
        f"      <pubDate>{format_datetime(date)}</pubDate>\n"
        f"      <description>{escape(summary)}</description>\n"
        f"      <content:encoded><![CDATA[{body}]]></content:encoded>\n"
        "    </item>"
    )


def build_feed(feed: dict, items: dict[int, str]) -> str:
    ordered = [
        items[i]
        for i in sorted(items, key=lambda i: (_block_date(items[i]), i), reverse=True)
    ][:MAX_ITEMS]
    now = format_datetime(dt.datetime.now(IST))
    self_url = f"{PUBLISHED_BASE_URL}/{feed['key']}/feed.xml" if PUBLISHED_BASE_URL else ""
    atom = (
        f'    <atom:link href="{escape(self_url)}" rel="self" type="application/rss+xml" />\n'
        if self_url
        else ""
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" '
        'xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "  <channel>\n"
        f"    <title>{escape(feed['title'])}</title>\n"
        f"    <link>{escape(feed['section'])}</link>\n"
        f"    <description>{escape(feed['desc'])}</description>\n"
        "    <language>en</language>\n"
        f"    <lastBuildDate>{now}</lastBuildDate>\n"
        f"{atom}"
        + "\n".join(ordered)
        + "\n  </channel>\n</rss>\n"
    )


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
def collect_posts(session: requests.Session, feed: dict, after: str) -> list[dict]:
    """All posts for the category after `after`, newest page first."""
    posts: list[dict] = []
    for page in range(1, 6):
        batch = fetch_json(
            session,
            REST,
            {
                "categories": feed["cat"],
                "per_page": PER_PAGE,
                "page": page,
                "after": after,
                "_fields": "id,date,link,title,content",
            },
        )
        if not batch:
            break
        posts.extend(batch)
        if len(batch) < PER_PAGE:
            break
        time.sleep(0.5)
    return posts


def run_feed(session: requests.Session, feed: dict) -> int:
    print(f"[{feed['key']}]")
    existing = load_published(session, feed["key"])
    after = (dt.datetime.now(IST) - dt.timedelta(days=DAYS)).strftime("%Y-%m-%dT%H:%M:%S")
    posts = collect_posts(session, feed, after)
    print(f"  {feed['key']}: {len(posts)} posts in last {DAYS} days")
    found = 0
    for post in posts:
        if post["id"] in existing:
            continue
        existing[post["id"]] = render_item(post).strip()
        found += 1
    xml = build_feed(feed, existing)
    kept = min(len(existing), MAX_ITEMS)
    write_feed(feed, xml, kept)
    print(f"  {feed['key']}: added {found}, feed now {kept}")
    return kept


def main() -> int:
    session = make_session()
    counts = {}
    for feed in FEEDS:
        counts[feed["key"]] = run_feed(session, feed)
    print("Done:", counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
