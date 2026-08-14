#!/usr/bin/env python3
"""Build full-text RSS feeds from The Economist (economist.com).

The Economist is doubly locked down: Cloudflare fronts the whole site with a
JavaScript challenge (plain requests / cloudscraper / spoofed bot UAs all get
403), and the articles themselves sit behind the Zephr paywall. Both are
defeated by a single trick lifted from the Bypass-Paywalls-Clean rule for
economist.com — a custom mobile User-Agent whose tail token ("Liskov") the
site treats as a whitelisted crawler. With that UA a normal GET returns 200
and the **full** article payload, Cloudflare and paywall included.

The site is a Next.js app: every page embeds a `<script id="__NEXT_DATA__">`
JSON blob under `props.pageProps.content`. Listing/topic pages expose
`content.articles` (headline, url, ISO datePublished, teaser image); article
pages expose `content.body`, a list of typed components (PARAGRAPH with ready
`textHtml`, IMAGE with url/caption/credit). Feeds are reconstructed from that:

  economist-indicators    /topics/economic-and-financial-indicators — the
                          weekly "Economic data, commodities and markets"
                          pages, which are essentially a set of chart images.
  economist-podcasts     /podcasts — every listed episode, with its direct MP3
                          URL as an RSS enclosure and the full transcript in the
                          item body. "Editor's Picks" narrated articles expose
                          their source-article link instead of a transcript, so
                          that full article body is used as the transcript.

Images: economist.com/content-assets images are Cloudflare-protected too, so a
plain RSS reader cannot hotlink them. In archive mode (ECON_ARCHIVE_MODE=archive
+ ECON_ARCHIVE_BASE_URL) every body image is rewritten to a durable copy on a
GitHub Release and recorded in a manifest under ECON_ARCHIVE_MANIFEST_DIR; the
actual mirroring is done by archive_pdfs.py pointed at that dir/release (it must
run with the Liskov UA to fetch the images). This is the "different folder"
for the indicator charts: a separate manifest dir + release tag from the PDFs.

Output: public/<key>/feed.xml + index.html, each merging its previously
published copy (ECON_PUBLISHED_BASE_URL) so history survives past the ~12-item
scan window. Every run also retries incomplete items among the five newest
entries so a transient scrape failure does not become permanent.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import sys
from email.utils import format_datetime, parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit
from xml.sax.saxutils import escape

import requests

BASE = "https://www.economist.com"
# The BPC economist.com rule: a mobile UA whose "Liskov" tail is whitelisted.
UA = os.environ.get(
    "ECON_UA",
    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.7922.76 Mobile Safari/537.36 Liskov",
)
# Use the repository-standard UA once a request leaves economist.com. In
# particular, the one-byte range probe against the MP3 host does not need the
# Economist-only Liskov token.
HTTP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.7922.76 Safari/537.36"
)
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

# --- global tunables ----------------------------------------------------------
TIMEOUT = int(os.environ.get("ECON_TIMEOUT", "60"))
RETRIES = int(os.environ.get("ECON_RETRIES", "2"))
OUT_DIR = os.environ.get("ECON_OUT_DIR", "public")
PUBLISHED_BASE_URL = os.environ.get("ECON_PUBLISHED_BASE_URL", "").strip().rstrip("/")
ARCHIVE_MODE = os.environ.get("ECON_ARCHIVE_MODE", "link").strip().lower()
ARCHIVE_BASE_URL = os.environ.get("ECON_ARCHIVE_BASE_URL", "").strip().rstrip("/")
ARCHIVE_DIR = os.environ.get("ECON_ARCHIVE_MANIFEST_DIR", "image_archive")

FEEDS = {
    "economist-indicators": {
        "title": "Economic & financial indicators - Economist",
        "desc": "Unofficial full-content feed of The Economist's weekly economic data, "
        "commodities and markets pages (chart images).",
        "page": f"{BASE}/topics/economic-and-financial-indicators",
        "html": f"{BASE}/topics/economic-and-financial-indicators",
        "max_items": 120,
        "archive_images": True,
    },
    "economist-finance-and-economics": {
        "title": "Finance & economics - Economist",
        "desc": "Unofficial full-text feed of The Economist's Finance & economics section.",
        "page": f"{BASE}/finance-and-economics",
        "html": f"{BASE}/finance-and-economics",
        "max_items": 120,
        "archive_images": True,
    },
    "economist-by-invitation": {
        "title": "By Invitation - Economist",
        "desc": "Unofficial full-text feed of The Economist's By Invitation guest commentary.",
        "page": f"{BASE}/topics/by-invitation",
        "html": f"{BASE}/topics/by-invitation",
        "max_items": 120,
        "archive_images": True,
    },
    "economist-business": {
        "title": "Business - Economist",
        "desc": "Unofficial full-text feed of The Economist's Business section.",
        "page": f"{BASE}/topics/business",
        "html": f"{BASE}/topics/business",
        "max_items": 120,
        "archive_images": True,
    },
    "economist-podcasts": {
        "title": "Podcasts - Economist",
        "desc": "Unofficial full-transcript podcast feed from The Economist, "
        "with direct MP3 enclosures.",
        "page": f"{BASE}/podcasts",
        "html": f"{BASE}/podcasts",
        "image": "https://assets.pippa.io/shows/62e28cad7ca7a10012e46a32/economist-show-cover.png",
        "max_items": 120,
        "archive_images": True,
        "kind": "podcast",
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


NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S
)


def next_data(page: str) -> dict | None:
    m = NEXT_DATA_RE.search(page or "")
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except ValueError:
        return None


def page_content(page: str) -> dict | None:
    data = next_data(page)
    if not data:
        return None
    c = ((data.get("props") or {}).get("pageProps") or {}).get("content")
    if isinstance(c, list):
        c = c[0] if c else None
    return c if isinstance(c, dict) else None


# --- xml safety ---------------------------------------------------------------
XML_ILLEGAL_RE = re.compile(
    "[^\x09\x0a\x0d\x20-퟿-�\U00010000-\U0010ffff]"
)


def xml_safe(text: str) -> str:
    return XML_ILLEGAL_RE.sub("", text)


def cdata(text: str) -> str:
    return xml_safe(text).replace("]]>", "]]]]><![CDATA[>")


TAG_RE = re.compile(r"<[^>]+>")


def as_text(val) -> str:
    """Flatten a value that may be a string, or a rich {text/textHtml} object,
    or a list of such, into plain text."""
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        return as_text(val.get("textHtml") or val.get("text") or val.get("content") or "")
    if isinstance(val, list):
        return " ".join(as_text(v) for v in val)
    return str(val)


def clean(text) -> str:
    return html.unescape(TAG_RE.sub(" ", as_text(text))).replace("\xa0", " ").strip()


# --- images -------------------------------------------------------------------
# Chart/photo URLs look like https://www.economist.com/content-assets/images/<name>,
# sometimes wrapped in a /cdn-cgi/image/<params>/ resizer prefix.
def canonical_image(url: str) -> str:
    if not url:
        return ""
    url = html.unescape(url.strip())
    i = url.find("/content-assets/")
    if i != -1:
        return BASE + url[i:]
    return url


def image_basename(url: str) -> str:
    name = canonical_image(url).rsplit("/", 1)[-1].split("?", 1)[0]
    return name


def archive_image(url: str, manifest: list[dict]) -> str:
    """Rewrite a content-asset image to its archived release URL and record it.

    No-op (returns the canonical source URL) unless archive mode is fully
    configured. Only content-assets images are archived; anything else is left
    as-is.
    """
    canon = canonical_image(url)
    if not canon:
        return ""
    if ARCHIVE_MODE != "archive" or not ARCHIVE_BASE_URL or "/content-assets/" not in canon:
        return canon
    name = image_basename(canon)
    if not name:
        return canon
    if not any(e["name"] == name for e in manifest):
        manifest.append({"name": name, "url": canon})
    return f"{ARCHIVE_BASE_URL}/{name}"


# --- body rendering -----------------------------------------------------------
def render_image_component(comp: dict, manifest: list[dict]) -> str:
    src = archive_image(comp.get("url", ""), manifest)
    if not src:
        return ""
    alt = escape(clean(comp.get("altText") or ""))
    cap = clean(comp.get("caption") or "")
    credit = clean(comp.get("credit") or comp.get("source") or "")
    figcap = " — ".join(p for p in (cap, credit) if p)
    out = f'<figure><img src="{escape(src)}" alt="{alt}" />'
    if figcap:
        out += f"<figcaption>{escape(figcap)}</figcaption>"
    return out + "</figure>"


def render_body(content: dict, manifest: list[dict]) -> tuple[str, str]:
    """Render content.body into (html, plain-text-summary).

    PARAGRAPH components carry ready-made inline HTML in `textHtml`; IMAGE
    components become <figure>s with archived srcs. Any other component that
    exposes text/textHtml is emitted as a paragraph; unknown ones are skipped.
    """
    body = content.get("body")
    if not isinstance(body, list):
        return "", ""
    parts: list[str] = []
    texts: list[str] = []
    for comp in body:
        if not isinstance(comp, dict):
            continue
        ctype = (comp.get("type") or "").upper()
        if ctype == "IMAGE" or (not ctype and comp.get("url") and comp.get("imageType")):
            fig = render_image_component(comp, manifest)
            if fig:
                parts.append(fig)
        elif ctype in ("UNORDERED_LIST", "ORDERED_LIST"):
            items = []
            for item in comp.get("items") or []:
                if not isinstance(item, dict):
                    continue
                inner = item.get("textHtml") or escape(as_text(item.get("text") or ""))
                if inner:
                    items.append(f"<li>{inner}</li>")
                    texts.append(clean(inner))
            if items:
                tag = "ol" if ctype == "ORDERED_LIST" else "ul"
                parts.append(f"<{tag}>" + "".join(items) + f"</{tag}>")
        elif comp.get("textHtml") or comp.get("text"):
            inner = comp.get("textHtml") or escape(comp.get("text", ""))
            if ctype in ("SUBHEADING", "CROSSHEAD", "HEADING"):
                parts.append(f"<h3>{inner}</h3>")
            else:
                parts.append(f"<p>{inner}</p>")
            texts.append(clean(comp.get("text") or comp.get("textHtml") or ""))
    summary = " ".join(t for t in texts if t).strip()
    if len(summary) > 500:
        summary = summary[:500].rsplit(" ", 1)[0] + "…"
    return "\n".join(parts), summary


# --- listing parsing ----------------------------------------------------------
def parse_listing(page: str) -> list[dict]:
    content = page_content(page)
    if not content:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for a in content.get("articles") or []:
        if not isinstance(a, dict):
            continue
        url = (a.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        link = url if url.startswith("http") else BASE + url
        out.append(
            {
                "link": link,
                "headline": clean(a.get("headline") or a.get("flyTitle") or url),
                "flyTitle": clean(a.get("flyTitle") or ""),
                "rubric": clean(a.get("rubric") or ""),
                "date": parse_iso(a.get("datePublished") or a.get("dateRevised")),
                "image": canonical_image(((a.get("image") or {}) or {}).get("url", "")),
                "duration": clean(a.get("duration") or ""),
            }
        )
    return out


def parse_iso(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    # a naive datetime would break sorting against the aware published dates
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


# --- feed I/O -----------------------------------------------------------------
ITEM_RE = re.compile(r"<item>.*?</item>", re.S)
FEEDLINK_RE = re.compile(r"<link>([^<]+)</link>")
PUBDATE_RE = re.compile(r"<pubDate>([^<]+)</pubDate>")
ITEM_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
CONTENT_RE = re.compile(
    r"<content:encoded><!\[CDATA\[(.*?)\]\]></content:encoded>", re.S
)
AUDIO_ENCLOSURE_RE = re.compile(r"<enclosure\b[^>]*\btype=\"audio/", re.I)
ITUNES_IMAGE_RE = re.compile(r"<itunes:image\b[^>]*\bhref=", re.I)
TRANSCRIPT_MARKER = "<h2>Transcript</h2>"


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


def _block_has_full_body(block: str) -> bool:
    """Return whether a stored RSS item contains a rendered article body."""
    m = CONTENT_RE.search(block)
    if not m:
        return False
    body = m.group(1).strip()
    return bool(body) and "Read on economist.com</a>" not in body


def _block_complete(key: str, block: str) -> bool:
    """Return whether an item has all source-specific payloads worth retrying."""
    if FEEDS[key].get("kind") == "podcast":
        return (
            bool(AUDIO_ENCLOSURE_RE.search(block))
            and TRANSCRIPT_MARKER in block
            and bool(ITUNES_IMAGE_RE.search(block))
        )
    return _block_has_full_body(block)


def _item_from_block(link: str, when: dt.datetime, block: str) -> dict:
    """Build minimal listing metadata for repairing an older RSS item."""
    m = ITEM_TITLE_RE.search(block)
    title = html.unescape(m.group(1)).strip() if m else link
    return {
        "link": link,
        "headline": title,
        "flyTitle": "",
        "rubric": "",
        "date": when,
        "image": "",
        "duration": "",
    }


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


def render_item(
    link: str,
    title: str,
    body_html: str,
    summary: str,
    when: dt.datetime,
    enclosure: tuple[str, int, str] | None = None,
    duration: str = "",
    image: str = "",
    author: str = "",
    category: str = "",
    itunes_title: str = "",
) -> str:
    if not summary:
        summary = clean(body_html)[:500]
    enclosure_xml = ""
    if enclosure:
        media_url, media_length, media_type = enclosure
        enclosure_xml = (
            f'      <enclosure url="{escape(media_url)}" length="{media_length}" '
            f'type="{escape(media_type)}" />\n'
        )
    duration_xml = (
        f"      <itunes:duration>{escape(duration)}</itunes:duration>\n"
        if duration
        else ""
    )
    image_xml = (
        f'      <itunes:image href="{escape(image)}" />\n'
        if image
        else ""
    )
    author_xml = (
        f"      <itunes:author>{escape(author)}</itunes:author>\n"
        if author
        else ""
    )
    category_xml = (
        f"      <category>{escape(category)}</category>\n"
        if category
        else ""
    )
    itunes_title_xml = (
        f"      <itunes:title>{escape(xml_safe(itunes_title))}</itunes:title>\n"
        if itunes_title
        else ""
    )
    explicit_xml = (
        "      <itunes:explicit>no</itunes:explicit>\n"
        if enclosure
        else ""
    )
    return (
        "    <item>\n"
        f"      <title>{escape(xml_safe(title))}</title>\n"
        f"      <link>{escape(link)}</link>\n"
        f"      <guid isPermaLink=\"true\">{escape(link)}</guid>\n"
        f"      <pubDate>{format_datetime(when)}</pubDate>\n"
        f"{enclosure_xml}"
        f"{duration_xml}"
        f"{image_xml}"
        f"{author_xml}"
        f"{category_xml}"
        f"{itunes_title_xml}"
        f"{explicit_xml}"
        f"      <description>{escape(xml_safe(summary))}</description>\n"
        f"      <content:encoded><![CDATA[{cdata(body_html)}]]></content:encoded>\n"
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
    is_podcast = feed.get("kind") == "podcast"
    itunes = (
        ' xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"'
        if is_podcast
        else ""
    )
    channel_image = feed.get("image") or ""
    image_xml = ""
    if channel_image:
        image_xml = (
            f"    <image>\n"
            f"      <url>{escape(channel_image)}</url>\n"
            f"      <title>{escape(feed['title'])}</title>\n"
            f"      <link>{escape(feed['html'])}</link>\n"
            f"    </image>\n"
        )
    itunes_channel = ""
    if is_podcast:
        cover_href = channel_image or "https://assets.pippa.io/shows/62e28cad7ca7a10012e46a32/economist-show-cover.png"
        itunes_channel = (
            "    <itunes:author>The Economist</itunes:author>\n"
            f"    <itunes:summary>{escape(feed['desc'])}</itunes:summary>\n"
            "    <itunes:type>episodic</itunes:type>\n"
            "    <itunes:owner>\n"
            "      <itunes:name>The Economist</itunes:name>\n"
            "    </itunes:owner>\n"
            f'    <itunes:image href="{escape(cover_href)}" />\n'
            '    <itunes:category text="News" />\n'
            "    <itunes:explicit>no</itunes:explicit>\n"
        )
        if not image_xml:
            image_xml = (
                f"    <image>\n"
                f"      <url>{escape(cover_href)}</url>\n"
                f"      <title>{escape(feed['title'])}</title>\n"
                f"      <link>{escape(feed['html'])}</link>\n"
                f"    </image>\n"
            )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" '
        f'xmlns:atom="http://www.w3.org/2005/Atom"{itunes}>\n'
        "  <channel>\n"
        f"    <title>{escape(feed['title'])}</title>\n"
        f"    <link>{escape(feed['html'])}</link>\n"
        f"    <description>{escape(feed['desc'])}</description>\n"
        "    <language>en</language>\n"
        f"    <lastBuildDate>{now}</lastBuildDate>\n"
        f"{image_xml}"
        f"{itunes_channel}"
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


def write_manifest(entries: list[dict]) -> None:
    if ARCHIVE_MODE != "archive":
        return
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    path = os.path.join(ARCHIVE_DIR, "economist-images.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=1)
    print(f"  image manifest: {len(entries)} images -> {path}")


# --- podcasts ----------------------------------------------------------------
HREF_RE = re.compile(r'href=["\']([^"\']+)', re.I)
DATED_ARTICLE_RE = re.compile(r"^/[^/]+/\d{4}/\d{2}/\d{2}/")
CONTENT_RANGE_RE = re.compile(r"/([0-9]+)$")


def podcast_source_article(content: dict) -> str:
    """Find the narrated article linked from an Editor's Picks show note."""
    preferred: list[str] = []
    fallback: list[str] = []
    for component in content.get("body") or []:
        if not isinstance(component, dict):
            continue
        for raw_url in HREF_RE.findall(component.get("textHtml") or ""):
            candidate = html.unescape(raw_url)
            parsed = urlsplit(candidate)
            if parsed.hostname not in ("economist.com", "www.economist.com"):
                continue
            if not DATED_ARTICLE_RE.match(parsed.path) or parsed.path.startswith("/podcasts/"):
                continue
            canonical = urlunsplit(("https", "www.economist.com", parsed.path, "", ""))
            if "audio.podcast" in parsed.query or "editorspicks" in parsed.query:
                preferred.append(canonical)
            else:
                fallback.append(canonical)
    candidates = preferred + fallback
    return candidates[0] if candidates else ""


def probe_audio(session: requests.Session, url: str) -> tuple[int, str]:
    """Read one MP3 byte to obtain the enclosure's total byte length."""
    last = None
    for _ in range(RETRIES + 1):
        response = None
        try:
            response = session.get(
                url,
                headers={
                    "User-Agent": HTTP_UA,
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
        print(f"  audio probe failed {urlsplit(url).netloc}: {last}", file=sys.stderr)
    return 0, "audio/mpeg"


def build_podcast_item(
    session: requests.Session,
    it: dict,
    content: dict,
    manifest: list[dict],
    now: dt.datetime,
) -> tuple[dt.datetime, str]:
    podcast = content.get("podcast") or {}
    audio = podcast.get("audio") or {}
    audio_url = (audio.get("url") or "").strip()
    duration = clean(audio.get("duration") or it.get("duration") or "")
    when = (
        parse_iso(podcast.get("publishedDate"))
        or parse_iso(content.get("datePublished"))
        or it.get("date")
        or now
    )

    parts: list[str] = []
    lead = content.get("leadComponent")
    if isinstance(lead, dict):
        image = render_image_component(lead, manifest)
        if image:
            parts.append(image)
    show = clean(((podcast.get("show") or {}).get("title")) or it.get("flyTitle") or "")
    if show:
        parts.append(f"<p><strong>{escape(show)}</strong></p>")
    rubric = clean(content.get("rubric") or it.get("rubric") or "")
    if rubric:
        parts.append(f"<p><em>{escape(rubric)}</em></p>")
    if audio_url:
        parts.append(
            f'<audio controls="controls" preload="none" src="{escape(audio_url)}"></audio>'
        )

    notes_html, _ = render_body(content, manifest)
    if notes_html:
        parts.extend(("<h2>Show notes</h2>", notes_html))

    transcript = podcast.get("transcript") or {}
    transcript_html, transcript_summary = render_body(
        {"body": transcript.get("body") or []}, manifest
    )
    source_url = ""
    if not transcript_html:
        source_url = podcast_source_article(content)
        source_page = fetch(session, source_url) if source_url else None
        source_content = page_content(source_page) if source_page else None
        if source_content:
            transcript_html, transcript_summary = render_body(source_content, manifest)
    if transcript_html:
        parts.append(TRANSCRIPT_MARKER)
        if source_url:
            parts.append(
                "<p><em>This episode narrates "
                f'<a href="{escape(source_url)}">the linked Economist article</a>; '
                "its complete text is reproduced below as the transcript.</em></p>"
            )
        parts.append(transcript_html)
    else:
        parts.append(
            f'<p><a href="{escape(it["link"])}">Transcript on economist.com</a></p>'
        )

    enclosure = None
    if audio_url:
        length, media_type = probe_audio(session, audio_url)
        enclosure = (audio_url, length, media_type)
    raw_title = clean(podcast.get("title") or content.get("headline") or it["headline"])
    summary = rubric or transcript_summary

    image_url = (podcast.get("imageUrl") or "").strip()
    if not image_url:
        show_img = ((podcast.get("show") or {}).get("imageUrl") or "").strip()
        if show_img:
            image_url = archive_image(show_img, manifest)
    if not image_url:
        lead_img = ((content.get("leadComponent") or {}).get("url") or it.get("image") or "").strip()
        if lead_img:
            image_url = archive_image(lead_img, manifest)
    if not image_url:
        image_url = FEEDS["economist-podcasts"].get("image", "")

    if show and not raw_title.startswith(f"[{show}]"):
        title = f"[{show}] {raw_title}"
    else:
        title = raw_title

    block = render_item(
        it["link"],
        title,
        "\n".join(parts),
        summary,
        when,
        enclosure=enclosure,
        duration=duration,
        image=image_url,
        author=show or "The Economist",
        category=show,
        itunes_title=raw_title,
    )
    return when, block.strip()


# --- per-feed builder ---------------------------------------------------------
def build_item(
    session: requests.Session,
    key: str,
    it: dict,
    manifest: list[dict],
    now: dt.datetime,
) -> tuple[dt.datetime, str]:
    """Fetch a detail page and render a full item; fall back gracefully."""
    detail = fetch(session, it["link"])
    content = page_content(detail) if detail else None
    if FEEDS[key].get("kind") == "podcast" and content:
        return build_podcast_item(session, it, content, manifest, now)
    body_html, summary = ("", "")
    if content:
        body_html, summary = render_body(content, manifest)
    when = it["date"]
    if content and content.get("datePublished"):
        when = parse_iso(content["datePublished"]) or when
    if when is None:
        when = now

    header = []
    if it["flyTitle"]:
        header.append(f"<p><strong>{escape(it['flyTitle'])}</strong></p>")
    if it["rubric"]:
        header.append(f"<p><em>{escape(it['rubric'])}</em></p>")
    if not body_html:
        # Interactive primers and any unparseable page: teaser image + link.
        if it["image"]:
            src = archive_image(it["image"], manifest)
            header.append(f'<figure><img src="{escape(src)}" alt="" /></figure>')
        header.append(f'<p><a href="{escape(it["link"])}">Read on economist.com</a></p>')
    body = "\n".join(header + ([body_html] if body_html else []))
    title = it["headline"]
    return when, render_item(it["link"], title, body, summary, when).strip()


def run_feed(session: requests.Session, key: str, manifest: list[dict], now: dt.datetime) -> int:
    print(f"[{key}]")
    merged = load_published(session, key)
    page = fetch(session, FEEDS[key]["page"])
    listing = parse_listing(page) if page else []
    print(f"  listing: {len(listing)} articles")
    listing_by_link = {it["link"]: it for it in listing}
    newest_published = max((when for when, _ in merged.values()), default=None)
    new = 0
    attempted: set[str] = set()
    for it in listing:
        if it["link"] in merged:
            continue
        # Topic payloads are curated rather than strictly chronological: a new
        # item can appear below an already-published one. Use the source date as
        # the boundary while independently skipping every known permalink.
        if newest_published and (
            it["date"] is None or it["date"] < newest_published
        ):
            continue
        when, block = build_item(session, key, it, manifest, now)
        merged[it["link"]] = (when, block)
        attempted.add(it["link"])
        new += 1

    latest = sorted(merged.items(), key=lambda pair: pair[1][0], reverse=True)[:5]
    if FEEDS[key].get("kind") == "podcast":
        missing = [entry for entry in merged.items() if not _block_complete(key, entry[1][1])]
    else:
        missing = [entry for entry in latest if not _block_complete(key, entry[1][1])]
    repaired = 0
    for link, (when, block) in missing:
        # New items were already fetched above. Retry an incomplete one on the
        # next run, when a just-published detail page has had time to populate.
        if link in attempted:
            continue
        it = listing_by_link.get(link) or _item_from_block(link, when, block)
        repaired_when, repaired_block = build_item(session, key, it, manifest, now)
        if _block_complete(key, repaired_block):
            merged[link] = (repaired_when, repaired_block)
            repaired += 1

    unresolved = sum(
        not _block_complete(key, merged[link][1]) for link, _ in latest
    )
    print(
        f"  body check: latest {len(latest)}, missing {len(missing)}, "
        f"repaired {repaired}, unresolved {unresolved}"
    )
    xml, kept = build_feed(key, merged)
    write_feed(key, xml, kept)
    print(f"  {key}: +{new} new, feed now {kept}")
    return kept


# --- main ---------------------------------------------------------------------
def main() -> int:
    session = make_session()
    now = dt.datetime.now(IST)
    manifest: list[dict] = []
    counts: dict[str, int] = {}
    for key in FEEDS:
        counts[key] = run_feed(session, key, manifest, now)
    write_manifest(manifest)
    print(f"ARCHIVE_MODE={ARCHIVE_MODE} images={len(manifest)}")
    print("Done:", counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
