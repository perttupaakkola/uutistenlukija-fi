# Alex Ghost Implementation Brief

**Deliverable #45** | Monica | 2026-03-25
**Purpose:** Single handoff doc for Alex to start Ghost MVP. References: ghost-cms-eval.md, email-provider-eval.md, ghost-theme-spec.md, journalist-notes-spec.md.

## 🟢 Phase 1 — Start NOW, No Blockers (4–8h)

1. **Ghost Docker Compose on Hetzner** — MySQL 8 + NGINX + SSL
2. **Mailgun EU** — `mg.uutistenlukija.fi`, SMTP config, SPF/DKIM DNS records
3. **Stripe membership** — ⚠️ needs Perttu's Stripe account

## 🟡 Phase 2 — Waiting on Sara (11–18h)

4. Fork **Headline** theme + local dev environment
5. Brand colors, logo, Finnish UI strings
6. Custom `index.hbs` (category grid), `post.hbs` (journalist note callout + source attribution)
7. Mobile + Lighthouse optimization (90+ score target)

## 🔵 Phase 3 — Post-MVP

- Hugo ↔ Ghost API bridge
- Dark mode
- Search
- Luetuimmat-widget (most read)

## Summary

| Item              | Detail                                          |
| ----------------- | ----------------------------------------------- |
| MVP työtunnit     | ~15–26h                                         |
| Kuukausikulu      | ~€40–45/mo                                      |
| Blokattu Pertulla | Stripe-tili                                     |
| Blokattu Saralla  | Värit, logo, fontit, teemavalinta               |
| Ei blokattuna     | Ghost Docker + Mailgun ← Alex voi aloittaa heti |

Source documents referenced inline: #40 (journalist-notes-spec), #42 (email-provider-eval), #44 (ghost-theme-spec), ghost-cms-eval.
