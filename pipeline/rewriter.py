"""
Article Writer — transforms RSS leads into original journalism.

Pipeline: RSS headline → web research → multi-source synthesis → original article.
Two-pass system: write + anti-AI audit pass.

Requires OPENAI_API_KEY environment variable.
Uses OpenAI API (gpt-4o-mini). No Anthropic dependency.
"""

import os
import json
import sys
import time
from typing import List, Dict
from pathlib import Path

from openai import OpenAI

CATEGORIES = ["Kotimaa", "Ulkomaat", "Talous", "Teknologia", "Urheilu", "Kulttuuri", "Tiede"]

SYSTEM_PROMPT = """Olet kokenut suomalainen uutistoimittaja. Kirjoitat omia, alkuperäisiä uutisartikkeleita.

Saat uutisaiheen otsikon, taustatietoja ja tutkimustuloksia useista lähteistä. Tehtäväsi on kirjoittaa oma, itsenäinen uutisartikkeli näiden pohjalta.

PITUUS — KRIITTINEN VAATIMUS:
- Minimipituus: 250 sanaa. EI POIKKEUKSIA.
- Tavoitepituus: 300–400 sanaa.
- Jos lähdemateriaali on lyhyt, LAAJENNA se — lisää taustatietoja, kontekstia ja merkitystä:
  * Mitä tapahtui aiemmin tässä asiassa?
  * Miksi tämä on tärkeää lukijalle?
  * Mitkä ovat seuraukset tai vaikutukset?
  * Liittyykö tämä johonkin laajempaan ilmiöön tai kehitykseen?
- ÄLÄ koskaan kirjoita alle 250 sanan artikkelia. Lyhyet lähdetekstit vaativat enemmän taustatietoa ja kontekstia, eivät tiivistämistä.

TÄRKEÄÄ:
- Kirjoita AINA suomeksi, myös jos lähdemateriaali on englanniksi.
- Tämä on SINUN artikkelisi. Älä viittaa "alkuperäiseen uutiseen" tai "raportin mukaan" (paitsi jos tiedät raportin nimen).
- Poikkeus KANSAINVÄLISET LÄHTEET: jos artikkeli on englanninkielisestä lähteestä (BBC, Reuters, AP, The Guardian, Ars Technica, TechCrunch, Der Spiegel jne.), mainitse lähde luonnollisesti kerran — esim. "BBC:n mukaan", "The Guardianin mukaan", "Ars Technica raportoi". Ei enempää.
- Muille artikkeleille: älä mainitse lähdettä ollenkaan.

RAKENNE JA OTSIKOT:
- Kirjoita 4–6 kappaletta.
- Käytä 1–2 H2-väliotsikkoa (## Otsikko) jäsentämään artikkeli — aina kun artikkeli on 300+ sanaa.
- Alle 300 sanan artikkeleissa EI väliotsikoita — suora kertomus.
- Väliotsikot ovat informatiivisia, eivät klikkiotsikoita: "Mitä tapahtui seuraavaksi" → "Tilanne kehittyi nopeasti".
- Vain ensimmäinen sana isolla väliotsikoissa.

OTSIKON SÄÄNNÖT:
- Sisällytä uutiskoukku: miksi tämä on tärkeää juuri tänään?
- Käytä konkreettisia nimiä, paikkoja ja lukuja kun mahdollista
- Rakenne: toimija + teko (esim. "Tuomari pakotti", "Poliisi julkaisi")
- Jos tarina koskee Suomea tai suomalaisia, mainitse se otsikossa
- Maksimipituus: 80 merkkiä
- EI klikkiotsikoita ("uskomatonta", "tämä muuttaa kaiken", "hämmästyttävää" jne.)
- Jos artikkeli on lähes identtinen aiemman kanssa samalta päivältä: palauta DUPLICATE
- Jos sisältö ei sovi uutissivustolle (mainokset, kasinopelit, PR-tekstit): palauta FILTER

KIRJOITUSTYYLI:
- Aloita suoraan asiasta.
- Lyhyet, suorat lauseet. Vaihtele pituutta.
- Neutraalia yleiskieltä — ei puhekieltä eikä virkasuomea.
- Vältä kliseitä: "merkittävä", "historiallinen", "mullistava" — paitsi jos se oikeasti on sitä.
- Vältä passiivia kun aktiivi toimii.
- Ei emojeja tai otsikkolistoja.
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
10. TARKISTA RAKENNE: pidemmissä artikkeleissa (300+ sanaa) tulee olla 1-2 H2-väliotsikkoa (## Otsikko).
    Lyhyissä (alle 300 sanaa) ei väliotsikoita. Lisää tai poista tarvittaessa.
11. TARKISTA PITUUS: artikkelin täytyy olla vähintään 250 sanaa. Jos artikkeli on lyhyempi,
    laajenna sitä lisäämällä asiayhteyden, taustan tai vaikutusten kuvausta. ÄLÄ koskaan
    palauta alle 250 sanan artikkelia.

Korjaa ongelmat ja palauta korjattu JSON-lista samassa muodossa. Vastaa VAIN JSON-listalla."""


_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 2  # seconds; doubles each attempt (2s, 4s, 8s)

# HTTP status codes worth retrying (transient)
_RETRYABLE_HTTP = {429, 500, 502, 503, 504}

# Reuse a single client instance per process
_openai_client: "OpenAI | None" = None


def _get_client() -> "OpenAI":
    global _openai_client
    if _openai_client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        _openai_client = OpenAI(api_key=api_key)
    return _openai_client


def _call_llm(system: str, prompt: str) -> str:
    """Call OpenAI gpt-4o-mini with exponential backoff retry (3 attempts).

    Retries on: 429, 5xx, timeout, connection errors.
    Hard-fails on: 400, 401, 403 (bad request / auth — won't fix on retry).
    """
    last_exc = None
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            client = _get_client()
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=4096,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            )
            return response.choices[0].message.content.strip()

        except Exception as e:
            last_exc = e
            status = getattr(e, "status_code", None)
            if status is not None and status not in _RETRYABLE_HTTP:
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


def _build_single_prompt(article: dict) -> str:
    """Build a rewrite prompt for a single article."""
    ATTRIBUTION_SOURCES = {
        "BBC World", "BBC Technology", "BBC Science",
        "Reuters World", "Reuters Technology", "Reuters Science",
        "AP News", "The Guardian World", "The Guardian",
        "Ars Technica", "TechCrunch", "Der Spiegel International", "Science News",
    }
    lang = article.get("language", "fi")
    source = article.get("source", "")
    is_international = lang != "fi" or source in ATTRIBUTION_SOURCES

    lang_note = f"\nKieli: {lang} — KIRJOITA ARTIKKELI SUOMEKSI" if lang != "fi" else ""
    attribution_note = (f"\nLähde (mainitse kerran luonnollisesti tekstissä): {source}"
                        if is_international and source else "")
    research = article.get("research", "")
    research_section = f"\nTaustatutkimus:\n{research}" if research else ""

    return f"""Kirjoita seuraavasta aiheesta oma, alkuperäinen uutisartikkeli.

---
Otsikko: {article['title']}
Kuvaus: {article['description']}{research_section}{lang_note}{attribution_note}
---

Vastaa JSON-listana (lista yhdellä alkiolla):
[
  {{
    "title": "Uutisen otsikko",
    "content": "4-6 kappaleen uutisteksti...",
    "category": "Yksi: {', '.join(CATEGORIES)}",
    "original_title": "Alkuperäinen otsikko RSS:stä"
  }}
]

Vastaa VAIN JSON-listalla."""


def _rewrite_individually(batch: List[Dict]) -> List[Dict]:
    """Fallback: rewrite each article in the batch one at a time.

    Slower but recovers content when batch JSON parsing fails.
    """
    results = []
    for idx, article in enumerate(batch):
        print(f"[writer]   Individual rewrite {idx + 1}/{len(batch)}: '{article.get('title', '')[:50]}'")
        try:
            prompt = _build_single_prompt(article)
            response_text = _call_llm(SYSTEM_PROMPT, prompt)
            parsed = _extract_json(response_text)
            if parsed and isinstance(parsed, list):
                item = parsed[0]
                item["fingerprint"] = article.get("fingerprint", "")
                item["trending"] = article.get("trending", False)
                results.append(item)
        except Exception as e:
            print(f"[writer]   Individual rewrite failed for '{article.get('title', '')[:40]}': {e}")
    return results


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

    batch_size = 1
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
    "content": "4-6 kappaleen uutisteksti. Kappaleet erotetaan kahdella rivinvaihdolla (\\n\\n). Pidemmissä artikkeleissa (300+ sanaa) käytä 1-2 H2-väliotsikkoa muodossa '## Otsikko' omalla rivillään. Lyhyissä (alle 300 sanaa) ei väliotsikoita.",
    "category": "Yksi: {', '.join(CATEGORIES)}",
    "original_title": "Alkuperäinen otsikko RSS:stä"
  }}
]

Vastaa VAIN JSON-listalla."""

        pass1_result = None
        try:
            # Pass 1: Write (batch)
            response_text = _call_llm(SYSTEM_PROMPT, prompt)
            pass1_result = _extract_json(response_text)
            print(f"[writer]   Pass 1 → {len(pass1_result)} articles written")
        except json.JSONDecodeError as e:
            print(f"[writer] Pass 1 JSON parse error (batch {i // batch_size + 1}): {e}")
            print(f"[writer]   Retrying batch once...")
            try:
                response_text = _call_llm(SYSTEM_PROMPT, prompt)
                pass1_result = _extract_json(response_text)
                print(f"[writer]   Batch retry succeeded → {len(pass1_result)} articles")
            except json.JSONDecodeError as e2:
                print(f"[writer]   Batch retry still failed ({e2}). Falling back to individual rewrites...")
                pass1_result = _rewrite_individually(batch)
                if not pass1_result:
                    print(f"[writer]   Individual fallback produced 0 articles. Skipping batch.")
                    continue
                print(f"[writer]   Individual fallback → {len(pass1_result)} articles")
            except Exception as e2:
                print(f"[writer]   Batch retry failed: {e2}. Falling back to individual rewrites...")
                pass1_result = _rewrite_individually(batch)
                if not pass1_result:
                    print(f"[writer]   Individual fallback produced 0 articles. Skipping batch.")
                    continue
                print(f"[writer]   Individual fallback → {len(pass1_result)} articles")
        except Exception as e:
            print(f"[writer] Pass 1 failed after retries (batch {i // batch_size + 1}): {e}")
            import traceback
            traceback.print_exc()
            print(f"[writer]   Falling back to individual rewrites...")
            pass1_result = _rewrite_individually(batch)
            if not pass1_result:
                print(f"[writer]   Individual fallback produced 0 articles. Skipping batch.")
                continue
            print(f"[writer]   Individual fallback → {len(pass1_result)} articles")

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

        # Pass 3: Per-article expansion retry for anything under 200 words
        EXPANSION_SYSTEM = """Olet uutistoimittaja. Sinulle annetaan lyhyt uutisartikkeli.
Laajenna se vähintään 250 sanaan lisäämällä:
- Taustatieto: mitä aiheen ympärillä on tapahtunut aiemmin?
- Konteksti: miksi tämä on merkittävää tai miten se liittyy laajempaan kehitykseen?
- Seuraukset tai vaikutukset: mitä tämä tarkoittaa ihmisille tai yhteiskunnalle?
Säilytä alkuperäinen otsikko ja faktat. Kirjoita luonnollista suomea.
Vastaa VAIN JSON-muodossa: {"title": "...", "content": "...", "category": "...", "original_title": "..."}"""

        expanded_audited = []
        for article in audited:
            word_count = len(article.get("content", "").split())
            if word_count < 200:
                title = article.get("title", "")
                print(f"[writer]   ⚠ Short ({word_count}w), expanding: '{title[:50]}'")
                try:
                    expand_prompt = f"""Laajenna tämä artikkeli vähintään 250 sanaan:\n\n{json.dumps(article, ensure_ascii=False, indent=2)}\n\nVastaa VAIN JSON-objektina."""
                    expand_response = _call_llm(EXPANSION_SYSTEM, expand_prompt)
                    # Response is a single object, not a list
                    expand_text = expand_response.strip()
                    if expand_text.startswith("```"):
                        expand_text = expand_text.split("```")[1]
                        if expand_text.startswith("json"):
                            expand_text = expand_text[4:]
                        expand_text = expand_text.strip()
                    expanded = json.loads(expand_text)
                    new_count = len(expanded.get("content", "").split())
                    print(f"[writer]   Expanded: {word_count}w → {new_count}w")
                    # Keep original metadata
                    expanded["fingerprint"] = article.get("fingerprint", "")
                    expanded["trending"] = article.get("trending", False)
                    expanded_audited.append(expanded)
                except Exception as e:
                    print(f"[writer]   Expansion failed ({e}), keeping original")
                    expanded_audited.append(article)
            else:
                expanded_audited.append(article)

        # Filter sentinels and carry through metadata
        kept = []
        for j, written_article in enumerate(expanded_audited):
            title = written_article.get("title", "")
            content = written_article.get("content", "")
            # Check for DUPLICATE / FILTER sentinel (title or content starts with it)
            sentinel = None
            for field in (title, content):
                upper = field.strip().upper()
                if upper.startswith("DUPLICATE"):
                    sentinel = "DUPLICATE"
                    break
                if upper.startswith("FILTER"):
                    sentinel = "FILTER"
                    break
            if sentinel:
                orig = batch[j].get("title", "?") if j < len(batch) else "?"
                print(f"[writer]   {sentinel}: '{orig[:60]}' — skipped")
                continue

            # Quality flags — warn but don't drop here (quality gate in run_pipeline.py)
            word_count = len(content.split())
            title_len = len(title)
            if word_count < 150:
                print(f"[writer]   ⚠ Still short after expansion ({word_count} words): '{title[:50]}'")
            if title_len > 100 or title_len < 10:
                print(f"[writer]   ⚠ Suspicious title length ({title_len} chars): '{title[:60]}'")

            if j < len(batch):
                written_article["fingerprint"] = batch[j].get("fingerprint", "")
                written_article["trending"] = batch[j].get("trending", False)
                # Do NOT carry source_name or source_url to output
            kept.append(written_article)

        rewritten.extend(kept)
        print(f"[writer]   Batch {i // batch_size + 1} complete: {len(kept)}/{len(expanded_audited)} articles kept")

    return rewritten
