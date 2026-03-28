# Uutistenlukija.fi — Lukijakysely

**Deliverable:** #31
**Viimeksi päivitetty:** 2026-03-23

---

## 9 KYSYMYSTÄ (+ lyhytversio 5:llä)

| # | Kysymys | Tyyppi | Pakollinen |
|---|---------|--------|------------|
| 1 | Miten löysit Uutistenlukijan? | Monivalinta | ✅ |
| 2 | Kuinka usein käytät? | Monivalinta | ✅ |
| 3 | Milloin tyypillisesti luet? | Monivalinta (multi) | ➖ |
| 4 | Mitä kategorioita seuraat? | Monivalinta (multi) | ✅ |
| 5 | Puuttuuko jokin aihe? | Avoin teksti | ➖ |
| 6 | Puuttuuko jokin lähde? | Avoin teksti | ➖ |
| 7 | Millä laitteella käytät? | Monivalinta | ✅ |
| 8 | NPS: 0–10 suosittelisitko? | Asteikko | ✅ |
| 9 | Avoin palaute | Avoin teksti | ➖ |

---

## IMPLEMENTATION: GOOGLE FORMS (suositus)

- Ilmainen, 30 min pystyttää, suoraan Google Sheetsiin
- Trigger: näytä käyttäjälle joka on käynyt **vähintään 3 kertaa** (localStorage-laskuri)
- Footer-linkki pysyvästi, X/Twitter viikolla 2, newsletter-lopussa
- Älä näytä ensimmäisellä vierailulla

Vaihtoehto B: Typeform (kauniimpi, mutta €25/kk). Vaihtoehto C: upotettu lomake (paras, mutta Alex-työ — kuukausi 2).

---

## INCENTIVES (3 suositusta)

1. **🎁 Finnkinon lahjakortti ~€25** — arvonta opt-in sähköpostilla → nopein tapa nostaa vastausaste
2. **Vaikuttavuusviesti** — "vastauksesi vaikuttaa siihen mitä lähteitä lisäämme" → ilmainen, toimii
3. **Beta-käyttäjä -status** — early access -lista ensimmäisistä ominaisuusmuutoksista

_Suositeltu yhdistelmä: kaikki kolme samanaikaisesti._

---

## ANALYTIIKKA JA TOIMENPITEET

| Metriikka | Toimenpide |
|-----------|-----------|
| Löytyminen → Google dominoi | Boostaa SEO-panostusta |
| < 20% päivittäiskäyttäjiä | Paranna paluukoukku — newsletter, Twitter |
| Kategoria X heikko | Lisää lähteitä tai harkitse pudottamista |
| Avoimet vastaukset | Monica analysoi kuukausittain → Felix priorisoi |
| NPS < 20 | Kriittinen — selvitä avoimista syyt |
| NPS 50+ | Erinomainen — kasvupotentiaali suuri |

---

## KEY NOTES

- **NPS on yksinkertaisin tapa mitata palvelun terveyttä** kuukausittain — yksi luku kertoo enemmän kuin kymmenen muuta mittaria
- **Kysymys 6 (puuttuvat lähteet)** on arvokkain avoin kenttä — lukijat tietävät lähteistä joita me emme tunne
- **GDPR-huomiot** mukana — erityisesti sähköpostikeräys arvontaa varten vaatii erillisen opt-in checkboxin
- **Lyhytversio** (5 kysymystä) on valmis popup-käyttöön jos Alex toteuttaa exit-intent-tunnistuksen
