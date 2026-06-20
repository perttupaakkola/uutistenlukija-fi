# OPE-207 No-Public Distribution Angle Backlog

Generated: 2026-06-19 20:33 UTC  
Owner lane: Iris / growth, marketing, business-growth, social  
Scope: private planning only. No posting, scheduling, Buffer/X write call, email, campaign launch, spend, payment, or provider/account change.

## Evidence Used

- Linear OPE-207 had no owner artifact after creation at 2026-06-18 14:57 UTC and escalation at 2026-06-19 20:20 UTC.
- `python3 pipeline/health_check.py`: OK at 2026-06-19 20:26 UTC; latest article 138 minutes old outside daytime hours, no pipeline lock, disk OK, memory OK.
- `static/api/category-stats.json`: Talous 337 / 3250 articles = 10.4%, target 20%, under by 9.6 percentage points.
- `static/api/search-console-data.json`: 28-day GSC snapshot has working local/utility page signals, including `vappuopas/kaupat-auki/` 357 impressions, `paasiaisopas/kaupat-auki/` 320 impressions, and several local incident / local utility posts with top-10-ish positions.
- Fresh article signals inspected from `content/posts/`:
  - `2026-06-19-finanssialan-kokenut-asiantuntija-joutui-maksukorttihuijauks.md`
  - `2026-06-19-porssisahkon-hinta-vaihtelee-rajusti-halvimmat-vartit-loytyv.md`
  - `2026-06-19-polyesterin-kaytto-kasvaa-vaatteissa-eu-valmistelee-tekstiil.md`
  - `2026-06-19-helsingin-juhannus-houkuttelee-saunaan-torille-ja-linnanmael.md`
  - `2026-06-19-aikuisena-uimaan-oppiminen-on-vaikeaa-muistuttaa-mtvn-uutisp.md`

## Backlog

### 1. Kuluttajan turva: maksukorttihuijaus matkavarauksen jälkeen

Source/article signal:
- Talous article: `Finanssialan kokenut asiantuntija joutui maksukorttihuijauksen uhriksi`.
- Story has concrete consumer-risk elements: Booking.com-like WhatsApp message, card details, hundreds of euros hold, expert victim framing.
- Supports the current Talous under-target gap without needing a market-data hook.

Target audience/channel:
- Private draft for later LinkedIn / newsletter / Facebook group adaptation aimed at Finnish consumers, travel planners, and small-business owners who book travel.
- No public posting in this task; prepare an internal angle card only.

Angle:
- "Jos finanssialan asiantuntijakin voi mennä lankaan, matkavarausten maksulinkit tarvitsevat oman tarkistuslistan."
- Use as a trust/usefulness angle, not fearbait.

Risk note:
- Avoid implying Booking.com caused this specific fraud unless separately verified; article itself frames the data-leak connection as Kivisaari's assessment.
- Do not name or target any company in public copy beyond what the article already attributes.

Measurement idea:
- If approved later, use UTM `utm_campaign=consumer_safety_card_fraud`.
- Measure article page sessions, newsletter clicks if used, and whether Talous category click-through changes for safety/service angles.

Next private asset:
- One 5-bullet "maksulinkin tarkistuslista" draft, reviewed against the source article before any public use.

### 2. Arjen raha: pörssisähkön halvat vartit ja ajoituksen hyöty

Source/article signal:
- Article: `Pörssisähkön hinta vaihtelee rajusti: halvimmat vartit löytyvät iltapäivästä`.
- Concrete numbers: cheapest quarter starts 16:00 at 6.969 c/kWh; most expensive starts 7:15 at 22.336 c/kWh; 48-hour quarter-hour price tracking.
- Category is currently `Kotimaa`, but the user problem is household money/energy, suitable for a Talous-adjacent distribution angle.

Target audience/channel:
- Private draft for later homeowner / EV owner / household-budget channels.
- Candidate channels after approval: newsletter utility block, LinkedIn post, or local Facebook groups where energy-price timing is relevant.

Angle:
- "Pörssisähkön säästö ei ole enää vain yöajastusta: varttihinnat voivat tehdä iltapäivästä halvimman kohdan."

Risk note:
- Price figures are time-specific; any public copy must include date/time and avoid evergreen promises about the cheapest hour.
- If reused later, refresh the source or frame as an example, not current advice.

Measurement idea:
- If approved later, use UTM `utm_campaign=spot_price_timing`.
- Compare click-through to this article from private newsletter/social drafts against generic Kotimaa links; watch time-on-page and related Talous clicks.

Next private asset:
- A short "milloin kannattaa tarkistaa pörssisähkö" explainer card with a mandatory timestamp field.

### 3. Search-led local utility: turn proven seasonal search pages into summer city guides

Source/article signal:
- GSC 28-day snapshot shows existing utility/seasonal pages still earning impressions:
  - `/vappuopas/kaupat-auki/`: 357 impressions, 2 clicks.
  - `/paasiaisopas/kaupat-auki/`: 320 impressions, 2 clicks.
- Fresh article: `Helsingin juhannus houkuttelee saunaan, torille ja Linnanmäelle` has useful city-specific seasonal details.

Target audience/channel:
- Private SEO/distribution planning, not public posting.
- Candidate channels after approval: internal-link module, newsletter city section, or a later "kaupunkijuhannus Helsinki" package.

Angle:
- "Kaupunkijuhannus Helsinki: sauna, tori, Linnanmäki ja tyhjempi keskusta samassa käytännön oppaassa."

Risk note:
- Avoid creating a thin landing page from one article. Needs a package only if it can cite enough concrete details and stay useful after the holiday.
- Seasonal timing is perishable; do not schedule after relevance passes without reframing as archival/evergreen.

Measurement idea:
- If built later, measure GSC impressions/clicks for `kaupunkijuhannus`, `Helsinki juhannus`, and internal clicks from the article to any guide page.
- Use UTM only for approved outbound copy; internal SEO work can be measured via Search Console and page views.

Next private asset:
- One internal-link/guide outline that maps current article details to search intents, with a "publish only if useful" gate.

### 4. Service journalism: adult swimming as summer safety angle

Source/article signal:
- Article: `Aikuisena uimaan oppiminen on vaikeaa, muistuttaa MTV:n uutispäällikkö`.
- Strong seasonal relevance: summer, water safety, parents, adult learners.
- Human problem is clear without requiring public debate or paid promotion.

Target audience/channel:
- Private draft for later newsletter / family-safety / local community distribution.

Angle:
- "Uimataito ei ole vain lasten harrastus: aikuisen oppiminen on vaikeaa, joten kesän uimakoulut ovat turvallisuusteko."

Risk note:
- Avoid shaming adults without swimming skills.
- The article is based on a personal comment; public copy should keep the tone supportive and practical.

Measurement idea:
- If approved later, use UTM `utm_campaign=summer_swimming_safety`.
- Track article clicks and whether related summer/safety articles receive downstream clicks.

Next private asset:
- A compassionate 4-point draft that links the article to practical family summer planning.

### 5. EU/consumer trend: polyester, recycling, and the clothes people already own

Source/article signal:
- Article: `Polyesterin käyttö kasvaa vaatteissa, EU valmistelee tekstiilien kierrätyksen vauhdittamista`.
- Concrete figures: oil-based synthetic fibers around 70% of global clothing textiles; fiber production rose from 125M to 132M tons from 2023 to 2024.

Target audience/channel:
- Private draft for later sustainability, consumer, and EU regulation audiences.

Angle:
- "Vaatteen materiaalilappu muuttuu kuluttajauutiseksi: polyesterin kasvu, EU-sääntely ja kierrätyksen todellinen pullonkaula."

Risk note:
- Avoid overclaiming individual consumer impact; story is partly structural and supply-chain driven.
- Keep claims tied to article figures and source attribution.

Measurement idea:
- If approved later, use UTM `utm_campaign=textile_recycling_explainer`.
- Compare engagement against other EU/consumer explainer posts and track clicks to `Ulkomaat` vs `Talous` adjacent content.

Next private asset:
- One comparison-card draft: "materiaalilappu / mitä se tarkoittaa / miksi EU puuttuu asiaan".

## Prioritization For Iris

Recommended first private follow-up: Angle 1, `Kuluttajan turva: maksukorttihuijaus matkavarauksen jälkeen`.

Why:
- It supports the under-target Talous lane.
- It has a concrete human hook and practical consumer value.
- It can be prepared privately without public posting, X access, GSC wait, spend, or new credentials.

Acceptance for the next Iris task:
- Pick one angle from this backlog.
- Produce a private one-page experiment brief with draft copy, audience/channel, risk checklist, and measurement plan.
- Do not post or schedule anything publicly.
