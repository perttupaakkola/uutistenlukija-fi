# CRON.md — Scheduled Pipeline Jobs

All times UTC. See the live crontab for exact entries (`crontab -l`).

Last updated: 2026-03-26

## Every minute
- **kill-rogue-gateways.sh** — kill leaked openclaw-gateway processes
- **config-guard.sh** — enforce openclaw config integrity

## Every 5 minutes
- **sync-taskboard.sh** — sync TASKBOARD.md changes
- **refresh-anthropic-token.sh** — keep Anthropic OAuth token fresh

## Every 10 minutes
- **auto_publish.sh** — scan RSS → dedup → research → rewrite → publish → Hugo build → push
- **cleanup-sandboxes.sh** — clean up idle Docker sandbox containers
- **host-bridge.sh** — sync agent workspace changes to main repo
- **host_apply_bridge_requests.sh** — apply pending bridge write requests
- **firehose_cron.sh** — fetch new articles from Firehose/RSS feeds
- **check-github-actions.sh** — monitor GitHub Actions for failures

## Every 15 minutes
- **health_monitor.sh** — check pipeline health, alert #operations if degraded
- **cleanup-browser-tabs.sh** — close stale browser tabs

## Every 30 minutes
- **session-cleanup.sh** — clean up idle OpenClaw sessions
- **task-watchdog.sh** — check agent tasks for timeouts

## Every 45 minutes
- **refresh-search-console-token.sh** — refresh Google Search Console OAuth token

## Every 90 minutes
- **refresh-x-token.sh** — refresh X/Twitter OAuth2 token

## Hourly/6-hourly
- **15min past every 6h** — check-analytics.sh (Google Analytics data pull)
- **Every 6h** — disk_monitor.sh (disk usage check, alert if >80%)

## Daily
- **02:00** — content_backup.py (export articles to JSON, keep 7 days)
- **05:00** — rss_health.py (RSS feed health report)
- **06:00** — metrics_cron.sh (pipeline metrics summary to #metrics)
- **06:05** — metrics_history.py (aggregate run data into metrics_history.json)
- **18:00** — generate_digest.py (auto päivän kooste article)

## Weekly
- **Monday 07:00** — weekly_digest.py (week-over-week stats to #metrics)
- **Sunday 06:00** — rotate_logs.sh (archive logs >7d, delete archive >30d)
- **Sunday 07:00** — dead_link_cron.sh (dead link checker scan)
- **Sunday 07:30** — validate_articles.py (article quality validation audit)

## X/Twitter posting
- **07:30 and 11:30 UTC daily** — x_auto_poster.py
- **17:00 and 20:00 UTC daily** — x_auto_poster.py

## TODO / Planned
- pipeline-watchdog.sh — auto-restart on crash (not yet in crontab)
- weekly-ops-report.sh — weekly ops summary to #operations (script exists, not yet scheduled)
- pipeline-status.sh — on-demand status tool (script exists, not scheduled)
