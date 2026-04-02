# Spec: Big Story Package — homepage module

**Date:** 2026-04-02
**Author:** Monica (research) + Felix (spec)
**For:** Alex (Hugo implementation)
**Priority:** P1 — this is the single biggest UX gap on the homepage

---

## Problem
Homepage is too flat — every article looks equally important. On big news days (drones, fuel crisis, elections), readers can't immediately see "the story" and its related angles.

## Solution
A reusable "Big Story Package" module at the top of the homepage for major stories.

## Structure
```
┌─────────────────────────────────────────┐
│  [JUURI NYT]  Hero headline             │
│  Subheadline / lede (1-2 sentences)     │
│  Päivitetty klo 14:32                   │
├─────────────────────────────────────────┤
│  → Uutinen: Main news article           │
│  → Analyysi: What this means            │
│  → Tausta: Background explainer         │
│  → Seuranta: Live updates (if active)   │
└─────────────────────────────────────────┘
```

## Implementation notes for Alex

### Frontend (Hugo template)
1. New partial: `layouts/partials/big-story-package.html`
2. Renders a hero card with 2-4 linked sub-items below
3. Each sub-item shows content_type label (`Uutinen`, `Analyysi`, `Tausta`, `Seuranta`, `Kooste`)
4. Visible `Päivitetty klo HH:MM` timestamp on the hero

### Content model
- Use frontmatter field `story_package: "kouvola-droni"` to group related articles
- Hero article: `story_package_role: "hero"`
- Sub-items: `story_package_role: "analyysi"` / `"tausta"` / `"seuranta"`
- Template queries `.Site.RegularPages` filtered by `story_package` param

### CSS
- Hero card: larger font, prominent background, clear visual break from rest of feed
- Sub-items: compact list below hero, each with content_type badge
- Labels use existing `content_type` field — just needs CSS badges (already in P1 recommendations)

### When to activate
- Felix/pipeline decides when a story is "big enough" for the package
- Default: homepage shows normal feed
- When `story_package` articles exist for today → package renders at top

## Competitive reference
- Yle: topic clustering with live/analyysi/news entry points
- NRK: "Forklarer" labels on explainer content
- IS: "IS SEURAA" badges for live stories

## Dependencies
- Requires content_type labels (P1 item 3 — already specified)
- Requires `story_package` frontmatter field (new, Alex adds)
- No pipeline changes needed — just frontmatter + template
