"""Semantic guardrails for stock image candidates.

The provider APIs can return technically relevant but editorially misleading
photos. Keep this layer provider-neutral so Unsplash and Pexels fail closed in
the same way before an image is marked used or written to frontmatter.
"""

from __future__ import annotations

import re
from typing import Any


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


def vet_image_candidate(
    candidate: dict[str, Any],
    *,
    query: str,
    title: str = "",
    summary: str = "",
    key_points: list[str] | None = None,
    content: str = "",
) -> tuple[bool, str]:
    """Return whether a stock image candidate is safe for the article context."""
    article_tokens = _tokens(title, summary, " ".join(key_points or []), content)
    query_tokens = _tokens(query)
    candidate_tokens = _tokens(_candidate_text(candidate))

    if not candidate_tokens:
        return True, "no candidate metadata"

    article_is_weather = bool((article_tokens | query_tokens) & WEATHER_TERMS)
    article_allows_winter = bool(article_tokens & WINTER_TERMS)
    article_allows_rain = bool(article_tokens & RAIN_TERMS)
    article_requests_sun = bool(query_tokens & SUN_TERMS) or bool(article_tokens & SUN_TERMS)
    article_requests_heat = bool(query_tokens & HEAT_TERMS) or bool(article_tokens & HEAT_TERMS)

    if article_is_weather and not article_allows_winter and candidate_tokens & WINTER_TERMS:
        return False, "winter metadata contradicts non-winter weather story"

    if article_requests_sun and not article_allows_rain and candidate_tokens & RAIN_TERMS:
        return False, "rain/storm metadata contradicts sunny weather story"

    if article_requests_sun and candidate_tokens & WINTER_TERMS:
        return False, "winter metadata contradicts sunny weather query"

    if article_requests_heat and candidate_tokens & (WINTER_TERMS | COLD_TERMS):
        return False, "cold/winter metadata contradicts heat weather story"

    if article_allows_rain and not article_allows_winter and candidate_tokens & WINTER_TERMS:
        return False, "winter metadata contradicts rain-only weather story"

    return True, "accepted"


def filter_image_candidates(
    candidates: list[dict[str, Any]],
    *,
    query: str,
    title: str = "",
    summary: str = "",
    key_points: list[str] | None = None,
    content: str = "",
    provider: str = "image",
) -> list[dict[str, Any]]:
    """Filter stock candidates and log rejected semantic mismatches."""
    accepted: list[dict[str, Any]] = []
    for candidate in candidates:
        ok, reason = vet_image_candidate(
            candidate,
            query=query,
            title=title,
            summary=summary,
            key_points=key_points,
            content=content,
        )
        if ok:
            accepted.append(candidate)
        else:
            ident = candidate.get("id") or candidate.get("photo_page") or candidate.get("pexels_url") or "unknown"
            print(f"[{provider}] Rejected image candidate {ident}: {reason}")
    return accepted
