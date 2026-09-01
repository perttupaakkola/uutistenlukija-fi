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
import urllib.error
import urllib.parse
from typing import Optional, Dict, List

try:
    from .image_provider_result import (
        build_provider_result, combine_provider_results, search_photos,
        search_result, set_provider_result,
    )
except ImportError:  # pragma: no cover - direct pipeline execution
    from image_provider_result import (
        build_provider_result, combine_provider_results, search_photos,
        search_result, set_provider_result,
    )

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
    "ovat", "olla", "oli", "saattavat", "takia", "lähellä", "tulokset", "asiantuntija", "pääministeri",
    "kannattaako", "laskuri", "arvioi", "arvioidaan", "vertaamalla", "kertoo",
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
    "korkeakoulututkinto": "university degree",
    "korkeakoulututkinnon": "university degree",
    "tutkinto": "degree diploma",
    "tutkinnon": "degree diploma",
    "koulutus": "education",
    "koulutuksen": "education",
    "opintolaina": "student loan",
    "opintolainaa": "student loan",
    "palkkaero": "salary comparison",
    "palkkaerosta": "salary comparison",
    "palkkataso": "salary",
    "tuotto": "return investment",
    "tuoton": "return investment",
    "takaisinmaksuaika": "payback calculation",
    "takaisinmaksuajasta": "payback calculation",
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

_ENTERTAINMENT_FALLBACK_TERMS = {
    "netflix", "hbo", "hbo max", "disney", "disney+", "prime video",
    "yle areena", "suoratoisto", "streaming", "elokuva", "elokuvat", "film",
    "movie", "sarja", "sarjat", "sarjakausi", "series", "tv", "televisio",
    "televisiosarja", "peli", "pelit", "game", "games", "actor", "näyttelijä",
    "ohjaaja", "director",
}


def _project_root() -> str:
    """Resolve project root from this file's location."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cache_dir() -> str:
    return os.path.join(_project_root(), _CACHE_SUBDIR)


def _normalize_category(category: str) -> str:
    category = (category or "").strip()
    if not category:
        return ""
    for canonical in CATEGORY_QUERIES:
        if canonical.lower() == category.lower():
            return canonical
    return category


def _tokenize_terms(*parts: str) -> list[str]:
    tokens: list[str] = []
    seen = set()
    for part in parts:
        words = re.sub(r"[^\wäöå\s-]", " ", (part or "").lower()).split()
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
            candidates = (en.split() if en else [word])
            for cand in candidates:
                cand = cand.strip()
                if not cand or cand in seen:
                    continue
                if not en and re.search(r"(inen|lainen|läinen|linen|llinen)$", cand):
                    continue
                seen.add(cand)
                tokens.append(cand)
    return tokens


def blocks_broad_category_fallback(
    title: str,
    *,
    summary: str = "",
    key_points: list[str] | None = None,
    content: str = "",
) -> bool:
    """Reject broad category fallback for entertainment/title-specific stories."""
    haystack = " ".join([title or "", summary or "", " ".join(key_points or []), content or ""]).lower()
    return any(term in haystack for term in _ENTERTAINMENT_FALLBACK_TERMS)


def build_search_query(
    title: str,
    category: str = "",
    *,
    summary: str = "",
    key_points: list[str] | None = None,
    content: str = "",
    max_terms: int = 5,
) -> str:
    """Build a topic-specific image search query from article fields."""
    category = _normalize_category(category)
    content_excerpt = " ".join((content or "").split()[:80])
    tokens = _tokenize_terms(
        " ".join(key_points or []),
        title,
        summary,
        content_excerpt,
    )

    terms = tokens[:max_terms]
    if not terms:
        return CATEGORY_QUERIES.get(category, "news")

    if category in CATEGORY_QUERIES:
        for cat_word in CATEGORY_QUERIES[category].split():
            if len(terms) >= max_terms:
                break
            if cat_word not in terms:
                terms.append(cat_word)

    return " ".join(terms[:max_terms])


def extract_keywords(title: str, category: str = "", max_terms: int = 4) -> str:
    """Backward-compatible title-only keyword extraction."""
    return build_search_query(title, category, max_terms=max_terms)


def _search_pexels(query: str, per_page: int = 80) -> List[Dict]:
    """Search Pexels and return photos with a bounded request receipt."""
    if not PEXELS_API_KEY:
        print("[pexels] No PEXELS_API_KEY set — skipping API calls")
        return search_photos(
            [], provider="pexels", attempted=False, succeeded=False,
            outcome="no_key", reason="key_unavailable",
        )

    cache_key = f"{query}|{per_page}"
    if cache_key in _query_cache:
        return search_photos(
            _query_cache[cache_key], provider="pexels", attempted=False,
            succeeded=True, outcome="cache_hit", reason="cached_search_result",
        )

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
            remaining = resp.headers.get("X-Ratelimit-Remaining", "?")
            reset = resp.headers.get("X-Ratelimit-Reset", "?")
            if remaining != "?" and int(remaining) < 20:
                print(f"[pexels] ⚠ Rate limit low: {remaining} remaining, resets {reset}")
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            print("[pexels] ✗ Rate limit exceeded (429) — skipping image search")
        else:
            print(f"[pexels] HTTP error {exc.code} during image search")
        failed = search_photos(
            [], provider="pexels", attempted=True, succeeded=False,
            outcome="provider_fault", reason=f"http_{exc.code}", fault_count=1,
        )
        return failed
    except Exception as exc:
        print(f"[pexels] Search error: {exc.__class__.__name__}")
        failed = search_photos(
            [], provider="pexels", attempted=True, succeeded=False,
            outcome="provider_fault", reason="request_exception", fault_count=1,
        )
        return failed

    photos = []
    for photo in data.get("photos", []):
        src = photo.get("src", {})
        photos.append({
            "url": src.get("large") or src.get("large2x"),
            "thumb_url": src.get("medium") or src.get("small"),
            "photographer": photo.get("photographer", "Unknown"),
            "photographer_url": photo.get("photographer_url", "https://www.pexels.com"),
            "pexels_url": photo.get("url", "https://www.pexels.com"),
            "alt": photo.get("alt") or "",
            "width": photo.get("width", 0),
            "height": photo.get("height", 0),
            "avg_color": photo.get("avg_color", ""),
            "id": photo.get("id"),
        })

    completed = search_photos(
        photos, provider="pexels", attempted=True, succeeded=True,
        outcome="search_succeeded", reason="response_received",
    )
    _query_cache[cache_key] = completed
    return completed


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
    *,
    summary: str = "",
    key_points: list[str] | None = None,
    content: str = "",
    slug: str = "",
    download: bool = True,
    inter_request_delay: float = 0.5,
    return_result: bool = False,
) -> object:
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
    category = _normalize_category(category)
    searches: list[dict] = []
    candidate_count = 0
    fresh_candidate_count = 0
    rejected_count = 0
    download_failed = False

    def finish(image: Optional[Dict], *, reason: str = "") -> object:
        receipt = combine_provider_results(
            provider="pexels",
            searches=searches,
            candidate_count=candidate_count,
            fresh_candidate_count=fresh_candidate_count,
            rejected_count=rejected_count,
            accepted_count=1 if image and (not download or image.get("local_path")) else 0,
            reason=reason,
        )
        if download_failed:
            receipt.update({
                "outcome": "provider_fault",
                "reason": "download_failed",
                "accepted_count": 0,
                "fault_count": min(10_000, int(receipt.get("fault_count") or 0) + 1),
            })
        return (image, receipt) if return_result else image

    if not PEXELS_API_KEY:
        receipt = build_provider_result(
            provider="pexels", attempted=False, succeeded=False,
            outcome="no_key", reason="key_unavailable",
        )
        return (None, receipt) if return_result else None

    # Try LLM-powered query first for better contextual matching
    query = ""
    try:
        from image_query import generate_image_query, sanitize_generated_query
        query = sanitize_generated_query(
            generate_image_query(title, content or summary or "", category),
            title,
            content or summary or "",
            category,
        )
    except Exception as e:
        print(f"[pexels] LLM query unavailable ({e}), using keyword extraction")

    if not query:
        query = build_search_query(
            title,
            category,
            summary=summary,
            key_points=key_points,
            content=content,
        )
    print(f"[pexels] '{title[:50]}' → '{query}'")

    # Filter out already used images
    try:
        from image_state import is_image_used, mark_image_used, get_query_index, set_query_index
        from image_candidate_guard import build_stock_queries, filter_image_candidates, stock_decision_fields
    except ImportError:
        is_image_used = lambda x: False
        mark_image_used = lambda x: None
        get_query_index = lambda x: _query_index.get(x, 0)
        set_query_index = lambda x, y: _query_index.update({x: y})
        from image_candidate_guard import build_stock_queries, filter_image_candidates, stock_decision_fields

    stock_queries = build_stock_queries(
        title,
        category,
        summary=summary,
        key_points=key_points,
        content=content,
        primary_query=query,
    )
    available_photos = []
    selected_query = query
    for candidate_query, concept, brief in stock_queries:
        photos = _search_pexels(candidate_query)
        receipt = search_result(photos, "pexels")
        searches.append(receipt)
        candidate_count += len(photos)
        fresh = [p for p in photos if not is_image_used(p["id"])] if receipt.get("succeeded") else []
        fresh_candidate_count += len(fresh)
        available_photos, decisions = filter_image_candidates(
            fresh,
            query=candidate_query,
            title=title,
            summary=summary,
            key_points=key_points,
            content=content,
            provider="pexels",
            intent=brief.intent,
            brief=brief,
            concept=concept,
            return_decisions=True,
        )
        rejected_count += sum(1 for decision in decisions if not decision.accepted)
        selected_query = candidate_query
        if available_photos:
            break

    # Fallback: try category query if specific search is empty or all used
    if not available_photos and category in CATEGORY_QUERIES:
        if blocks_broad_category_fallback(title, summary=summary, key_points=key_points, content=content):
            print(f"[pexels] No fresh results for '{query}' — broad category fallback blocked")
            return finish(None, reason="broad_category_fallback_blocked")
        fallback_query = CATEGORY_QUERIES[category]
        print(f"[pexels] No fresh results for '{query}' — trying category fallback '{fallback_query}'")
        photos = _search_pexels(fallback_query)
        receipt = search_result(photos, "pexels")
        searches.append(receipt)
        candidate_count += len(photos)
        fresh = [p for p in photos if not is_image_used(p["id"])] if receipt.get("succeeded") else []
        fresh_candidate_count += len(fresh)
        available_photos, decisions = filter_image_candidates(
            fresh,
            query=fallback_query,
            title=title,
            summary=summary,
            key_points=key_points,
            content=content,
            provider="pexels",
            intent=stock_queries[0][2].intent,
            brief=stock_queries[0][2],
            concept=fallback_query,
            return_decisions=True,
        )
        rejected_count += sum(1 for decision in decisions if not decision.accepted)
        selected_query = fallback_query

    if not available_photos:
        print(f"[pexels] No fresh image found for '{title[:50]}'")
        return finish(None)

    # Round-robin to distribute different photos across articles
    idx = get_query_index(query) % len(available_photos)
    set_query_index(query, idx + 1)
    photo = available_photos[idx]

    local_path = None
    if download:
        # large2x = 2560px, large = 1920px — prefer large2x per Sara's spec
        hero_url = photo.get("url")  # already large2x or large from _search_pexels
        local_path = _download_image(hero_url, slug, suffix="hero")
        thumb_local = _download_image(photo["thumb_url"], slug, suffix="thumb")
        if local_path:
            mark_image_used(photo["id"])
        else:
            download_failed = True
        time.sleep(inter_request_delay)
    else:
        thumb_local = None

    photographer = photo["photographer"]
    pexels_url = photo["pexels_url"]

    result = {
        "local_path": local_path,
        "thumb_path": thumb_local,
        "url": photo["url"],
        "thumb_url": photo["thumb_url"],
        "photographer": photographer,
        "photographer_url": photo["photographer_url"],
        "pexels_url": pexels_url,
        "alt": title[:125],
        "credit": f"Photo by {photographer} on Pexels",
        "decision": photo.get("_image_decision", {}),
        "intent": photo.get("_image_visual_intent", stock_queries[0][2].intent.to_dict()),
        "brief": photo.get("_image_visual_brief", {}),
        "visual_judge": photo.get("_image_visual_judge", {}),
        "concept": photo.get("_image_concept", selected_query),
    }
    result.update(stock_decision_fields("pexels", result, selected_query))
    return finish(result, reason="download_failed" if download_failed else "")


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
        key_points = list(article.get("key_points") or [])
        key_points.extend(article.get("tags") or [])

        result, provider_result = fetch_image_for_article(
            title,
            category,
            summary=article.get("summary", "") or "",
            key_points=key_points,
            content=article.get("content", "") or "",
            slug=slug,
            download=True,
            inter_request_delay=delay,
            return_result=True,
        )
        set_provider_result(article, provider_result)

        if result and result.get("local_path"):
            article["image"] = result["local_path"]
            article["image_thumb"] = result.get("thumb_path") or result["local_path"]
            article["image_alt"] = result["alt"]
            article["image_credit"] = result["credit"]
            article["image_source_url"] = result["pexels_url"]
            article["image_caption"] = ""
            article.update({k: v for k, v in result.items() if k.startswith("image_")})
            # Generate blur-up placeholder
            b64 = _generate_blur_placeholder(result["local_path"])
            if b64:
                article["image_placeholder"] = b64
        else:
            from image_candidate_guard import category_fallback_fields
            article.update(category_fallback_fields(category, reason="stock candidates unavailable or rejected"))

    return articles
