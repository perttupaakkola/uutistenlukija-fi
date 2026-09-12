Step 4 preparation only. None of these scripts is installed or run against live services.
Forward stop/repoint requires CONTROL step 5, unexpired deadline and no stop request.
The gate binds every reviewed cutover file to its approved Git blob in both HEAD
and the working tree; ordinary committed step5 descendants are allowed. Dirty or
committed changes to those files are refused. Restoration has the separate narrow
gate described below; no review file needs editing to accept descendant work.

Canonical source: /home/pertt/work/uutistenlukija. Sole state:
/home/pertt/.local/share/uutistenlukija. Shared installed Hermes Python, news-mvp
profile and existing Codex OAuth remain unchanged. Public destination remains
perttupaakkola/uutistenlukija-fi main -> .github/workflows/deploy.yml -> existing
Cloudflare Pages project uutistenlukija-fi -> https://uutistenlukija.fi/.
No alternate project, domain, credential or runtime installation.

Step 5 execution sequence (requires its release)

1. Read CONTROL and the independent review. Recheck routes.json against current
   crontab, exact OpenClaw news job enabled flags, listed unit states, four Actions
   workflow states and remote main. Drift needs reconciliation before running;
   never replay stale enable flags. Preserve a small before-state receipt for only
   these touched schedules and deployment IDs. No old queues or role imports.
2. Run `bash cutover/stop-legacy.sh`. It comments 35 exact crontab news lines,
   disables 12 previously enabled OpenClaw news jobs and four publishing/scan
   workflows, stops seven news units, and adds four news-only service conditions
   so shared health helpers cannot restart those services. Existing disabled news
   jobs stay disabled. The crontab transformation preserves all other bytes.
3. Disabling schedules does not cancel running work. Inspect exact news processes
   from the existing inventory (host bridge, staged Monica, current_main_job,
   staged pipeline recovery) and Actions runs for these four workflow IDs.
   Drain them; if cancellation is needed, target only the observed news run/PID.
   Do not kill the shared gateways or whole Node/Python process families. Record
   zero active legacy news writers and remote head after drain in
   cutover/drain-verified.json. Do not advance if a writer remains.
4. Freeze the deployed public DATA, including all historical URLs, media,
   redirects, RSS, sitemap, verification files and existing consent behavior.
   `continuity.py baseline SITEMAP PUBLIC_DATA_DIR` requires all URLs present;
   `continuity.py verify MANIFEST RELEASE_DIR` rejects missing or changed history.
   The sampled old public directory is NOT complete (see phase4 coverage receipt).
   Never use it alone as a Pages replacement. Fetch missing public data through
   public HTTP; do not run the old generator or import its queues/agents.
   Validate local asset references too. The new homepage is the only baseline
   page allowed to change; historical pages stay at original /posts/... paths.
   Keep the old content/history and media canonical source in place through review.
5. Compose complete static public data plus the reviewed real new article in a
   private release directory. Remove private labels only in the public rendering
   variant, refuse fixture articles, bind its exact file hashes in release.json,
   and review that private release. `check_release.py` checks this exact bundle.
   Preserve historical sitemap URLs and add the new /uutiset/<stable-id>/ URL.
   Record continuity/asset/HTTP checks in public-continuity-verified.json.
6. Stage fresh source and complete public data into the EXISTING remote repository
   as a normal non-force main commit with deploy disabled; no old runtime code
   copied into fresh source. Replace deploy.yml with deploy.yml.template. Keep
   staged-publish, staged-scan and daily-kooste disabled. Adapt source-validation
   to these focused checks and retain the read-only deploy failure alert. Record
   actual remote release commit. Existing GitHub secrets stay in GitHub.
7. `bash cutover/repoint.sh` enables only the replacement deploy executor and
   dispatches it on current main. Verify the actual resulting Pages deployment,
   homepage/article/history/canonical URLs and no private/fixture content. Only
   after that install the single prepared MVP timer and enable the controller.
   Controller integration must dispatch this same executor only when new reviewed
   output exists; repeated idle ticks must not create commits/deploy requests.
   No second scheduler in Actions. This wiring/activation belongs to step 5.

Minimal rollback

Before repoint: rollback-before-repoint.sh permits restoration even after expiry
or stop_requested. It requires unchanged approved cutover code, a matching JSON
stop.finished receipt binding stop.started and both crontab snapshots, no
repoint.started, disabled MVP config and inactive/disabled MVP service/timer.
The four remote workflows must still be disabled with the exact legacy blobs
captured before stop; replacing their executor code also bars this inverse.
stop.finished is written only after all stop commands succeed under set -e. It restores only selected crontab lines, previously enabled
news job/workflow flags and news timers; removes only its four new drop-ins.
For a partial stop failure, inspect the transcript and reverse only successful
commands using that script's exact inverse commands. Do not replay whole job DBs.
After repoint: first disable the MVP controller/timer and replacement deploy
workflow; leave legacy schedules OFF. Restore the previously recorded successful
Cloudflare Pages deployment via the existing project rollback control, then
verify its exact deployment ID and historical URL responses. Restore the touched
workflow config from the pre-cutover Git commit as a normal reviewed commit,
never reset/force-push or restore old data wholesale. Re-enable old schedules only
if explicitly choosing full rollback and the new executor is confirmed stopped.
No two publishers may overlap. No article/job rows are deleted during rollback.

Personal dependency boundary

Keep every Hermes job, memory, state DB, browser, gateway, shared runtime and auth.
Keep OpenClaw personal jobs and gateways. Preserve Search Console/X token refresh
and the read-only analytics team snapshot exporter in the crontab. The old
analytics scripts, .secrets paths and static/api data remain for those consumers;
retirement is a later gate. No ads activation or X campaign is added.
Shared updater/health/self-edit helpers remain installed and scheduled. The
news-only service conditions fence their service restarts; arbitrary authorized
self-edit commands could still change cron/workflows, so a restart is not proof
against intentional future configuration changes. Check their pending requests
for news re-enablement before activation; never wholesale-disable personal helpers.

Analytics continuity

Live GA4 measurement ID G-35XERS8V6J and consent key cookie_consent_v2 remain.
Existing consent schema is {v:2,necessary:true,analytics:boolean,advertising:boolean}.
analytics.js is a fresh public-only template, disabled unless the canonical origin
and affirmative analytics consent are both present. The public page needs Finnish
accept/reject/settings controls wired to newsAnalyticsConsent; old historical
pages retain their existing consent UI. Revocation reloads the page. Private
previews never include this script. Existing GA4/Search Console property/history
and token files are retained; no synthetic analytics events or token reads needed.
Preserve 30-day reporting targets: 10,000 pageviews and 1,000 active users.
