"""
RSS Scanner — fetches and deduplicates Finnish news from public RSS feeds.
Uses only stdlib (no feedparser dependency).
"""

import difflib
import hashlib
import json
import os
import re
import time
import xml.etree.ElementTree as ET
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import List, Dict, Optional
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse, parse_qs, urlunparse

RSS_FEEDS = [
    # Interleaved Finnish + international — ensures international feeds aren't
    # all at the end of a timeout window. Order: high-priority first, then alternate.

    # Tier 1: Core Finnish news (fast, high volume)
    {
        "name": "Yle Uutiset",
        "url": "https://feeds.yle.fi/uutiset/v1/recent.rss?publisherIds=YLE_UUTISET",
        "language": "fi",
    },
    {
        "name": "BBC World",
        "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
        "language": "en",
    },
    {
        "name": "Iltalehti",
        "url": "https://www.iltalehti.fi/rss/uutiset.xml",
        "language": "fi",
    },
    {
        "name": "The Guardian World",
        "url": "https://www.theguardian.com/world/rss",
        "language": "en",
    },
    {
        "name": "Ilta-Sanomat",
        "url": "https://www.is.fi/rss/uutiset.xml",
        "language": "fi",
    },
    {
        "name": "BBC Science",
        "url": "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
        "language": "en",
        "category_hint": "Tiede",
    },
    {
        "name": "Kauppalehti",
        "url": "https://feeds.kauppalehti.fi/rss/main",
        "language": "fi",
        "category_hint": "Talous",
    },
    {
        "name": "TechCrunch",
        "url": "https://techcrunch.com/feed/",
        "language": "en",
        "category_hint": "Teknologia",
    },
    {
        "name": "Taloussanomat",
        "url": "https://www.is.fi/rss/taloussanomat.xml",
        "language": "fi",
        "category_hint": "Talous",
    },
    {
        "name": "Ars Technica",
        "url": "https://feeds.arstechnica.com/arstechnica/index",
        "language": "en",
        "category_hint": "Teknologia",
    },

    # Tier 2: Finnish specialized
    {
        "name": "Yle Urheilu",
        "url": "https://feeds.yle.fi/uutiset/v1/recent.rss?publisherIds=YLE_URHEILU",
        "language": "fi",
        "category_hint": "Urheilu",
    },
    {
        "name": "Hacker News Best",
        "url": "https://hnrss.org/best",
        "language": "en",
        "category_hint": "Teknologia",
    },
    {
        "name": "IS Urheilu",
        "url": "https://www.is.fi/rss/urheilu.xml",
        "language": "fi",
        "category_hint": "Urheilu",
    },
    {
        "name": "BBC Technology",
        "url": "https://feeds.bbci.co.uk/news/technology/rss.xml",
        "language": "en",
        "category_hint": "Teknologia",
    },
    {
        "name": "Yle Teknologia",
        "url": "https://feeds.yle.fi/uutiset/v1/recent.rss?publisherIds=YLE_UUTISET&concepts=18-85",
        "language": "fi",
        "category_hint": "Teknologia",
    },
    {
        "name": "Der Spiegel International",
        "url": "https://www.spiegel.de/international/index.rss",
        "language": "en",
    },
    {
        "name": "Tekniikka & Talous",
        "url": "https://www.tekniikkatalous.fi/feed",
        "language": "fi",
        "category_hint": "Teknologia",
    },
    {
        "name": "Science News",
        "url": "https://www.sciencenews.org/feed",
        "language": "en",
        "category_hint": "Tiede",
    },
    {
        "name": "Yle Tiede",
        "url": "https://feeds.yle.fi/uutiset/v1/recent.rss?publisherIds=YLE_UUTISET&concepts=18-819",
        "language": "fi",
        "category_hint": "Tiede",
    },
    {
        "name": "Turun Sanomat",
        "url": "https://www.ts.fi/rss.xml",
        "language": "fi",
    },
    {
        "name": "Yle Kulttuuri",
        "url": "https://feeds.yle.fi/uutiset/v1/recent.rss?publisherIds=YLE_UUTISET&concepts=18-3",
        "language": "fi",
        "category_hint": "Kulttuuri",
    },

    # Disabled — confirmed broken (kept for reference)
    {
        "name": "AP News",
        "url": "https://rsshub.app/apnews/topics/world-news",
        "language": "en",
        "disabled": True,  # 403 consistently
    },
    {
        "name": "HS Tiede",
        "url": "https://www.hs.fi/rss/?section=fi-tiede",
        "language": "fi",
        "category_hint": "Tiede",
        "disabled": True,  # HS returns HTML (paywall/Next.js), not RSS
    },
    {
        "name": "Kauppalehti Markets",
        "url": "https://www.kauppalehti.fi/rss",
        "language": "fi",
        "category_hint": "Talous",
        "disabled": True,  # returns malformed XML (non-RSS endpoint)
    },
    {
        "name": "HS Kulttuuri",
        "url": "https://www.hs.fi/rss/?section=fi-kulttuuri",
        "language": "fi",
        "category_hint": "Kulttuuri",
        "disabled": True,  # HS returns HTML (paywall/Next.js), not RSS
    },
]

HEADERS = {
    "User-Agent": "Uutistenlukija/1.0 (news aggregator; +https://uutistenlukija.fi)"
}

# Politeness: minimum seconds between requests to the same domain
# 5s is still polite for different domains; most feeds are on separate domains
DOMAIN_DELAY = 5

# Hard cap on total scanner wall-clock time (seconds)
# Previously 120s — raised to 180s now that pipeline runs every 10min (not 3h),
# giving more budget per scan. 21 active feeds * ~5s avg = 105s happy path;
# 180s leaves buffer for slow feeds.
SCANNER_TIMEOUT = 180

# Per-domain last-fetch timestamps (in-process only)
_domain_last_fetch: Dict[str, float] = {}


def _domain(url: str) -> str:
    return urlparse(url).netloc


def _clean_html(text: str) -> str:
    """Strip HTML tags from text."""
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", text).strip()


def _parse_rss_date(date_str: str) -> Optional[datetime]:
    """Parse RSS date string."""
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        pass
    # Try ISO format
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except Exception:
        pass
    return None


_STRIP_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source",
}


def _normalize_url(url: str) -> str:
    """Strip tracking params and normalize URL for dedup."""
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        path = parsed.path
        if path != "/" and path.endswith("/"):
            path = path[:-1]
        query_pairs = []
        for k, vs in parse_qs(parsed.query, keep_blank_values=True).items():
            if k not in _STRIP_PARAMS:
                for v in vs:
                    query_pairs.append(f"{k}={v}")
        query = "&".join(sorted(query_pairs))
        return urlunparse((parsed.scheme, host, path, parsed.params, query, ""))
    except Exception:
        return url.lower().strip()


def _url_hash(url: str) -> str:
    return hashlib.sha256(_normalize_url(url).encode()).hexdigest()


def _fingerprint(title: str) -> str:
    """Create a simple fingerprint for dedup."""
    normalized = re.sub(r"[^a-zäöå0-9 ]", "", title.lower().strip())
    words = sorted(set(normalized.split()))
    return hashlib.md5(" ".join(words).encode()).hexdigest()


def _normalize_title(title: str) -> str:
    """Normalize title for fuzzy comparison."""
    return re.sub(r"[^a-zäöå0-9 ]", "", title.lower().strip())


_SLOP_TITLE_PATTERNS = [
    # Clickbait trigger words
    r"\buskomatton?a?\b",
    r"\bhämmästyttävä\b",
    r"tämä muuttaa kaiken",
    r"\bet usko\b",
    r"katso video",
    r"\bshokki\b",
    r"\bklikkaa\b",
    r"voitko arvata",
    r"salaisuus paljastuu",
    r"nämä \d+ (vinkkiä|tapaa|syytä|asiaa)",  # listicle
    r"top \d+ ",
    # Promotional / non-editorial
    r"\bmainos\b",
    r"\bsponsoro\w+\b",
    r"\bpr-\w+\b",
    r"tilaa (uutiskirje|newsletter)",
    r"lataa (app|sovellus)",
    r"kasinopeli",
    r"\bkasinot?\b",
    r"vedonlyönti",
    r"netticasino",
    r"ilmaiset (spinnit|kierrokset|pelit)",
    # Erotic / tabloid junk
    r"\bsexi?\b.{0,20}\bvideo\b",
    # RSS feed artifacts — boilerplate titles
    r"^(Uutiset|Etusivu|Ajankohtaista|RSS|Feed|Comments)$",
]

_SLOP_TITLE_RE = re.compile(
    "|".join(_SLOP_TITLE_PATTERNS),
    re.IGNORECASE,
)

_SLOP_DESC_PATTERNS = [
    r"(kasinot?|netticasino|vedonlyönti|pokeri|\bslot\b)",
    r"(affiliate|kumppanilink|sponsoroitu sisältö)",
    r"(as an ai language model|i'm an ai|olen tekoäly)",  # LLM leak
    r"tämä artikkeli on (generoitu|tuotettu tekoälyllä)",
]

_SLOP_DESC_RE = re.compile(
    "|".join(_SLOP_DESC_PATTERNS),
    re.IGNORECASE,
)


def _pre_filter_slop(articles: List[Dict]) -> List[Dict]:
    """Drop articles that are clearly promotional, clickbait, or feed artifacts.

    Runs before fuzzy-dedup and rewrite so we don't burn API tokens on junk.
    Returns (kept, dropped_count).
    """
    kept = []
    dropped = 0
    for article in articles:
        title = article.get("title", "")
        desc = article.get("description", "")

        # Title must be at least 10 chars — likely a feed artifact otherwise
        if len(title.strip()) < 10:
            print(f"[scanner] slop-filter (short title): {title!r}")
            dropped += 1
            continue

        if _SLOP_TITLE_RE.search(title):
            print(f"[scanner] slop-filter (title pattern): {title!r}")
            dropped += 1
            continue

        if desc and _SLOP_DESC_RE.search(desc):
            print(f"[scanner] slop-filter (desc pattern): {title!r}")
            dropped += 1
            continue

        kept.append(article)

    if dropped:
        print(f"[scanner] Pre-filter: {len(articles)} → {len(kept)} ({dropped} slop dropped)")
    return kept


def _fuzzy_dedup(articles: List[Dict], threshold: float = 0.85) -> List[Dict]:
    """Remove near-duplicate articles (>threshold title similarity).
    
    Keeps the article with the most complete description (longest).
    O(n²) but n is bounded ~500 articles per run — fine.
    """
    kept = []
    dropped = set()  # indices into articles list

    for i, a in enumerate(articles):
        if i in dropped:
            continue
        title_a = _normalize_title(a.get("title", ""))
        for j, b in enumerate(articles):
            if j <= i or j in dropped:
                continue
            title_b = _normalize_title(b.get("title", ""))
            ratio = difflib.SequenceMatcher(None, title_a, title_b).ratio()
            if ratio >= threshold:
                # Keep the one with longer description (more content)
                if len(b.get("description", "")) > len(a.get("description", "")):
                    dropped.add(i)
                    break
                else:
                    dropped.add(j)
        if i not in dropped:
            kept.append(a)

    return kept


def _get_text(element, tag: str) -> str:
    """Safely get text from an XML element."""
    child = element.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    return ""


def fetch_feed(feed_info: dict) -> List[Dict]:
    """Fetch and parse a single RSS feed with politeness."""
    articles = []
    url = feed_info["url"]
    try:
        # Domain politeness: enforce minimum delay between same-domain requests
        domain = _domain(url)
        now = time.monotonic()
        last = _domain_last_fetch.get(domain, 0)
        wait = DOMAIN_DELAY - (now - last)
        if wait > 0:
            time.sleep(wait)
        _domain_last_fetch[domain] = time.monotonic()

        req = urllib.request.Request(url, headers=dict(HEADERS))
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read()
        
        # Sanitize content: strip control characters that break ET parser
        content = re.sub(rb'[\x00-\x08\x0b\x0c\x0e-\x1f]', b'', content)
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            # Try decoding as latin-1 then re-encoding to utf-8 as fallback
            content = content.decode("latin-1", errors="replace").encode("utf-8", errors="replace")
            content = re.sub(rb'[\x00-\x08\x0b\x0c\x0e-\x1f]', b'', content)
            root = ET.fromstring(content)
        
        # Handle both RSS 2.0 and Atom feeds
        items = root.findall(".//item")
        if not items:
            # Try Atom format
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            items = root.findall(".//atom:entry", ns)
        
        for item in items[:30]:
            title = _clean_html(_get_text(item, "title"))
            if not title:
                continue
            
            description = _clean_html(
                _get_text(item, "description") or _get_text(item, "summary")
            )
            
            link = _get_text(item, "link")
            if not link:
                link_el = item.find("link")
                if link_el is not None:
                    link = link_el.get("href", "")
            
            date_str = (
                _get_text(item, "pubDate") or 
                _get_text(item, "published") or
                _get_text(item, "updated")
            )
            pub_date = _parse_rss_date(date_str) or datetime.now(timezone.utc)
            
            articles.append({
                "title": title,
                "description": description[:500],
                "link": link,
                "published": pub_date.isoformat(),
                "source": feed_info["name"],
                "language": feed_info.get("language", "fi"),
                "fingerprint": _fingerprint(title),
                "_url_hash": _url_hash(link),
                **({"category_hint": feed_info["category_hint"]} if feed_info.get("category_hint") else {}),
            })
    except Exception as e:
        print(f"[scanner] Error fetching {feed_info['name']}: {e}")

    return articles


def scan_all_feeds() -> List[Dict]:
    """Scan all configured RSS feeds, deduplicate, return top articles.

    Stops fetching new feeds after SCANNER_TIMEOUT seconds to keep pipeline
    running even when many feeds are slow.
    """
    all_articles = []
    scan_start = time.monotonic()
    feeds_fetched = 0
    feeds_skipped = 0

    for feed in RSS_FEEDS:
        if feed.get("disabled"):
            continue

        elapsed = time.monotonic() - scan_start
        if elapsed >= SCANNER_TIMEOUT:
            feeds_skipped += 1
            print(f"[scanner] ⏱ Timeout ({SCANNER_TIMEOUT}s) — skipping remaining feeds ({feeds_skipped} total skipped)")
            break

        print(f"[scanner] Fetching {feed['name']}...")
        articles = fetch_feed(feed)
        print(f"[scanner]   → {len(articles)} articles")
        all_articles.extend(articles)
        feeds_fetched += 1

    # Count remaining skipped feeds
    active_feeds = [f for f in RSS_FEEDS if not f.get("disabled")]
    if feeds_skipped == 0 and feeds_fetched < len(active_feeds):
        feeds_skipped = len(active_feeds) - feeds_fetched

    total_scan_time = time.monotonic() - scan_start
    print(f"[scanner] Scan complete: {feeds_fetched} feeds in {total_scan_time:.1f}s "
          f"({feeds_skipped} skipped due to timeout)")

    # Exact dedup by fingerprint
    seen = set()
    unique = []
    for article in all_articles:
        fp = article["fingerprint"]
        if fp not in seen:
            seen.add(fp)
            unique.append(article)

    # Pre-filter: drop slop/promotional/artifact titles before burning rewrite tokens
    unique = _pre_filter_slop(unique)

    # Fuzzy dedup: drop near-duplicate titles (>85% similarity)
    before_fuzzy = len(unique)
    unique = _fuzzy_dedup(unique, threshold=0.85)
    print(f"[scanner] Fuzzy dedup: {before_fuzzy} → {len(unique)} (dropped {before_fuzzy - len(unique)} near-dupes)")

    # Detect trending: articles with similar fingerprints from multiple sources
    fp_sources = {}
    for article in all_articles:
        fp = article["fingerprint"]
        source = article["source"]
        if fp not in fp_sources:
            fp_sources[fp] = set()
        fp_sources[fp].add(source)

    # Mark articles as trending if covered by 2+ sources
    trending_fps = {fp for fp, sources in fp_sources.items() if len(sources) >= 2}
    for article in unique:
        article["trending"] = article["fingerprint"] in trending_fps

    trending_count = sum(1 for a in unique if a.get("trending"))
    print(f"[scanner] Trending stories: {trending_count}")

    # Sort by date (newest first)
    unique.sort(key=lambda a: a["published"], reverse=True)

    # Category-aware selection with target distribution
    CATEGORIES = ["Kotimaa", "Ulkomaat", "Talous", "Teknologia", "Urheilu", "Kulttuuri", "Tiede"]
    CATEGORY_KEYWORDS = {
        "Urheilu": ["urheilu", "sport", "liiga", "olymp", "jalkapallo", "jääkiekko", "f1", "formula", "tennis", "golf"],
        "Tiede": ["tiede", "tutkimus", "science", "research", "ilmasto", "avaruus", "terveys", "health"],
        "Kulttuuri": ["kulttuuri", "taide", "musiikk", "elokuva", "teatteri", "kirja", "culture", "art", "music"],
        "Teknologia": ["teknologia", "tech", "ai", "tekoäly", "ohjelmisto", "cyber", "digital", "apple", "google", "microsoft"],
        "Talous": ["talous", "ekonom", "osake", "pörssi", "business", "economy", "market", "finance", "kauppa"],
        "Ulkomaat": ["ulkomaa", "world", "international", "usa", "eu ", "eurooppa", "kiina", "venäjä", "nato"],
        "Kotimaa": ["suomi", "helsinki", "tampere", "turku", "eduskunta", "hallitus"],
    }

    # Target distribution (must sum to 1.0)
    CATEGORY_TARGETS = {
        "Kotimaa":    0.25,
        "Ulkomaat":   0.20,
        "Talous":     0.20,
        "Teknologia": 0.15,
        "Urheilu":    0.10,
        "Kulttuuri":  0.07,
        "Tiede":      0.03,
    }

    TOTAL_TARGET = 25

    # Compute per-category quotas (minimum 1 per category regardless of %)
    import math
    cat_quotas = {}
    for cat in CATEGORIES:
        raw = CATEGORY_TARGETS[cat] * TOTAL_TARGET
        cat_quotas[cat] = max(1, round(raw))
    # Adjust rounding drift to hit exactly TOTAL_TARGET
    while sum(cat_quotas.values()) > TOTAL_TARGET:
        # Trim from the category most over its raw target
        worst = max(CATEGORIES, key=lambda c: cat_quotas[c] - CATEGORY_TARGETS[c] * TOTAL_TARGET)
        if cat_quotas[worst] > 1:
            cat_quotas[worst] -= 1
    while sum(cat_quotas.values()) < TOTAL_TARGET:
        # Add to category most under its raw target
        best = max(CATEGORIES, key=lambda c: CATEGORY_TARGETS[c] * TOTAL_TARGET - cat_quotas[c])
        cat_quotas[best] += 1

    def _guess_category(article):
        """Guess category from source hint, title, or description."""
        hint = article.get("category_hint", "")
        if hint in CATEGORIES:
            return hint
        text = (article.get("title", "") + " " + article.get("description", "")).lower()
        for cat, keywords in CATEGORY_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                return cat
        # English sources default to Ulkomaat
        if article.get("language") == "en":
            return "Ulkomaat"
        return "Kotimaa"

    # Pre-classify all unique articles
    for article in unique:
        article["_guessed_category"] = _guess_category(article)

    # Build per-category pools (newest first)
    cat_pools: Dict[str, list] = {c: [] for c in CATEGORIES}
    for article in unique:
        cat_pools[article["_guessed_category"]].append(article)

    # Fill quotas from each category pool
    selected = []
    selected_fps: set = set()
    cat_counts = {c: 0 for c in CATEGORIES}

    for cat in CATEGORIES:
        quota = cat_quotas[cat]
        taken = 0
        for article in cat_pools[cat]:
            if taken >= quota:
                break
            if article["fingerprint"] not in selected_fps:
                selected.append(article)
                selected_fps.add(article["fingerprint"])
                cat_counts[cat] += 1
                taken += 1

    # If any category was short (not enough articles), fill remaining slots
    # from whichever categories have surplus, newest first
    if len(selected) < TOTAL_TARGET:
        remaining_budget = {c: cat_quotas[c] - cat_counts[c] for c in CATEGORIES}
        # Allow overflow into categories that already hit quota
        for article in unique:
            if len(selected) >= TOTAL_TARGET:
                break
            if article["fingerprint"] not in selected_fps:
                cat = article["_guessed_category"]
                selected.append(article)
                selected_fps.add(article["fingerprint"])
                cat_counts[cat] += 1

    print(f"[scanner] Quotas: {cat_quotas}")
    print(f"[scanner] Category distribution: {cat_counts}")
    print(f"[scanner] Total: {len(all_articles)} → Unique: {len(unique)} → Selected: {len(selected)}")
    return selected


if __name__ == "__main__":
    import json
    articles = scan_all_feeds()
    print(json.dumps(articles, indent=2, ensure_ascii=False))
