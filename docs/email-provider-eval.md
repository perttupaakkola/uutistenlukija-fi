# Email Provider Evaluation — Mailgun vs Postmark vs Resend

**Deliverable #42** | Monica | 2026-03-25

## TL;DR: Mailgun (EU region) — yksimielinen voittaja

Ghost tukee natiivisti vain Mailgunia newsletter-lähetyksiin. Postmark ja Resend toimivat transaktionaaleihin SMTP:llä, mutta bulk-newsletterin lähettäminen niillä vaatisi custom middleware -rakentamista — 8–20h Alexin aikaa vs. 30 min Mailgunilla.

## Vertailu

|                     | Mailgun                    | Postmark     | Resend        |
| ------------------- | -------------------------- | ------------ | ------------- |
| Ghost newsletter    | ✅ Natiivi                  | ❌ Custom työ | ❌ Custom työ  |
| EU data residency   | ✅ Saksa                    | ❌ Vain US    | ⚠️ Osittainen |
| Hinta launch→50K    | €35/kk                     | ~$50/kk      | $20/kk        |
| Hinta 100K sends    | €90/kk (sis. dedicated IP) | ~$100/kk     | $90/kk        |
| Setup-aika Alexille | ~1–2h                      | 2–8h+        | 8–20h         |

## GDPR

Mailgun ainoa jolla täysi EU-dataresidencie (Saksan datacenter) + EU API endpoint + EU-pohjainen DPO.

## Alexin 6 implementaatioaskelta

1. Mailgun-tili EU-regionilla
2. `mg.uutistenlukija.fi` subdomain
3. DNS (SPF/DKIM)
4. Ghost SMTP config
5. Ghost Admin API key
6. Testinewsletter

📚 Sources: Ghost docs, Mailgun pricing, Postmark pricing, Resend pricing. Verified March 2026.
