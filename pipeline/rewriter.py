"""
Article Rewriter — uses Anthropic API to rewrite news articles in clean Finnish.
Two-pass system: rewrite + anti-AI audit pass.
Falls back to Claude transport bridge if API key is not available.
"""

import os
import json
import sys
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
from claude_transport import complete_with_claude, parse_json_object

CATEGORIES = ["Kotimaa", "Ulkomaat", "Talous", "Teknologia", "Urheilu", "Kulttuuri", "Tiede"]

SYSTEM_PROMPT = """Olet kokenut suomalainen uutistoimittaja, joka kirjoittaa kuin ihminen — ei kuin tekoäly.

Sinulle annetaan lista uutisotsikoita ja -kuvauksia. Jokaisesta sinun tulee kirjoittaa:
1. Uusi otsikko (selkeä, informatiivinen, ei klikkiotsikko)
2. 2-4 kappaleen uutisteksti
3. Oikea kategoria seuraavista: Kotimaa, Ulkomaat, Talous, Teknologia, Urheilu, Kulttuuri, Tiede

Jos artikkeli on vieraskielinen (esim. englanninkielinen), KÄÄNNÄ ja kirjoita uutinen suomeksi. Älä jätä mitään englanniksi. Suomenna nimet ja käsitteet kun se on luontevaa. Säilytä alkuperäiset erisnimet.

KIRJOITUSTYYLI — TÄRKEÄÄ:
- Kirjoita kuin kokenut toimittaja, EI kuin tekoäly.
- Aloita suoraan asiasta. Ei "Nykypäivän muuttuvassa maailmassa..." tai "On syytä huomata, että..." -aloituksia.
- Käytä lyhyitä, suoria lauseita. Vaihtele lauseiden pituutta — osa lyhyitä, osa pidempiä.
- Vältä tyhjää korostusta: "merkittävä", "historiallinen", "mullistava", "keskeinen", "ratkaiseva" — käytä vain jos asia oikeasti on sitä.
- Vältä passiivia kun aktiivi toimii: "Hallitus päätti" > "Päätös tehtiin"
- Kappaleiden pituus saa vaihdella: osa 1-2 lausetta, osa pidempiä.
- Kirjoita neutraalia, selkeää yleiskieltä. Ei puhekieltä, mutta ei myöskään jäykkää virkasuomea.

TEKOÄLYKIRJOITUKSEN MERKIT — VÄLTÄ NÄITÄ KAIKKIA:

1. MERKITTÄVYYDEN PAISUTTELU: Älä kirjoita "merkitsee käännekohtaa", "mullistaa alan", "historiallinen hetki". Anna faktojen puhua.
2. NIMIEN PUDOTTELU KOROSTUSKEINONA: Älä korosta henkilöiden merkitystä turhaan. Kerro mitä tapahtui.
3. PINNALLISET -ING-ANALYYSIT (suomeksi -minen/-mista): Älä kirjoita "symboloiden... heijastaen... osoittaen...". Kerro suoraan mitä asia tarkoittaa.
4. MAINOSMAINEN KIELI: Ei "kiehtova", "ainutlaatuinen", "upea", "henkeäsalpaava". Neutraali kuvailu riittää.
5. EPÄMÄÄRÄISET VIITTAUKSET: Ei "Asiantuntijat uskovat", "Tutkijat arvioivat" ilman konkreettista lähdettä. Kerro kuka sanoi tai jätä pois.
6. KAAVAMAINEN HAASTE-MENESTYS: Ei "Haasteista huolimatta... jatkaa menestystään" -rakennetta. Se on klisee.
7. TEKOÄLYSANASTO: Vältä: "Lisäksi", "Toisaalta", "On huomionarvoista", "kokonaisvaltainen", "osoitus siitä", "maisema" (kuvainnollisesti), "ekosysteemi" (ei-biologisesti), "paradigma", "synergia". Käytä tavallisia sanoja.
8. OLLA-VERBIN VÄLTTELEMINEN: Käytä "on" ja "oli" rohkeasti. Älä korvaa niitä keinotekoisesti: "toimii", "edustaa", "muodostaa", "korostaa" kun yksinkertainen "on" riittää.
9. NEGATIIVISET RINNASTUKSET: Ei "Kyse ei ole vain X:stä, vaan myös Y:stä" -rakennetta. Kerro suoraan mistä on kyse.
10. KOLMEN SÄÄNTÖ: Älä tee kolmen sarjoja: "nopeampi, tehokkaampi ja luotettavampi" tai "innovaatio, inspiraatio ja oivallus". Vaihtele.
11. SYNONYYMIEN KIERRÄTYS: Älä vaihda samasta asiasta käytettyä sanaa joka lauseessa. "Yritys" saa olla "yritys" koko tekstin ajan, ei "yhtiö... firma... toimija...".
12. VÄÄRÄT VAIHTELUVÄLIT: Ei "aina musiikista urheiluun" tai "lapset ja vanhukset" ellei oikeasti kata koko skaalaa.
13. AJATUSVIIVAN YLIKÄYTTÖ: Käytä ajatusviivoja (—) harvoin. Pisteet ja pilkut riittävät.
14. LIHAVOINNIN YLIKÄYTTÖ: Älä lihavoi sanoja tekstissä. Otsikko riittää.
15. OTSIKKOLISTAT: Älä tee "Otsikko: selitys" -listoja tekstin sisään. Kirjoita juoksevaa tekstiä.
16. OTSIKKOJEN ISOT KIRJAIMET: Suomeksi vain ensimmäinen sana isolla. Ei "Suomen Talous Kasvoi" vaan "Suomen talous kasvoi".
17. EMOJIT: Ei emojeja uutistekstiin. Koskaan.
18. TYPOGRAFISET LAINAUSMERKIT: Käytä suoria lainausmerkkejä (" "), ei kaarevaa (" ").
19. CHATBOT-ARTEFAKTIT: Ei "Toivottavasti tämä auttaa!", "Kerron mielelläni lisää", "Kuten aiemmin mainitsin". Olet toimittaja, et chatbot.
20. KATKAISUHUOMAUTUKSET: Ei "Tietoni ulottuvat vuoteen..." tai muita tekoälyrajoituksiin viittaavia lauseita.
21. MIELISTELEVÄ SÄVY: Ei "Erinomainen kysymys!", "Tämä on todella mielenkiintoinen aihe". Kirjoita asiallisesti.
22. TÄYTESANAT: Ei "Jotta voidaan", "Johtuen siitä tosiasiasta", "On tärkeää huomata, että". Mene suoraan asiaan.
23. LIIALLINEN VARAUTUMINEN: Ei "saattaisi mahdollisesti ehkä vaikuttaa". Yksi varauma riittää, tai sano suoraan.
24. GENEERISET LOPETUKSET: Ei "Tulevaisuus näyttää valoisalta", "Aika näyttää", "Jää nähtäväksi miten tilanne kehittyy". Lopeta viimeiseen faktaan.

ÄLÄ kopioi alkuperäistä tekstiä sellaisenaan. Kirjoita uutinen omin sanoin."""

AUDIT_SYSTEM_PROMPT = """Olet tarkka kielentarkistaja, joka tunnistaa tekoälyn kirjoittaman tekstin piirteet suomenkielisessä uutistekstissä.

Saat uudelleenkirjoitettuja uutisartikkeleita JSON-listana. Tarkista jokainen artikkeli näiden 24 tekoälykirjoituksen merkin varalta ja korjaa löytämäsi ongelmat:

1. Merkittävyyden paisuttelu ("merkitsee käännekohtaa", "mullistava")
2. Turhaa korostava nimien pudottelu
3. Pinnalliset -minen/-mista-analyysit ("symboloiden... heijastaen...")
4. Mainosmainen kieli ("ainutlaatuinen", "kiehtova", "upea")
5. Epämääräiset viittaukset ("Asiantuntijat uskovat") ilman konkreettista lähdettä
6. Kaavamainen "haasteista huolimatta... menestys" -rakenne
7. Tekoälysanasto: "Lisäksi", "Toisaalta", "kokonaisvaltainen", "osoitus siitä", "ekosysteemi", "paradigma"
8. Olla-verbin turha välttely: "toimii X:nä" kun "on X" riittäisi
9. "Kyse ei ole vain X:stä, vaan Y:stä" -rakenne
10. Kolmen sarjat ("nopeampi, tehokkaampi ja luotettavampi")
11. Synonyymien kierrätys (yritys/yhtiö/firma/toimija samassa tekstissä)
12. Väärät vaihteluvälit ("musiikista urheiluun")
13. Ajatusviivan (—) liiallinen käyttö
14. Lihavoinnin liiallinen käyttö
15. Otsikkolistat tekstin sisällä
16. Virheellinen isojen kirjainten käyttö otsikoissa
17. Emojit
18. Typografiset/kaarevat lainausmerkit
19. Chatbot-ilmaukset ("Toivottavasti tämä auttaa!")
20. Tekoälyrajoituksiin viittaukset
21. Mielistelevä sävy
22. Täytesanat ("Jotta voidaan", "On tärkeää huomata")
23. Liiallinen varautuminen ("saattaisi mahdollisesti ehkä")
24. Geneeriset lopetukset ("Tulevaisuus näyttää valoisalta", "Aika näyttää")

Korjaa kaikki löytämäsi ongelmat ja palauta korjattu JSON-lista TÄSMÄLLEEN samassa muodossa kuin sait sen.
Jos teksti on jo hyvä, palauta se sellaisenaan. Älä muuta JSON-rakennetta tai kenttien nimiä.

Vastaa VAIN JSON-listalla."""


def _call_llm(system: str, prompt: str) -> str:
    """Call the LLM via Anthropic SDK or transport bridge. Returns response text."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    use_sdk = HAVE_ANTHROPIC_SDK and api_key

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
        print("[rewriter]   Using Claude Code bridge...")
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
    """Rewrite articles using two-pass system: rewrite + anti-AI audit."""
    rewritten = []

    # Process in batches of 5 to reduce API calls
    batch_size = 5
    for i in range(0, len(articles), batch_size):
        batch = articles[i:i + batch_size]
        print(f"[rewriter] Processing batch {i // batch_size + 1} ({len(batch)} articles)...")

        articles_text = ""
        for idx, article in enumerate(batch):
            lang = article.get("language", "fi")
            lang_note = ""
            if lang != "fi":
                lang_note = f"\nKieli: {lang} (KÄÄNNÄ SUOMEKSI)"

            articles_text += f"""
---
Artikkeli {idx + 1}:
Otsikko: {article['title']}
Kuvaus: {article['description']}
Lähde: {article['source']}
Linkki: {article['link']}
Julkaistu: {article['published']}{lang_note}
---
"""

        prompt = f"""Kirjoita jokaisesta seuraavasta uutisesta uudelleenkirjoitettu versio.

{articles_text}

Vastaa täsmälleen tässä JSON-muodossa (lista):
[
  {{
    "title": "Uusi otsikko",
    "content": "2-4 kappaleen uutisteksti. Kappaleet erotettu kahdella rivinvaihdolla.",
    "category": "Yksi seuraavista: {', '.join(CATEGORIES)}",
    "source_name": "Alkuperäinen lähde",
    "source_url": "Alkuperäinen linkki",
    "original_title": "Alkuperäinen otsikko"
  }}
]

Vastaa VAIN JSON-listalla, ei muuta tekstiä."""

        try:
            # Pass 1: Rewrite
            response_text = _call_llm(SYSTEM_PROMPT, prompt)
            parsed = _extract_json(response_text)
            print(f"[rewriter]   Pass 1 → {len(parsed)} articles rewritten")

            # Pass 2: Anti-AI audit
            audit_prompt = f"""Tarkista ja korjaa seuraavat uudelleenkirjoitetut uutisartikkelit tekoälykirjoituksen merkkien varalta.

{json.dumps(parsed, indent=2, ensure_ascii=False)}

Palauta korjattu JSON-lista TÄSMÄLLEEN samassa muodossa. Vastaa VAIN JSON-listalla."""

            audit_response = _call_llm(AUDIT_SYSTEM_PROMPT, audit_prompt)
            audited = _extract_json(audit_response)
            print(f"[rewriter]   Pass 2 (audit) → {len(audited)} articles cleaned")

            rewritten.extend(audited)

        except json.JSONDecodeError as e:
            print(f"[rewriter] JSON parse error: {e}")
            # If audit pass failed but first pass succeeded, use first pass
            if 'parsed' in dir():
                rewritten.extend(parsed)
                print(f"[rewriter]   Using pass 1 results (audit parse failed)")
        except Exception as e:
            print(f"[rewriter] Error: {e}")
            import traceback
            traceback.print_exc()

    return rewritten


if __name__ == "__main__":
    # Test with sample data
    sample = [
        {
            "title": "Suomen hallitus päätti uusista toimista",
            "description": "Hallitus päätti tänään useista uusista toimenpiteistä.",
            "link": "https://example.com/1",
            "published": "2025-03-15T10:00:00+00:00",
            "source": "Yle Uutiset",
            "language": "fi",
        }
    ]
    result = rewrite_articles(sample)
    print(json.dumps(result, indent=2, ensure_ascii=False))
