# Finnish Article Sources Research — Supplement

**Deliverable (supplement to #26/#29)** | Monica | 2026-03-25
**Note:** Overlaps significantly with source-allowlist-rss.md (#26) and source-tier-analysis.md (#29). Saved for the HIGH.FI API finding and content gap opportunities.

## Tier 1 — Ready to Ingest Now (free, no paywall)

- **YLE Uutiset** — 4 RSS feeds (main, headlines, most-read, sports) + topic filtering via `concepts` param
- **Iltalehti** — full RSS + short headline feed
- **MTV Uutiset** — commercial TV news RSS
- **Iltasanomat** — RSS available (partial paywall, needs verification)

## Tier 2 — Business Vertical

- **Kauppalehti** — headlines RSS (paywall on full articles)
- **Talouselämä** — RSS available, mostly paywalled

## HIGH.FI News Aggregator API 🌟

Direct competitor/benchmark. JSON API with categories, popularity scoring, paywall indicators. Free API key. Worth studying their category taxonomy and source selection for gaps in our own pipeline.

## Content Gap Opportunities

1. **YLE Selkouutiset** (plain-language news) — unique niche nobody else aggregates
2. **Regional newspapers** (Aamulehti, Turun Sanomat, Kaleva) — national aggregators skip these
3. **Tech news** (Tivi, Tekniikka & Talous)
4. **International APIs** (NewsData.io free tier: 200 req/day) for Finland-related international coverage

## Legal Note

⚠️ STT and HS full content require commercial licenses. RSS headline + link aggregation is generally OK.
