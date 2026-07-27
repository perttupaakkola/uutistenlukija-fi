"""
High-stakes source-confidence guard for post-writer, pre-publish checks.

The guard is intentionally narrow: it only inspects high-stakes geopolitics
articles where the source corpus itself contains denial/contradiction or
election-uncertainty signals that must survive into the public headline,
summary/key points, and lead paragraph.
"""

from __future__ import annotations

import re

HIGH_STAKES_KEYWORDS = (
    "iran",
    "israel",
    "gaza",
    "ukraina",
    "ukraine",
    "venäjä",
    "russia",
    "nato",
    "trump",
    "yhdysvallat",
    "united states",
    "ceasefire",
    "tulitauko",
    "nuclear",
    "ydinase",
    "ydinohjel",
    "ydinsopim",
    "ydintarkast",
    "ydinuh",
    "ydinpelot",
    "ydinkärk",
    "election",
    "vaali",
    "sanctions",
    "pakotte",
    "strike",
    "isku",
)

STATE_ACTOR_CLAIM_MARKERS = (
    "says",
    "said",
    "claim",
    "claimed",
    "väitt",
    "sano",
    "kertoi",
    "mukaan",
    "agreed",
    "suostu",
)

DENIAL_MARKERS = (
    "denied",
    "denies",
    "rejected",
    "disputed",
    "contradict",
    "no new commitment",
    "not made new commitment",
    "has not made",
    "kiist",
    "ei ole tehnyt",
    "ei ole antanut",
    "ei uusia sitoum",
    "ei uutta sitoum",
    "ristiriita",
)

PUBLIC_DENIAL_CONTEXT_MARKERS = (
    "kiist",
    "ei ole tehnyt",
    "ei ole antanut",
    "ei uusia sitoum",
    "ei uutta sitoum",
    "ei ole sitoutunut",
    "ei vahvist",
    "ristiriita",
)

PUBLIC_ATTRIBUTION_MARKERS = (
    "mukaan",
    "sanoi",
    "kertoi",
    "väitt",
    "arvioi",
    "lausunn",
    "bbc",
    "viranoma",
    "ulkoministeri",
    "vance",
    "trump",
)

ELECTION_SOURCE_UNCERTAINTY_MARKERS = (
    "preliminary",
    "initial count",
    "not legally binding",
    "not yet conceded",
    "has not yet conceded",
    "cross checked",
    "razor-thin",
    "less than one percentage point",
    "alustav",
    "ei oikeudellisesti sitova",
    "ei ole myöntänyt",
    "ei ole vielä myöntänyt",
    "tarkist",
    "niukka",
)

PUBLIC_ELECTION_UNCERTAINTY_MARKERS = (
    "alustav",
    "ei ole oikeudellisesti sitova",
    "ei ole vielä oikeudellisesti sitova",
    "ei ole myöntänyt",
    "ei ole vielä myöntänyt",
    "tarkist",
    "niukka",
    "alle prosent",
    "0,96",
    "0.96",
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    haystack = _norm(text)
    return any(needle in haystack for needle in needles)


def _first_paragraph(content: str) -> str:
    paragraphs = [p.strip() for p in (content or "").split("\n\n") if p.strip()]
    return paragraphs[0] if paragraphs else ""


def _public_surfaces(article: dict) -> tuple[str, str, str]:
    title = str(article.get("title") or "")
    summary_bits = [
        str(article.get("summary") or article.get("description") or ""),
        " ".join(str(item) for item in (article.get("summary_bullets") or [])),
        " ".join(str(item) for item in (article.get("key_points") or [])),
    ]
    lead = _first_paragraph(str(article.get("content") or ""))
    return title, " ".join(summary_bits), lead


def _source_corpus(article: dict) -> str:
    parts = [
        article.get("source_text"),
        article.get("research"),
        article.get("fresh_source_text"),
        article.get("source_confidence_fresh_text"),
    ]
    return "\n\n".join(str(part) for part in parts if part)


def is_high_stakes_geopolitics(article: dict, source_text: str | None = None) -> bool:
    category = _norm(str(article.get("category") or article.get("category_hint") or ""))
    corpus = " ".join(
        [
            str(article.get("title") or ""),
            str(article.get("summary") or article.get("description") or ""),
            str(source_text if source_text is not None else _source_corpus(article)),
        ]
    )
    return category == "ulkomaat" or _contains_any(corpus, HIGH_STAKES_KEYWORDS)


def source_confidence_issues(article: dict) -> list[str]:
    source_text = _source_corpus(article)
    if not source_text or not is_high_stakes_geopolitics(article, source_text):
        return []

    issues: list[str] = []
    title, summary, lead = _public_surfaces(article)
    public_all = " ".join([title, summary, lead])
    source_has_state_claim = _contains_any(source_text, STATE_ACTOR_CLAIM_MARKERS)
    source_has_denial = _contains_any(source_text, DENIAL_MARKERS)

    if source_has_state_claim and source_has_denial:
        surfaces_have_denial = all(
            _contains_any(surface, PUBLIC_DENIAL_CONTEXT_MARKERS)
            for surface in (title, summary, lead)
        )
        surfaces_have_attribution = all(
            _contains_any(surface, PUBLIC_ATTRIBUTION_MARKERS)
            for surface in (title, summary, lead)
        )
        if not (surfaces_have_denial and surfaces_have_attribution):
            issues.append("source_confidence_denial_context_missing")

    source_has_election_uncertainty = (
        _contains_any(source_text, ("election", "vaali", "vote", "ääntenlask"))
        and _contains_any(source_text, ELECTION_SOURCE_UNCERTAINTY_MARKERS)
    )
    if source_has_election_uncertainty and not _contains_any(public_all, PUBLIC_ELECTION_UNCERTAINTY_MARKERS):
        issues.append("source_confidence_election_uncertainty_missing")

    return issues
