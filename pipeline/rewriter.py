"""
Article Writer — transforms RSS leads into original journalism.

Pipeline: RSS headline → web research → multi-source synthesis → original article.
Two-pass system: write + anti-AI audit pass.
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

try:
    from claude_transport import complete_with_claude, parse_json_object
except ImportError:
    pass

def _get_anthropic_oauth_token():
    """Read the Anthropic OAuth access token from openclaw's auth store."""
    import json as _json
    from pathlib import Path as _Path
    # Try multiple auth store locations
    paths = [
        _Path("/home/pertt/.openclaw/agents/felix/agent/auth-profiles.json"),
        _Path("/home/pertt/.openclaw/agents/main/agent/auth-profiles.json"),
        _Path("/home/pertt/.claude/.credentials.json"),
    ]
    for p in paths:
        try:
            data = _json.loads(p.read_text())
            # auth-profiles.json format
            prof = data.get("profiles", {}).get("anthropic:default", {})
            if prof.get("access"):
                return prof["access"]
            # .credentials.json format
            oauth = data.get("claudeAiOauth", {})
            if oauth.get("accessToken"):
                return oauth["accessToken"]
        except Exception:
            continue
    return None


CATEGORIES = ["Kotimaa", "Ulkomaat", "Talous", "Teknologia", "Urheilu", "Kulttuuri", "Tiede"]

SYSTEM_PROMPT = """Olet kokenut suomalainen uutistoimittaja. Kirjoitat omia, alkuperäisiä uutisartikkeleita.

Saat uutisaiheen otsikon, taustatietoja ja tutkimustuloksia useista lähteistä. Tehtäväsi on kirjoittaa oma, itsenäinen uutisartikkeli näiden pohjalta.

TÄRKEÄÄ:
- Tämä on SINUN artikkelisi. Älä viittaa lähteisiin, alkuperäisiin uutisiin tai muihin medioihin.
- Poikkeus: jos artikkeli perustuu yksittäisen tahon lausuntoon tai tutkimukseen, mainitse se luonnollisesti osana tekstiä.
- Älä mainitse "alkuperäistä lähdettä", "raportin mukaan" (paitsi jos tiedät raportin nimen), "uutisen mukaan" tms.
- Kirjoita 3-5 kappaletta, 200-400 sanaa.

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

TEKOÄLYKIRJOITUKSEN VÄLTTÄMINEN (stop-slop):

Kielletyt fraasit ja rakenteet:
- Ei "Lisäksi", "Toisaalta", "On huomionarvoista", "On syytä huomata", "Samalla on todettava"
- Ei "kokonaisvaltainen", "ekosysteemi" (kuvainnollisesti), "moniulotteinen", "merkittävä" (ellei oikeasti ole)
- Ei "Tämä tarkoittaa sitä, että", "Kyse on siitä, että", "On selvää, että"
- Ei "herättää kysymyksiä", "jää nähtäväksi", "aika näyttää", "tulevaisuus näyttää"

Rakenteet joita välttää:
- Ei binäärivastakohtia ("Kyse ei ole X:stä. Kyse on Y:stä.") — sano suoraan Y
- Ei negatiivisia listoja ("Ei X. Ei Y. Vaan Z.") — sano suoraan Z
- Ei dramaattisia fragmentteja ("Yksi sana. Muutos.") — kirjoita kokonaisia lauseita
- Ei retorisia kysymyksiä joihin vastataan heti seuraavassa lauseessa
- Ei kolmen sarjoja joka kappaleessa (kaksi asiaa riittää, tai yksi)
- Ei synonyymien kierrätystä (yhtiö/firma/toimija/yritys samasta asiasta)

Passiivin ja toimijuuden säännöt:
- Nimeä tekijä aina kun mahdollista ("päätös syntyi" → "hallitus päätti")
- Ei elottomille asioille inhimillisiä verbejä ("tilanne kertoo" → "asiantuntijat tulkitsevat")
- Aktiivi ensin, passiivi vain kun tekijä on oikeasti tuntematon

Rytmi ja muoto:
- Vaihtele lausepituutta — ei tasaisen metronomista tekstiä
- Ei ajatusviivoja (—) lainkaan
- Ei lihavointia, kursivointia tai typografisia tehosteita
- Älä lopeta kappaletta iskevällä yksilauseisella — vaihtele lopetuksia
- Jos lause kuulostaa sitaatilta tai aforismilta, kirjoita se uudelleen

Täytesanat (poista aina):
- "erittäin", "todella", "varsin", "erityisesti", "nimenomaan"
- "käytännössä", "periaatteessa", "pohjimmiltaan", "itse asiassa"
- "tietyllä tavalla", "jossain määrin", "tavallaan"

Ei mainosmaista kieltä. Ei chatbot-artefakteja. Anna faktojen puhua.

Vastaa VAIN JSON-muodossa."""

AUDIT_SYSTEM_PROMPT = """Olet tarkka kielentarkistaja. Tarkista uutisartikkelit tekoälykirjoituksen merkkien varalta ja korjaa.

TARKISTETTAVAT ASIAT:

1. Kielletyt fraasit — poista: "Lisäksi", "Toisaalta", "On huomionarvoista", "On syytä huomata", "Samalla on todettava", "Tämä tarkoittaa sitä, että", "Kyse on siitä, että", "On selvää, että", "herättää kysymyksiä", "jää nähtäväksi", "aika näyttää", "tulevaisuus näyttää"
2. Täytesanat — poista: "erittäin", "todella", "varsin", "erityisesti", "nimenomaan", "käytännössä", "periaatteessa", "pohjimmiltaan", "itse asiassa", "tietyllä tavalla", "jossain määrin", "tavallaan"
3. Binäärivastakohtarakenteet — "Kyse ei ole X:stä. Kyse on Y:stä." → sano suoraan Y
4. Kolmen sarjat — jos kolme asiaa listataan peräkkäin, karsi kahteen tai yhteen
5. Retoriset kysymykset joihin vastataan heti → poista kysymys, sano asia suoraan
6. Passiivin ylikäyttö — nimeä tekijä ("päätös tehtiin" → "hallitus päätti")
7. Elottomien asioiden inhimilliset verbit ("tilanne kertoo", "luvut paljastavat") → nimeä ihminen
8. Synonyymien kierrätys — käytä yhtä termiä johdonmukaisesti
9. Tasainen rytmi — vaihtele lausepituutta, ei metronomia
10. Ajatusviivat (—) — poista kaikki, käytä pistettä tai pilkkua
11. Aforistiset lopetukset — jos viimeinen lause kuulostaa sitaatilta, kirjoita se uudelleen
12. Paisuttelu ja mainosmainen kieli
13. Viittaukset alkuperäisiin lähteisiin tai muihin uutismedioihin (POISTA — tämä on meidän oma artikkeli)

PISTEYTYS (arvioi ennen korjausta):
- Suoruus (1-10): Sanooko asia suoraan vai kierteleekö?
- Rytmi (1-10): Vaihteleva vai metronominen?
- Luottamus (1-10): Kunnioittaako lukijan älyä?
- Aitous (1-10): Kuulostaako ihmiseltä?
- Tiiviys (1-10): Voiko jotain karsia?

Jos yhteispistemäärä on alle 35/50, kirjoita artikkeli kokonaan uudelleen.

Korjaa ongelmat ja palauta korjattu JSON-lista samassa muodossa. Vastaa VAIN JSON-listalla."""


def _call_llm(system: str, prompt: str) -> str:
    """Call the LLM with fallback chain: gpt-4.1-nano -> gpt-4.1-mini -> bridge."""
    models = [
        {
            "name": "gpt-4.1-nano",
            "provider": "openai",
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4.1-nano",
        },
        {
            "name": "gpt-4.1-mini",
            "provider": "openai",
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4.1-mini",
        },
    ]

    last_error = None
    for m in models:
        api_key = os.environ.get(m["api_key_env"])
        if not api_key and m.get("api_key_fn"):
            try:
                api_key = globals()[m["api_key_fn"]]()
            except Exception:
                pass
        if not api_key:
            continue
        try:
            if m["provider"] == "anthropic" and HAVE_ANTHROPIC_SDK:
                client = anthropic.Anthropic(api_key=api_key)
                response = client.messages.create(
                    model=m["model"],
                    max_tokens=4096,
                    system=system,
                    messages=[{"role": "user", "content": prompt}],
                )
                result = response.content[0].text.strip()
            elif m["provider"] in ("openrouter", "openai"):
                import urllib.request as _ur
                import urllib.error as _ue
                body = json.dumps({
                    "model": m["model"],
                    "max_tokens": 4096,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                }).encode()
                req = _ur.Request(
                    m["base_url"] + "/chat/completions",
                    data=body,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                )
                with _ur.urlopen(req, timeout=120) as resp:
                    data = json.loads(resp.read())
                result = data["choices"][0]["message"]["content"].strip()
            else:
                continue
            print(f"[writer]   Model: {m['name']} (success)")
            return result
        except Exception as e:
            last_error = e
            print(f"[writer]   Model {m['name']} failed: {e}")
            continue

    # All API models failed — try Claude Code bridge as last resort
    try:
        print("[writer]   All API models failed. Trying Claude Code bridge...")
        return complete_with_claude(
            system_prompt=system,
            messages=[{"role": "user", "content": prompt}],
            cwd=Path(__file__).parent.parent,
            require_json=True,
        )
    except Exception:
        pass

    raise ValueError(f"All LLM providers failed. Last error: {last_error}")


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

{articles_text}

Vastaa JSON-listana:
[
  {{
    "title": "Uutisen otsikko",
    "content": "3-5 kappaleen uutisteksti. Kappaleet erotetaan kahdella rivinvaihdolla.",
    "category": "Yksi: {', '.join(CATEGORIES)}",
    "original_title": "Alkuperäinen otsikko RSS:stä"
  }}
]

Vastaa VAIN JSON-listalla."""

        try:
            # Pass 1: Write
            response_text = _call_llm(SYSTEM_PROMPT, prompt)
            parsed = _extract_json(response_text)
            print(f"[writer]   Pass 1 → {len(parsed)} articles written")

            # Pass 2: Anti-AI audit
            audit_prompt = f"""Tarkista ja korjaa seuraavat uutisartikkelit.

{json.dumps(parsed, indent=2, ensure_ascii=False)}

Palauta korjattu JSON-lista samassa muodossa. Vastaa VAIN JSON-listalla."""

            audit_response = _call_llm(AUDIT_SYSTEM_PROMPT, audit_prompt)
            audited = _extract_json(audit_response)
            print(f"[writer]   Pass 2 (audit) → {len(audited)} articles cleaned")

            # Carry through metadata from input
            for j, written_article in enumerate(audited):
                if j < len(batch):
                    written_article["fingerprint"] = batch[j].get("fingerprint", "")
                    written_article["trending"] = batch[j].get("trending", False)
                    # Do NOT carry source_name or source_url to output

            rewritten.extend(audited)

        except json.JSONDecodeError as e:
            print(f"[writer] JSON parse error: {e}")
            if 'parsed' in locals():
                for j, written_article in enumerate(parsed):
                    if j < len(batch):
                        written_article["fingerprint"] = batch[j].get("fingerprint", "")
                        written_article["trending"] = batch[j].get("trending", False)
                rewritten.extend(parsed)
                print(f"[writer]   Using pass 1 results (audit parse failed)")
        except Exception as e:
            print(f"[writer] Error in batch {i // batch_size + 1}: {e}")
            import traceback
            traceback.print_exc()
            # Retry once after 5 seconds for transient failures
            try:
                import time as _time
                _time.sleep(5)
                print(f"[writer] Retrying batch {i // batch_size + 1}...")
                response_text = _call_llm(SYSTEM_PROMPT, prompt)
                parsed = _extract_json(response_text)
                for j, written_article in enumerate(parsed):
                    if j < len(batch):
                        written_article["fingerprint"] = batch[j].get("fingerprint", "")
                        written_article["trending"] = batch[j].get("trending", False)
                rewritten.extend(parsed)
                print(f"[writer]   Retry succeeded: {len(parsed)} articles")
            except Exception as e2:
                print(f"[writer]   Retry also failed: {e2}")

    return rewritten
