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
    # Finnish main sources
    {
        "name": "Yle Uutiset",
        "url": "https://feeds.yle.fi/uutiset/v1/recent.rss?publisherIds=YLE_UUTISET",
        "language": "fi",
    },
    {
        "name": "Iltalehti",
        "url": "https://www.iltalehti.fi/rss/uutiset.xml",
        "language": "fi",
    },
    {
        "name": "Ilta-Sanomat",
        "url": "https://www.is.fi/rss/uutiset.xml",
        "language": "fi",
    },
    {
        "name": "Turun Sanomat",
        "url": "https://www.ts.fi/rss.xml",
        "language": "fi",
    },
    {
        "name": "Kauppalehti",
        "url": "https://feeds.kauppalehti.fi/rss/main",
        "language": "fi",
    },
    {
        "name": "Taloussanomat",
        "url": "https://www.is.fi/rss/taloussanomat.xml",
        "language": "fi",
    },
    # Finnish specialized
    {
        "name": "Yle Urheilu",
        "url": "https://feeds.yle.fi/uutiset/v1/recent.rss?publisherIds=YLE_URHEILU",
        "language": "fi",
        "category_hint": "Urheilu",
    },
    {
        "name": "IS Urheilu",
        "url": "https://www.is.fi/rss/urheilu.xml",
        "language": "fi",
        "category_hint": "Urheilu",
    },
    {
        "name": "Tekniikka & Talous",
        "url": "https://www.tekniikkatalous.fi/feed",
        "language": "fi",
        "category_hint": "Teknologia",
    },
    {
        "name": "Yle Tiede",
        "url": "https://feeds.yle.fi/uutiset/v1/recent.rss?publisherIds=YLE_UUTISET&concepts=18-819",
        "language": "fi",
        "category_hint": "Tiede",
    },
    {
        "name": "HS Tiede",
        "url": "https://www.hs.fi/rss/?section=fi-tiede",
        "language": "fi",
        "category_hint": "Tiede",
        "disabled": True,  # HS returns HTML (paywall/Next.js), not RSS
    },
    {
        "name": "Yle Teknologia",
        "url": "https://feeds.yle.fi/uutiset/v1/recent.rss?publisherIds=YLE_UUTISET&concepts=18-85",
        "language": "fi",
        "category_hint": "Teknologia",
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
    {
        "name": "Yle Kulttuuri",
        "url": "https://feeds.yle.fi/uutiset/v1/recent.rss?publisherIds=YLE_UUTISET&concepts=18-3",
        "language": "fi",
        "category_hint": "Kulttuuri",
    },
    # International sources
    {
        "name": "BBC World",
        "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
        "language": "en",
    },
    {
        "name": "BBC Technology",
        "url": "https://feeds.bbci.co.uk/news/technology/rss.xml",
        "language": "en",
    },
    {
        "name": "BBC Science",
        "url": "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
        "language": "en",
    },
    {
        "name": "AP News",
        "url": "https://rsshub.app/apnews/topics/world-news",
        "language": "en",
        "disabled": True,  # 403 consistently
    },
    {
        "name": "The Guardian World",
        "url": "https://www.theguardian.com/world/rss",
        "language": "en",
    },
    {
        "name": "TechCrunch",
        "url": "https://techcrunch.com/feed/",
        "language": "en",
    },
    {
        "name": "Ars Technica",
        "url": "https://feeds.arstechnica.com/arstechnica/index",
        "language": "en",
    },
    {
        "name": "Hacker News Best",
        "url": "https://hnrss.org/best",
        "language": "en",
    },
    {
        "name": "Der Spiegel International",
        "url": "https://www.spiegel.de/international/index.rss",
        "language": "en",
    },
]

HEADERS = {
    "User-Agent": "Uutistenlukija/1.0 (news aggregator; +https://uutistenlukija.fi)"
}

# Politeness: minimum seconds between requests to the same domain
DOMAIN_DELAY = 30

# ETag/Last-Modified cache file (persists between pipeline runs)
_CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
_HTTP_CACHE_FILE = os.path.join(_CACHE_DIR, "feed_http_cache.json")

# Per-domain last-fetch timestamps (in-process only)
_domain_last_fetch: Dict[str, float] = {}


def _load_http_cache() -> Dict:
    """Load persisted ETag/Last-Modified cache."""
    try:
        with open(_HTTP_CACHE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_http_cache(cache: Dict) -> None:
    """Persist ETag/Last-Modified cache to disk."""
    os.makedirs(_CACHE_DIR, exist_ok=True)
    with open(_HTTP_CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


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


def fetch_feed(feed_info: dict, http_cache: Optional[Dict] = None) -> List[Dict]:
    """Fetch and parse a single RSS feed with politeness and 304 caching."""
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

        # Build request with conditional headers for 304 support
        headers = dict(HEADERS)
        cache_entry = (http_cache or {}).get(url, {})
        if cache_entry.get("etag"):
            headers["If-None-Match"] = cache_entry["etag"]
        if cache_entry.get("last_modified"):
            headers["If-Modified-Since"] = cache_entry["last_modified"]

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                content = resp.read()
                # Update cache with new validators
                if http_cache is not None:
                    new_entry = {}
                    etag = resp.headers.get("ETag")
                    lm = resp.headers.get("Last-Modified")
                    if etag:
                        new_entry["etag"] = etag
                    if lm:
                        new_entry["last_modified"] = lm
                    if new_entry:
                        http_cache[url] = new_entry
        except urllib.error.HTTPError as e:
            if e.code == 304:
                # Not Modified — return empty, caller uses cached articles
                return []
            raise
        
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
    """Scan all configured RSS feeds, deduplicate, return top articles."""
    http_cache = _load_http_cache()
    all_articles = []
    for feed in RSS_FEEDS:
        if feed.get("disabled"):
            continue
        print(f"[scanner] Fetching {feed['name']}...")
        articles = fetch_feed(feed, http_cache=http_cache)
        print(f"[scanner]   → {len(articles)} articles")
        all_articles.extend(articles)
    _save_http_cache(http_cache)

    # Exact dedup by fingerprint
    seen = set()
    unique = []
    for article in all_articles:
        fp = article["fingerprint"]
        if fp not in seen:
            seen.add(fp)
            unique.append(article)

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

    # Category-aware selection: ensure all 7 categories get representation
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

    # First pass: pick at least 1 article per category
    selected = []
    selected_fps = set()
    for cat in CATEGORIES:
        for article in unique:
            if article["fingerprint"] not in selected_fps and _guess_category(article) == cat:
                article["_guessed_category"] = cat
                selected.append(article)
                selected_fps.add(article["fingerprint"])
                break

    # Second pass: fill remaining slots with newest articles, balanced by category
    # Track how many we've selected per category
    cat_counts = {c: sum(1 for a in selected if a.get("_guessed_category") == c) for c in CATEGORIES}
    target = 25
    
    for article in unique:
        if len(selected) >= target:
            break
        if article["fingerprint"] not in selected_fps:
            cat = _guess_category(article)
            # Prefer underrepresented categories
            article["_guessed_category"] = cat
            selected.append(article)
            selected_fps.add(article["fingerprint"])
            cat_counts[cat] = cat_counts.get(cat, 0) + 1

    print(f"[scanner] Category distribution: {cat_counts}")
    print(f"[scanner] Total: {len(all_articles)} → Unique: {len(unique)} → Selected: {len(selected)}")
    return selected


if __name__ == "__main__":
    import json
    articles = scan_all_feeds()
    print(json.dumps(articles, indent=2, ensure_ascii=False))
