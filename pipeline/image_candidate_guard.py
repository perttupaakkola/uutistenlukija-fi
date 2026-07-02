"""Image Flow v2 guardrails for article hero images.

Keep this provider-neutral. Unsplash, Pexels, generated fallback, and publish
gates all use the same intent and scoring vocabulary so a weak stock candidate
does not become a published frontmatter value by accident.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any


ACCEPT_THRESHOLD = 55
MISMATCH_SCORE = 0

WINTER_TERMS = {
    "snow", "snowy", "snowfall", "snowstorm", "winter", "ice", "icy",
    "frozen", "frost", "frosty", "blizzard", "sleet",
    "lumi", "luminen", "talvi", "jää", "jaassa", "jäinen", "pakkanen",
}

RAIN_TERMS = {
    "rain", "rainy", "rainfall", "shower", "showers", "downpour",
    "wet", "storm", "stormy", "thunder", "thunderstorm",
    "sade", "sateinen", "sadekuuro", "ukkonen", "myrsky",
}

SUN_TERMS = {
    "sun", "sunny", "sunshine", "clear sky", "bright", "summer",
    "aurinko", "aurinkoinen", "pouta", "kesä",
}

HEAT_TERMS = {
    "heat", "hot", "heatwave", "helte", "helteinen", "kuuma",
}

COLD_TERMS = {
    "cold", "cool", "chilly", "viileä", "viilenee", "kylmä",
}

WEATHER_TERMS = WINTER_TERMS | RAIN_TERMS | SUN_TERMS | HEAT_TERMS | COLD_TERMS | {
    "weather", "forecast", "cloud", "cloudy", "sää", "ennuste", "pilvi",
}

PERSON_IMAGE_TERMS = {
    "portrait", "headshot", "person", "people", "man", "woman", "boy", "girl",
    "businessman", "businesswoman", "politician", "leader", "face", "actor",
    "athlete", "customer", "employee", "crowd", "henkilö", "ihminen",
}

SENSITIVE_TERMS = {
    "rikos", "murha", "kuolema", "kuoli", "surma", "ampuminen", "oikeus",
    "sota", "isku", "hyökkäys", "uhri", "rauniot", "onnettomuus", "terror",
    "crime", "murder", "death", "shooting", "court", "war", "attack",
    "victim", "disaster", "accident",
}

CATEGORY_SETTINGS = {
    "Kotimaa": "Finnish public life or neutral Finnish landscape",
    "Ulkomaat": "international context without implying a specific event scene",
    "Talous": "business, finance, offices, documents, charts, or economy",
    "Teknologia": "technology, devices, software, data, or abstract digital work",
    "Urheilu": "sports venue, equipment, training, or competition atmosphere",
    "Kulttuuri": "arts, media, stage, books, music, or cinema",
    "Tiede": "research, laboratory, nature, space, or scientific instruments",
}


@dataclass(frozen=True)
class ImageIntent:
    subject: str
    setting: str
    season_time: str
    must_have: list[str]
    must_not: list[str]
    stock_ok: bool
    generated_ok: bool
    safety_mode: str
    style_preference: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateDecision:
    provider: str
    candidate_id: str
    source_url: str
    score: int
    accepted: bool
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _tokens(*parts: str) -> set[str]:
    text = " ".join(part or "" for part in parts).lower()
    words = set(re.findall(r"[\wäöå+-]+", text, flags=re.IGNORECASE))
    phrases = {phrase for phrase in ("clear sky",) if phrase in text}
    return words | phrases


def _candidate_text(candidate: dict[str, Any]) -> str:
    values: list[str] = []
    for key in (
        "alt", "alt_description", "description", "photo_page", "pexels_url",
        "url", "url_full", "url_regular", "url_small", "url_thumb",
        "photographer", "photographer_url",
    ):
        value = candidate.get(key)
        if value:
            values.append(str(value))
    return " ".join(values)


def _named_person_like(text: str) -> bool:
    # Finnish article titles often capitalize only proper names. Two adjacent
    # capitalized words is a conservative enough proxy for stock-person safety.
    return bool(re.search(r"\b[A-ZÅÄÖ][a-zåäö]+(?:\s+[A-ZÅÄÖ][a-zåäö]+)+\b", text or ""))


def build_image_intent(
    title: str,
    category: str = "",
    *,
    summary: str = "",
    key_points: list[str] | None = None,
    content: str = "",
    query: str = "",
) -> ImageIntent:
    """Derive conservative visual intent from article fields."""
    key_points = key_points or []
    article_text = " ".join([title or "", summary or "", " ".join(key_points), content or ""])
    article_tokens = _tokens(article_text, query)

    must_have: list[str] = []
    must_not: list[str] = []
    season_time = "neutral"
    safety_mode = "normal"
    stock_ok = True
    generated_ok = True

    if article_tokens & WEATHER_TERMS:
        must_have.append("weather")
    if article_tokens & SUN_TERMS:
        must_have.append("sunny or bright outdoor weather")
        must_not.extend(["snow", "winter", "rainstorm"])
        season_time = "summer or non-winter"
    if article_tokens & RAIN_TERMS:
        must_have.append("rain or clouds")
        must_not.append("snow")
    if article_tokens & HEAT_TERMS:
        must_have.append("warm weather")
        must_not.extend(["snow", "ice", "cold"])
        season_time = "summer or hot"
    if article_tokens & WINTER_TERMS:
        must_have.append("winter conditions")
        season_time = "winter"

    named_person = _named_person_like(article_text)
    sensitive = bool(article_tokens & SENSITIVE_TERMS)
    if named_person or sensitive:
        safety_mode = "illustration_only"
        generated_ok = True
        if named_person:
            must_not.append("generic person portrait or lookalike")
        if sensitive:
            must_not.append("realistic victim, crime, attack, or disaster scene")

    subject_terms = list(_tokens(title))[:5]
    subject = " ".join(subject_terms) or (category or "news")
    setting = CATEGORY_SETTINGS.get(category, CATEGORY_SETTINGS.get(category.title(), "neutral news context"))

    return ImageIntent(
        subject=subject,
        setting=setting,
        season_time=season_time,
        must_have=list(dict.fromkeys(must_have)),
        must_not=list(dict.fromkeys(must_not)),
        stock_ok=stock_ok,
        generated_ok=generated_ok,
        safety_mode=safety_mode,
        style_preference="editorial illustration preferred for unsafe specifics",
    )


def _source_id(candidate: dict[str, Any]) -> tuple[str, str]:
    candidate_id = str(candidate.get("id") or "unknown")
    source_url = str(candidate.get("photo_page") or candidate.get("pexels_url") or candidate.get("url") or "")
    return candidate_id, source_url


def score_image_candidate(
    candidate: dict[str, Any],
    *,
    intent: ImageIntent,
    query: str,
    title: str = "",
    summary: str = "",
    key_points: list[str] | None = None,
    content: str = "",
    provider: str = "image",
) -> CandidateDecision:
    """Score and vet one stock candidate against the article intent."""
    article_tokens = _tokens(title, summary, " ".join(key_points or []), content, query)
    query_tokens = _tokens(query)
    candidate_tokens = _tokens(_candidate_text(candidate))
    candidate_id, source_url = _source_id(candidate)

    score = 50
    reasons: list[str] = []

    if not candidate_tokens:
        score += 5
        reasons.append("candidate has no semantic metadata")
    else:
        shared = (article_tokens | query_tokens) & candidate_tokens
        if shared:
            score += min(25, 5 * len(shared))
            reasons.append(f"metadata matches {', '.join(sorted(shared)[:5])}")

    weather_cues = candidate_tokens & WEATHER_TERMS
    if weather_cues and (article_tokens | query_tokens) & WEATHER_TERMS:
        score += 10
        reasons.append("weather metadata matches visual intent")
    if candidate_tokens & SUN_TERMS and ((article_tokens | query_tokens) & SUN_TERMS):
        score += 10
        reasons.append("sunny metadata matches visual intent")
    if candidate_tokens & RAIN_TERMS and ((article_tokens | query_tokens) & RAIN_TERMS):
        score += 10
        reasons.append("rain metadata matches visual intent")

    article_is_weather = bool((article_tokens | query_tokens) & WEATHER_TERMS)
    article_allows_winter = bool(article_tokens & WINTER_TERMS)
    article_allows_rain = bool(article_tokens & RAIN_TERMS)
    article_requests_sun = bool(query_tokens & SUN_TERMS) or bool(article_tokens & SUN_TERMS)
    article_requests_heat = bool(query_tokens & HEAT_TERMS) or bool(article_tokens & HEAT_TERMS)

    hard_rejects: list[str] = []
    if article_is_weather and not article_allows_winter and candidate_tokens & WINTER_TERMS:
        hard_rejects.append("winter metadata contradicts non-winter weather story")
    if article_requests_sun and not article_allows_rain and candidate_tokens & RAIN_TERMS:
        hard_rejects.append("rain/storm metadata contradicts sunny weather story")
    if article_requests_sun and candidate_tokens & WINTER_TERMS:
        hard_rejects.append("winter metadata contradicts sunny weather query")
    if article_requests_heat and candidate_tokens & (WINTER_TERMS | COLD_TERMS):
        hard_rejects.append("cold/winter metadata contradicts heat weather story")
    if article_allows_rain and not article_allows_winter and candidate_tokens & WINTER_TERMS:
        hard_rejects.append("winter metadata contradicts rain-only weather story")
    if intent.safety_mode == "illustration_only" and candidate_tokens & PERSON_IMAGE_TERMS:
        hard_rejects.append("generic person/lookalike metadata is unsafe for named-person or sensitive story")

    if hard_rejects:
        return CandidateDecision(provider, candidate_id, source_url, MISMATCH_SCORE, False, hard_rejects)

    if any(term in candidate_tokens for term in {"generic", "abstract", "background"}):
        score -= 8
        reasons.append("generic stock metadata")

    accepted = intent.stock_ok and score >= ACCEPT_THRESHOLD
    if not accepted:
        reasons.append(f"score below threshold {ACCEPT_THRESHOLD}")
    elif not reasons:
        reasons.append("accepted")

    return CandidateDecision(provider, candidate_id, source_url, score, accepted, reasons)


def vet_image_candidate(
    candidate: dict[str, Any],
    *,
    query: str,
    title: str = "",
    summary: str = "",
    key_points: list[str] | None = None,
    content: str = "",
) -> tuple[bool, str]:
    """Backward-compatible boolean vetting API."""
    intent = build_image_intent(title, summary=summary, key_points=key_points, content=content, query=query)
    decision = score_image_candidate(
        candidate,
        intent=intent,
        query=query,
        title=title,
        summary=summary,
        key_points=key_points,
        content=content,
    )
    return decision.accepted, "; ".join(decision.reasons)


def filter_image_candidates(
    candidates: list[dict[str, Any]],
    *,
    query: str,
    title: str = "",
    summary: str = "",
    key_points: list[str] | None = None,
    content: str = "",
    provider: str = "image",
    intent: ImageIntent | None = None,
    return_decisions: bool = False,
) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], list[CandidateDecision]]:
    """Filter stock candidates, preserving scored decision evidence."""
    intent = intent or build_image_intent(
        title,
        summary=summary,
        key_points=key_points,
        content=content,
        query=query,
    )
    accepted: list[dict[str, Any]] = []
    decisions: list[CandidateDecision] = []
    for candidate in candidates:
        decision = score_image_candidate(
            candidate,
            intent=intent,
            query=query,
            title=title,
            summary=summary,
            key_points=key_points,
            content=content,
            provider=provider,
        )
        decisions.append(decision)
        if decision.accepted:
            enriched = dict(candidate)
            enriched["_image_decision"] = decision.to_dict()
            enriched["_image_visual_intent"] = intent.to_dict()
            accepted.append(enriched)
        else:
            print(f"[{provider}] Rejected image candidate {decision.candidate_id}: {'; '.join(decision.reasons)}")

    if return_decisions:
        return accepted, decisions
    return accepted


def category_fallback_fields(category: str, *, reason: str) -> dict[str, Any]:
    """Neutral fallback frontmatter fields for a category placeholder."""
    category = category or "Kotimaa"
    cat_slug = category.lower()
    return {
        "image": f"/images/categories/{cat_slug}.jpg",
        "image_thumb": f"/images/categories/{cat_slug}.jpg",
        "image_alt": f"{category}-uutiset",
        "image_credit": "",
        "image_source_url": "",
        "image_caption": "",
        "image_hotlink": False,
        "image_category_fallback": True,
        "image_source": "category_fallback",
        "image_decision": {
            "source": "category_fallback",
            "accepted": True,
            "reason": reason,
        },
    }


def stock_decision_fields(provider: str, result: dict[str, Any], query: str) -> dict[str, Any]:
    """Frontmatter-safe stock decision evidence."""
    decision = result.get("decision") or result.get("_image_decision") or {}
    intent = result.get("intent") or result.get("_image_visual_intent") or {}
    return {
        "image_source": provider,
        "image_visual_intent": intent,
        "image_decision": {
            "source": provider,
            "query": query,
            "accepted": True,
            "score": decision.get("score"),
            "candidate_id": decision.get("candidate_id"),
            "source_url": decision.get("source_url"),
            "reasons": decision.get("reasons", []),
        },
        "image_quality_score": decision.get("score"),
        "image_category_fallback": False,
    }
