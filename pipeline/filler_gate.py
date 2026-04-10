"""
filler_gate.py — Detects AI-generated filler, sentimental fluff, and nonsense in Finnish articles.
Part of the Uutistenlukija quality gate.
"""

from __future__ import annotations
import re
from typing import NamedTuple

class FillerResult(NamedTuple):
    matches: list[str]
    labels: list[str]
    total_penalty: int

# Phrases that strongly indicate AI-generated sentimental fluff or clichés.
# Each pattern has an associated penalty (historical 80-point scale).
FILLER_PATTERNS = {
    # Sentimental / Emotional fluff
    r"enemmän kuin vain peli": 15,
    r"enemmän kuin vain uutinen": 15,
    r"tunne ja odotus": 15,
    r"yhteisöllisyyden tunne": 10,
    r"kulttuurinen optimismi": 15,
    r"tuo toivoa suomalaisille": 10,
    r"positiivisina hetkinä elämänsä varrella": 15,
    r"elinehto monelle": 20, # Hyperbole
    r"muuttaa elämän suuntaa": 10,
    r"suurta innostusta": 10,
    
    # Generic AI endings / "Aika näyttää" style
    r"jää nähtäväksi": 10,
    r"aika näyttää": 10,
    r"tulevaisuus näyttää": 10,
    r"seuraamme tilannetta": 5,
    r"herättää (paljon )?keskustelua": 5,
    r"herättää kysymyksiä": 10,
    
    # Hallucinated advice / moralizing
    r"voi käyttää voittoa harkitusti": 20,
    r"on tärkeää muistaa": 5,
    r"jokainen voi tehdä": 10,
    
    # AI structural clichés
    r"viimeisenä, mutta ei vähäisimpänä": 15,
    r"yhteenvetona voidaan todeta": 15,
    r"on huomionarvoista": 5,
    r"on syytä huomata": 5,
}

# Nonsense / Out-of-context words (often hallucinated by AI)
NONSENSE_PATTERNS = {
    r"perjantairaskaus": 40, # From specimen
    r"perjantairaskauden": 40,
}

def analyze_article(article: dict) -> FillerResult:
    content = (article.get("content", "") or "")
    title = (article.get("title", "") or "")
    full_text = f"{title}\n\n{content}"
    
    matches = []
    labels = []
    total_penalty = 0
    
    for pattern, penalty in FILLER_PATTERNS.items():
        if re.search(pattern, full_text, re.IGNORECASE):
            matches.append(pattern)
            labels.append(f"filler:{pattern}")
            total_penalty += penalty
            
    for pattern, penalty in NONSENSE_PATTERNS.items():
        if re.search(pattern, full_text, re.IGNORECASE):
            matches.append(pattern)
            labels.append(f"nonsense:{pattern}")
            total_penalty += penalty
            
    # Check for specific hyperbole logic
    if "elinehto" in full_text.lower() and "eurojackpot" in full_text.lower():
        if "elinehto" not in matches:
            matches.append("elinehto (hyperbole)")
            labels.append("quality:hyperbole")
            total_penalty += 20

    return FillerResult(matches=matches, labels=labels, total_penalty=total_penalty)

def log_hits(article: dict, result: FillerResult) -> None:
    if not result.matches:
        return
    title = article.get("title", "Unknown")[:50]
    print(f"[filler]   HIT on '{title}': {', '.join(result.matches)} (Penalty: {result.total_penalty})")
