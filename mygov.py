#!/usr/bin/env python3
"""Build RSS feeds for MyGov (mygov.in) PDF publications.

Three MyGov listings publish issues only as PDFs, with no RSS:

    bharat_matters   https://www.mygov.in/bharat-matters
    pulse_newsletter https://www.mygov.in/pulse-newsletter
    mann_ki_baat     https://www.mygov.in/read-mkb-more   (Read Mann Ki Baat)

Each is a paginated Drupal listing whose cards link a title, an ebook page and a
direct PDF on static.mygov.in. This script SCRAPES the actual PDF link from each
card (rather than constructing URLs), reads the card title, derives the date
from the Unix timestamp embedded in the PDF filename, and emits an item per
issue. It walks pages until one yields no new PDFs.

Item body links the PDF; from ARCHIVE_MIN_YEAR onward the PDFs are also mirrored
to the release (see archive_pdfs.py / DOCS.md). Output: public/<key>/feed.xml +
index.html, merged with the published feed to retain history.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import os
import re
import sys
from email.utils import format_datetime, parsedate_to_datetime
from urllib.parse import unquote
from xml.sax.saxutils import escape

import requests

BASE = "https://www.mygov.in"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.7922.76 Safari/537.36"
)
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

# --- tunables -----------------------------------------------------------------
TIMEOUT = int(os.environ.get("MYGOV_TIMEOUT", "30"))
RETRIES = int(os.environ.get("MYGOV_RETRIES", "2"))
MAX_PAGES = int(os.environ.get("MYGOV_MAX_PAGES", "8"))
OUT_DIR = os.environ.get("MYGOV_OUT_DIR", "public")
PUBLISHED_BASE_URL = os.environ.get("MYGOV_PUBLISHED_BASE_URL", "").strip().rstrip("/")
ARCHIVE_MODE = os.environ.get("MYGOV_ARCHIVE_MODE", "link").strip().lower()
ARCHIVE_BASE_URL = os.environ.get("MYGOV_ARCHIVE_BASE_URL", "").strip().rstrip("/")
ARCHIVE_DIR = os.environ.get("ARCHIVE_MANIFEST_DIR", "archive")
ARCHIVE_MIN_YEAR = int(os.environ.get("ARCHIVE_MIN_YEAR", "2024"))

FEEDS = [
    {
        "key": "mygov_bharatmatters",
        "title": "Bharat Matters - MyGov",
        "desc": "Unofficial PDF feed of MyGov Bharat Matters.",
        "path": "/bharat-matters",
        "max_items": 200,
    },
    {
        "key": "mygov_pulsenewsletter",
        "title": "Pulse Newsletter - MyGov",
        "desc": "Unofficial PDF feed of the MyGov Pulse newsletter.",
        "path": "/pulse-newsletter",
        "max_items": 200,
    },
    {
        "key": "mygov_mannkibaat",
        "title": "Read Mann Ki Baat - MyGov",
        "desc": "Unofficial feed of Mann Ki Baat monthly booklets from MyGov.",
        "path": "/read-mkb-more",
        "max_items": 100,
    },
]


# --- http ---------------------------------------------------------------------
def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "en"})
    return s


def fetch(session: requests.Session, url: str) -> str | None:
    last = None
    for _ in range(RETRIES + 1):
        try:
            r = session.get(url, timeout=TIMEOUT)
            if r.status_code == 200 and r.text:
                r.encoding = r.apparent_encoding or "utf-8"
                return r.text
            last = f"HTTP {r.status_code}"
        except requests.RequestException as e:  # pragma: no cover - network
            last = str(e)
    if last:
        print(f"  fetch failed {url}: {last}", file=sys.stderr)
    return None


# --- scraping -----------------------------------------------------------------
CARD_RE = re.compile(
    r'<div[^>]+class=["\'][^"\']*news-item[^"\']*["\'].*?'
    r'(?=(?:<div[^>]+class=["\'][^"\']*news-item|\Z))',
    re.S,
)
PDF_RE = re.compile(r'https://static\.mygov\.in/[^"\'\s]+\.pdf', re.I)
HEAD_RE = re.compile(r"<h[1-5][^>]*>(.*?)</h[1-5]>", re.S | re.I)
EBOOK_RE = re.compile(r"(https://www\.mygov\.in/mygov-ebook/[a-z0-9-]+)", re.I)
EBOOK_SHARE_RE = re.compile(
    r'sharer\.php\?u=(https%3A%2F%2Fwww\.mygov\.in%2Fmygov-ebook%2F[a-z0-9-]+|https://www\.mygov\.in/mygov-ebook/[a-z0-9-]+)',
    re.I,
)
EPOCH_RE = re.compile(r"mygov_(\d{10})")
PUBLISH_TIME_RE = re.compile(
    r'class=["\'][^"\']*publish-time[^"\']*["\'][^>]*>\s*(\d{1,2})/(\d{1,2})/(\d{4})',
    re.I,
)
TITLE_DATE_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b",
    re.I,
)
MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
TAG_RE = re.compile(r"<[^>]+>")


def _slug(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


def _parse_card_date(card_text: str, title: str, pdf: str) -> dt.datetime | None:
    dm = PUBLISH_TIME_RE.search(card_text)
    if dm:
        d, mo, y = int(dm.group(1)), int(dm.group(2)), int(dm.group(3))
        try:
            return dt.datetime(y, mo, d, 12, 0, tzinfo=IST)
        except ValueError:
            pass

    tm = TITLE_DATE_RE.search(title)
    if tm:
        mo = MONTHS.get(tm.group(1).lower(), 1)
        y = int(tm.group(2))
        return dt.datetime(y, mo, 1, 12, 0, tzinfo=IST)

    em = EPOCH_RE.search(pdf)
    if em:
        try:
            return dt.datetime.fromtimestamp(int(em.group(1)), tz=dt.timezone.utc).astimezone(IST)
        except (ValueError, OSError):
            pass

    return None


def parse_page(page: str) -> list[dict]:
    """Extract (title, ebook link, pdf, date) per card by scraping the page."""
    cards = CARD_RE.findall(page)
    if cards:
        out = []
        for c in cards:
            pm = PDF_RE.search(c)
            if not pm:
                continue
            pdf = pm.group(0)
            hm = HEAD_RE.search(c)
            title = html.unescape(TAG_RE.sub("", hm.group(1))).strip() if hm else ""
            eb = EBOOK_RE.findall(c)
            if eb:
                link = eb[-1]
            else:
                sm = EBOOK_SHARE_RE.search(c)
                link = unquote(sm.group(1)) if sm else pdf
            date = _parse_card_date(c, title, pdf)
            em = EPOCH_RE.search(pdf)
            item_id = int(em.group(1)) if em else int(hashlib.md5(pdf.encode()).hexdigest(), 16) % (10**10)
            out.append({"id": item_id, "pdf": pdf, "link": link, "title": title, "date": date})
        return out

    out = []
    for m in PDF_RE.finditer(page):
        pdf = m.group(0)
        window = page[max(0, m.start() - 2500) : m.start()]
        heads = [html.unescape(TAG_RE.sub("", h)).strip() for h in HEAD_RE.findall(window)]
        heads = [h for h in heads if h]
        title = heads[-1] if heads else ""
        eb = EBOOK_RE.findall(window)
        link = eb[-1] if eb else pdf
        date = _parse_card_date(window, title, pdf)
        em = EPOCH_RE.search(pdf)
        item_id = int(em.group(1)) if em else int(hashlib.md5(pdf.encode()).hexdigest(), 16) % (10**10)
        out.append({"id": item_id, "pdf": pdf, "link": link, "title": title, "date": date})
    return out


def archival_name(key: str, art: dict) -> str:
    src = key.replace("mygov_", "")
    stamp = art["date"].strftime("%Y-%m-%d") if art.get("date") else str(art.get("id", "item"))
    slug = _slug(art["link"]) if art.get("link", "").startswith(BASE) else str(art.get("id", "item"))
    return f"mygov_{src}_{stamp}_{slug}.pdf"[:180]


def collect(
    session: requests.Session, feed: dict, published_guids: set[str]
) -> list[dict]:
    items: dict[str, dict] = {}
    for page_no in range(MAX_PAGES):
        page = fetch(session, f"{BASE}{feed['path']}?page={page_no}")
        if not page:
            break
        listed = parse_page(page)
        if not listed:
            break
        fresh = 0
        in_range = 0
        all_past_min_year = True
        for art in listed:
            year = art["date"].year if art.get("date") else None
            if year is not None and year < ARCHIVE_MIN_YEAR:
                continue
            all_past_min_year = False
            in_range += 1
            if art["pdf"] not in items:
                items[art["pdf"]] = art
                if art["pdf"] not in published_guids:
                    fresh += 1
        print(f"  {feed['key']} page={page_no}: {len(listed)} listed, {fresh} new, {in_range} in-range")
        if all_past_min_year:
            break
        if published_guids and in_range > 0 and fresh == 0:
            break
    return list(items.values())


def archive_base_for(art: dict) -> str:
    if not ARCHIVE_BASE_URL:
        return ""
    year = art["date"].year if art.get("date") else dt.datetime.now(IST).year
    return ARCHIVE_BASE_URL.format(year=year) if "{year}" in ARCHIVE_BASE_URL else ARCHIVE_BASE_URL


def archive_tag_for(art: dict) -> str:
    base = archive_base_for(art)
    return base.rsplit("/", 1)[-1] if base else "pdf-archive"


def item_pdf_url(key: str, art: dict) -> str:
    if ARCHIVE_MODE == "archive" and ARCHIVE_BASE_URL:
        base = archive_base_for(art)
        return f"{base}/{archival_name(key, art)}"
    return art["pdf"]


# --- feed I/O -----------------------------------------------------------------
ITEM_RE = re.compile(r"<item>.*?</item>", re.S)
GUID_TAG_RE = re.compile(r"<guid[^>]*>([^<]+)</guid>")
PUBDATE_RE = re.compile(r"<pubDate>([^<]+)</pubDate>")


def load_published(session: requests.Session, key: str) -> dict[str, tuple[str, dt.datetime]]:
    if not PUBLISHED_BASE_URL:
        return {}
    body = fetch(session, f"{PUBLISHED_BASE_URL}/{key}/feed.xml")
    if not body:
        return {}
    items: dict[str, tuple[str, dt.datetime]] = {}
    for m in ITEM_RE.finditer(body):
        block = m.group(0).strip()
        gm = GUID_TAG_RE.search(block)
        if not gm:
            continue
        guid = html.unescape(gm.group(1).strip())
        pm = PUBDATE_RE.search(block)
        try:
            when = parsedate_to_datetime(pm.group(1).strip()) if pm else dt.datetime(1970, 1, 1, tzinfo=IST)
        except (TypeError, ValueError):
            when = dt.datetime(1970, 1, 1, tzinfo=IST)
        items[guid] = (block, when)
    print(f"  {key}: loaded {len(items)} published items")
    return items


def render_item(key: str, art: dict) -> str:
    pub = art["date"] or dt.datetime.now(IST)
    title = art["title"] or _slug(art["link"]).replace("-", " ").title()
    pdf = item_pdf_url(key, art)
    body = (
        f'<p><a href="{escape(pdf)}">{escape(title)} (PDF)</a></p>\n'
        f'<p>Source: <a href="{escape(art["link"])}">{escape(art["link"])}</a></p>'
    )
    return (
        "    <item>\n"
        f"      <title>{escape(title)}</title>\n"
        f"      <link>{escape(art['link'])}</link>\n"
        f'      <guid isPermaLink="false">{escape(art["pdf"])}</guid>\n'
        f"      <pubDate>{format_datetime(pub)}</pubDate>\n"
        f'      <enclosure url="{escape(pdf)}" type="application/pdf" />\n'
        f"      <description>{escape(title)} — PDF.</description>\n"
        f"      <content:encoded><![CDATA[{body}]]></content:encoded>\n"
        "    </item>"
    )


def _item_date(val: tuple[str, dt.datetime] | str) -> dt.datetime:
    if isinstance(val, tuple):
        return val[1]
    m = PUBDATE_RE.search(val)
    if m:
        try:
            return parsedate_to_datetime(m.group(1).strip())
        except (TypeError, ValueError):
            pass
    return dt.datetime(1970, 1, 1, tzinfo=IST)


def _item_block(val: tuple[str, dt.datetime] | str) -> str:
    return val[0] if isinstance(val, tuple) else val


def build_feed(feed: dict, items: dict) -> str:
    ordered = sorted(items.values(), key=_item_date, reverse=True)[: feed["max_items"]]
    blocks = [_item_block(v) for v in ordered]
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
        f"    <link>{escape(BASE + feed['path'])}</link>\n"
        f"    <description>{escape(feed['desc'])}</description>\n"
        "    <language>en</language>\n"
        f"    <lastBuildDate>{now}</lastBuildDate>\n"
        f"{atom}"
        + "\n".join(blocks)
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


def write_manifest(key: str, entries: list[dict]) -> None:
    import json

    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    path = os.path.join(ARCHIVE_DIR, f"{key}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)
    print(f"  {key}: manifest {len(entries)} pdfs -> {path}")


# --- main ---------------------------------------------------------------------
def run_feed(session: requests.Session, feed: dict) -> int:
    print(f"[{feed['key']}]")
    merged = load_published(session, feed["key"])
    arts = collect(session, feed, set(merged))
    new, manifest = 0, []
    for art in arts:
        year = art["date"].year if art.get("date") else None
        if year is None or year < ARCHIVE_MIN_YEAR:
            continue
        if art["pdf"] not in merged:
            new += 1
        merged[art["pdf"]] = (render_item(feed["key"], art).strip(), art["date"])
        if ARCHIVE_MODE == "archive":
            name = archival_name(feed["key"], art)
            manifest.append({"name": name, "url": art["pdf"], "tag": archive_tag_for(art)})
    if ARCHIVE_MODE == "archive":
        write_manifest(feed["key"], manifest)
    xml = build_feed(feed, merged)
    kept = min(len(merged), feed["max_items"])
    write_feed(feed, xml, kept)
    print(f"  {feed['key']}: fetched {new} new, feed now {kept}")
    return kept


def main() -> int:
    session = make_session()
    print(f"ARCHIVE_MODE={ARCHIVE_MODE} min_year={ARCHIVE_MIN_YEAR}")
    counts = {feed["key"]: run_feed(session, feed) for feed in FEEDS}
    print("Done:", counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
