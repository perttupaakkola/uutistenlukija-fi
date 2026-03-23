# Uutistenlukija.fi — Source Tier Analysis

**Deliverable:** #29
**Viimeksi päivitetty:** 2026-03-22

---

## PART 1: CURRENT SOURCE AUDIT

| Source | Rating | Key finding |
|--------|--------|-------------|
| Yle | ⭐⭐⭐ T1 | Foundational — paras lähde kaikilla mittareilla. Jos vain yksi lähde, Yle. |
| Ilta-Sanomat | ⭐⭐⭐ T1 | Hyvä. IS Viihde-feed tarvitsee clickbait-filterin ("Katso kuvat:") |
| Kauppalehti | ⭐⭐⭐ T1 | Must-have Talouteen. Paywall-tunnistus tarvitaan (/plus/ URL-polku) |
| Turun Sanomat | ⭐⭐ T2 | Hyvä alueellinen diversiteetti. Ei tabloid-ongelmia. |
| Verkkouutiset | ⭐⭐ T2 | OK Politiikalle. Oikeistolainen paino — seurata |
| Tekniikka & Talous | ⭐⭐⭐ T1* | Loistava kun verified. Tärkein suomenkielinen teknologialähde. |
| Pelaaja.fi | ⭐⭐ T2 | Pelaaminen OK, pieni volyymi |
| Ars Technica | ⭐⭐⭐ T1 | Paras kansainvälinen teknologialähde |
| ScienceNews | ⭐⭐ T2 | Korkea laatu, pieni volyymi |
| Iltalehti | ⭐⭐ T2 cond. | Juridinen riski. Korkein clickbait-taso kaikista lähteistä. |

---

## PART 2: GAP ANALYSIS

| Kategoria | Tila | Kriittisin puute |
|-----------|------|-----------------|
| Kotimaa | OK | Ei aluelehtiä Turun lisäksi |
| Ulkomaat | ⚠️ Thin | Ei kansainvälistä wire-serviceä — BBC aktivoitava heti |
| Talous | Good | Ei startup/PK-fokusta |
| Politiikka | OK | Ei analyyttistä pitkää journalismia |
| Teknologia | Good | Englannispainotteinen |
| Urheilu | Good | Ei lajispesifisiä lähteitä (SM-liiga, Palloliitto) |
| Kulttuuri | Thin | Ei elokuva/musiikki-erikoislähteitä |
| Terveys | ❌ Kriittinen | Lähes tyhjä — vain IL Terveys (juridinen riski) |

---

## PART 3: 10 NEW SOURCE RECOMMENDATIONS

| # | Source | RSS | Prioriteetti | Miksi |
|---|--------|-----|-------------|-------|
| 1 | BBC News (7 feeds) | feeds.bbci.co.uk/news/... | 🔴 Viikko 2 | Korjaa Ulkomaat + Terveys kerralla |
| 2 | Duodecim | duodecim.fi/feed/ | 🔴 Viikko 2 | Ainoa luotettava FI terveyslähde |
| 3 | Muropaketti | muropaketti.com/feed/ | 🟡 Viikko 2-3 | FI-kielinen tekniikka/pelit |
| 4 | The Verge (4 feeds) | theverge.com/rss/ | 🟡 Viikko 2-3 | AI-feed = tekoäly-avainsanat |
| 5 | Suomen Kuvalehti | suomenkuvalehti.fi/feed/ | 🟡 Viikko 3 | Analyyttinen pitkä journalismi |
| 6 | Uusi Suomi | uusisuomi.fi/feed/ | 🟡 Viikko 3 | Kotimaan diversiteetti ⚠️ sulje /puheenvuoro/ |
| 7 | New Scientist | newscientist.com/feed/ | 🟢 Viikko 3-4 | Tiede-premium |
| 8 | Variety (4 feeds) | variety.com/feed/ | 🟢 Viikko 4 | Kulttuuri & Viihde EN |
| 9 | ArcticStartup | arcticstartup.com/feed/ | 🟢 Kuukausi 2 | Nordic startup-ekosysteemi |
| 10 | SM-liiga | liiga.fi/feed/ (verify) | 🟡 Ennen MM-kisoja | Jääkiekko-MM alkaa 15.5. |

---

## PART 4: QUALITY GATE FAILURE PATTERNS

**Alexille 4 konkreettista filtteriä:**

1. **Clickbait-regex** — hylkää jos otsikossa: "katso kuvat", "katso video", "kohupaljastus", "juuri nyt:", tai isoja kirjaimia ≥4 peräkkäin
2. **Liian lyhyt preview** — jos `<description>` < 30 merkkiä, näytä vain otsikko
3. **Paywall-tunnistus** — Kauppalehti URL `/plus/` tai `/premium/` → merkitse `[Tilaajille]`
4. **Uusi Suomi -blogisuodatin** — sulje URL-polku `/puheenvuoro/` kokonaan

---

## PART 5: FINAL TIER MAP

**Tier 1 (6 lähdettä):** Yle, IS, Kauppalehti, Ars Technica, TS, BBC _(lisää viikko 2)_
**Tier 2 (11 lähdettä):** TekniikkaTalous, Verkkouutiset, Pelaaja, ScienceNews, Duodecim, Muropaketti, Verge, SuomenKuvalehti, UusiSuomi, NewScientist, Variety
**Tier 2 conditional:** IL _(Pertun päätös)_, HS _(suositus: skip)_
**Tier 3:** ArcticStartup, SM-liiga, Talouselämä, AP News
**Excluded:** tiede.fi, tivi.fi, kaleva.fi, aamulehti.fi, suomenuutiset.fi

---

## KATEGORIAKATEALUEEN MUUTOS TIER 2:N AKTIVOINNIN JÄLKEEN

| Kategoria | Tier 1 | Tier 1+2 |
|-----------|--------|----------|
| Ulkomaat | ⚠️ Ohut | ✅ Hyvä |
| Terveys | ❌ Kriittinen | ✅ OK |
| Kulttuuri | ⚠️ Ohut | ✅ OK |
| Kaikki muut | ✅/⭐⭐⭐ | ✅✅ Vahva |

---

## KEY NOTES

- **Uusi Suomi -blogifiltteri** on kriittinen Alexille — ilman sitä lukijakontribuutiot livahtavat sisään
- **SM-liiga RSS pitää tutkia ennen 15.5.** — jääkiekon MM-kisat ovat Urheilu-kategorian suurin tapahtuma koko vuodelle
- **Terveys + Ulkomaat korjaantuvat** pelkästään BBC:n aktivoinnilla — yksi toimenpide, seitsemän syötettä
- **ArcticStartup** olisi uniikki lisäarvo — ei muilla suomalaisaggregaattoreilla tätä kulmaa
