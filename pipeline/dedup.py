"""
Deduplication — tracks published article fingerprints to prevent republishing.
"""
import json
import os
from datetime import datetime, timezone, timedelta

DEDUP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "published_fingerprints.json")
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


def filter_new_articles(articles: list) -> list:
    """Remove articles that have already been published. Returns only new ones."""
    fps = load_fingerprints()

    # Clean old fingerprints
    cutoff = (datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)).isoformat()
    fps = {k: v for k, v in fps.items() if v > cutoff}

    new_articles = []
    for article in articles:
        fp = article.get("fingerprint", "")
        if fp and fp not in fps:
            new_articles.append(article)

    print(f"[dedup] {len(articles)} scanned → {len(new_articles)} new ({len(articles) - len(new_articles)} duplicates filtered)")
    return new_articles


def mark_published(articles: list):
    """Mark articles as published."""
    fps = load_fingerprints()
    now = datetime.now(timezone.utc).isoformat()
    for article in articles:
        fp = article.get("fingerprint", "")
        if fp:
            fps[fp] = now
    save_fingerprints(fps)
