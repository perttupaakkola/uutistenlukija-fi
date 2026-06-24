---
name: Uutistenlukija Editorial Design System
version: 1.0.0
status: active
owner: Sara
scope: projects/uutistenlukija
updated: 2026-06-24

colors:
  primary: "#C0392B"
  primary-hover: "#A93226"
  primary-dark: "#E74C3C"
  background: "#FAFAF8"
  surface: "#FFFFFF"
  surface-alt: "#F1EEE8"
  text: "#1A1A1A"
  text-secondary: "#555555"
  text-muted: "#666666"
  border: "#E0DDD8"
  dark-background: "#1A1A1A"
  dark-surface: "#242424"
  dark-surface-alt: "#202428"
  dark-text: "#E8E6E3"
  dark-text-secondary: "#A0A0A0"
  success: "#1F7A4D"
  warning: "#B26A00"
  sponsored: "#F0B030"

typography:
  headline-xl:
    fontFamily: "Georgia, Times New Roman, serif"
    fontSize: "clamp(2.4rem, 5vw, 4.25rem)"
    fontWeight: 900
    lineHeight: 0.95
    letterSpacing: "-0.045em"
  headline-lg:
    fontFamily: "Georgia, Times New Roman, serif"
    fontSize: "clamp(1.8rem, 3vw, 2.8rem)"
    fontWeight: 850
    lineHeight: 1.04
    letterSpacing: "-0.035em"
  headline-md:
    fontFamily: "Georgia, Times New Roman, serif"
    fontSize: "clamp(1.25rem, 2vw, 1.8rem)"
    fontWeight: 800
    lineHeight: 1.08
    letterSpacing: "-0.025em"
  body:
    fontFamily: "Georgia, Times New Roman, serif"
    fontSize: "17px"
    fontWeight: 400
    lineHeight: 1.7
  ui:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif"
    fontSize: "14px"
    fontWeight: 600
    lineHeight: 1.35
  label:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif"
    fontSize: "12px"
    fontWeight: 750
    lineHeight: 1.15
    letterSpacing: "0.065em"
    textTransform: uppercase

spacing:
  0: "0"
  1: "0.25rem"
  2: "0.5rem"
  3: "0.75rem"
  4: "1rem"
  5: "1.25rem"
  6: "1.5rem"
  8: "2rem"
  10: "2.5rem"
  12: "3rem"
  16: "4rem"

layout:
  max-width: "1100px"
  reading-width: "720px"
  narrow-width: "640px"
  page-padding-mobile: "1rem"
  page-padding-desktop: "1.5rem"
  grid-gap: "1.5rem"
  card-gap: "1rem"
  breakpoint-sm: "640px"
  breakpoint-md: "768px"
  breakpoint-lg: "1024px"
  breakpoint-xl: "1200px"

radius:
  none: "0"
  sm: "2px"
  md: "4px"
  lg: "8px"
  pill: "999px"

borders:
  hairline: "1px solid #E0DDD8"
  strong: "2px solid #1A1A1A"
  accent: "2px solid #C0392B"

motion:
  fast: "120ms ease"
  normal: "220ms ease"
  slow: "360ms ease"

components:
  article-card:
    background: "transparent or surface"
    border: "hairline only when it improves grouping"
    imageRatio: "16/9 for normal cards, 4/3 for feature cards"
    hover: "accent title color, no gimmicky transforms"
  lead-story:
    layout: "large headline, strong image, concise summary, clear metadata"
    emphasis: "one dominant story per page; never make every card loud"
  category-label:
    style: "small uppercase sans label with accent color or subtle border"
  button:
    style: "solid accent for primary, outline/ghost for secondary"
    radius: "md"
  newsletter-box:
    style: "editorial callout, not SaaS marketing card"
  quote-pullout:
    style: "large serif, left accent rule, high contrast"
---

# Uutistenlukija Editorial Design System

## Purpose

`uutistenlukija.fi` should feel like a serious, modern Finnish digital newspaper: credible, fast, calm, readable, and slightly premium. It should not look like a generic SaaS landing page, a blog template, or an AI-generated demo site.

## Protected portal template baseline

The restored June portal template is the accepted production baseline. As of 2026-06-24, the reference restore is commit `0777ad27e`, based on the known-good June portal design from `d042e2594`.

Sara and other design agents should work with this template when suggesting changes. Proposals should refine the existing portal structure, hierarchy, spacing, copy, accessibility, SEO presentation, and component behavior inside the current template instead of replacing the template, changing the site-wide colour system, or proposing a broad redesign.

Changing the template architecture or site-wide colour direction requires an explicit Felix/Perttu-approved Linear issue. A design review that recommends changes must state how the recommendation preserves the current portal template baseline.

The design goal is **editorial authority with modern restraint**:
- strong typography
- clear hierarchy
- calm color palette
- generous whitespace
- high information density where appropriate
- minimal decorative effects
- excellent mobile readability

## Brand personality

- **Credible**: feels trustworthy enough for news.
- **Sharp**: clear hierarchy, decisive headlines, no mushy cards.
- **Nordic**: restrained, spacious, functional, not overdesigned.
- **Readable**: article pages are comfortable for long reading.
- **Current**: modern web patterns, but not trendy for trendiness' sake.

Avoid:
- glassmorphism, neon gradients, generic AI blobs
- excessive shadows and rounded SaaS cards
- emoji-heavy UI
- random color-coded sections without editorial logic
- dense clutter above the fold
- low-contrast grey-on-grey text

## Visual hierarchy

Every page needs an obvious hierarchy:

1. **Primary lead story**: one dominant item with the largest headline.
2. **Secondary stories**: supporting grid/list items.
3. **Tertiary items**: compact headlines, metadata, category sections.
4. **Utility UI**: search, nav, theme toggle, newsletter, archive links.

If everything is equally prominent, the page has failed. Make one thing clearly first.

## Color usage

The red accent is an editorial signal, not a decoration bucket.

Use `#C0392B` for:
- active nav state
- primary CTAs
- section rules/labels
- hover states
- important editorial emphasis

Do not flood cards or section backgrounds with red. Use it sparingly so it remains meaningful.

Light mode should feel warm off-white, not stark white. Dark mode should be readable and neutral, not pure black.

## Typography

Use serif typography for editorial voice and headline authority. Use sans-serif for navigation, labels, metadata, buttons, forms, and utility text.

Headline rules:
- Use tight line-height and negative tracking for large headlines.
- Headlines should wrap cleanly and avoid orphan words when possible.
- Do not center large news headlines except for special editorial packages.

Body text rules:
- Article body should be 17–19px depending on viewport.
- Line length should stay around 65–75 characters.
- Paragraph rhythm matters more than decorative styling.

Metadata rules:
- Metadata is sans-serif, compact, and muted.
- Dates/categories should support scanning, not compete with headlines.

## Layout principles

- Maximum content width: about 1100px.
- Article reading width: about 720px.
- Mobile-first layouts must be intentional, not collapsed desktop grids.
- Use grid for homepage/category pages and a single readable column for article pages.
- Keep nav sticky if it helps orientation, but never let it dominate mobile screens.

Homepage structure recommendation:

1. Header/nav/date/search.
2. Lead story module.
3. Top stories grid.
4. Category rails or topic sections.
5. Daily digest / “Pähkinänkuoressa” style summary box.
6. Newsletter or follow CTA.
7. Footer with clear site identity.

## Component guidance

### Lead story

The lead story should have visual weight:
- big serif headline
- strong image or clean editorial block
- concise summary
- category + time/source metadata

Use asymmetry on desktop if it improves hierarchy. On mobile, stack image, label, headline, summary.

### Article cards

Cards should feel editorial, not app-like.

Preferred patterns:
- clean naked cards with borders/rules
- image + headline + metadata
- subtle hover color change
- compact summary only where useful

Avoid:
- heavy box shadows
- excessive border radius
- uniform card decks that make news feel like products

### Category sections

Each category section should have:
- strong section header
- thin rule or accent marker
- consistent card rhythm
- no more than one extra visual motif

### Article pages

Article pages must prioritize reading:
- clear headline and lead paragraph
- metadata visible but subdued
- hero image with caption if available
- comfortable line length
- related articles after the article, not interrupting early reading
- newsletter CTA after meaningful content, not immediately after title

### Daily summary / digest modules

The “Päivän kooste” style should feel useful and scannable:
- short bullets or compact sections
- strong timestamp/date context
- avoid walls of text
- emphasize what changed and why it matters

## Accessibility requirements

- All color combinations must meet WCAG AA contrast.
- Keyboard focus must be visible.
- Do not remove skip links.
- Links must be distinguishable by more than color in long-form body text.
- Respect `prefers-reduced-motion`.
- Touch targets should be at least 44px where practical.
- Dark mode must preserve contrast and hierarchy.

## Responsive behavior

Mobile:
- one-column flow
- large tap targets
- concise nav
- no horizontal scroll
- lead story still clear but not overwhelming

Tablet:
- two-column grids where useful
- preserve headline hierarchy

Desktop:
- use multi-column editorial layout
- avoid stretching article text beyond readable width
- use whitespace intentionally

## Sara's design workflow

When Sara works on this site, she should:

1. Read this `DESIGN.md` before changing UI.
2. Inspect the actual page in a browser or screenshots.
3. Identify the design problem in concrete terms: hierarchy, spacing, typography, contrast, responsiveness, or component consistency.
4. Make a focused change, not a broad restyle.
5. Verify visually at desktop and mobile widths.
6. Run the relevant build/test command before declaring done.
7. Update this file if a new durable design rule is learned.

## Quality bar

A change is not good enough unless:
- the page looks intentionally designed at first glance
- the lead story is obvious within 2 seconds
- headlines are readable and attractive
- cards align and breathe correctly
- mobile is clean
- dark mode is not an afterthought
- the site still feels like a news publication

## Implementation mapping

Existing CSS tokens live mainly in:
- `themes/uutistenlukija/static/css/style.css`
- `themes/uutistenlukija/static/css/homepage-polish.css`
- `themes/uutistenlukija/static/css/article.css`
- `themes/uutistenlukija/static/css/category.css`
- `themes/uutistenlukija/static/css/category-hero.css`

When possible, align CSS variables with the tokens in this file instead of hardcoding new visual values in isolated selectors.
