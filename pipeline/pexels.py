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
import tempfile
import urllib.request
import urllib.error
import urllib.parse
import warnings
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
_MAX_IMAGE_DOWNLOAD_BYTES = 20 * 1024 * 1024
_IMAGE_DOWNLOAD_CHUNK_BYTES = 64 * 1024
_SUPPORTED_IMAGE_MIME = {
    "image/jpeg": ("JPEG", ".jpg"),
    "image/png": ("PNG", ".png"),
    "image/webp": ("WEBP", ".webp"),
}

# In-memory result cache: query → list of photo dicts
# Avoids re-querying the same keyword set across articles in one run
_query_cache: Dict[str, List[Dict]] = {}


def _valid_https_url(value: object, allowed_hosts: set[str]) -> bool:
    try:
        parsed = urllib.parse.urlsplit(str(value or "").strip())
        port = parsed.port
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return (
        parsed.scheme.lower() == "https"
        and host in allowed_hosts
        and port in {None, 443}
        and parsed.username is None
        and parsed.password is None
        and bool(parsed.path.strip("/"))
    )


_PEXELS_PHOTO_ID_RE = re.compile(r"^[0-9]+$")


def _strict_provider_url(value: object, allowed_hosts: set[str]) -> urllib.parse.SplitResult | None:
    raw = str(value or "").strip()
    try:
        parsed = urllib.parse.urlsplit(raw)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.lower() != "https"
        or (parsed.hostname or "").lower() not in allowed_hosts
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or "%" in parsed.path
        or "\\" in parsed.path
        or any(segment in {".", ".."} for segment in parsed.path.split("/"))
    ):
        return None
    return parsed


def _pexels_cdn_url_binds_photo_id(value: object, photo_id: str) -> bool:
    if not _PEXELS_PHOTO_ID_RE.fullmatch(photo_id):
        return False
    parsed = _strict_provider_url(value, {"images.pexels.com"})
    if parsed is None:
        return False
    match = re.fullmatch(r"/photos/([0-9]+)/[^/]+/?", parsed.path)
    return bool(match and match.group(1) == photo_id)


def _pexels_page_binds_photo_id(value: object, photo_id: str) -> bool:
    if not _PEXELS_PHOTO_ID_RE.fullmatch(photo_id):
        return False
    parsed = _strict_provider_url(value, {"pexels.com", "www.pexels.com"})
    if parsed is None:
        return False
    match = re.fullmatch(r"/photo/([^/]+)/?", parsed.path)
    if not match:
        return False
    page_slug = match.group(1)
    return page_slug == photo_id or page_slug.endswith(f"-{photo_id}")


def _candidate_identity_consistent(photo: Dict) -> bool:
    photo_id = str(photo.get("id") or "").strip()
    return bool(
        _pexels_cdn_url_binds_photo_id(photo.get("url"), photo_id)
        and _pexels_cdn_url_binds_photo_id(photo.get("thumb_url"), photo_id)
        and _pexels_page_binds_photo_id(photo.get("pexels_url"), photo_id)
    )


def _load_image_pipeline_guards():
    """Load duplicate/policy guards for package and direct-script execution."""

    try:
        from .image_state import (
            canonical_image_identity,
            get_query_index,
            image_identity_aliases,
            is_image_used,
            mark_image_used,
            set_query_index,
        )
    except ImportError:  # pragma: no cover - direct pipeline execution
        try:
            from image_state import (
                canonical_image_identity,
                get_query_index,
                image_identity_aliases,
                is_image_used,
                mark_image_used,
                set_query_index,
            )
        except ImportError:
            return None

    try:
        from .image_candidate_guard import (
            build_stock_queries,
            filter_image_candidates,
            stock_decision_fields,
        )
    except ImportError:  # pragma: no cover - direct pipeline execution
        try:
            from image_candidate_guard import (
                build_stock_queries,
                filter_image_candidates,
                stock_decision_fields,
            )
        except ImportError:
            return None

    return (
        canonical_image_identity,
        image_identity_aliases,
        get_query_index,
        is_image_used,
        mark_image_used,
        set_query_index,
        build_stock_queries,
        filter_image_candidates,
        stock_decision_fields,
    )


def _load_category_fallback_fields():
    try:
        from .image_candidate_guard import category_fallback_fields
    except ImportError:  # pragma: no cover - direct pipeline execution
        try:
            from image_candidate_guard import category_fallback_fields
        except ImportError:
            return None
    return category_fallback_fields


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
            "photographer": photo.get("photographer") or "",
            "photographer_url": photo.get("photographer_url") or "",
            "pexels_url": photo.get("url") or "",
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


def _download_cache_stem(
    url: str,
    slug: str,
    suffix: str,
    candidate_identity: str,
) -> str:
    safe_slug = re.sub(r"[^a-z0-9-]", "-", str(slug or "").lower()).strip("-")
    safe_slug = re.sub(r"-+", "-", safe_slug)[:64]
    safe_suffix = re.sub(r"[^a-z0-9-]", "-", str(suffix or "").lower()).strip("-")
    safe_suffix = re.sub(r"-+", "-", safe_suffix)[:24] or "image"
    provenance = str(candidate_identity or "").strip() or f"url:{url}"
    provenance_hash = hashlib.sha256(provenance.encode("utf-8")).hexdigest()[:16]
    prefix = f"{safe_slug}-" if safe_slug else ""
    return f"{prefix}{provenance_hash}-{safe_suffix}"


def _validated_raster_file(path: str, expected_format: str | None = None) -> bool:
    """Require a fully decodable raster from a small explicit format set."""

    try:
        from PIL import Image
    except (ImportError, ModuleNotFoundError):
        return False

    supported_formats = {value[0] for value in _SUPPORTED_IMAGE_MIME.values()}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter(
                "error",
                getattr(Image, "DecompressionBombWarning", Warning),
            )
            with Image.open(path) as image:
                image_format = str(image.format or "").upper()
                if image_format not in supported_formats:
                    return False
                if expected_format and image_format != expected_format:
                    return False
                if image.width <= 0 or image.height <= 0:
                    return False
                image.verify()

            # verify() checks structure; load() ensures pixel decoding also
            # succeeds before the file becomes visible at its final path.
            with Image.open(path) as image:
                if str(image.format or "").upper() != image_format:
                    return False
                image.load()
        return True
    except Exception:
        return False


def _download_image(
    url: str,
    slug: str,
    suffix: str = "hero",
    *,
    candidate_identity: str = "",
) -> Optional[str]:
    """Download, validate, and atomically cache one trusted Pexels raster."""

    url = str(url or "").strip()
    if not _valid_https_url(url, {"images.pexels.com"}):
        print("[pexels] Download rejected: untrusted image origin")
        return None

    cache_dir = _cache_dir()
    os.makedirs(cache_dir, exist_ok=True)
    stem = _download_cache_stem(url, slug, suffix, candidate_identity)

    # Cached files are provenance-keyed, but still must decode successfully.
    for expected_format, extension in _SUPPORTED_IMAGE_MIME.values():
        cached_path = os.path.join(cache_dir, f"{stem}{extension}")
        if os.path.isfile(cached_path) and _validated_raster_file(
            cached_path,
            expected_format,
        ):
            return f"/images/articles/{stem}{extension}"

    temp_path = ""
    descriptor: int | None = None
    total_bytes = 0
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "uutistenlukija/1.0 (https://uutistenlukija.fi)",
            "Referer": "https://www.pexels.com/",
        })
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw_content_type = str(resp.headers.get("Content-Type") or "")
            content_type = raw_content_type.split(";", 1)[0].strip().lower()
            image_type = _SUPPORTED_IMAGE_MIME.get(content_type)
            if image_type is None:
                print("[pexels] Download rejected: unsupported response MIME")
                return None
            expected_format, extension = image_type

            raw_length = str(resp.headers.get("Content-Length") or "").strip()
            if raw_length:
                try:
                    content_length = int(raw_length)
                except ValueError:
                    return None
                if content_length < 0 or content_length > _MAX_IMAGE_DOWNLOAD_BYTES:
                    print("[pexels] Download rejected: response exceeds size limit")
                    return None

            descriptor, temp_path = tempfile.mkstemp(
                prefix=f".{stem}.",
                suffix=".part",
                dir=cache_dir,
            )
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = None
                while True:
                    remaining = _MAX_IMAGE_DOWNLOAD_BYTES - total_bytes
                    chunk = resp.read(min(_IMAGE_DOWNLOAD_CHUNK_BYTES, remaining + 1))
                    if not chunk:
                        break
                    if not isinstance(chunk, bytes):
                        raise TypeError("image response yielded non-bytes data")
                    total_bytes += len(chunk)
                    if total_bytes > _MAX_IMAGE_DOWNLOAD_BYTES:
                        print("[pexels] Download rejected: streamed body exceeds size limit")
                        return None
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())

        if not _validated_raster_file(temp_path, expected_format):
            print("[pexels] Download rejected: invalid raster payload")
            return None

        filename = f"{stem}{extension}"
        local_path = os.path.join(cache_dir, filename)
        os.chmod(temp_path, 0o644)
        os.replace(temp_path, local_path)
        temp_path = ""
        print(f"[pexels] Downloaded {total_bytes // 1024}KB → {filename}")
        return f"/images/articles/{filename}"
    except Exception as exc:
        print(f"[pexels] Download failed: {exc.__class__.__name__}")
        return None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


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


def _attribution_complete(photo: Dict) -> bool:
    photographer = str(photo.get("photographer") or "").strip()
    if not photographer or photographer.lower() == "unknown":
        return False
    for key in ("photographer_url", "pexels_url"):
        if not _valid_https_url(
            photo.get(key),
            {"pexels.com", "www.pexels.com"},
        ):
            return False
    return _pexels_page_binds_photo_id(
        photo.get("pexels_url"),
        str(photo.get("id") or "").strip(),
    )


def fetch_image_for_article(
    title: str,
    category: str,
    *,
    summary: str = "",
    key_points: list[str] | None = None,
    content: str = "",
    source_evidence: str = "",
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
    semantic_accepted = False
    attribution_complete = False
    delivery_attempted = False
    delivery_succeeded = False
    thumbnail_delivery_succeeded = False

    def finish(image: Optional[Dict], *, reason: str = "") -> object:
        receipt = combine_provider_results(
            provider="pexels",
            searches=searches,
            candidate_count=candidate_count,
            fresh_candidate_count=fresh_candidate_count,
            rejected_count=rejected_count,
            accepted_count=1 if image and (not download or image.get("local_path")) else 0,
            reason=reason,
            semantic_accepted=semantic_accepted,
            attribution_complete=attribution_complete,
            delivery_mode=("download" if download else "hotlink") if semantic_accepted else "none",
            delivery_attempted=delivery_attempted,
            delivery_succeeded=delivery_succeeded,
            thumbnail_delivery_succeeded=thumbnail_delivery_succeeded,
        )
        return (image, receipt) if return_result else image

    def duplicate_guard_fault(reason: str) -> object:
        receipt = build_provider_result(
            provider="pexels",
            attempted=bool(searches),
            succeeded=False,
            outcome="provider_fault",
            reason=reason,
            query_count=len(searches),
            candidate_count=candidate_count,
            fresh_candidate_count=fresh_candidate_count,
            rejected_count=rejected_count,
            accepted_count=0,
            fault_count=1,
        )
        return (None, receipt) if return_result else None

    if not PEXELS_API_KEY:
        receipt = build_provider_result(
            provider="pexels", attempted=False, succeeded=False,
            outcome="no_key", reason="key_unavailable",
        )
        return (None, receipt) if return_result else None

    # Try LLM-powered query first for better contextual matching
    query = ""
    try:
        try:
            from .image_query import generate_image_query, sanitize_generated_query
        except ImportError:  # pragma: no cover - direct pipeline execution
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

    guards = _load_image_pipeline_guards()
    if guards is None:
        return duplicate_guard_fault("duplicate_guard_unavailable")
    (
        canonical_image_identity,
        image_identity_aliases,
        get_query_index,
        is_image_used,
        mark_image_used,
        set_query_index,
        build_stock_queries,
        filter_image_candidates,
        stock_decision_fields,
    ) = guards

    def candidate_identities(candidate: dict) -> tuple[str, ...]:
        canonical = str(canonical_image_identity("pexels", candidate) or "").strip()
        aliases = {
            str(alias or "").strip()
            for alias in image_identity_aliases("pexels", candidate)
            if str(alias or "").strip()
        }
        if canonical:
            aliases.add(canonical)
        if not aliases:
            raise ValueError("candidate has no stable image identity")
        return tuple(([canonical] if canonical else []) + sorted(aliases - {canonical}))

    stock_queries = build_stock_queries(
        title,
        category,
        summary=summary,
        key_points=key_points,
        content=content,
        source_evidence=source_evidence,
        primary_query=query,
    )
    if not stock_queries:
        return finish(None, reason="no_grounded_stock_queries")

    duplicate_guard_failed = False
    identity_binding_failed = False

    def fresh_candidates(photos: list[dict]) -> list[dict]:
        nonlocal duplicate_guard_failed, identity_binding_failed
        fresh: list[dict] = []
        for candidate in photos:
            provider_urls_are_official = bool(
                _valid_https_url(candidate.get("url"), {"images.pexels.com"})
                and _valid_https_url(candidate.get("thumb_url"), {"images.pexels.com"})
                and _valid_https_url(
                    candidate.get("pexels_url"),
                    {"pexels.com", "www.pexels.com"},
                )
            )
            if provider_urls_are_official and not _candidate_identity_consistent(candidate):
                identity_binding_failed = True
                return []
            try:
                identities = candidate_identities(candidate)
                used = [is_image_used(identity) for identity in identities]
            except Exception:
                duplicate_guard_failed = True
                return []
            if not any(used):
                fresh.append(candidate)
        return fresh

    available_photos = []
    selected_query = query
    for candidate_query, concept, brief in stock_queries:
        photos = _search_pexels(candidate_query)
        receipt = search_result(photos, "pexels")
        searches.append(receipt)
        candidate_count += len(photos)
        fresh = fresh_candidates(photos) if receipt.get("succeeded") else []
        if identity_binding_failed:
            return duplicate_guard_fault("provider_identity_mismatch")
        if duplicate_guard_failed:
            return duplicate_guard_fault("duplicate_guard_check_failed")
        fresh_candidate_count += len(fresh)
        available_photos, decisions = filter_image_candidates(
            fresh,
            query=candidate_query,
            title=title,
            summary=summary,
            key_points=key_points,
            content=content,
            source_evidence=source_evidence,
            category=category,
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
        fresh = fresh_candidates(photos) if receipt.get("succeeded") else []
        if identity_binding_failed:
            return duplicate_guard_fault("provider_identity_mismatch")
        if duplicate_guard_failed:
            return duplicate_guard_fault("duplicate_guard_check_failed")
        fresh_candidate_count += len(fresh)
        available_photos, decisions = filter_image_candidates(
            fresh,
            query=fallback_query,
            title=title,
            summary=summary,
            key_points=key_points,
            content=content,
            source_evidence=source_evidence,
            category=category,
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

    semantic_accepted = True
    hero_url = str(photo.get("url") or "").strip()
    thumb_url = str(photo.get("thumb_url") or "").strip()
    attribution_complete = _attribution_complete(photo)
    if not attribution_complete:
        return finish(None, reason="provider_attribution_incomplete")
    if not (
        _valid_https_url(hero_url, {"images.pexels.com"})
        and _valid_https_url(thumb_url, {"images.pexels.com"})
    ):
        delivery_attempted = True
        return finish(None, reason="hero_or_thumbnail_delivery_unavailable")
    if not _candidate_identity_consistent(photo):
        return duplicate_guard_fault("provider_identity_mismatch")
    try:
        selected_identities = candidate_identities(photo)
    except Exception:
        return duplicate_guard_fault("duplicate_guard_check_failed")

    local_path = None
    if download:
        # large2x = 2560px, large = 1920px — prefer large2x per Sara's spec
        delivery_attempted = True
        local_path = _download_image(
            hero_url,
            slug,
            suffix="hero",
            candidate_identity=selected_identities[0],
        )
        thumb_local = _download_image(
            thumb_url,
            slug,
            suffix="thumb",
            candidate_identity=selected_identities[0],
        )
        delivery_succeeded = bool(local_path)
        thumbnail_delivery_succeeded = bool(thumb_local)
        if local_path and not thumb_local:
            thumb_local = local_path
            thumbnail_delivery_succeeded = True
        time.sleep(inter_request_delay)
    else:
        thumb_local = None
        delivery_attempted = True
        delivery_succeeded = True
        thumbnail_delivery_succeeded = True

    if not delivery_succeeded:
        return finish(None, reason="hero_download_failed")

    try:
        for identity in selected_identities:
            mark_image_used(identity)
    except Exception:
        return duplicate_guard_fault("duplicate_guard_mark_failed")

    photographer = photo["photographer"]
    pexels_url = photo["pexels_url"]

    result = {
        "local_path": local_path,
        "thumb_path": thumb_local,
        "url": hero_url,
        "thumb_url": thumb_url,
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
    return finish(result)


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

        result, provider_result = fetch_image_for_article(
            title,
            category,
            summary=article.get("summary", "") or "",
            key_points=key_points,
            content=article.get("content", "") or "",
            source_evidence=str(article.get("source_text") or article.get("research") or ""),
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
            category_fallback_fields = _load_category_fallback_fields()
            if category_fallback_fields is not None:
                article.update(category_fallback_fields(
                    category,
                    reason="stock candidates unavailable or rejected",
                ))

    return articles
