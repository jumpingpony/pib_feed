# Tasks & Roadmap

1. **Switch Remaining Static Sources to Direct Links (Free ~4.7 GB Release Space)**:
   - **NITI Aayog** (`niti.py`): Set `NITI_ARCHIVE_MODE: link` in CI; delete `niti-2019`…`niti-2026` releases (~1.38 GB).
   - **NextIAS Magazine** (`meca.py`): Set `MECA_ARCHIVE_MODE: link` in CI; delete `nextias-magazine-2024`…`2026` releases (~1.56 GB).
   - **Vision IAS** (`visioniaspt365.py`): Set `VIS_ARCHIVE_MODE: link` in CI; delete `visionias-pt365-*` and `visionias-mains365-*` releases (~1.78 GB).

2. **Automated User-Agent Modernization**:
   - Implement an automated mechanism to dynamically resolve or periodically update the standard browser User-Agent string to the latest stable Chrome release.
   - Propagate the up-to-date UA across all standalone scraper scripts and workflows.

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
