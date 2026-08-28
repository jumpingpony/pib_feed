#!/usr/bin/env python3
"""Build consolidated English podcast and full-text RSS feed from News On AIR.

News On AIR — the news service of All India Radio / Prasar Bharati — runs on
WordPress but its news BULLETINS and NEWS MAGAZINES (Morning News / Midday News /
Evening News / Parikrama / Aaj Savere — AIR's signature content) have no working
feed.

This script reconstructs a clean, full-text, podcast-compliant RSS 2.0 feed
under public/newsonair/feed.xml with direct MP3 enclosures, iTunes podcast
metadata, show artwork, durations, and complete server-rendered transcripts.

Output: public/newsonair/feed.xml + public/newsonair/index.html.
"""
from __future__ import annotations

import datetime as dt
import html
import os
import re
import shutil
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.utils import format_datetime, parsedate_to_datetime
from xml.sax.saxutils import escape

import requests

BASE = "https://newsonair.gov.in"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.7922.76 Safari/537.36"
)
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

# --- global tunables ----------------------------------------------------------
WORKERS = int(os.environ.get("NOA_WORKERS", "3"))
TIMEOUT = int(os.environ.get("NOA_TIMEOUT", "20"))
RETRIES = int(os.environ.get("NOA_RETRIES", "1"))
DELAY = float(os.environ.get("NOA_DELAY", "0.3"))
RETRY_GAP = 1.0
OUT_DIR = os.environ.get("NOA_OUT_DIR", "public")
PUBLISHED_BASE_URL = os.environ.get("NOA_PUBLISHED_BASE_URL", "").strip().rstrip("/")

FEED_KEY = "newsonair"
FEED_TITLE = "News On AIR - All India Radio"
FEED_DESC = (
    "Unofficial consolidated podcast and full-transcript feed of All India Radio "
    "bulletins and news magazines (Morning News, Midday News, Evening News, "
    "Parikrama, Aaj Savere), with direct MP3 enclosures."
)
CHANNEL_IMAGE = "https://newsonair.gov.in/wp-content/uploads/2025/11/Akhashvani-1.png"
MAX_ITEMS = 300

CATEGORIES = {
    "parikrama": {
        "slug": "parikrama",
        "title": "Parikrama",
        "label": "Parikrama",
        "image": "https://newsonair.gov.in/wp-content/uploads/2025/11/parikrama.jpg",
        "duration": "00:30:00",
        "desc": "All India Radio daily news magazine — afternoon broadcast.",
        "keywords": ["parikrama"],
    },
    "aaj-savere": {
        "slug": "aaj-savere",
        "title": "Aaj Savere",
        "label": "Aaj Savere",
        "image": "https://newsonair.gov.in/wp-content/themes/newsonair/assets/custom-assets/images/radio.jpg",
        "duration": "00:30:00",
        "desc": "All India Radio daily morning news magazine.",
        "keywords": ["aaj savere", "samachar savera", "samacharsavera", "aaj-0730"],
    },
    "midday-news": {
        "slug": "midday-news",
        "title": "Midday News",
        "label": "Midday News",
        "image": "https://newsonair.gov.in/wp-content/uploads/2025/11/new-temp-midday-news.jpeg",
        "duration": "00:15:00",
        "desc": "All India Radio daily afternoon news bulletin.",
        "keywords": ["midday news", "midday-news", "midday"],
    },
    "morning-news": {
        "slug": "morning-news",
        "title": "Morning News",
        "label": "Morning News",
        "image": "https://newsonair.gov.in/wp-content/uploads/2025/11/Akhashvani-1.png",
        "duration": "00:15:00",
        "desc": "All India Radio daily morning news bulletin.",
        "keywords": ["morning news", "morning-news"],
    },
    "evening-news": {
        "slug": "evening-news",
        "title": "Evening News",
        "label": "Evening News",
        "image": "https://newsonair.gov.in/wp-content/uploads/2025/11/Akhashvani-1.png",
        "duration": "00:15:00",
        "desc": "All India Radio daily evening news bulletin.",
        "keywords": ["evening news", "evening-news", "news-at-nine", "news at nine"],
    },
}

LEGACY_FEED_KEYS = [
    "bulletin_morning",
    "bulletin_midday",
    "bulletin_evening",
    "parikrama",
]


# --- http ---------------------------------------------------------------------
def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "en"})
    return s


def fetch(session: requests.Session, url: str, **kw) -> str | None:
    last = None
    method = kw.pop("method", "get")
    for attempt in range(RETRIES + 1):
        if attempt > 0:
            import time
            time.sleep(RETRY_GAP * attempt)
        try:
            r = session.request(method, url, timeout=TIMEOUT, **kw)
            if r.status_code == 200 and r.text:
                r.encoding = r.apparent_encoding or "utf-8"
                return r.text
            if r.status_code in (404,):
                return None
            last = f"HTTP {r.status_code}"
        except requests.RequestException as e:  # pragma: no cover - network
            last = str(e)
    if last:
        print(f"  fetch failed {url}: {last}", file=sys.stderr)
    return None


# --- xml safety ---------------------------------------------------------------
XML_ILLEGAL_RE = re.compile(
    "[^\x09\x0a\x0d\x20-퟿-\U00010000-\U0010ffff]"
)


def xml_safe(text: str) -> str:
    return XML_ILLEGAL_RE.sub("", text)


def cdata(text: str) -> str:
    return xml_safe(text).replace("]]>", "]]]]><![CDATA[>")


TAG_RE = re.compile(r"<[^>]+>")


def strip_tags(s: str) -> str:
    return html.unescape(TAG_RE.sub(" ", s)).strip()


# --- audio extraction & probing -----------------------------------------------
SHARE_RE = re.compile(
    r'href=["\']([^"\']*(?:facebook\.com/sharer|whatsapp|twitter)[^"\']*)["\']',
    re.I,
)
QUOTE_DATE_RE = re.compile(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})")
CONTENT_RANGE_RE = re.compile(r"/([0-9]+)$")
TABLE_ROW_RE = re.compile(
    r"<tr\b[^>]*>.*?<td>(?P<title>[^<]+)</td>\s*<td>(?P<date>[^<]+)</td>\s*<td>(?P<time>[^<]+)</td>\s*<td>.*?<source\b[^>]*\bsrc=[\"'](?P<src>[^\"']+\.mp3)[\"']",
    re.S | re.I,
)


def load_audio_map(session: requests.Session) -> dict[tuple[str, dt.date], str]:
    """Index .mp3 files by (category_slug, date) from NOA audio broadcast & listen pages."""
    audio_map: dict[tuple[str, dt.date], str] = {}

    # 1. Listen-news category tables (Morning News, Midday News, Evening News, Aaj Savere)
    for slug in CATEGORIES:
        page = fetch(session, f"{BASE}/listen-news-category/{slug}/")
        if not page:
            continue
        for m in TABLE_ROW_RE.finditer(page):
            d_str = m.group("date").strip()
            src = m.group("src").strip()
            dm = QUOTE_DATE_RE.search(d_str)
            if dm and src:
                day, mon_name, year = dm.groups()
                try:
                    date_obj = dt.datetime.strptime(
                        f"{day} {mon_name[:3]} {year}", "%d %b %Y"
                    ).date()
                    audio_map[(slug, date_obj)] = src
                except ValueError:
                    pass

    # 2. Share links from news-magazine, daily-broadcast, national-bulletins (Parikrama, etc.)
    sources = ["/news-magazine/", "/daily-broadcast/", "/national-bulletins/"]
    for path in sources:
        page = fetch(session, f"{BASE}{path}")
        if not page:
            continue

        for m in SHARE_RE.finditer(page):
            raw_href = m.group(1)
            parsed = urllib.parse.urlparse(raw_href)
            qs = urllib.parse.parse_qs(parsed.query)
            quote = qs.get("quote", [""])[0] or qs.get("text", [""])[0]
            if not quote or "Audio:" not in quote:
                continue

            quote = html.unescape(quote)
            parts = [p.strip() for p in quote.split("|")]
            title_part = parts[0].lower()
            audio_url = None
            date_obj = None

            for p in parts[1:]:
                if p.startswith("Audio:"):
                    audio_url = p.replace("Audio:", "").strip().split()[0]
                elif p.startswith("Date:"):
                    dm = QUOTE_DATE_RE.search(p)
                    if dm:
                        day, mon_name, year = dm.groups()
                        try:
                            date_obj = dt.datetime.strptime(
                                f"{day} {mon_name} {year}", "%d %B %Y"
                            ).date()
                        except ValueError:
                            pass

            if not (audio_url and date_obj):
                continue

            for slug, cat in CATEGORIES.items():
                if any(kw in title_part for kw in cat["keywords"]) or any(
                    kw in audio_url.lower() for kw in cat["keywords"]
                ):
                    audio_map[(slug, date_obj)] = audio_url

    print(f"  audio map: loaded {len(audio_map)} audio broadcast links")
    return audio_map


def probe_audio_size(session: requests.Session, url: str) -> tuple[int, str]:
    """Read 1 byte via Range request to determine MP3 Content-Length without full download."""
    last = None
    for _ in range(RETRIES + 1):
        response = None
        try:
            response = session.get(
                url,
                headers={
                    "User-Agent": UA,
                    "Accept": "audio/mpeg,*/*;q=0.8",
                    "Range": "bytes=0-0",
                },
                timeout=TIMEOUT,
                allow_redirects=True,
                stream=True,
            )
            if response.status_code in (200, 206):
                match = CONTENT_RANGE_RE.search(response.headers.get("Content-Range", ""))
                length = (
                    int(match.group(1))
                    if match
                    else int(response.headers.get("Content-Length", "0"))
                )
                media_type = response.headers.get("Content-Type", "audio/mpeg").split(";", 1)[0]
                if not media_type.startswith("audio/"):
                    media_type = "audio/mpeg"
                return length, media_type
            last = f"HTTP {response.status_code}"
        except (requests.RequestException, ValueError) as exc:  # pragma: no cover - network
            last = str(exc)
        finally:
            if response is not None:
                response.close()
    if last:
        print(f"  audio probe failed {urllib.parse.urlsplit(url).netloc}: {last}", file=sys.stderr)
    return 0, "audio/mpeg"


# --- bulletins (category discovery + server-rendered detail) -----------------
ENTRY_RE = re.compile(r'<div[^>]*class="[^"]*\bentry-content\b[^"]*"[^>]*>', re.I)
BULLETIN_END_RE = re.compile(
    r'<!--\s*\.entry-content\s*-->'
    r'|class="[^"]*\b(?:mostReadBar|shareSec|share-|post-navigation|navigation|related|wp-block-comments)\b'
    r'|id="comments"|<footer',
    re.I,
)
DETAIL_DATE_RE = re.compile(
    r"([A-Z][a-z]+)\s+(\d{1,2}),\s+(\d{4})\s+(\d{1,2}):(\d{2})\s*([AP]M)"
)


def _parse_detail_date(page: str) -> dt.datetime | None:
    m = DETAIL_DATE_RE.search(page)
    if not m:
        return None
    mon, day, year, hh, mm, ap = m.groups()
    try:
        base = dt.datetime.strptime(f"{mon} {int(day):02d} {year}", "%B %d %Y")
        hour = int(hh) % 12 + (12 if ap.upper() == "PM" else 0)
        return base.replace(hour=hour, minute=int(mm), tzinfo=IST)
    except ValueError:
        return None


def scrape_bulletin(
    session: requests.Session, cat_info: dict, url: str
) -> dict | None:
    page = fetch(session, url)
    if not page:
        return None

    m = ENTRY_RE.search(page)
    if not m:
        return None

    start = m.end()
    end_m = BULLETIN_END_RE.search(page, start)
    inner = page[start : end_m.start() if end_m else start + 60000]
    inner = re.sub(r"<script\b.*?</script>", "", inner, flags=re.S | re.I)
    inner = re.sub(r"<style\b.*?</style>", "", inner, flags=re.S | re.I)

    paras = [
        html.unescape(TAG_RE.sub(" ", p)).strip()
        for p in re.findall(r"<p[^>]*>(.*?)</p>", inner, re.S)
    ]
    paras = [p for p in paras if p]
    if not paras:
        return None

    body_html = "".join(f"<p>{escape(p)}</p>\n" for p in paras).strip()
    date = _parse_detail_date(page)
    day = date.strftime("%d %b %Y") if date else ""
    label = cat_info["label"]
    title = f"{label} — {day}" if day else label

    return {
        "link": url,
        "title": title,
        "date": date,
        "body_html": body_html,
        "slug": cat_info["slug"],
        "category": label,
        "duration": cat_info["duration"],
        "image": cat_info["image"],
        "author": "All India Radio News",
        "itunes_title": title,
    }


def discover_bulletin_urls(
    session: requests.Session, slug: str, newest_id: int
) -> list[str]:
    """Return candidate bulletin detail URLs, newest first."""
    cat_url = f"{BASE}/bulletins-detail-category/{slug}/"
    cat_page = fetch(session, cat_url)
    latest_id = None
    if cat_page:
        m = re.search(rf"/bulletins-detail/{slug}-(\d+)/", cat_page)
        if m:
            latest_id = int(m.group(1))

    if latest_id is not None:
        start_id = (newest_id + 1) if (newest_id > 0) else max(1, latest_id - 20)
        return [
            f"{BASE}/bulletins-detail/{slug}-{b_id}/"
            for b_id in range(start_id, latest_id + 1)
        ]

    # Fallback forward-probe if category HTML did not yield an ID
    urls: list[str] = []
    start_id = (newest_id + 1) if (newest_id > 0) else 1
    for b_id in range(start_id, start_id + 15):
        u = f"{BASE}/bulletins-detail/{slug}-{b_id}/"
        if not fetch(session, u):
            break
        urls.append(u)
    return urls


def collect_bulletins(
    session: requests.Session, cat_info: dict, published_urls: set[str]
) -> list[dict]:
    slug = cat_info["slug"]
    pub_ids = [
        int(m.group(1))
        for url in published_urls
        if (m := re.search(rf"/bulletins-detail/{slug}-(\d+)/", url))
    ]
    newest_id = max(pub_ids, default=0)
    pending = [
        u for u in discover_bulletin_urls(session, slug, newest_id)
        if u not in published_urls
    ]
    print(
        f"  {slug}: newest published #{newest_id}, "
        f"{len(pending)} newer to fetch"
    )
    out: list[dict] = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {
            ex.submit(scrape_bulletin, session, cat_info, u): u for u in pending
        }
        for fut in as_completed(futs):
            art = fut.result()
            if art:
                out.append(art)
    return out


# --- feed I/O -----------------------------------------------------------------
ITEM_RE = re.compile(r"<item>.*?</item>", re.S)
PUBDATE_RE = re.compile(r"<pubDate>([^<]+)</pubDate>")
FEEDLINK_RE = re.compile(r"<link>([^<]+)</link>")


def _guid_url(block: str) -> str | None:
    g = re.search(r"<guid[^>]*>([^<]+)</guid>", block)
    return html.unescape(g.group(1)).strip() if g else None


def _block_link(block: str) -> str | None:
    m = FEEDLINK_RE.search(block)
    return html.unescape(m.group(1)).strip() if m else None


def _block_date(block: str) -> dt.datetime:
    match = PUBDATE_RE.search(block)
    if match:
        try:
            return parsedate_to_datetime(match.group(1).strip())
        except (TypeError, ValueError):
            pass
    return dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)


def parse_item_block(block: str) -> dict:
    """Parse an existing RSS <item> block into a structured dictionary."""
    link = _guid_url(block) or _block_link(block) or ""
    title_m = re.search(r"<title>(.*?)</title>", block, re.S)
    title = html.unescape(title_m.group(1)).strip() if title_m else ""
    pub_date = _block_date(block)

    desc_m = re.search(r"<description>(.*?)</description>", block, re.S)
    summary = html.unescape(desc_m.group(1)).strip() if desc_m else ""

    content_m = re.search(
        r"<content:encoded><!\[CDATA\[(.*?)\]\]></content:encoded>", block, re.S
    )
    body_html = content_m.group(1).strip() if content_m else ""
    if not body_html and not content_m:
        content_m = re.search(r"<content:encoded>(.*?)</content:encoded>", block, re.S)
        body_html = html.unescape(content_m.group(1)).strip() if content_m else ""

    enclosure = None
    enc_m = re.search(r"<enclosure\b([^>]+)>", block, re.I)
    if enc_m:
        attrs = enc_m.group(1)
        u = re.search(r'url=["\']([^"\']+)["\']', attrs)
        l = re.search(r'length=["\']([^"\']+)["\']', attrs)
        t = re.search(r'type=["\']([^"\']+)["\']', attrs)
        if u:
            url_val = u.group(1)
            len_val = int(l.group(1)) if l and l.group(1).isdigit() else 0
            type_val = t.group(1) if t else "audio/mpeg"
            enclosure = (url_val, len_val, type_val)

    slug = ""
    for s in CATEGORIES:
        if f"/bulletins-detail/{s}-" in link:
            slug = s
            break
    if not slug:
        for s, cat in CATEGORIES.items():
            if cat["label"].lower() in title.lower():
                slug = s
                break

    cat_info = CATEGORIES.get(slug, {})
    category = cat_info.get("label", "News Bulletin")
    duration = cat_info.get("duration", "00:15:00")
    image = cat_info.get("image", CHANNEL_IMAGE)
    author = "All India Radio News"

    return {
        "link": link,
        "title": title,
        "date": pub_date,
        "body_html": body_html,
        "summary": summary,
        "enclosure": enclosure,
        "duration": duration,
        "image": image,
        "author": author,
        "category": category,
        "itunes_title": title,
        "slug": slug,
    }


def load_all_published(session: requests.Session) -> dict[str, dict]:
    """Load items from published consolidated feed and legacy feeds."""
    if not PUBLISHED_BASE_URL:
        return {}
    items: dict[str, dict] = {}

    primary_body = fetch(session, f"{PUBLISHED_BASE_URL}/{FEED_KEY}/feed.xml")
    if primary_body:
        for m in ITEM_RE.finditer(primary_body):
            block = m.group(0).strip()
            item = parse_item_block(block)
            if item["link"]:
                items[item["link"]] = item
        print(f"  {FEED_KEY}: loaded {len(items)} published items from consolidated feed")

    legacy_count = 0
    for legacy_key in LEGACY_FEED_KEYS:
        body = fetch(session, f"{PUBLISHED_BASE_URL}/{legacy_key}/feed.xml")
        if not body:
            continue
        for m in ITEM_RE.finditer(body):
            block = m.group(0).strip()
            item = parse_item_block(block)
            if item["link"] and item["link"] not in items:
                items[item["link"]] = item
                legacy_count += 1

    if legacy_count:
        print(f"  migrated {legacy_count} items from legacy feeds into consolidated feed")

    return items


def attach_audio_enclosures(
    session: requests.Session,
    items: list[dict],
    audio_map: dict[tuple[str, dt.date], str],
) -> None:
    """Match audio URLs to items and probe byte lengths concurrently."""
    to_probe: list[tuple[dict, str]] = []
    for it in items:
        if it.get("enclosure"):
            continue
        slug = it.get("slug")
        date_val = it.get("date")
        if not (slug and date_val):
            continue
        audio_url = audio_map.get((slug, date_val.date()))
        if not audio_url:
            continue
        to_probe.append((it, audio_url))

    if not to_probe:
        return

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {
            ex.submit(probe_audio_size, session, url): (it, url)
            for it, url in to_probe
        }
        for fut in as_completed(futs):
            it, url = futs[fut]
            length, media_type = fut.result()
            it["enclosure"] = (url, length, media_type)


def render_item(a: dict) -> str:
    pub = a.get("date") or dt.datetime.now(IST)
    body = a.get("body_html") or ""
    summary = a.get("summary") or strip_tags(body)
    if len(summary) > 500:
        summary = summary[:500].rsplit(" ", 1)[0] + "…"

    title = xml_safe(a.get("title", ""))
    link = a.get("link", "")
    enclosure_xml = ""
    enclosure = a.get("enclosure")
    if enclosure:
        media_url, media_length, media_type = enclosure
        enclosure_xml = (
            f'      <enclosure url="{escape(media_url)}" length="{media_length}" '
            f'type="{escape(media_type)}" />\n'
        )

    duration = a.get("duration", "")
    duration_xml = (
        f"      <itunes:duration>{escape(duration)}</itunes:duration>\n"
        if duration
        else ""
    )
    image = a.get("image", "")
    image_xml = (
        f'      <itunes:image href="{escape(image)}" />\n'
        if image
        else ""
    )
    author = a.get("author", "All India Radio News")
    author_xml = (
        f"      <itunes:author>{escape(author)}</itunes:author>\n"
        if author
        else ""
    )
    category = a.get("category", "")
    category_xml = (
        f"      <category>{escape(category)}</category>\n"
        if category
        else ""
    )
    itunes_title = a.get("itunes_title") or title
    itunes_title_xml = (
        f"      <itunes:title>{escape(xml_safe(itunes_title))}</itunes:title>\n"
        if itunes_title
        else ""
    )
    explicit_xml = "      <itunes:explicit>no</itunes:explicit>\n"

    return (
        "    <item>\n"
        f"      <title>{escape(title)}</title>\n"
        f"      <link>{escape(link)}</link>\n"
        f"      <guid isPermaLink=\"true\">{escape(link)}</guid>\n"
        f"      <pubDate>{format_datetime(pub)}</pubDate>\n"
        f"{enclosure_xml}"
        f"{duration_xml}"
        f"{image_xml}"
        f"{author_xml}"
        f"{category_xml}"
        f"{itunes_title_xml}"
        f"{explicit_xml}"
        f"      <description>{escape(xml_safe(summary))}</description>\n"
        f"      <content:encoded><![CDATA[{cdata(body)}]]></content:encoded>\n"
        "    </item>"
    )


def build_feed(items: list[dict]) -> str:
    """Render consolidated RSS 2.0 podcast XML feed."""
    sorted_items = sorted(
        items,
        key=lambda it: it.get("date") or dt.datetime(1970, 1, 1, tzinfo=IST),
        reverse=True,
    )[:MAX_ITEMS]

    blocks = [render_item(it) for it in sorted_items]
    now = format_datetime(dt.datetime.now(IST))
    self_url = (
        f"{PUBLISHED_BASE_URL}/{FEED_KEY}/feed.xml" if PUBLISHED_BASE_URL else ""
    )
    atom = (
        f'    <atom:link href="{escape(self_url)}" rel="self" type="application/rss+xml" />\n'
        if self_url
        else ""
    )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" '
        'xmlns:atom="http://www.w3.org/2005/Atom" '
        'xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">\n'
        "  <channel>\n"
        f"    <title>{escape(FEED_TITLE)}</title>\n"
        f"    <link>{escape(BASE)}</link>\n"
        f"    <description>{escape(FEED_DESC)}</description>\n"
        "    <language>en</language>\n"
        f"    <lastBuildDate>{now}</lastBuildDate>\n"
        "    <image>\n"
        f"      <url>{escape(CHANNEL_IMAGE)}</url>\n"
        f"      <title>{escape(FEED_TITLE)}</title>\n"
        f"      <link>{escape(BASE)}</link>\n"
        "    </image>\n"
        "    <itunes:author>All India Radio / Prasar Bharati</itunes:author>\n"
        f"    <itunes:summary>{escape(FEED_DESC)}</itunes:summary>\n"
        "    <itunes:type>episodic</itunes:type>\n"
        "    <itunes:owner>\n"
        "      <itunes:name>All India Radio News</itunes:name>\n"
        "    </itunes:owner>\n"
        f'    <itunes:image href="{escape(CHANNEL_IMAGE)}" />\n'
        '    <itunes:category text="News">\n'
        '      <itunes:category text="Daily News" />\n'
        "    </itunes:category>\n"
        "    <itunes:explicit>no</itunes:explicit>\n"
        f"{atom}"
        + "\n".join(blocks)
        + "\n  </channel>\n</rss>\n"
    )


def scrub_legacy_dirs(out_dir: str) -> None:
    """Remove legacy published directories to prevent stale Pages artifacts."""
    for legacy_key in LEGACY_FEED_KEYS:
        d = os.path.join(out_dir, legacy_key)
        if os.path.exists(d):
            shutil.rmtree(d, ignore_errors=True)
            print(f"  scrubbed legacy directory {d}")


def write_feed(xml: str, count: int) -> None:
    d = os.path.join(OUT_DIR, FEED_KEY)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "feed.xml"), "w", encoding="utf-8") as f:
        f.write(xml)
    with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as f:
        f.write(
            "<!doctype html><meta charset='utf-8'>"
            f"<title>{escape(FEED_TITLE)} (unofficial podcast RSS)</title>"
            f"<h1>{escape(FEED_TITLE)} (unofficial)</h1>"
            f"<p>{escape(FEED_DESC)}</p>"
            "<p>Subscribe: <a href='feed.xml'>feed.xml</a></p>"
            f"<p>{count} items. Rebuilt automatically.</p>"
        )


def write_landing() -> None:
    # Blank white page matching repository standard
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write("<!doctype html><meta charset='utf-8'><title></title>")


# --- main ---------------------------------------------------------------------
def main() -> int:
    session = make_session()
    print("[newsonair]")

    existing = load_all_published(session)
    audio_map = load_audio_map(session)

    new_items: list[dict] = []
    published_urls = set(existing.keys())
    for slug, cat_info in CATEGORIES.items():
        arts = collect_bulletins(session, cat_info, published_urls)
        new_items.extend(arts)

    for art in new_items:
        existing[art["link"]] = art

    all_items = list(existing.values())
    attach_audio_enclosures(session, all_items, audio_map)

    xml = build_feed(all_items)
    kept = min(len(all_items), MAX_ITEMS)
    write_feed(xml, kept)
    scrub_legacy_dirs(OUT_DIR)
    write_landing()

    print(f"  newsonair: fetched {len(new_items)} new, feed total {kept}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
