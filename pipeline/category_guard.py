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
