#!/usr/bin/env python3
"""Independently audit article-image grounding and recent stock reuse.

Article truth is derived only from editorial article fields and, when a packet
is supplied, its source evidence. Persisted image intent, retrieval queries,
article-written alt text, and earlier acceptance scores are evidence to audit,
never evidence that an image is relevant.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

from image_state import canonical_image_identity, image_identity_aliases  # noqa: E402


PROJECT_ROOT = Path(__file__).resolve().parents[1]
POSTS_DIR = PROJECT_ROOT / "content" / "posts"

_PROVIDER_HOSTS = {
    "unsplash": ("unsplash.com", "www.unsplash.com"),
    "pexels": ("pexels.com", "www.pexels.com"),
}
_PROVIDER_PAGE_ROOTS = {"unsplash": "photos", "pexels": "photo"}
_AUDIT_FALLBACK_PROMPT_VERSION_RE = re.compile(
    r"^image-flow-v(?P<major>\d+)(?:-[a-z0-9]+)*-\d{4}-\d{2}-\d{2}$"
)
_PROVIDER_PATH_NOISE = {
    "a", "an", "and", "at", "by", "filled", "for", "from", "in", "is",
    "of", "on", "or", "photo", "photos", "picture", "the", "to", "top",
    "with", "www", "unsplash", "pexels", "com",
}
_GROUNDING_NOISE = {
    "a", "an", "and", "are", "at", "by", "for", "from", "in", "is", "of",
    "on", "or", "the", "to", "with", "without", "news", "neutral", "context",
    "public", "life", "generic", "story", "conditions",
    "ja", "joka", "jonka", "kun", "kuin", "mutta", "myös", "on", "tai", "että",
}
_TITLE_NOISE = {
    *_GROUNDING_NOISE,
    "arvioi", "esitetään", "hallitus", "kertoi", "kertoo", "mukaan", "uusi",
    "uutinen", "vaatii", "vuonna", "yli",
}

# This vocabulary intentionally lives in the audit. Importing the runtime
# retrieval guard here would make a defect in that guard self-certifying.
_AUDIT_WEATHER_EXACT = {
    "sää", "sään", "säätä", "weather", "meteorology",
}
_AUDIT_WEATHER_PREFIXES = (
    "sääennust", "säätila", "sääolosuh", "lämpötil", "helle",
    "sademäär", "sate", "ukkos", "aurinko", "pilvi", "lumisade",
    "temperature", "heatwave", "sunny", "cloud", "rain", "storm",
)
_AUDIT_WINTER_EXACT = {
    "talvi", "talven", "talvella", "winter", "snow", "ice", "jäinen", "jäätä",
}
_AUDIT_WINTER_PREFIXES = ("talvi", "lum", "jäis", "winter", "snow", "icy", "ice")
_AUDIT_SUMMER_EXACT = {"kesä", "kesän", "kesällä", "summer", "elokuu", "august"}
_AUDIT_SUMMER_PREFIXES = ("kesä", "helle", "summer", "elokuu", "august")
_AUDIT_SENSITIVE_PREFIXES = (
    "murh", "tapp", "tapet", "kuole", "väkivalt", "pahoinpit", "rikos",
    "puukot", "ryöst", "kavall", "raisk", "seksuaal", "hyökkä", "ohjus",
    "sotilas", "sodan", "sota",
    "konflikt", "räjäh", "pommi", "tulipal", "onnettom", "uhri", "sairau",
    "tervey", "tauti", "hoito", "syöp", "diabet", "epidem", "pandem",
    "sikarutto", "murder", "killed", "death", "violence", "assault", "crime",
    "rape", "attack", "missile", "military", "war", "conflict", "explosion",
    "bomb", "victim", "disease", "health", "cancer", "diabetes", "epidemic",
)
_AUDIT_SENSITIVE_EXACT = {"iski", "isku", "iskut", "strike", "strikes"}

_NON_PERSON_NAME_WORDS = {
    "Analyysi", "Etelä", "Euroopan", "Finanssiala", "Hallitus", "Iran",
    "Itä", "Karjalan", "Keski", "Kotimaa", "Kuva", "Länsi", "Pohjois",
    "Shutterstock", "Suomen", "Talous", "Tampereen", "Venäjä", "Yhdysvallat",
}
_AUDIT_NON_PERSON_PREFIXES = (
    "hallitu", "ministeriö", "poliisi", "rahastoyhtiö", "yhtiö", "yliopisto",
)
_AUDIT_PERSON_ACTION_PREFIXES = (
    "allekirjoit", "arvostel", "ehdott", "erosi", "ilmoit", "johti",
    "komment", "kertoi", "kiisti", "kuoli", "lupasi", "myönsi", "nimitt",
    "sanoi", "syytti", "tapasi", "vaati", "vierail", "voitti",
)
_AUDIT_PERSON_ROLE_TOKENS = {
    "johtaja", "kuningas", "ministeri", "pääministeri", "presidentti",
    "puheenjohtaja", "toimitusjohtaja",
}

_AUDIT_LOCATION_ALIASES: dict[str, tuple[str, ...]] = {
    "finland": ("suom*", "finland", "finnish"),
    "helsinki": ("helsing*", "helsinki"),
    "tampere": ("tamper*", "tampere"),
    "turku": ("turku", "turu*"),
    "oulu": ("oulu*",),
    "vaasa": ("vaasa*",),
    "vantaa": ("vantaa", "vantaan", "vantaalla"),
    "kouvola": ("kouvol*",),
    "nurmes": ("nurmes*",),
    "joensuu": ("joensu*",),
    "imatra": ("imatra*",),
    "karjala": ("karjal*",),
    "lappi": ("lappi", "lapin", "lapissa"),
    "tornio": ("tornio*",),
    "seinäjoki": ("seinäjo*",),
    "pyhtää": ("pyhtää*",),
    "salo": ("salo", "salon", "salossa"),
    "savonlinna": ("savonlinn*",),
    "loviisa": ("loviisa*",),
    "paris": ("paris", "pariisi*"),
    "france": ("france", "french", "ranska*"),
    "rome": ("rome", "rooma*"),
    "italy": ("italy", "italian", "italia*"),
    "london": ("london*",),
    "united kingdom": ("britain", "british", "england", "english", "uk"),
    "spain": ("spain", "spanish", "espanja*"),
    "iran": ("iran*",),
    "jordan": ("jordan*",),
    "larak": ("larak*",),
    "united states": ("usa", "u.s.", "yhdysvall*", "american"),
    "germany": ("germany", "german", "saksa*"),
    "russia": ("russia", "russian", "venäj*"),
    "switzerland": ("switzerland", "swiss", "sveits*"),
    "paraguay": ("paraguay*",),
    "leipzig": ("leipzig*",),
    "europe": ("europe", "european", "euroop*"),
}
_AUDIT_MULTI_TOKEN_LOCATION_ALIASES: dict[str, tuple[tuple[str, ...], ...]] = {
    "new york": (("new", "york"),),
    "united kingdom": (("united", "kingdom"),),
    "united states": (("united", "states"),),
}
_AUDIT_LOCATION_PARENTS = {
    "helsinki": "finland", "tampere": "finland", "turku": "finland",
    "oulu": "finland", "vaasa": "finland", "vantaa": "finland",
    "kouvola": "finland", "nurmes": "finland", "joensuu": "finland",
    "imatra": "finland", "karjala": "finland", "lappi": "finland",
    "tornio": "finland", "seinäjoki": "finland", "pyhtää": "finland",
    "salo": "finland", "savonlinna": "finland", "loviisa": "finland",
    "paris": "france", "rome": "italy", "london": "united kingdom",
    "new york": "united states",
}
_AUDIT_COUNTRY_SLUG_SUFFIXES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("united", "kingdom"), "united kingdom"),
    (("united", "states"), "united states"),
    (("england",), "united kingdom"),
    (("finland",), "finland"),
    (("france",), "france"),
    (("italy",), "italy"),
    (("spain",), "spain"),
    (("uk",), "united kingdom"),
    (("usa",), "united states"),
)

# Each group must have at least one matching cue. A trailing * is a token-stem
# marker, never a substring search over the raw article.
_AUDIT_CONCEPT_RULES: tuple[tuple[str, tuple[tuple[str, ...], ...]], ...] = (
    (
        "financial regulation, investment funds, or compliance documents",
        ((
            "finans*", "rahasto*", "sijoituspalvel*", "sisäpiirirekister*",
            "sääntel*", "compliance", "financial", "regulation", "regulatory",
        ),),
    ),
    (
        "railway tracks, rail infrastructure, or railway construction",
        ((
            "rautatie*", "rataverk*", "raide*", "rata", "radan", "radalle",
            "rail", "rails", "railway*", "railroad*", "train*", "tracks",
        ),),
    ),
    (
        "peatland, wetland restoration, or forestry land",
        (("turve*", "turpe*", "peat*", "wetland*", "metsity*", "vettämi*"),),
    ),
    (
        "boat repair or small craft restoration",
        (("vene*", "boat*", "craft"), ("korja*", "kunnost*", "repair*", "restor*")),
    ),
    (
        "military conflict, missile strike, or attack",
        ((
            "ohjus*", "sotilas*", "sota", "sodan", "konflikt*", "hyökkä*",
            "iski", "isku", "iskut", "military", "war", "conflict", "missile*",
            "attack*", "strike*", "drone*", "droon*",
        ),),
    ),
    (
        "book, television, or screen production",
        (("kirja*", "dekkari*", "televisio*", "tv", "hollywood*", "book*", "screen*"),),
    ),
    (
        "university, study, or student admissions",
        (("korkeakoulu*", "yliopisto*", "opiskel*", "yhteishaku*", "university", "student*"),),
    ),
    (
        "health care, hospital, or disease monitoring",
        ((
            "tervey*", "sairau*", "sairaala*", "hoito*", "syöp*", "diabet*",
            "tauti*", "health*", "hospital*", "disease*", "cancer*",
        ),),
    ),
)

_AUDIT_CONCEPT_ANCHORS: dict[str, set[str]] = {
    "financial regulation, investment funds, or compliance documents": {
        "financial", "finance", "regulation", "regulatory", "compliance",
        "investment", "fund", "funds", "documents", "registry", "register",
    },
    "railway tracks, rail infrastructure, or railway construction": {
        "rail", "rails", "railway", "railways", "railroad", "railroads",
        "train", "trains", "track", "tracks",
    },
    "peatland, wetland restoration, or forestry land": {
        "peat", "peatland", "wetland", "wetlands", "forest", "forestry",
    },
    "boat repair or small craft restoration": {
        "boat", "boats", "craft", "repair", "restoration", "workshop",
    },
    "military conflict, missile strike, or attack": {
        "military", "conflict", "missile", "missiles", "attack", "strike",
        "war", "drone",
    },
}

_AUDIT_GENERIC_CONCEPT_TOKENS = {
    "business", "company", "conditions", "construction", "context", "generic",
    "image", "industry", "news", "people", "person", "production", "public",
    "scene", "story",
}


@dataclass(frozen=True)
class AuditTruth:
    subject: str
    season_time: str
    must_have: tuple[str, ...]
    acceptable_concepts: tuple[str, ...]
    locations: tuple[str, ...]
    named_people: tuple[str, ...]
    named_person: bool
    sensitive_story: bool
    ambiguous: bool
    stock_ok: bool
    weather_story: bool
    evidence_terms: tuple[str, ...]


@dataclass(frozen=True)
class ProviderPageEvidence:
    tokens: frozenset[str]
    locations: frozenset[str]
    error: str = ""


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return value[1:-1]
        return parsed if isinstance(parsed, str) else str(parsed)
    return value


def _frontmatter_from_text(text: str) -> dict[str, Any]:
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}

    lines = parts[1].splitlines()
    data: dict[str, Any] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line or line[0].isspace() or ":" not in line:
            index += 1
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if raw_value in {"|", ">"}:
            block: list[str] = []
            index += 1
            while index < len(lines) and (not lines[index] or lines[index][0].isspace()):
                block.append(lines[index].strip())
                index += 1
            data[key] = ("\n" if raw_value == "|" else " ").join(block).strip()
            continue
        if not raw_value:
            values: list[Any] = []
            index += 1
            while index < len(lines) and (not lines[index] or lines[index][0].isspace()):
                item = lines[index].strip()
                if item.startswith("- "):
                    values.append(_parse_scalar(item[2:]))
                index += 1
            data[key] = values
            continue
        data[key] = _parse_scalar(raw_value)
        index += 1

    categories = data.get("categories")
    if isinstance(categories, list) and categories:
        data["category"] = str(categories[0])
    elif isinstance(categories, str):
        data["category"] = categories
    return data


def _frontmatter(path: Path) -> dict[str, Any]:
    try:
        return _frontmatter_from_text(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return {}


def _body_from_text(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2]
    return text


def _body(path: Path) -> str:
    try:
        return _body_from_text(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return ""


def _text(fields: Mapping[str, Any], key: str) -> str:
    value = fields.get(key)
    return str(value).strip() if value is not None and not isinstance(value, (list, dict)) else ""


def _string_list(fields: Mapping[str, Any], key: str) -> list[str]:
    value = fields.get(key)
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _is_true(value: Any) -> bool:
    return value is True or str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _has_value(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, Mapping)):
        return bool(value)
    return True


def _supported_fallback_prompt_version(value: str) -> bool:
    match = _AUDIT_FALLBACK_PROMPT_VERSION_RE.fullmatch(value.strip().lower())
    return bool(match and int(match.group("major")) >= 2)


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _article_truth(path: Path) -> tuple[dict[str, Any], str, list[str]]:
    errors: list[str] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {}, "", [f"article evidence unavailable: {exc.__class__.__name__}"]
    fields = _frontmatter_from_text(text)
    body = _body_from_text(text).strip()
    if not fields:
        errors.append("article evidence unavailable: missing or invalid front matter")
    if not _text(fields, "title"):
        errors.append("article evidence unavailable: missing title")
    date_value = _text(fields, "date")
    if not date_value:
        errors.append("article evidence unavailable: missing date")
    else:
        try:
            datetime.fromisoformat(date_value.replace("Z", "+00:00"))
        except ValueError:
            errors.append("article evidence unavailable: invalid date")
    if not body:
        errors.append("article evidence unavailable: missing body")
    return fields, body, errors


def _combined_summary(fields: Mapping[str, Any]) -> str:
    values: list[str] = []
    for key in ("description", "summary"):
        value = _text(fields, key)
        if value and value not in values:
            values.append(value)
    return " ".join(values)


def _word_tokens(*parts: str) -> set[str]:
    return set(re.findall(r"[a-zåäö]+", " ".join(parts).lower(), flags=re.IGNORECASE))


def _token_matches_cue(token: str, cue: str) -> bool:
    return token.startswith(cue[:-1]) if cue.endswith("*") else token == cue


def _matching_tokens(
    tokens: set[str],
    exact: set[str],
    prefixes: tuple[str, ...],
) -> set[str]:
    return {
        token
        for token in tokens
        if token in exact or any(token.startswith(prefix) for prefix in prefixes)
    }


def _matching_concepts(
    tokens: set[str],
    primary_tokens: set[str],
) -> tuple[list[str], set[str]]:
    concepts: list[str] = []
    evidence: set[str] = set()
    for concept, groups in _AUDIT_CONCEPT_RULES:
        group_hits = [
            {
                token
                for token in tokens
                if any(_token_matches_cue(token, cue) for cue in group)
            }
            for group in groups
        ]
        primary_group_hits = [
            {
                token
                for token in primary_tokens
                if any(_token_matches_cue(token, cue) for cue in group)
            }
            for group in groups
        ]
        # A central-field match is enough. Body/source-only concepts need at
        # least two independent cue tokens so an incidental attribution such
        # as "valtiollisen television mukaan" cannot become image truth.
        source_evidence_is_concrete = len(set().union(*group_hits)) >= max(2, len(groups))
        if all(group_hits) and (all(primary_group_hits) or source_evidence_is_concrete):
            concepts.append(concept)
            for hits in group_hits:
                evidence.update(hits)
    return concepts, evidence


def _locations_from_tokens(tokens: set[str]) -> set[str]:
    locations: set[str] = set()
    for canonical, aliases in _AUDIT_LOCATION_ALIASES.items():
        if any(
            _token_matches_cue(token, alias)
            for token in tokens
            for alias in aliases
        ):
            locations.add(canonical)
    for canonical, aliases in _AUDIT_MULTI_TOKEN_LOCATION_ALIASES.items():
        if any(set(alias) <= tokens for alias in aliases):
            locations.add(canonical)
    for location in tuple(locations):
        parent = _AUDIT_LOCATION_PARENTS.get(location)
        if parent:
            locations.add(parent)
    return locations


def _single_named_people(text: str, occupied_spans: list[tuple[int, int]]) -> list[str]:
    names: list[str] = []
    for match in re.finditer(r"\b[A-ZÅÄÖ][a-zåäö'-]{1,}\b", text or ""):
        if any(start <= match.start() and match.end() <= end for start, end in occupied_spans):
            continue
        value = match.group(0)
        lowered = value.lower()
        if value in _NON_PERSON_NAME_WORDS:
            continue
        if any(lowered.startswith(prefix) for prefix in _AUDIT_NON_PERSON_PREFIXES):
            continue
        if _locations_from_tokens({lowered}):
            continue

        after = (text or "")[match.end():]
        next_word_match = re.match(r"[\s,–—:-]+([A-Za-zÅÄÖåäö'-]+)", after)
        next_word = next_word_match.group(1).lower() if next_word_match else ""
        before_words = re.findall(r"[A-Za-zÅÄÖåäö'-]+", (text or "")[:match.start()])
        previous_word = before_words[-1].lower() if before_words else ""
        has_person_action = any(
            next_word.startswith(prefix) for prefix in _AUDIT_PERSON_ACTION_PREFIXES
        )
        has_person_role = previous_word in _AUDIT_PERSON_ROLE_TOKENS
        if (has_person_action or has_person_role) and value not in names:
            names.append(value)
    return names


def _named_people(text: str) -> list[str]:
    names: list[str] = []
    matches = list(re.finditer(
        r"\b[A-ZÅÄÖ][a-zåäö'-]{1,}(?:\s+[A-ZÅÄÖ][a-zåäö'-]{1,})+\b",
        text or "",
    ))
    for match in matches:
        value = match.group(0).strip()
        words = value.split()
        if any(word in _NON_PERSON_NAME_WORDS for word in words):
            continue
        if _locations_from_tokens(_word_tokens(value)):
            continue
        if words[-1].lower().endswith(("ssa", "ssä", "lla", "llä", "sta", "stä", "lle")):
            continue
        if value not in names:
            names.append(value)
    for value in _single_named_people(
        text,
        [(match.start(), match.end()) for match in matches],
    ):
        if value not in names:
            names.append(value)
    return names


def _derive_audit_truth(
    fields: Mapping[str, Any],
    body: str,
    *,
    source_evidence: str = "",
) -> AuditTruth:
    """Derive audit truth without retrieval queries, stored intent, or guard code."""
    title = _text(fields, "title")
    primary_parts = [
        title,
        _text(fields, "description"),
        _text(fields, "summary"),
        *_string_list(fields, "key_points"),
    ]
    all_parts = [*primary_parts, body, source_evidence]
    primary_text = " ".join(part for part in primary_parts if part)
    all_text = " ".join(part for part in all_parts if part)
    primary_tokens = _word_tokens(primary_text)
    all_tokens = _word_tokens(all_text)

    primary_weather = _matching_tokens(
        primary_tokens,
        _AUDIT_WEATHER_EXACT,
        _AUDIT_WEATHER_PREFIXES,
    )
    all_weather = _matching_tokens(
        all_tokens,
        _AUDIT_WEATHER_EXACT,
        _AUDIT_WEATHER_PREFIXES,
    )
    weather_story = bool(primary_weather) or len(all_weather) >= 2

    primary_winter = _matching_tokens(
        primary_tokens,
        _AUDIT_WINTER_EXACT,
        _AUDIT_WINTER_PREFIXES,
    )
    all_winter = _matching_tokens(
        all_tokens,
        _AUDIT_WINTER_EXACT,
        _AUDIT_WINTER_PREFIXES,
    )
    primary_summer = _matching_tokens(
        primary_tokens,
        _AUDIT_SUMMER_EXACT,
        _AUDIT_SUMMER_PREFIXES,
    )
    all_summer = _matching_tokens(
        all_tokens,
        _AUDIT_SUMMER_EXACT,
        _AUDIT_SUMMER_PREFIXES,
    )

    season_time = "neutral"
    if primary_winter or (weather_story and all_winter):
        season_time = "winter"
    elif primary_summer or (weather_story and all_summer):
        season_time = "summer or non-winter"

    concepts, concept_evidence = _matching_concepts(all_tokens, primary_tokens)
    must_have = list(concepts)
    acceptable_concepts = list(concepts)
    weather_evidence: set[str] = set()
    if weather_story:
        must_have.append("weather conditions")
        acceptable_concepts.append("weather conditions, sky, sun, clouds, rain, or temperature")
        weather_evidence.update(all_weather)
    if season_time == "winter":
        must_have.append("winter conditions")
        acceptable_concepts.append("snow, ice, or winter weather")
        weather_evidence.update(all_winter)
    elif season_time == "summer or non-winter":
        acceptable_concepts.append("sunny, warm, or non-winter outdoor weather")
        weather_evidence.update(all_summer)

    primary_names = _named_people(primary_text)
    all_names = _named_people(all_text)
    sensitive_tokens = {
        token
        for token in all_tokens
        if token in _AUDIT_SENSITIVE_EXACT
        or any(token.startswith(prefix) for prefix in _AUDIT_SENSITIVE_PREFIXES)
    }
    named_person = bool(primary_names) or any(
        len(re.findall(re.escape(name), all_text, flags=re.IGNORECASE)) >= 2
        for name in all_names
    )
    sensitive_story = bool(sensitive_tokens)
    locations = _locations_from_tokens(all_tokens)
    ambiguous = not acceptable_concepts

    evidence_terms = set(concept_evidence)
    evidence_terms.update(weather_evidence)
    evidence_terms.update(sensitive_tokens)
    return AuditTruth(
        subject=title,
        season_time=season_time,
        must_have=tuple(dict.fromkeys(must_have)),
        acceptable_concepts=tuple(dict.fromkeys(acceptable_concepts)),
        locations=tuple(sorted(locations)),
        named_people=tuple(dict.fromkeys(all_names)),
        named_person=named_person,
        sensitive_story=sensitive_story,
        ambiguous=ambiguous,
        stock_ok=not (named_person or sensitive_story or ambiguous),
        weather_story=weather_story,
        evidence_terms=tuple(sorted(evidence_terms)),
    )


def _packet_source_evidence(packet: Mapping[str, Any]) -> str:
    evidence: list[str] = []

    def add(value: Any) -> None:
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned and cleaned not in evidence:
                evidence.append(cleaned)

    for key in ("packet", "article", "original_article"):
        section = packet.get(key)
        if not isinstance(section, Mapping):
            continue
        add(section.get("source_text"))
        blocks = section.get("clean_source_blocks")
        if isinstance(blocks, list):
            for block in blocks:
                if isinstance(block, Mapping):
                    add(block.get("text"))
    return "\n\n".join(evidence)


def _normalized_provider(fields: Mapping[str, Any]) -> str:
    provider = _text(fields, "image_source").lower()
    if provider in {"unsplash", "pexels", "category_fallback", "generated"}:
        return provider
    for key in ("image_candidate_url", "image_source_url", "image"):
        try:
            host = urlsplit(_text(fields, key)).netloc.lower().split(":", 1)[0]
        except ValueError:
            continue
        if host == "unsplash.com" or host.endswith(".unsplash.com"):
            return "unsplash"
        if host == "pexels.com" or host.endswith(".pexels.com"):
            return "pexels"
    return provider or _text(fields, "image_source_type").lower()


def _stock_candidate(fields: Mapping[str, Any]) -> tuple[str, dict[str, Any], str]:
    provider = _normalized_provider(fields)
    candidate = {
        "image_candidate_id": _text(fields, "image_candidate_id") or _text(fields, "image_id"),
        "image_candidate_url": _text(fields, "image_candidate_url"),
        "image_source_url": _text(fields, "image_source_url"),
        "image": _text(fields, "image"),
    }
    identity = canonical_image_identity(provider, candidate)
    return provider, candidate, identity


def _semantic_tokens(value: str, *, noise: set[str]) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zåäö]+", (value or "").lower(), flags=re.IGNORECASE)
        if len(token) >= 3 and token not in noise
    }


def _provider_location_claims(slug_tokens: list[str]) -> set[str]:
    claims = _locations_from_tokens(set(slug_tokens))
    preposition_index = max(
        (index for index, token in enumerate(slug_tokens) if token in {"at", "in", "near"}),
        default=-1,
    )
    if preposition_index < 0:
        return claims

    tail = slug_tokens[preposition_index + 1:]
    for country_suffix, country in _AUDIT_COUNTRY_SLUG_SUFFIXES:
        suffix_length = len(country_suffix)
        if len(tail) <= suffix_length or tuple(tail[-suffix_length:]) != country_suffix:
            continue
        city_tokens = tail[:-suffix_length]
        if 1 <= len(city_tokens) <= 3 and all(
            token not in _PROVIDER_PATH_NOISE for token in city_tokens
        ):
            claims.add(" ".join(city_tokens))
            claims.add(country)
        break
    return claims


def _validated_provider_page(
    provider: str,
    source_url: str,
    candidate_id: str,
) -> tuple[tuple[str, str], str, str]:
    try:
        parsed = urlsplit(source_url)
        port = parsed.port
    except ValueError:
        return ("", ""), "", "source-page URL is malformed"

    if parsed.scheme.lower() != "https":
        return ("", ""), "", "source-page URL is not HTTPS"
    if parsed.username is not None or parsed.password is not None:
        return ("", ""), "", "source-page URL contains user information"
    if port not in {None, 443}:
        return ("", ""), "", "source-page URL uses a nonstandard port"

    host = (parsed.hostname or "").lower()
    if host not in _PROVIDER_HOSTS.get(provider, ()):
        return ("", ""), "", "source-page URL is not on the official provider web host"

    segments = [unquote(segment) for segment in (parsed.path or "").split("/") if segment]
    expected_root = _PROVIDER_PAGE_ROOTS.get(provider, "")
    if len(segments) != 2 or segments[0].lower() != expected_root:
        return ("", ""), "", f"source-page URL does not use /{expected_root}/<photo>"
    slug = segments[1]
    if not candidate_id:
        return ("", ""), "", "candidate ID is missing from provider evidence"
    if provider == "unsplash" and not re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate_id):
        return ("", ""), "", "Unsplash candidate ID has an invalid format"
    if provider == "pexels" and (
        not candidate_id.isdigit() or int(candidate_id) <= 0
    ):
        return ("", ""), "", "Pexels candidate ID has an invalid format"
    if slug != candidate_id and not slug.endswith(f"-{candidate_id}"):
        return ("", ""), "", "source-page URL is not bound to the candidate ID"

    descriptive_slug = "" if slug == candidate_id else slug[:-(len(candidate_id) + 1)]
    normalized_host = host.removeprefix("www.")
    return (
        (normalized_host, f"/{expected_root}/{slug}"),
        descriptive_slug,
        "",
    )


def _provider_page_evidence(
    provider: str,
    candidate: Mapping[str, Any],
) -> ProviderPageEvidence:
    candidate_id = str(candidate.get("image_candidate_id") or "").strip()
    urls = [
        str(candidate.get(key) or "").strip()
        for key in ("image_candidate_url", "image_source_url")
        if str(candidate.get(key) or "").strip()
    ]
    if not urls:
        return ProviderPageEvidence(frozenset(), frozenset(), "source-page URL is absent")

    signatures: set[tuple[str, str]] = set()
    descriptive_slugs: set[str] = set()
    for source_url in urls:
        signature, descriptive_slug, error = _validated_provider_page(
            provider,
            source_url,
            candidate_id,
        )
        if error:
            return ProviderPageEvidence(frozenset(), frozenset(), error)
        signatures.add(signature)
        descriptive_slugs.add(descriptive_slug)
    if len(signatures) != 1:
        return ProviderPageEvidence(
            frozenset(),
            frozenset(),
            "candidate and source-page URLs are inconsistent",
        )

    descriptive_slug = next(iter(descriptive_slugs), "")
    slug_tokens = re.findall(r"[a-zåäö]+", descriptive_slug.lower(), flags=re.IGNORECASE)
    tokens = _semantic_tokens(" ".join(slug_tokens), noise=_PROVIDER_PATH_NOISE)
    if not tokens:
        return ProviderPageEvidence(
            frozenset(),
            frozenset(),
            "source-page path is non-descriptive",
        )
    return ProviderPageEvidence(
        frozenset(tokens),
        frozenset(_provider_location_claims(slug_tokens)),
    )


def _provider_path_tokens_for_diagnostics(
    provider: str,
    candidate: Mapping[str, Any],
) -> set[str]:
    """Read an official descriptive slug only to explain a rejection.

    This deliberately does not make provider evidence valid. In particular,
    an absent/unbound candidate ID remains a missing-evidence failure even
    when a legacy official URL is descriptive enough to explain the mismatch.
    """
    for key in ("image_candidate_url", "image_source_url"):
        source_url = str(candidate.get(key) or "").strip()
        if not source_url:
            continue
        try:
            parsed = urlsplit(source_url)
        except ValueError:
            continue
        if parsed.scheme.lower() != "https":
            continue
        if (parsed.hostname or "").lower() not in _PROVIDER_HOSTS.get(provider, ()):
            continue
        segments = [unquote(segment) for segment in (parsed.path or "").split("/") if segment]
        if len(segments) != 2 or segments[0].lower() != _PROVIDER_PAGE_ROOTS.get(provider, ""):
            continue
        slug = segments[1]
        candidate_id = str(candidate.get("image_candidate_id") or "").strip()
        if candidate_id and (slug == candidate_id or slug.endswith(f"-{candidate_id}")):
            slug = "" if slug == candidate_id else slug[:-(len(candidate_id) + 1)]
        return _semantic_tokens(
            slug.replace("-", " ").replace("_", " "),
            noise=_PROVIDER_PATH_NOISE,
        )
    return set()


def _provider_page_tokens(provider: str, candidate: Mapping[str, Any]) -> set[str]:
    return set(_provider_page_evidence(provider, candidate).tokens)


def _grounded_concept_tokens(intent: AuditTruth) -> set[str]:
    parts = [
        " ".join(intent.must_have),
        " ".join(intent.acceptable_concepts),
        " ".join(intent.locations),
        " ".join(intent.evidence_terms),
    ]
    return _semantic_tokens(
        " ".join(parts),
        noise=_GROUNDING_NOISE | _AUDIT_GENERIC_CONCEPT_TOKENS,
    )


def _mapping_value(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, Mapping) else None
    return None


def _constraint_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _season_constraint_supported(value: str, truth: AuditTruth) -> bool:
    tokens = _word_tokens(value)
    if not tokens or tokens <= {"neutral", "none", "unspecified"}:
        return True
    winter = _matching_tokens(tokens, _AUDIT_WINTER_EXACT, _AUDIT_WINTER_PREFIXES)
    summer = _matching_tokens(tokens, _AUDIT_SUMMER_EXACT, _AUDIT_SUMMER_PREFIXES)
    non_winter = "non" in tokens and "winter" in tokens
    if non_winter:
        return truth.season_time == "summer or non-winter"
    if winter:
        return truth.season_time == "winter"
    if summer:
        return truth.season_time == "summer or non-winter"
    return value.strip().lower() == truth.season_time.lower()


def _constraint_supported(value: str, truth: AuditTruth) -> bool:
    tokens = _word_tokens(value)
    if not tokens:
        return False
    weather = _matching_tokens(tokens, _AUDIT_WEATHER_EXACT, _AUDIT_WEATHER_PREFIXES)
    winter = _matching_tokens(tokens, _AUDIT_WINTER_EXACT, _AUDIT_WINTER_PREFIXES)
    summer = _matching_tokens(tokens, _AUDIT_SUMMER_EXACT, _AUDIT_SUMMER_PREFIXES)
    non_winter = "non" in tokens and "winter" in tokens
    if weather and not truth.weather_story:
        return False
    if winter and not non_winter and truth.season_time != "winter":
        return False
    if (summer or non_winter) and truth.season_time != "summer or non-winter":
        return False

    locations = _locations_from_tokens(tokens)
    if locations and not locations <= set(truth.locations):
        return False

    lowered_value = " ".join(value.lower().split())
    if any(" ".join(name.lower().split()) in lowered_value for name in truth.named_people):
        return True
    meaningful = tokens - _GROUNDING_NOISE - _AUDIT_GENERIC_CONCEPT_TOKENS
    return bool(meaningful & _grounded_concept_tokens(truth))


def _stored_truth_issues(
    truth: AuditTruth,
    *,
    stored_intent: Mapping[str, Any] | None,
    stored_brief: Mapping[str, Any] | None,
    stored_concept: str,
) -> list[str]:
    issues: list[str] = []
    intents: list[Mapping[str, Any]] = []
    if stored_intent is not None:
        intents.append(stored_intent)
    if stored_brief is not None:
        nested = _mapping_value(stored_brief.get("intent"))
        if nested is not None:
            intents.append(nested)

    for intent in intents:
        if "season_time" in intent:
            season = str(intent.get("season_time") or "neutral").strip()
            if not _season_constraint_supported(season, truth):
                issues.append(f"unsupported stored intent season_time={season}")
        for constraint in _constraint_values(intent.get("must_have")):
            if not _constraint_supported(constraint, truth):
                issues.append(f"unsupported stored intent must_have={constraint}")
        for location in _constraint_values(intent.get("locations") or intent.get("location")):
            normalized = _locations_from_tokens(_word_tokens(location)) or {location.lower()}
            if not normalized <= set(truth.locations):
                issues.append(f"unsupported stored intent location={location}")
        if "named_person" in intent:
            stored_named = _is_true(intent.get("named_person"))
            if (stored_named and not truth.named_people) or (not stored_named and truth.named_person):
                issues.append(
                    "unsupported stored intent named_person="
                    f"{str(stored_named).lower()}"
                )
        if (
            "sensitive_story" in intent
            and _is_true(intent.get("sensitive_story")) != truth.sensitive_story
        ):
            issues.append(
                "unsupported stored intent sensitive_story="
                f"{str(_is_true(intent.get('sensitive_story'))).lower()}"
            )
        if _is_true(intent.get("stock_ok")) and not truth.stock_ok:
            issues.append("unsupported stored intent stock_ok=true for fail-closed article truth")

    acceptable_values: list[str] = []
    if stored_brief is not None:
        acceptable_values.extend(_constraint_values(stored_brief.get("acceptable_concepts")))
    for intent in intents:
        acceptable_values.extend(_constraint_values(intent.get("acceptable_concepts")))
    for concept in acceptable_values:
        if not _constraint_supported(concept, truth):
            issues.append(f"unsupported stored acceptable_concept={concept}")
    if stored_concept and not _constraint_supported(stored_concept, truth):
        issues.append(f"unsupported stored image_concept={stored_concept}")
    return _deduplicated_reasons(issues)


def _deduplicated_reasons(reasons: list[str]) -> list[str]:
    return list(dict.fromkeys(reason.strip() for reason in reasons if reason.strip()))


def _audit_stock_candidate(
    fields: Mapping[str, Any],
    grounded_intent: AuditTruth,
    *,
    stored_intent: Mapping[str, Any] | None = None,
    stored_brief: Mapping[str, Any] | None = None,
    stored_concept: str = "",
) -> tuple[str, list[str], str, str, tuple[str, ...]]:
    provider, candidate, identity = _stock_candidate(fields)
    identity_aliases = tuple(sorted(image_identity_aliases(provider, candidate)))
    flag_reasons: list[str] = []
    missing_reasons: list[str] = []

    flag_reasons.extend(_stored_truth_issues(
        grounded_intent,
        stored_intent=stored_intent,
        stored_brief=stored_brief,
        stored_concept=stored_concept,
    ))
    if provider not in {"unsplash", "pexels"}:
        missing_reasons.append("missing genuine provider identity for stock image")
    if not identity:
        missing_reasons.append("missing canonical provider/candidate identity")

    provider_evidence = _provider_page_evidence(provider, candidate)
    provider_tokens = set(provider_evidence.tokens)
    if not provider_tokens:
        missing_reasons.append(
            "missing genuine provider semantic evidence: "
            + (provider_evidence.error or "source-page path is absent or non-descriptive")
        )

    grounded_tokens = _grounded_concept_tokens(grounded_intent)
    if not grounded_tokens:
        missing_reasons.append(
            "article has no independently grounded concrete visual concept; stock relevance cannot be verified"
        )

    if grounded_intent.sensitive_story:
        flag_reasons.append(
            "candidate unrelated/unsafe: sensitive article requires a safe non-stock fallback"
        )
    if grounded_intent.named_person:
        flag_reasons.append(
            "candidate unrelated/unsafe: named-person article requires a safe non-stock fallback"
        )
    if grounded_intent.ambiguous:
        flag_reasons.append(
            "candidate unrelated/unsafe: article has no concrete audit-grounded visual concept"
        )

    overlap: set[str] = set()
    comparison_tokens = provider_tokens or _provider_path_tokens_for_diagnostics(
        provider,
        candidate,
    )
    if comparison_tokens and grounded_tokens:
        overlap = comparison_tokens & grounded_tokens
        missing_anchors = [
            concept
            for concept in grounded_intent.acceptable_concepts
            if concept in _AUDIT_CONCEPT_ANCHORS
            and not comparison_tokens & _AUDIT_CONCEPT_ANCHORS[concept]
        ]
        if not overlap or missing_anchors:
            mismatch_scope = (
                "boat-repair "
                if "boat repair or small craft restoration" in grounded_intent.must_have
                else ""
            )
            flag_reasons.append(
                f"candidate unrelated to article-grounded {mismatch_scope}concepts "
                f"(provider evidence: {', '.join(sorted(comparison_tokens))}; "
                f"grounded concepts: {', '.join(sorted(grounded_tokens))})"
            )

        candidate_weather = _matching_tokens(
            comparison_tokens,
            _AUDIT_WEATHER_EXACT,
            _AUDIT_WEATHER_PREFIXES,
        )
        candidate_winter = _matching_tokens(
            comparison_tokens,
            _AUDIT_WINTER_EXACT,
            _AUDIT_WINTER_PREFIXES,
        )
        if candidate_weather and not grounded_intent.weather_story:
            flag_reasons.append("candidate weather evidence lacks article support")
        if candidate_winter and grounded_intent.season_time != "winter":
            flag_reasons.append("candidate winter evidence lacks article support")

        if provider_tokens:
            candidate_locations = set(provider_evidence.locations)
            unsupported_locations = candidate_locations - set(grounded_intent.locations)
            if unsupported_locations:
                flag_reasons.append(
                    "candidate location lacks article support: "
                    + ", ".join(sorted(unsupported_locations))
                )

    reasons = _deduplicated_reasons([*flag_reasons, *missing_reasons])
    if flag_reasons:
        return "flag", reasons, provider, identity, identity_aliases
    if missing_reasons:
        return "missing", reasons, provider, identity, identity_aliases
    return (
        "ok",
        [f"{provider} independently grounded by {', '.join(sorted(overlap))}"],
        provider,
        identity,
        identity_aliases,
    )


def _base_row(path: Path, fields: Mapping[str, Any]) -> dict[str, object]:
    return {
        "file": _relative(path),
        "title": _text(fields, "title"),
        "date": _text(fields, "date"),
        "image": _text(fields, "image"),
        "image_source": _normalized_provider(fields),
        "image_identity": "",
        "image_identity_aliases": (),
        "status": "ok",
        "reason": "",
    }


def _audit_article(path: Path) -> dict[str, object]:
    fields, body, evidence_errors = _article_truth(path)
    row = _base_row(path, fields)
    if evidence_errors:
        row["status"] = "missing"
        row["reason"] = "; ".join(evidence_errors)
        return row

    image = _text(fields, "image")
    provider = _normalized_provider(fields)
    if not image:
        row["status"] = "missing"
        row["reason"] = "missing image"
        return row
    if _is_true(fields.get("image_category_fallback")) or provider == "category_fallback":
        row["image_source"] = "category_fallback"
        category = _text(fields, "category") or "Kotimaa"
        expected_image = f"/images/categories/{category.lower()}.jpg"
        fallback_issues: list[str] = []
        if image != expected_image or _text(fields, "image_thumb") != expected_image:
            fallback_issues.append("fallback claim does not use the matching category asset")
        if (
            _text(fields, "image_source") != "category_fallback"
            or _text(fields, "image_source_type") != "category_fallback"
            or not _is_true(fields.get("image_category_fallback"))
        ):
            fallback_issues.append("fallback provenance fields are inconsistent")
        stale_stock_fields = [
            key for key in (
                "image_credit", "image_source_url", "image_concept", "image_query",
                "image_candidate_id", "image_candidate_url", "image_asset_identity",
                "image_placeholder", "image_hotlink",
                "image_visual_intent", "image_visual_brief", "image_quality_score",
                "image_generated_fallback", "image_provider", "image_model",
                "image_generation_prompt", "image_decision",
                "image_accepted_reasons", "image_rejected_reasons",
                "image_accepted_reasons_json", "image_rejected_reasons_json",
            )
            if _has_value(fields.get(key))
            and not (key == "image_hotlink" and not _is_true(fields.get(key)))
        ]
        judge_score = _text(fields, "image_visual_judge_score")
        if judge_score:
            try:
                fallback_judge_is_zero = float(judge_score) == 0
            except ValueError:
                fallback_judge_is_zero = False
            if not fallback_judge_is_zero:
                stale_stock_fields.append("image_visual_judge_score")
        prompt_version = _text(fields, "image_prompt_version")
        if prompt_version and not _supported_fallback_prompt_version(prompt_version):
            stale_stock_fields.append("image_prompt_version")
        if stale_stock_fields:
            fallback_issues.append(
                "fallback retains stock/generated fields: " + ", ".join(stale_stock_fields)
            )
        if fallback_issues:
            row["status"] = "flag"
            row["reason"] = "; ".join(fallback_issues)
        else:
            row["reason"] = "safe category fallback"
        return row
    if provider not in {"unsplash", "pexels"}:
        row["status"] = "missing"
        row["reason"] = "independent semantic evidence unavailable for non-fallback image"
        return row

    grounded = _derive_audit_truth(fields, body)
    status, reasons, provider, identity, identity_aliases = _audit_stock_candidate(
        fields,
        grounded,
        stored_intent=_mapping_value(fields.get("image_visual_intent")),
        stored_brief=_mapping_value(fields.get("image_visual_brief")),
        stored_concept=_text(fields, "image_concept"),
    )
    row.update({
        "status": status,
        "reason": "; ".join(reasons),
        "image_source": provider,
        "image_identity": identity,
        "image_identity_aliases": identity_aliases,
    })
    return row


def _post_sort_key(path: Path) -> tuple[int, str, str]:
    fields, _body_text, errors = _article_truth(path)
    # Evidence failures sort before dated records, so an invalid file cannot
    # evade a bounded audit by omitting or corrupting its date metadata.
    return (1 if errors else 0, _text(fields, "date"), path.name)


def _story_tokens(title: str) -> set[str]:
    return _semantic_tokens(title, noise=_TITLE_NOISE)


def _stories_related(first: Mapping[str, object], second: Mapping[str, object]) -> bool:
    first_title = str(first.get("title") or "").strip().lower()
    second_title = str(second.get("title") or "").strip().lower()
    if first_title and first_title == second_title:
        return True
    left = _story_tokens(first_title)
    right = _story_tokens(second_title)
    if not left or not right:
        return False
    shared = left & right
    return len(shared) >= 3 and len(shared) / min(len(left), len(right)) >= 0.6


def _append_row_reason(row: dict[str, object], reason: str) -> None:
    existing = str(row.get("reason") or "").strip()
    row["reason"] = f"{existing}; {reason}" if existing else reason


def _flag_duplicate_identities(rows: list[dict[str, object]]) -> None:
    parents = list(range(len(rows)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    alias_owner: dict[str, int] = {}
    stock_indices: list[int] = []
    for index, row in enumerate(rows):
        identity = str(row.get("image_identity") or "")
        if row.get("image_source") not in {"unsplash", "pexels"}:
            continue
        raw_aliases = row.get("image_identity_aliases") or ()
        aliases = {
            str(alias).strip()
            for alias in raw_aliases
            if str(alias).strip()
        }
        if identity:
            aliases.add(identity)
        if not aliases:
            continue
        stock_indices.append(index)
        for alias in aliases:
            if alias in alias_owner:
                union(index, alias_owner[alias])
            else:
                alias_owner[alias] = index

    groups: dict[int, list[int]] = {}
    for index in stock_indices:
        groups.setdefault(find(index), []).append(index)

    for indices in groups.values():
        if len(indices) < 2:
            continue
        aliases = sorted({
            str(alias).strip()
            for index in indices
            for alias in (rows[index].get("image_identity_aliases") or ())
            if str(alias).strip()
        })
        identities = sorted({
            str(rows[index].get("image_identity") or "").strip()
            for index in indices
            if str(rows[index].get("image_identity") or "").strip()
        })
        duplicate_identity = next(
            (alias for alias in aliases if ":id:" in alias),
            identities[0] if identities else aliases[0],
        )
        for index in indices:
            peers = {peer for peer in indices if peer != index}
            peer_files = ", ".join(sorted(str(rows[peer].get("file") or "") for peer in peers))
            _append_row_reason(
                rows[index],
                f"duplicate canonical image {duplicate_identity} reused without explicit editorial policy: {peer_files}",
            )
            rows[index]["status"] = "flag"


def _recent_scan_failure(reason: str) -> list[dict[str, object]]:
    return [{
        "file": _relative(POSTS_DIR),
        "title": "",
        "date": "",
        "image": "",
        "image_source": "",
        "image_identity": "",
        "image_identity_aliases": (),
        "status": "missing",
        "reason": f"recent post audit evidence unavailable: {reason}",
    }]


def audit_recent(limit: int) -> list[dict[str, object]]:
    if limit <= 0:
        return _recent_scan_failure("limit must be positive")
    try:
        if not POSTS_DIR.is_dir():
            return _recent_scan_failure("posts directory is missing")
        available_posts = list(POSTS_DIR.glob("*.md"))
    except OSError as exc:
        return _recent_scan_failure(f"posts directory cannot be read ({exc.__class__.__name__})")
    if not available_posts:
        return _recent_scan_failure("posts directory contains no Markdown posts")

    posts = sorted(available_posts, key=_post_sort_key, reverse=True)[:limit]
    rows = [_audit_article(path) for path in posts]
    _flag_duplicate_identities(rows)
    return rows


def audit_packet(packet_path: Path | str, article_path: Path | str) -> dict[str, object]:
    packet_path = Path(packet_path)
    article_path = Path(article_path)
    fields, body, article_errors = _article_truth(article_path)
    row = _base_row(article_path, fields)
    row["packet"] = _relative(packet_path)

    try:
        raw_packet = json.loads(packet_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        article_errors.append(f"packet evidence unavailable: {exc.__class__.__name__}")
        raw_packet = {}
    if not isinstance(raw_packet, Mapping):
        article_errors.append("packet evidence unavailable: root is not an object")
        raw_packet = {}

    source_evidence = _packet_source_evidence(raw_packet)
    if not source_evidence:
        article_errors.append("packet source evidence unavailable")
    if article_errors:
        row["status"] = "missing"
        row["reason"] = "; ".join(_deduplicated_reasons(article_errors))
        return row

    packet_article = raw_packet.get("article")
    if not isinstance(packet_article, Mapping):
        row["status"] = "missing"
        row["reason"] = "packet image evidence unavailable: missing article object"
        return row
    image_fields: dict[str, Any] = {}
    enrichment = raw_packet.get("image_enrichment")
    if isinstance(enrichment, Mapping):
        image_fields.update(enrichment)
    image_fields.update(packet_article)
    if not _text(image_fields, "image"):
        row["status"] = "missing"
        row["reason"] = "packet image evidence unavailable: missing delivered image"
        return row

    grounded = _derive_audit_truth(fields, body, source_evidence=source_evidence)
    status, reasons, provider, identity, identity_aliases = _audit_stock_candidate(
        image_fields,
        grounded,
        stored_intent=_mapping_value(image_fields.get("image_visual_intent")),
        stored_brief=_mapping_value(image_fields.get("image_visual_brief")),
        stored_concept=_text(image_fields, "image_concept"),
    )
    row.update({
        "image": _text(image_fields, "image"),
        "image_source": provider,
        "image_identity": identity,
        "image_identity_aliases": identity_aliases,
        "status": status,
        "reason": "; ".join(reasons),
    })
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args(argv)

    rows = audit_recent(args.limit)
    issues = [row for row in rows if row["status"] != "ok"]
    print(
        "image_flow_audit "
        f"generated_at={datetime.now(timezone.utc).isoformat()} "
        f"checked={len(rows)} flags={len(issues)}"
    )
    for row in rows:
        print(f"{row['status']}\t{row['file']}\t{row['image_source'] or '-'}\t{row['reason']}")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
