# Homepage Redesign Spec — Pass 2

**Deliverable #46** | Monica | 2026-03-25
**Purpose:** Block-by-block actionable spec for Alex. Based on Monica's Mar 23 homepage analysis from #improvement-ideas.

## 6 Blocks (priority order)

### 1. Site Header
- **Editorial job:** Orient the reader instantly
- **Hugo partial:** `partials/site-header.hbs`
- **Content:** "Päivän tärkeimmät uutiset suomeksi" — no explainer copy
- **CSS:** Minimal, one-line tagline, logo left, nav right

### 2. Pääuutinen (Hero Cluster)
- **Editorial job:** Anchor the page with the day's biggest story
- **Hugo partial:** `partials/hero-cluster.hbs`
- **Content:** 1 lead article + 2 follow-ups. Kicker labels: "Pääuutinen" / "Kehittyvä uutinen"
- **CSS:** Lead gets 2/3 width desktop, full-width mobile. Follow-ups stacked right (desktop) or below (mobile)

### 3. Mitä tapahtui tänään (Quick Briefing)
- **Editorial job:** 30-second catch-up for skimmers
- **Hugo partial:** `partials/daily-briefing.hbs`
- **Content:** 4–6 line summary, numbered list, no images
- **CSS:** Light background card, tight line-height, max-width 640px

### 4. Luetuimmat (Trending)
- **Editorial job:** Social proof, engagement driver
- **Hugo partial:** `partials/trending.hbs`
- **Content:** Top 5 most read. Requires analytics integration (GA4 API or simple click counter)
- **CSS:** Numbered list, compact. **MVP note:** Can skip this block initially if analytics not ready
- **Sara dependency:** ❓ Visual treatment of numbered ranking

### 5. Category Spotlight
- **Editorial job:** Surface variety without overwhelming
- **Hugo partial:** `partials/category-spotlight.hbs`
- **Content:** MAX 2–3 categories per day, rotating/curated — NOT all-categories-always-visible
- **CSS:** Category kicker + 3 headlines per category, card layout
- **Sara dependency:** ❓ Category color coding, card styling

### 6. Newsletter CTA
- **Editorial job:** Convert readers to subscribers
- **Hugo partial:** `partials/newsletter-cta.hbs`
- **Content:** One line + one input field. Bottom of page (not header)
- **CSS:** Full-width band, high contrast, single email input + submit button
- **Sara dependency:** ❓ CTA colors, button styling

## What to Cut
- Explainer intro paragraph
- Mandatory all-categories grid
- Duplicate feeds showing same articles in multiple sections
- Generic section names ("Uutiset", "Artikkelit")

## What to Keep
- Hero prominence (biggest story gets biggest space)
- Source attribution on every article
- Timestamps
- Mobile-first responsive layout

## Sara Dependencies (4 items)
1. Trending block visual treatment
2. Category color coding / card styling  
3. Newsletter CTA colors / button
4. Overall color palette (from ghost-theme-spec.md decisions)

## Alex Can Start Immediately
Blocks 1–3 (Header, Hero, Daily Briefing) have no Sara dependencies. Block 4 can be stubbed. Blocks 5–6 need Sara input for final styling but structure can be built.
