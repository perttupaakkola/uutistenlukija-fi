"""Which article pages are offered to search engines.

Articles rated as outdated or of little value to readers (AI rating of
information, importance, source trust and current relevance; source count is
not a criterion) and all distant NASA satellite-image pieces stay published
for readers but are served `noindex,follow` and left out of the sitemap.
The list is reviewed data in search_noindex.json. In addition, any new
article whose body is under MIN_INDEX_WORDS words (explainers excepted) is
served noindex automatically, so thin items never re-enter the index.
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


MIN_INDEX_WORDS = 150


def body_words(draft):
    """Body word count of a draft (dict or JSON text); None when unreadable."""
    try:
        if isinstance(draft, (str, bytes)):
            draft = json.loads(draft)
        return sum(len(str(p["text"]).split()) for p in draft["paragraphs"])
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


def indexable(path, draft=None):
    """True when the article page at `path` (uutiset/.../) should be indexed."""
    key = "/" + str(path).strip("/") + "/"
    if key in NOINDEX_PATHS:
        return False
    if draft is not None and "/selittaja-" not in key:
        words = body_words(draft)
        if words is not None and words < MIN_INDEX_WORDS:
            return False
    return True
