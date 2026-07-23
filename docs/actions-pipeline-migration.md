# Pipeline → GitHub Actions migration (owner directive, Perttu, 2026-07-23)

## Goal

The VPS keeps only the agent layer (OpenClaw gateway + Felix/Alex/Monica/Sara + Hermes).
Everything deterministic moves to GitHub Actions scheduled workflows. The repo is the
message bus: `pipeline/queues/staged/` state is committed, so stages on different
machines coordinate through git. End-state VPS: ~10-12G disk, ~2-3G standing RAM.

Repo is public → Actions minutes are unlimited. Cloudflare Pages deploy secrets
(`CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`) and `DISCORD_PIPELINE_WEBHOOK`
already exist as repo secrets, so this extends an established pattern.

Key mechanic: pushes made with the default `GITHUB_TOKEN` do NOT trigger other
workflows, so `deploy.yml` will not fire for workflow pushes. The Actions pipeline
workflows therefore build + deploy themselves. `deploy.yml` remains for human/agent
pushes from the VPS.

## Phase 1 — publish + kooste (workflows shipped 2026-07-23, gated)

- `.github/workflows/staged-publish.yml` — every 15 min: publish up to 3 outbox
  packets, build, deploy. Replaces the quiesced VPS `uutis-staged-publish` cron and
  resolves OPE-448's root cause (heavy local Hugo builds on the VPS) structurally.
- `.github/workflows/daily-kooste.yml` — 18:00 UTC: generate kooste, push, build, deploy.
- Both are inert on schedule until the marker file `pipeline/actions-publish.enabled`
  is committed. `workflow_dispatch` always runs (use for a supervised first run).

### Cutover checklist (Felix/Alex, ~30 min)

1. Optional but recommended — image enrichment secrets, from the VPS
   (`gh auth login` as repo admin first). Without these, published articles use
   category-fallback images (pipeline degrades gracefully):
   ```bash
   cd ~/.openclaw/workspace/projects/uutistenlukija
   for k in OPENAI_API_KEY PEXELS_API_KEY UNSPLASH_ACCESS_KEY KIE_API_KEY; do
     gh secret set "$k" --body "$(grep "^$k=" .env | cut -d= -f2-)"
   done
   ```
2. Decide the stale-backlog policy. `pipeline/queues/staged/outbox/` holds ~142
   packets written before the 2026-07-20 pause; several days old is not news.
   Recommended: archive packets older than 48h to `failed_archive/` with reason
   `stale-backlog-20260723`, publish the rest via the 3-per-run trickle.
3. Run one supervised max-1 publish:
   - Preferred when authenticated Actions control is available: use
     `workflow_dispatch` with `max_articles=1`, then verify the run before
     enabling schedules.
   - Git-only fallback: commit the marker in step 4. A push adding
     `pipeline/actions-publish.enabled` triggers exactly one article immediately;
     queue/marker-only pushes are ignored by `deploy.yml`, avoiding a concurrent
     old-build deploy race.
   Verify: run green, article live on the site, packet moved to `published/`.
4. Commit only the marker and reviewed queue archive paths (do not use broad
   `git add -A` in a dirty checkout):
   `touch pipeline/actions-publish.enabled && git add pipeline/actions-publish.enabled pipeline/queues/staged && git commit -m "Enable Actions publish cutover" && git push`.
5. On the VPS crontab: the `uutis-staged-publish` line stays commented (now
   permanently — annotate it "MIGRATED to GitHub Actions 2026-07"), and comment out
   the `0 18 * * *` kooste line the same way. Do NOT re-enable them after OPE-465.
6. Watch two scheduled cycles. Failure alerts: extend
   `deploy-failure-alert.yml` `workflows:` list with "Staged publish" and
   "Daily kooste" so Discord gets failures from these too.

## Phase 2 — scan (needs research-source keys)

`staged_publish.py scan` is stdlib + `scanner.py`/`firehose.py` (urllib). Add a
15-min scheduled workflow running `scan --max-packets 1 ...` with the same flags as
the old `uutis-staged-scan` safe-job-runner line (drop the CPU/disk guards — the
runner is ephemeral). Queue writes land in `queues/staged/ready/` and are committed
by the workflow (`git add pipeline/queues/staged && commit && pull --rebase && push`).
Check `scanner.py`/`research` for any API keys read from `.env` and mirror them as
secrets first.

## Phase 3 — metrics, reports, monitors (needs GA4/SC + Discord secrets)

The daily/weekly report crons (`metrics_cron.sh`, `fetch_search_console.py`,
`daily_traffic_card.py`, `ctr_gap_report.py`, weekly digests, `rss_health.py`,
`dead_link_cron.sh`, `validate_articles.py`, …) are pure scripts. One
`reports.yml` workflow with a schedule matrix replaces them. Requires: GA4/SC
service-account JSON as a secret (`GOOGLE_APPLICATION_CREDENTIALS` written at
runtime), plus `DISCORD_METRICS_WEBHOOK` / `DISCORD_OPERATIONS_WEBHOOK`.
Health/uptime monitors that check the live site (`uptime_monitor.sh`,
`monitor_deploys.sh`) can move as-is; retire the VPS-local disk/load monitors —
they monitor a machine the pipeline no longer runs on.

## Phase 4 — X auto-poster

`x_auto_poster.py` 6×/day; needs the X token set (see
`workspace/scripts/refresh-x-token.sh` — the refresh flow must also move or tokens
must be long-lived). Migrate last; low risk if it lags.

## What stays on the VPS (by design)

- The Monica writer lane (`staged_publish.py monica-worker`): it drives an OpenClaw
  agent session — it IS the agent layer. It consumes `ready/` and fills `outbox/`
  through git (`pull --rebase` before, `push` after each packet batch).
- Felix/Alex/Monica/Sara editorial + coordination sessions, Hermes.
- `openclaw-backup` (scope shrinks as pipeline state now lives in git/Actions).

## End-state VPS crontab

Gateway maintenance (config-guard, rogue-killer, sandbox cleanup, session cleanup,
memory archive, tmp janitor), monica-worker lane, token refreshers still needed by
agents, backups. Everything else → Actions. Target: crontab under 15 lines.
