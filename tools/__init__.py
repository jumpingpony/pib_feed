"""Build utilities that operate on the generated site or on published state.

Unlike ``feeds/``, nothing here produces feed content on its own:

- ``archive_pdfs.py`` - upload manifests from ``archive/`` to GitHub releases and
  verify that every release link in ``public/`` resolves.
- ``carry_forward.py`` - copy published ``feed.xml``/``index.html`` for feeds the
  current run skips, so the Pages artifact never loses a directory.
- ``stagger_pubdates.py`` - one-off pubDate re-dating so Inoreader imports stale
  backfills (gated by the ``pubdate_stagger`` dispatch input).
- ``inoreader/`` - account operations: OAuth (``auth.py``) and subscription
  migration (``migrate.py``). Credentials live in the git-ignored
  ``.inoreaderconfig`` at the repo root.
"""
