# Google Publisher Center — Registration Guide for uutistenlukija.fi

**Last updated:** 2026-03-22
**Purpose:** Step-by-step guide Perttu can follow to register with Google Publisher Center and set up news indexing.

---

## EXECUTIVE SUMMARY

Google News works on **two levels**:

1. **Automatic web crawl** — covers Top stories in Search, News tab, Google Discover. No registration required.
2. **Publisher Center registration** — editorial control, Google News Showcase eligibility, performance data.

**Key fact:** _"Publishers are automatically considered for 'Top stories'. They just need to produce high-quality content and comply with Google News content policies."_ Registration helps but does not guarantee inclusion.

---

## PART 1: PREREQUISITES

**Technical (Alex):**

- [ ] Site live at `https://uutistenlukija.fi`
- [ ] Search Console verified for the domain
- [ ] News sitemap live (see Part 4)
- [ ] Article pages have publication date + source attribution visible
- [ ] `robots.txt` does NOT block Googlebot or Googlebot-News
- [ ] Site is HTTPS

**Editorial (Perttu):**

- [ ] "About/Tietoa" page live
- [ ] Contact info visible
- [ ] Privacy Policy + Terms live
- [ ] Logo prepared (see Part 3 specs)

---

## PART 2: REGISTRATION STEPS

**URL:** https://publishercenter.google.com

**Publication details to enter:**

| Field | Value |
|---|---|
| Publication name | Uutistenlukija (no ".fi" — this is the editorial brand name Google shows) |
| Publication URL | https://uutistenlukija.fi |
| Country | Finland |
| Language | Finnish (fi) |
| Category | General news |

**Category sections to configure (maps to URL structure):**

| Section | URL |
|---|---|
| Kotimaa | https://uutistenlukija.fi/kotimaa/ |
| Ulkomaat | https://uutistenlukija.fi/ulkomaat/ |
| Talous | https://uutistenlukija.fi/talous/ |
| Politiikka | https://uutistenlukija.fi/politiikka/ |
| Teknologia & Tiede | https://uutistenlukija.fi/teknologia-tiede/ |
| Urheilu | https://uutistenlukija.fi/urheilu/ |
| Kulttuuri & Viihde | https://uutistenlukija.fi/kulttuuri-viihde/ |
| Terveys & Hyvinvointi | https://uutistenlukija.fi/terveys-hyvinvointi/ |

**Verification:** Publisher Center links to Search Console automatically if the same Google account owns both. If not, verify via DNS TXT record in Cloudflare DNS.

---

## PART 3: LOGO REQUIREMENTS

**For Sara — minimum required at launch:**

| Asset | Dimensions | Format | Notes |
|---|---|---|---|
| Square logo | 1024 × 1024 px | PNG | Brand mark on opaque background |
| Wordmark | 250 × 40 px | PNG | "Uutistenlukija" text on white |

- Name in logo must exactly match Publisher Center name: **Uutistenlukija**
- Legible at small sizes
- No transparency in main square logo

---

## PART 4: NEWS SITEMAP SETUP

### Rules (from official Google Search Central docs)

- Update with fresh articles as they publish — never recreate the file from scratch
- Only include articles from the **last 2 days**
- Remove older articles or strip `<news:news>` metadata once they age out
- Max 1,000 entries per file

### Sitemap URL

```
https://uutistenlukija.fi/news-sitemap.xml
```

### XML template

```xml
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
  <url>
    <loc>https://uutistenlukija.fi/kotimaa/2026/03/22/article-slug/</loc>
    <news:news>
      <news:publication>
        <news:name>Uutistenlukija</news:name>
        <news:language>fi</news:language>
      </news:publication>
      <news:publication_date>2026-03-22T18:00:00+02:00</news:publication_date>
      <news:title>Article headline goes here</news:title>
    </news:news>
  </url>
</urlset>
```

**Critical:** `<news:name>` must be exactly `Uutistenlukija` — matching Publisher Center precisely.
**Timezone:** Use `+02:00` (Helsinki EET) or `+03:00` (EEST summer).

### Alex implementation note

For Hugo: generate sitemap via custom template in `layouts/_default/news-sitemap.xml`. Use Hugo's `.PublishDate` or `.Date` — NOT sitemap generation time — for `<news:publication_date>`.

### Submission

1. Submit in Google Search Console → Sitemaps → `news-sitemap.xml`
2. Also enter the URL in Google Publisher Center sitemap settings

---

## PART 5: SEARCH CONSOLE INTEGRATION

**Key reports to watch after launch:**

| Report | Where | What it tells you |
|---|---|---|
| Google News performance | Search results → filter: Google News | Whether content appears in News surfaces |
| Index Coverage | Pages | Crawl errors on article pages |
| Sitemaps | Sitemaps section | News sitemap health |
| Core Web Vitals | Core Web Vitals | LCP/CLS against targets |

**Verification method for Hugo/Cloudflare:** Use DNS TXT record in Cloudflare — most reliable for static sites.

---

## PART 6: WHAT TO EXPECT

| Stage | Timeline |
|---|---|
| Publisher Center registration | Day 1 |
| Site crawl initiated | Days 1-7 |
| First content indexed in Google News | Days 3-14 |
| Top stories eligibility | Weeks 1-4+ (algorithmic, not guaranteed) |
| Stable Google News presence | Months 2-6 |
| Google News Showcase eligibility | 6+ months (invitation-based) |

**What helps:**

- Fresh, consistent daily publishing
- News sitemap updating in real-time
- JSON-LD `NewsArticle` structured data on article pages
- Fast pages (LCP < 2.5s)
- Transparent editorial identity

**Note:** Google News favours original reporting — which aligns perfectly with our model. As a verkkolehti producing original AI-written journalism from multiple sources, we are well-positioned for Google News inclusion.

---

## PART 7: GOOGLE NEWS SHOWCASE (FUTURE STEP)

- Requires a **direct partnership agreement** with Google — not self-serve
- Evaluate after 6+ months with established Google News presence
- Google pays a licensing fee to participating publishers
- Available in Finland

---

## PART 8: COMPLETE SETUP CHECKLIST

**Technical (Alex):**

- [ ] HTTPS, no mixed content
- [ ] `sitemap.xml` + `news-sitemap.xml` live
- [ ] News sitemap auto-updates on publish
- [ ] `<news:name>` = `Uutistenlukija` (exact)
- [ ] `robots.txt` allows Googlebot + Googlebot-News
- [ ] `<article>` + `<time>` markup on article pages
- [ ] JSON-LD `NewsArticle` structured data (recommended)
- [ ] Core Web Vitals targets met

**Perttu:**

- [ ] Google Account ready (use info@uutistenlukija.fi or dedicated Gmail)
- [ ] Search Console property verified
- [ ] Publisher Center account created
- [ ] Publication details entered (name, URL, country, language)
- [ ] 8 category sections configured
- [ ] Logos uploaded (square + wordmark)
- [ ] News sitemap URL submitted in Publisher Center

---

## KEY URLS

| Resource | URL |
|---|---|
| Publisher Center | https://publishercenter.google.com |
| Search Console | https://search.google.com/search-console/ |
| News sitemap docs | https://developers.google.com/search/docs/crawling-indexing/sitemaps/news-sitemap |
| Rich results test | https://search.google.com/test/rich-results |
