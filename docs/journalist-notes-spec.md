# Journalist Notes & Analysis Content Spec

**Deliverable #40** | Created: 2026-03-23 | Author: Monica 🔍

---

## Part 1: Toimittajan Huomio — Formaatti

```
---
📝 **Toimittajan huomio**
[40–100 sanaa kontekstia. Ei mielipide. Aina faktuaalinen.]
```

**Milloin käytetään (~20–30% artikkeleista):**

- Kansainvälinen uutinen, jolla on suomalainen kulma
- Data/tilasto joka kaipaa suomalaista kontekstia
- Breaking news jossa faktat vielä kehittyvät
- Osa pidempää sarjaa johon viittaaminen lisää arvoa

**3 esimerkkinotia:**
1. EKP-koronnosto (suomalainen kotitalousvaikutus)
2. Kahvitutkimus (metodologiahuomio)
3. Breaking news (kehittyvä tilanne)

---

## Part 2: Analyysiartikkeli — Uusi Sisältötyyppi

|           | Uutinen                 | Analyysi                |
| --------- | ----------------------- | ----------------------- |
| Pituus    | 200–400 sanaa           | 600–1 200 sanaa         |
| Lähteet   | 1–2                     | 4–8+                    |
| Aikajänne | Minuutit                | 4–24h                   |
| Byline    | Uutistenlukija Toimitus | Uutistenlukija Analyysi |

**Ensimmäiset 3 analyysiä suosituksena:**

1. _EKP:n koronnostot suomalaisten arjessa_ — Talous
2. _MM-kisat 2026: Suomi ennen turnausta_ — Urheilu (evergreen)
3. _Tekoäly suomalaisessa mediassa_ — rakentaa brändiluottamusta

---

## Päivitetty Framing (aggregaattori → sanomalehti)

| Vanha                               | Uusi                                                        |
| ----------------------------------- | ----------------------------------------------------------- |
| "Automaattinen kooste"              | "Uutistenlukija Toimitus"                                   |
| "Lähde: yle.fi" (ainoa attribuutio) | "Perustuu lähteeseen: Yle Uutiset"                          |
| AI-ilmoitus = varoituslabeli        | "Laadittu tekoälyavusteisesti ja tarkistettu toimituksessa" |

| EU AI Act = eksistentiaalinen uhka  | Toimituksellinen läpinäkyvyys = brändietu                   |

---

## Part 3: Alex Implementation Spec

Uusi `journalist_note` -kenttä artikkelischemaan + `content_type: news|analysis|breaking` + desk-byline-järjestelmä.

**Schema additions:**
- `journalist_note` — optional text field (40-100 words)
- `content_type` — enum: `news`, `analysis`, `breaking`
- `editorial_reviewed` — boolean flag

**3 Hugo templates needed:**
1. Journalist note partial (renders the note box)
2. Analysis article layout (longer form, different styling)
3. Byline component (renders desk byline based on content_type)

---

## Aggregaattori → Sanomalehti Document Updates

10 documents updated:

| Dokumentti                          | Muutos                                                                     |
| ----------------------------------- | -------------------------------------------------------------------------- |
| launch-announcement.md              | "News aggregator" → "AI-assisted newspaper"; taglines ja PR-teksti uusittu |
| content-quality-audit.md            | Aggregaattorihypoteesi korjattu, newspaper-malli dokumentoitu              |
| seo-content-gaps.md                 | Aggregator-angle → newspaper identity angle                                |
| seo-implementation-sheet.md         | "Aggregators can rank" → "independent publications can rank"               |
| partnerships-syndication-2026-03.md | 4 kohtaa: Uutistenlukija kuvataan nyt sanomalehtena                        |
| regulatory-landscape-2026-03.md     | Purpose + 2 summary-kohtaa päivitetty                                      |
| competitive-map.md                  | Positioning tagline suomennettu + päivitetty                               |
| finnish-media-landscape.md          | HS-gap kuvaus + Instagram-huomio korjattu                                  |
| launch-readiness.md                 | Model update -huomio lisätty otsikkoon                                     |
| attribution-best-practices.md       | Model update -huomio lisätty (jo tehty aiemmin)                            |

**Ampparit-hakemus ja ad-revenue-model jätettiin ennalleen** — siellä "aggregator" viittaa kilpailijoihin tai teknisiin benchmarkeihin, ei Uutistenlukijaan.
