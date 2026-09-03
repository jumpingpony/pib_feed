# Tasks & Roadmap

## Priority 1 (Highest)

- [ ] **Add back The Economist RSS feeds**:
  - Resolve full-text / article extraction past paywall and Cloudflare.
  - Implement durable image handling without heavy release mirroring or socket drops.
  - Re-integrate `economist.py` into `.github/workflows/build-feeds.yml`.
  - Update `DOCS.md`, `OPML/economist.opml`, and `OPML/all.opml`.

## Priority 2

- [ ] **Switch Remaining Static Sources to Direct Links (Free ~4.7 GB Release Space)**:
  - **NITI Aayog** (`niti.py`): Set `NITI_ARCHIVE_MODE: link` in CI; delete `niti-2019`…`niti-2026` releases (saves ~1.38 GB).
  - **NextIAS Magazine** (`meca.py`): Set `MECA_ARCHIVE_MODE: link` in CI; delete `nextias-magazine-2024`…`2026` releases (saves ~1.56 GB).
  - **Vision IAS** (`visioniaspt365.py`): Set `VIS_ARCHIVE_MODE: link` in CI; delete `visionias-pt365-*` and `visionias-mains365-*` releases (saves ~1.78 GB).

## Priority 3

- [ ] **Resolve Indian Express 403 on Remote CI Runners**:
  - Investigate Azure datacenter IP geo-blocking for `indianexpress-explained` and `indianexpress-opinion`.
  - Test alternate request headers or proxying to avoid 403 Forbidden on GitHub Actions.

## Priority 4

- [ ] **Full-Article Body Extraction Audit**:
  - Audit feeds delivering summaries/snippets and evaluate extraction rules for complete article bodies.
