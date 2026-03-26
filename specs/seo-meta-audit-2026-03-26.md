# SEO Meta Tag Audit — Spec #31
*Date: 2026-03-26 | Author: Sara | Status: Ready for implementation*

## Target Keywords
- "uutiskooste tänään" (500–1500/mo)
- "uutiskirje ilmainen" (1000–3000/mo)
- "talous uutiset ilmainen" (1000–2500/mo)

---

## 1. Homepage (Etusivu)
**Target keywords:** "uutiskooste tänään", "uutiskirje ilmainen"

- **New Title:** `Uutistenlukija – Kattava uutiskooste tänään suomeksi`
- **New Meta Description:** `Lue päivän tärkein uutiskooste tänään. Tiivistämme uutiset puolestasi: kotimaa, ulkomaat, talous, teknologia ja urheilu. Tilaa ilmainen uutiskirje.`

**Implementation:** `hugo.toml` title param + baseof.html/head partial homepage override

---

## 2. Category: Talous (Economy)
**Target keyword:** "talous uutiset ilmainen"

- **New Meta Description:** `Talous uutiset ilmainen – seuraa talouden uusimpia käänteitä ja markkinauutisia. Lue asiantuntevat tiivistelmät ja säästä aikaa joka päivä.`

**Implementation:** `content/categories/talous/_index.md` params.description

---

## 3. Newsletter CTA (Global)
**Target keyword:** "uutiskirje ilmainen"

- **New Heading:** `Tilaa ilmainen uutiskirje`
- **New Body Text:** `Saat kattavan uutiskoosteen tänään suoraan sähköpostiisi. Pysy ajan tasalla ilman uutisähkyä.`

**Implementation:** `layouts/partials/newsletter-band.html` + `newsletter-cta.html`

---

## 4. Article Fallback Meta Description (single.html)
If no summary present, use:
> `Lue uutiskooste aiheesta [Title]. Tiivistämme päivän tärkeimmät uutiset suomeksi — säästä aikaa ja pysy kärryillä vaivatta.`

**Implementation:** `layouts/_default/single.html` head meta description fallback template

---

## Notes
- All changes are text/template only, no structural HTML changes required
- Keep titles under 60 chars, descriptions under 155 chars
- Category-specific descriptions override global fallback via front matter params
