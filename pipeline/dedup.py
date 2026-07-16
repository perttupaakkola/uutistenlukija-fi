"""
Deduplication — tracks published article fingerprints to prevent republishing.

Four layers:
1. Title fingerprint (sorted word hash) — catches exact/near-exact RSS dupes
2. URL hash — catches cross-source same-URL dupes
3. Semantic title similarity — compares incoming titles against already-published
   content/posts/*.md front matter titles using difflib (>60% similarity threshold)
4. Keyword overlap — catches same-event articles written differently from different
   sources (e.g. "Himoksen kuolema" + "Lasketteluonnettomuus Himoksella")

Tier 1 source rule: if a story appears in a Tier 1 source (Yle, BBC, Reuters, HS…),
it is treated as verified real news. Within-batch dedup keeps the Tier 1 version
over lower-tier duplicates. Auto-deletion scripts must never delete Tier 1 articles.
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
URL_HASH_MAX_AGE_DAYS = 90  # Exact source URLs recur well beyond the semantic window

# Semantic dedup: content/posts/ directory (relative to pipeline/)
_CONTENT_POSTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "content", "posts"
)
SIMILARITY_THRESHOLD = 0.78   # Raised from 0.60 — was too aggressive, blocking most articles

# Keyword overlap dedup: long Finnish words (6+ chars) that indicate named entities
KEYWORD_OVERLAP_THRESHOLD = 20  # raised from 12 to reduce false positive deduplications

# Finnish function words that are NOT event-specific (don't count as signal)
_KW_STOPWORDS = {
    'jälkeen', 'ennen', 'kanssa', 'mukaan', 'mukana', 'vuonna', 'vuoden',
    'tämän', 'tässä', 'tähän', 'siinä', 'siihen', 'siitä',
    'heidän', 'heille', 'heistä', 'hänelle', 'hänestä', 'häntä',
    'joiden', 'joille', 'joissa', 'joista', 'jotka', 'joihin',
    'kautta', 'kohti', 'välillä', 'aikana', 'osalta', 'puolesta',
    'kaikki', 'kaikille', 'kaikista', 'kaikkia', 'kaikkien',
    'useita', 'useiden', 'useille', 'useissa', 'useista',
    'toinen', 'toisen', 'toiseen', 'toiselle', 'toisessa',
    'myöhemmin', 'aiemmin', 'viime', 'seuraava', 'seuraavan',
    'kertoo', 'sanoo', 'toteaa', 'arvioi', 'kertoi', 'sanoi',
    'samalla', 'samaan', 'samassa', 'samasta',
    'paljon', 'vähän', 'hyvin', 'paremmin',
    'tärkeää', 'tärkeä', 'tärkeän', 'tärkeät',
    'suomessa', 'suomesta', 'suomeen', 'suomalaiset', 'suomalainen',
    'helsingissä', 'helsingin', 'helsinkiin', 'helsinki',
    'kuitenkin', 'kuitenkaan', 'siksi', 'joten',
    'koska', 'vaikka', 'jotta', 'sekä',
    'lisäksi', 'lisää', 'lisätietoja',
}


def _normalize_title(title: str) -> str:
    """Lowercase, strip punctuation for fairer comparison."""
    return re.sub(r"[^\w\s]", "", title.lower()).strip()


def _titles_similar(a: str, b: str) -> bool:
    """Return True if two titles are ≥60% similar (catches same-event cross-source rewrites)."""
    return SequenceMatcher(None, _normalize_title(a), _normalize_title(b)).ratio() >= SIMILARITY_THRESHOLD


def _keyword_overlap(text_a: str, text_b: str) -> int:
    """Count long Finnish words (6+ chars) shared between two texts.

    Long words act as named-entity proxies: place names, proper nouns, and
    domain-specific terms that appear in both articles signal same-event coverage.
    """
    def extract(text: str) -> set:
        words = re.sub(r"[^\w]", " ", text.lower()).split()
        return {w for w in words if len(w) >= 6 and w not in _KW_STOPWORDS}

    return len(extract(text_a) & extract(text_b))


def load_published_articles(window_hours: int = 48) -> tuple[list[str], list[str]]:
    """
    Load titles and content bodies from content/posts/*.md published within
    the last ``window_hours`` hours (default 48h).

    Returns (titles, contents) — parallel lists.

    Articles outside the window are ignored so the similarity check stays fast
    and relevant to recent events only.  Pass window_hours=0 to load all.
    """
    titles = []
    contents = []
    cutoff: datetime | None = None
    if window_hours > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)

    pattern = os.path.join(_CONTENT_POSTS_DIR, "*.md")
    for path in sorted(glob.glob(pattern)):
        try:
            text = open(path, "r", encoding="utf-8").read()
            # Split on second "---" to get front matter + body
            parts = text.split("---", 2)
            if len(parts) < 3:
                continue
            fm, body = parts[1], parts[2]

            # Time-window filter: parse `date:` from front matter
            if cutoff is not None:
                date_m = re.search(r"^date:\s*['\"]?(\d{4}-\d{2}-\d{2}T[\d:+\-Z]+)['\"]?",
                                   fm, re.MULTILINE)
                if date_m:
                    try:
                        pub_date = datetime.fromisoformat(
                            date_m.group(1).replace("Z", "+00:00"))
                        if pub_date.tzinfo is None:
                            pub_date = pub_date.replace(tzinfo=timezone.utc)
                        if pub_date < cutoff:
                            continue  # outside window, skip
                    except ValueError:
                        pass  # unparseable date — include to be safe

            title_m = re.search(r"^title:\s*\"(.+)\"", fm, re.MULTILINE)
            if title_m:
                titles.append(title_m.group(1))
                contents.append(body.strip())
        except (IOError, UnicodeDecodeError):
            continue
    return titles, contents


def load_published_titles(window_hours: int = 48) -> list[str]:
    """Backwards-compatible wrapper — returns just titles."""
    titles, _ = load_published_articles(window_hours=window_hours)
    return titles


def dedup_within_batch(articles: list) -> list:
    """
    Remove within-batch near-duplicates — same event from different sources arriving
    in the same pipeline run.

    Tier rule: when a dupe is detected between a Tier 1 source and a lower-tier
    source, always keep the Tier 1 version (swap if needed). This ensures that
    a Yle/BBC/Reuters article is never dropped in favour of a tabloid rewrite
    of the same story.

    Uses same two signals as check_published_duplicates:
    1. Title similarity >= 60%
    2. Keyword overlap >= 12 long Finnish words
    """
    kept = []
    dropped = 0
    for article in articles:
        incoming_title = article.get("title", "")
        incoming_content = article.get("content", "")
        incoming_tier = article.get("source_tier", 2)

        is_dupe = False
        for i, accepted in enumerate(kept):
            # Signal 1: title similarity
            title_match = (incoming_title and accepted.get("title") and
                           _titles_similar(incoming_title, accepted["title"]))
            # Signal 2: keyword overlap
            kw_match = (incoming_content and accepted.get("content") and
                        _keyword_overlap(incoming_content, accepted["content"]) >= KEYWORD_OVERLAP_THRESHOLD)

            if title_match or kw_match:
                signal = "TITLE" if title_match else "KW"
                accepted_tier = accepted.get("source_tier", 2)
                # Tier 1 beats everything — swap if incoming is better tier
                if incoming_tier < accepted_tier:
                    print(f"[dedup:batch] {signal}_MATCH tier upgrade "
                          f"T{accepted_tier}→T{incoming_tier}: '{incoming_title[:60]}'")
                    kept[i] = article  # replace lower-tier with higher-tier
                else:
                    print(f"[dedup:batch] {signal}_MATCH dropped T{incoming_tier} "
                          f"(kept T{accepted_tier}): '{incoming_title[:60]}'")
                is_dupe = True
                break

        if is_dupe:
            dropped += 1
        else:
            kept.append(article)

    if dropped:
        print(f"[dedup:batch] {dropped} within-batch dupes dropped ({len(kept)} kept)")
    return kept


def check_published_duplicates(articles: list, window_hours: int = 48) -> list:
    """
    Filter out articles that are near-duplicates of already-published posts.

    Only compares against posts published within the last ``window_hours`` hours
    (default 48h) so the check stays fast and event-relevant.

    Two signals:
    1. Title similarity ≥ 60% — catches same-event different phrasing
    2. Keyword overlap ≥ 12 long Finnish words — catches same-event different angles
       (e.g. "Himoksen kuolema" vs "Lasketteluonnettomuus Himoksella")

    Previously used 85% title threshold which missed cross-source rewrites.
    """
    published_titles, published_contents = load_published_articles(window_hours=window_hours)
    if not published_titles:
        return articles  # nothing to compare against

    print(f"[dedup:published] comparing against {len(published_titles)} posts from last {window_hours}h")

    kept = []
    dropped = 0
    for article in articles:
        incoming_title = article.get("title", "")
        incoming_content = article.get("content", "")
        if not incoming_title:
            kept.append(article)
            continue

        # Check 1: title similarity
        title_dupe = any(_titles_similar(incoming_title, pt) for pt in published_titles)
        if title_dupe:
            print(f"[dedup:published] TITLE_MATCH (window={window_hours}h): '{incoming_title[:60]}'")
            dropped += 1
            continue

        # Check 2: keyword overlap (only if we have content to compare)
        if incoming_content:
            kw_dupe = any(
                _keyword_overlap(incoming_content, pc) >= KEYWORD_OVERLAP_THRESHOLD
                for pc in published_contents
            )
            if kw_dupe:
                print(f"[dedup:published] KW_MATCH (window={window_hours}h): '{incoming_title[:60]}'")
                dropped += 1
                continue

        kept.append(article)

    if dropped:
        print(f"[dedup:published] {dropped} articles dropped ({len(kept)} kept)")
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
    fingerprint_cutoff = (datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)).isoformat()
    url_hash_cutoff = (datetime.now(timezone.utc) - timedelta(days=URL_HASH_MAX_AGE_DAYS)).isoformat()
    fps = {k: v for k, v in fps.items() if v > fingerprint_cutoff}
    url_hashes = {k: v for k, v in url_hashes.items() if v > url_hash_cutoff}

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
