"""
Deduplication — tracks published article fingerprints to prevent republishing.

Three layers:
1. Title fingerprint (sorted word hash) — catches exact/near-exact RSS dupes
2. URL hash — catches cross-source same-URL dupes
3. Semantic title similarity — compares incoming titles against already-published
   content/posts/*.md front matter titles using difflib (>85% similarity threshold)
"""
import glob
import json
import os
import re
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher

DEDUP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "published_fingerprints.json")
URL_HASH_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "published_url_hashes.json")
MAX_AGE_DAYS = 7  # Forget fingerprints older than 7 days

# Semantic dedup: content/posts/ directory (relative to pipeline/)
_CONTENT_POSTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "content", "posts"
)
SIMILARITY_THRESHOLD = 0.85


def _normalize_title(title: str) -> str:
    """Lowercase, strip punctuation for fairer comparison."""
    return re.sub(r"[^\w\s]", "", title.lower()).strip()


def _titles_similar(a: str, b: str) -> bool:
    """Return True if two titles are >85% similar."""
    return SequenceMatcher(None, _normalize_title(a), _normalize_title(b)).ratio() >= SIMILARITY_THRESHOLD


def load_published_titles() -> list[str]:
    """
    Load titles from all content/posts/*.md front matter.
    Only reads the first ~10 lines of each file (front matter only — fast).
    """
    titles = []
    pattern = os.path.join(_CONTENT_POSTS_DIR, "*.md")
    for path in glob.glob(pattern):
        try:
            with open(path, "r", encoding="utf-8") as f:
                in_front_matter = False
                for i, line in enumerate(f):
                    if i == 0 and line.strip() == "---":
                        in_front_matter = True
                        continue
                    if in_front_matter:
                        if line.strip() == "---":
                            break  # end of front matter
                        if line.startswith("title:"):
                            # title: "Some title" or title: Some title
                            raw = line[len("title:"):].strip().strip('"').strip("'")
                            if raw:
                                titles.append(raw)
                            break
                    if i > 15:
                        break  # give up — malformed front matter
        except (IOError, UnicodeDecodeError):
            continue
    return titles


def check_published_duplicates(articles: list) -> list:
    """
    Filter out articles whose titles are >85% similar to any already-published post.
    Loads published titles from content/posts/*.md front matter.
    """
    published_titles = load_published_titles()
    if not published_titles:
        return articles  # nothing to compare against

    kept = []
    dropped = 0
    for article in articles:
        incoming_title = article.get("title", "")
        if not incoming_title:
            kept.append(article)
            continue
        is_dupe = any(_titles_similar(incoming_title, pt) for pt in published_titles)
        if is_dupe:
            dropped += 1
        else:
            kept.append(article)

    if dropped:
        print(f"[dedup:published] {dropped} articles dropped (similar to already-published titles)")
    return kept


def load_fingerprints() -> dict:
    """Load published fingerprints. Returns {fingerprint: iso_date_string}."""
    if not os.path.exists(DEDUP_FILE):
        return {}
    try:
        with open(DEDUP_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def save_fingerprints(fps: dict):
    """Save fingerprints to disk."""
    with open(DEDUP_FILE, "w") as f:
        json.dump(fps, f, indent=2)


def _load_url_hashes() -> dict:
    """Load published URL hashes. Returns {url_hash: iso_date_string}."""
    if not os.path.exists(URL_HASH_FILE):
        return {}
    try:
        with open(URL_HASH_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save_url_hashes(hashes: dict):
    with open(URL_HASH_FILE, "w") as f:
        json.dump(hashes, f, indent=2)


def filter_new_articles(articles: list) -> list:
    """Remove articles that have already been published. Returns only new ones."""
    fps = load_fingerprints()
    url_hashes = _load_url_hashes()

    # Clean old entries
    cutoff = (datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)).isoformat()
    fps = {k: v for k, v in fps.items() if v > cutoff}
    url_hashes = {k: v for k, v in url_hashes.items() if v > cutoff}

    new_articles = []
    for article in articles:
        fp = article.get("fingerprint", "")
        url_h = article.get("_url_hash", "")
        # Skip if seen by title fingerprint or URL hash
        if (fp and fp in fps) or (url_h and url_h in url_hashes):
            continue
        new_articles.append(article)

    print(f"[dedup] {len(articles)} scanned → {len(new_articles)} new ({len(articles) - len(new_articles)} duplicates filtered)")
    return new_articles


def mark_published(articles: list):
    """Mark articles as published."""
    fps = load_fingerprints()
    url_hashes = _load_url_hashes()
    now = datetime.now(timezone.utc).isoformat()
    for article in articles:
        fp = article.get("fingerprint", "")
        url_h = article.get("_url_hash", "")
        if fp:
            fps[fp] = now
        if url_h:
            url_hashes[url_h] = now
    save_fingerprints(fps)
    _save_url_hashes(url_hashes)
