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

UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")
UNSPLASH_SEARCH_URL = "https://api.unsplash.com/search/photos"
UNSPLASH_DOWNLOAD_URL = "https://api.unsplash.com/photos/{id}/download"

UTM = "utm_source=uutistenlukija&utm_medium=referral"

# In-memory search cache: query → list of photo dicts
# Keeps API calls low against the 50 req/hr demo limit
_query_cache: Dict[str, List[Dict]] = {}

# Round-robin index per query
_query_index: Dict[str, int] = {}


def _valid_https_url(value: object, allowed_hosts: set[str]) -> bool:
    try:
        parsed = urllib.parse.urlsplit(str(value or "").strip())
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return parsed.scheme.lower() == "https" and host in allowed_hosts and bool(parsed.path.strip("/"))


_UNSPLASH_PHOTO_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


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


def _download_location_binds_photo_id(value: object, photo_id: str) -> bool:
    if not _UNSPLASH_PHOTO_ID_RE.fullmatch(photo_id):
        return False
    parsed = _strict_provider_url(value, {"api.unsplash.com"})
    return bool(
        parsed
        and parsed.path == f"/photos/{photo_id}/download"
    )


def _photo_page_binds_photo_id(value: object, photo_id: str) -> bool:
    if not _UNSPLASH_PHOTO_ID_RE.fullmatch(photo_id):
        return False
    parsed = _strict_provider_url(value, {"unsplash.com", "www.unsplash.com"})
    if parsed is None:
        return False
    match = re.fullmatch(r"/photos/([^/]+)/?", parsed.path)
    if not match:
        return False
    page_slug = match.group(1)
    return page_slug == photo_id or page_slug.endswith(f"-{photo_id}")


def _candidate_identity_consistent(photo: Dict) -> bool:
    photo_id = str(photo.get("id") or "").strip()
    if not _photo_page_binds_photo_id(photo.get("photo_page"), photo_id):
        return False
    download_location = photo.get("download_location")
    return not download_location or _download_location_binds_photo_id(
        download_location,
        photo_id,
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


def _attribution_complete(photo: Dict) -> bool:
    photographer = str(photo.get("photographer") or "").strip()
    if not photographer or photographer.lower() == "unknown":
        return False
    for key in ("photographer_url", "photo_page"):
        value = photo.get(key)
        if not _valid_https_url(
            value,
            {"unsplash.com", "www.unsplash.com"},
        ):
            return False
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(str(value)).query)
        if (
            "uutistenlukija" not in query.get("utm_source", [])
            or "referral" not in query.get("utm_medium", [])
        ):
            return False
    return _photo_page_binds_photo_id(
        photo.get("photo_page"),
        str(photo.get("id") or "").strip(),
    )

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
    "ovat", "saattavat", "takia", "lähellä", "tulokset", "asiantuntija", "pääministeri",
    "kannattaako", "laskuri", "arvioi", "arvioidaan", "vertaamalla", "kertoo",
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
    """Build a topic-specific English-biased image search query.

    Priority: title terms first, then key points, then summary/content, then category context.
    """
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


def _api_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}",
        "Accept-Version": "v1",
        "User-Agent": "uutistenlukija/1.0 (https://uutistenlukija.fi)",
    }


def _search(query: str, per_page: int = 30) -> List[Dict]:
    """Search Unsplash and return photos with a bounded request receipt."""
    if not UNSPLASH_ACCESS_KEY:
        return search_photos(
            [], provider="unsplash", attempted=False, succeeded=False,
            outcome="no_key", reason="key_unavailable",
        )

    cache_key = f"{query}|{per_page}"
    if cache_key in _query_cache:
        return search_photos(
            _query_cache[cache_key], provider="unsplash", attempted=False,
            succeeded=True, outcome="cache_hit", reason="cached_search_result",
        )

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
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            print("[unsplash] ✗ Rate limit exceeded (429)")
        else:
            print(f"[unsplash] HTTP {exc.code} during image search")
        failed = search_photos(
            [], provider="unsplash", attempted=True, succeeded=False,
            outcome="provider_fault", reason=f"http_{exc.code}", fault_count=1,
        )
        return failed
    except Exception as exc:
        print(f"[unsplash] Search error: {exc.__class__.__name__}")
        failed = search_photos(
            [], provider="unsplash", attempted=True, succeeded=False,
            outcome="provider_fault", reason="request_exception", fault_count=1,
        )
        return failed

    photos = []
    for photo in data.get("results", []):
        user = photo.get("user", {})
        user_links = user.get("links", {})
        photographer_profile = str(user_links.get("html") or "").strip()
        if photographer_profile:
            if "?" in photographer_profile:
                photographer_profile += f"&{UTM}"
            else:
                photographer_profile += f"?{UTM}"

        photo_page = str(photo.get("links", {}).get("html") or "").strip()
        if photo_page:
            if "?" in photo_page:
                photo_page += f"&{UTM}"
            else:
                photo_page += f"?{UTM}"

        urls = photo.get("urls", {})
        photos.append({
            "id": photo["id"],
            "url_full": urls.get("full"),
            "url_regular": urls.get("regular"),
            "url_small": urls.get("small"),
            "url_thumb": urls.get("thumb"),
            "download_location": photo.get("links", {}).get("download_location"),
            "photographer": user.get("name") or "",
            "photographer_url": photographer_profile,
            "photo_page": photo_page,
            # Never use our query as candidate evidence. An absent provider
            # caption must remain absent so the semantic guard fails closed.
            "alt": photo.get("alt_description") or "",
            "width": photo.get("width", 0),
            "height": photo.get("height", 0),
        })

    completed = search_photos(
        photos, provider="unsplash", attempted=True, succeeded=True,
        outcome="search_succeeded", reason="response_received",
    )
    _query_cache[cache_key] = completed
    return completed


def _trigger_download(photo: Dict) -> tuple[bool, bool]:
    """Trigger Unsplash download tracking endpoint.

    Required by Unsplash API guidelines every time a photo is used.
    Uses download_location from the photo (preferred) or constructs it.
    Return ``(attempted, succeeded)`` so acceptance can fail closed when the
    provider-required tracking call does not complete.
    """
    if not UNSPLASH_ACCESS_KEY:
        return False, False

    photo_id = str(photo.get("id") or "").strip()
    if not _UNSPLASH_PHOTO_ID_RE.fullmatch(photo_id):
        return False, False

    dl_url = photo.get("download_location")
    if not dl_url:
        dl_url = UNSPLASH_DOWNLOAD_URL.format(id=photo_id)

    if not _download_location_binds_photo_id(dl_url, photo_id):
        print("[unsplash] Download tracking blocked: invalid provider endpoint")
        return False, False

    req = urllib.request.Request(dl_url, headers=_api_headers())
    try:
        with urllib.request.urlopen(req, timeout=8) as _:
            pass
        print(f"[unsplash] Download tracked: {photo.get('id')}")
        return True, True
    except Exception as exc:
        print(f"[unsplash] Download tracking failed type={exc.__class__.__name__}")
        return True, False


def fetch_image_for_article(
    title: str,
    category: str,
    *,
    summary: str = "",
    key_points: list[str] | None = None,
    content: str = "",
    source_evidence: str = "",
    inter_request_delay: float = 1.2,
    return_result: bool = False,
) -> object:
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
    tracking_attempted = False
    tracking_succeeded = False

    def finish(image: Optional[Dict], *, reason: str = "") -> object:
        receipt = combine_provider_results(
            provider="unsplash",
            searches=searches,
            candidate_count=candidate_count,
            fresh_candidate_count=fresh_candidate_count,
            rejected_count=rejected_count,
            accepted_count=1 if image else 0,
            reason=reason,
            semantic_accepted=semantic_accepted,
            attribution_complete=attribution_complete,
            delivery_mode="hotlink" if semantic_accepted else "none",
            delivery_attempted=delivery_attempted,
            delivery_succeeded=delivery_succeeded,
            thumbnail_delivery_succeeded=thumbnail_delivery_succeeded,
            tracking_attempted=tracking_attempted,
            tracking_succeeded=tracking_succeeded,
        )
        return (image, receipt) if return_result else image

    def duplicate_guard_fault(reason: str) -> object:
        receipt = build_provider_result(
            provider="unsplash",
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

    if not UNSPLASH_ACCESS_KEY:
        receipt = build_provider_result(
            provider="unsplash", attempted=False, succeeded=False,
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
        print(f"[unsplash] LLM query unavailable ({e}), using keyword extraction")

    if not query:
        query = build_search_query(
            title,
            category,
            summary=summary,
            key_points=key_points,
            content=content,
        )
    print(f"[unsplash] '{title[:50]}' → '{query}'")

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
        canonical = str(canonical_image_identity("unsplash", candidate) or "").strip()
        aliases = {
            str(alias or "").strip()
            for alias in image_identity_aliases("unsplash", candidate)
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
            download_location = candidate.get("download_location")
            provider_urls_are_official = bool(
                _valid_https_url(
                    candidate.get("photo_page"),
                    {"unsplash.com", "www.unsplash.com"},
                )
                and (
                    not download_location
                    or _valid_https_url(download_location, {"api.unsplash.com"})
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
        photos = _search(candidate_query)
        receipt = search_result(photos, "unsplash")
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
            provider="unsplash",
            intent=brief.intent,
            brief=brief,
            concept=concept,
            return_decisions=True,
        )
        rejected_count += sum(1 for decision in decisions if not decision.accepted)
        selected_query = candidate_query
        if available_photos:
            break

    if not available_photos and category in CATEGORY_QUERIES:
        if blocks_broad_category_fallback(title, summary=summary, key_points=key_points, content=content):
            print(f"[unsplash] No fresh results for '{query}' — broad category fallback blocked")
            return finish(None, reason="broad_category_fallback_blocked")
        fallback_query = CATEGORY_QUERIES[category]
        print(f"[unsplash] No fresh results for '{query}' → category fallback '{fallback_query}'")
        photos = _search(fallback_query)
        receipt = search_result(photos, "unsplash")
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
            provider="unsplash",
            intent=stock_queries[0][2].intent,
            brief=stock_queries[0][2],
            concept=fallback_query,
            return_decisions=True,
        )
        rejected_count += sum(1 for decision in decisions if not decision.accepted)
        selected_query = fallback_query

    if not available_photos:
        return finish(None)

    idx = get_query_index(query) % len(available_photos)
    set_query_index(query, idx + 1)
    photo = available_photos[idx]

    semantic_accepted = True
    hero_url = str(photo.get("url_regular") or photo.get("url_full") or "").strip()
    thumb_url = str(photo.get("url_small") or photo.get("url_thumb") or "").strip()
    delivery_attempted = True
    delivery_succeeded = _valid_https_url(hero_url, {"images.unsplash.com"})
    thumbnail_delivery_succeeded = _valid_https_url(
        thumb_url,
        {"images.unsplash.com"},
    )
    attribution_complete = _attribution_complete(photo)
    if not delivery_succeeded or not thumbnail_delivery_succeeded:
        return finish(None, reason="hero_or_thumbnail_delivery_unavailable")
    if not attribution_complete:
        return finish(None, reason="provider_attribution_incomplete")
    if not _candidate_identity_consistent(photo):
        return duplicate_guard_fault("provider_identity_mismatch")

    # Trigger mandatory download tracking
    tracking_attempted, tracking_succeeded = _trigger_download(photo)
    if not tracking_attempted or not tracking_succeeded:
        return finish(None, reason="download_tracking_failed")
    try:
        for identity in candidate_identities(photo):
            mark_image_used(identity)
    except Exception:
        return duplicate_guard_fault("duplicate_guard_mark_failed")
    time.sleep(inter_request_delay)

    photographer = photo["photographer"]
    photo_page = photo["photo_page"]

    result = {
        "url": hero_url,  # 1080px for performance, not full 2400px
        "thumb_url": thumb_url,
        "photographer": photographer,
        "photographer_url": photo["photographer_url"],
        "photo_page": photo_page,
        "alt": title[:125],
        "credit": f"Photo by {photographer} on Unsplash",
        "hotlink": True,  # must NOT be downloaded/cached locally
        "decision": photo.get("_image_decision", {}),
        "intent": photo.get("_image_visual_intent", stock_queries[0][2].intent.to_dict()),
        "brief": photo.get("_image_visual_brief", {}),
        "visual_judge": photo.get("_image_visual_judge", {}),
        "concept": photo.get("_image_concept", selected_query),
    }
    result.update(stock_decision_fields("unsplash", result, selected_query))
    return finish(result)


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
        key_points = list(article.get("key_points") or [])

        result, provider_result = fetch_image_for_article(
            title,
            category,
            summary=article.get("summary", "") or "",
            key_points=key_points,
            content=article.get("content", "") or "",
            source_evidence=str(article.get("source_text") or article.get("research") or ""),
            inter_request_delay=delay,
            return_result=True,
        )
        set_provider_result(article, provider_result)

        if result:
            article["image"] = result["url"]
            article["image_thumb"] = result["thumb_url"]
            article["image_alt"] = result["alt"]
            article["image_credit"] = result["credit"]
            article["image_source_url"] = result["photo_page"]
            article["image_caption"] = ""
            article["image_hotlink"] = True
            article.update({k: v for k, v in result.items() if k.startswith("image_")})
        else:
            category_fallback_fields = _load_category_fallback_fields()
            if category_fallback_fields is not None:
                article.update(category_fallback_fields(
                    category,
                    reason="stock candidates unavailable or rejected",
                ))

    return articles
