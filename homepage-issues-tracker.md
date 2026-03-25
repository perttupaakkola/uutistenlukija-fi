# Homepage Issues Tracker

Created: 2026-03-25 21:20 UTC
Source: Perttu's screenshot review + Felix visual audit (Mar 23, 18:08 UTC, #improvement-ideas)
Purpose: Track every identified homepage problem to resolution.

## Status Legend
- 🔴 Not started
- 🟡 In progress
- 🟢 Fixed
- ⏸️ Blocked

---

## VISUAL / UI ISSUES (from screenshot audit)

| # | Issue | Severity | Owner | Status | Notes |
|---|-------|----------|-------|--------|-------|
| V1 | Mobile layout too narrow/cramped — content column too skinny | P0 | Alex | 🟢 Fixed | `efb6bac` + `6465d50` (Mar 23) — wider mobile layout, fuller-bleed lead |
| V2 | Header/logo area weak and under-designed | P2 | Sara → Alex | 🟡 In progress | Sara delivered brand specs (Mar 25 17:24) — logo formats, OG images. Alex Phase 2 will implement |
| V3 | Hero/top story image not impactful enough | P0 | Alex | 🟢 Fixed | `6465d50` — stronger top-story hierarchy, dominant lead |
| V4 | Article cards visually repetitive — no hierarchy | P0 | Alex | 🟢 Fixed | `efb6bac` + `6465d50` — varied card treatments, deduped |
| V5 | Typography hierarchy weak — headlines/metadata/excerpts too similar | P1 | Alex | 🟢 Fixed | Part of `efb6bac` pass — improved headline/excerpt hierarchy |
| V6 | Images inconsistent — awkward crops, monotonous proportions | P1 | Alex | 🟡 Partial | Card treatments varied, but image pipeline still uses stock/scraped images. Needs better image selection logic |
| V7 | Category labels/metadata noisy and cluttered | P1 | Alex | 🟢 Fixed | Card meta noise reduced in Mar 23 pass |
| V8 | Spacing rhythm inconsistent | P2 | Alex | 🟢 Fixed | Part of `efb6bac` — section pacing improved |
| V9 | Section transitions weak — unclear boundaries | P1 | Alex | 🟢 Fixed | `6465d50` — clearer section separation, right-rail "Seuraa nyt" |
| V10 | Duplicate stories/images appearing in multiple places | P0 | Alex | 🟢 Fixed | `6465d50` — deduped upper homepage flow |
| V11 | No premium editorial feel — looks like MVP/content dump | P0 | All | 🟡 In progress | Mar 23 pass improved significantly. Monica's pass 2 spec in progress for next level |

## CONTENT / IA / EDITORIAL ISSUES (from content audit)

| # | Issue | Severity | Owner | Status | Notes |
|---|-------|----------|-------|--------|-------|
| C1 | Doesn't feel like a front page — more like a generated feed | P0 | Monica + Alex | 🟡 In progress | Monica delivering homepage editorial strategy spec → Alex implements. `6465d50` was pass 1 |
| C2 | "Why these stories?" logic unclear — no visible editorial judgment | P0 | Monica | 🟡 In progress | Monica's editorial ranking logic in her Mar 23 audit. Pass 2 spec being written now |
| C3 | Not enough story prioritization — everything similar weight | P0 | Alex | 🟢 Partial | `6465d50` added 1 dominant lead + 2 follow-up hierarchy. Still needs editorial scoring |
| C4 | Over-optimized for publishing, under-optimized for reading | P1 | Monica | 🟡 In progress | Monica's homepage spec addresses user intents (catch up fast, browse by topic, most read) |
| C5 | Too much low-signal inventory on homepage | P1 | Monica + Alex | 🟡 In progress | Monica recommended: stricter quality filter for homepage, fewer cards with stronger selection |
| C6 | Not enough freshness framing — no "updated just now" cues | P1 | Alex | 🔴 Not started | Need: "Päivitetty juuri nyt", "Uusi kehitys", time-alive cues on cards |
| C7 | Not enough distinct article roles (urgent/important/explainer/lighter) | P1 | Sara + Alex | 🟡 In progress | Sara delivered journalist-notes style guide (content_type badges: ANALYYSI, MIELIPIDE). Alex to implement in templates |
| C8 | Weak trust signals — repetition/generic packaging erodes credibility | P0 | All | 🟡 In progress | Bylines fixed (Toimitus), source attribution added, dedup done. Journalist notes next step |
| C9 | Missing stronger entry points (catch up fast, by topic, most read, latest) | P0 | Alex | 🟡 Partial | "Seuraa nyt" right-rail added, "Tänään aktiivisimmat" exists. Still need: "Kärryille nopeasti" summary block, real "Luetuimmat" |
| C10 | Product identity unclear (newspaper? aggregator? digest?) | P1 | Monica | 🟢 Resolved | Perttu decided Mar 23: we are a **newspaper** (verkkolehti). Docs updated, identity clear |
| C11 | Top of page not doing enough work above the fold | P0 | Alex + Monica | 🟡 In progress | Improved in pass 1. Monica's pass 2 recommends: tighten intro copy, stronger editorial labels |
| C12 | Lacks "reason to return daily" | P1 | Monica + Alex | 🟡 In progress | Monica spec includes: habit-forming "Kärryille nopeasti" block, daily briefing format |
| C13 | Empty "Luetuimmat" weakens polish | P0 | Alex | 🔴 Not started | Monica recommended: hide if no data, or fallback to "Toimituksen valinnat" |
| C14 | Category balance — mechanical/random feeling, not curated | P1 | Monica → Alex | 🟡 In progress | Monica recommended: only show categories with genuinely homepage-worthy stories |
| C15 | Headline/excerpt quality inconsistent — some feel translated/generic | P1 | Pipeline | 🟡 In progress | rewriter.py improvements ongoing. Tier-aware rewriter (`75c2960`) improved quality. More work needed |

## STRUCTURAL RECOMMENDATIONS (from Monica's editorial spec)

| # | Recommendation | Owner | Status | Notes |
|---|---------------|-------|--------|-------|
| S1 | Homepage block order: Hero → Tärkeimmät nyt (3-4) → Kärryille nopeasti → Viimeisimmät → Luetuimmat → Category entries → Taustoitus → Newsletter | Monica → Alex | 🟡 Monica writing spec | Monica assigned this as her current task |
| S2 | Sharper editorial section naming (Tärkeimmät nyt, Päivän kuva, etc.) | Monica → Alex | 🔴 Not started | Depends on S1 |
| S3 | Reduce category blocks to only those with strong stories that day | Alex | 🔴 Not started | Requires template logic changes |
| S4 | Tighter headline/excerpt quality threshold for upper homepage | Pipeline | 🔴 Not started | Needs quality scoring in rewriter/publisher |
| S5 | Homepage should feel shorter and more opinionated | Alex + Monica | 🔴 Not started | Depends on S1 spec |

---

## Summary

- **Fixed (🟢):** 9 issues — mostly from the Mar 23 sprint (V1, V3, V4, V5, V7, V8, V9, V10, C10)
- **In progress (🟡):** 12 issues — agents actively working
- **Not started (🔴):** 5 issues — waiting on current work to complete
- **Blocked (⏸️):** 0

## Current Agent Assignments (related to homepage)
- **Alex** → Ghost CMS Phase 1 (infra), then Phase 2 will address remaining visual issues
- **Sara** → Brand decisions ✅ delivered, journalist-notes style guide ✅ delivered. Standing by for QA
- **Monica** → Writing homepage editorial strategy spec (S1) — her current active task
- **Max** → Pipeline ops (not directly homepage, but pipeline health affects content freshness)

## Next Actions
1. Monica delivers homepage block-by-block spec → posted to #research
2. Alex implements spec after Ghost Phase 1 infra is done
3. C6 (freshness framing) and C13 (empty Luetuimmat) are quick wins Alex can do anytime
4. S4 (headline quality threshold) needs pipeline work — separate from template changes
