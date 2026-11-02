"""Source builders: one standalone module per publisher.

Every module runs on its own and writes into the repo-root ``public/`` tree:

    python feeds/pib_feed.py        # -> public/<feed-key>/feed.xml

Modules read their tunables from environment variables declared near the top of
each file; nothing is shared between them, so a source can change without
touching the others. Feed keys and env vars are documented in the matching
DOCS.md section listed below.

| Module | Source | DOCS.md section |
|---|---|---|
| `eacpm.py` | EAC-PM reports | EAC-PM feeds (unofficial) |
| `economist.py` | The Economist (app gateway) | The Economist feeds (unofficial) |
| `frontline.py` | Frontline magazine and blog | Frontline feeds (unofficial) |
| `ft.py` | FT Opinion | FT Opinion feed - full-text (unofficial) |
| `idsa.py` | MP-IDSA publications | MP-IDSA feeds (unofficial) |
| `ie_epaper.py` | Indian Express epaper and UPSC Essentials | Indian Express epaper feeds (unofficial) |
| `indianexpress.py` | The Indian Express full text | The Indian Express feeds - full-text (unofficial) |
| `indiasworld.py` | India's World | India's World feed (unofficial) |
| `indiatoday.py` | India Today magazine | India Today magazine feed (unofficial) |
| `ipcs.py` | IPCS commentaries | IPCS feed (unofficial) |
| `meca.py` | Made Easy and NextIAS PDFs | Current-affairs PDF feeds - Vision IAS, Made Easy, NextIAS (unofficial) |
| `mygov.py` | MyGov PDF publications | MyGov PDF feeds (unofficial) |
| `newsonair_feed.py` | News On AIR bulletins | News On AIR feed - Podcast & Full-Text (unofficial) |
| `niti.py` | NITI Aayog publications | NITI Aayog publication feeds (unofficial) |
| `pib_feed.py` | PIB press releases and PMO | PIB RSS feeds - English (unofficial) |
| `prsindia.py` | PRS Legislative Research | PRS Legislative Research feeds (unofficial) |
| `scobserver.py` | Supreme Court Observer | Supreme Court Observer feeds (unofficial) |
| `theprint.py` | ThePrint | ThePrint feeds - full-text (unofficial) |
| `toi.py` | Times of India op-eds | The Times of India feeds - full-text (unofficial) |
| `visioniaspt365.py` | Vision IAS PT 365 and Mains 365 | Current-affairs PDF feeds - Vision IAS, Made Easy, NextIAS (unofficial) |
"""
