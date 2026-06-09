# AGENTS.md — Theme

## Purpose

`themes/uutistenlukija/` contains theme-level Hugo layouts, CSS, and JavaScript used by the public site.

## Ownership

- Sara owns visual design, UX, accessibility, SEO presentation, and browser review.
- Alex owns implementation details.
- Felix verifies deploy readiness.

## Local Contracts

- Read `../../DESIGN.md` before changing theme UI, typography, spacing, colors, motion, or component behavior.
- Preserve the editorial newspaper feel: serious, fast, readable, restrained, and Finnish-language appropriate.
- Avoid generic SaaS effects, excessive shadows/rounding, neon/glass styling, and decorative animation without editorial purpose.
- Keep CSS/JS compatible with Hugo build and existing templates.
- Do not place private analytics/account values in theme files.

## Work Guidance

- Prefer design-token-consistent changes over one-off values.
- Check mobile and desktop for visible changes.
- If theme and root `layouts/` overlap, verify both paths and avoid contradictory partials.

## Verification

- `bash scripts/validate_templates.sh`
- `hugo --minify --destination /tmp/uutistenlukija-hugo-check`
- Browser/screenshot review for visual changes when available.

## Child DOX Index

No child `AGENTS.md` files are currently required here.
