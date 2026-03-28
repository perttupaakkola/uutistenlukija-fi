# Uutistenlukija.fi — Source Allowlist & RSS Feeds

**Viimeksi päivitetty:** 2026-03-22
**Deliverable:** #26

---

## TIER 1: LAUNCH DAY

| Source | Status | Legal | Primary categories |
|---|---|---|---|
| Yle (9 category feeds) | ✅ VERIFIED | 🟢 LOW | Kaikki kategoriat |
| Kauppalehti (main + 4 topic feeds) | ✅ VERIFIED | 🔴 HIGH | Talous |
| Ilta-Sanomat (10 section feeds) | ✅ VERIFIED | 🟡 MEDIUM | Kotimaa, Ulkomaat, Talous, Urheilu, Teknologia |
| Iltalehti (8 section feeds) | ✅ VERIFIED | 🔴 HIGH ⚠️ | Kotimaa, Ulkomaat, Urheilu — PERTTU GO/NO-GO NEEDED |
| Turun Sanomat | ✅ VERIFIED | 🟡 MEDIUM | Kotimaa |
| MTV Uutiset | ❌ NO RSS | — | → Firehose only |
| Verkkouutiset | ⚠️ RESEARCHED | 🟢 LOW | Politiikka, Kotimaa |
| Tekniikka & Talous | ⚠️ RESEARCHED | 🟡 MEDIUM | Teknologia, Talous |
| Pelaaja.fi | ⚠️ RESEARCHED | 🟢 LOW | Kulttuuri & Viihde |
| Ars Technica (5 feeds) | ✅ VERIFIED | 🟢 LOW | Teknologia & Tiede |
| ScienceNews | ✅ VERIFIED | 🟢 LOW | Teknologia & Tiede |

---

## TIER 2: WEEK 2-4

HS (HIGH risk — skip until legal review), Muropaketti, Suomen Kuvalehti, Uusi Suomi, Duodecim, BBC (7 feeds), The Verge (4 feeds), New Scientist, Variety

---

## TIER 3: MONTH 2+

Talouselämä, Yle Areena cultural, academic sources

---

## EXCLUDED

tiede.fi (redirect), tivi.fi (blocked), kaleva.fi (dead), aamulehti.fi (blocked), HBL (Swedish)

---

## CATEGORY COVERAGE AT TIER 1

| Category | Daily volume est. | Status |
|---|---|---|
| Kotimaa | 40-80/day | ✅ Good |
| Ulkomaat | 30-60/day | ✅ Good |
| Talous | 25-50/day | ✅ Good |
| Politiikka | 20-40/day | ✅ Good |
| Teknologia & Tiede | 25-50/day | ✅ Good |
| Urheilu | 30-70/day | ✅ Good |
| Kulttuuri & Viihde | 15-30/day | ✅ OK |
| Terveys & Hyvinvointi | 5-15/day | ⚠️ THIN |

**Terveys & Hyvinvointi needs Tier 2 sources** (Duodecim, BBC Health, New Scientist) to feel populated at launch — worth fast-tracking these.

---

## TECHNICAL SPEC (for Alex)

**Polling schedule:** Yle 5min → IS/IL/Kauppalehti 10min → others 15min

**Deduplication:** sha256 URL hash + headline similarity (Levenshtein <10%)

**Source priority order** (dedup winner): Yle > IS/IL > Regional > Specialty > International

**Per-item extraction:**

- `<title>`, `<link>`, `<pubDate>` — required
- `<description>` — optional, used as research input for article writing
- No images from RSS (use licensed stock or original)

**Content policy:** RSS feeds are used as research sources — our pipeline reads multiple feeds on a topic and writes an original article. No verbatim copying.

**Feed validation before adding:** W3C validator + HTTP 200 + guid stability check

25-row testing checklist included for all Tier 1 feeds.

---

## ⚠️ PERTTU DECISIONS NEEDED

**Iltalehti:** Terms prohibit commercial use. Recommendation: **skip at launch, add week 2-4 after legal review**.

**Helsingin Sanomat:** Highest legal risk. Recommendation: **skip entirely at launch, revisit month 3-6**.

---

## KEY FLAGS

- **Terveys & Hyvinvointi on ohut** Tier 1-lähteillä — kannattaa fast-trackia Duodecim + BBC Health Tier 2:sta
- **MTV Uutiset ei tarjoa RSS:ää** — Firehose-säännöt ainoana vaihtoehtona
- **IL ja HS vaativat Pertulta go/no-go** ennen launch-päätöstä
- **Yle on selkeästi paras lähde** — 9 kategoriasyötettä, matala juridiikka, korkein luotettavuus
