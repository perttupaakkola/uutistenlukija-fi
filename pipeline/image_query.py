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


QUERY_PROMPT = """You are an image search expert. Given a Finnish news article title and body, generate the BEST English search query (3-5 words) for finding a relevant stock photo on Unsplash.

Rules:
- The query must be in ENGLISH
- Focus on the VISUAL SUBJECT of the article, not abstract concepts
- Consider the SEASON and SETTING described in the article
- Be specific: "rainy spring street Helsinki" is better than "weather"
- Never use abstract words like "crisis", "impact", "situation"
- Prefer concrete visual subjects: people, places, objects, landscapes
- If the article mentions a specific location, include it
- If the article is about weather, match the ACTUAL weather described (rain ≠ snow)

Return ONLY the search query, nothing else. No quotes, no explanation."""


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
        if query and len(query) > 2:
            print(f"[image_query] LLM query: '{title[:50]}' → '{query}'")
            return query
    except Exception as e:
        print(f"[image_query] LLM failed ({e}), falling back to keyword extraction")

    # Fallback: return empty to let the caller use its own keyword extraction
    return ""
