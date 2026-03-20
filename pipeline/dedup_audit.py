"""
dedup_audit.py — Near-duplicate detection across published articles.

Detects same-event articles that slipped through the title-similarity gate:
- Two articles about the same news event, written from different RSS sources,
  will have different Finnish titles/content but share many named entities
  (proper nouns, place names, uncommon long words).

Usage:
    python3 pipeline/dedup_audit.py              # audit published articles
    python3 pipeline/dedup_audit.py --verbose    # show shared keywords per pair

Reports pairs sorted by confidence. Use output to manually review or auto-drop.
"""

import os
import re
import sys
import itertools
import argparse
from difflib import SequenceMatcher
from collections import Counter
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

CONTENT_POSTS_DIR = Path(__file__).parent.parent / "content" / "posts"

# Title similarity: 0.60 catches "jalkapallojoukkueen kapteeni poistui" vs "jalkapallomaajoukkueen kapteeni luopui"
TITLE_SIM_THRESHOLD = 0.60

# Keyword overlap: long Finnish words (6+ chars) shared between two articles
# 12+ shared = strong signal of same event
KEYWORD_OVERLAP_THRESHOLD = 12

# Finnish stopwords (common function words that don't indicate same event)
STOPWORDS = {
    'jälkeen', 'ennen', 'kanssa', 'mukaan', 'mukana', 'vuonna', 'vuoden',
    'tämän', 'tässä', 'tähän', 'tähän', 'siinä', 'siihen', 'siitä',
    'sinne', 'sieltä', 'siellä', 'tänne', 'täällä', 'täältä',
    'heidän', 'heille', 'heistä', 'hänelle', 'hänestä', 'häntä',
    'joiden', 'joille', 'joissa', 'joista', 'jotka', 'joihin',
    'kautta', 'kohti', 'välillä', 'aikana', 'osalta', 'puolesta',
    'kaikki', 'kaikille', 'kaikista', 'kaikkia', 'kaikkien',
    'useita', 'useiden', 'useille', 'useissa', 'useista',
    'toinen', 'toisen', 'toiseen', 'toiselle', 'toisessa',
    'myöhemmin', 'aiemmin', 'viime', 'seuraava', 'seuraavan',
    'kertoo', 'sanoo', 'toteaa', 'arvioi', 'kertoi', 'sanoi',
    'samalla', 'samaan', 'samassa', 'samassa', 'samasta',
    'paljon', 'vähän', 'hyvin', 'hyvillä', 'paremmin',
    'tärkeää', 'tärkeä', 'tärkeän', 'tärkeät',
    'suomessa', 'suomesta', 'suomeen', 'suomalaiset', 'suomalainen',
    'helsingissä', 'helsingin', 'helsinkiin', 'helsinki',
    'kuitenkin', 'kuitenkaan', 'kuitenkin', 'siksi', 'joten',
    'koska', 'vaikka', 'jotta', 'joten', 'sekä', 'sekäkin',
    'lisäksi', 'lisää', 'lisätietoja', 'lisäksi', 'myös',
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalize_title(title: str) -> str:
    return re.sub(r"[^\w\s]", "", title.lower()).strip()


def _title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize_title(a), _normalize_title(b)).ratio()


def _extract_keywords(text: str) -> set:
    """Extract long Finnish words that indicate named entities / specific events."""
    words = re.sub(r"[^\w]", " ", text.lower()).split()
    return {
        w for w in words
        if len(w) >= 6 and w not in STOPWORDS
    }


def _keyword_overlap(a: str, b: str) -> tuple[int, set]:
    """Return (overlap_count, shared_keywords) for two text bodies."""
    kw_a = _extract_keywords(a)
    kw_b = _extract_keywords(b)
    shared = kw_a & kw_b
    return len(shared), shared


# ── Article loader ────────────────────────────────────────────────────────────

def load_published_articles() -> list[dict]:
    articles = []
    for path in sorted(CONTENT_POSTS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
        if not m:
            continue
        fm, content = m.group(1), m.group(2).strip()
        title_m = re.search(r'^title:\s*"(.+)"', fm, re.MULTILINE)
        cat_m = re.search(r"categories:\s*\n\s*-\s*(.+)", fm)
        articles.append({
            "fname": path.name,
            "title": title_m.group(1) if title_m else "",
            "category": cat_m.group(1).strip() if cat_m else "",
            "content": content,
        })
    return articles


# ── Detection ─────────────────────────────────────────────────────────────────

def find_near_duplicates(articles: list[dict]) -> list[dict]:
    """
    Compare all pairs. Return list of duplicate groups sorted by confidence.
    Each result: {confidence, title_sim, keyword_overlap, shared_kw, a, b}
    """
    results = []
    for a, b in itertools.combinations(articles, 2):
        title_sim = _title_similarity(a["title"], b["title"])
        kw_overlap, shared_kw = _keyword_overlap(a["content"], b["content"])

        # Confidence scoring
        # Title sim ≥ 0.60 is strong signal (same Finnish event, slight rephrasing)
        # Keyword overlap ≥ 12 is strong signal (many shared named entities)
        # Both together = very high confidence
        if title_sim >= TITLE_SIM_THRESHOLD or kw_overlap >= KEYWORD_OVERLAP_THRESHOLD:
            confidence = (title_sim * 0.5) + (min(kw_overlap, 30) / 30 * 0.5)
            results.append({
                "confidence": confidence,
                "title_sim": title_sim,
                "keyword_overlap": kw_overlap,
                "shared_kw": sorted(shared_kw)[:15],
                "a": a,
                "b": b,
            })

    return sorted(results, key=lambda x: -x["confidence"])


# ── Pre-publish gate ──────────────────────────────────────────────────────────

def filter_near_duplicates(
    incoming: list[dict],
    published_titles: list[str],
    published_contents: list[str],
    title_threshold: float = TITLE_SIM_THRESHOLD,
    keyword_threshold: int = KEYWORD_OVERLAP_THRESHOLD,
) -> tuple[list[dict], int]:
    """
    Filter incoming articles against published content.

    Returns (kept_articles, dropped_count).
    An incoming article is dropped if:
    - Title similarity ≥ title_threshold against any published title, OR
    - Keyword overlap ≥ keyword_threshold against any published content body
    """
    kept = []
    dropped = 0

    for article in incoming:
        incoming_title = article.get("title", "")
        incoming_content = article.get("content", "")
        is_dupe = False

        # Check title similarity
        for pub_title in published_titles:
            if _title_similarity(incoming_title, pub_title) >= title_threshold:
                print(
                    f"[dedup:gate] TITLE_MATCH (sim={_title_similarity(incoming_title, pub_title):.2f}): "
                    f"'{incoming_title[:60]}'"
                )
                is_dupe = True
                break

        # Check keyword overlap (only if title didn't already match)
        if not is_dupe and incoming_content:
            for pub_content in published_contents:
                overlap, shared = _keyword_overlap(incoming_content, pub_content)
                if overlap >= keyword_threshold:
                    print(
                        f"[dedup:gate] KW_MATCH ({overlap} shared kw): "
                        f"'{incoming_title[:60]}'"
                    )
                    is_dupe = True
                    break

        if is_dupe:
            dropped += 1
        else:
            kept.append(article)

    return kept, dropped


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Audit published articles for near-duplicates")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show shared keywords")
    parser.add_argument(
        "--threshold-title", type=float, default=TITLE_SIM_THRESHOLD,
        help=f"Title similarity threshold (default: {TITLE_SIM_THRESHOLD})"
    )
    parser.add_argument(
        "--threshold-kw", type=int, default=KEYWORD_OVERLAP_THRESHOLD,
        help=f"Keyword overlap threshold (default: {KEYWORD_OVERLAP_THRESHOLD})"
    )
    args = parser.parse_args()

    articles = load_published_articles()
    print(f"Loaded {len(articles)} published articles")
    print(f"Comparing {len(articles) * (len(articles) - 1) // 2} pairs...\n")

    dupes = find_near_duplicates(articles)

    if not dupes:
        print("✅ No near-duplicate pairs found.")
        return

    # Group by confidence tier
    high = [d for d in dupes if d["confidence"] >= 0.65]
    medium = [d for d in dupes if 0.45 <= d["confidence"] < 0.65]
    low = [d for d in dupes if d["confidence"] < 0.45]

    print(f"⚠️  Found {len(dupes)} near-duplicate pairs:")
    print(f"   High confidence (≥0.65): {len(high)}")
    print(f"   Medium (0.45–0.65):      {len(medium)}")
    print(f"   Low (<0.45):             {len(low)}")
    print()

    for tier_name, tier in [("HIGH", high), ("MEDIUM", medium), ("LOW", low)]:
        if not tier:
            continue
        print(f"=== {tier_name} CONFIDENCE ===")
        for d in tier:
            a, b = d["a"], d["b"]
            print(
                f"\n  conf={d['confidence']:.2f}  title_sim={d['title_sim']:.2f}  "
                f"kw_overlap={d['keyword_overlap']}"
            )
            print(f"  A [{a['category']}]: {a['title'][:80]}")
            print(f"  B [{b['category']}]: {b['title'][:80]}")
            if args.verbose and d["shared_kw"]:
                print(f"  Shared: {d['shared_kw'][:10]}")
        print()

    print(f"Total pairs analyzed: {len(articles) * (len(articles) - 1) // 2}")
    print(f"Near-duplicate pairs: {len(dupes)}")


if __name__ == "__main__":
    main()
