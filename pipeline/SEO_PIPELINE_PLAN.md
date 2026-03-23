# SEO Data Pipeline Plan — Uutistenlukija.fi
*Created: 2026-03-21 | Author: Max*

## Status at Plan Time

| Data source | Status |
|---|---|
| GA4 Data API | ✅ Connected, tokens refresh via OAuth2. **No data yet** — GA4 tag fires (`G-35XERS8V6J` confirmed in HTML) but no sessions recorded. Likely new property / cold start. Data will appear within 24–72h. |
| Search Console API | ✅ Connected. **No data yet** — 2-3 day lag for new properties. Sitemap not submitted (read-only token; see Action Items). |
| X / Twitter | ✅ Connected. @Uutistenlukija_ account, 500 posts/month free tier. OAuth2 tokens have 2h TTL, refresh script ready. |

---

## Module 1 — Daily SEO Dashboard (script: `seo_daily_dashboard.py`)

**Runs:** Every day at 07:30 UTC via cron (after SC data is available)

**What it pulls:**
- **Search Console:** Top 25 queries by clicks; top 25 pages by clicks; avg CTR, position, impressions
- **GA4:** Sessions, pageviews, users, bounce rate (last 24h + 7d trend); top 10 pages; traffic source breakdown

**Output:** Posts to Discord `#seo` channel (1482511287912104130)

**Format:**
```
📊 SEO Daily — 2026-03-21

Search Console (last 3 days, SC lag)
  Top queries: "uutiset", "päivän uutiset", "suomi uutiset" ...
  Top pages: /posts/xyz (230 clicks, 4.2% CTR, pos 3.1)
  ⚠️  Low CTR pages: /posts/abc (2,000 impressions, 0.8% CTR) → fix title

GA4 (last 24h)
  Sessions: 1,234 | Users: 891 | Pageviews: 2,156
  Sources: organic 61% | direct 22% | referral 17%

Real-time: 4 active users
```

**Key insight:** Low CTR pages (high impressions, CTR <2%) are flagged for title/meta review.

---

## Module 2 — Content Optimization Loop (script: `seo_optimization_loop.py`)

**Runs:** Weekly on Monday 08:00 UTC

**Algorithm:**
1. Pull last 30 days SC data: all pages with >200 impressions
2. Flag **underperformers**: impressions ≥200 AND CTR <2% AND avg position ≤30
3. For each flagged page, read its markdown frontmatter (title, description)
4. Call OpenAI (gpt-4o-mini) to suggest improved title + meta description:
   - Current title + query context fed as input
   - Output: 3 variants for title (≤60 chars), 1 meta description (≤155 chars)
5. Write recommendations to `pipeline/logs/seo-optimization-YYYY-MM-DD.json`
6. Post top 5 recommendations to Discord `#seo`

**Example output:**
```json
{
  "page": "/posts/2026-03-19-markkinoilla-heiluntaa",
  "current_title": "Markkinoilla heiluntaa - analyytikot puhuvat...",
  "current_ctr": 0.009,
  "impressions": 1840,
  "avg_position": 8.2,
  "suggested_titles": [
    "Pörssiromahdus: Mitä analyytikot sanovat nyt?",
    "Markkinaheilunta jatkuu – asiantuntijoiden arviot",
    "Osakemarkkinat laskussa: syyt ja seuraukset"
  ],
  "suggested_description": "Analyytikot arvioivat pörssiromahduksen syitä..."
}
```

**Next step (Phase 2):** Auto-apply top recommendation if confidence >85%, write back to frontmatter, trigger rebuild.

---

## Module 3 — Auto-posting to X (script: `x_auto_poster.py`)

**Timing:** Post 3–4 times/day. Best Finnish news engagement times:
- 07:30 (morning commute)
- 11:30 (lunch break)
- 17:00 (after work)
- 20:00 (evening)

**Selection logic (priority order):**
1. Articles published in last 90 min with source_tier=1 (Yle, IS, HS, BBC, Reuters)
2. Articles with most views in GA4 last 24h (once data flows)
3. Fresh articles with high-engagement categories: Kotimaa, Ulkomaat, Talous, Urheilu

**Tweet format:**
```
[Emoji] [Title, max 180 chars]

[1-sentence summary — original description of the article]

uutistenlukija.fi/posts/... #uutiset #[category_tag]
```

**Category → hashtag map:**
- Kotimaa → #suomi #kotimaa
- Ulkomaat → #ulkomaat #maailma
- Talous → #talous #osakkeet (if finance) / #talous
- Urheilu → #urheilu
- Teknologia → #teknologia #tekoäly (if AI)
- Tiede → #tiede

**Rate limit:** 500 posts/month free tier = ~16/day max. Target 3-4/day = ~90-120/month. Well within limit.

**Token refresh:** `scripts/refresh-x-token.sh` must run every 90min on host (cron not yet installed).

**Duplicate guard:** Track posted URLs in `pipeline/logs/x-posted.json`.

---

## Module 4 — Weekly SEO Report (script: `seo_weekly_report.py`)

**Runs:** Every Monday 09:00 UTC, posts to `#metrics` (1482720741790060554)

**Contents:**
```
📈 SEO Weekly Report — Week 12 (Mar 15–21)

TRAFFIC
  Organic sessions: 8,234 (+12% WoW)
  Top organic page: /posts/xyz (1,840 clicks)
  New pages indexed: 87

SEARCH CONSOLE
  Total impressions: 142,000 | Clicks: 3,100 | CTR: 2.2%
  Avg position: 18.4 (improved from 21.1)
  Top query: "päivän uutiset" (340 clicks, pos 4.2)

CONTENT QUALITY
  Articles optimized this week: 5
  CTR improvement from optimizations: est. +0.8pp

WINS
  - "Markkinaheilunta" article: 2.3k impressions, pos 3.1
  - Category page /kotimaa indexed for 12 new queries

OPPORTUNITIES
  - 23 pages with >500 impressions, CTR <1.5% → batch optimize
  - Category /talous has avg pos 15 — could break top 10 with internal linking

X/TWITTER
  Posts this week: 21 | Engagement: [impressions when read API available]
```

---

## Module 5 — Sitemap Registration & Index Coverage (script: `seo_sitemap_monitor.py`)

**Immediate action needed (Perttu):**
The Search Console token is **read-only** (`webmasters.readonly` scope). To submit the sitemap programmatically, Felix needs a token with `webmasters` (write) scope.

**Workaround until then:** Manual submission via Search Console UI:
1. Go to https://search.google.com/search-console
2. Select `sc-domain:uutistenlukija.fi`
3. Sitemaps → Add sitemap → `https://uutistenlukija.fi/sitemap.xml`

**After write token obtained:**
- `seo_sitemap_monitor.py` will auto-submit sitemap weekly
- Monitor index coverage: track submitted vs indexed URL count
- Alert if indexed count drops >10% week-over-week

**Current sitemap:** Live at `https://uutistenlukija.fi/sitemap.xml`, Google News sitemap format ✅

---

## Module 6 — Analytics-Driven Content Priorities (for Monica)

**Runs:** Weekly, output posted to `#research` (1482720265174782055) and @Monica

**Logic:**
1. Pull top 20 categories by organic traffic (GA4 + SC combined)
2. Pull top 20 search queries with no matching article (queries with >50 impressions, no click-through)
3. Identify "content gaps": trending queries in our topic area with no existing article
4. Format as content brief for Monica:

```
📝 Content priorities for this week:

HIGH PRIORITY (traffic gaps):
- Query "suomen nato joukot" — 480 impressions, 0 articles matching closely
- Query "öljyn hinta suomi" — 320 impressions, coverage thin

TRENDING in our existing categories:
- Talous articles getting 2x avg views this week
- Teknologia/tekoäly queries up 40%

UNDERSERVED categories:
- Tiede: only 3 articles/week, 15% of organic impressions
```

---

## Implementation Timeline

### Phase 1 — This Week (Max implements)
- [x] SEO pipeline plan written ← this document
- [ ] `seo_daily_dashboard.py` — read GA4 + SC, post to #seo
- [ ] `x_auto_poster.py` — select + post articles to X (3-4/day)
- [ ] Token refresh cron for X (needs host crontab update by Perttu)
- [ ] Sitemap submission (needs Perttu to re-auth SC with write scope OR manual submit)

### Phase 2 — Next Week
- [ ] `seo_optimization_loop.py` — underperformer detection + AI title suggestions
- [ ] `seo_weekly_report.py` — full weekly digest to #metrics
- [ ] `seo_sitemap_monitor.py` — index coverage tracking

### Phase 3 — When SC data populates (3-5 days)
- [ ] `seo_content_priorities.py` — content gap analysis → feed to Monica
- [ ] Auto-apply high-confidence title optimizations to frontmatter

---

## Action Items for Perttu

1. **Search Console write scope** — re-auth at https://search.google.com/oauth2 with `webmasters` scope (not `webmasters.readonly`), save to `/workspace/.secrets/search-console-tokens.json`. Felix can then submit sitemap and monitor coverage programmatically.

2. **OR manual sitemap submit** (2 minutes): Search Console UI → Sitemaps → `https://uutistenlukija.fi/sitemap.xml`

3. **X token refresh cron** — add to host crontab:
   ```
   */85 * * * * /workspace/scripts/refresh-x-token.sh >> /workspace/logs/x-token-refresh.log 2>&1
   ```

4. **Watchdog cron update** (from earlier): switch `auto_publish.sh` → `scripts/pipeline-watchdog.sh`

---

## Token Management

| API | Token file | Refresh | TTL |
|---|---|---|---|
| GA4 | `/workspace/.secrets/analytics-tokens.json` | `oauth2.googleapis.com/token` | 1h |
| Search Console | `/workspace/.secrets/search-console-tokens.json` | `oauth2.googleapis.com/token` | 1h |
| X OAuth 2.0 | `/workspace/.secrets/x-tokens.json` | `scripts/refresh-x-token.sh` | 2h |

All Google tokens: auto-refresh via `refresh_token` before each script run. X token: needs cron or manual refresh.
