"""Which article pages are offered to search engines.

Short automated articles (under 150 words of body text, not explainers, with no
earned Google impressions) stay published for readers but are served
`noindex,follow` and left out of the sitemap, so search engines judge the site
by its fuller pages. The list is reviewed data in search_noindex.json.
"""
import json
from pathlib import Path

_FILE = Path(__file__).with_name("search_noindex.json")


def _load():
    try:
        return frozenset(json.loads(_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return frozenset()


NOINDEX_PATHS = _load()


def indexable(path, draft=None):
    """True when the article page at `path` (uutiset/.../) should be indexed."""
    return "/" + str(path).strip("/") + "/" not in NOINDEX_PATHS
