# AGENTS.md — Pipeline

## Purpose

`pipeline/` owns automated news ingestion, enrichment, writing, staging, publishing, metrics, health checks, queue retention, and cron-facing operations for `uutistenlukija.fi`.

## Ownership

- Monica owns writer/editor/research quality concerns.
- Alex owns implementation changes.
- Max owns reliability, queue hygiene, monitoring, and secrets-safe operations.
- Felix coordinates through Linear OPE and verifies evidence.

## Local Contracts

- Treat the pipeline as production: fail closed rather than publishing thin, unsourced, duplicate, or hallucinated articles.
- Preserve Finnish editorial quality, source attribution, source sufficiency, duplicate suppression, and category balance.
- Do not commit most `logs/`, `queues/`, lock files, or runtime artifacts. Commit only durable source, public/static status JSON intentionally generated for the site, metrics artifacts explicitly tracked by the pipeline, or small evidence fixtures required by tests.
- Never print or commit `.env`, webhook URLs, API keys, OAuth tokens, cookies, or bearer headers. Use wrappers such as `scripts/run_with_project_env.sh` when a cron/reporting script needs environment variables.
- Firehose credentials must come from `FIREHOSE_TOKEN` in the runtime environment, never source. The supplementary local source skips cleanly when absent. Until the historically exposed credential is rotated and separately reviewed, the Actions staged-scan workflow intentionally runs RSS/public-research only and must not inject `FIREHOSE_TOKEN`.
- Before changing yield/classification behavior, reproduce with real logs or packets where possible and add a targeted regression test.
- Queue cleanup must be reversible or manifest-backed unless deleting clearly generated throwaway artifacts under an approved retention rule.

## Work Guidance

- Check recent logs before patching from a hunch: `pipeline/logs/staged-scan.log`, `pipeline/logs/staged-monica-worker.log`, `pipeline/logs/staged-publish.log`, `pipeline/logs/metrics.json`, and relevant `auto_publish_*.log` if present.
- For source/category guardrails, distinguish weak promotional copy from legitimate source-backed news.
- For Discord/webhook reporting, include a non-empty `User-Agent` in Python `urllib.request.Request` calls.
- For business-control metrics, surface `fresh`, `stale`, or `blocked` states with non-secret evidence instead of hiding unavailable metrics.

## Verification

Use the narrowest real checks that match the change:

- `python3 -m py_compile <changed pipeline .py files>`
- `python3 pipeline/health_check.py`
- `python3 scripts/cron_health_monitor.py --dry-run`
- `python3 pipeline/validate_frontmatter.py` when content/frontmatter generation changes.
- Relevant targeted tests or dry-runs for scanner, publisher, staged worker, business-control, or retention changes.

## Child DOX Index

No child `AGENTS.md` files are currently required here. Keep queue/log rules in this file unless a durable sub-area develops its own workflow.
