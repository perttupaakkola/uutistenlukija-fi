"""
Unsplash image integration for article featured images.

API compliance requirements (Unsplash API Guidelines):
  - HOTLINK ONLY: serve images directly from images.unsplash.com — no local caching
  - DOWNLOAD TRACKING: must call /photos/{id}/download endpoint for every image used
  - ATTRIBUTION MANDATORY: photographer name + link with UTM params
    UTM format: ?utm_source=uutistenlukija&utm_medium=referral

Rate limits:
  - Demo mode:      50 req/hr  (search/info API calls only; hotlinks don't count)
  - Production:  5,000 req/hr  (apply at unsplash.com/oauth/applications)

Image sizing (hotlink URL params):
  - Full:    urls.full    (~2400px, varies by original)
  - Regular: urls.regular (~1080px wide)
  - Small:   urls.small   (~400px wide, for thumbnails)
  - Thumb:   urls.thumb   (200px wide)

Environment:
  UNSPLASH_ACCESS_KEY — required

Fallback:
  Returns None → caller falls back to Pexels or category placeholder
"""

import os
import re
import json
import time
import urllib.request
import urllib.parse
from typing import Optional, Dict, List

UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")
UNSPLASH_SEARCH_URL = "https://api.unsplash.com/search/photos"
UNSPLASH_DOWNLOAD_URL = "https://api.unsplash.com/photos/{id}/download"

UTM = "utm_source=uutistenlukija&utm_medium=referral"

# In-memory search cache: query → list of photo dicts
# Keeps API calls low against the 50 req/hr demo limit
_query_cache: Dict[str, List[Dict]] = {}

# Round-robin index per query
_query_index: Dict[str, int] = {}

# Finnish stopwords
_FI_STOPWORDS = {
    "ja", "tai", "on", "ei", "se", "hän", "he", "me", "te", "olla", "oli",
    "että", "kun", "jos", "niin", "jo", "vain", "myös", "sekä", "mutta",
    "kuin", "mikä", "miksi", "missä", "miten", "kuinka", "joka", "jotka",
    "uusi", "uuden", "uutta", "uudet", "uusia",
    "koko", "kaikki", "yksi", "kaksi", "kolme", "neljä", "viisi",
    "suuri", "pieni", "iso", "vuosi", "vuoden", "vuotta",
    "yli", "alle", "noin", "lähes", "enää",
    "sanoo", "kertoo", "mukaan", "mukana", "jälkeen", "ennen",
    "suomi", "suomen", "suomessa", "suomalais", "suomalainen",
    "voitti", "hävis", "julkaisi", "ilmoitti", "kertoi", "totesi",
    "uutiset", "lehti", "media", "uutinen",
}

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
    "avaruus": "space astronomy",
    "robotti": "robot automation",
    "tietokone": "computer",
    "ohjelmisto": "software",
    "kyber": "cybersecurity",
    "tietoturva": "cybersecurity",
}

CATEGORY_QUERIES = {
    "Kotimaa":    "finland landscape city",
    "Ulkomaat":   "world globe international",
    "Talous":     "business finance economy",
    "Teknologia": "technology innovation digital",
    "Urheilu":    "sports athlete competition",
    "Kulttuuri":  "culture arts performance",
    "Tiede":      "science research laboratory",
}


def extract_keywords(title: str, category: str = "", max_terms: int = 4) -> str:
    """Extract English search keywords from a Finnish article title."""
    words = re.sub(r"[^\wäöå\s-]", " ", title.lower()).split()
    translated = []
    seen = set()

    for word in words:
        stem = re.sub(
            r"(ssa|ssä|sta|stä|lle|lta|ltä|lla|llä|ksi|han|hen|hin|hun|hyn|höön|een|ien|jen|den|ten|nen|sen)$",
            "", word
        )
        if word in _FI_STOPWORDS or stem in _FI_STOPWORDS:
            continue
        if len(stem) < 3:
            continue
        en = _FI_TO_EN.get(word) or _FI_TO_EN.get(stem)
        if en:
            key = en.split()[0]
            if key not in seen:
                seen.add(key)
                translated.append(en)
        else:
            if not re.search(r"(inen|lainen|läinen|linen|llinen)$", word):
                if word not in seen:
                    seen.add(word)
                    translated.append(word)

    terms = translated[:max_terms]
    if not terms:
        return CATEGORY_QUERIES.get(category, "news")

    if len(terms) < max_terms and category in CATEGORY_QUERIES:
        cat_word = CATEGORY_QUERIES[category].split()[0]
        if cat_word not in " ".join(terms):
            terms.append(cat_word)

    return " ".join(terms)


def _api_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}",
        "Accept-Version": "v1",
        "User-Agent": "uutistenlukija/1.0 (https://uutistenlukija.fi)",
    }


def _search(query: str, per_page: int = 30) -> List[Dict]:
    """Search Unsplash. Returns list of normalized photo dicts, cached per query.

    Per Unsplash API guidelines, per_page max is 30.
    """
    if not UNSPLASH_ACCESS_KEY:
        return []

    cache_key = f"{query}|{per_page}"
    if cache_key in _query_cache:
        return _query_cache[cache_key]

    params = urllib.parse.urlencode({
        "query": query,
        "orientation": "landscape",
        "per_page": min(per_page, 30),
        "content_filter": "high",
        "order_by": "relevant",
    })
    url = f"{UNSPLASH_SEARCH_URL}?{params}"
    req = urllib.request.Request(url, headers=_api_headers())

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            remaining = resp.headers.get("X-Ratelimit-Remaining", "?")
            if remaining != "?" and int(remaining) < 10:
                print(f"[unsplash] ⚠ Rate limit low: {remaining} remaining")
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print("[unsplash] ✗ Rate limit exceeded (429)")
        else:
            print(f"[unsplash] HTTP {e.code} for query '{query}'")
        _query_cache[cache_key] = []
        return []
    except Exception as e:
        print(f"[unsplash] Search error for '{query}': {e}")
        _query_cache[cache_key] = []
        return []

    photos = []
    for p in data.get("results", []):
        user = p.get("user", {})
        user_links = user.get("links", {})
        photographer_profile = user_links.get("html", "https://unsplash.com")
        # Append UTM to attribution URLs (required by Unsplash guidelines)
        if "?" in photographer_profile:
            photographer_profile += f"&{UTM}"
        else:
            photographer_profile += f"?{UTM}"

        photo_page = p.get("links", {}).get("html", "https://unsplash.com")
        if "?" in photo_page:
            photo_page += f"&{UTM}"
        else:
            photo_page += f"?{UTM}"

        urls = p.get("urls", {})
        photos.append({
            "id": p["id"],
            # Hotlink URLs — served directly from images.unsplash.com
            "url_full":    urls.get("full"),
            "url_regular": urls.get("regular"),   # ~1080px
            "url_small":   urls.get("small"),     # ~400px
            "url_thumb":   urls.get("thumb"),     # 200px
            "download_location": p.get("links", {}).get("download_location"),
            "photographer": user.get("name", "Unknown"),
            "photographer_url": photographer_profile,
            "photo_page": photo_page,
            "alt": p.get("alt_description") or query,
            "width": p.get("width", 0),
            "height": p.get("height", 0),
        })

    _query_cache[cache_key] = photos
    return photos


def _trigger_download(photo: Dict) -> None:
    """Trigger Unsplash download tracking endpoint.

    Required by Unsplash API guidelines every time a photo is used.
    Uses download_location from the photo (preferred) or constructs it.
    Non-blocking: failure is logged but does not abort the pipeline.
    """
    if not UNSPLASH_ACCESS_KEY:
        return

    dl_url = photo.get("download_location")
    if not dl_url:
        photo_id = photo.get("id")
        if not photo_id:
            return
        dl_url = UNSPLASH_DOWNLOAD_URL.format(id=photo_id)

    req = urllib.request.Request(dl_url, headers=_api_headers())
    try:
        with urllib.request.urlopen(req, timeout=8) as _:
            pass
        print(f"[unsplash] Download tracked: {photo.get('id')}")
    except Exception as e:
        print(f"[unsplash] Download tracking failed (non-fatal): {e}")


def fetch_image_for_article(
    title: str,
    category: str,
    inter_request_delay: float = 1.2,
) -> Optional[Dict]:
    """Fetch a relevant Unsplash image for a single article.

    Returns dict with:
      url          — hotlink URL (full size, images.unsplash.com)
      thumb_url    — hotlink thumbnail URL
      photographer — photographer name
      photographer_url — photographer Unsplash profile URL (with UTM)
      photo_page   — Unsplash photo page URL (with UTM, for attribution link)
      alt          — alt text string
      credit       — "Photo by X on Unsplash" attribution string
      hotlink      — True (signals templates to use as <img src> directly)
    Or None if nothing found.

    Side effect: triggers Unsplash download tracking endpoint.
    """
    query = extract_keywords(title, category)
    print(f"[unsplash] '{title[:50]}' → '{query}'")

    photos = _search(query)

    if not photos and category in CATEGORY_QUERIES:
        fallback_query = CATEGORY_QUERIES[category]
        print(f"[unsplash] No results for '{query}' → category fallback '{fallback_query}'")
        photos = _search(fallback_query)

    if not photos:
        return None

    idx = _query_index.get(query, 0) % len(photos)
    _query_index[query] = idx + 1
    photo = photos[idx]

    # Trigger mandatory download tracking
    _trigger_download(photo)
    time.sleep(inter_request_delay)

    photographer = photo["photographer"]
    photo_page = photo["photo_page"]

    return {
        "url": photo["url_regular"] or photo["url_full"],  # 1080px for performance, not full 2400px
        "thumb_url": photo["url_small"] or photo["url_thumb"],
        "photographer": photographer,
        "photographer_url": photo["photographer_url"],
        "photo_page": photo_page,
        "alt": title[:125],
        "credit": f"Photo by {photographer} on Unsplash",
        "hotlink": True,  # must NOT be downloaded/cached locally
    }


def fetch_images_for_articles(articles: list, delay: float = 1.2) -> list:
    """Fetch Unsplash hotlink images for a list of articles.

    Sets frontmatter fields on each article:
      image            — hotlink URL (images.unsplash.com) to use in <img src>
      image_thumb      — thumbnail hotlink URL
      image_alt        — alt text (125 char cap)
      image_credit     — "Photo by X on Unsplash" (mandatory attribution)
      image_source_url — Unsplash photo page URL with UTM params
      image_caption    — empty (Sara's layout handles rendering)
      image_hotlink    — True (downstream templates must not proxy/re-serve this URL)
      image_category_fallback — True if fell back to local category placeholder

    Skips articles that already have an `image` field set.
    """
    for article in articles:
        if article.get("image"):
            continue

        title = article.get("title", "")
        category = article.get("category", "Kotimaa")

        result = fetch_image_for_article(title, category, inter_request_delay=delay)

        if result:
            article["image"] = result["url"]
            article["image_thumb"] = result["thumb_url"]
            article["image_alt"] = result["alt"]
            article["image_credit"] = result["credit"]
            article["image_source_url"] = result["photo_page"]
            article["image_caption"] = ""
            article["image_hotlink"] = True
            article["image_category_fallback"] = False
        else:
            cat_slug = category.lower()
            article["image"] = f"/images/categories/{cat_slug}.jpg"
            article["image_thumb"] = f"/images/categories/{cat_slug}.jpg"
            article["image_alt"] = f"{category}-uutiset"
            article["image_credit"] = ""
            article["image_source_url"] = ""
            article["image_caption"] = ""
            article["image_hotlink"] = False
            article["image_category_fallback"] = True

    return articles
