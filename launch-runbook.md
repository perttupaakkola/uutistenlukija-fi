# Uutistenlukija.fi — Launch Runbook

**Viimeksi päivitetty:** 2026-03-22
**Deliverable:** #27

---

## T-7 DAYS CHECKLIST

### P0 blockers (ei launchata ennen kuin kaikki kunnossa):

🔧 **Alex:**
- Site live HTTPS + kaikki 8 kategoriaa
- 25 Tier 1 feedin tarkistus
- Ingestion pipeline
- news-sitemap auto-update
- GA4/Clarity ei lataudu ennen suostumusta
- Cookie banner
- title/meta/canonical/JSON-LD/OG kaikilla sivuilla
- Core Web Vitals LCP < 4.0s

🎨 **Sara:**
- Logo 1024×1024
- Wordmark 250×40
- OG image 1200×630

📋 **Perttu:**
- Search Console verified
- Publisher Center configured
- GA4 property
- Clarity project
- Legal pages julkaistu [nimi/pvm täytetty]
- IL/HS go/no-go päätös

### P1 (tärkeä mutta ei blokkaa):

Publisher Center logos/sitemap/kategoriat, breadcrumb data, feed monitoring, sosiaalinen media valmis

---

## LAUNCH DAY HOUR-BY-HOUR

**T+0 (Alex):** Deploy → Cloudflare → tarkista 15-kohdan tekninen checklist → Go/No-Go gate

**T+1h (Perttu):** Search Console → submit sitemap.xml + news-sitemap.xml + request indexing kotimaa/urheilu/talous

**T+2h (Perttu):** Vahvista Publisher Center aktiivisena

**T+3h (Perttu):** X/Twitter launch posts × 2 (copy-paste-valmis teksti runbookissa)

**T+4h (Monica):** Laatu-audit — 10 artikkelia kaikista kategorioista

**T+6h (Perttu):** GA4 Realtime — näkyykö sessioita?

**T+24h:** Yhteisreview — artikkelit ingested, feed-virheet, Search Console, sähköposti

---

## DAYS 2-7 DAILY TASKS

| Päivä | Kuka | Tehtävä |
|---|---|---|
| Joka aamu | Perttu 10 min | GA4 + sähköposti + Twitter-mainitsemiset |
| Joka aamu | Alex 10 min | Feed logs + sitemap + Cloudflare virheet |
| Päivä 2-3 | Monica | 20 artikkelin laatu-audit, Terveys-kategorian tila |
| Päivä 3-4 | Alex | Tier 2 -lähteet (BBC 7 syötettä, Verge, New Scientist, Duodecim, Variety) |
| Päivä 4-5 | Perttu | Search Console → onko sivuja indeksoitu? |
| Päivä 5-7 | Perttu | Viikon analytics-review |
| Päivä 7 | Perttu | Ampparit-hakemus — tarkista onko valmis (submit päivänä 14) |

---

## SUCCESS METRICS

**Viikko 1:** 500+ artikkelia, kaikki 8 kategoriaa aktiivisia, 0 legal complaintia, >20 sivua indeksoitu

**Viikko 2-4:** 200+ sessioita/viikko, >100 organic impressiota, Ampparit submitted

**Kuukausi 1:** 500+ organic sessioita, Google News -näkyvyys >0, 5+ Tier 2 -lähteen lisäys

### Hälytysrajat (reagoi heti):

- Feed 0 artikkelia >2h → Alex debuggaa
- Publisher lähettää valituksen → Perttu poistaa lähteen välittömästi + vastaustemplate mukana
- Site downtime → Alex rollback Cloudflare Pages edelliseen deployiin
- 0 GA4 sessioita 24h jälkeen → consent-konfiguraatio rikki

---

## ROLLBACK PLAN (5 skenaariota)

1. **Tekninen failure** → Cloudflare Pages instant rollback + Twitter-viesti + fix staging:ssa
2. **Legal complaint** → 24h vastaus, poista lähde välittömästi, vastaustemplate mukana
3. **Feed ingestion failure** → URL check → User-Agent check → Tier 2 tilalle
4. **Google ei indeksoi 14 pv jälkeen** → robots.txt → canonical → noindex → Cloudflare Googlebot-esto
5. **Kategoria tyhjä** → feed check → classifier check → manuaalinen täyttö

---

## FINAL LAUNCH GATE

```
P0 checklist complete:                       YES / NO
Legal pages live:                            YES / NO
Feed ingestion tested (24h stable):          YES / NO
Analytics configured (consent-safe):         YES / NO
Search Console verified:                     YES / NO
IL/HS decisions made:                        YES / NO
Perttu reviewed legal pages:                 YES / NO
Sara logos delivered:                         YES / NO

ALL YES → CLEAR TO LAUNCH ✅
ANY NO  → FIX FIRST ❌
```

---

## KEY NOTES

- **Consent-safe analytics on the final gate** — tämä on helpoin asia unohtaa ja suurin GDPR-riski
- **Publisher complaint template** on mukana suomeksi — Perttu voi käyttää sellaisenaan
- **Ampparit submission day 14** — ei aiemmin, Ampparit haluaa nähdä sisältöä ensin
- **Terveys & Hyvinvointi on ohuinta** — Monica tekee laatu-auditin päivänä 2-3 ja raportoi
