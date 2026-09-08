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

## 1. Source Discovery & Endpoint Hierarchy

When onboarding a new publication or column, evaluate potential data sources from highest structure to lowest:

### Step 1: Endpoint Priority Ladder
1. **Public Headless / CMS APIs**:
   - Check standard CMS endpoints first:
     - WordPress REST API: `/wp-json/wp/v2/posts?categories=...` or `/wp-json/wp/v2/article`.
     - Ghost Content API: `/ghost/api/v3/content/posts/`.
     - Next.js / Nuxt hydration payloads: `/_next/data/...` or `/_payload.json`.
   - Advantages: Clean structured JSON, rendered or structured bodies, zero scraping fragility.

2. **Hydration & Application State**:
   - Inspect server-rendered page HTML for global state variables:
     - `window.__INITIAL_STATE__`
     - `window.App` / `window.__DATA__`
     - `<script id="__NEXT_DATA__" type="application/json">`
     - `<script type="application/ld+json">` (ItemList / NewsArticle schemas)
   - Advantages: Contains pre-rendered article lists, pagination tokens, timestamps, and metadata without parsing complex HTML trees.

3. **Internal Microservice / Search Index APIs**:
   - Trace network calls or search page bundles for internal backend gateways:
     - Solr / Elasticsearch search or feed endpoints (e.g., `/wufs/feed/...`, `/api/search/...`).
     - Content API feeds used by mobile apps or dynamic frontends.

4. **Dedicated Author / Section Profiles**:
   - If an op-ed or column does not appear on the general editorial front, locate the author's primary profile page or dedicated topic URL.
   - Compare update timestamps against front-page indices to detect section fragmentation.

5. **Official RSS/Atom Feeds (Metadata Baseline)**:
   - Check `<link rel="alternate" type="application/rss+xml">` or `/rss`, `/feed`, `/feeds/`.
   - Often metadata-only (titles and links without bodies), but provides canonical URLs and pubDate timestamps.

---

## 2. Freshness & Frequency Validation Heuristics

### Detecting Stale vs. Active Platforms
- Publishers frequently migrate CMS architectures without redirecting legacy subdomains or paths (e.g., abandoning older WordPress `/blogs/` while launching new native sections).
- **Verification rule**: Inspect timestamps of the top 3 items across candidates.
  - If latest post date is months or years old, mark candidate as abandoned.
  - Confirm active publication matches expected editorial cadence (e.g., daily for print edit pages, weekly for Sunday columns).
- Look for "Print Edition" or "From Print" tags when seeking syndicated op-eds that may be partitioned from web-only community blogs.

---

## 3. Ground-Truth Inspection & Paywall Heuristics

### Direct Inspection Rules
- Always use the project standard User-Agent header on every network probe.
- Fetch raw HTML and API responses directly via terminal tools (`curl`, `wget`) or Python sessions before designing selectors.

### Bypass Paywalls Clean Rules Inspection
- Check the local Bypass-Paywalls-Clean database at:
  `/home/slawpper/.local/share/bypass-paywalls-chrome-clean-master`
- Check `sites.js` and `cs_local/contentScript_en.js` for the target domain:
  - **Client-side overlays**: Paywall hides content via CSS/JS while full body is served in HTML DOM (no bypass needed on server-side requests).
  - **Dedicated article feed APIs**: Many paywalled outlets fetch full text via internal unmetered AUFS/JSON endpoints.
  - **Crawler verification bypass**: Check if the site serves full text to Googlebot via user-agent + `X-Forwarded-For` spoofing.
  - **AMP endpoints**: Check if an `/amp/` alternate URL provides clean, server-rendered full text.

### Runner Environment Heuristic
- When a target site employs CDN bot-detection (e.g., Cloudflare, Akamai, CloudFront), GitHub Actions runner IPs may behave differently than local IPs.
- If requests fail in CI, dispatch a minimal temporary `.github/workflows/probe.yml` using `gh run watch` to test endpoint connectivity from the exact runner family.

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
- Convert video/audio placeholders into plain hyperlink paragraphs (`<p><a href="...">Watch Video</a></p>`).

---

## 5. Feed Persistence & Deduplication Heuristics

### State Merging
- Always support a `*_PUBLISHED_BASE_URL` environment variable.
- On startup, fetch the live `<base>/<key>/feed.xml` to load existing item GUIDs and timestamps.
- Only scrape detail bodies for **new items** not already present in the published feed, respecting a configurable `MAX_FETCH` limit.

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
5. **Reader Subscription**:
   - If Inoreader integration is requested, use OAuth credentials in `.inoreaderconfig`.
   - Call `subscription/quickadd` followed by `subscription/edit` to assign to target folder.
