"""
RSS Scanner — fetches and deduplicates Finnish news from public RSS feeds.
Uses only stdlib (no feedparser dependency).
"""

import difflib
import hashlib
import html as html_module
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

try:
    from feed_health import get_global_health, save_global_health
    _FEED_HEALTH_AVAILABLE = True
except ImportError:
    _FEED_HEALTH_AVAILABLE = False
    def get_global_health(): return None  # noqa: E731
    def save_global_health(): pass  # noqa: E731

# Source trust tiers — controls deletion protection and rewriter fact-anchoring.
#
# Tier 1 (PROTECTED): Editorial fact-checking standards. Articles from these
#   sources CANNOT be auto-deleted — require manual review. Rewriter does not
#   expand facts beyond what the source provides.
# Tier 2 (STANDARD): Major outlets with editorial standards but not in Tier 1.
#   Normal pipeline rules apply.
# Tier 3 (VERIFY): Aggregators, smaller sites, single-source stories. Pipeline
#   logs a warning when an article's only source is Tier 3.

SOURCE_TRUST_TIERS: dict[str, int] = {
    # ── Tier 1: Finnish public media ──────────────────────────────────────────
    "Yle Uutiset":       1,
    "Yle Urheilu":       1,
    "Yle Teknologia":    1,
    "Yle Tiede":         1,
    "Yle Kulttuuri":     1,
    # ── Tier 1: Major Finnish dailies ─────────────────────────────────────────
    "Helsingin Sanomat": 1,
    "HS Tiede":          1,
    "HS Kulttuuri":      1,
    "Turun Sanomat":     1,
    "HS Tuoreimmat":    1,
    "Kauppalehti":       1,
    "Kauppalehti Markets": 1,
    "Kauppalehti KL-Nyt": 1,
    "Ilta-Sanomat":      1,
    "IS Urheilu":        1,
    "Taloussanomat":     1,
    "Iltalehti":         1,
    "MTV Uutiset":       1,
    # ── Tier 1: International wire services / broadcasters ────────────────────
    "BBC World":         1,
    "BBC Science":       1,
    "BBC Technology":    1,
    "Reuters World":     1,
    "AP News":           1,
    # ── Tier 2: Standard major outlets ───────────────────────────────────────
    "The Guardian World": 2,
    "The Guardian":       2,
    "Der Spiegel International": 2,
    "Tekniikka & Talous": 2,
    "TechCrunch":         2,
    "Ars Technica":       2,
    "Science News":       2,
    "Etelä-Suomen Sanomat": 2,
    "Lääkärilehti":       2,
    "Suomen Yrittäjät":   2,
    "Teknavi":            2,
    # ── Tier 3: Aggregators / smaller sites ──────────────────────────────────
    "Hacker News Best":   3,
}

# Convenience sets derived from the dict above
TIER1_SOURCES = frozenset(k for k, v in SOURCE_TRUST_TIERS.items() if v == 1)
TIER2_SOURCES = frozenset(k for k, v in SOURCE_TRUST_TIERS.items() if v == 2)
TIER3_SOURCES = frozenset(k for k, v in SOURCE_TRUST_TIERS.items() if v == 3)

def get_source_tier(feed_name: str) -> int:
    """Return trust tier (1/2/3) for a feed. Unknown feeds default to 2."""
    return SOURCE_TRUST_TIERS.get(feed_name, 2)

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
        "disabled": True,  # 2026-03-27: Tiede should be Finnish-language sources
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
        "name": "Kauppalehti KL-Nyt",
        "url": "https://feeds.kauppalehti.fi/rss/klnyt",
        "language": "fi",
        "category_hint": "Talous",
    },
    {
        "name": "Suomen Yrittäjät",
        "url": "https://www.yrittajat.fi/feed/?post_type=news&tax-organization=suomen-yrittajat",
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
        "name": "Jatkoaika.com",
        "url": "https://jatkoaika.com/rss/index.rss",
        "language": "fi",
        "category_hint": "Urheilu",
    },
    {
        "name": "BBC Technology",
        "url": "https://feeds.bbci.co.uk/news/technology/rss.xml",
        "language": "en",
        "category_hint": "Teknologia",
        "disabled": True,  # 2026-03-27: Teknologia should be Finnish-language sources
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
        "disabled": True,  # 8 days stale 2026-03-27, no new content passing dedup
    },
    {
        "name": "Tekniikka & Talous",
        "url": "https://www.tekniikkatalous.fi/api/feed/v2/rss/tt",  # updated URL 2026-03-26
        "language": "fi",
        "category_hint": "Teknologia",
    },
    {
        "name": "Tivi",
        "url": "https://www.tivi.fi/feed/",
        "language": "fi",
        # No category_hint — tivi.fi content is mixed (tech, lifestyle, general);
        # let the rewriter classify per article
    },
    {
        "name": "io-tech.fi",
        "url": "https://www.io-tech.fi/feed/rss/",
        "language": "fi",
        "category_hint": "Teknologia",
    },
    {
        "name": "Teknavi",
        "url": "https://teknavi.fi/feed/",
        "language": "fi",
        "category_hint": "Teknologia",  # Finnish consumer tech (phones, gadgets, Apple/Samsung)
    },
    {
        "name": "mobiili.fi",
        "url": "https://mobiili.fi/feed/",
        "language": "fi",
        "category_hint": "Teknologia",
    },
    {
        "name": "muropaketti.com",
        "url": "https://muropaketti.com/feed/",
        "language": "fi",
        "category_hint": "Teknologia",
    },
    {
        "name": "IS Digitoday",
        "url": "https://www.is.fi/rss/digitoday.xml",
        "language": "fi",
        "category_hint": "Teknologia",
    },
    {
        "name": "MTV Uutiset",
        "url": "https://www.mtvuutiset.fi/api/feed/rss/uutiset_uusimmat",
        "language": "fi",
        "category_hint": "Kotimaa",
    },
    {
        "name": "Maaseudun Tulevaisuus",
        "url": "https://www.maaseuduntulevaisuus.fi/feeds/maaseuduntulevaisuus",
        "language": "fi",
        "category_hint": "Kotimaa",
    },
    {
        "name": "Etelä-Suomen Sanomat",
        "url": "https://www.ess.fi/feed/rss/",
        "language": "fi",
        "category_hint": "Kotimaa",
    },
    {
        "name": "Lääkärilehti",
        "url": "http://www.laakarilehti.fi/?rss=1",
        "language": "fi",
        "category_hint": "Tiede",
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
        "name": "THL",
        "url": "https://thl.fi/ajankohtaista/-/asset_publisher/m8s4MMkgtyYg/rss",
        "language": "fi",
        "category_hint": "Tiede",
    },
    {
        "name": "Turun Sanomat",
        "url": "https://www.ts.fi/rss.xml",
        "language": "fi",
        "disabled": True,  # Paywall — rewriter fabricates from partial RSS content
    },
    {
        "name": "HS Tuoreimmat",
        "url": "https://www.hs.fi/rss/tuoreimmat.xml",
        "language": "fi",
        "category_hint": "Uutiset",  # General HS feed - paywall-free RSS endpoint
    },
    {
        "name": "Yle Kulttuuri",
        "url": "https://feeds.yle.fi/uutiset/v1/recent.rss?publisherIds=YLE_UUTISET&concepts=18-150067",
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

# Domains blocked from publication — product pages, SEO farms, non-Finnish aggregators, etc.
# Two-layer defense: these are also excluded in Firehose rules where possible.
BLOCKED_SOURCE_DOMAINS = frozenset({
    "scoop.it",
    "ecoonline.com",
    "7sun.fi",
    "bandilanews.com",
    "itbranschen.com",
    "kelikamerat.info",
    "listafriikki.com",
    "listamaailma.fi",
    "nauvolaiset.fi",
    "menejatieda.fi",
    "ilmastoviisas.fi",
    "destia.fi",
    "voice.fi",
    "uutiskaista.com",
    "tieteentekijat.fi",
    "koneensaatio.fi",
    "etappi.com",
    "shpilotech.com",   # Chinese lab equipment, non-Finnish product pages (2026-03-27)
})

# Politeness: minimum seconds between requests to the same domain
# 5s is still polite for different domains; most feeds are on separate domains
DOMAIN_DELAY = 5

# Hard cap on total scanner wall-clock time (seconds)
# Previously 120s — raised to 180s now that pipeline runs every 10min (not 3h),
# giving more budget per scan. 21 active feeds * ~5s avg = 105s happy path;
# 180s leaves buffer for slow feeds.
SCANNER_TIMEOUT = 180

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
    """Strip HTML tags and decode HTML entities from text."""
    if not text:
        return ""
    # Decode entities first (e.g. Guardian desc: &lt;p&gt;text&lt;/p&gt;)
    text = html_module.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s{2,}", " ", text).strip()


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


# URL path → category hint mapping for generic feeds (IS, IL, etc.)
# These feeds publish all sections in one RSS feed without a category_hint on the
# feed config, so individual article URLs are the only structural signal available.
_URL_PATH_CATEGORY: list[tuple[str, str]] = [
    # Ilta-Sanomat: is.fi/<section>/art-...
    ("/talous/",      "Talous"),
    ("/taloussanomat/", "Talous"),
    ("/urheilu/",     "Urheilu"),
    ("/teknologia/",  "Teknologia"),
    ("/tiede/",       "Tiede"),
    ("/terveys/",     "Tiede"),
    ("/viihde/",      "Kulttuuri"),
    ("/kulttuuri/",   "Kulttuuri"),
    ("/ulkomaat/",    "Ulkomaat"),
    ("/politiikka/",  "Kotimaa"),
    ("/kotimaa/",     "Kotimaa"),
    # IS Digitoday: is.fi/digitoday/...
    ("/digitoday/",   "Teknologia"),
    # Iltalehti: iltalehti.fi/<section>/a/...
    # (same path segments, covered by patterns above)
    # Yle sub-feeds: yle.fi/uutiset/<topic> style links are numeric; handled by feed-level hints
]


def _infer_category_from_url(url: str) -> str:
    """Return a category hint inferred from the article's URL path, or empty string."""
    if not url:
        return ""
    path = url.lower().split("?")[0]  # strip query params
    for segment, category in _URL_PATH_CATEGORY:
        if segment in path:
            return category
    return ""


def _build_category_hint(feed_hint: Optional[str], article_url: str) -> dict:
    """Return a {'category_hint': ...} dict if a hint can be determined, else {}."""
    if feed_hint:
        return {"category_hint": feed_hint}
    inferred = _infer_category_from_url(article_url)
    return {"category_hint": inferred} if inferred else {}


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

        # Block known low-quality / non-Finnish domains
        link = article.get("link", "")
        if link:
            from urllib.parse import urlparse as _urlparse2
            _netloc = _urlparse2(link).netloc.lower().removeprefix("www.")
            if any(_netloc == bd or _netloc.endswith("." + bd) for bd in BLOCKED_SOURCE_DOMAINS):
                print(f"[scanner] slop-filter (blocked domain {_netloc}): {title!r}")
                dropped += 1
                continue

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
        
        # RSS namespaces for content:encoded and media
        _NS = {
            "content": "http://purl.org/rss/1.0/modules/content/",
            "dc":      "http://purl.org/dc/elements/1.1/",
            "media":   "http://search.yahoo.com/mrss/",
        }

        for item in items[:30]:
            title = _clean_html(_get_text(item, "title"))
            if not title:
                continue

            # --- Description: prefer content:encoded > description > summary ---
            # content:encoded often has full article text (valuable for paywalled sources)
            content_encoded = ""
            ce_el = item.find("content:encoded", _NS)
            if ce_el is not None and ce_el.text:
                content_encoded = _clean_html(ce_el.text)

            plain_desc = _clean_html(
                _get_text(item, "description") or _get_text(item, "summary") or ""
            )

            # Use whichever is longer (content:encoded may be full article)
            description = content_encoded if len(content_encoded) > len(plain_desc) else plain_desc

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
                "description": description[:2000],  # raised from 500 — content:encoded can be long
                "link": link,
                "published": pub_date.isoformat(),
                "source": feed_info["name"],
                "source_domain": urlparse(feed_info["url"]).netloc.removeprefix("www.").removeprefix("feeds."),
                "language": feed_info.get("language", "fi"),
                "fingerprint": _fingerprint(title),
                "_url_hash": _url_hash(link),
                "source_tier": get_source_tier(feed_info["name"]),
                **_build_category_hint(feed_info.get("category_hint"), link),
            })
    except Exception as e:
        print(f"[scanner] Error fetching {feed_info['name']}: {e}")
        # Record error in feed health tracker
        if _FEED_HEALTH_AVAILABLE:
            _h = get_global_health()
            if _h:
                code = 0
                msg = str(e)[:120]
                if isinstance(e, urllib.error.HTTPError):
                    code = e.code
                _h.record_error(feed_info["name"], code, msg)

    return articles


def _source_diversity_reorder(articles: List[Dict]) -> List[Dict]:
    """Round-robin interleave articles by source_domain.

    Groups articles by their source_domain and picks one from each group in
    turn (order within each group preserved — newest first).  This ensures
    that if Yle has 12 items and BBC has 3, we alternate Yle/BBC/Yle/BBC/...
    until BBC is exhausted, then continue with Yle — rather than serving all
    Yle first.

    Articles without a source_domain are placed in a catch-all bucket.
    """
    from collections import defaultdict, OrderedDict

    # Use an OrderedDict keyed by first-seen domain to keep deterministic order
    buckets: dict = OrderedDict()
    for article in articles:
        domain = article.get("source_domain") or "_unknown"
        if domain not in buckets:
            buckets[domain] = []
        buckets[domain].append(article)

    reordered = []
    # Round-robin until all buckets exhausted
    while any(buckets[d] for d in buckets):
        for domain in list(buckets.keys()):
            if buckets[domain]:
                reordered.append(buckets[domain].pop(0))

    return reordered


def scan_all_feeds() -> List[Dict]:
    """Scan all configured RSS feeds, deduplicate, return top articles.

    Stops fetching new feeds after SCANNER_TIMEOUT seconds to keep pipeline
    running even when many feeds are slow.
    """
    http_cache = _load_http_cache()
    all_articles = []
    scan_start = time.monotonic()
    feeds_fetched = 0
    feeds_skipped = 0

    _health = get_global_health() if _FEED_HEALTH_AVAILABLE else None

    for feed in RSS_FEEDS:
        if feed.get("disabled"):
            continue

        # Skip feeds that have been auto-disabled by feed_health
        if _health:
            _disabled, _reason = _health.is_disabled(feed["name"])
            if _disabled:
                print(f"[scanner] ⛔ {feed['name']}: auto-disabled ({_reason[:60]})")
                feeds_skipped += 1
                continue

        elapsed = time.monotonic() - scan_start
        if elapsed >= SCANNER_TIMEOUT:
            feeds_skipped += 1
            print(f"[scanner] ⏱ Timeout ({SCANNER_TIMEOUT}s) — skipping remaining feeds ({feeds_skipped} total skipped)")
            break

        print(f"[scanner] Fetching {feed['name']}...")
        prev_count = len(all_articles)
        articles = fetch_feed(feed, http_cache=http_cache)
        print(f"[scanner]   → {len(articles)} articles")
        all_articles.extend(articles)
        feeds_fetched += 1

        # Record success in health tracker
        if _health and len(all_articles) > prev_count:
            # Find newest article timestamp from this feed's batch
            newest = None
            for a in articles:
                try:
                    ts = datetime.fromisoformat(a.get("published", "").replace("Z", "+00:00"))
                    if newest is None or ts > newest:
                        newest = ts
                except (ValueError, AttributeError):
                    pass
            _health.record_success(feed["name"], newest_article_ts=newest)
        elif _health and len(all_articles) == prev_count:
            # Feed returned 0 articles but didn't error — still a "success" (304 or no new items)
            _health.record_success(feed["name"])

    # Count remaining skipped feeds
    active_feeds = [f for f in RSS_FEEDS if not f.get("disabled")]
    if feeds_skipped == 0 and feeds_fetched < len(active_feeds):
        feeds_skipped = len(active_feeds) - feeds_fetched

    total_scan_time = time.monotonic() - scan_start
    print(f"[scanner] Scan complete: {feeds_fetched} feeds in {total_scan_time:.1f}s "
          f"({feeds_skipped} skipped due to timeout)")
    _save_http_cache(http_cache)
    save_global_health()  # persist feed health state

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

    # Source diversity reorder: round-robin by source_domain so no single
    # source dominates the front of the candidate list.
    unique = _source_diversity_reorder(unique)

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

    # Batch source summary
    from collections import Counter
    source_counts = Counter(a.get("source_domain", a.get("source", "?")) for a in selected)
    source_summary = ", ".join(f"{src}({n})" for src, n in sorted(source_counts.items(), key=lambda x: -x[1]))
    print(f"[scanner] Batch sources: {source_summary}")

    return selected


if __name__ == "__main__":
    import json
    articles = scan_all_feeds()
    print(json.dumps(articles, indent=2, ensure_ascii=False))
