"""
Pexels image fetcher for article featured images.

Downloads images locally to static/images/articles/ for self-hosting.
Hotlinking is NOT used — Pexels terms require attribution but permit download+serve.

Rate limits (free tier):
  - 200 requests/hour
  - Use per_page=80 to minimize API calls (80 photos per search → batch reuse)

Attribution format required by Pexels API ToS:
  "Photo by <Photographer> on Pexels"
  With link to the Pexels photo page.

Environment:
  PEXELS_API_KEY — required for all API calls

Fallback chain:
  1. Pexels search (keyword-based, downloaded locally)
  2. Return None → caller uses category placeholder
"""

import os
import re
import json
import time
import hashlib
import base64
import io
import urllib.request
import urllib.parse
from typing import Optional, Dict, List

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"

# Local cache directory (relative to project root — resolved at call time)
_CACHE_SUBDIR = "static/images/articles"

# In-memory result cache: query → list of photo dicts
# Avoids re-querying the same keyword set across articles in one run
_query_cache: Dict[str, List[Dict]] = {}

# Finnish stopwords — stripped before building search query
_FI_STOPWORDS = {
    "ja", "tai", "on", "ei", "se", "hän", "he", "me", "te",
    "että", "kun", "jos", "niin", "jo", "vain", "myös", "sekä", "mutta",
    "kuin", "mikä", "miksi", "missä", "miten", "kuinka", "joka", "jotka",
    "uusi", "uuden", "uutta", "uudet", "uusia",
    "koko", "kaikki", "yksi", "kaksi", "kolme", "neljä", "viisi",
    "yli", "alle", "noin", "lähes", "enää",
    "sanoo", "kertoo", "mukaan", "mukana", "jälkeen", "ennen",
    "vuosi", "vuoden", "vuotta", "tänä", "tänään", "nyt",
    "suomi", "suomen", "suomessa", "suomalais", "suomalainen",
    "voitti", "hävis", "julkaisi", "ilmoitti", "kertoi", "totesi",
    "uutiset", "lehti", "media", "uutinen",
}

# Finnish → English translations for high-value content terms
_FI_TO_EN = {
    "hallitus": "government",
    "eduskunta": "parliament",
    "poliisi": "police",
    "pörssi": "stock market",
    "talous": "economy",
    "teknologia": "technology",
    "tekoäly": "artificial intelligence",
    "urheilu": "sports",
    "jalkapallo": "football soccer",
    "jääkiekko": "ice hockey",
    "jääkiekon": "ice hockey",
    "jääkiekossa": "ice hockey",
    "tiede": "science",
    "tutkimus": "research",
    "ilmasto": "climate",
    "kulttuuri": "culture",
    "musiikki": "music",
    "elokuva": "film cinema",
    "sota": "war conflict",
    "kriisi": "crisis",
    "vaali": "election",
    "presidentin": "president",
    "presidentti": "president",
    "ministeri": "minister",
    "yritys": "company business",
    "nokia": "nokia technology",
    "nato": "NATO military",
    "eu": "european union",
    "ukraina": "ukraine",
    "venäjä": "russia",
    "kiina": "china",
    "yhdysvallat": "united states",
    "britannia": "britain",
    "ranska": "france",
    "saksa": "germany",
    "terveys": "health medical",
    "sairaala": "hospital",
    "koulu": "school education",
    "liikenne": "traffic transportation",
    "energia": "energy",
    "sähkö": "electricity",
    "luonto": "nature",
    "meri": "sea ocean",
    "metsä": "forest",
    "raha": "money finance",
    "pankki": "bank",
    "asunto": "housing apartment",
    "auto": "car automobile",
    "lentokone": "airplane aviation",
    "laiva": "ship maritime",
    "juna": "train railway",
    "rokote": "vaccine medicine",
    "virus": "virus pandemic",
    "ilmanlaatu": "air quality",
    "avaruus": "space astronomy",
    "robotti": "robot automation",
    "tietokone": "computer",
    "ohjelmisto": "software",
    "kyber": "cybersecurity",
    "tietoturva": "cybersecurity",
}

# Category fallback queries — used when keyword extraction yields nothing useful
CATEGORY_QUERIES = {
    "Kotimaa":    "finland landscape city",
    "Ulkomaat":   "world globe international",
    "Talous":     "business finance economy",
    "Teknologia": "technology innovation digital",
    "Urheilu":    "sports athlete competition",
    "Kulttuuri":  "culture arts performance",
    "Tiede":      "science research laboratory",
}


def _project_root() -> str:
    """Resolve project root from this file's location."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cache_dir() -> str:
    return os.path.join(_project_root(), _CACHE_SUBDIR)


def extract_keywords(title: str, category: str = "", max_terms: int = 4) -> str:
    """Extract English search keywords from a Finnish article title.

    Strips stopwords, translates key Finnish terms, falls back to category query.
    Returns space-joined query string for Pexels.
    """
    words = re.sub(r"[^\wäöå\s-]", " ", title.lower()).split()
    translated = []
    seen = set()

    for word in words:
        # Try stripping common Finnish inflection suffixes for lookup
        stem = re.sub(
            r"(ssa|ssä|sta|stä|lle|lta|ltä|lla|llä|ksi|han|hen|hin|hun|hyn|höön|een|ien|jen|den|ten|nen|sen)$",
            "", word
        )
        if word in _FI_STOPWORDS or stem in _FI_STOPWORDS:
            continue
        if len(stem) < 3:
            continue

        # Translate if known
        en = _FI_TO_EN.get(word) or _FI_TO_EN.get(stem)
        if en:
            key = en.split()[0]  # primary EN word for dedup
            if key not in seen:
                seen.add(key)
                translated.append(en)
        else:
            # Keep non-stopword Finnish words that might be proper nouns/brands
            # Skip words with purely Finnish morphology suffixes
            if not re.search(r"(inen|lainen|läinen|linen|llinen)$", word):
                if word not in seen:
                    seen.add(word)
                    translated.append(word)

    terms = translated[:max_terms]

    if not terms:
        return CATEGORY_QUERIES.get(category, "news")

    # Append category context if space remains
    if len(terms) < max_terms and category in CATEGORY_QUERIES:
        cat_word = CATEGORY_QUERIES[category].split()[0]
        if cat_word not in " ".join(terms):
            terms.append(cat_word)

    return " ".join(terms)


def _search_pexels(query: str, per_page: int = 80) -> List[Dict]:
    """Search Pexels API. Returns list of photo dicts (may be empty).

    Uses in-memory cache to avoid repeat API calls for same query.
    Each photo dict: url, thumb_url, photographer, photographer_url,
                     pexels_url, width, height, avg_color
    """
    if not PEXELS_API_KEY:
        print("[pexels] No PEXELS_API_KEY set — skipping API calls")
        return []

    cache_key = f"{query}|{per_page}"
    if cache_key in _query_cache:
        return _query_cache[cache_key]

    params = urllib.parse.urlencode({
        "query": query,
        "per_page": min(per_page, 80),
        "orientation": "landscape",
        "size": "large",
    })
    url = f"{PEXELS_SEARCH_URL}?{params}"
    req = urllib.request.Request(url, headers={
        "Authorization": PEXELS_API_KEY,
        "User-Agent": "uutistenlukija/1.0 (https://uutistenlukija.fi)",
    })

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            # Log rate limit headers
            remaining = resp.headers.get("X-Ratelimit-Remaining", "?")
            reset = resp.headers.get("X-Ratelimit-Reset", "?")
            if remaining != "?" and int(remaining) < 20:
                print(f"[pexels] ⚠ Rate limit low: {remaining} remaining, resets {reset}")
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print("[pexels] ✗ Rate limit exceeded (429) — skipping image search")
        else:
            print(f"[pexels] HTTP error {e.code} for query '{query}'")
        _query_cache[cache_key] = []
        return []
    except Exception as e:
        print(f"[pexels] Search error for '{query}': {e}")
        _query_cache[cache_key] = []
        return []

    photos = []
    for photo in data.get("photos", []):
        src = photo.get("src", {})
        photos.append({
            "url": src.get("large") or src.get("large2x"),  # 800px large, not huge large2x for performance
            "thumb_url": src.get("medium") or src.get("small"),
            "photographer": photo.get("photographer", "Unknown"),
            "photographer_url": photo.get("photographer_url", "https://www.pexels.com"),
            "pexels_url": photo.get("url", "https://www.pexels.com"),
            "width": photo.get("width", 0),
            "height": photo.get("height", 0),
            "avg_color": photo.get("avg_color", ""),
            "id": photo.get("id"),
        })

    _query_cache[cache_key] = photos
    return photos


def _download_image(url: str, slug: str, suffix: str = "hero") -> Optional[str]:
    """Download image to local cache. Returns relative static path or None.

    File is named {slug}-{suffix}.jpg for human readability and Sara's layout refs.
    Falls back to URL hash if slug is empty.
    Returns path like /images/articles/my-article-hero.jpg for Hugo frontmatter.
    """
    cache_dir = _cache_dir()
    os.makedirs(cache_dir, exist_ok=True)

    # Always store as .jpg (Pexels large/large2x are always JPEG)
    if slug:
        # Sanitize slug: lowercase, alphanumeric + hyphens only
        safe_slug = re.sub(r"[^a-z0-9-]", "-", slug.lower()).strip("-")
        safe_slug = re.sub(r"-+", "-", safe_slug)[:80]  # cap length
        filename = f"{safe_slug}-{suffix}.jpg"
    else:
        url_hash = hashlib.sha1(url.encode()).hexdigest()[:12]
        filename = f"{url_hash}-{suffix}.jpg"

    local_path = os.path.join(cache_dir, filename)
    static_path = f"/images/articles/{filename}"

    if os.path.exists(local_path):
        return static_path  # already cached

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "uutistenlukija/1.0 (https://uutistenlukija.fi)",
            "Referer": "https://www.pexels.com/",
        })
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()

        if len(data) < 1000:
            print(f"[pexels] Download too small ({len(data)}B) — skipping: {url[:60]}")
            return None

        with open(local_path, "wb") as f:
            f.write(data)

        print(f"[pexels] Downloaded {len(data)//1024}KB → {filename}")
        return static_path

    except Exception as e:
        print(f"[pexels] Download failed for {url[:60]}: {e}")
        return None


def _generate_blur_placeholder(local_static_path: str) -> Optional[str]:
    """Generate a 20px-wide base64 JPEG thumbnail for CSS blur-up effect.

    Args:
        local_static_path: relative path like /images/articles/slug-hero.jpg

    Returns:
        data:image/jpeg;base64,... string, or None on failure.
    """
    try:
        from PIL import Image
    except ImportError:
        return None

    # Resolve to filesystem path
    static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
    # local_static_path starts with /images/... — strip leading slash for join
    abs_path = os.path.join(static_dir, local_static_path.lstrip("/"))

    if not os.path.exists(abs_path):
        return None

    try:
        with Image.open(abs_path) as img:
            # Preserve aspect ratio, target 20px wide
            w, h = img.size
            thumb_w = 20
            thumb_h = max(1, int(h * thumb_w / w))
            img = img.convert("RGB")
            img = img.resize((thumb_w, thumb_h), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=40, optimize=True)
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            return f"data:image/jpeg;base64,{b64}"
    except Exception as e:
        print(f"[pexels] blur placeholder failed for {local_static_path}: {e}")
        return None


# Round-robin index per query to avoid all articles getting the same first result
_query_index: Dict[str, int] = {}


def fetch_image_for_article(
    title: str,
    category: str,
    slug: str = "",
    download: bool = True,
    inter_request_delay: float = 0.5,
) -> Optional[Dict]:
    """Fetch a Pexels image for a single article.

    Returns dict with:
      local_path   — /images/articles/xxx.jpg (downloaded) or None
      url          — original Pexels CDN URL
      thumb_url    — medium thumbnail URL
      photographer — photographer name
      photographer_url — Pexels photographer profile URL
      pexels_url   — Pexels photo page URL (required for attribution link)
      alt          — generated alt text
      credit       — "Photo by X on Pexels" attribution string
    Or None if no suitable image found.
    """
    query = extract_keywords(title, category)
    print(f"[pexels] '{title[:50]}' → '{query}'")

    photos = _search_pexels(query)

    # Fallback: try category query if specific search is empty
    if not photos and category in CATEGORY_QUERIES:
        fallback_query = CATEGORY_QUERIES[category]
        print(f"[pexels] No results for '{query}' — trying category fallback '{fallback_query}'")
        photos = _search_pexels(fallback_query)

    if not photos:
        print(f"[pexels] No image found for '{title[:50]}'")
        return None

    # Round-robin to distribute different photos across articles
    idx = _query_index.get(query, 0) % len(photos)
    _query_index[query] = idx + 1
    photo = photos[idx]

    local_path = None
    if download:
        # large2x = 2560px, large = 1920px — prefer large2x per Sara's spec
        hero_url = photo.get("url")  # already large2x or large from _search_pexels
        local_path = _download_image(hero_url, slug, suffix="hero")
        thumb_local = _download_image(photo["thumb_url"], slug, suffix="thumb")
        time.sleep(inter_request_delay)
    else:
        thumb_local = None

    photographer = photo["photographer"]
    pexels_url = photo["pexels_url"]

    return {
        "local_path": local_path,
        "thumb_path": thumb_local,
        "url": photo["url"],
        "thumb_url": photo["thumb_url"],
        "photographer": photographer,
        "photographer_url": photo["photographer_url"],
        "pexels_url": pexels_url,
        "alt": title[:125],
        "credit": f"Photo by {photographer} on Pexels",
    }


def fetch_images_for_articles(articles: list, delay: float = 0.5) -> list:
    """Fetch and download Pexels images for a list of articles.

    Adds frontmatter fields to each article:
      image            — local static path (/images/articles/xxx.jpg) or category fallback
      image_thumb      — thumbnail path
      image_alt        — alt text (Finnish, 125 char cap)
      image_credit     — "Photo by X on Pexels" attribution
      image_source_url — Pexels photo page URL for attribution link
      image_caption    — empty string (Sara's layouts handle rendering)
      image_category_fallback — True if fell back to category image

    Skips articles that already have an `image` field set.

    Rate limit strategy:
      - Per-run in-memory cache means N articles with similar keywords → 1 API call
      - per_page=80 means one search covers up to 80 result variants
      - 200 req/hr limit: at 1 unique query per 2 articles, supports ~400 articles/hr
    """
    import unicodedata as _ud

    def _derive_slug(title: str, max_length: int = 60) -> str:
        s = _ud.normalize("NFKD", title.lower())
        s = s.replace("ä", "a").replace("ö", "o").replace("å", "a")
        s = re.sub(r"[^a-z0-9\s-]", "", s)
        s = re.sub(r"[\s-]+", "-", s).strip("-")
        return s[:max_length].rstrip("-")

    for article in articles:
        if article.get("image"):
            continue

        title = article.get("title", "")
        category = article.get("category", "Kotimaa")
        slug = article.get("slug", "") or _derive_slug(title)

        result = fetch_image_for_article(
            title, category, slug=slug, download=True, inter_request_delay=delay
        )

        if result and result.get("local_path"):
            article["image"] = result["local_path"]
            article["image_thumb"] = result.get("thumb_path") or result["local_path"]
            article["image_alt"] = result["alt"]
            article["image_credit"] = result["credit"]
            article["image_source_url"] = result["pexels_url"]
            article["image_caption"] = ""
            article["image_category_fallback"] = False
            # Generate blur-up placeholder
            b64 = _generate_blur_placeholder(result["local_path"])
            if b64:
                article["image_placeholder"] = b64
        else:
            # Category placeholder fallback
            cat_slug = category.lower()
            article["image"] = f"/images/categories/{cat_slug}.jpg"
            article["image_thumb"] = f"/images/categories/{cat_slug}.jpg"
            article["image_alt"] = f"{category}-uutiset"
            article["image_credit"] = ""
            article["image_source_url"] = ""
            article["image_caption"] = ""
            article["image_category_fallback"] = True

    return articles
