# Pipeline Cron Schedule

All times UTC. Copy-paste the full block below into `crontab -e` on the deploy host.

## Quick Reference

| Schedule | Job | Purpose | Output |
|---|---|---|---|
| `*/15 * * * *` | pipeline watchdog | Scan → rewrite → publish (auto-retry, 5 max) | #operations on failure |
| `*/85 * * * *` | X token refresh | Keep OAuth2 token alive (2h TTL) | log file |
| `30 7 * * *` | SEO dashboard | GA4 + Search Console daily digest | #seo |
| `30 7,11,17,20 * * *` | X auto-poster | Post recent articles to @Uutistenlukija_ | X/Twitter |
| `0 6 * * *` | metrics report | 7-day pipeline stats | #metrics |
| `0 9 * * *` | Lighthouse | Score tracking + delta | #metrics |
| `0 17 * * *` | daily briefing | Build `Päivän kooste` newsletter HTML preview | `static/newsletter/` |
| `0 7 * * 1` | content quality | Weekly article validation | #operations |
| `0 7 * * 0` | dead links | Weekly crawl for broken links | #metrics |

---

## Full Crontab Block (copy-paste ready)

```cron
# ══════════════════════════════════════════════════════════════════════════════
# uutistenlukija.fi pipeline — full cron schedule
# Deploy host: /home/pertt/.openclaw/workspace/projects/uutistenlukija
# Last updated: 2026-03-21
# ══════════════════════════════════════════════════════════════════════════════

PROJECT=/home/pertt/.openclaw/workspace/projects/uutistenlukija
PIPELINE=$PROJECT/pipeline
LOGS=$PIPELINE/logs
WORKSPACE=/home/pertt/.openclaw/workspace

# ── Main pipeline (every 15 min, via watchdog for auto-retry + alerting) ─────
*/15 * * * * $PROJECT/scripts/pipeline-watchdog.sh >> $LOGS/watchdog.log 2>&1

# ── X / Twitter token refresh (every 85 min — token TTL is 2h) ───────────────
*/85 * * * * $WORKSPACE/scripts/refresh-x-token.sh >> $WORKSPACE/logs/x-token-refresh.log 2>&1

# ── SEO daily dashboard (07:30 UTC — GA4 + Search Console digest → #seo) ─────
30 7 * * * cd $PIPELINE && python3 seo_daily_dashboard.py >> $LOGS/seo-dashboard.log 2>&1

# ── X auto-poster (4× daily: morning, lunch, after-work, evening) ────────────
30 7,11,17,20 * * * cd $PIPELINE && python3 x_auto_poster.py >> $LOGS/x-poster.log 2>&1

# ── Daily metrics report (06:00 UTC → #metrics) ──────────────────────────────
0 6 * * * $PIPELINE/metrics_cron.sh >> $LOGS/metrics-cron.log 2>&1

# ── Lighthouse scores (09:00 UTC, after metrics) ─────────────────────────────
0 9 * * * cd $PIPELINE && python3 lighthouse_check.py >> $LOGS/lighthouse-cron.log 2>&1

# ── Daily newsletter preview (17:00 UTC) ─────────────────────────────────────
0 17 * * * cd $PROJECT && python3 pipeline/daily_briefing.py >> $LOGS/daily-briefing.log 2>&1

# ── Weekly content quality scan (Mondays 07:00 UTC → #operations) ────────────
0 7 * * 1 cd $PIPELINE && python3 validate_articles.py --all >> $LOGS/validate-cron.log 2>&1

# ── Weekly dead-link crawl (Sundays 07:00 UTC → #metrics) ────────────────────
0 7 * * 0 $PIPELINE/dead_link_cron.sh >> $LOGS/dead-link-cron.log 2>&1
```

---

## What Changed vs Previous Crontab

If you had any of these already, **replace** them:

| Old entry | Replace with |
|---|---|
| `*/15 * * * * .../auto_publish.sh` | `*/15 * * * * .../scripts/pipeline-watchdog.sh` |
| *(none)* | Add X token refresh (`*/85 * * * *`) |
| *(none)* | Add SEO dashboard (`30 7 * * *`) |
| *(none)* | Add X auto-poster (`30 7,11,17,20 * * *`) |

---

## Log Files

| Log file | Written by |
|---|---|
| `logs/watchdog.log` | `pipeline-watchdog.sh` (per-run output) |
| `logs/pipeline-failures.log` | `pipeline-watchdog.sh` (failure detail + backoff events) |
| `logs/auto_publish_*.log` | `auto_publish.sh` (timestamped per-run) |
| `logs/seo-dashboard.log` | `seo_daily_dashboard.py` |
| `logs/seo-dashboard-state.json` | `seo_daily_dashboard.py` (last run state) |
| `logs/x-poster.log` | `x_auto_poster.py` |
| `logs/x-posted.json` | `x_auto_poster.py` (posted URL dedup log) |
| `logs/metrics.json` | `run_pipeline.py` (per-run timing, 200-run rotation) |
| `logs/publish-metrics.json` | `update_publish_metrics.py` (daily publish stats) |
| `logs/metrics-cron.log` | `metrics_cron.sh` |
| `logs/lighthouse_scores.json` | `lighthouse_check.py` |
| `logs/lighthouse-cron.log` | lighthouse cron |
| `logs/daily-briefing.log` | `daily_briefing.py` |
| `logs/validation.json` | `validate_articles.py` |
| `logs/validate-cron.log` | validate cron |
| `logs/dead_links.json` | `dead_link_check.py` |
| `logs/dead-link-cron.log` | `dead_link_cron.sh` |
| `logs/rejected.json` | `pre_publish_check.py` |
| `~/workspace/logs/x-token-refresh.log` | `refresh-x-token.sh` |

---

## Environment Variables (pipeline/.env)

```bash
OPENAI_API_KEY=...
PEXELS_API_KEY=...
UNSPLASH_ACCESS_KEY=...
KIE_API_KEY=...
DISCORD_BOT_TOKEN=...           # used by seo_daily_dashboard.py for Discord posts
DISCORD_WEBHOOK_METRICS=...     # optional webhook for #metrics
DISCORD_WEBHOOK_OPS=...         # optional webhook for #operations
DISCORD_PIPELINE_WEBHOOK=...    # used by pipeline-watchdog.sh for failure alerts
```

---

## Notes

- **Watchdog:** wraps `pipeline/auto_publish.sh` with up to 5 retries and exponential backoff (30s → 60s → 120s → 300s). Sends Discord alert on hard failure. `pipeline/logs/pipeline-failures.log` has details.
- **X token:** `refresh-x-token.sh` must run more often than the 2h TTL. Every 85min is safe. Without it, the auto-poster fails with 401 after first token expiry.
- **SEO dashboard:** gracefully handles no-data periods (new GA4 property / SC lag). Will show real data after 24-72h for GA4 and 2-3 days for Search Console.
- **X auto-poster:** capped at 2 tweets per run × 4 runs/day = max 8 tweets/day, well within free tier 500/month. Deduplicates via `logs/x-posted.json`.
- **Lighthouse:** requires `npm install -g lighthouse` on host if using CLI mode. Falls back to PSI API.
- **Dead-link crawl:** limited to 300 pages to stay under 5-min runtime.
