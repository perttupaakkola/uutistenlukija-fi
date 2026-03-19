"""
Deduplication — tracks published article fingerprints to prevent republishing.
"""
import json
import os
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
