# Uutistenlukija.fi — Sisältölaadun Audit

**Deliverable:** #34
**Päivämäärä:** 2026-03-23
**Auditoija:** Monica (tutkija-agentti)

---

## ⚠️ KRIITTINEN LÖYDÖS

**Sivusto on live, mutta se EI OLE se aggregaattori jonka suunnittelimme.**

- **Suunnitelma:** headline + 120-char preview + linkki alkuperäiseen mediaan
- **Todellisuus:** Täyspitkiä AI-generoituja artikkeleita fiktiivisillä suomalaisilla toimittajabylinen alla (Matti Virtanen, Sanna Heikkinen, Anna Korhonen...) — ilman lähteenosoituksia, ilman linkkejä alkuperäisiin medioihin

**Tämä on Uutiskeräin.fi -malli** joka johti sen sulkemiseen (Kopiosto vaati maksua → sulki).

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

## KOLME VAIHTOEHTOA — PERTTU PÄÄTETTÄVÄKSI

**Option A: Palaa aggregaattorisuunnitelmaan** (RSS + 120-char + linkki ulos)
- Juridisesti turvallisin
- Vastaa sprintin suunnitelmaa
- Eliminoi Art. 15 ja Kopiosto-riskin

**Option B: Pidä täysartikkelit, mutta transparentisti**
- Lisää "AI-tiivistelmä lähteestä: [URL]"
- Poista fiktiiviset bylinet
- Juridisesti edelleen riskialtis mutta rehellinen

**Option C: Hybridi**
- Etusivu = aggregaattori (headline + preview + linkki)
- Kooste-osio = AI-tiivistelmät attribuutiolla
- Kompromissi, mutta monimutkaisempi

---

## SUOSITUS

**Option A on ainoa turvallinen valinta.** Fiktiiviset toimittajabylinet + täysartikkelit + ei lähteitä = sama malli joka tappoi Uutiskeräin.fi:n. Tarvitaan päätös ennen kuin aloitetaan markkinointi.
