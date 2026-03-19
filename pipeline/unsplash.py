"""
Unsplash image fetcher for article featured images.

Uses Unsplash Source API (free, no key needed for direct URLs)
and Unsplash API for proper search + attribution metadata.

Priority:
  1. Unsplash search (UNSPLASH_ACCESS_KEY env var required for search API)
  2. Unsplash Source random-by-keyword (free, no key, no attribution metadata)
  3. Return None → caller falls back to category placeholder

Rate limits (free tier):
  - Search API: 50 req/hr
  - Source API: no hard limit but be polite
"""

import os
import re
import json
import time
import urllib.request
import urllib.parse
from typing import Optional, Dict, Tuple

UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")
UNSPLASH_SEARCH_URL = "https://api.unsplash.com/search/photos"
UNSPLASH_SOURCE_URL = "https://source.unsplash.com"

# Finnish stopwords + generic words to strip before querying Unsplash
_FI_STOPWORDS = {
    "ja", "tai", "on", "ei", "se", "hän", "he", "me", "te", "olla", "oli",
    "että", "kun", "jos", "niin", "jo", "vain", "myös", "sekä", "mutta",
    "kuin", "mikä", "miksi", "missä", "miten", "kuinka", "joka", "jotka",
    "uusi", "uuden", "uutta", "uudet", "uusia",
    "koko", "kaikki", "yksi", "kaksi", "kolme", "neljä", "viisi",
    "suuri", "pieni", "iso", "vuosi", "vuoden", "vuotta",
    "yli", "alle", "noin", "lähes", "noin", "enää",
    "sanoo", "kertoo", "mukaan", "mukana", "jälkeen", "ennen",
    "suomi", "suomen", "suomessa", "suomalais", "suomalainen",  # too generic for image search
    "voitti", "voittaa", "voitti", "hävis", "julkaisi", "kertoo", "sanoo", "ilmoitti",  # verbs, not useful for image search
    "uutiset", "lehti", "media",
}

# EN translations for key Finnish category-specific terms (Unsplash works in EN)
_FI_TO_EN = {
    "hallitus": "government",
    "eduskunta": "parliament",
    "poliisi": "police",
    "pörssi": "stock market",
    "talous": "economy",
    "teknologia": "technology",
    "tekoäly": "artificial intelligence",
    "urheilu": "sports",
    "jalkapallo": "football",
    "jääkiekko": "ice hockey",
    "jääkiekon": "ice hockey",
    "jääkiekossa": "ice hockey",
    "tiede": "science",
    "tutkimus": "research",
    "ilmasto": "climate",
    "kulttuuri": "culture",
    "musiikki": "music",
    "elokuva": "film",
    "sota": "war",
    "kriisi": "crisis",
    "vaali": "election",
    "presidentin": "president",
    "ministeri": "minister",
    "yritys": "company",
    "nokia": "nokia",
    "nato": "nato",
    "eu": "european union",
    "ukraina": "ukraine",
    "venäjä": "russia",
    "kiina": "china",
    "yhdysvallat": "united states",
    "britannia": "britain",
    "ranska": "france",
    "saksa": "germany",
    "terveys": "health",
    "sairaala": "hospital",
    "koulu": "school",
    "liikenne": "traffic",
    "energia": "energy",
    "sähkö": "electricity",
    "ilma": "air",
    "luonto": "nature",
    "meri": "sea",
    "metsä": "forest",
}

CATEGORY_SEARCH_TERMS = {
    "Kotimaa": "finland news",
    "Ulkomaat": "world news international",
    "Talous": "business economy finance",
    "Teknologia": "technology innovation",
    "Urheilu": "sports athletic",
    "Kulttuuri": "culture arts",
    "Tiede": "science research laboratory",
}


def extract_keywords(title: str, category: str = "", max_keywords: int = 3) -> str:
    """Extract 2-3 English search keywords from a Finnish title.

    Strategy:
    1. Strip Finnish stopwords
    2. Translate known Finnish terms to English
    3. Fall back to category search terms if nothing useful extracted
    Returns a space-separated query string for Unsplash.
    """
    # Normalize: lowercase, strip punctuation except hyphens
    words = re.sub(r"[^\wäöå\s-]", " ", title.lower()).split()

    translated = []
    for word in words:
        # Strip common Finnish inflection suffixes for lookup
        stem = re.sub(r"(ssa|ssä|sta|stä|lle|lta|ltä|lla|llä|sta|stä|ksi|lla|han|hen|hin|hun|hyn|höön|een|ien|jen|den|ten|nen|sen)$", "", word)
        if stem in _FI_STOPWORDS or word in _FI_STOPWORDS:
            continue
        if len(stem) < 3:
            continue
        # Translate if known
        en = _FI_TO_EN.get(stem) or _FI_TO_EN.get(word)
        if en:
            translated.append(en)
        else:
            # Keep original — Unsplash handles some Finnish proper nouns (Nokia etc.)
            # but skip purely Finnish common words
            # Heuristic: if it ends in common Finnish suffixes, likely not useful in EN
            if not re.search(r"(inen|inen|inen|lainen|läinen|linen|llinen|llinen)$", word):
                translated.append(word)

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for w in translated:
        if w not in seen:
            seen.add(w)
            unique.append(w)

    keywords = unique[:max_keywords]

    if not keywords:
        # Full fallback to category terms
        fallback = CATEGORY_SEARCH_TERMS.get(category, "news")
        return fallback

    # Append one category hint if we have room
    if len(keywords) < max_keywords and category:
        cat_hint = CATEGORY_SEARCH_TERMS.get(category, "").split()[0]
        if cat_hint and cat_hint not in " ".join(keywords):
            keywords.append(cat_hint)

    return " ".join(keywords)


def _search_unsplash(query: str, orientation: str = "landscape") -> Optional[Dict]:
    """Search Unsplash API. Returns photo dict or None.

    Requires UNSPLASH_ACCESS_KEY env var.
    Photo dict keys: url, thumb_url, photographer, photographer_url, alt_description
    """
    if not UNSPLASH_ACCESS_KEY:
        return None

    params = urllib.parse.urlencode({
        "query": query,
        "orientation": orientation,
        "per_page": 5,
        "content_filter": "high",
    })
    url = f"{UNSPLASH_SEARCH_URL}?{params}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}",
        "Accept-Version": "v1",
    })
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        results = data.get("results", [])
        if not results:
            return None
        photo = results[0]
        return {
            "url": photo["urls"]["regular"],  # ~1080px wide
            "thumb_url": photo["urls"]["small"],  # ~400px wide
            "photographer": photo["user"]["name"],
            "photographer_url": photo["user"]["links"]["html"],
            "alt_description": photo.get("alt_description") or query,
            "unsplash_photo_url": photo["links"]["html"],
        }
    except Exception as e:
        print(f"[unsplash] Search error for '{query}': {e}")
        return None


def _source_unsplash(query: str, width: int = 1200, height: int = 675) -> Optional[Dict]:
    """Use Unsplash Source (no API key). Returns URL only, no attribution metadata."""
    encoded = urllib.parse.quote(query)
    url = f"{UNSPLASH_SOURCE_URL}/{width}x{height}/?{encoded}"
    # Unsplash Source returns a redirect to actual image — resolve it
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "uutistenlukija/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            final_url = resp.url
        if "unsplash.com/photos" in final_url or "images.unsplash.com" in final_url:
            return {
                "url": final_url,
                "thumb_url": final_url,
                "photographer": "Unsplash",
                "photographer_url": "https://unsplash.com",
                "alt_description": query,
                "unsplash_photo_url": "https://unsplash.com",
            }
    except Exception as e:
        print(f"[unsplash] Source URL error for '{query}': {e}")
    return None


def fetch_image_for_article(title: str, category: str, _inter_request_delay: float = 1.2) -> Optional[Dict]:
    """Fetch a relevant Unsplash image for an article.

    Returns dict with url, thumb_url, photographer, photographer_url,
    alt_description, unsplash_photo_url — or None if nothing found.

    Callers should use category placeholder if None is returned.
    """
    query = extract_keywords(title, category)
    print(f"[unsplash] '{title[:50]}' → query: '{query}'")

    # Try search API first (has proper attribution)
    photo = _search_unsplash(query)
    if photo:
        print(f"[unsplash] Search hit: {photo['photographer']} — {photo['url'][:60]}")
        time.sleep(_inter_request_delay)
        return photo

    # Fall back to Source URL (no attribution metadata, but free)
    photo = _source_unsplash(query)
    if photo:
        print(f"[unsplash] Source URL hit: {photo['url'][:60]}")
        time.sleep(_inter_request_delay)
        return photo

    print(f"[unsplash] No image found for '{title[:50]}'")
    return None


def fetch_images_for_articles(articles: list, delay: float = 1.2) -> list:
    """Fetch Unsplash images for a list of articles.

    Adds to each article:
      - image: URL (Unsplash regular or category fallback path)
      - image_thumb: thumbnail URL
      - image_alt: descriptive alt text
      - image_credit: "Photo: Photographer / Unsplash" for frontmatter display
      - image_source_url: Unsplash photo page URL for attribution link
      - image_category_fallback: True if using category placeholder

    Articles that already have an `image` field are skipped.
    """
    for article in articles:
        if article.get("image"):
            continue  # already has image (e.g. from AI gen)

        title = article.get("title", "")
        category = article.get("category", "Kotimaa")

        photo = fetch_image_for_article(title, category, _inter_request_delay=delay)

        if photo:
            article["image"] = photo["url"]
            article["image_thumb"] = photo["thumb_url"]
            article["image_alt"] = f"{category}-aiheinen kuva: {title}"[:125]
            photographer = photo.get("photographer", "Unsplash")
            article["image_credit"] = f"Kuva: {photographer} / Unsplash"
            article["image_source_url"] = photo.get("unsplash_photo_url", "https://unsplash.com")
            article["image_caption"] = ""  # populated by caller if needed
        else:
            # Category placeholder — set a flag, publisher handles the path
            cat_slug = category.lower()
            article["image"] = f"/images/categories/{cat_slug}.jpg"
            article["image_thumb"] = f"/images/categories/{cat_slug}.jpg"
            article["image_alt"] = f"{category}-uutiset"
            article["image_credit"] = ""
            article["image_source_url"] = ""
            article["image_caption"] = ""
            article["image_category_fallback"] = True

    return articles
