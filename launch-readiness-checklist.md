# Uutistenlukija.fi — Launch Readiness Checklist

**Last updated:** 2026-03-22
**Purpose:** Practical pre-launch checklist covering technical, content, legal, SEO, and distribution readiness.

---

## Executive Summary

Uutistenlukija.fi has a strong research foundation and a clear launch direction. The biggest remaining work is no longer strategy — it is execution and verification.

### High-level status
- **Research / planning:** Strongly complete ✅
- **Taxonomy / SEO direction:** Complete ✅
- **Legal risk awareness:** Complete, but operating policy still needs implementation ⚠️
- **Content/distribution setup:** Partly complete ⚠️
- **Technical launch verification:** Needs checklist-based completion ⚠️

### Recommended launch rule
Launch as a **headline-first, fast, clean aggregator** with:
- clear category pages
- strong attribution
- conservative snippet policy
- analytics from day one
- newsletter capture from day one

---

# 1) TECHNICAL READINESS

## Domain / Hosting / Security
- [ ] Production domain resolves correctly (`uutistenlukija.fi` + `www` policy decided)
- [ ] SSL certificate valid on all public routes
- [ ] HTTP → HTTPS redirect enabled
- [ ] Canonical host enforced (choose `uutistenlukija.fi` or `www.uutistenlukija.fi`)
- [ ] 404 page exists and matches brand
- [ ] 500 / fallback error handling exists
- [ ] Cloudflare active and correctly proxied
- [ ] Basic uptime monitoring configured
- [ ] Backup / rollback path defined for launch day

### Status
- **Partly done:** Cloudflare already on domain
- **Still needed:** explicit pre-launch verification of SSL, redirects, canonical host, and monitoring

## Indexation / Discovery Infrastructure
- [ ] XML sitemap generated and publicly accessible
- [ ] News sitemap generated if Google News submission planned
- [ ] `robots.txt` exists and is correct
- [ ] `robots.txt` allows category pages and article pages
- [ ] Search, admin, or duplicate pages blocked if present
- [ ] Feed/RSS endpoint works if used for external distribution

### Status
- **Still needed:** live verification of sitemap, news sitemap, robots.txt, feed endpoint

## Analytics / Measurement
- [ ] GA4 installed on all pages
- [ ] Pageview tracking verified in production
- [ ] Newsletter signup event configured
- [ ] Outbound click tracking configured (important for aggregator behavior)
- [ ] UTM conventions defined for social / newsletter / distribution
- [ ] Search Console property connected
- [ ] Clarity or equivalent heatmap/session tool installed
- [ ] Conversion dashboard created (signup, clickthrough, returning user)

### Status
- **Partly done:** GA4 API connected; Search Console API connected
- **Still needed:** production event tracking, outbound click events, Clarity install, dashboard setup

## Performance / Delivery
- [ ] Mobile PageSpeed check run on homepage
- [ ] Mobile PageSpeed check run on category page
- [ ] Mobile PageSpeed check run on article page
- [ ] Cloudflare caching rules configured
- [ ] Image optimization enabled (WebP / compression / responsive sizes)
- [ ] Lazy-loading for below-the-fold images enabled
- [ ] CLS issues checked on mobile
- [ ] Core Web Vitals measured before launch

### Target thresholds
- [ ] LCP under 2.5s on mobile
- [ ] CLS under 0.1
- [ ] INP/FID in "good" range

### Status
- **Direction complete:** optimization strategy defined
- **Still needed:** implementation + real performance verification

---

# 2) CONTENT READINESS

## Minimum launch coverage by category
Recommended minimum visible inventory at launch:
- [ ] **Kotimaa:** 20+ quality items available
- [ ] **Ulkomaat:** 15+ quality items available
- [ ] **Talous:** 15+ quality items available
- [ ] **Politiikka:** 10+ quality items available
- [ ] **Teknologia & Tiede:** 10+ quality items available
- [ ] **Urheilu:** 15+ quality items available
- [ ] **Kulttuuri & Viihde:** 10+ quality items available
- [ ] **Terveys & Hyvinvointi:** 8+ quality items available

## Minimum category quality threshold
Each category page should have:
- [ ] clear H1
- [ ] intro copy / category description
- [ ] recent content freshness
- [ ] at least one "strong" lead story
- [ ] at least one related topic/tag path
- [ ] no obviously broken or miscategorized items
- [ ] no visibly low-trust spam/affiliate sources

## Homepage minimum standard
- [ ] homepage shows all 8 launch categories
- [ ] homepage lead area feels current and credible
- [ ] homepage not dominated by one category only
- [ ] visible freshness cues (time, source, date)
- [ ] clear differentiation from Ampparit-style clutter
- [ ] newsletter CTA visible without excessive scrolling

## Article / card quality threshold
Every content card should include:
- [ ] source/publisher name
- [ ] linked headline
- [ ] timestamp
- [ ] category label
- [ ] topic tag(s) if available
- [ ] thumbnail only if rights/usage policy allows
- [ ] snippet policy applied consistently

## Snippet policy readiness
- [ ] launch policy decided: no snippet / minimal preview / generated context
- [ ] per-domain overrides supported or documented
- [ ] no copied ledes from high-risk publishers beyond allowed policy

### Status
- **Research done:** content taxonomy, SEO targets, source allowlist, content strategy
- **Still needed:** final inventory check, category-page polish, launch-day quality QA

---

# 3) LEGAL READINESS

## Required legal pages / product policy
- [ ] Privacy Policy published
- [ ] Cookie Policy published
- [ ] Terms of Use / Terms of Service published
- [ ] Contact / publisher takedown contact published
- [ ] data processing / email consent language checked
- [ ] analytics/cookie banner compliant with actual tracking stack

## Copyright / publisher-right posture
- [ ] launch operating model explicitly set as **link + minimal preview aggregator**
- [ ] no assumption of broad snippet rights
- [ ] high-risk publisher handling documented
- [ ] per-source preview rules documented
- [ ] staff/agents know not to expand copied source text casually
- [ ] fallback "headline-only" mode possible if risk increases

## Kopiosto / licensing stance
- [ ] internal note documented: no public self-serve aggregator tariff found
- [ ] decision recorded: launch without richer preview licensing
- [ ] future licensing outreach deferred until traction exists
- [ ] richer previews treated as later rights-expansion project

## Publisher risk handling
Recommended risk stance from prior legal brief:
- [ ] HS handled cautiously / preferably headline-link only
- [ ] Iltalehti handled cautiously / preferably headline-link only
- [ ] IS handled with attribution rules respected
- [ ] Alma/Kauppalehti handled cautiously due to rights reservation / anti-mining note
- [ ] Yle treated as medium-risk / conservative usage
- [ ] unknown sources default to conservative preview mode

### Status
- **Research done:** copyright brief + Kopiosto licensing brief
- **Still needed:** publish legal pages, implement operational policy in product

---

# 4) SEO READINESS

## Core page SEO
- [ ] homepage title tag set
- [ ] homepage meta description set
- [ ] each category page has unique title tag
- [ ] each category page has unique meta description
- [ ] H1 matches target keyword intent
- [ ] canonical tags set correctly
- [ ] Open Graph tags present
- [ ] Twitter/X card tags present

## Category SEO implementation
Launch slug structure should be locked:
- [ ] `/kotimaa/`
- [ ] `/ulkomaat/`
- [ ] `/talous/`
- [ ] `/politiikka/`
- [ ] `/teknologia-tiede/`
- [ ] `/urheilu/`
- [ ] `/kulttuuri-viihde/`
- [ ] `/terveys-hyvinvointi/`

## Structured data
- [ ] Organization schema added
- [ ] WebSite schema added
- [ ] Breadcrumb schema added where relevant
- [ ] NewsArticle / Article schema added on article pages if applicable
- [ ] SearchAction schema only if site search is real and public

## Crawl / quality checks
- [ ] no duplicate category pages
- [ ] no empty category pages indexed
- [ ] no placeholder metadata in production
- [ ] no lorem ipsum or unfinished copy
- [ ] internal links between category pages and topic pages work

## Target SEO baseline at launch
- [ ] all category pages indexable
- [ ] all category pages keyword-aligned
- [ ] sitemap submitted to Search Console
- [ ] key pages inspected in Search Console

### Status
- **Research done:** SEO keyword research, URL structure recommendation
- **Still needed:** implement tags, schema, metadata, indexing verification

---

# 5) DISTRIBUTION READINESS

## External distribution setup
- [ ] Google Search Console connected and verified
- [ ] Google News inclusion workflow prepared
- [ ] news sitemap ready for submission
- [ ] Ampparit submission materials ready (RSS/feed + site info)
- [ ] Apple News evaluated (optional, lower priority)

## Social presence
- [ ] X/Twitter account active and branded
- [ ] profile bio explains value proposition clearly
- [ ] website link added to profile
- [ ] social posting rhythm defined for launch week
- [ ] at least 5 launch posts drafted in advance
- [ ] Open Graph images look good when shared

## Newsletter readiness
- [ ] newsletter platform chosen (Substack vs Ghost etc.)
- [ ] custom sender domain configured if needed
- [ ] signup form live on site
- [ ] double opt-in / consent wording checked
- [ ] first welcome email drafted
- [ ] first daily/weekly digest template drafted
- [ ] UTM strategy defined for newsletter links

## Distribution ops
- [ ] launch-day social checklist prepared
- [ ] launch-day newsletter send plan prepared
- [ ] first-week posting cadence set
- [ ] source feed health monitored daily during launch week
- [ ] verify feed/sitemap endpoints

### Status
- **Research done:** audience growth playbook, social strategy, newsletter strategy
- **Still needed:** actual platform setup + submissions + first assets

---

# 6) WHAT IS DONE VS. WHAT IS STILL NEEDED

## Already done ✅

### Research / strategy
- [x] Competitive analysis completed
- [x] Category taxonomy defined (8 launch categories)
- [x] Source allowlist researched
- [x] RSS source directory researched
- [x] SEO keyword research completed
- [x] Monetization research completed
- [x] User personas completed
- [x] Audience growth playbook completed
- [x] Technical architecture research completed
- [x] Content strategy completed
- [x] Legal/copyright brief completed
- [x] Kopiosto licensing research completed

### Product direction
- [x] Launch category structure defined
- [x] URL structure recommendation defined
- [x] classification stack direction defined
- [x] conservative legal posture recommended
- [x] newsletter / growth / distribution direction defined

## Still needed before launch ⚠️

### Technical implementation
- [ ] verify SSL/redirect/canonical host
- [ ] generate and test sitemap/news sitemap/robots.txt
- [ ] install and verify analytics events
- [ ] install Clarity or equivalent
- [ ] optimize images / caching / Core Web Vitals

### Product/content implementation
- [ ] ensure enough quality content exists in all 8 categories
- [ ] QA category routing accuracy
- [ ] polish homepage + category page copy
- [ ] verify timestamps, attribution, source labels
- [ ] lock snippet behavior

### Legal implementation
- [ ] publish Privacy Policy
- [ ] publish Cookie Policy
- [ ] publish Terms
- [ ] publish contact/takedown route
- [ ] enforce conservative source preview settings

### Distribution implementation
- [ ] launch newsletter stack
- [ ] prepare social profiles and first posts
- [ ] submit to Google News if eligible
- [ ] prepare Ampparit submission
- [ ] verify feed/sitemap endpoints

---

# 7) GO / NO-GO LAUNCH GATES

## Must-have before public launch
- [ ] site loads correctly on mobile
- [ ] SSL and redirects work
- [ ] analytics works
- [ ] privacy + cookie + terms pages live
- [ ] category pages populated and not embarrassing
- [ ] source attribution visible everywhere
- [ ] snippet policy conservative and consistent
- [ ] sitemap + robots.txt live
- [ ] newsletter signup works

## Strongly recommended before launch
- [ ] Clarity installed
- [ ] Google Search Console verified
- [ ] Open Graph cards tested
- [ ] first-week social content drafted
- [ ] first newsletter drafted
- [ ] performance score checked on at least 3 template types

## Can wait until shortly after launch
- [ ] Ampparit submission
- [ ] Google News approval
- [ ] richer segmentation for newsletter
- [ ] advanced schema enhancements
- [ ] premium/licensing expansion conversations

---

# 8) RECOMMENDED LAUNCH ORDER

## Phase 1 — Launch-blocker fixes
1. Technical verification
2. Legal pages live
3. Category/homepage QA
4. Analytics + newsletter form verification

## Phase 2 — Distribution readiness
5. Social accounts + assets ready
6. Search Console + sitemap submission
7. Newsletter first send ready
8. Ampparit / Google News submission package ready

## Phase 3 — Post-launch optimization
9. Core Web Vitals improvements
10. CTR improvements on category pages
11. Topic hubs and long-tail SEO expansion
12. Licensing / richer preview exploration only after traction

---

# Final Launch Assessment

## Current state
**Uutistenlukija is strategically launch-ready, but not yet operationally launch-ready.**

That means:
- the big research questions are answered ✅
- the major category / SEO / legal posture decisions are answered ✅
- the remaining work is execution, QA, and compliance implementation ⚠️

## Best next step
Use this checklist as the pre-launch board and mark each item owner-by-owner:
- **Alex:** technical + routing + performance + analytics implementation
- **Sara:** design polish + newsletter/social templates
- **Felix:** launch sequencing / distribution coordination
- **Monica:** QA support, policy summaries, and any follow-up research
