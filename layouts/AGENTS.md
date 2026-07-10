# AGENTS.md — Layouts

## Purpose

`layouts/` owns Hugo templates and public HTML structure for `uutistenlukija.fi`.

## Ownership

- Sara owns design/UX/SEO planning and browser review.
- Alex implements template changes.
- Felix verifies production impact and coordinates handoffs.

## Local Contracts

- Read `../DESIGN.md` before changing templates, navigation, article pages, category pages, monetization UI, or SEO markup.
- Keep the site credible, calm, fast, and editorial. Avoid SaaS-style visual clutter, fake urgency, emoji-heavy UI, and generic AI-looking sections.
- Preserve accessibility, semantic landmarks, canonical/metadata behavior, NewsArticle/CollectionPage structured data, and Finnish-language UX.
- Do not hardcode secrets, private analytics values, or account tokens in templates.
- `partials/ad-config.html` is the authoritative server-side ad gate. Provider hints, runtime loading, slot intent/markup, hydration, and initialization must not bypass it; external provider resources require a non-empty provider ID plus explicit consent from the configured current revision. Keep dormant consent on v2 until a separately reviewed activation release advances the revision.
- Do not edit `public/` as the source for UI fixes; edit templates/assets and rebuild.

## Work Guidance

- Make one template concern obvious per patch where possible.
- Check mobile and desktop behavior for visible UI changes.
- Keep monetization experiments approval-gated for outbound campaigns and paid/account changes, but safe on-site CTA/measurement changes may be implemented with tests.

## Verification

- `bash scripts/validate_templates.sh`
- `hugo --minify --destination /tmp/uutistenlukija-hugo-check`
- `python3 pipeline/ci_validate.py --skip templates` when a broader build validation is needed.
- Browser or screenshot evidence for visual changes when available.

## Child DOX Index

No child `AGENTS.md` files are currently required here.
