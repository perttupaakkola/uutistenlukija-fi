#!/usr/bin/env python3
"""Small deterministic category guards shared by pipeline category writers."""

from __future__ import annotations

import re


_SCHOOL_POLICE_TERMS = re.compile(
    r"\b("
    r"poliisi|poliisin|poliisia|poliisioperaatio|rikos|rikoksen|rikoksia|rikosnimike|"
    r"ase|aseistaut|ampu|ammu|ammuskel|räjäh|kiinni|pidätt|vangit|tuomio|"
    r"koulu|koulussa|koulun|oppilaitos|oppilaitoks|ammattikorkeakoulu|"
    r"samk|kampus|päiväkoti|yhtenäiskoulu"
    r")",
    re.IGNORECASE,
)

_SCIENCE_ANGLE_TERMS = re.compile(
    r"\b("
    r"tiede|tieteell|tutkimus(?!laitos|laitoks)|tutkimuksessa|tutkija|tutkijat|professori|"
    r"väitös|väitöskirja|vertaisarvio|tiedelehti|julkaistu|aineisto|"
    r"menetelmä|laboratorio|havaitsi|selvitti|löysivät|analyysi"
    r")",
    re.IGNORECASE,
)

_BUSINESS_SIGNAL_GROUPS = (
    re.compile(r"\b(?:yrity\w*|yhtiö\w*|ravintol\w*)\b", re.IGNORECASE),
    re.compile(r"\b(?:yrittäj\w*|ravintoloitsij\w*)\b", re.IGNORECASE),
    re.compile(r"\b(?:(?:tulos(?:ta)?|tulok\w*)|liikevaih\w*|käyttökate\w*|konkurss\w*|markkin\w*|pörss\w*|osak\w*)\b", re.IGNORECASE),
    re.compile(r"\b(?:kasv\w*|kannattav\w*|investoin\w*|myynt\w*|marginaal\w*|analyytik\w*)\b", re.IGNORECASE),
)


def category_text(article: dict, *extra_parts: str) -> str:
    """Return compact article text used for deterministic category guards."""
    fields = (
        "title",
        "original_title",
        "description",
        "summary",
        "content",
        "source_text",
        "research",
        "research_text",
    )
    parts = [str(article.get(field) or "") for field in fields]
    parts.extend(str(part or "") for part in extra_parts)
    return " ".join(part for part in parts if part).casefold()


def protect_tiede_category(category: str, text: str) -> str:
    """Keep school/police/crime incidents out of Tiede without a science angle."""
    if str(category or "").strip() != "Tiede":
        return category
    haystack = str(text or "").casefold()
    if _SCHOOL_POLICE_TERMS.search(haystack) and not _SCIENCE_ANGLE_TERMS.search(haystack):
        return "Kotimaa"
    return category


def protect_business_category(category: str, text: str) -> str:
    """Route only strongly signalled company/business stories to Talous.

    Two distinct signal groups are required so a lone mention of a company,
    entrepreneur, result, or market cannot override an otherwise valid topic.
    This is intentionally a category guard, not a quality-gate bypass.
    """
    haystack = str(text or "").casefold()
    matched_groups = sum(bool(pattern.search(haystack)) for pattern in _BUSINESS_SIGNAL_GROUPS)
    return "Talous" if matched_groups >= 2 else category


def contains_token(text: str, token: str) -> bool:
    """Match a category token as a word/stem, never inside another word."""
    haystack = str(text or "").casefold()
    needle = str(token or "").casefold().strip()
    if not needle:
        return False
    right_boundary = r"(?![a-zäöå])" if len(needle) <= 3 else ""
    return bool(re.search(rf"(?<![a-zäöå]){re.escape(needle)}{right_boundary}", haystack))
