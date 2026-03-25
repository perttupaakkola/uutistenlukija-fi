# Ghost CMS Evaluation — Decision Memo

**Deliverable #62** | Monica | 2026-03-25
**Confidence labels:** ✅ confirmed | 🔶 assumption | ❓ needs Alex validation

## 1. Recommendation: Ghost-First MVP ✅

**Yes — Ghost-first for uutistenlukija.fi's newsletter/membership layer.**

- Ghost provides **native publish + newsletter + membership** in one platform ✅
- Hugo remains the public-facing article aggregation site (fast, cheap, SEO-optimized) ✅
- For MVP: Ghost handles newsletter publishing, member management, paid subs, editorial content 🔶
- Ghost Content API can feed into Hugo if cross-publishing is needed later ❓

## 2. `journalist_note` Model — Now

Ghost has **no native custom fields**. ✅ Best approach for MVP:

**Use internal tag `#journalist-note` + callout card convention** in the editor. No custom code needed, filterable via Content API, requires editorial discipline. If we later need true structured data, Alex can build middleware that parses callout cards via API. ❓

Other options considered: excerpt field repurposing (🔶 loses excerpt functionality), code injection JSON (fragile, not recommended).

## 3. Ghost Limitations Without Custom Work

- ❌ No custom post fields (use tags/code injection workaround)
- ❌ No native RSS aggregation (existing Hugo pipeline handles this)
- ❌ Max 20 custom theme settings (sufficient for MVP)
- ❌ Self-hosted email requires Mailgun/Postmark (~€15-35/mo)
- ❌ Starter plan removed paid subscriptions (need Publisher $29/mo or self-host)
- ✅ Single-language fine for Finnish-only site
- ✅ Content API read-only but sufficient for newsletter use case

## 4. Alex-First Implementation Steps

1. **Provision Ghost self-hosted** — Docker Compose on VPS, MySQL 8, NGINX, SSL (~2-4h) ❓
2. **Configure Mailgun** — sending domain, SPF/DKIM/DMARC DNS records (~1-2h) ❓
3. **Theme + branding** — customize theme matching uutistenlukija identity (~3-5h, needs Sara input) ❓
4. **Membership + Stripe** — connect Stripe, configure free/paid tiers (~1-2h, needs Perttu pricing decision) ❓
5. **Content API bridge** — optional sync Ghost → Hugo for cross-publishing (~4-8h) ❓

**Total estimated: ~11-21h of Alex's time** 🔶

## 5. MVP Cost

| Option                    | Monthly                           |
| ------------------------- | --------------------------------- |
| Self-hosted (recommended) | ~€5-23/mo (Hetzner VPS + Mailgun) |
| Ghost(Pro) Publisher      | ~€27/mo (email included)          |

**Recommendation:** Self-hosted — team already has VPS infra + DevOps capability. Can migrate to Ghost(Pro) later if ops burden grows. ✅

## 6. Summary

| Decision                          | Answer                                  | Confidence                    |
| --------------------------------- | --------------------------------------- | ----------------------------- |
| Ghost-first or Hugo-first?        | Ghost-first for newsletter/membership   | ✅                             |
| journalist_note model             | Internal tag + callout card             | 🔶 needs editorial testing    |
| First Alex action                 | Provision Ghost Docker on VPS           | ❓ needs Alex infra validation |
| Limitations acceptable?           | Yes for MVP                             | ✅                             |
| Hosting                           | Self-hosted Hetzner ~€5-23/mo           | 🔶                            |
| When reconsider Hugo integration? | After MVP validates newsletter audience | ✅                             |

---

📚 Sources: ghost.org/pricing, ghost.org/docs, Ghost forums (2025-2026). Pricing verified March 2026.
