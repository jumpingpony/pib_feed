---
name: add-feed
description: >-
  Use this skill when researching, designing, or implementing new full-text RSS feeds.
  Provides generalized discovery heuristics, endpoint probing methodology, payload extraction
  patterns, and feed lifecycle integration rules without source-specific code.
---

# Feed Discovery & Integration Heuristics

This runbook guides the systematic identification, inspection, full-text extraction, and lifecycle integration of new RSS feeds.

---

## 1. Ground-Truth Inspection & Paywall Impact (First Step)

Do not jump to a predetermined endpoint type before understanding the live webpage and paywall interaction. Listing rigid solutions first artificially reduces research scope.

### Step 1: Live Terminal Probe
- Fetch the target URL directly using the project standard User-Agent:
  ```bash
  curl -A "$UA" -sI "$URL"
  curl -A "$UA" -sL "$URL" -o sample.html
  ```
- Inspect the raw HTML, response headers, and status codes:
  - Is the page server-rendered, or is it an SPA shell requiring client-side hydration?
  - Where does the article text live? Inside semantic HTML tags, embedded JSON script tags, or fetched asynchronously?
  - Are edge CDNs (Cloudflare, Akamai) issuing challenges or 403s against automated tools?

### Step 2: Paywall & Anti-Bot Rule Inspection
- **Pre-Inspection Rule Refresh**: Update the local Bypass Paywalls Clean database in place before consulting rules:
  1. Note current version:
     ```bash
     grep '"version"' ~/.local/share/bypass-paywalls-chrome-clean-master/manifest.json
     ```
  2. Download latest master zip with retries and verify archive integrity:
     ```bash
     curl -fL --retry 3 -o /tmp/bpc.zip \
       "https://gitflic.ru/project/magnolia1234/bpc_uploads/blob/raw?file=bypass-paywalls-chrome-clean-master.zip"
     file /tmp/bpc.zip   # verify output contains "Zip archive"
     ```
  3. Overwrite files in place:
     ```bash
     unzip -q -o /tmp/bpc.zip -d ~/.local/share/
     ```
  4. Verify updated version and remove temp archive:
     ```bash
     grep '"version"' ~/.local/share/bypass-paywalls-chrome-clean-master/manifest.json
     rm -f /tmp/bpc.zip
     ```
- Check `sites.js` and `cs_local/contentScript_en.js` for the target domain:
  - Observe how the paywall affects the site: client-side script overlays, CSS gating, crawler verification, or cookie metering.
  - Determine if the raw server-side GET already bypasses the paywall (because client-side JS never runs).
  - Determine if crawler user-agents, `X-Forwarded-For` spoofing, or translation relays (`translate.goog`) unlock the full text.
  - Check if dedicated article feed APIs or `/amp/` alternate endpoints serve unmetered full text.

### Step 3: Runner Environment Heuristic
- When a target site employs CDN bot-detection (e.g., Cloudflare, Akamai, CloudFront), GitHub Actions runner IPs may behave differently than local IPs.
- If requests fail in CI, dispatch a minimal temporary `.github/workflows/probe.yml` using `gh run watch` to test endpoint connectivity from the exact runner family.

---

## 2. Open-Ended Architectural Discovery

Conduct unconstrained exploratory research into how the site exposes and paginates its content.

### Reference Toolkit of Potential Architectural Solutions
Consult this non-exhaustive reference checklist during research for inspiration, without treating it as a restrictive funnel:
- **Headless / CMS REST & GraphQL APIs**: WordPress REST (`/wp-json/wp/v2/posts`), Ghost Content API, Drupal JSON:API, or GraphQL endpoints.
- **Hydration & Application State**: Next.js (`<script id="__NEXT_DATA__">`, `/_next/data/...`), Nuxt (`_payload.json`), global state (`__INITIAL_STATE__`), JSON-LD schema blocks (`ItemList`, `NewsArticle`).
- **Internal Microservices & Content Feeds**: Unmetered AUFS feeds, Solr/Elasticsearch search gateways, or mobile content APIs.
- **Dedicated Author / Section Profiles**: Author profile URLs or section-specific indexes that partition editorial columns from general blogs.
- **Syndication Feeds**: Official RSS/Atom/JSON feeds used as discovery queues for canonical permalinks and publication dates.
- **Sequential Walks & Form Postbacks**: Monotonic numerical sequence walks (e.g. PRID ranges) or form postback sequences across date/category facets.
- **Binary Asset & Enclosure Endpoints**: Direct PDF or MP3 tracks verified via HTTP byte-range probes for length and MIME type.
- **Alternate Surfaces & Mirrors**: AMP variants (`/amp/`), translation relays (`translate.goog`), print edition views, or web archives.
- **Site-Specific Mechanisms**: Unindexed internal endpoints, mobile web views, or custom token exchanges. Original research must explore the live application behavior.

---

## 3. Freshness & Frequency Validation Heuristics

### Detecting Stale vs. Active Platforms
- Publishers frequently migrate CMS architectures without redirecting legacy subdomains or paths (e.g., abandoning older WordPress `/blogs/` while launching new native sections).
- **Verification rule**: Inspect timestamps of the top 3 items across candidates.
  - If latest post date is months or years old, mark candidate as abandoned.
  - Confirm active publication matches expected editorial cadence (e.g., daily for print edit pages, weekly for Sunday columns).
- Look for "Print Edition" or "From Print" tags when seeking syndicated op-eds that may be partitioned from web-only community blogs.

---

## 4. Full-Text Sanitization & Responsive Media Heuristics

### Content Extraction
- Identify the innermost container encompassing the entire article body while excluding recommendations, ads, and related links.
- Parse text into semantic blocks: `<p>` paragraphs, `<h3>` subheadings, and `<blockquote>` quotes.
- Prepend verified author byline in `<strong>` tags if not embedded in the body.

### Responsive Media & Image Dimensions
- **Sensible Dimensions**:
  - Strip hardcoded CMS dimensions (e.g., dummy attributes like `h="100" w="1000"` or inline fixed widths) that cause image distortion or horizontal overflow in RSS readers.
  - Wrap article images in standard responsive HTML:
    `<figure><img src="..." alt="..." style="max-width:100%;height:auto;" /><figcaption>...</figcaption></figure>`.
- **Archiving Decision**:
  - Hotlink directly to the publisher's CDN if images resolve with HTTP 200 without authentication or hotlink blockers.
  - Do not mirror or archive images to GitHub releases unless assets are ephemeral or actively blocked.

### Junk Elimination
- Strip all `<embed>`, `<ins>`, `<script>`, `<style>`, and `<iframe>` ad placeholders.
- Remove promo text matching patterns such as "Also Read", "Click Here", "Subscribe", and newsletter banners.
- **Video/Audio Links**:
  - Only related video and audio links may be added to feed items.
  - **User Confirmation Required**: Prompt the user and obtain explicit confirmation before including any video or audio links in feed output.

---

## 5. Feed Persistence & Deduplication Heuristics

### State Merging
- Always support a `*_PUBLISHED_BASE_URL` environment variable.
- On startup, fetch the live `<base>/<key>/feed.xml` to load existing item GUIDs and timestamps.
- Only scrape detail bodies for **new items** not already present in the published feed, respecting a configurable `MAX_FETCH` limit.

### Continuous Feed Entry Extraction & Continuity Invariants
- **Cadence Invariants & Gap Detection**:
  - Enforce maximum allowed interval gaps based on publication cadence:
    - Daily: <= 3 days maximum gap.
    - Weekly: <= 10 days maximum gap.
    - Monthly: <= 45 days maximum gap.
    - Seasonal: Event or issue driven.
  - Items must be strictly reverse-chronological (`pubDate[i] >= pubDate[i+1]`).
  - Legitimate editorial breaks or recess periods must be registered in `tests/intentional_gaps.json`.
- **Timestamp Synthesis & Order Preservation**:
  - When items carry only coarse dates (year or month only), anchor mid-period and subtract rank offsets (`anchor - rank * delta`) so feed readers preserve listing order.
  - Resurfaced items (dockets, legislative trackers): sort and date by `modified` timestamp rather than `created`.
  - *Date Stability*: Once an item is published, preserve its assigned `pubDate` across all future runs.
- **Continuous Pagination & Stop Conditions**:
  - Walk backwards from newest items.
  - Do not terminate on a single known match (to tolerate pinned posts or re-ordered items). Terminate only after $N \ge 2$ consecutive pages have zero new items (`stale >= 2`) or when `MAX_FETCH` is reached.
  - Use API delta parameters (`&after=<ISO>`) where supported.
- **Sequence Scanning & Filter Caching**:
  - For monotonic numeric ID walks, scan backwards `SCAN_COUNT` steps from the highest observed ID.
  - Persist evaluated non-matching or filtered IDs in a state cache (`cache.json`) to prevent redundant requests on future runs.
- **Incomplete Item Self-Repair**:
  - On each steady-state run, re-inspect the newest $N$ published entries (typically top 5).
  - If an item body is truncated or contains fallback placeholders, re-scrape and repair it in the merged state.

### Feed Maintenance
- Sort all merged items strictly newest-first by publication datetime.
- Enforce a maximum item ceiling (typically 250 to 500 items) to keep feed XML files performant and within memory bounds.
- Wrap all body HTML in XML CDATA blocks (`<![CDATA[...]]>`) and sanitize control characters invalid in XML 1.0.

---

## 6. End-to-End Repository Integration Checklist

1. **Standalone Scraper**:
   - Single top-level `<source>.py` file.
   - Python 3.12 compatible; standard library + `requests` only.
   - Standard UPPER_CASE configuration environment variables (`*_MAX_FETCH`, `*_TIMEOUT`, `*_OUT_DIR`).
2. **Output Artifacts**:
   - `public/<key>/feed.xml` (valid RSS 2.0 with `<content:encoded>`).
   - `public/<key>/index.html` (readable landing page).
3. **CI Automation**:
   - Add script to push path triggers in `.github/workflows/build-feeds.yml`.
   - Add builder step with `continue-on-error: true`.
   - Register outcome in the workflow gate check.
4. **Catalog & OPML**:
   - Document feed details, source mechanics, and variables in `DOCS.md`.
   - Create `OPML/<source>.opml`.
   - Add feed entries to `OPML/all.opml`.
5. **Local Run, Commit, Push, Watch**:
   - Run the builder locally with a narrow scope; confirm the emitted `<OUT_DIR>/<key>/feed.xml` parses, is non-empty, is reverse-chronological, and carries full bodies.
   - If it works locally, commit and push.
   - Watch the triggered run to completion (`gh run watch <run-id> --exit-status`); proceed only on success.
   - Verify the deployed feed over HTTP at `<PUBLISHED_BASE_URL>/<key>/feed.xml`.
6. **Reader Subscription** (only after a green run):
   - If Inoreader integration is requested, use the OAuth credentials in `.inoreaderconfig`; `scripts/inoreader_migrate.py` shows the API pattern.
   - **Ask the user which folder** to file the feed under; do not assume one. Offer only real folders from the local cache `scratch/inoreader_folders.json` (gitignored). In this account only the `Tier *` labels are folders; every other label returned by the API is an entry tag, not a subscription target.
   - **Conserve Inoreader's quota (~100 requests/day)**: use the cache and refresh it only when the user asks (filtering the API labels down to the `Tier *` folders); keep the subscription itself to `subscription/quickadd`, then `subscription/edit` (`ac=edit`, `s=<streamId>`, `t=<title>`, `a=user/-/label/<folder>`), plus at most one verifying `subscription/list`.
   - If the API answers 401, refresh the access token first with the `refresh_token` grant on `https://www.inoreader.com/oauth2/token` (`client_id=app_id`, `client_secret=app_key`) and persist it.
   - Verify and report the feed title and folder.
