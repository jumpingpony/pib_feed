#!/usr/bin/env python3
"""Build a full-text RSS 2.0 feed of FT Opinion (ft.com/opinion).

Discovery comes from FT's own RSS feeds (opinion, lex, big-read, ft-view,
banx), which are served from Cloudflare's edge and stay reachable from
datacenter IPs even when the article HTML does not, plus the paginated
/opinion listing as an opportunistic top-up for premium features the RSS
windows drop; a challenged listing page falls back to RSS-only discovery.
Full stories come from the FT app's content API, an unchallenged JSON route
that needs no auth, referer or TLS impersonation and serves fresh articles
from the origin too:

    GET https://app-api.ft.com/__content/v6/article/<uuid>?useVanities=false

The www.ft.com article HTML stays as a fallback: Chrome TLS impersonation
plus a Google referer (Bypass Paywalls Clean's ft.com rule) unlocks it
locally, though the same shape is a Cloudflare 403 lottery from runners.

Payload mapping, verified across every entry of all three feeds:

    title        JSON `title` (RSS titles can be stale); series prefix from
                 the topper display concept (Lex / The FT View) or the
                 editorial desk (/FT/Feats/The Big Read)
    standfirst   JSON `standfirst`, used as the description and as the
                 opening italic paragraph
    byline       `byline.tree` author nodes, joined with " and "
    body         `body.structured.tree` blocks + `references` figures;
                 emphasis/strong/links/lists/headings/blockquotes kept,
                 newsletter/podcast promo boxes and embeds dropped
    exclusions   listing tag paths and heading brand prefixes stop known
                 lifestyle pieces before the fetch; the FT ontology
                 annotations (Life & Arts / House & Home / Personal Finance /
                 Restaurants / Wine) catch the rest. Banx cartoons are kept
                 (their body is the lead figure)

Output: public/ft-opinion/feed.xml + index.html, merged with the published
copy.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.utils import format_datetime, parsedate_to_datetime
from xml.sax.saxutils import escape

try:
    from curl_cffi import requests as creq
except ImportError:  # pragma: no cover - dependency guard
    raise SystemExit("curl_cffi is required: pip install -r requirements.txt")

BASE = "https://www.ft.com"
CONTENT = BASE + "/content/{uuid}"
OPINION = BASE + "/opinion"
API = "https://app-api.ft.com/__content/v6/article/{uuid}?useVanities=false"
# RSS paths are never Cloudflare-challenged; /rss/big-read and /rss/ft-view
# carry the premium series the opinion feed drops out of its window, and both
# Banx routes serve the same items (/rss/banx is the readable alias). The
# letters, Alphaville and newsletter feeds are commentary the /opinion
# listing only shows intermittently.
RSS_FEEDS = (
    BASE + "/rss/opinion",
    BASE + "/rss/lex",
    BASE + "/rss/big-read",
    BASE + "/rss/ft-view",
    BASE + "/rss/letters",
    BASE + "/rss/alphaville",
    BASE + "/rss/free-lunch",
    BASE + "/rss/inside-politics",
    BASE + "/rss/unhedged",
    BASE + "/rss/trade-secrets",
    BASE + "/rss/tech-tonic",
    BASE + "/rss/moral-money",
    BASE + "/rss/banx",
)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.7922.76 Safari/537.36"
)

# --- global tunables ----------------------------------------------------------
WORKERS = int(os.environ.get("FT_WORKERS", "1"))
TIMEOUT = int(os.environ.get("FT_TIMEOUT", "30"))
RETRIES = int(os.environ.get("FT_RETRIES", "3"))
DELAY = float(os.environ.get("FT_DELAY", "1.0"))
MAX_ITEMS = int(os.environ.get("FT_MAX_ITEMS", "100"))
MAX_PAGES = int(os.environ.get("FT_MAX_PAGES", "5"))
REPAIR_NEWEST = int(os.environ.get("FT_REPAIR_NEWEST", "0"))
OUT_DIR = os.environ.get("FT_OUT_DIR", "public")
PUBLISHED_BASE_URL = os.environ.get("FT_PUBLISHED_BASE_URL", "").strip().rstrip("/")
FEED_KEY = "ft-opinion"
CACHE_VERSION = 2

FEED_TITLE = "Opinion - FT"
FEED_DESC = (
    "Unofficial full-text feed of FT Opinion (Life & Arts excluded), with "
    "Lex., The Big Read. and The FT View. series prefixes preserved."
)

# Series headings live on the topper (Lex, The FT View) or the desk
# (The Big Read carries a topic label instead, so the desk is the marker).
SERIES_LABELS = {"Lex": "Lex.", "The FT View": "The FT View."}
SERIES_DESKS = {"/FT/Lex": "Lex.", "/FT/Feats/The Big Read": "The Big Read."}

# Exact heading brands and ontology labels for content we do not want.
EX_PREFIXES = ("FT Magazine.", "Obituary.", "Lunch with the FT.", "House & Home.")
EX_LABELS = {"Life & Arts", "House & Home", "Personal Finance", "Restaurants", "Wine"}

# Exact topic paths FT tags lifestyle/culture pieces with on the listing.
# Broad paths such as /travel-leisure or /luxury-goods are absent on purpose:
# Lex columns carry those.
EX_TAGS = {
    "/life-arts",
    "/restaurants",
    "/wine",
    "/personal-finance",
    "/television",
    "/music",
    "/film",
    "/sport",
    "/style",
}

# Promo boxes and embeds present in the JSON but absent from the old HTML
# feed: the HTML sanitizer stripped matching <aside>/<iframe> blocks.
# Flourish charts are not dropped; they get a clickable indicator instead.
DROP_BLOCKS = {"card", "info-box", "info-pair", "recommended"}

# Block-level node kinds; used to tell table cells with block content apart.
BLOCK_KINDS = {
    "paragraph", "main-image", "image-set", "image-pair", "heading",
    "blockquote", "list", "table", "thematic-break", "tweet",
    "custom-code-component", "flourish",
}


# --- http ---------------------------------------------------------------------
def make_session() -> creq.Session:
    s = creq.Session(impersonate="chrome")
    s.headers.update(
        {
            "User-Agent": UA,
            "Accept-Language": "en",
            # Bypass Paywalls Clean's ft.com rule; used by the HTML fallback.
            "Referer": "https://www.google.com/",
        }
    )
    return s


def fetch(session: creq.Session, url: str, attempts: int | None = None) -> str | None:
    """GET with retries; attempts=1 for opportunistic requests worth one try."""
    tries = RETRIES + 1 if attempts is None else attempts
    last = None
    for attempt in range(tries):
        if attempt:
            time.sleep(2.0 * attempt)
        try:
            r = session.get(url, timeout=TIMEOUT)
            if r.status_code == 200 and r.text:
                return r.text
            if r.status_code == 404:
                return None
            last = f"HTTP {r.status_code}"
        except Exception as e:  # pragma: no cover - network
            last = f"{type(e).__name__}: {e}"
    if last:
        print(f"  fetch failed {url}: {last}", file=sys.stderr)
    return None


def fetch_api(session: creq.Session, uuid: str) -> dict | None:
    """Article JSON from the app content API; None on 404 or repeated errors."""
    last = None
    for attempt in range(RETRIES + 1):
        if attempt:
            time.sleep(2.0 * attempt)
        try:
            r = session.get(API.format(uuid=uuid), timeout=TIMEOUT)
            if r.status_code == 200 and r.text:
                content = (r.json().get("data") or {}).get("content")
                if content:
                    return content
                last = "no content"
            elif r.status_code == 404:
                return None
            else:
                last = f"HTTP {r.status_code}"
        except Exception as e:  # pragma: no cover - network
            last = f"{type(e).__name__}: {e}"
    if last:
        print(f"  api failed {uuid}: {last}", file=sys.stderr)
    return None


# --- rss discovery ------------------------------------------------------------
RSS_ITEM_RE = re.compile(r"<item>(.*?)</item>", re.S)
RSS_TITLE_RE = re.compile(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", re.S)
RSS_LINK_RE = re.compile(r"<link>(.*?)</link>", re.S)
RSS_DATE_RE = re.compile(r"<pubDate>(.*?)</pubDate>", re.S)
UUID_RE = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")


def parse_rss(body: str, banx: bool) -> list[dict]:
    rows: list[dict] = []
    for block in RSS_ITEM_RE.findall(body):
        link_m = RSS_LINK_RE.search(block)
        id_m = UUID_RE.search(link_m.group(1)) if link_m else None
        if not id_m:
            continue
        title_m = RSS_TITLE_RE.search(block)
        date_m = RSS_DATE_RE.search(block)
        rows.append(
            {
                "uuid": id_m.group(1),
                "rss_title": html.unescape(title_m.group(1).strip()) if title_m else "",
                "date": date_m.group(1).strip() if date_m else "",
                "banx": banx,
            }
        )
    return rows


# --- opinion listing (opportunistic) ------------------------------------------
# The listing carries the full surface, including premium series the RSS
# windows drop. It is Cloudflare-challenged from datacenter IPs, so every
# page gets one attempt and a failure falls back to RSS-only discovery.
TEASER_SPLIT_RE = re.compile(r'(?=<div class="o-teaser[ "])')
TEASER_HEAD_RE = re.compile(r'js-teaser-heading-link"[^>]*>(.*?)</a>', re.S)
TEASER_TAG_RE = re.compile(r'o-teaser__tag[^>]*href="([^"]+)"')
TEASER_ID_RE = re.compile(r'data-id="([^"]+)"')


def parse_listing(page: str) -> list[dict]:
    """Article teasers on an /opinion listing page: uuid, heading, tag."""
    rows: list[dict] = []
    for block in TEASER_SPLIT_RE.split(page):
        if not block.startswith('<div class="o-teaser') or "o-teaser--article" not in block:
            continue
        id_m = TEASER_ID_RE.search(block)
        head_m = TEASER_HEAD_RE.search(block)
        if not (id_m and head_m):
            continue
        uid_m = UUID_RE.search(id_m.group(1))
        if not uid_m:
            continue
        tag_m = TEASER_TAG_RE.search(block)
        rows.append(
            {
                "uuid": uid_m.group(1),
                "listing_title": strip_tags(head_m.group(1)),
                "tag": tag_m.group(1) if tag_m else "",
            }
        )
    return rows


def excluded_by_listing(row: dict) -> bool:
    """Stage-1 exclusion: heading brand or lifestyle/culture tag path."""
    title = row.get("listing_title") or row.get("rss_title") or ""
    tag = row.get("tag") or ""
    return title.startswith(EX_PREFIXES) or tag in EX_TAGS or tag.startswith("/content/")


def discover_listing(session: creq.Session) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    stale = 0
    for page_no in range(1, MAX_PAGES + 1):
        url = OPINION + (f"?page={page_no}" if page_no > 1 else "")
        body = fetch(session, url, attempts=1)
        if not body or "o-teaser--article" not in body:
            print(f"  listing page {page_no}: unreachable")
            break
        new = 0
        for row in parse_listing(body):
            if row["uuid"] in rows:
                continue
            rows[row["uuid"]] = row
            new += 1
        print(f"  listing page {page_no}: {new} new entries")
        stale = stale + 1 if new == 0 else 0
        if stale >= 2:
            break
        time.sleep(DELAY)
    return rows


def discover(session: creq.Session) -> dict[str, dict]:
    """All current entries keyed by UUID; RSS first, listing tops up."""
    rows: dict[str, dict] = {}
    for url in RSS_FEEDS:
        body = fetch(session, url)
        if not body:
            continue
        new = 0
        for row in parse_rss(body, banx=url.endswith("/rss/banx")):
            if row["uuid"] in rows:
                continue
            rows[row["uuid"]] = row
            new += 1
        print(f"  {url.rsplit('/', 1)[-1]}: {new} new entries")
        time.sleep(DELAY)
    for uid, row in discover_listing(session).items():
        if uid in rows:
            rows[uid]["tag"] = row["tag"]
            rows[uid]["listing_title"] = row["listing_title"]
        else:
            row["rss_title"] = row["listing_title"]
            row["banx"] = False
            rows[uid] = row
    return rows


# --- json article rendering ---------------------------------------------------
def esc(s: str) -> str:
    return escape(html.unescape(s or ""))


def inline_html(nodes) -> str:
    out = []
    for node in nodes or []:
        t = node.get("type")
        if t == "text":
            out.append(esc(node.get("value", "")))
        elif t == "link":
            out.append(
                f'<a href="{esc(node.get("url", ""))}">{inline_html(node.get("children"))}</a>'
            )
        elif t == "emphasis":
            out.append(f"<em>{inline_html(node.get('children'))}</em>")
        elif t == "strong":
            out.append(f"<strong>{inline_html(node.get('children'))}</strong>")
        elif t == "break":
            out.append("<br />")
        elif t == "strikethrough":
            out.append(f"<s>{inline_html(node.get('children'))}</s>")
        elif node.get("children"):
            out.append(inline_html(node.get("children")))
        else:
            out.append(esc(node.get("value", "")))
    return "".join(out)


def figure_html(ref) -> str:
    """Responsive figure from a main-image/image-set reference."""
    picture = (ref or {}).get("picture") or {}
    image = picture.get("fallbackImage") or ((picture.get("images") or [{}])[0])
    url = image.get("url", "")
    if not url:
        return ""
    out = (
        f'<figure><img src="{esc(url)}" alt="{esc(picture.get("alt", ""))}" '
        'style="max-width:100%;height:auto;" />'
    )
    caption = " ".join(x for x in (picture.get("caption"), picture.get("credit")) if x)
    if caption:
        out += f"<figcaption>{esc(caption)}</figcaption>"
    return out + "</figure>"


def table_cell(cell, refs) -> str:
    kids = cell.get("children") or []
    if any(k.get("type") in BLOCK_KINDS for k in kids):
        return blocks_html(kids, refs)
    return inline_html(kids)


def table_html(block, refs) -> str:
    caption = ""
    body = {}
    for child in block.get("children") or []:
        if child.get("type") == "table-caption":
            caption = f"<caption>{inline_html(child.get('children'))}</caption>"
        elif child.get("type") == "table-body":
            body = child
    rows = []
    for row in body.get("children") or []:
        cells = []
        for cell in row.get("children") or []:
            tag = "th" if cell.get("heading") else "td"
            cells.append(f"<{tag}>{table_cell(cell, refs)}</{tag}>")
        rows.append(f"<tr>{''.join(cells)}</tr>")
    return f"<table>{caption}<tbody>{''.join(rows)}</tbody></table>"


def chart_link_html(block) -> str:
    """Clickable indicator for a dynamic chart too complex to render inline."""
    chart_id = block.get("id") or ""
    if not chart_id:
        return ""
    href = f"https://public.flourish.studio/visualisation/{chart_id}/"
    return (
        f'<p class="chart-link"><a href="{esc(href)}">'
        "Interactive chart — view</a></p>"
    )


def custom_code_html(ref) -> str:
    """Interactive chart fallback: keep its title, caption and credit."""
    attrs = (ref or {}).get("attributes") or {}
    parts = []
    if attrs.get("title"):
        parts.append(f"<strong>{esc(attrs['title'])}</strong>")
    tail = " — ".join(x for x in (attrs.get("caption"), attrs.get("credit")) if x)
    if tail:
        parts.append(f"<em>{esc(tail)}</em>")
    return f"<p>{'<br />'.join(parts)}</p>" if parts else ""


def blocks_html(nodes, refs) -> str:
    out = []
    for block in nodes or []:
        t = block.get("type")
        if t == "paragraph":
            out.append(f"<p>{inline_html(block.get('children'))}</p>")
        elif t in ("main-image", "image-set"):
            idx = (block.get("data") or {}).get("referenceIndex")
            if isinstance(idx, int) and 0 <= idx < len(refs):
                out.append(figure_html(refs[idx]))
        elif t == "heading":
            out.append(f"<h2>{inline_html(block.get('children'))}</h2>")
        elif t == "blockquote":
            out.append(f"<blockquote>{blocks_html(block.get('children'), refs)}</blockquote>")
        elif t == "list":
            items = []
            for li in block.get("children") or []:
                inner = re.sub(r"^<p>|</p>$", "", blocks_html(li.get("children"), refs))
                items.append(f"<li>{inner}</li>")
            out.append(f"<ul>{''.join(items)}</ul>")
        elif t == "thematic-break":
            out.append("<hr />")
        elif t == "table":
            out.append(table_html(block, refs))
        elif t == "image-pair":
            for child in block.get("children") or []:
                idx = (child.get("data") or {}).get("referenceIndex")
                if isinstance(idx, int) and 0 <= idx < len(refs):
                    out.append(figure_html(refs[idx]))
        elif t == "tweet":
            idx = (block.get("data") or {}).get("referenceIndex")
            if isinstance(idx, int) and 0 <= idx < len(refs):
                snippet = refs[idx].get("html") or ""
                if snippet:
                    out.append(sanitize_body(snippet))
        elif t == "custom-code-component":
            idx = (block.get("data") or {}).get("referenceIndex")
            ref = refs[idx] if isinstance(idx, int) and 0 <= idx < len(refs) else {}
            out.append(custom_code_html(ref))
        elif t == "flourish":
            out.append(chart_link_html(block))
        elif t in DROP_BLOCKS or t == "break":
            continue
        elif block.get("children"):
            out.append(blocks_html(block.get("children"), refs))
    return "".join(out)


def byline_names(content: dict) -> str:
    names = []

    def walk(node):
        if not isinstance(node, dict):
            return
        if node.get("type") == "author":
            names.append("".join(c.get("value", "") for c in node.get("children", [])))
            return
        for child in node.get("children") or []:
            walk(child)

    walk((content.get("byline") or {}).get("tree") or {})
    return " and ".join(n for n in names if n)


def render_article(content: dict) -> dict:
    """Full-text item fields from one API payload."""
    struct = (content.get("body") or {}).get("structured") or {}
    refs = struct.get("references") or []
    title = content.get("title") or ""
    label = ((content.get("topper") or {}).get("displayConcept") or {}).get("prefLabel")
    prefix = SERIES_LABELS.get(label) or SERIES_DESKS.get(content.get("editorialDesk") or "")
    if prefix:
        title = f"{prefix} {title}"
    date = None
    raw = content.get("publishedDate") or content.get("firstPublishedDate") or ""
    if raw:
        try:
            date = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            date = None
    standfirst = content.get("standfirst") or ""
    byline = byline_names(content)
    head = ""
    if standfirst:
        head += f'<p class="standfirst"><em>{esc(standfirst)}</em></p>'
    if byline:
        head += f'<p class="byline">{esc(byline)}</p>'
    return {
        "title": title,
        "date": date,
        "standfirst": standfirst,
        "byline": byline,
        "labels": {a.get("prefLabel") for a in (content.get("annotations") or [])},
        "body_html": head + blocks_html((struct.get("tree") or {}).get("children"), refs),
    }


# --- html fallback ------------------------------------------------------------
TAG_RE = re.compile(r"<[^>]+>")
LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
H1_RE = re.compile(r'<h1[^>]*class="[^>]*o-topper__headline[^>]*>(.*?)</h1>', re.S)
BODY_RE = re.compile(r'<article[^>]*id="article-body"[^>]*>(.*?)</article>', re.S)
ONTO_RE = re.compile(
    r'"predicate":"http://www\.ft\.com/ontology/([^"]+)","prefLabel":"([^"]+)"'
)
TIME_RE = re.compile(r'datetime="([^"]+)"')
LEAD_FIGURE_RE = re.compile(r'<figure[^>]*class="[^"]*n-content-image[^"]*".*?</figure>', re.S)
OG_IMAGE_RE = re.compile(r'<meta property="og:image" content="([^"]+)"')


def strip_tags(s: str) -> str:
    return html.unescape(TAG_RE.sub(" ", s)).strip()


def _parse_ld(page: str) -> dict:
    for m in LD_RE.finditer(page):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        for d in data if isinstance(data, list) else [data]:
            if isinstance(d, dict) and d.get("@type") in ("NewsArticle", "Article"):
                return d
    return {}


def _figure(fragment: str) -> str:
    """Rebuild one <figure> with a responsive hotlinked image."""
    img = re.search(r'<img\b[^>]*\bsrc="([^"]+)"', fragment, re.I)
    if not img:
        return ""
    src = escape(html.unescape(img.group(1)))
    alt_m = re.search(r'\balt="([^"]*)"', fragment, re.I)
    alt = escape(html.unescape(alt_m.group(1))) if alt_m else ""
    out = (
        f'<figure><img src="{src}" alt="{alt}" '
        'style="max-width:100%;height:auto;" />'
    )
    cap = re.search(r"<figcaption[^>]*>(.*?)</figcaption>", fragment, re.S | re.I)
    if cap:
        text = strip_tags(cap.group(1))
        if text:
            out += f"<figcaption>{escape(text)}</figcaption>"
    return out + "</figure>"


def sanitize_body(inner: str) -> str:
    """Keep semantic blocks and responsive figures; drop ads/embeds/scripts."""
    inner = re.sub(r"<!--.*?-->", "", inner, flags=re.S)
    inner = re.sub(r"<(script|style|aside|iframe|form|button)\b.*?</\1>", "", inner, flags=re.S | re.I)
    inner = re.sub(r"<figure\b.*?</figure>", lambda m: _figure(m.group(0)), inner, flags=re.S | re.I)
    inner = re.sub(r"<(p|h2|h3|h4|blockquote|ul|ol|li)\b[^>]*>", r"<\1>", inner, flags=re.I)
    inner = re.sub(
        r'<a\b[^>]*\bhref="([^"]+)"[^>]*>(.*?)</a>',
        lambda m: f'<a href="{escape(html.unescape(m.group(1)))}">{m.group(2)}</a>',
        inner,
        flags=re.S | re.I,
    )
    allowed = {
        "p", "h2", "h3", "h4", "blockquote", "ul", "ol", "li", "a", "em", "strong",
        "i", "b", "br", "figure", "img", "figcaption",
    }
    inner = re.sub(
        r"</?([a-zA-Z0-9]+)[^>]*>",
        lambda m: m.group(0) if m.group(1).lower() in allowed else "",
        inner,
    )
    inner = re.sub(r"<p>\s*(?:<br\s*/?>)?\s*</p>", "", inner, flags=re.I)
    inner = re.sub(r"[ \t]+", " ", inner)
    inner = re.sub(r"\n{3,}", "\n\n", inner)
    return inner.strip()


def parse_article_html(page: str, banx: bool = False) -> dict | None:
    """Fallback full-text article from www.ft.com HTML."""
    ld = _parse_ld(page)
    title_m = H1_RE.search(page)
    title = strip_tags(title_m.group(1)) if title_m else str(ld.get("headline", ""))
    date = None
    raw = ld.get("datePublished") or (TIME_RE.search(page).group(1) if TIME_RE.search(page) else "")
    if raw:
        try:
            date = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            date = None
    labels = {label for _, label in ONTO_RE.findall(page)}
    body_m = BODY_RE.search(page)
    body = sanitize_body(body_m.group(1)) if body_m else ""
    if banx and "<img" not in body:
        # Cartoons are the lead figure; the article body is only a link.
        lead = LEAD_FIGURE_RE.search(page)
        body = _figure(lead.group(0)) if lead else ""
        if not body:
            og = OG_IMAGE_RE.search(page)
            if og:
                body = (
                    f'<figure><img src="{escape(html.unescape(og.group(1)))}" alt="" '
                    'style="max-width:100%;height:auto;" /></figure>'
                )
    if not body or not title:
        return None
    return {
        "title": title,
        "date": date,
        "standfirst": "",
        "byline": "",
        "labels": labels,
        "body_html": body,
    }


# --- feed I/O -----------------------------------------------------------------
ITEM_RE = re.compile(r"<item>.*?</item>", re.S)
GUID_UUID_RE = re.compile(r"<guid[^>]*>[^<]*?([0-9a-f-]{36})</guid>")
PUBDATE_RE = re.compile(r"<pubDate>([^<]+)</pubDate>")


def _block_date(block: str) -> dt.datetime:
    m = PUBDATE_RE.search(block)
    if m:
        try:
            return parsedate_to_datetime(m.group(1).strip())
        except (TypeError, ValueError):
            pass
    return dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)


def load_state(session: creq.Session) -> tuple[dict[str, str], set[str]]:
    """Published item blocks keyed by UUID plus skipped (excluded) UUIDs."""
    items: dict[str, str] = {}
    skipped: set[str] = set()
    local_feed = os.path.join(OUT_DIR, FEED_KEY, "feed.xml")
    local_cache = os.path.join(OUT_DIR, FEED_KEY, "cache.json")
    if os.path.exists(local_cache):
        try:
            with open(local_cache, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("v") == CACHE_VERSION:
                skipped = set(data.get("skipped", []))
        except Exception:
            pass
    if not skipped and PUBLISHED_BASE_URL:
        cache_body = fetch(session, f"{PUBLISHED_BASE_URL}/{FEED_KEY}/cache.json")
        if cache_body:
            try:
                data = json.loads(cache_body)
                if data.get("v") == CACHE_VERSION:
                    skipped = set(data.get("skipped", []))
            except Exception:
                pass
    body = None
    if os.path.exists(local_feed):
        try:
            with open(local_feed, encoding="utf-8") as f:
                body = f.read()
        except Exception:
            pass
    if not body and PUBLISHED_BASE_URL:
        body = fetch(session, f"{PUBLISHED_BASE_URL}/{FEED_KEY}/feed.xml")
    if body:
        for m in ITEM_RE.finditer(body):
            g = GUID_UUID_RE.search(m.group(0))
            if g:
                items[g.group(1)] = m.group(0).strip()
    print(f"  loaded {len(items)} published items ({len(skipped)} skipped)")
    return items, skipped


def render_item(art: dict) -> str:
    pub = art["date"] or dt.datetime.now(dt.timezone.utc)
    summary = art.get("standfirst") or strip_tags(art["body_html"])
    if len(summary) > 500:
        summary = summary[:500].rsplit(" ", 1)[0] + "…"
    link = CONTENT.format(uuid=art["uuid"])
    author = art.get("byline") or ""
    author_tag = f"      <author>{escape(author)}</author>\n" if author else ""
    return (
        "    <item>\n"
        f"      <title>{escape(art['title'])}</title>\n"
        f"      <link>{link}</link>\n"
        f'      <guid isPermaLink="true">{link}</guid>\n'
        f"      <pubDate>{format_datetime(pub)}</pubDate>\n"
        f"{author_tag}"
        f"      <description>{escape(summary)}</description>\n"
        f"      <content:encoded><![CDATA[{art['body_html']}]]></content:encoded>\n"
        "    </item>"
    )


def repair_newest(session: creq.Session, items: dict[str, str], count: int) -> int:
    """Re-render the newest published items from the API (one-off backfill)."""
    if count <= 0:
        return 0
    newest = sorted(items, key=lambda u: _block_date(items[u]), reverse=True)[:count]
    repaired = 0
    for uid in newest:
        content = fetch_api(session, uid)
        if not content:
            continue
        art = render_article(content)
        art["uuid"] = uid
        items[uid] = render_item(art).strip()
        repaired += 1
        time.sleep(DELAY)
    print(f"  repaired {repaired}/{len(newest)} newest items")
    return repaired


def build_feed(items: dict[str, str]) -> str:
    ordered = [
        items[u]
        for u in sorted(items, key=lambda u: (_block_date(items[u]), u), reverse=True)
    ][:MAX_ITEMS]
    now = format_datetime(dt.datetime.now(dt.timezone.utc))
    self_url = f"{PUBLISHED_BASE_URL}/{FEED_KEY}/feed.xml" if PUBLISHED_BASE_URL else ""
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
        f"    <title>{escape(FEED_TITLE)}</title>\n"
        f"    <link>{escape(OPINION)}</link>\n"
        f"    <description>{escape(FEED_DESC)}</description>\n"
        "    <language>en</language>\n"
        f"    <lastBuildDate>{now}</lastBuildDate>\n"
        f"{atom}"
        + "\n".join(ordered)
        + "\n  </channel>\n</rss>\n"
    )


def write_feed(xml: str, count: int, skipped: set[str]) -> None:
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
    with open(os.path.join(d, "cache.json"), "w", encoding="utf-8") as f:
        json.dump({"v": CACHE_VERSION, "skipped": sorted(skipped)[:1000]}, f)


# --- main ---------------------------------------------------------------------
def scrape(session: creq.Session, cand: dict) -> tuple[dict, dict | None]:
    """One article: app API first, www HTML fallback. Fails -> retried next run."""
    content = fetch_api(session, cand["uuid"])
    art = render_article(content) if content else None
    if not art:
        page = fetch(session, CONTENT.format(uuid=cand["uuid"]))
        if page:
            art = parse_article_html(page, banx=cand.get("banx", False))
    time.sleep(DELAY)
    if not art:
        return cand, None
    art["uuid"] = cand["uuid"]
    if not art["date"] and cand["date"]:
        try:
            art["date"] = parsedate_to_datetime(cand["date"])
        except (TypeError, ValueError):
            pass
    return cand, art


def run(session: creq.Session) -> int:
    print(f"[{FEED_KEY}]")
    existing, skipped = load_state(session)
    repair_newest(session, existing, REPAIR_NEWEST)
    rows = discover(session)
    candidates = {}
    staged = 0
    for uid, row in rows.items():
        if uid in existing or uid in skipped:
            continue
        if excluded_by_listing(row):
            skipped.add(uid)
            staged += 1
            continue
        candidates[uid] = row
    print(f"  {len(candidates)} new candidates to scrape ({staged} pre-excluded)")
    found = 0
    if candidates:
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futures = {ex.submit(scrape, session, c): c for c in candidates.values()}
            for fut in as_completed(futures):
                cand, art = fut.result()
                if not art:
                    continue  # transient; retried next run
                if (
                    art["labels"] & EX_LABELS
                    or art["title"].startswith(EX_PREFIXES)
                    or cand["rss_title"].startswith(EX_PREFIXES)
                ):
                    skipped.add(cand["uuid"])
                    continue
                existing[cand["uuid"]] = render_item(art).strip()
                found += 1
    xml = build_feed(existing)
    kept = min(len(existing), MAX_ITEMS)
    write_feed(xml, kept, skipped)
    print(f"  {FEED_KEY}: fetched {found}, feed now {kept}")
    return kept


def main() -> int:
    session = make_session()
    run(session)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
