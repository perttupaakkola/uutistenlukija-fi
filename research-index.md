# Uutistenlukija.fi — Research Library Index

**Last updated:** 2026-03-23
**Compiled by:** Monica 🔍
**Total:** 39 deliverables across 32 files (~255KB+)

This document is the master table of contents for the uutistenlukija.fi research library. All files are in `projects/uutistenlukija/` in the shared workspace.

---

## Quick navigation

| # | Deliverable | File | Key takeaway |
|---|---|---|---|
| 1 | Firehose taxonomy validation | (in-session, not saved to file) | Real Finnish news sites return no page_categories — Firehose is a discovery transport, not a taxonomy source |
| 2 | Competitive analysis | competitor-analysis-2026-03.md | Ampparit (250+ sources, ad-monetized), Google News (story-clustering), Suomen Uutiset (partisan, not a real competitor) |
| 3 | 8-category taxonomy | uutistenlukija-taxonomy-proposal.md | Kotimaa / Ulkomaat / Talous / Politiikka / Teknologia & Tiede / Urheilu / Kulttuuri & Viihde / Terveys & Hyvinvointi |
| 4 | Source allowlist | (in-session, not saved to file) | Tier 1: tekniikkatalous, ars technica, sciencenews, pelaaja; Tier 2: muropaketti, duodecim; Tier 3: avoid tiede.fi/tivi.fi |
| 5 | Content gap analysis | (in-session, not saved to file) | Top gaps: explainers, topic hubs, consumer economy, local impact, liveblogs, health explainers, crime/justice |
| 6 | Content roadmap | (in-session, not saved to file) | 18-item roadmap; top priority items: allowlist expansion, category routing, explainer template, roundup template |
| 7 | Sprint backlog | (in-session, not saved to file) | Top 6: allowlist expansion, category routing, explainer template (Monica+Sara+Alex), roundup template, health lane, crime sub-lane |
| 8 | Finnish RSS feed directory | legal-brief-aggregation-2026-03.md (embedded) | Verified working: Yle, IS, IL, TS, Kauppalehti; Dead/blocked: tiede.fi, tivi.fi, Aamulehti; MTV Uutiset: no working feed |
| 9 | Legal/copyright brief | legal-brief-aggregation-2026-03.md | Art. 15 in force Finland since Apr 2023; Uutiskeräin shut Apr 2025; operate headline-only, max 120 chars preview; HS/IL/Kauppalehti HIGH risk |
| 10 | Kopiosto licensing brief | (in-session, not saved to file) | No public standard tariff; case-by-case, slow, expensive; strategy: build traction first, then negotiate |
| 11 | SEO keyword research | seo-keyword-research-2026-03.md | URL structure locked; Kotimaa/Talous/Urheilu strongest near-term; full keyword tables by category |
| 12 | Monetization research | monetization-research-2026-03.md | Finnish CPM €2.50-€2.90; realistic RPM €4-8 net; revenue target €234k-€330k/yr at 500k-1M monthly uniques |
| 13 | User personas | user-personas-2026-03.md | 5 personas; MVP priority: Direct Accessor (35-55), Young Social Native (18-24), Finnish Professional (25-40) |
| 14 | Audience growth playbook | audience-growth-playbook-2026-03.md | Traffic mix: Direct+Email 60%, X 15%, Facebook 12%; newsletter target 100-200 subs month 1, 1000+ by month 6 |
| 15 | Technical architecture | technical-architecture-research-2026-03.md | Newsletter: Substack→Ghost; Analytics: GA4+Clarity (€0 MVP); CDN: Cloudflare Polish+WebP (-1.7s LCP, 14 dev hours P0) |
| 16 | Content strategy | content-strategy-2026-03.md | 28-32 articles/week; Thursday peak; 4 newsletter segments; X 5-7 tweets/week; Reddit max 1-2 posts/week |
| 17 | Launch readiness checklist | launch-readiness-checklist.md | "Strategically launch-ready, not yet operationally"; 3-phase launch order; 8 readiness sections with go/no-go gates |
| 18 | Competitive pricing analysis | competitive-pricing-2026-03.md | HS Digi €12.42-14.90/kk (observed); future premium tier hypothesis €3.99-7.99/mo; direct-sold CPM target €8-12 |
| 19 | Regulatory landscape | regulatory-landscape-2026-03.md | No broadcast licence needed; DSA compliance required; cookie consent critical; ad labelling (Mainos/Sponsoroitu) mandatory |
| 20 | Partnerships & syndication | partnerships-syndication-2026-03.md | Day-one: Cloudflare + Google Publisher Center + Ampparit submission + AdSense; Adform is the Finnish ad tech endgame |
| 21 | Ampparit submission application | ampparit-application.md | Pre-filled form fields, RSS technical requirements, category mapping, submit after 2-4 weeks of publishing |
| 22 | Google Publisher Center guide | google-publisher-center-guide.md | Registration steps, logo requirements (Sara), news sitemap spec, JSON-LD NewsArticle, DNS verification, timeline expectations |
| 23 | Finnish legal pages (GDPR) | legal-pages-drafts.md | Tietosuojaseloste, evästekäytäntö, käyttöehdot — all in Finnish, GDPR-compliant, placeholders for legal name/date |
| 24 | About page (Tietoa meistä) | about-page-draft.md | Full Finnish about page with DSA transparency section, editorial line, source selection criteria |
| 25 | SEO implementation sheet | seo-implementation-sheet.md | Per-category keywords, title/meta templates, internal linking, JSON-LD schemas, technical SEO checklist |
| 26 | Source allowlist with RSS | source-allowlist-rss.md | Tier 1/2/3 sources with verified RSS URLs, legal risk ratings, polling schedule, dedup spec, category coverage analysis |
| 27 | Launch runbook | launch-runbook.md | T-7 checklist, launch day hour-by-hour, days 2-7 tasks, success metrics, 5 rollback scenarios, final gate checklist |
| 28 | April 2026 content calendar | content-calendar-april-2026.md | Week-by-week themes, X posting schedule, newsletter plan, key events (Pääsiäinen, Helmarit, Vappu), category balance targets |
| 29 | Source tier analysis | source-tier-analysis.md | Current source audit, gap analysis, 10 new source recommendations with RSS, quality gate filters, tier map with coverage projections |
| 30 | Launch announcement drafts | launch-announcement.md | 5 formats: Finnish blog/press release, X thread, Facebook, English PR, Product Hunt. Distribution checklist. "No AI-hype" messaging rule |
| 31 | Reader feedback survey | reader-survey.md | 9 questions (+ 5-question short version), Google Forms implementation, 3 incentive ideas, NPS analytics, GDPR notes |
| 32 | Competitive map | competitive-map.md | 7 aggregators mapped, 6 mainstream publishers, unique positioning, SWOT, positioning chart. Uutiskeräin.fi gap identified |
| 33 | Ad revenue model | ad-revenue-model.md | Traffic tier projections (1K-500K), break-even analysis, 3 scenarios (€900-€25K yr1), newsletter sponsorship tiers, MM-kisat golden window |
| 34 | Content quality audit | content-quality-audit.md | ⚠️ CRITICAL: Site has AI-generated full articles with fictional bylines, no source attribution. Grade C+. UX A- but legal compliance D |
| 35 | Attribution best practices | attribution-best-practices.md | Aggregator comparison, JSN guidelines, EU AI Act Art. 50 (Aug 2026), STT/Yle examples, P0 fix list for Alex |
| 36 | Launch readiness v2 | launch-readiness-v2.md | 32% ready (16/50), 5 blockers (B1-B5), 5 Perttu decisions, timeline: mid-April launch if decisions made now |
| 37 | Monetization timeline | monetization-timeline.md | Path to 1M€ (year 3 realistic), 3 yr1 scenarios (€5K-€120K), milestone unlocks, MM-kisat golden window, byline risk = zero revenue |
| 38 | Finnish media landscape | finnish-media-landscape.md | Top 5 media by traffic, 5 underserved categories, Alma conflict-free positioning, social media priorities, MM-kisat opportunity, launch messaging |
| 39 | SEO content gaps | seo-content-gaps.md | Free talous gap, AI/tech keyword growth, MM-kisat SEO window (deadline 25.4.), Ampparit UX displacement, Google News Showcase, content calendar priorities |
| 39 | SEO content gap analysis | seo-content-gaps.md | High-volume Finnish query gaps, Google News traffic by category, long-tail opportunities, content types ranking in FI, 2026 content calendar priorities, 3 exploitable gaps |

---

## Full file inventory

### Files saved to shared workspace

| File | Size | Deliverables | Status |
|---|---|---|---|
| competitor-analysis-2026-03.md | ~8KB | #2 | ✅ Complete |
| uutistenlukija-taxonomy-proposal.md | ~6KB | #3 | ✅ Complete |
| legal-brief-aggregation-2026-03.md | ~12KB | #8, #9 | ✅ Complete |
| seo-keyword-research-2026-03.md | ~12KB | #11 | ✅ Complete |
| monetization-research-2026-03.md | ~10KB | #12 | ✅ Complete |
| user-personas-2026-03.md | ~9KB | #13 | ✅ Complete |
| audience-growth-playbook-2026-03.md | ~19KB | #14 | ✅ Complete |
| technical-architecture-research-2026-03.md | ~15KB | #15 | ✅ Complete |
| content-strategy-2026-03.md | ~16KB | #16 | ✅ Complete |
| launch-readiness-checklist.md | ~14KB | #17 | ✅ Complete |
| competitive-pricing-2026-03.md | ~14KB | #18 | ✅ Complete |
| regulatory-landscape-2026-03.md | ~17KB | #19 | ✅ Complete |
| partnerships-syndication-2026-03.md | ~21KB | #20 | ✅ Complete |
| research-index.md | ~5KB | Index | ✅ This file |
| ampparit-application.md | ~4KB | #21 | ✅ Complete |
| google-publisher-center-guide.md | ~7KB | #22 | ✅ Complete |
| legal-pages-drafts.md | ~9KB | #23 | ✅ Complete |
| about-page-draft.md | ~6KB | #24 | ✅ Complete |
| seo-implementation-sheet.md | ~4KB | #25 | ✅ Complete |
| source-allowlist-rss.md | ~3KB | #26 | ✅ Complete |
| launch-runbook.md | ~4KB | #27 | ✅ Complete |
| content-calendar-april-2026.md | ~3KB | #28 | ✅ Complete |
| source-tier-analysis.md | ~4KB | #29 | ✅ Complete |
| launch-announcement.md | ~2KB | #30 | ✅ Complete |
| reader-survey.md | ~2KB | #31 | ✅ Complete |
| competitive-map.md | ~4KB | #32 | ✅ Complete |
| ad-revenue-model.md | ~3KB | #33 | ✅ Complete |
| content-quality-audit.md | ~3KB | #34 | ✅ Complete |
| attribution-best-practices.md | ~4KB | #35 | ✅ Complete |
| launch-readiness-v2.md | ~2KB | #36 | ✅ Complete |
| monetization-timeline.md | ~2KB | #37 | ✅ Complete |
| finnish-media-landscape.md | ~2KB | #38 | ✅ Complete |
| seo-content-gaps.md | ~2KB | #39 | ✅ Complete |
| seo-content-gaps.md | ~5KB | #39 | ✅ Complete |

### Deliverables without standalone files

Deliverables #1, #4, #5, #6, #7, #10 were produced in-session and reported via Discord. Key findings are summarized in the index table above and incorporated into subsequent documents. If standalone files are needed, Monica can reconstruct from session context.

---

## Key decisions / strategic anchors (cross-cutting)

### Product

- **8-category taxonomy** is the right structure at launch
- **Headline-only aggregation with max 120 chars preview** is the safe legal posture
- **Domain-first source allowlist** with quality-trusted publishers; category assignment done downstream by classifier

### Audience

- Primary launch personas: **Direct Accessor**, **Young Social Native**, **Finnish Professional**
- Newsletter is the highest-value owned channel — target 1,000+ subscribers by month 6

### Monetization

- **Phase 1:** programmatic display (~€3.5 CPM)
- **Phase 2:** direct-sold display (€8-12 CPM) + newsletter sponsorships (€150-400/issue)
- **Phase 3:** native content + premium tier at **€3.99-7.99/mo**

### Legal

- Article 15 = biggest ongoing risk; HS/IL/Kauppalehti = HIGH risk
- No special Traficom licence needed; DSA compliance and cookie consent are the real obligations

### Tech

- Cloudflare → Hugo → GA4+Clarity → Substack→Ghost
- MVP tech cost: ~€0-20/mo

### Launch readiness verdict

_"Strategically launch-ready, not yet operationally launch-ready."_

### Partnerships

- Ampparit submission + Google Publisher Center = day-one priority
- Adform = Finnish ad tech endgame (6+ months)
- Direct publisher outreach at 3-6 months with referral data

---

## Research sprint timeline

| Date | Work |
|---|---|
| 2026-03-17 | Meta description template; SEO action plan; channel mapping error fixed |
| 2026-03-17–18 | RSS feed directory; Finnish + international source research |
| 2026-03-18–19 | Firehose integration research; taxonomy validation |
| 2026-03-19–20 | Firehose strategy finalized; competitive analysis; category taxonomy |
| 2026-03-20–21 | Source allowlist; content gap analysis; 18-item roadmap |
| 2026-03-21 | RSS feed directory finalized; legal/copyright brief; Kopiosto research |
| 2026-03-22 (AM) | SEO keyword research |
| 2026-03-22 (PM) | Monetization research; user personas; audience growth playbook |
| 2026-03-22 (evening) | Technical architecture (3 parts); content strategy; launch readiness checklist |
| 2026-03-22 (late) | Competitive pricing; regulatory landscape; partnerships & syndication; this index |

---

## Suggested next research priorities

If further research is needed, highest-value topics not yet covered:

1. **Finnish social media landscape deep-dive** — X/Twitter, Reddit r/suomi, Facebook group dynamics for Finnish news sharing
2. **Search intent mapping** — keyword-to-article-type mapping per category, informed by Search Console data post-launch
3. **Publisher outreach prep** — draft outreach templates and value proposition for regional publisher conversations (3-6 month horizon)
4. **Competitor feature gap analysis** — deeper UX/feature comparison vs Ampparit and Google News Finland
5. **Finnish affiliate market deep-dive** — specific programs via Tradedoubler/Adtraction for Terveys/Talous/Teknologia categories

---

_Research library compiled by Monica 🔍 — March 2026_
