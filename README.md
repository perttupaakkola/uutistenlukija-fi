# Uutistenlukija MVP

Fresh Finnish news: one Python controller, SQLite, sequential writer/reviewer
prompts, static pages, and one Cloudflare Pages deployment workflow. Uses the
installed shared Hermes runtime and existing Codex OAuth in the news-mvp profile.
No legacy website data, news queues, agent memories or old pipeline is loaded.

The systemd timer calls:

```
/home/pertt/.hermes/hermes-agent/venv/bin/python -B -m news_mvp live-tick --config config.json
```

The same scheduled controller discovers at most five recent image reports from
NASA's MODIS gallery, admits at most one per tick and fetches the source, exact
page image and NASA permission evidence automatically. Article date, capture date,
image filename/title and exact NASA GSFC credit must match; unsupported or stale
items are skipped. Terminal rejected/failed/deployed items cannot starve later news.
This is one initial allowlisted family, not a change to the broader Finnish news
product's purpose. No old backlog or hand-maintained per-article list is required.

One SQLite jobs table stores drafts/reviews; a publications table binds packet,
draft, image, source commit, remote commit, Actions run and live deployment. A
completed source returns idle before fetching, committing or dispatching again.
A dispatch recorded before its HTTP request is never automatically repeated if
run visibility is delayed. Inspect the run before manually resolving a failed or
ambiguous dispatch. No automatic publication retry after an uncertain failure.

State: `/home/pertt/.local/share/uutistenlukija`. Actual public output is ONLY
`live-site/`. The abandoned `public-history/` residual is excluded and unused; its
collector is stopped. Its eventual disposition belongs to a later guarded step.
The `cutover/` files remain exact reviewed phase4 evidence; the historical-site
requirements in them were superseded by CONTROL revision7 and the owner amendment.
The active executor is `ops/deploy.yml`, installed at the existing repository's
`.github/workflows/deploy.yml`, targeting the existing uutistenlukija-fi project.
It has no Actions schedule. Existing repository history remains remote; the new
release uploads only the fresh `public/` tree. Local implementation does not clone
or import that repository.

Stop admission and publication with `python -B -m news_mvp stop --config config.json`.
The timer can remain installed; stopped ticks do nothing. During this migration,
public writes also require the current CONTROL/review gate and committed source.
The 15-minute timer discovers current allowlisted source items. Step5 verification temporarily
uses a one-minute interval on the SAME timer, then restores 15 minutes.

Public pages include source links, exact image credit/date/permission, canonical
URLs, sitemap, an actual 404 page and Finnish consent controls. GA4 G-35XERS8V6J
loads only on the canonical origin after affirmative cookie_consent_v2 consent.
Private previews never send analytics. Existing personal helpers and the analytics
exporter are retained; old news publishing schedules are stopped. The runtime's
system-owned old-news skill reviews are disabled by the supported
`skills.workshop.autonomous.mode=off` setting, with no gateway restart.

Checks: `python -B -m unittest discover -s tests -v` and the offline consent test
`node tests/test_analytics.cjs`. Fixture mode is refused by live scheduling and
public rendering. Phase receipts live in the separate Hermes plan directory.

Steady-state transition is PREPARED ONLY. `authorization_mode` defaults to
`migration`, retaining CONTROL step/deadline/stop checks. After independent review,
the operator can install `state_dir/steady-state-policy.json` for the exact source
commit, fill its Hermes review reference/approval, set its enabled flag and switch
config to `steady_state`. The proposal is disabled and is NOT that activation file.
The steady-state branch uses only that explicit policy and the controller stop
switch; it does not read the migration bundle. Source commit, family, freshness,
limits, origin and executor are pinned; any source change needs renewed policy
approval. Keep the same 15-minute timer. Setting config enabled=false or policy
enabled=false stops publication. No transition has been activated in step5.

The step5 correction sets a temporary migration_publication_limit of two total
publications (the existing article plus one unattended canary). It blocks further
new admission at the review gate. This migration-only cap is not applied by the
separately approved steady-state policy; that transition remains unactivated.
