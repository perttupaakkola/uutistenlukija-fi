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
VISUAL_JUDGE_ACCEPT_THRESHOLD = 45
MISMATCH_SCORE = 0
PROMPT_VERSION = "image-flow-v2-2026-07-03"

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
    "aurinko", "aurinkoa", "aurinkoinen", "aurinkoisena", "pouta", "poutainen",
    "poutaisena", "kesä",
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

BOAT_REPAIR_TERMS = {
    "vene", "veneet", "veneen", "veneiden", "veneenkorjaus", "veneenkorjaustaidot",
    "soutuvene", "soutuveneen", "moottorivene", "moottoriveneen", "pulpettivene",
    "hyttivene", "taifunx", "boat", "boats", "rowboat", "motorboat", "boat repair",
}

REPAIR_WORK_TERMS = {
    "korjaus", "korjaa", "korjattavaksi", "korjattavia", "korjattujen", "korjaamaansa",
    "kunnostaa", "kunnostamisesta", "kunnostettu", "kunnostettuja", "romukuntoisia",
    "repair", "repairs", "repairing", "restoration", "restoring",
}

YOUTH_ENTREPRENEUR_TERMS = {
    "4h-yrittäjyys", "4h", "kesätyö", "kesätöitä", "nuoret", "nuorukainen",
    "16-vuotias", "yrittäjä", "yrittäjyys", "youth", "teen", "entrepreneur",
}

URBAN_BUSINESS_IMAGE_TERMS = {
    "skyscraper", "skyscrapers", "high-rise", "highrise", "city", "cityscape",
    "skyline", "downtown", "office", "offices", "business district", "building",
    "buildings", "architecture", "urban", "corporate", "tower", "towers",
}

# Article-derived bilingual concepts. These are deliberately keyed only from
# editorial fields, never from the generated provider query. They let Finnish
# stories retrieve and verify English stock metadata without reviving the
# query-as-truth defect fixed by OPE-585.
ARTICLE_VISUAL_CONCEPT_RULES: tuple[
    tuple[set[str], str, tuple[str, ...]], ...
] = (
    (
        {
            "kuljetusyrittäjä", "kuljetusyrittäjälle", "kuljetusyritys",
            "kuljetusliike", "kuorma-auto", "kuorma-autoa", "rekka",
            "logistiikka", "freight", "truck", "logistics",
        },
        "freight truck or logistics",
        (
            "freight truck logistics",
            "commercial truck on road",
            "transport and logistics",
        ),
    ),
    (
        {
            "puuseppä", "puuseppäyrittäjä", "puusepän", "kaluste",
            "kalusteet", "kalusteita", "keittiö", "keittiön",
            "keittiökaluste", "keittiökalusteita", "verstas", "carpentry",
            "woodworking", "furniture",
        },
        "carpentry, woodworking, kitchen cabinets, or furniture workshop",
        (
            "carpentry workshop",
            "woodworking kitchen cabinets",
            "furniture workshop tools",
        ),
    ),
    (
        {
            "korkeakoulu", "korkeakoulujen", "yhteishaku", "opiskelupaikka",
            "opiskelupaikkaa", "opiskelijat", "university", "college",
            "admissions", "students",
        },
        "university, study, or student admissions",
        ("university campus", "students studying", "university admissions"),
    ),
    (
        {
            "hotelli", "hotellit", "hotellimajoitus", "majoitus", "spahotel",
            "hotel", "hospitality", "accommodation",
        },
        "hotel or hospitality",
        ("hotel exterior", "hotel room hospitality", "hotel reception"),
    ),
    (
        {
            "sikarutto", "villisika", "villisikoja", "swine", "boar",
        },
        "wild boar or animal disease monitoring",
        ("wild boar in forest", "wildlife monitoring", "forest field research"),
    ),
    (
        {
            "budjetti", "vaalibudjetti", "talousarvio", "julkistalous",
            "budget", "fiscal",
        },
        "budget documents or public finance",
        ("budget documents", "public finance papers", "financial planning desk"),
    ),
    (
        {
            "dekkari", "kirja", "romaani", "tv-sarja", "televisiosarja",
            "hollywood", "book", "novel", "television", "cinema",
        },
        "book, television, or screen production",
        ("book and television production", "film studio equipment", "open book cinema"),
    ),
    (
        {
            "ralli", "mm-ralli", "rallissa", "ralliauto", "motorsport",
        },
        "rally car or motorsport",
        ("rally car on gravel road", "motorsport service area", "rally racing"),
    ),
    (
        {
            "kaasupallo", "kuumailmapallo", "balloon",
        },
        "competitive gas balloon flight",
        ("gas balloon in sky", "balloon aviation competition", "balloon landing field"),
    ),
)


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
class VisualBrief:
    acceptable_concepts: list[str]
    hard_forbidden_implications: list[str]
    intent: ImageIntent
    prompt_version: str = PROMPT_VERSION

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["intent"] = self.intent.to_dict()
        return data


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


@dataclass(frozen=True)
class VisualJudgeDecision:
    score: int
    accepted: bool
    reasons: list[str]
    hard_fail: bool = False
    prompt_version: str = PROMPT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _tokens(*parts: str) -> set[str]:
    text = " ".join(part or "" for part in parts).lower()
    words = set(re.findall(r"[\wäöå+-]+", text, flags=re.IGNORECASE))
    words |= set(re.findall(r"[\wäöå+]+", text.replace("-", " "), flags=re.IGNORECASE))
    phrases = {
        phrase
        for phrase in ("clear sky", "boat repair", "business district")
        if phrase in text
    }
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
    article_tokens = _tokens(article_text)

    must_have: list[str] = []
    must_not: list[str] = []
    season_time = "neutral"
    safety_mode = "normal"
    stock_ok = True
    generated_ok = True

    if article_tokens & WEATHER_TERMS:
        must_have.append("weather")
    if article_tokens & BOAT_REPAIR_TERMS and article_tokens & (REPAIR_WORK_TERMS | YOUTH_ENTREPRENEUR_TERMS):
        must_have.append("boat repair or small craft restoration")
        must_not.extend(["skyscraper", "office tower", "generic business district"])
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
    for cues, required_concept, _ in ARTICLE_VISUAL_CONCEPT_RULES:
        if article_tokens & cues:
            must_have.append(required_concept)

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


def build_visual_brief(
    title: str,
    category: str = "",
    *,
    summary: str = "",
    key_points: list[str] | None = None,
    content: str = "",
    query: str = "",
) -> VisualBrief:
    """Build the Image Flow v2 structured brief from article text."""
    intent = build_image_intent(
        title,
        category,
        summary=summary,
        key_points=key_points,
        content=content,
        query=query,
    )
    article_tokens = _tokens(title, summary, " ".join(key_points or []), content)
    concepts: list[str] = []
    forbidden = list(intent.must_not)

    if "boat repair or small craft restoration" in intent.must_have:
        concepts.extend([
            "boat repair workshop",
            "small craft restoration",
            "rowboat maintenance",
        ])
        forbidden.extend([
            "skyscrapers or glass office towers",
            "generic finance skyline",
            "corporate city district",
        ])
    if article_tokens & WEATHER_TERMS:
        if article_tokens & SUN_TERMS:
            concepts.append("sunny Finnish weather")
        elif article_tokens & RAIN_TERMS:
            concepts.append("rainy Finnish weather")
        elif article_tokens & WINTER_TERMS:
            concepts.append("winter weather")
        else:
            concepts.append("weather forecast")
    for cues, _, article_concepts in ARTICLE_VISUAL_CONCEPT_RULES:
        if article_tokens & cues:
            concepts.extend(article_concepts)
    if not concepts:
        concepts.extend([
            intent.subject,
            intent.setting,
        ])

    return VisualBrief(
        acceptable_concepts=[c for c in dict.fromkeys(concepts) if c],
        hard_forbidden_implications=[f for f in dict.fromkeys(forbidden) if f],
        intent=intent,
    )


def build_stock_queries(
    title: str,
    category: str = "",
    *,
    summary: str = "",
    key_points: list[str] | None = None,
    content: str = "",
    primary_query: str = "",
) -> list[tuple[str, str, VisualBrief]]:
    """Return bounded stock search concepts for Image Flow v2."""
    brief = build_visual_brief(
        title,
        category,
        summary=summary,
        key_points=key_points,
        content=content,
        query=primary_query,
    )
    queries: list[tuple[str, str, VisualBrief]] = []
    if primary_query and not brief.intent.must_have:
        return [(primary_query, "primary_query", brief)]
    for concept in brief.acceptable_concepts[:3]:
        queries.append((concept, concept, brief))
    if primary_query and primary_query not in {q for q, _, _ in queries}:
        queries.append((primary_query, "primary_query", brief))
    return queries[:4] or [(primary_query or brief.intent.subject, "primary_query", brief)]


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
    article_tokens = _tokens(title, summary, " ".join(key_points or []), content)
    grounded_tokens = article_tokens | _tokens(intent.setting, " ".join(intent.must_have))
    query_tokens = _tokens(query)
    candidate_tokens = _tokens(_candidate_text(candidate))
    candidate_id, source_url = _source_id(candidate)

    score = 50
    reasons: list[str] = []

    grounded_overlap = grounded_tokens & candidate_tokens
    if not candidate_tokens:
        return CandidateDecision(
            provider,
            candidate_id,
            source_url,
            MISMATCH_SCORE,
            False,
            ["candidate has no semantic metadata"],
        )
    if grounded_overlap:
        score += min(25, 5 * len(grounded_overlap))
        reasons.append(f"metadata matches {', '.join(sorted(grounded_overlap)[:5])}")
        query_overlap = query_tokens & candidate_tokens
        if query_overlap:
            score += min(5, len(query_overlap))
            reasons.append(f"retrieval hint matches {', '.join(sorted(query_overlap)[:5])}")

    weather_cues = candidate_tokens & WEATHER_TERMS
    if weather_cues and article_tokens & WEATHER_TERMS:
        score += 10
        reasons.append("weather metadata matches visual intent")
    if candidate_tokens & SUN_TERMS and (article_tokens & SUN_TERMS):
        score += 10
        reasons.append("sunny metadata matches visual intent")
    if candidate_tokens & RAIN_TERMS and (article_tokens & RAIN_TERMS):
        score += 10
        reasons.append("rain metadata matches visual intent")

    article_is_weather = bool(article_tokens & WEATHER_TERMS)
    article_allows_winter = bool(article_tokens & WINTER_TERMS)
    article_allows_rain = bool(article_tokens & RAIN_TERMS)
    article_requests_sun = bool(article_tokens & SUN_TERMS)
    article_requests_heat = bool(article_tokens & HEAT_TERMS)

    hard_rejects: list[str] = []
    if article_is_weather and not article_allows_winter and candidate_tokens & WINTER_TERMS:
        hard_rejects.append("winter metadata contradicts non-winter weather story")
    if article_requests_sun and not article_allows_rain and candidate_tokens & RAIN_TERMS:
        hard_rejects.append("rain/storm metadata contradicts sunny weather story")
    if article_requests_sun and candidate_tokens & WINTER_TERMS:
        hard_rejects.append("winter metadata contradicts sunny weather story")
    if article_requests_heat and candidate_tokens & (WINTER_TERMS | COLD_TERMS):
        hard_rejects.append("cold/winter metadata contradicts heat weather story")
    if article_allows_rain and not article_allows_winter and candidate_tokens & WINTER_TERMS:
        hard_rejects.append("winter metadata contradicts rain-only weather story")
    if intent.safety_mode == "illustration_only" and candidate_tokens & PERSON_IMAGE_TERMS:
        hard_rejects.append("generic person/lookalike metadata is unsafe for named-person or sensitive story")
    concrete_boat_repair_story = bool(
        article_tokens & BOAT_REPAIR_TERMS
        and article_tokens & (REPAIR_WORK_TERMS | YOUTH_ENTREPRENEUR_TERMS)
    )
    if concrete_boat_repair_story and not candidate_tokens & BOAT_REPAIR_TERMS:
        if candidate_tokens & URBAN_BUSINESS_IMAGE_TERMS:
            hard_rejects.append("urban business/skyscraper metadata contradicts concrete boat-repair story")
        elif query_tokens & URBAN_BUSINESS_IMAGE_TERMS:
            hard_rejects.append("broad business query lacks required boat-repair subject")

    if hard_rejects:
        return CandidateDecision(provider, candidate_id, source_url, MISMATCH_SCORE, False, hard_rejects)

    if not grounded_overlap:
        return CandidateDecision(
            provider,
            candidate_id,
            source_url,
            MISMATCH_SCORE,
            False,
            ["candidate metadata has no article-grounded concept overlap"],
        )

    if any(term in candidate_tokens for term in {"generic", "abstract", "background"}):
        score -= 8
        reasons.append("generic stock metadata")

    accepted = intent.stock_ok and score >= ACCEPT_THRESHOLD
    if not accepted:
        reasons.append(f"score below threshold {ACCEPT_THRESHOLD}")
    elif not reasons:
        reasons.append("accepted")

    return CandidateDecision(provider, candidate_id, source_url, score, accepted, reasons)


def judge_visual_candidate(
    candidate: dict[str, Any],
    *,
    brief: VisualBrief,
    provider: str = "image",
) -> VisualJudgeDecision:
    """Deterministic local visual judge over available image metadata.

    Production can replace this with an actual vision-model call, but the gate is
    already fail-closed: hard forbidden implications and uncertainty override the
    keyword/category score.
    """
    candidate_tokens = _tokens(_candidate_text(candidate))
    text = _candidate_text(candidate).lower()
    reasons: list[str] = []
    hard_fails: list[str] = []

    for forbidden in brief.hard_forbidden_implications:
        forbidden_tokens = _tokens(forbidden)
        if forbidden_tokens and candidate_tokens & forbidden_tokens:
            hard_fails.append(f"forbidden visual implication: {forbidden}")

    if hard_fails:
        return VisualJudgeDecision(MISMATCH_SCORE, False, hard_fails, hard_fail=True)

    score = 25
    for concept in brief.acceptable_concepts:
        concept_tokens = _tokens(concept)
        overlap = concept_tokens & candidate_tokens
        if overlap:
            score += min(35, 12 * len(overlap))
            reasons.append(f"visual metadata supports concept '{concept}'")

    for required in brief.intent.must_have:
        required_tokens = _tokens(required)
        overlap = required_tokens & candidate_tokens
        if overlap:
            score += min(25, 10 * len(overlap))
            reasons.append(f"visual metadata supports required cue '{required}'")

    if not text.strip():
        score = min(score, 45)
        reasons.append("visual judge uncertain: no image metadata")
    if not reasons:
        reasons.append("visual judge uncertain: no acceptable concept evidence")

    accepted = score >= VISUAL_JUDGE_ACCEPT_THRESHOLD
    if not accepted:
        reasons.append(f"visual judge score below threshold {VISUAL_JUDGE_ACCEPT_THRESHOLD}")
    return VisualJudgeDecision(min(score, 100), accepted, reasons, hard_fail=False)


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
    brief: VisualBrief | None = None,
    concept: str = "",
    return_decisions: bool = False,
) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], list[CandidateDecision]]:
    """Filter stock candidates, preserving scored decision evidence."""
    brief = brief or build_visual_brief(
        title,
        "",
        summary=summary,
        key_points=key_points,
        content=content,
        query=query,
    )
    intent = intent or brief.intent
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
        judge = judge_visual_candidate(candidate, brief=brief, provider=provider)
        if decision.accepted and not judge.accepted:
            decision = CandidateDecision(
                provider,
                decision.candidate_id,
                decision.source_url,
                decision.score,
                False,
                [*decision.reasons, *judge.reasons],
            )
        decisions.append(decision)
        if decision.accepted:
            enriched = dict(candidate)
            enriched["_image_decision"] = decision.to_dict()
            enriched["_image_visual_intent"] = intent.to_dict()
            enriched["_image_visual_brief"] = brief.to_dict()
            enriched["_image_visual_judge"] = judge.to_dict()
            enriched["_image_concept"] = concept or query
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
        "image_source_type": "category_fallback",
        "image_decision_reason": reason,
        "image_prompt_version": PROMPT_VERSION,
        "image_visual_judge_score": 0,
        "image_decision": {
            "source": "category_fallback",
            "accepted": True,
            "reason": reason,
            "prompt_version": PROMPT_VERSION,
        },
    }


def stock_decision_fields(provider: str, result: dict[str, Any], query: str) -> dict[str, Any]:
    """Frontmatter-safe stock decision evidence."""
    decision = result.get("decision") or result.get("_image_decision") or {}
    intent = result.get("intent") or result.get("_image_visual_intent") or {}
    brief = result.get("brief") or result.get("_image_visual_brief") or {}
    judge = result.get("visual_judge") or result.get("_image_visual_judge") or {}
    concept = result.get("concept") or result.get("_image_concept") or query
    reasons = [str(reason) for reason in decision.get("reasons", []) if str(reason).strip()]
    return {
        "image_source": provider,
        "image_source_type": "stock",
        "image_decision_reason": "; ".join(reasons) or f"{provider} accepted",
        "image_visual_intent": intent,
        "image_visual_brief": brief,
        "image_concept": concept,
        "image_query": query,
        "image_candidate_id": decision.get("candidate_id"),
        "image_candidate_url": decision.get("source_url"),
        "image_visual_judge_score": judge.get("score"),
        "image_accepted_reasons": reasons,
        "image_rejected_reasons": [],
        "image_prompt_version": PROMPT_VERSION,
        "image_decision": {
            "source": provider,
            "query": query,
            "concept": concept,
            "accepted": True,
            "score": decision.get("score"),
            "candidate_id": decision.get("candidate_id"),
            "source_url": decision.get("source_url"),
            "visual_judge_score": judge.get("score"),
            "visual_judge_reasons": judge.get("reasons", []),
            "reasons": reasons,
            "prompt_version": PROMPT_VERSION,
        },
        "image_quality_score": decision.get("score"),
        "image_category_fallback": False,
    }


def generated_decision_fields(
    *,
    provider: str,
    model: str,
    prompt: str,
    image_path: str,
    brief: VisualBrief | dict[str, Any],
    judge: VisualJudgeDecision | dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    brief_dict = brief.to_dict() if hasattr(brief, "to_dict") else dict(brief or {})
    judge_dict = judge.to_dict() if hasattr(judge, "to_dict") else dict(judge or {})
    accepted = bool(judge_dict.get("accepted"))
    return {
        "image_source": "generated",
        "image_source_type": "generated_editorial",
        "image_decision_reason": reason,
        "image_generated_fallback": True,
        "image_visual_brief": brief_dict,
        "image_visual_intent": brief_dict.get("intent", {}),
        "image_concept": (brief_dict.get("acceptable_concepts") or ["generated editorial"])[0],
        "image_query": "",
        "image_candidate_id": image_path,
        "image_candidate_url": image_path,
        "image_visual_judge_score": judge_dict.get("score"),
        "image_accepted_reasons": judge_dict.get("reasons", []) if accepted else [],
        "image_rejected_reasons": [] if accepted else judge_dict.get("reasons", []),
        "image_provider": provider,
        "image_model": model,
        "image_prompt_version": PROMPT_VERSION,
        "image_generation_prompt": prompt,
        "image_decision": {
            "source": "generated",
            "accepted": accepted,
            "reason": reason,
            "provider": provider,
            "model": model,
            "prompt_version": PROMPT_VERSION,
            "visual_judge_score": judge_dict.get("score"),
            "visual_judge_reasons": judge_dict.get("reasons", []),
        },
    }
