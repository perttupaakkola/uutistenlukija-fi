"""
Article Writer — transforms RSS leads into original journalism.

Pipeline: RSS headline → web research → multi-source synthesis → original article.
Two-pass system: write + anti-AI audit pass.
"""

import os
import json
import sys
import time
from typing import List, Dict
from pathlib import Path

# Try to import anthropic, but fallback to claude_transport if not available
try:
    import anthropic
    HAVE_ANTHROPIC_SDK = True
except ImportError:
    HAVE_ANTHROPIC_SDK = False

# Add parent paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "autopoetry"))

try:
    from claude_transport import complete_with_claude, parse_json_object
except ImportError:
    pass

CATEGORIES = ["Kotimaa", "Ulkomaat", "Talous", "Teknologia", "Urheilu", "Kulttuuri", "Tiede"]

SYSTEM_PROMPT = """Olet kokenut suomalainen uutistoimittaja. Kirjoitat omia, alkuperäisiä uutisartikkeleita.

Saat uutisaiheen otsikon, taustatietoja ja tutkimustuloksia useista lähteistä. Tehtäväsi on kirjoittaa oma, itsenäinen uutisartikkeli näiden pohjalta.

TÄRKEÄÄ:
- Kirjoita AINA suomeksi, myös jos lähdemateriaali on englanniksi.
- Tämä on SINUN artikkelisi. Älä viittaa "alkuperäiseen uutiseen" tai "raportin mukaan" (paitsi jos tiedät raportin nimen).
- Poikkeus KANSAINVÄLISET LÄHTEET: jos artikkeli on englanninkielisestä lähteestä (BBC, Reuters, AP, The Guardian, Ars Technica, TechCrunch, Der Spiegel jne.), mainitse lähde luonnollisesti kerran — esim. "BBC:n mukaan", "The Guardianin mukaan", "Ars Technica raportoi". Ei enempää.
- Muille artikkeleille: älä mainitse lähdettä ollenkaan.
- Kirjoita 3-5 kappaletta, VÄHINTÄÄN 200 sanaa, tavoite 280-380 sanaa. Lyhyempi kuin 180 sanaa on liian lyhyt.

KIRJOITUSTYYLI:
- Aloita suoraan asiasta.
- Lyhyet, suorat lauseet. Vaihtele pituutta.
- Neutraalia yleiskieltä — ei puhekieltä eikä virkasuomea.
- Vältä kliseitä: "merkittävä", "historiallinen", "mullistava" — paitsi jos se oikeasti on sitä.
- Vältä passiivia kun aktiivi toimii.
- Ei emojeja, lihavointia tai otsikkolistoja.
- Ei ajatusviivoja (—) liiallisesti.
- Suomeksi vain ensimmäinen sana isolla otsikoissa.
- Ei geneerisiä lopetuksia ("Aika näyttää", "Tulevaisuus näyttää").
- Lopeta viimeiseen faktaan.

TEKOÄLYKIRJOITUKSEN VÄLTTÄMINEN:
- Ei "Lisäksi", "Toisaalta", "On huomionarvoista", "kokonaisvaltainen", "ekosysteemi" (kuvainnollisesti)
- Ei kolmen sarjoja joka kappaleessa
- Ei synonyymien kierrätystä (yhtiö/firma/toimija/yritys samasta asiasta)
- Ei mainosmaista kieltä
- Ei chatbot-artefakteja
- Anna faktojen puhua, älä paisuttele

Vastaa VAIN JSON-muodossa."""

AUDIT_SYSTEM_PROMPT = """Olet tarkka kielentarkistaja. Tarkista uutisartikkelit tekoälykirjoituksen merkkien varalta ja korjaa:

1. Paisuttelu ja mainosmainen kieli
2. Tekoälysanasto (Lisäksi, Toisaalta, kokonaisvaltainen, ekosysteemi)
3. Kolmen sarjat, synonyymien kierrätys
4. Geneeriset lopetukset
5. Passiivin ylikäyttö
6. Lähdeviittaukset: POISTA generiset viittaukset ("alkuperäisen uutisen mukaan", "uutinen kertoo").
   SÄILYTÄ kansainvälisten lähteiden maininta kun se on luonnollinen osa tekstiä ("BBC:n mukaan", "The Guardianin mukaan" jne.) — sallittu kerran per artikkeli.
7. Chatbot-artefaktit
8. Täytesanat ja varautumiset
9. TARKISTA KIELI: artikkelin täytyy olla suomea. Jos jokin lause on englanniksi, käännä se.
10. PITUUS: jos artikkeli on alle 180 sanaa, laajenna sitä lisäämällä kontekstia, taustaa tai seurauksia — älä toista samaa. Tavoite 250-350 sanaa.

Korjaa ongelmat ja palauta korjattu JSON-lista samassa muodossa. Vastaa VAIN JSON-listalla."""


_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 2  # seconds; doubles each attempt (2s, 4s, 8s)

# HTTP status codes worth retrying (transient)
_RETRYABLE_HTTP = {429, 500, 502, 503, 504}


def _call_llm(system: str, prompt: str) -> str:
    """Call the LLM with exponential backoff retry (3 attempts).

    Retries on: 429, 5xx, timeout, connection errors.
    Hard-fails on: 400, 401, 403 (bad request / auth — won't fix on retry).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    use_sdk = HAVE_ANTHROPIC_SDK and api_key

    last_exc = None
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            if use_sdk:
                client = anthropic.Anthropic(api_key=api_key)
                response = client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=4096,
                    system=system,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.content[0].text.strip()
            else:
                print("[writer]   Using Claude Code bridge...")
                return complete_with_claude(
                    system_prompt=system,
                    messages=[{"role": "user", "content": prompt}],
                    cwd=Path(__file__).parent.parent,
                    require_json=True,
                )

        except Exception as e:
            last_exc = e
            # Check if retryable
            status = getattr(e, "status_code", None)
            if status is not None and status not in _RETRYABLE_HTTP:
                # Hard error — no point retrying
                print(f"[writer]   LLM call failed (HTTP {status}, non-retryable): {e}")
                raise

            if attempt < _RETRY_ATTEMPTS:
                delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                print(f"[writer]   LLM call failed (attempt {attempt}/{_RETRY_ATTEMPTS}): {e}")
                print(f"[writer]   Retrying in {delay}s...")
                time.sleep(delay)
            else:
                print(f"[writer]   LLM call failed after {_RETRY_ATTEMPTS} attempts: {e}")

    raise last_exc


def _extract_json(text: str) -> list:
    """Extract JSON list from response text, handling code fences."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


def rewrite_articles(articles: List[Dict]) -> List[Dict]:
    """Write original articles from RSS leads and research data.

    Each article dict should contain:
    - title: headline from RSS
    - description: brief from RSS
    - research: (optional) additional context/facts from web research
    - source: RSS feed source name (used internally, NOT published)
    - link: RSS link (used internally, NOT published)
    """
    rewritten = []

    batch_size = 5
    for i in range(0, len(articles), batch_size):
        batch = articles[i:i + batch_size]
        print(f"[writer] Processing batch {i // batch_size + 1} ({len(batch)} articles)...")

        # English-attribution sources: always mention in article once
        ATTRIBUTION_SOURCES = {
            "BBC World", "BBC Technology", "BBC Science",
            "Reuters World", "Reuters Technology", "Reuters Science",
            "AP News",
            "The Guardian World", "The Guardian",
            "Ars Technica",
            "TechCrunch",
            "Der Spiegel International",
            "Science News",
        }

        articles_text = ""
        for idx, article in enumerate(batch):
            lang = article.get("language", "fi")
            source = article.get("source", "")
            is_international = lang != "fi" or source in ATTRIBUTION_SOURCES

            lang_note = ""
            if lang != "fi":
                lang_note = f"\nKieli: {lang} — KIRJOITA ARTIKKELI SUOMEKSI"

            attribution_note = ""
            if is_international and source:
                attribution_note = f"\nLähde (mainitse kerran luonnollisesti tekstissä): {source}"

            research = article.get("research", "")
            research_section = ""
            if research:
                research_section = f"\nTaustatutkimus:\n{research}"

            articles_text += f"""
---
Aihe {idx + 1}:
Otsikko: {article['title']}
Kuvaus: {article['description']}{research_section}{lang_note}{attribution_note}
---
"""

        prompt = f"""Kirjoita jokaisesta seuraavasta aiheesta oma, alkuperäinen uutisartikkeli.

{articles_text}

Vastaa JSON-listana:
[
  {{
    "title": "Uutisen otsikko",
    "content": "3-5 kappaletta, 200-380 sanaa. Vähintään 180 sanaa vaaditaan. Kappaleet erotetaan kahdella rivinvaihdolla.",
    "category": "Yksi: {', '.join(CATEGORIES)}",
    "original_title": "Alkuperäinen otsikko RSS:stä"
  }}
]

Vastaa VAIN JSON-listalla."""

        pass1_result = None
        try:
            # Pass 1: Write
            response_text = _call_llm(SYSTEM_PROMPT, prompt)
            pass1_result = _extract_json(response_text)
            print(f"[writer]   Pass 1 → {len(pass1_result)} articles written")
            # Word count check — flag articles under target
            for _art in pass1_result:
                _wc = len(_art.get("content", "").split())
                if _wc < 150:
                    print(f"[writer]   ⚠️  Short article ({_wc}w): {_art.get('title','')[:40]}")
        except json.JSONDecodeError as e:
            print(f"[writer] Pass 1 JSON parse error (batch {i // batch_size + 1}): {e}")
            print(f"[writer]   Skipping batch — no parseable output")
            continue
        except Exception as e:
            print(f"[writer] Pass 1 failed after retries (batch {i // batch_size + 1}): {e}")
            import traceback
            traceback.print_exc()
            print(f"[writer]   Skipping batch")
            continue

        try:
            # Pass 2: Anti-AI audit
            audit_prompt = f"""Tarkista ja korjaa seuraavat uutisartikkelit.

{json.dumps(pass1_result, indent=2, ensure_ascii=False)}

Palauta korjattu JSON-lista samassa muodossa. Vastaa VAIN JSON-listalla."""

            audit_response = _call_llm(AUDIT_SYSTEM_PROMPT, audit_prompt)
            audited = _extract_json(audit_response)
            print(f"[writer]   Pass 2 (audit) → {len(audited)} articles cleaned")
        except Exception as e:
            # Audit failure is non-fatal — fall back to pass 1 results
            print(f"[writer]   Pass 2 (audit) failed: {e} — using pass 1 results")
            audited = pass1_result

        # Carry through metadata from input
        for j, written_article in enumerate(audited):
            if j < len(batch):
                written_article["fingerprint"] = batch[j].get("fingerprint", "")
                written_article["trending"] = batch[j].get("trending", False)
                # Do NOT carry source_name or source_url to output

        rewritten.extend(audited)
        print(f"[writer]   Batch {i // batch_size + 1} complete: {len(audited)} articles")

    return rewritten
