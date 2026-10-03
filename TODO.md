# Tasks & Roadmap

1. **Switch Remaining Static Sources to Direct Links (Free ~4.7 GB Release Space)**:
   - **NITI Aayog** (`niti.py`): Set `NITI_ARCHIVE_MODE: link` in CI; delete `niti-2019`…`niti-2026` releases (~1.38 GB).
   - **NextIAS Magazine** (`meca.py`): Set `MECA_ARCHIVE_MODE: link` in CI; delete `nextias-magazine-2024`…`2026` releases (~1.56 GB).
   - **Vision IAS** (`visioniaspt365.py`): Set `VIS_ARCHIVE_MODE: link` in CI; delete `visionias-pt365-*` and `visionias-mains365-*` releases (~1.78 GB).

2. **Automated User-Agent Modernization**:
   - Implement an automated mechanism to dynamically resolve or periodically update the standard browser User-Agent string to the latest stable Chrome release.
   - Propagate the up-to-date UA across all standalone scraper scripts and workflows.

3. **Reserve Bank of India (RBI) Feeds & Memorial Lectures Archive**:
   - Create standalone builder `rbi_feed.py` for 5 public RSS feeds:
     - `rbi_press_releases`: Reverse PRID walk for English releases.
     - `rbi_bulletin`: Monthly bulletin with PDF enclosure/link and HTML TOC body.
     - `rbi_publications`: Consolidated feed covering 6 frequencies (post-2023) with `[TimeTag]` and `[Category]` prefixes.
     - `rbi_speeches`: Governor/DG speeches (post-2023).
     - `rbi_media_interactions`: Post-policy press conferences (post-2025) with embedded YouTube links.
   - Create standalone generator `scripts/build_memo_lectures.py` for local-only archive in `~/rbi_memo_lec/`:
     - Clean typography using Merriweather serif font, `#faf9f5` warm light paper theme, 740px reading column.
     - Two-hop link resolution, column-aware targeting, and fallback mapping across all 47 lectures.
     - Generates `index.html` catalog and individual offline lecture pages.
   - Full technical specifications preserved in `.todo/rbi_feed_implementation_plan.md`.

4. **FT Opinion Full-Text Feed (`ft.com/opinion`, Life & Arts excluded, Banx included)**:
   - **Blocked**: GitHub-hosted runners hit a Cloudflare 403 lottery on ft.com HTML; no reliable full-text path from CI (6 probe runs). Locally `curl_cffi` + Google referer works 100%.
   - Draft builder preserved in `.todo/ft.py`; title format (`Lex. Title` etc.), exclusion rules and Banx discovery verified against 5 weeks of listings.
   - Pending decision: local scheduled generation + committed feed (recommended), flaky CI with `continue-on-error`, or a paid proxy/scraping API.
   - Full findings, verified exclusion rules and remaining integration steps in `.todo/ft_feed_implementation_plan.md`.

## Completed & Dropped

- **Times of India Op-Eds Full-Text Feed** (Done):
  - Research TOI Opinion / Edit Page endpoints and TOI Plus Swaminomics.
  - Create standalone builder `toi.py` producing `public/toi-opinion/feed.xml` and `public/toi-swami-nomics/feed.xml`.
  - Add feed definition to OPML collections and documentation.

- **Add back The Economist RSS feeds** (Done):
  - Resolve full-text / article extraction past paywall and Cloudflare.
  - Implement durable image handling without heavy release mirroring or socket drops.
  - Re-integrate `economist.py` into `.github/workflows/build-feeds.yml`.
  - Update `DOCS.md`, `OPML/economist.opml`, and `OPML/all.opml`.

- **Supreme Court Observer Rate Limiting & Concurrency** (Not to be done):
  - Set worker concurrency in `scobserver.py` to 1 (strictly sequential execution) for journal full-body fetching.
  - Add 900ms politeness sleep between per-article HTML requests to avoid exhausting `scobserver.in` PHP-FPM worker pool and prevent HTTP 503 rejections.
