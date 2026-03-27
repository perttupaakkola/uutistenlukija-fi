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
import re
from pathlib import Path

from openai import OpenAI

CATEGORIES = ["Kotimaa", "Ulkomaat", "Talous", "Teknologia", "Urheilu", "Kulttuuri", "Tiede"]

# Load SEO keyword data for natural keyword injection into articles
_SEO_KEYWORDS_PATH = Path(__file__).parent / "seo_keywords.json"
try:
    with open(_SEO_KEYWORDS_PATH) as _f:
        SEO_KEYWORDS: Dict[str, Dict] = json.load(_f)
except Exception:
    SEO_KEYWORDS = {}

SYSTEM_PROMPT = """Olet kokenut suomalainen uutistoimittaja. Kirjoitat omia, alkuperäisiä uutisartikkeleita.

=== PITUUS — TÄRKEIN VAATIMUS, LUE ENSIN ===
Jokaisen artikkelin TÄYTYY olla 300–400 sanaa. ABSOLUUTTINEN MINIMI ON 280 SANAA.
Laske sanat mielessäsi: tavallinen kappale on 60–80 sanaa. Tarvitset VÄHINTÄÄN 4 täyttä kappaletta.
Jos ensimmäinen versio jää alle 280 sanan, jatka kirjoittamista — lisää kontekstia, taustaa ja seurauksia.
LYHYET LÄHDETEKSTIT TARKOITTAVAT ENEMMÄN TAUSTAA, EI LYHYEMPÄÄ ARTIKKELIA.

Kun lähdemateriaali on lyhyt, laajenna AINA näillä tavoilla:
  * Tausta: Mitä tapahtui aiemmin tässä asiassa? Mikä johti tähän tilanteeseen?
  * Merkitys: Miksi tämä on tärkeää lukijalle? Ketä tämä koskee?
  * Seuraukset: Mitkä ovat seuraukset tai vaikutukset lähiaikoina?
  * Laajempi kehys: Liittyykö tämä johonkin laajempaan ilmiöön tai trendiin?
  * Lisäfaktat: VAIN faktat jotka esiintyvät lähdetekstissä — älä keksi tilastoja.

KIELLETTY — älä koskaan tee näin:
- Älä keksi tilastoja, lukuja, vuosilukuja tai lainauksia joita ei ole lähdetekstissä
- Jos lähde ei sisällä tilastoja, älä lisää niitä — laajenna kontekstilla, taustoituksella tai merkityksellä
- Älä päätä artikkelia yleisellä tulevaisuuden pohdinnalla tai tyhjällä yhteenvedolla — lopeta konkreettiseen tietoon

Saat uutisaiheen otsikon, taustatietoja ja tutkimustuloksia useista lähteistä. Tehtäväsi on kirjoittaa oma, itsenäinen uutisartikkeli näiden pohjalta.

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
11. TARKISTA PITUUS: artikkelin täytyy olla vähintään 280 sanaa (tavoite 300–400). Jos artikkeli on lyhyempi,
    laajenna sitä lisäämällä taustan, kontekstin ja vaikutusten kuvausta. ÄLÄ koskaan
    palauta alle 280 sanan artikkelia. Tavallinen kappale on 60–80 sanaa.
12. TARKISTA journalist_note: säilytä se vain jos siinä on aitoa toimituksellista lisäarvoa. Poista geneerinen tai itsestään selvä huomio käyttämällä tyhjää merkkijonoa.
13. TARKISTA content_type: pidä oletuksena "article". Käytä "analysis" vain aidosti moninäkökulmaiseen, kehittyvään tai tulkintaa vaativaan aiheeseen.
14. TARKISTA editorial_reviewed: sen tulee aina olla true.
15. TARKISTA key_points: kentässä tulee olla tasan 3 suomenkielistä kohtaa. Poista luettelomerkit, tiivistä muotoon yksi ydinajatus per kohta ja pidä yhteispituus enintään 300 merkissä aina kun mahdollista.
16. SISÄISET LINKIT: Lisää artikkelin sisältöön enintään 3 kontekstuaalista sisäistä linkkiä markdown-muodossa. Linkitä VAIN ensimmäinen maininta per kohde. Käytä näitä linkkejä:
    - "kotimaa" → [kotimaa](/categories/kotimaa/)
    - "ulkomaat" → [ulkomaat](/categories/ulkomaat/)
    - "talous" tai "talousuutiset" → [talous](/categories/talous/)
    - "teknologia" → [teknologia](/categories/teknologia/)
    - "urheilu" → [urheilu](/categories/urheilu/)
    - "kulttuuri" → [kulttuuri](/categories/kulttuuri/)
    - "tiede" → [tiede](/categories/tiede/)
    - "uutiskirje" → [uutiskirje](/uutiskirje/)
    Lisää linkit vain jos sana esiintyy luonnollisesti lauseessa. Älä pakota linkkejä. Jos artikkelissa ei ole sopivia kohtia, jätä sisältö ennalleen.

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




MAX_KEY_POINTS_TOTAL_CHARS = 300


def _sanitize_key_point(text: str) -> str:
    text = re.sub(r"^\s*[-•*\d.)\s]+", "", str(text or "").strip())
    text = " ".join(text.split())
    text = text.strip("\"“”'’.,;:!?-–— ")
    return text


def _rebalance_key_points(points: List[str], max_total_chars: int = MAX_KEY_POINTS_TOTAL_CHARS) -> List[str]:
    points = [_sanitize_key_point(p) for p in points if _sanitize_key_point(p)]
    if not points:
        return []

    points = points[:3]
    total = sum(len(p) for p in points)
    if total <= max_total_chars:
        return points

    lengths = [len(p) for p in points]
    total_len = sum(lengths) or 1
    targets = [max(40, int(max_total_chars * (length / total_len))) for length in lengths]
    overflow = sum(targets) - max_total_chars
    idx = 0
    while overflow > 0 and targets:
        if targets[idx % len(targets)] > 40:
            targets[idx % len(targets)] -= 1
            overflow -= 1
        idx += 1
        if idx > 1000:
            break

    trimmed = []
    for point, limit in zip(points, targets):
        if len(point) <= limit:
            trimmed.append(point)
            continue
        cut = point[:limit].rstrip()
        if ' ' in cut and limit >= 24:
            cut = cut.rsplit(' ', 1)[0]
        cut = cut.rstrip('.,;:!?-–— ')
        trimmed.append(cut)

    if sum(len(p) for p in trimmed) > max_total_chars:
        # Final hard trim from the longest points first.
        while sum(len(p) for p in trimmed) > max_total_chars:
            longest_idx = max(range(len(trimmed)), key=lambda i: len(trimmed[i]))
            if len(trimmed[longest_idx]) <= 20:
                break
            trimmed[longest_idx] = trimmed[longest_idx][:-1].rstrip(' .,;:!?-–—')

    return [_sanitize_key_point(p) for p in trimmed if _sanitize_key_point(p)]


def _fallback_key_points(article: Dict) -> List[str]:
    source_text = " ".join(
        str(article.get(field, ""))
        for field in ("summary", "description", "content")
        if article.get(field)
    )
    sentences = re.split(r"(?<=[.!?])\s+", source_text)
    cleaned = []
    seen = set()
    for sentence in sentences:
        point = _sanitize_key_point(sentence)
        if len(point) < 20:
            continue
        key = point.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(point)
        if len(cleaned) == 3:
            break
    return _rebalance_key_points(cleaned)


def _normalize_key_points(article: Dict) -> List[str]:
    raw = article.get("key_points", [])
    if isinstance(raw, str):
        raw = [part for part in re.split(r"[\n•]+", raw) if part.strip()]
    elif not isinstance(raw, list):
        raw = []

    points = _rebalance_key_points([str(item) for item in raw])
    if len(points) < 3:
        fallback = _fallback_key_points(article)
        for point in fallback:
            if len(points) >= 3:
                break
            if point.casefold() not in {p.casefold() for p in points}:
                points.append(point)
        points = _rebalance_key_points(points)
    return points[:3]

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

    # SEO keyword hint: inject 2-3 category keywords naturally
    category_hint = article.get("category_hint", "")
    seo_note = ""
    for cat, data in SEO_KEYWORDS.items():
        if cat.lower() in (category_hint or "").lower() or category_hint == cat:
            kws = data.get("inject", [])[:3]
            if kws:
                kws_str = ", ".join(f'"{k}"' for k in kws)
                seo_note = (
                    f"\nHakusanaohje: Sisällytä 2–3 seuraavista hakutermeistä luonnollisesti artikkeliin: {kws_str}. "
                    "Älä toista niitä keinotekoisesti — käytä vain jos sopii lauseyhteyteen."
                )
            break

    return f"""Kirjoita seuraavasta aiheesta oma, alkuperäinen uutisartikkeli.

---
Otsikko: {article['title']}
Kuvaus: {article['description']}{research_section}{lang_note}{attribution_note}{seo_note}
---

Vastaa JSON-listana (lista yhdellä alkiolla):
[
  {{
    "title": "Uutisen otsikko",
    "content": "4-6 kappaleen uutisteksti...",
    "category": "Yksi: {', '.join(CATEGORIES)}",
    "tags": ["avainsana1", "avainsana2"],
    "summary": "2-3 lauseen tiivistelmä suomeksi lukijalle.",
    "original_title": "Alkuperäinen otsikko RSS:stä",
    "journalist_note": "40-100 sanan toimituksellinen huomio TAI tyhjä merkkijono jos ei lisäarvoa",
    "content_type": "article tai analysis",
    "editorial_reviewed": true,
    "key_points": ["Kohta 1", "Kohta 2", "Kohta 3"]
  }}
]

"tags": 2–5 konkreettista suomenkielistä avainsanaa artikkelista (esim. "tekoäly", "NATO", "korot"). Käytä yksikköä ja pieniä kirjaimia.
"summary": 2-3 lauseen tiivistelmä artikkelista suomeksi. Selkeä, informatiivinen, ei klikkiotsikko-tyylinen.
"journalist_note": lisää VAIN noin 20–30 % artikkeleista. Kirjoita 40–100 sanaa toimituksellista taustaa, merkitystä tai kontekstia. Ei geneeristä filler-tekstiä. Jos huomio ei tuo oikeaa lisäarvoa, käytä tyhjää merkkijonoa.
"content_type": käytä oletuksena "article". Käytä "analysis" VAIN kun aihe on aidosti monikulmainen, kehittyvä, kiistanalainen tai vaatii tulkintaa useasta näkökulmasta.
"editorial_reviewed": aina true.
"key_points": tasan 3 suomenkielistä bullet-kohtaa. Ytimekkäitä, informatiivisia, eivät kokonaisia pitkiä lausekappaleita. Pyri siihen, että kaikkien kolmen kohdan yhteispituus on enintään 300 merkkiä.

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

    batch_size = 3  # Reduced from 5 — model cuts articles short in large batches
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

            # SEO keyword hint
            category_hint = article.get("category_hint", "")
            seo_note = ""
            for cat, data in SEO_KEYWORDS.items():
                if cat.lower() in (category_hint or "").lower() or category_hint == cat:
                    kws = data.get("inject", [])[:3]
                    if kws:
                        kws_str = ", ".join(f'"{k}"' for k in kws)
                        seo_note = (
                            f"\nHakusanaohje: sisällytä 2–3 seuraavista luonnollisesti: {kws_str}."
                        )
                    break

            articles_text += f"""
---
Aihe {idx + 1}:
Otsikko: {article['title']}
Kuvaus: {article['description']}{research_section}{lang_note}{attribution_note}{seo_note}
---
"""

        prompt = f"""Kirjoita jokaisesta seuraavasta aiheesta oma, alkuperäinen uutisartikkeli.

MUISTUTUS PITUUDESTA: Jokaisen artikkelin TÄYTYY olla 300–400 sanaa (minimi 280). Tavallinen kappale on 60–80 sanaa. Tarvitset VÄHINTÄÄN 4–5 täyttä kappaletta. Lisää tausta, merkitys ja seuraukset jokaiseen artikkeliin.

{articles_text}

Vastaa JSON-listana ({len(batch)} artikkelia):
[
  {{
    "title": "Uutisen otsikko (max 80 merkkiä)",
    "content": "Vähintään 280 sanan uutisteksti. 4-6 kappaletta, erotettu \\n\\n. Käytä 1-2 H2-väliotsikkoa (## Otsikko) kun artikkeli on 300+ sanaa.",
    "category": "Yksi: {', '.join(CATEGORIES)}",
    "tags": ["avainsana1", "avainsana2"],
    "summary": "2-3 lauseen tiivistelmä suomeksi lukijalle.",
    "original_title": "Alkuperäinen otsikko RSS:stä",
    "journalist_note": "40-100 sanan toimituksellinen huomio TAI tyhjä merkkijono",
    "content_type": "article tai analysis",
    "editorial_reviewed": true,
    "key_points": ["Kohta 1", "Kohta 2", "Kohta 3"]
  }}
]

"tags": 2–5 konkreettista suomenkielistä avainsanaa jokaiseen artikkeliin (esim. "tekoäly", "NATO", "korot"). Käytä yksikköä ja pieniä kirjaimia.
"summary": 2-3 lauseen tiivistelmä artikkelista suomeksi. Selkeä, informatiivinen, ei klikkiotsikko-tyylinen.
"journalist_note": lisää VAIN noin 20–30 % artikkeleista. Kirjoita 40–100 sanaa vain kun toimituksellinen huomio tuo oikeaa lisäarvoa: taustaa, miksi asia on tärkeä tai mitä lukijan kannattaa seurata. Ei geneeristä filler-tekstiä. Muulloin käytä tyhjää merkkijonoa.
"content_type": käytä oletuksena "article". Käytä "analysis" vain aidosti moninäkökulmaisiin, kehittyviin, kiistanalaisiin tai tulkintaa vaativiin juttuihin.
"editorial_reviewed": aina true.
"key_points": tasan 3 suomenkielistä bullet-kohtaa per artikkeli. Tiiviit, konkreettiset, ei otsikkomuotoisia katkelmia. Pyri siihen, että kolmen kohdan yhteispituus on enintään 300 merkkiä.

Vastaa VAIN JSON-listalla. TARKISTA ennen vastausta: onko jokainen artikkeli vähintään 280 sanaa?"""

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
Laajenna se vähintään 300 sanaan (tavoite 320–380) lisäämällä KAIKKI seuraavista:
- Taustatieto: mitä aiheen ympärillä on tapahtunut aiemmin? Mikä johti tähän?
- Konteksti: miksi tämä on merkittävää tai miten se liittyy laajempaan kehitykseen?
- Seuraukset tai vaikutukset: mitä tämä tarkoittaa ihmisille tai yhteiskunnalle?
- Lisäfaktat: VAIN faktat jotka esiintyvät lähdetekstissä — älä keksi tilastoja tai lukuja.
KIELLETTY: Älä keksi tilastoja, vuosilukuja tai lainauksia joita ei ole lähdetekstissä. Älä päätä yleisellä tulevaisuuden pohdinnolla.
Lisää H2-väliotsikko (## Otsikko) jäsentämään teksti. Säilytä alkuperäinen otsikko ja faktat. Kirjoita luonnollista suomea.
Säilytä myös kentät journalist_note, content_type ja editorial_reviewed ennallaan, ellei journalist_note ole selvästi geneerinen — silloin tyhjennä se. editorial_reviewed on aina true.
Vastaa VAIN JSON-muodossa: {"title": "...", "content": "...", "category": "...", "original_title": "...", "journalist_note": "...", "content_type": "article", "editorial_reviewed": true}"""

        expanded_audited = []
        for article in audited:
            word_count = len(article.get("content", "").split())
            if word_count < 310:
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
            if word_count < 250:
                print(f"[writer]   ⚠ Still short after expansion ({word_count} words): '{title[:50]}'")
            if title_len > 100 or title_len < 10:
                print(f"[writer]   ⚠ Suspicious title length ({title_len} chars): '{title[:60]}'")

            if j < len(batch):
                written_article["fingerprint"] = batch[j].get("fingerprint", "")
                written_article["trending"] = batch[j].get("trending", False)
                # Pass source attribution fields through to publisher
                for _src_field in ("source", "source_domain", "source_url", "link"):
                    if _src_field in batch[j]:
                        written_article[_src_field] = batch[j][_src_field]
            # Normalise tags — ensure list of lowercase strings, 2–5 items
            raw_tags = written_article.get("tags", [])
            if isinstance(raw_tags, list):
                written_article["tags"] = [str(t).lower().strip() for t in raw_tags if t][:5]
            else:
                written_article["tags"] = []

            # New editorial fields
            note = written_article.get("journalist_note", "")
            note = " ".join(str(note).split()).strip()
            note_words = len(note.split()) if note else 0
            if note and (note_words < 40 or note_words > 100):
                # Keep notes high-signal only; drop bad-length output instead of publishing filler
                note = ""
            written_article["journalist_note"] = note

            content_type = str(written_article.get("content_type", "article") or "article").strip().lower()
            if content_type not in {"article", "analysis"}:
                content_type = "article"
            written_article["content_type"] = content_type
            written_article["editorial_reviewed"] = True
            written_article["key_points"] = _normalize_key_points(written_article)

            kept.append(written_article)

        rewritten.extend(kept)
        print(f"[writer]   Batch {i // batch_size + 1} complete: {len(kept)}/{len(expanded_audited)} articles kept")

    return rewritten
