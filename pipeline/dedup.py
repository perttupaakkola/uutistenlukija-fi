"""
Deduplication — tracks published article fingerprints to prevent republishing.
Includes fuzzy title matching to catch near-duplicates from different feeds.
"""
import json
import os
import re
from datetime import datetime, timezone, timedelta

DEDUP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "published_fingerprints.json")
URL_HASH_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "published_url_hashes.json")
MAX_AGE_DAYS = 7  # Forget fingerprints older than 7 days


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


def _normalize_title(title: str) -> set:
    """Normalize a title into a set of meaningful words for comparison."""
    title = title.lower().strip()
    # Remove common punctuation
    title = re.sub(r'[^\w\s]', ' ', title)
    # Split into words, remove short ones
    words = {w for w in title.split() if len(w) > 2}
    # Remove very common Finnish stop words
    stop_words = {'eli', 'tai', 'jos', 'kun', 'nyt', 'niin', 'myös', 'sekä',
                  'vain', 'ovat', 'olla', 'oli', 'ole', 'sen', 'tämä', 'tämän',
                  'hänen', 'hän', 'ovat', 'joka', 'jossa', 'jota', 'jonka',
                  'the', 'and', 'for', 'that', 'with', 'from', 'this', 'are'}
    return words - stop_words


def _titles_similar(title1: str, title2: str, threshold: float = 0.6) -> bool:
    """Check if two titles are semantically similar using Jaccard similarity."""
    words1 = _normalize_title(title1)
    words2 = _normalize_title(title2)
    if not words1 or not words2:
        return False
    intersection = words1 & words2
    union = words1 | words2
    similarity = len(intersection) / len(union)
    return similarity >= threshold


def filter_new_articles(articles: list) -> list:
    """Remove articles that have already been published. Returns only new ones.
    Also deduplicates within the current batch using fuzzy title matching."""
    fps = load_fingerprints()
    url_hashes = _load_url_hashes()

    # Clean old entries
    cutoff = (datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)).isoformat()
    fps = {k: v for k, v in fps.items() if v > cutoff}
    url_hashes = {k: v for k, v in url_hashes.items() if v > cutoff}

    new_articles = []
    seen_titles = []  # Track titles within this batch for fuzzy dedup
    exact_dupes = 0
    fuzzy_dupes = 0

    for article in articles:
        fp = article.get("fingerprint", "")
        url_h = article.get("_url_hash", "")
        title = article.get("title", "")

        # Skip if seen by title fingerprint or URL hash
        if (fp and fp in fps) or (url_h and url_h in url_hashes):
            exact_dupes += 1
            continue

        # Fuzzy title check within current batch
        is_fuzzy_dupe = False
        for seen_title in seen_titles:
            if _titles_similar(title, seen_title):
                is_fuzzy_dupe = True
                fuzzy_dupes += 1
                print(f"[dedup] Fuzzy duplicate skipped: '{title}' ≈ '{seen_title}'")
                break

        if is_fuzzy_dupe:
            continue

        seen_titles.append(title)
        new_articles.append(article)

    print(f"[dedup] {len(articles)} scanned → {len(new_articles)} new "
          f"({exact_dupes} exact + {fuzzy_dupes} fuzzy duplicates filtered)")
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
