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

SYSTEM_PROMPT = """Olet kokenut suomalainen uutistoimittaja, joka kirjoittaa Helsingin Sanomien tasolla.

Saat uutisaiheen otsikon, taustatietoja ja mahdollisesti tutkimustuloksia lähteistä. Kirjoita oma, itsenäinen uutisartikkeli näiden pohjalta.

PITUUS JA SISÄLTÖ:
- Kirjoita 5-8 kappaletta, 400-700 sanaa. Lyhyempi artikkeli on HYLÄTTY.
- Jokaisessa artikkelissa on oltava KONKREETTISIA FAKTOJA: lukuja, prosentteja, nimiä, aikamääreitä, paikkoja.
- Jos taustatietoja on vähän, keskity niihin faktoihin joita sinulla ON. Älä keksi faktoja, mutta syvennä olemassa olevia.
- Älä KOSKAAN viittaa kuviin, kaavioihin, infograafeihin tai visuaaliseen materiaaliin, jota artikkelissa ei ole.
- Älä mainitse "kuvan mukaan", "kaaviosta näkyy", "alla oleva kuva" tai vastaavia. Muunna visuaalinen tieto tekstimuotoon.

TÄRKEÄÄ:
- Tämä on SINUN artikkelisi. Älä viittaa lähteisiin, alkuperäisiin uutisiin tai muihin medioihin.
- Poikkeus: kun artikkeli perustuu tietyn tahon lausuntoon, tutkimukseen tai tilastoon, mainitse lähde nimeltä luonnollisesti osana tekstiä (esim. "Tilastokeskuksen mukaan", "Financial Timesin analyysin perusteella").
- Älä mainitse "alkuperäistä lähdettä", "raportin mukaan" (paitsi jos tiedät raportin nimen), "uutisen mukaan" tms.

RAKENNE (HS-tyylinen):
- 1. kappale: Tärkein fakta tai uutinen suoraan. Ei johdattelua.
- 2.-3. kappale: Tausta ja konteksti. Miksi tämä on tärkeää? Miten tilanne on kehittynyt?
- 4.-6. kappale: Yksityiskohdat, numerot, reaktiot tai asiantuntija-arviot (jos tietoa on).
- 7.-8. kappale: Mitä seuraavaksi tapahtuu? Mikä on aikataulu? Lopeta konkreettiseen faktaan.

KIRJOITUSTYYLI:
- Aloita suoraan asiasta. Ei "johdanto"-lauseita.
- Vaihtele lauseiden pituutta: lyhyitä ja pitkiä sekaisin.
- Neutraalia, selkeää yleiskieltä — kuin HS:n uutissivuilla.
- Käytä aktiivissa aina kun mahdollista.
- Ei emojeja, lihavointia tai otsikkolistoja.
- Suomeksi vain ensimmäinen sana isolla otsikoissa.
- Lopeta viimeiseen faktaan, ei geneeriseen yhteenvetoon.

TEKOÄLYKIRJOITUKSEN VÄLTTÄMINEN — KRIITTISTÄ:
Seuraavat ovat ehdottomia kieltoja. Jos mikään näistä esiintyy tekstissä, artikkeli on hylätty:
- "Lisäksi", "Toisaalta", "On huomionarvoista", "On syytä huomata"
- "kokonaisvaltainen", "ekosysteemi" (kuvainnollisesti), "herättää keskustelua"
- "aiheuttaa huolta", "jännitteet lisääntyvät/kasvavat" (yleisluontoisesti ilman konkretiaa)
- "haasteita" (toistuvasti eri kappaleissa), "merkittävä" (ilman konkretiaa)
- Kolmen listan toistaminen joka kappaleessa
- Synonyymien pyörittäminen (yhtiö/firma/toimija/yritys samasta asiasta)
- Geneeriset lopetukset: "Aika näyttää", "Tulevaisuus näyttää", "herättää kysymyksiä"
- Tyhjät "vaikuttaa"-väitteet ilman lukuja (esim. "vaikuttaa talouteen" — MITEN ja kuinka paljon?)
- "polarisoituu", "eriytyy", "syventää eroja" ilman konkreettisia lukuja

OTSIKKO:
- Napakka, informatiivinen, ei clickbait.
- Kerro tärkein uutinen otsikossa.
- Ei kaksoispistettä jokaisen otsikon alussa.
- Esimerkki hyvästä: "Fedin ohjauskorko pysyy ennallaan 3,50–3,75 prosentissa"
- Esimerkki huonosta: "Yksi kuva kertoo paljon USA:n taloudesta"

Vastaa VAIN JSON-muodossa."""

AUDIT_SYSTEM_PROMPT = """Olet uutistoimituksen laaduntarkistaja. Tehtäväsi on varmistaa, että artikkeli on Helsingin Sanomien tasolla.

HYLKÄÄ JA KIRJOITA UUDELLEEN jos:
1. Artikkeli on alle 350 sanaa — kirjoita pidempi versio samoilla tiedoilla
2. Artikkeli viittaa kuviin, kaavioihin tai visuaaliseen materiaaliin — poista viittaukset ja muunna tieto tekstiksi
3. Artikkeli sisältää tekoälysanastoa (ks. alla) — poista ja korvaa konkreettisilla ilmaisuilla

TEKOÄLYSANASTON TARKISTUS — poista tai korvaa:
- "Lisäksi", "Toisaalta", "On huomionarvoista", "On syytä huomata"
- "kokonaisvaltainen", "ekosysteemi" (kuvainnollisesti)
- "herättää keskustelua", "aiheuttaa huolta", "herättää kysymyksiä"
- Geneeriset lopetukset ("Aika näyttää", "Tulevaisuus näyttää")
- Tyhjät vaikuttamisväitteet ilman lukuja
- "polarisoituu", "eriytyy" ilman konkreettisia lukuja
- Synonyymien pyörittäminen (yhtiö/firma/toimija/yritys samasta asiasta)
- Passiivilauseita joissa aktiivi olisi selkeämpi

MUU TARKISTUS:
- Onko otsikko informatiivinen (kertoo uutisen) vai geneerinen?
- Alkaako artikkeli suoraan uutisesta vai tyhjällä johdattelulla?
- Loppuuko viimeiseen konkreettiseen faktaan vai geneeriseen pyörittelyyn?
- Onko artikkeli kielellisesti luontevaa suomea?

Korjaa ongelmat ja palauta korjattu JSON-lista samassa muodossa. Vastaa VAIN JSON-listalla."""


def _call_llm(system: str, prompt: str) -> str:
    """Call the LLM via Anthropic SDK or transport bridge."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    use_sdk = HAVE_ANTHROPIC_SDK and api_key

    if use_sdk:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=8192,
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

    batch_size = 3  # Smaller batches = better quality per article
    for i in range(0, len(articles), batch_size):
        batch = articles[i:i + batch_size]
        print(f"[writer] Processing batch {i // batch_size + 1} ({len(batch)} articles)...")

        articles_text = ""
        for idx, article in enumerate(batch):
            lang = article.get("language", "fi")
            lang_note = ""
            if lang != "fi":
                lang_note = f"\nKieli: {lang} (KIRJOITA SUOMEKSI)"

            research = article.get("research", "")
            research_section = ""
            if research:
                research_section = f"\nTaustatutkimus:\n{research}"

            articles_text += f"""
---
Aihe {idx + 1}:
Otsikko: {article['title']}
Kuvaus: {article['description']}{research_section}{lang_note}
---
"""

        prompt = f"""Kirjoita jokaisesta seuraavasta aiheesta oma, alkuperäinen uutisartikkeli.

MUISTA:
- Jokaisessa artikkelissa 5-8 kappaletta, 400-700 sanaa
- Konkreettisia faktoja, lukuja ja nimiä
- ÄLÄ viittaa kuviin tai kaavioihin joita ei ole
- ÄLÄ käytä tekoälysanastoa (Lisäksi, Toisaalta, herättää keskustelua, jne.)
- Lopeta konkreettiseen faktaan, ei geneeriseen pohdintaan

{articles_text}

Vastaa JSON-listana:
[
  {{
    "title": "Napakka, informatiivinen otsikko joka kertoo uutisen",
    "content": "5-8 kappaleen uutisteksti (400-700 sanaa). Kappaleet erotetaan kahdella rivinvaihdolla.",
    "category": "Yksi: {', '.join(CATEGORIES)}",
    "original_title": "Alkuperäinen otsikko RSS:stä"
  }}
]

Vastaa VAIN JSON-listalla."""

        MAX_RETRIES = 3
        for attempt in range(1, MAX_RETRIES + 1):
            parsed = None
            try:
                # Pass 1: Write
                response_text = _call_llm(SYSTEM_PROMPT, prompt)
                parsed = _extract_json(response_text)
                if not parsed:
                    raise ValueError("LLM returned empty list")
                print(f"[writer]   Pass 1 → {len(parsed)} articles written (attempt {attempt})")

                # Pass 2: Anti-AI audit
                audit_prompt = f"""Tarkista ja korjaa seuraavat uutisartikkelit.

{json.dumps(parsed, indent=2, ensure_ascii=False)}

Palauta korjattu JSON-lista samassa muodossa. Vastaa VAIN JSON-listalla."""

                audit_response = _call_llm(AUDIT_SYSTEM_PROMPT, audit_prompt)
                try:
                    audited = _extract_json(audit_response)
                except json.JSONDecodeError:
                    print(f"[writer]   Audit parse failed, using pass 1 results")
                    audited = parsed

                if not audited:
                    audited = parsed

                print(f"[writer]   Pass 2 (audit) → {len(audited)} articles cleaned")

                # Carry through metadata from input
                for j, written_article in enumerate(audited):
                    if j < len(batch):
                        written_article["fingerprint"] = batch[j].get("fingerprint", "")
                        written_article["trending"] = batch[j].get("trending", False)
                        # Do NOT carry source_name or source_url to output

                rewritten.extend(audited)
                break  # Success — exit retry loop

            except json.JSONDecodeError as e:
                print(f"[writer] JSON parse error (attempt {attempt}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES:
                    wait = 10 * attempt
                    print(f"[writer]   Retrying in {wait}s...")
                    time.sleep(wait)
                elif parsed:
                    # Last attempt: salvage pass 1 results if available
                    for j, written_article in enumerate(parsed):
                        if j < len(batch):
                            written_article["fingerprint"] = batch[j].get("fingerprint", "")
                            written_article["trending"] = batch[j].get("trending", False)
                    rewritten.extend(parsed)
                    print(f"[writer]   Using pass 1 results after {MAX_RETRIES} failed attempts")
            except (ValueError, Exception) as e:
                print(f"[writer] Error (attempt {attempt}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES:
                    wait = 10 * attempt
                    print(f"[writer]   Retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    print(f"[writer]   Batch failed after {MAX_RETRIES} attempts, skipping")
                    import traceback
                    traceback.print_exc()

    return rewritten
