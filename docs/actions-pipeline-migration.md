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

- `.github/workflows/staged-publish.yml` — every 15 min at staggered UTC minutes
  `13,28,43,58`: publish up to 3 outbox packets, build, deploy. The stagger avoids
  common quarter-hour contention because GitHub documents that scheduled events
  can be delayed or dropped under load. Replaces the quiesced VPS
  `uutis-staged-publish` cron and resolves OPE-448's root cause (heavy local Hugo
  builds on the VPS) structurally.
- `.github/workflows/daily-kooste.yml` — 18:07 UTC: generate kooste, push, build,
  deploy. The seven-minute offset avoids GitHub's documented top-of-hour load
  while replacing the prior 18:00 VPS cron.
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
     old-build deploy race. A later `staged-publish.yml` repair also triggers a
     max-1 retry while the marker exists.
   - The staged workflow gives the publisher's full-archive Hugo pre-commit build
     a 600-second bound. The original 180-second VPS default is too short on a
     clean GitHub runner; the same output is validated again before Pages deploy.
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

## Phase 2 — scan (marker-gated)

- `.github/workflows/staged-scan.yml` runs at staggered UTC minutes
  `01,16,31,46`. Scheduled runs are inert until
  `pipeline/actions-scan.enabled` is committed; manual dispatch bypasses the
  marker for the supervised canary only.
- The scan command keeps the accepted paused VPS flags exactly:
  `scan --max-packets 1 --max-research-candidates 8 --dedup-window 48
  --max-ready-backlog 150 --max-ready-age-hours 24`. The old CPU/disk guards
  are omitted on the ephemeral runner, while the prior 240-second execution
  bound is retained.
- Firehose is supplementary but credentialed. Configure only the
  `FIREHOSE_TOKEN` GitHub Secret. `firehose.py` reads it from the environment,
  never source or logs; the Actions job fails before scanning when it is absent.
  RSS and research extraction remain stdlib/public-endpoint code.
- The workflow validates a manual canary as exactly one new packet with the
  staged schema, matching packet ID, usable source provenance, and a SHA-256
  manifest. It stages only `pipeline/queues/staged`, checks the staged diff,
  commits, rebases on `origin/main`, and pushes. Queue-only pushes remain ignored
  by `deploy.yml`.

### Phase 2 canary and enablement

1. Merge the workflow while `pipeline/actions-scan.enabled` is absent. Confirm
   the VPS `uutis-staged-scan` and `uutis-monica-worker` declarations remain
   commented.
2. Dispatch `Staged scan` once. Record the Actions run ID and the queue
   pre/post counts plus manifest from the run summary. The run must add exactly
   one valid `ready/` packet.
3. Commit the empty `pipeline/actions-scan.enabled` marker to enable the
   staggered schedule. Do not resume the Monica worker here; that is a separate
   Max restoration decision at the verified ready-packet boundary.

Rollback is independent of publishing: remove
`pipeline/actions-scan.enabled` to stop scheduled scans, and revert
`.github/workflows/staged-scan.yml` if the workflow itself must be removed.
Neither action changes `pipeline/actions-publish.enabled`,
`.github/workflows/staged-publish.yml`, or the current publisher.

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
