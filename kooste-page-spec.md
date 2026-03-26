# /kooste/ — Implementation Spec for Alex

**Deliverable #48** | Monica | 2026-03-26
**SEO target:** "uutiskooste tänään", "päivittäinen uutiskooste", "suomen uutiset tiivistelmä"

## 1. URL & Meta

| Field            | Value                                                                                                          |
|------------------|----------------------------------------------------------------------------------------------------------------|
| URL              | uutistenlukija.fi/kooste/                                                                                      |
| Title tag        | Uutiskooste tänään – päivän tärkeimmät uutiset \| Uutistenlukija                                               |
| H1               | Uutiskooste – [päivämäärä] (dynaaminen Hugo date)                                                              |
| Meta description | Päivän tärkeimmät suomalaiset uutiset koottuna yhteen paikkaan. Uutiskooste päivittyy useita kertoja päivässä. |
| Canonical        | uutistenlukija.fi/kooste/                                                                                      |

## 2. Sisältö sivulla

### Blokki 1: Päivän otsikko
- `## Uutiskooste – {{ now | dateFormat "2.1.2006" }}`
- Subtext: "Päivitetty {{ now | dateFormat "15:04" }}"

### Blokki 2: Top 5–10 uutista tänään
- Artikkelit järjestetty: `where .Date "after" (now.AddDate 0 0 -1)` → `first 10`
- Jokaisesta: otsikko (linkki) + lähde + aikaleima
- EI kuvia — tekstilistamuoto, nopea skannaus

### Blokki 3: Kategorioittain
- Kotimaa: 3 uusinta
- Talous: 3 uusinta
- Ulkomaat: 3 uusinta
- Teknologia: 2 uusinta (jos saatavilla)

### Blokki 4: Newsletter CTA
- "Tilaa päivittäinen kooste sähköpostiin" + Ghost signup form

## 3. Hugo-implementaatio

### Vaihtoehto A (suositus): Section page
- Luo `content/kooste/_index.md` frontmatterilla: `title: "Uutiskooste"`, `layout: "kooste"`
- Luo `layouts/kooste/list.html` — queries `.Site.RegularPages` by date
- Hugo generoi staattiset versiot — ei pipeline-muutoksia tarvita

### Vaihtoehto B: Pipeline-generoitu data
- Pipeline kirjoittaa `data/kooste.json` päivittäin (top 10 artikkelia)
- Hugo lukee `{{ range .Site.Data.kooste.articles }}`
- Enemmän työtä, mutta tarkempi kontrolli järjestykseen
- ❓ Tarvitaan vain jos A ei riitä

**Suositus:** Aloita A:lla — nopein shipata, testaa SEO-hyöty ensin.

## 4. Freshness-signaali (SEO-kriittinen)

Hugo-config tai sitemap-prioriteetti: `/kooste/` saa `changefreq: hourly`, `priority: 0.9`
→ Googlebot indeksoi useammin → freshness-bonus hakutuloksissa

## 5. Alex-työmääräarvio

| Tehtävä                                | ~Aika  |
|----------------------------------------|--------|
| _index.md + frontmatter                | 5 min  |
| layouts/kooste/list.html               | 1–2h   |
| CSS (sama kuin quick-briefing -blokki) | 30 min |
| Sitemap-config                         | 15 min |
| **Yhteensä**                           | **~2–3h** |

**Sara-riippuvuus:** ei. Alex voi aloittaa heti.
