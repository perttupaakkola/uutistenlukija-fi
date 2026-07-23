# CRON.md — Scheduled Pipeline Jobs

All times UTC. Last synced from live `crontab -l` on 2026-07-23 for disk monitor schedule.

---

## Every 5 minutes
- **monitor_deploys.sh** — watch Cloudflare Pages deploy status → deploy-monitor.log

## Every 10 minutes
- **firehose_cron.sh** — fetch new articles from Firehose stream → firehose_cron.log
- **watchdog.sh** — check pipeline health, restart if stalled → watchdog.log

## Every 15 minutes
- **health_monitor.sh** — curl /api/health.json, alert on degraded/stale (06:00–22:00 UTC window) → health-monitor.log
- **uptime_monitor.sh** — HTTP status + response time check, Discord alert on failure or >5s (30min cooldown) → uptime-monitor.log

## Every 30 minutes
- **pipeline-health-check.sh --alert-only** → health-check.log

## Every 6 hours
- **:00** — check_pipeline_silence.sh (alert if no publish in 6h) → pipeline-silence.log
- **:00** — scripts/disk_space_monitor.sh --no-alert (status-only; thresholds remain 80%/90%) → data/disk_space_status.json; warnings/errors also append to disk_monitor.log
  - Live crontab should contain only this canonical Uutistenlukija status-writer entry. The user-systemd watchdog is the sole Discord disk-alert writer.
  - Legacy path `pipeline/disk_monitor.sh` remains as a manual/backward-compatible wrapper, but is not scheduled.
- **:15** — check-analytics.sh → analytics.log

## Daily
- **02:00** — content_backup.py → content-backup.log
- **05:00** — rss_health.py (RSS feed health check) → rss-health.log
- **06:00** — metrics_cron.sh (pipeline metrics summary) → metrics-cron.log
- **06:05** — metrics_history.py (aggregate run data) → metrics_history.log
- **06:10** — pipeline_error_tracker.py (parse cron.log, rolling 30-day errors JSON) → pipeline-error-tracker.log
- **06:30** — fetch_search_console.py (pull GSC data → static/api/search-console-data.json) → fetch-search-console.log
- **07:00** — source_stats.py (per-source article counts to Discord) → source-stats.log
- **07:00** — daily_traffic_card.py (GA4 yesterday card) → daily-traffic-card.log
- **07:30** — category_distribution.py --post-discord (category balance → category-stats.json + Discord) → category-distribution.log
- **17:00** — daily_briefing.py (writes static/newsletter/daily-YYYY-MM-DD.html) → daily-briefing.log
- **17:00 + 20:00** — x_auto_poster.py (auto-post to @Uutistenlukija_) → x-poster.log
- **18:00** — generate_digest.py + git push (päivän kooste) → (no log)

## Weekly
- **Sunday 06:00** — rotate_logs.sh (archive logs >7d, delete archive >30d) → rotate_logs.log
- **Sunday 07:00** — dead_link_cron.sh (scan for dead outbound links) → dead-link-cron.log
- **Sunday 07:30** — validate_articles.py (full article quality validation) → validate-articles.log
- **Sunday 20:00** — weekly-ops-report.sh --post → weekly-ops-report.log
- **Monday 06:00** — feed_health_report.py --live (feed health to #operations) → feed-health.log
- **Monday 07:00** — weekly_digest.py (week-over-week stats to #metrics) → weekly_digest.log
- **Monday 07:00** — weekly-metrics-digest.py (GA4 weekly digest to #metrics) → weekly-metrics-digest.log
- **Monday 08:00** — ctr_gap_report.py --post-discord (CTR gap report to #metrics) → ctr-gap-report.log
- **Monday 08:00** — weekly_top_articles.py (top articles by pageviews) → weekly-top-articles.log
- **Monday 09:05** — pipeline_error_weekly_report.py (weekly error summary to Discord) → pipeline-error-weekly.log

## OpenClaw System Crons (not in project crons.txt)
~21 additional entries for OpenClaw gateway maintenance (session cleanup, token refresh, task watchdog, GitHub Actions check, etc.)

---

**Total project crons:** 30 entries  
**Note:** auto_publish.sh runs via `watchdog.sh` trigger (every 10min), not a direct cron entry.
