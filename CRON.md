# CRON.md — Scheduled Pipeline Jobs

All times UTC. See the live crontab for exact entries.

## Every 15 minutes
- **auto_publish.sh** — scan → rewrite → publish → build → push
- **health_monitor.sh** — curl /api/health.json, alert #operations on degraded
- **uptime_monitor.sh** — HTTP status + response time check for uutistenlukija.fi, Discord alert on failure or >5s response (30min cooldown)

## Every 10 minutes
- **firehose** — fetch new articles from RSS feeds

## Every 6 hours
- **disk_monitor.sh** — check disk usage, alert #operations if >80%

## Daily
- **06:00** — metrics_cron (pipeline metrics summary)
- **06:05** — metrics_history.py (aggregate run data into metrics_history.json)
- **17:00** — daily_briefing.py (writes `static/newsletter/daily-YYYY-MM-DD.html` preview for Päivän kooste)
- **18:00** — daily digest post to Discord

## Weekly
- **Monday 07:00** — weekly_digest.py (week-over-week stats to #metrics)
- **Monday 08:00** — weekly_top_articles.py (top 5 articles by pageviews to #metrics)
- **Monday 07:05** — feed_health.py --weekly-summary (feed health report to #operations via Discord webhook)
- **Every pipeline run** — generate_pipeline_status.py (writes static/api/pipeline-status.json for /tila/ live widget)
- **Sunday 06:00** — rotate_logs.sh (archive logs >7d, delete archive >30d)

## System / Maintenance
- kill-rogue-gateways
- cleanup-sandboxes
- session-cleanup
- task-watchdog
- sync-taskboard
- refresh-anthropic-token
- check-github-actions (every 10 min)

## Added 2026-03-28
- **06:30 daily** — fetch_search_console.py (pull GSC data → search-console-data.json)
- **07:30 daily** — category_distribution.py --post-discord (category balance report)
