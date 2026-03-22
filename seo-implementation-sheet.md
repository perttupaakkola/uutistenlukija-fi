# Uutistenlukija.fi — SEO Implementation Sheet

**Viimeksi päivitetty:** 2026-03-22
**Deliverable:** #25

---

## PART 1: PER-CATEGORY KEYWORDS

| Category | URL | Primary | Top long-tails | Priority |
|---|---|---|---|---|
| Kotimaa | /kotimaa/ | suomalaiset uutiset | kotimaan uutiset tänään, suomen päivän uutiset | ⭐⭐⭐ |
| Ulkomaat | /ulkomaat/ | ulkomaan uutiset | maailman uutiset tänään suomeksi | ⭐⭐⭐ |
| Talous | /talous/ | talousuutiset | talousuutiset tänään, yritysuutiset suomi | ⭐⭐⭐ |
| Politiikka | /politiikka/ | politiikan uutiset | eduskunnan uutiset tänään | ⭐⭐ |
| Teknologia & Tiede | /teknologia-tiede/ | teknologia uutiset | tekoäly uutiset suomi | ⭐⭐⭐ |
| Urheilu | /urheilu/ | urheiluuutiset | jääkiekko uutiset tänään, liiga uutiset | ⭐⭐⭐ |
| Kulttuuri & Viihde | /kulttuuri-viihde/ | kulttuuriuutiset | peliuutiset suomeksi | ⭐⭐ |
| Terveys & Hyvinvointi | /terveys-hyvinvointi/ | terveysuutiset | lääketieteen uutiset suomeksi | ⭐⭐ |

---

## PART 2: TITLE + META TEMPLATES

### Homepage:

- **Title:** `Uutistenlukija — Suomen parhaat uutiset yhdessä paikassa`
- **Meta:** `Uutistenlukija kokoaa luotettavien suomalaisten medioiden uutisotsikot yhteen paikkaan. Kotimaa, talous, urheilu, politiikka ja paljon muuta — kaikki tuoreimmat uutiset yhdellä silmäyksellä.`

### Category pages:

- **Title:** `[Kategoria] | Uutiset tänään — Uutistenlukija`
- **Meta:** Per-category Finnish descriptions (customized per category)

### Article pages:

- **Title:** `[Artikkelin otsikko] — [Lähde] | Uutistenlukija` (truncate at 60 chars total)

---

## PART 3: INTERNAL LINKING

- Every page → 3 cross-category links
- Breadcrumbs on all category + article pages
- Footer: all 8 categories as text links
- **Cross-linking map:** Kotimaa↔Politiikka↔Talous core cluster; Teknologia↔Talous; Urheilu↔Kulttuuri

---

## PART 4: STRUCTURED DATA (all JSON-LD)

| Page | Schema | Priority |
|---|---|---|
| Homepage | WebSite + Organization | P0 |
| Category pages | CollectionPage + BreadcrumbList | P0 |
| Article pages | NewsArticle + BreadcrumbList | P0 |
| Static pages | WebPage | P1-P2 |

**Key aggregator note:** In `NewsArticle`, set `url` to the original source URL — not the uutistenlukija URL. Signals aggregation, not authorship.

---

## PART 5: TECHNICAL SEO

**robots.txt:** Allow all + explicit `Allow: /` for Googlebot-News. Block only `/admin/`, `/api/`.

**Sitemap structure:**

- `sitemap.xml` (index → links to 3 child sitemaps)
- `sitemap-pages.xml` (homepage + categories at priority 0.9, static at 0.5)
- `sitemap-articles.xml` (last 30 days, priority 0.7)
- `news-sitemap.xml` (last 2 days only, Google News format)

**Every page `<head>` must have:**

- `<title>`, `<meta description>`, `<link rel="canonical">`
- Open Graph: `og:title`, `og:description`, `og:url`, `og:image`, `og:locale`, `og:site_name`
- Twitter: `twitter:card`, `twitter:site` (`@Uutistenlukija_`), `twitter:title`, `twitter:description`
- JSON-LD structured data

**Default OG image needed:** 1200×630px — action for Sara.

---

## PART 6: LAUNCH CHECKLIST

### Before launch (Alex):

- [ ] All title tags + meta desc implemented
- [ ] Canonical tags on every page
- [ ] JSON-LD on all page types
- [ ] robots.txt + all 4 sitemaps live
- [ ] OG + Twitter Card tags on all pages
- [ ] Default OG image deployed

### Day 1:

- [ ] Submit sitemap.xml + news-sitemap.xml to Search Console
- [ ] Rich Results Test on homepage + category + article page
- [ ] Mobile-Friendly Test

---

## KEY FLAGS

- **Sara needs:** default OG image 1200×630px — same session as the logos
- **Alex critical:** `NewsArticle` schema `url` = original source URL, not uutistenlukija URL — easy to get wrong
- **Tekoäly** is the single fastest-growing subcategory keyword — worth flagging for future sub-path consideration
- **Urheilu + Kotimaa** strongest near-term SEO bets — highest volume, most habitual daily traffic
