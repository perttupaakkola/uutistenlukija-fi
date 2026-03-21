# Pipeline Cron Schedule

All times UTC. All scripts assume `.env` is co-located in `pipeline/` and source it at startup.

## Active Jobs

| Schedule | Script | Purpose | Discord target |
|---|---|---|---|
| `*/15 * * * *` | `scripts/pipeline-watchdog.sh` | Watchdog wrapper → auto_publish.sh (auto-retry with backoff) | #operations (on failure) |
| `30 7 * * *` | `seo_daily_dashboard.py` | Daily SEO digest: GA4 + Search Console | #seo |
| `30 7,11,17,20 * * *` | `x_auto_poster.py` | Post recent articles to @Uutistenlukija_ (3-4/day) | X/Twitter |
| `*/85 * * * *` | `scripts/refresh-x-token.sh` | Refresh X OAuth2 token (2h TTL) | — |
| `0 6 * * *` | `metrics_cron.sh` | Daily pipeline metrics report | #metrics |
| `0 9 * * *` | `lighthouse_check.py` | Lighthouse scores + delta tracking | #metrics |
| `0 7 * * 1` | `validate_articles.py --all` | Weekly content quality health score | #operations |
| `0 7 * * 0` | `dead_link_cron.sh` | Weekly dead-link crawl | #metrics |

## Install (on deploy host)

Run `crontab -e` and add:

```cron
# ── uutistenlukija pipeline ────────────────────────────────────────────────
PIPELINE=/path/to/projects/uutistenlukija/pipeline

# Main pipeline — every 15 min (via watchdog for auto-retry)
*/15 * * * * $PROJECT/scripts/pipeline-watchdog.sh >> $PIPELINE/logs/watchdog.log 2>&1

# Daily metrics report — 06:00 UTC
0 6 * * * $PIPELINE/metrics_cron.sh >> $PIPELINE/logs/metrics-cron.log 2>&1

# Lighthouse scores — 09:00 UTC (after metrics)
0 9 * * * cd $PIPELINE && python3 lighthouse_check.py >> $PIPELINE/logs/lighthouse-cron.log 2>&1

# Weekly content quality — Mondays 07:00 UTC
0 7 * * 1 cd $PIPELINE && python3 validate_articles.py --all >> $PIPELINE/logs/validate-cron.log 2>&1

# Weekly dead-link crawl — Sundays 07:00 UTC
0 7 * * 0 $PIPELINE/dead_link_cron.sh >> $PIPELINE/logs/dead-link-cron.log 2>&1
```

Replace paths with absolute paths on the host. Example for default install:
- `PROJECT=/home/pertt/.openclaw/workspace/projects/uutistenlukija`
- `PIPELINE=$PROJECT/pipeline`

## Log Files

All jobs append to `pipeline/logs/`. Log rotation is handled per-script for JSON history files.
Raw shell logs may be rotated with `logrotate` if they grow large.

| Log file | Written by |
|---|---|
| `logs/watchdog.log` | `pipeline-watchdog.sh` (cron entry) |
| `logs/pipeline-failures.log` | `pipeline-watchdog.sh` (failure detail) |
| `logs/auto_publish.log` | `auto_publish.sh` |
| `logs/metrics.json` | `run_pipeline.py` (per-run timing) |
| `logs/metrics-cron.log` | `metrics_cron.sh` |
| `logs/lighthouse_scores.json` | `lighthouse_check.py` |
| `logs/lighthouse-cron.log` | lighthouse cron |
| `logs/validation.json` | `validate_articles.py` |
| `logs/validate-cron.log` | validate cron |
| `logs/dead_links.json` | `dead_link_check.py` |
| `logs/dead-link-cron.log` | `dead_link_cron.sh` |
| `logs/rejected.json` | `pre_publish_check.py` |

## Environment Variables Required

Stored in `pipeline/.env` (not committed):

```bash
OPENAI_API_KEY=...
PEXELS_API_KEY=...
UNSPLASH_ACCESS_KEY=...
KIE_API_KEY=...
DISCORD_BOT_TOKEN=...          # for Discord posts from scripts
DISCORD_WEBHOOK_METRICS=...    # optional: webhook for #metrics channel
DISCORD_WEBHOOK_OPS=...        # optional: webhook for #operations channel
```

## Notes

- `auto_publish.sh` runs `pre_publish_check.py` as step 3/4 — articles failing the quality gate (no image, thin content) are un-staged and skipped, not blocking the deploy.
- `lighthouse_check.py` requires `npm install -g lighthouse` on the host (or a Lighthouse CI service endpoint — see script header).
- `dead_link_cron.sh` limits crawl to 300 pages to stay under 5 min runtime.
- `validate_articles.py --all` scans the full content dir (currently ~620 articles, takes ~5s).
