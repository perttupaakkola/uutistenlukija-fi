# Uutistenlukija.fi — Sisältölaadun Audit

**Deliverable:** #34
**Päivämäärä:** 2026-03-23
**Auditoija:** Monica (tutkija-agentti)

---

> ## ✅ RATKAISU (2026-03-23)
>
> **Sisältömalli päätetty:** Uutistenlukija.fi on **verkkolehti / uutismedia** joka tuottaa omaa, alkuperäistä AI-avusteista journalismia useiden lähteiden pohjalta. Emme ole uutisaggregaattori emmekä julkaise "headline + linkki ulos" -sisältöä. Kirjoitamme alkuperäisiä artikkeleita, jotka perustuvat useiden lähteiden tutkimiseen ja synteesiin. Tämä ratkaisee alla kuvatun A/B/C-valinnan: toteutamme alkuperäistä journalismia (lähimpänä entistä Option B:tä, mutta ilman "uudelleenkirjoitus"-kehystä — kyse on alkuperäisestä sisällöstä).

---

## ⚠️ ALKUPERÄINEN LÖYDÖS (historiallinen konteksti)

**Auditin aikaan sivusto julkaisi artikkeleita ilman asianmukaista läpinäkyvyyttä:**

- Täyspitkiä AI-kirjoitettuja artikkeleita fiktiivisillä suomalaisilla toimittajabylinen alla (Matti Virtanen, Sanna Heikkinen, Anna Korhonen...) — ilman lähteenosoituksia
- Puutteellinen AI-sisällön ilmoittaminen

**Nämä ongelmat on nyt tunnistettu ja korjaukset käynnissä.** Fiktiiviset bylinet poistetaan, lähdeattribuutio lisätään, ja AI-sisältö merkitään läpinäkyvästi. Koska kirjoitamme alkuperäistä journalismia useiden lähteiden pohjalta (emme kopioi tai aggregoi yksittäisiä artikkeleita), Art. 15 / Kopiosto-riskit eivät ole suoraan sovellettavissa — mutta toimituksellinen standardi edellyttää silti, ettei lähdemateriaalia kopioida sanatarkasti.

---

## KOKONAISARVOSANA: C+

| Alue | Arvosana |
|------|----------|
| Suomen kielen laatu | B+ |
| Otsikkolaatu | C |
| Tarkkuus/koherenssi | C |
| Lähdetransparenssi | F |
| Kategorisointi | B |
| Juridinen compliance | D |
| UX/design | A- |

---

## P0 — KRIITTISET LÖYDÖKSET

1. **Fiktiiviset toimittajabylinet** jokaisessa artikkelissa — "Laura Mäkelä · Tiedetoimittaja" yms. Esittää AI-sisältöä oikeana journalismina. Eettisesti ja juridisesti vaarallista.
2. **Ei lähteenosoituksia** — yksikään artikkeli ei linkitä alkuperäiseen lähteeseen
3. **"Sähkön keskihinta Suomessa alhaisin Ruotsin pääkaupungeissa"** — kieliopillisesti rikki, tarkoitus ymmärtämätön
4. **"Yehuda Sherman's kuoleman jälkeen"** — englannin possessiivi suomenkielisessä tekstissä (käännöspipeline-artefakti)
5. **"MacBook Neo"** — tuotetta ei olemassa. Potentiaalinen AI-hallusinaatio.

## PATTERN — YÖLLINEN HEIKKO SISÄLTÖ

Artikkeleita julkaistu klo 01:11, 03:52, 04:33, 05:52 — automaatti ajaa yöllä ilman laadunvalvontaa. Nämä ovat heikointa sisältöä: ruotsalaiset ammattilehdet, Chuck Norris -meemit, irrelevantit yhdysvaltalaiset uutiset.

---

## POSITIIVISTA

- ✅ Suomen kielen laatu on yleisesti hyvä
- ✅ UX/design on **erinomainen** — parempi kuin Ampparit
- ✅ Hyvät artikkelit löytyvät: Sudan, Wilma Murto, Suvi Minkkinen
- ✅ Kaikki 8 kategoriaa toimii ja sisältöä on
- ✅ Footer-linkit (tietosuoja, evästeet, käyttöehdot) paikallaan

---

## SISÄLTÖMALLI — PÄÄTETTY ✅

**Ratkaisu: Alkuperäinen AI-avusteinen journalismi**

Uutistenlukija.fi toimii verkkolehtenä, joka tuottaa alkuperäisiä artikkeleita AI:n avulla useiden lähteiden pohjalta. Tämä ei ole aggregointia eikä yksittäisten artikkeleiden uudelleenkirjoitusta — kyse on alkuperäisestä journalismista, jossa AI tutkii useita lähteitä ja kirjoittaa oman artikkelin.

**Toimitukselliset standardit:**
- AI-sisältö merkitään läpinäkyvästi (byline: "Uutistenlukija · AI-toimitus")
- Lähdeattribuutio artikkelin lopussa (käytetyt lähteet listataan)
- Ei sanatarkkaa kopiointia lähdemateriaaleista — tämä on toimituksellinen standardi
- EU AI Act Art. 50 -valmius (voimaan elokuussa 2026)

**Juridinen arvio:** Koska tuotamme alkuperäistä sisältöä useiden lähteiden synteesinä, Art. 15 / Kopiosto-riskit eivät ole suoraan sovellettavissa. Uutiskeräin.fi:n malli (joka aggregoi ja julkaisi suoraan lähdesisältöä) on eri asia kuin alkuperäisen journalismin tuottaminen.
