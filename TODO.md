# Tasks & Roadmap

## Priority 1 (Highest)

- [ ] **Add back The Economist RSS feeds**:
  - Resolve full-text / article extraction past paywall and Cloudflare.
  - Implement durable image handling without heavy release mirroring or socket drops.
  - Re-integrate `economist.py` into `.github/workflows/build-feeds.yml`.
  - Update `DOCS.md`, `OPML/economist.opml`, and `OPML/all.opml`.

## Priority 2

- [ ] **Rate Limiting & Concurrency Fix for Supreme Court Observer**:
  - Set worker concurrency in `scobserver.py` to 1 (strictly sequential execution) for journal full-body fetching.
  - Add 900ms politeness sleep between per-article HTML requests to avoid exhausting `scobserver.in` Nginx/PHP-FPM worker pool and prevent HTTP 503 rejections.

- [ ] **Switch Remaining Static Sources to Direct Links (Free ~4.7 GB Release Space)**:
  - **NITI Aayog** (`niti.py`): Set `NITI_ARCHIVE_MODE: link` in CI; delete `niti-2019`…`niti-2026` releases (saves ~1.38 GB).
  - **NextIAS Magazine** (`meca.py`): Set `MECA_ARCHIVE_MODE: link` in CI; delete `nextias-magazine-2024`…`2026` releases (saves ~1.56 GB).
  - **Vision IAS** (`visioniaspt365.py`): Set `VIS_ARCHIVE_MODE: link` in CI; delete `visionias-pt365-*` and `visionias-mains365-*` releases (saves ~1.78 GB).

## Priority 3

- [ ] **Times of India Op-Eds Full-Text Feed**:
  - Research TOI Opinion / Edit Page endpoints (`timesofindia.indiatimes.com/opinions`, `blogs.timesofindia.indiatimes.com`).
  - Inspect article DOM and Bypass-Paywalls-Clean rules for clean body container extraction (`<article>`, `arttextxml`, or JSON state).
  - Create standalone builder `timesofindia.py` producing `public/toi-opinion/feed.xml`.
  - Add feed definition to OPML collections and documentation.

- [ ] **Resolve Indian Express 403 on Remote CI Runners**:
  - Investigate Azure datacenter IP geo-blocking for `indianexpress-explained` and `indianexpress-opinion`.
  - Test alternate request headers or proxying to avoid 403 Forbidden on GitHub Actions.

## Priority 4

- [ ] **Automated User-Agent Modernization**:
  - Implement an automated mechanism to dynamically resolve or periodically update the standard browser User-Agent string to the latest stable Chrome release.
  - Propagate the up-to-date UA across all standalone scraper scripts and workflows.

- [ ] **Inoreader Subscription Migration**:
  - [x] Subscribe all 44 feeds to `jumpingpony.github.io/pib_feed` on Inoreader.
  - [x] Configure titles and assign folders for all 44 feeds on Inoreader.
  - [x] Unsubscribe 16 legacy `nappingcats` feeds.
  - [ ] Unsubscribe remaining 30 legacy `nappingcats` feeds by re-running `python3 scripts/inoreader_migrate.py`.
