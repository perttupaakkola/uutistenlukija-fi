"""
LLM-powered image search query generation.

Uses gpt-4o-mini to generate contextually accurate English search queries
for stock photo APIs (Unsplash/Pexels).

Replaces naive keyword extraction which often mismatches article content
(e.g., an article about spring rain getting a snowy photo because the
Finnish title mentions "kylmää" = cold).

Environment:
    OPENAI_API_KEY — required (falls back gracefully if missing)
"""

import os
import re
from typing import Optional

_client = None


def _get_client():
    global _client
    if _client is None:
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set")
        from openai import OpenAI
        _client = OpenAI(api_key=api_key)
    return _client


QUERY_PROMPT = """You are an image search expert. Given a Finnish news article title and body, generate the BEST English search query (3-5 words) for finding a relevant stock photo on Unsplash or Pexels.

Rules:
- The query must be in ENGLISH.
- Focus on the VISUAL SUBJECT of the article, not abstract concepts.
- Consider the SEASON and SETTING described in the article.
- Be specific: "rainy spring street Helsinki" is better than "weather".
- Never use abstract words like "crisis", "impact", "situation".
- Prefer concrete visual subjects: people, places, objects, landscapes.
- If the article mentions a specific location, include it.
- Do not search for a named person unless the story is specifically about a photo, appearance, or event where that person is visually essential.
- For polls, approval ratings, elections, parties, governments, and institutions, prefer the visible event or institution: "public opinion survey", "parliament debate", "government meeting", "ballot box".
- Do not use generic role portraits like "politician in suit" for named-person news. A random lookalike or unrelated person is worse than an institutional image.
- If the article is about weather, match the ACTUAL weather described (rain ≠ snow).

Return ONLY the search query, nothing else. No quotes, no explanation."""


_POLL_OR_POLITICS_TERMS = {
    "arvio", "arvioi", "gallup", "hallitus", "kannatus", "kysely", "mielipidekysely",
    "ministeri", "puolue", "vaali", "vastaaja", "vastaajista", "äänestys",
}

_PORTRAIT_QUERY_TERMS = {
    "businessman", "businesswoman", "leader", "minister", "politician", "portrait",
    "prime minister", "professional", "statesman",
}


def _contains_person_like_name(text: str) -> bool:
    words = re.findall(r"\b[A-ZÅÄÖ][a-zåäö]+(?:\s+[A-ZÅÄÖ][a-zåäö]+)+\b", text or "")
    return bool(words)


def sanitize_generated_query(query: str, title: str, body: str = "", category: str = "") -> str:
    """Prevent named-person stock searches from becoming random portrait matches."""
    cleaned = (query or "").strip()
    if not cleaned:
        return ""

    q_lower = cleaned.lower()
    haystack = " ".join([title or "", body or "", category or ""]).lower()
    is_political_or_poll = any(term in haystack for term in _POLL_OR_POLITICS_TERMS)
    is_portrait_query = any(term in q_lower for term in _PORTRAIT_QUERY_TERMS)
    includes_named_person = _contains_person_like_name(cleaned)

    if is_political_or_poll and (is_portrait_query or includes_named_person):
        if any(term in haystack for term in {"kysely", "gallup", "mielipidekysely", "vastaaja", "vastaajista"}):
            return "public opinion survey ballot"
        if "eduskunta" in haystack or "parliament" in haystack:
            return "parliament debate Finland"
        return "government meeting parliament"

    return cleaned


def generate_image_query(title: str, body: str, category: str = "") -> str:
    """Generate an English image search query using LLM.

    Args:
        title: Finnish article title
        body: Article body text (will be truncated to ~200 words)
        category: Article category (e.g. "Kotimaa", "Talous")

    Returns:
        English search query string, or empty string on failure
        (caller should fall back to keyword extraction).
    """
    # Truncate body to save tokens (~200 words ≈ 300 tokens input)
    body_excerpt = " ".join(body.split()[:200])

    prompt = f"Article title: {title}\nCategory: {category}\n\nArticle body:\n{body_excerpt}"

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=30,
            temperature=0.3,
            messages=[
                {"role": "system", "content": QUERY_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        query = response.choices[0].message.content.strip().strip('"').strip("'")
        query = sanitize_generated_query(query, title, body_excerpt, category)
        if query and len(query) > 2:
            print(f"[image_query] LLM query: '{title[:50]}' → '{query}'")
            return query
    except Exception as e:
        print(f"[image_query] LLM failed ({e}), falling back to keyword extraction")

    # Fallback: return empty to let the caller use its own keyword extraction
    return ""
