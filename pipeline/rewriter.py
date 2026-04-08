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
from typing import List, Dict, Optional
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

=== PITUUS ===
Tavoite 400–600 sanaa. Jos lähde on lyhyt, laajenna taustan, merkityksen ja seurausten avulla — älä täytä tyhjää tilaa keksityllä tiedolla.
Alle 300 sanan artikkelit hyväksytään vain jos lähdemateriaali on todella niukka eikä laajentaminen ole mahdollista.

Kun lähdemateriaali on lyhyt, laajenna VAIN näillä tavoilla (ilman keksittyjä faktoja):
  * Tausta: Mitä tapahtui aiemmin tässä asiassa? (vain jos tiedät sen varmasti)
  * Merkitys: Miksi tämä on tärkeää lukijalle? Ketä tämä koskee?
  * Seuraukset: Mitkä ovat mahdolliset vaikutukset? (epävarmuus OK, spekulointi ei)
  * Laajempi kehys: Yleinen ilmiö tai trendi — ilman lukuja.

=== NUMEROIDEN ABSOLUUTTINEN SÄÄNTÖ ===
KIELLETTY: Älä kirjoita YHTÄÄN numeroa, prosenttia, vuosilukua tai mittayksikköä joka EI esiinny sanasta sanaan lähdetekstissä.
Tämä sääntö on ehdoton. Ei poikkeuksia. Ei "arviolta", ei "noin", ei "viime vuonna".
Jos lähteessä ei ole lukuja → artikkelissa ei ole lukuja.
Rikkominen = artikkeli poistetaan välittömästi.

KIELLETTY — älä koskaan tee näin:
- Älä keksi lainauksia joita ei ole lähdetekstissä
- Älä päätä artikkelia yleisellä tulevaisuuden pohdinnolla tai tyhjällä yhteenvedolla — lopeta konkreettiseen tietoon
- Älä lisää markkinointipuhe-tyylistä yritystietoa (asiakasmäärät, messuosallistumiset) ellei lähde mainitse niitä

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

KIELLETYT FRAASIT — älä koskaan käytä:
- "herättää kysymyksiä" / "nostaa esiin kysymyksiä"
- "herättää huolta" (pelkkä klisee ilman faktaa)
- "voidaan todeta" / "yhteenvetona voidaan todeta"
- "on tärkeää huomata" / "on syytä huomata"
- "merkittävä askel" / "tärkeä askel"
- "läpinäkyvyys on tärkeää"
- "jokainen voi tehdä oman osuutensa"
- "aika näyttää" / "tulevaisuus näyttää" / "tulevaisuus on epävarma"
- "voimaantua" / "voimaantuminen" (hallintoslangi)
- Mitään muuta geneeristä tulevaisuus/vastuullisuus/yhteiskunta-jargonia joka ei lisää faktoja.

TEKOÄLYKIRJOITUKSEN VÄLTTÄMINEN:
- Ei "Lisäksi", "Toisaalta", "On huomionarvoista", "kokonaisvaltainen", "ekosysteemi" (kuvainnollisesti)
- Ei kolmen sarjoja joka kappaleessa
- Ei synonyymien kierrätystä (yhtiö/firma/toimija/yritys samasta asiasta)
- Ei mainosmaista kieltä
- Ei chatbot-artefakteja
- Anna faktojen puhua, älä paisuttele

=== LEDE ===
Aloita juttu heti tärkeimmällä uutisella.
Ensimmäisen virkkeen pitää kertoa mahdollisimman suoraan:
- mitä tapahtui
- kenelle tai mille asia tapahtui
- milloin, jos ajankohta on tiedossa

Älä aloita juttua taustoituksella, yleisellä ilmiökuvauksella tai epämääräisellä merkityspuheella.
Älä piilota uutista virkkeen loppuun.

Jos lähteessä on yksi selkeä uusi kehitys, sano se heti ensimmäisessä virkkeessä.
Vasta sen jälkeen voit avata taustaa, merkitystä ja seurauksia.

=== TOISTON ESTO ===
Jokaisen kappaleen pitää tuoda jutulle uusi tieto, uusi vaihe tapahtumissa tai uusi näkökulma.

Älä toista samaa pääasiaa eri sanoin useassa kappaleessa.
Älä kirjoita kappaletta, joka vain muotoilee uudelleen otsikon, ingressin tai edellisen kappaleen sisällön.
Älä päätä juttua yhteenvetoon, joka vain toistaa jo kerrotun ilman uutta tietoa.

Jos asia on jo kerrottu selvästi, siirry seuraavaan olennaiseen tietoon.
Jos uutta tietoa ei ole, jätä kappale kirjoittamatta.

=== TYYLI ===
Kirjoita selkeää, täsmällistä uutiskieltä suomeksi.
Suosi konkreettisia verbejä ja faktoja, vältä abstraktia metapuhetta.

Älä käytä geneerisiä täytefraaseja tai niiden kaltaisia ilmauksia, kuten:
- "voidaan todeta"
- "on tärkeää huomata"
- "merkittävä askel kohti"
- "herättää kysymyksiä"
- "nähtäväksi jää" / "jää nähtäväksi"
- "voidaan pitää"
- "on hyvä muistaa"
- "tämä tarkoittaa käytännössä sitä, että"
- "kaiken kaikkiaan"
- "yhteenvetona"
- "lopuksi voidaan"
- "kokonaisuutena"
- "tiivistäen"
- ÄLÄ käytä seuraavia fraseja tai niiden muunnelmia: "on syytä huomata", "tässä yhteydessä on hyvä mainita", "kuten aiemmin todettiin", "jää nähtäväksi", "asiantuntijat ovat huolissaan" (ilman nimeä). Korvaa geneerinen spekulaatio konkreettisilla faktoilla.

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
11. TARKISTA PITUUS: artikkelin täytyy olla vähintään 350 sanaa (tavoite 400–600). Jos artikkeli on lyhyempi,
    laajenna sitä lisäämällä taustan, kontekstin ja vaikutusten kuvausta. ÄLÄ koskaan
    palauta alle 350 sanan artikkelia. Tavallinen kappale on 60–80 sanaa.
12. TARKISTA journalist_note: säilytä se vain jos siinä on aitoa toimituksellista lisäarvoa. Poista geneerinen tai itsestään selvä huomio käyttämällä tyhjää merkkijonoa.
13. TARKISTA content_type: pidä oletuksena "article". Käytä "analysis" vain aidosti moninäkökulmaiseen, kehittyvään tai tulkintaa vaativaan aiheeseen.
14. TARKISTA editorial_reviewed: sen tulee aina olla true.
15. TARKISTA summary_bullets: kentässä tulee olla 3–4 lyhyttä suomenkielistä kohtaa. Poista luettelomerkit, tiivistä muotoon yksi ydinajatus per kohta ja pidä yhteispituus enintään 400 merkissä aina kun mahdollista.
16. SISÄISET LINKIT: Lisää artikkelin sisältöön enintään 3 kontekstuaalista sisäistä linkkiä markdown-muodossa. Linkitä VAIN ensimmäinen maininta per kohde. Käytä näitä linkkejä:
    - "kotimaa" → [kotimaa](/categories/kotimaa/)
    - "ulkomaat" → [ulkomaat](/categories/ulkomaat/)
    - "talous" tai "talousuutiset" → [talous](/categories/talous/)
    - "teknologia" → [teknologia](/categories/teknologia/)
    - "urheilu" → [urheilu](/categories/urheilu/)
    - "kulttuuri" → [kulttuuri](/categories/kulttuuri/)
    - "tiede" → [tiede](/categories/tiede/)
    - "uutiskirje" → [uutiskirje](/uutiskirje/)
    - "pääsiäinen" tai "pääsiäiseksi" tai "pääsiäisenä" → [pääsiäisopas](/paasiaisopas/)
    Lisää linkit vain jos sana esiintyy luonnollisesti lauseessa. Älä pakota linkkejä. Jos artikkelissa ei ole sopivia kohtia, jätä sisältö ennalleen.

Korjaa ongelmat ja palauta korjattu JSON-lista samassa muodossa. Vastaa VAIN JSON-listalla."""


QUALITY_SCORE_PROMPT = """Arvioi tämän suomenkielisen uutisartikkelin kielellinen laatu asteikolla 1–5:

5 = Luonnollista, sujuvaa uutiskieltä. Voisi olla ihmistoimittajan kirjoittama.
4 = Hyvää suomea, pieniä kömpelöyksiä mutta luettavaa.
3 = Ymmärrettävää mutta tunnistettavasti konegeneroitua. Toistoa tai täytettä.
2 = Kömpelöä, epäluonnollisia sanankäänteitä, selviä tekoälyartefakteja.
1 = Huonoa suomea, vaikeaselkoista.

Palauta VAIN JSON: {"score": <numero>, "issues": "<lyhyt selitys ongelmista>"}"""

ESCALATION_THRESHOLD = 3  # Score <= this triggers gpt-4o rewrite


def _score_article_quality(body: str) -> tuple:
    """Score Finnish quality 1-5. Returns (score, issues_text)."""
    try:
        resp = _call_llm(QUALITY_SCORE_PROMPT, f"Artikkeli:\n\n{body}", model="gpt-4o-mini")
        data = _extract_json(resp)
        if isinstance(data, dict):
            return int(data.get("score", 3)), data.get("issues", "")
    except Exception as e:
        print(f"[quality]   Scoring failed: {e}")
    return 3, ""  # Default to 3 on failure


def _escalate_to_gpt4o(article_json: dict, original_sources: str) -> dict:
    """Re-rewrite a low-quality article using gpt-4o."""
    title = article_json.get("title", "")
    body = article_json.get("body", "") or article_json.get("content", "")

    escalation_prompt = f"""Tämä artikkeli kirjoitettiin automaattisesti mutta sen suomen kielen laatu on heikko.
Kirjoita se kokonaan uudelleen paremmalla suomella. Säilytä kaikki faktat ja rakenne.

Otsikko: {title}

Alkuperäinen teksti:
{body}

Lähdemateriaali:
{original_sources[:3000]}

Palauta JSON-muodossa samalla rakenteella kuin alkuperäinen."""

    resp = _call_llm(SYSTEM_PROMPT, escalation_prompt, model="gpt-4o")
    return _extract_json(resp)


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


def _call_llm(system: str, prompt: str, model: str = "gpt-4o-mini") -> str:
    """Call OpenAI LLM with exponential backoff retry (3 attempts).

    Retries on: 429, 5xx, timeout, connection errors.
    Hard-fails on: 400, 401, 403 (bad request / auth — won't fix on retry).
    """
    last_exc = None
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            client = _get_client()
            response = client.chat.completions.create(
                model=model,
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


def _extract_json(text: str):
    """Extract JSON payload from response text, handling code fences."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


def _count_h2s(markdown: str) -> int:
    return len(re.findall(r"(?m)^##\s+", markdown or ""))


def _count_words(text: str) -> int:
    return len(str(text or "").split())


_GENERIC_ENDING_PATTERNS = re.compile(
    r"(tarina jatkuu|tulevaisuus on (nyt )?entistä|kaikki silmät ovat|"
    r"tulevat (viikot|kuukaudet|päivät) (näyttävät|kertovat|määrittävät)|"
    r"aika näyttää|jää nähtäväksi|seuraamme tilannetta|"
    r"merkittävä (hetki|askel|käänne|kehitys)|"
    r"on tärkeää,?\s+että|herättää (laajaa )?(kysymyksiä|huolta)|"
    r"voidaan todeta|yhteenvetona|kaiken kaikkiaan|"
    r"lopuksi voidaan|kokonaisuutena|tiivistäen)",
    re.IGNORECASE,
)

def _strip_generic_ending(content: str) -> str:
    """Remove last paragraph if it matches generic filler patterns."""
    if not content:
        return content
    paragraphs = [p.strip() for p in content.strip().split("\n\n") if p.strip()]
    if len(paragraphs) < 3:
        return content  # Don't strip short articles
    last = paragraphs[-1]
    # Skip if last paragraph is a H2 heading or update notice
    if last.startswith("##") or "*Uutista päivitetään" in last:
        return content
    if _GENERIC_ENDING_PATTERNS.search(last):
        stripped = "\n\n".join(paragraphs[:-1])
        print(f"[writer]   ✂ Stripped generic ending paragraph: '{last[:80]}...'")
        return stripped
    return content


def _enforce_h2_subheadings(article: Dict) -> tuple[Dict, bool, bool]:
    """Ensure long articles have at least one H2. Retry once, then warn-only."""
    content = str(article.get("content", "") or "")
    word_count = _count_words(content)
    h2_count = _count_h2s(content)
    if word_count <= 250 or h2_count >= 1:
        return article, False, h2_count >= 1

    title = article.get("title", "")
    print(f"[writer]   ⚠ Missing H2 in long article ({word_count}w), retrying: '{title[:50]}'")
    retry_prompt = f"""Lisää tähän artikkeliin 2 kuvaavaa H2-väliotsikkoa. Säilytä faktat, sävy, rakenne, linkit, journalist_note, content_type, editorial_reviewed ja summary_bullets. Älä keksi uutta tietoa. Vastaa VAIN JSON-objektina.\n\n{json.dumps(article, ensure_ascii=False, indent=2)}"""
    try:
        retried = _extract_json(_call_llm(AUDIT_SYSTEM_PROMPT, retry_prompt))
        retried_content = str(retried.get("content", "") or "")
        retried_h2_count = _count_h2s(retried_content)
        if retried_h2_count >= 1:
            print(f"[writer]   H2 retry succeeded: '{title[:50]}'")
            return retried, True, True
        print(f"[writer]   ⚠ H2 retry still missing subheadings: '{title[:50]}'")
        return retried, True, False
    except Exception as e:
        print(f"[writer]   ⚠ H2 retry failed ({e}): '{title[:50]}'")
        return article, True, False


def _enforce_min_words(article: Dict, min_words: int = 250) -> tuple[Dict, bool, bool]:
    """Ensure article meets minimum word count. Retry once, then fail closed."""
    content = str(article.get("content", "") or "")
    word_count = _count_words(content)
    if word_count >= min_words:
        return article, False, True

    title = article.get("title", "")
    print(f"[writer]   ⚠ Under minimum length ({word_count}w < {min_words}), retrying: '{title[:50]}'")
    retry_prompt = f"""Laajenna tämä artikkeli vähintään {min_words} sanaan lisäämällä kontekstia ja taustaa. Säilytä faktat, sävy, rakenne, linkit, journalist_note, content_type, editorial_reviewed ja summary_bullets. Älä keksi uutta tietoa, numeroita, lainauksia tai väitteitä. Jos tieto ei riitä, tee artikkelista vain selkeämpi ja kattavampi olemassa olevien faktojen pohjalta. Vastaa VAIN JSON-objektina.\n\n{json.dumps(article, ensure_ascii=False, indent=2)}"""
    try:
        retried = _extract_json(_call_llm(AUDIT_SYSTEM_PROMPT, retry_prompt))
        retried_count = _count_words(retried.get("content", ""))
        if retried_count >= min_words:
            print(f"[writer]   Length retry succeeded: {word_count}w → {retried_count}w: '{title[:50]}'")
            return retried, True, True
        print(f"[writer]   ⚠ Length retry still too short ({retried_count}w): '{title[:50]}'")
        return retried, True, False
    except Exception as e:
        print(f"[writer]   ⚠ Length retry failed ({e}): '{title[:50]}'")
        return article, True, False


def _normalize_title_tokens(title: str) -> set:
    """Normalize a headline into a set of lowercase tokens for overlap comparison."""
    text = re.sub(r"[^\w\s]", "", str(title or "").lower())
    # Drop very short tokens (articles, prepositions)
    return {t for t in text.split() if len(t) > 2}


def _deduplicate_articles(articles: List[Dict], threshold: float = 0.70) -> tuple[List[Dict], int]:
    """Remove near-duplicate articles based on headline token overlap.

    Compares all pairs. If overlap > threshold, keeps the longer article.
    Returns (deduplicated list, number of duplicates dropped).
    """
    if len(articles) <= 1:
        return articles, 0

    # Pre-compute token sets
    token_sets = [_normalize_title_tokens(a.get("title", "")) for a in articles]
    dropped = set()

    for i in range(len(articles)):
        if i in dropped:
            continue
        for j in range(i + 1, len(articles)):
            if j in dropped:
                continue
            tokens_i = token_sets[i]
            tokens_j = token_sets[j]
            if not tokens_i or not tokens_j:
                continue
            intersection = tokens_i & tokens_j
            union = tokens_i | tokens_j
            overlap = len(intersection) / len(union) if union else 0
            if overlap > threshold:
                # Keep the longer article
                len_i = _count_words(articles[i].get("content", ""))
                len_j = _count_words(articles[j].get("content", ""))
                drop_idx = j if len_i >= len_j else i
                keep_idx = i if drop_idx == j else j
                dropped.add(drop_idx)
                print(
                    f"[writer] DEDUP: '{articles[drop_idx].get('title', '')[:50]}' "
                    f"({overlap:.0%} overlap with '{articles[keep_idx].get('title', '')[:50]}') — dropped"
                )

    kept = [a for idx, a in enumerate(articles) if idx not in dropped]
    return kept, len(dropped)


MAX_SUMMARY_BULLETS_TOTAL_CHARS = 400


def _sanitize_bullet(text: str) -> str:
    text = re.sub(r"^\s*[-•*\d.)\s]+", "", str(text or "").strip())
    text = " ".join(text.split())
    text = text.strip("\"“”'’.,;:!?-–— ")
    return text


def _rebalance_summary_bullets(points: List[str], max_total_chars: int = MAX_SUMMARY_BULLETS_TOTAL_CHARS) -> List[str]:
    points = [_sanitize_bullet(p) for p in points if _sanitize_bullet(p)]
    if not points:
        return []

    points = points[:4]
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

    return [_sanitize_bullet(p) for p in trimmed if _sanitize_bullet(p)]


def _fallback_summary_bullets(article: Dict) -> List[str]:
    source_text = " ".join(
        str(article.get(field, ""))
        for field in ("summary", "description", "content")
        if article.get(field)
    )
    sentences = re.split(r"(?<=[.!?])\s+", source_text)
    cleaned = []
    seen = set()
    for sentence in sentences:
        point = _sanitize_bullet(sentence)
        if len(point) < 20:
            continue
        key = point.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(point)
        if len(cleaned) == 4:
            break
    return _rebalance_summary_bullets(cleaned)


def _normalize_summary_bullets(article: Dict) -> List[str]:
    raw = article.get("summary_bullets", article.get("summary_bullets", []))
    if isinstance(raw, str):
        raw = [part for part in re.split(r"[\n•]+", raw) if part.strip()]
    elif not isinstance(raw, list):
        raw = []

    points = _rebalance_summary_bullets([str(item) for item in raw])
    if len(points) < 3:
        fallback = _fallback_summary_bullets(article)
        for point in fallback:
            if len(points) >= 4:
                break
            if point.casefold() not in {p.casefold() for p in points}:
                points.append(point)
        points = _rebalance_summary_bullets(points)
    return points[:4]

def _infer_fallback_category(article: Dict) -> str:
    raw = str(article.get("category") or article.get("category_hint") or "").strip()
    if raw:
        return raw

    text = f"{article.get('title', '')} {article.get('description', '')}".lower()
    rules = [
        ("Urheilu", ["liiga", "nhl", "sm-liiga", "ottelu", "tappara", "hpk", "urheilu", "jalkapallo", "real madrid"]),
        ("Teknologia", ["tekoäly", "ai ", "chatgpt", "apple", "google", "nasa", "macbook", "teknologia", "kuulento", "artemis"]),
        ("Talous", ["talous", "kela", "eurojackpot", "komissio", "raha", "palkka", "työ", "markkina", "yritys"]),
        ("Kulttuuri", ["festivaali", "kulttuuri", "elokuva", "musiikki", "wireless festival"]),
        ("Ulkomaat", ["trump", "ukraina", "iran", "venäjä", "moskova", "orban", "pakistan", "nato", "zelenskyi"]),
    ]
    for category, needles in rules:
        if any(needle in text for needle in needles):
            return category
    return "Kotimaa"


def _build_quota_fallback_article(article: Dict) -> Optional[Dict]:
    title = str(article.get("title") or article.get("original_title") or "").strip()
    if not title:
        return None

    description = str(article.get("description") or "").strip()
    research = str(article.get("research") or article.get("research_text") or "").strip()
    source_text = str(article.get("content") or article.get("source_text") or "").strip()

    blocks: List[str] = []
    if description:
        blocks.append(description)
    if research:
        blocks.append(research)
    if source_text:
        blocks.append(source_text)

    cleaned_blocks: List[str] = []
    seen = set()
    for block in blocks:
        block = re.sub(r"\[Lähde:[^\]]+\]", "", block)
        block = re.sub(r"\n{3,}", "\n\n", block).strip()
        if len(block) < 80 or block in seen:
            continue
        seen.add(block)
        cleaned_blocks.append(block)

    if not cleaned_blocks:
        return None

    intro = description or cleaned_blocks[0].split("\n", 1)[0]
    intro = intro.strip()
    if intro and not re.search(r"[.!?]$", intro):
        intro += "."

    body_parts: List[str] = [intro, "## Mitä tiedetään nyt"]
    body_parts.extend(cleaned_blocks[:2])

    if len(cleaned_blocks) > 2:
        body_parts.append("## Miksi asia on tärkeä")
        body_parts.extend(cleaned_blocks[2:4])

    body = "\n\n".join(part for part in body_parts if part).strip()
    if len(body.split()) < 180:
        body = "\n\n".join([intro, "## Tilannekuva", "\n\n".join(cleaned_blocks)]).strip()

    if len(body.split()) < 120:
        return None

    summary = description or re.sub(r"\s+", " ", body).strip()[:220]
    category = _infer_fallback_category(article)
    source_name = str(article.get("source") or article.get("source_name") or article.get("domain") or "").strip()
    link = str(article.get("link") or article.get("url") or article.get("source_url") or "").strip()

    return {
        "title": title,
        "content": body,
        "summary": summary,
        "category": category,
        "tags": [category.lower(), "uutiset", "tilannekuva"],
        "summary_bullets": _fallback_summary_bullets({"description": summary, "content": body}),
        "source_name": source_name,
        "source_url": link,
    }


def _build_quota_fallback_batch(batch: List[Dict]) -> List[Dict]:
    fallback_articles: List[Dict] = []
    for article in batch:
        fallback_article = _build_quota_fallback_article(article)
        if fallback_article:
            fallback_articles.append(fallback_article)
    if fallback_articles:
        print(f"[writer]   Emergency quota fallback produced {len(fallback_articles)} article(s).")
    return fallback_articles


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
    "summary_bullets": ["Kohta 1", "Kohta 2", "Kohta 3"]
  }}
]

"tags": 2–5 konkreettista suomenkielistä avainsanaa artikkelista (esim. "tekoäly", "NATO", "korot"). Käytä yksikköä ja pieniä kirjaimia.
"summary": 2-3 lauseen tiivistelmä artikkelista suomeksi. Selkeä, informatiivinen, ei klikkiotsikko-tyylinen.
"journalist_note": lisää VAIN noin 20–30 % artikkeleista. Kirjoita 40–100 sanaa toimituksellista taustaa, merkitystä tai kontekstia. Ei geneeristä filler-tekstiä. Jos huomio ei tuo oikeaa lisäarvoa, käytä tyhjää merkkijonoa.
"content_type": käytä oletuksena "article". Käytä "analysis" VAIN kun aihe on aidosti monikulmainen, kehittyvä, kiistanalainen tai vaatii tulkintaa useasta näkökulmasta.
"editorial_reviewed": aina true.
"summary_bullets": 3–4 lyhyttä suomenkielistä bullet-kohtaa. Ytimekkäitä, informatiivisia, eivät kokonaisia pitkiä lausekappaleita. Pyri siihen, että kaikkien kolmen kohdan yhteispituus on enintään 400 merkkiä.

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
            fallback_article = _build_quota_fallback_article(article)
            if fallback_article:
                print(f"[writer]   Emergency fallback used for '{article.get('title', '')[:40]}'")
                fallback_article["fingerprint"] = article.get("fingerprint", "")
                fallback_article["trending"] = article.get("trending", False)
                results.append(fallback_article)
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
    h2_metric_long_articles = 0
    h2_metric_with_h2 = 0
    h2_metric_retries = 0
    h2_metric_warns = 0
    min_words_metric_checked = 0
    min_words_metric_passed = 0
    min_words_metric_retries = 0
    min_words_metric_failed = 0

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

MUISTUTUS PITUUDESTA: Jokaisen artikkelin TÄYTYY olla 400–600 sanaa (minimi 350). Tavallinen kappale on 60–80 sanaa. Tarvitset VÄHINTÄÄN 5–7 täyttä kappaletta. Lisää tausta, merkitys ja seuraukset jokaiseen artikkeliin.

{articles_text}

Vastaa JSON-listana ({len(batch)} artikkelia):
[
  {{
    "title": "Uutisen otsikko (max 80 merkkiä)",
    "content": "Vähintään 350 sanan uutisteksti. 5-7 kappaletta, erotettu \\n\\n. Käytä 1-2 H2-väliotsikkoa (## Otsikko) kun artikkeli on 300+ sanaa.",
    "category": "Yksi: {', '.join(CATEGORIES)}",
    "tags": ["avainsana1", "avainsana2"],
    "summary": "2-3 lauseen tiivistelmä suomeksi lukijalle.",
    "original_title": "Alkuperäinen otsikko RSS:stä",
    "journalist_note": "40-100 sanan toimituksellinen huomio TAI tyhjä merkkijono",
    "content_type": "article tai analysis",
    "editorial_reviewed": true,
    "summary_bullets": ["Kohta 1", "Kohta 2", "Kohta 3"]
  }}
]

"tags": 2–5 konkreettista suomenkielistä avainsanaa jokaiseen artikkeliin (esim. "tekoäly", "NATO", "korot"). Käytä yksikköä ja pieniä kirjaimia.
"summary": 2-3 lauseen tiivistelmä artikkelista suomeksi. Selkeä, informatiivinen, ei klikkiotsikko-tyylinen.
"journalist_note": lisää VAIN noin 20–30 % artikkeleista. Kirjoita 40–100 sanaa vain kun toimituksellinen huomio tuo oikeaa lisäarvoa: taustaa, miksi asia on tärkeä tai mitä lukijan kannattaa seurata. Ei geneeristä filler-tekstiä. Muulloin käytä tyhjää merkkijonoa.
"content_type": käytä oletuksena "article". Käytä "analysis" vain aidosti moninäkökulmaisiin, kehittyviin, kiistanalaisiin tai tulkintaa vaativiin juttuihin.
"editorial_reviewed": aina true.
"summary_bullets": 3–4 lyhyttä suomenkielistä bullet-kohtaa per artikkeli. Tiiviit, konkreettiset, ei otsikkomuotoisia katkelmia. Pyri siihen, että kolmen kohdan yhteispituus on enintään 400 merkkiä.

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
                    pass1_result = _build_quota_fallback_batch(batch)
                    if not pass1_result:
                        print(f"[writer]   Individual fallback produced 0 articles. Skipping batch.")
                        continue
                print(f"[writer]   Individual fallback → {len(pass1_result)} articles")
            except Exception as e2:
                print(f"[writer]   Batch retry failed: {e2}. Falling back to individual rewrites...")
                pass1_result = _rewrite_individually(batch)
                if not pass1_result:
                    pass1_result = _build_quota_fallback_batch(batch)
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
                pass1_result = _build_quota_fallback_batch(batch)
                if not pass1_result:
                    print(f"[writer]   Individual fallback produced 0 articles. Skipping batch.")
                    continue
            print(f"[writer]   Individual fallback → {len(pass1_result)} articles")

        # Stamp batch index into each written article so source metadata lookup
        # stays correct even after DUPLICATE/FILTER items are removed downstream.
        for _j, _art in enumerate(pass1_result):
            _art["_batch_idx"] = _j

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

        # Filter sentinels and carry through metadata
        kept = []
        for j, written_article in enumerate(audited):
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
                _bidx_s = written_article.get("_batch_idx", j)
                orig = batch[_bidx_s].get("title", "?") if _bidx_s < len(batch) else "?"
                print(f"[writer]   {sentinel}: '{orig[:60]}' — skipped")
                continue

            written_article, word_retried, word_ok = _enforce_min_words(written_article, min_words=250)
            min_words_metric_checked += 1
            if word_retried:
                min_words_metric_retries += 1
            if not word_ok:
                min_words_metric_failed += 1
                failed_count = _count_words(written_article.get("content", ""))
                print(f"[writer]   SKIP short article after retry ({failed_count} words): '{written_article.get('title', '')[:50]}'")
                continue
            min_words_metric_passed += 1

            written_article, h2_retried, h2_ok = _enforce_h2_subheadings(written_article)
            # Strip generic feel-good ending paragraphs programmatically
            raw_content = str(written_article.get("content", "") or "")
            cleaned_content = _strip_generic_ending(raw_content)
            if cleaned_content != raw_content:
                written_article["content"] = cleaned_content
            title = written_article.get("title", "")
            content = written_article.get("content", "")
            if _count_words(content) > 250:
                h2_metric_long_articles += 1
                if h2_retried:
                    h2_metric_retries += 1
                if h2_ok:
                    h2_metric_with_h2 += 1
                else:
                    h2_metric_warns += 1

            # Quality flags — warn but don't drop here (quality gate in run_pipeline.py)
            word_count = _count_words(content)
            title_len = len(title)
            if title_len > 100 or title_len < 10:
                print(f"[writer]   ⚠ Suspicious title length ({title_len} chars): '{title[:60]}'")

            # Use _batch_idx (stamped before any filtering) so source metadata
            # stays correctly paired even after DUPLICATE/FILTER items are skipped.
            _bidx = written_article.get("_batch_idx", j)
            if _bidx < len(batch):
                written_article["fingerprint"] = batch[_bidx].get("fingerprint", "")
                written_article["trending"] = batch[_bidx].get("trending", False)
                # Pass source attribution fields through to publisher
                for _src_field in ("source", "source_domain", "source_url", "link"):
                    if _src_field in batch[_bidx]:
                        written_article[_src_field] = batch[_bidx][_src_field]
                # Preserve source context for number validation in quality gate
                _src_article = batch[_bidx]
                written_article["source_text"] = " ".join(filter(None, [
                    str(_src_article.get("title", "")),
                    str(_src_article.get("description", "")),
                    str(_src_article.get("research", "")),
                ]))
            written_article.pop("_batch_idx", None)  # don't leak internal field to output
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
            written_article["summary_bullets"] = _normalize_summary_bullets(written_article)

            # Quality gate: score Finnish and escalate low-quality to gpt-4o
            art_body = written_article.get("content", "")
            score, issues = _score_article_quality(art_body)
            if score <= ESCALATION_THRESHOLD:
                print(f"[quality]   Score {score}/5 for '{written_article.get('title','')[:50]}' — escalating to gpt-4o")
                print(f"[quality]   Issues: {issues}")
                try:
                    upgraded = _escalate_to_gpt4o(written_article, written_article.get("source_text", ""))
                    if isinstance(upgraded, dict) and (upgraded.get("body") or upgraded.get("content")):
                        # Normalize: escalation may return "body" or "content"
                        if "body" in upgraded and "content" not in upgraded:
                            upgraded["content"] = upgraded.pop("body")
                        new_score, _ = _score_article_quality(upgraded.get("content", ""))
                        print(f"[quality]   Upgraded score: {new_score}/5")
                        if new_score > score:
                            # Preserve metadata from original
                            for key in ["category", "tags", "image_url", "image_alt", "source_url", "source_name",
                                         "content_type", "editorial_reviewed", "journalist_note", "author_title",
                                         "summary_bullets", "fingerprint", "trending", "source", "source_domain",
                                         "link", "source_text", "summary", "original_title"]:
                                if key in written_article and key not in upgraded:
                                    upgraded[key] = written_article[key]
                            written_article = upgraded
                except Exception as e:
                    print(f"[quality]   Escalation failed: {e}")
            else:
                print(f"[quality]   Score {score}/5 for '{written_article.get('title','')[:50]}' — OK")

            kept.append(written_article)

        rewritten.extend(kept)
        print(f"[writer]   Batch {i // batch_size + 1} complete: {len(kept)}/{len(audited)} articles kept")

    # Deduplicate near-identical headlines before returning
    rewritten, dedup_dropped = _deduplicate_articles(rewritten, threshold=0.70)

    min_words_rate = (min_words_metric_passed / min_words_metric_checked * 100) if min_words_metric_checked else 100.0
    h2_rate = (h2_metric_with_h2 / h2_metric_long_articles * 100) if h2_metric_long_articles else 100.0
    print(
        f"[writer] Min words (250): {min_words_metric_passed}/{min_words_metric_checked} passed ({min_words_rate:.0f}%) | retries={min_words_metric_retries} | failed={min_words_metric_failed}"
    )
    print(
        f"[writer] H2 presence: {h2_metric_with_h2}/{h2_metric_long_articles} long articles ({h2_rate:.0f}%) | retries={h2_metric_retries} | warns={h2_metric_warns}"
    )
    print(
        f"[writer] Dedup: {dedup_dropped} near-duplicate articles dropped (>{70}% headline overlap)"
    )
    return rewritten
