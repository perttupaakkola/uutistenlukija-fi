# AGENTS.md — Uutistenlukija DOX

## Purpose

This repository runs `uutistenlukija.fi`, a live automated Finnish news site. Owner directive (Perttu, 2026-07-23): the goal is audience and trust growth, not monetization — grow this into an SEO-strong, trustworthy news site that real people read (10,000 GA4 page views and 1,000 active readers in the same rolling 30-day window). Treat it as a production product: publishing reliability, editorial trust, SEO/discovery, reader experience, analytics, and agent handoffs all matter. Do not start monetization/revenue experiments.

This file adapts the DOX idea from `agent0ai/dox`: keep a small hierarchy of `AGENTS.md` files so agents read the local contract before editing and update durable instructions when the project structure or workflow changes.

## Read Before Editing

1. Read `/home/pertt/.openclaw/workspace/AGENTS.md` or your specialist workspace `AGENTS.md` first.
2. Read this file before changing anything in this repository.
3. For every path you expect to touch, read the nearest child `AGENTS.md` listed in the Child DOX Index below. If a task crosses multiple areas, read all relevant child docs.
4. Re-read the chain in the current session; do not rely on memory from a prior task.
5. Do not create `AGENTS.md` under `content/`, `static/`, or `public/`: `content/` can become Hugo content, `static/` is publicly served, and `public/` is generated output.

## Project Contracts

- Linear OPE is the authoritative task board. Local files are mirrors/evidence unless a fresh Linear query fails.
- Public posting/campaigns, paid services, account/credential changes, and legal/privacy-sensitive changes still require Perttu approval.
- Routine verified site/product/pipeline fixes may be implemented, tested, committed, pushed, and deployed without a second approval round.
- Never print, commit, or expose secrets: API keys, OAuth tokens, Discord webhooks, Cloudflare tokens, Google tokens, X tokens, cookies, or auth headers.
- Do not use Anthropic or OpenRouter for agent/runtime/pipeline work. Use the configured OpenAI/Codex/OpenClaw paths unless a tracked task explicitly changes provider policy.
- Prefer reversible changes. Do not delete production artifacts broadly; archive or move aside when retention matters.
- Generated output is not source of truth: `public/`, most `pipeline/logs/`, most `pipeline/queues/`, transient screenshots, and temporary review files should not be committed unless the pipeline or task explicitly requires an artifact.

## Work Guidance

- Monetization work is paused per the owner directive above. If legacy revenue, advertising, sponsorship, affiliate, newsletter, lead-generation, commercial CTA, or monetization analytics surfaces need maintenance, read `/workspace/procedures/uutistenlukija-business-quality-loop.md` (host path: `/home/pertt/.openclaw/workspace/procedures/uutistenlukija-business-quality-loop.md`) before changing the repository.
- Felix coordinates and reviews this work; Iris owns the experiment, Monica the editorial/disclosure gate, Sara the rendered reader-experience gate, Alex implementation, and Max privacy/ops review when applicable. Do not let Felix substitute for missing specialist evidence.
- A commercial change is not ready merely because it builds or tracks clicks. Preserve editorial separation, source/Finnish-language quality, the accepted portal hierarchy, accessibility/performance, explicit disclosures, and a measurable decision rule.
- Start with `git status --short --branch`; preserve unrelated local changes and untracked queue/log files.
- Tie non-trivial work to an OPE issue or create/update one through Felix/Linear when needed.
- For code changes, make the smallest safe patch and add/adjust regression tests when behavior changes.
- For UI/design/SEO work, read `DESIGN.md` and follow the editorial design system.
- For content/editorial changes, preserve source sufficiency, attribution, Finnish quality, and no-hallucination standards.
- For analytics/business-control work, prefer local safe artifacts and explicit `blocked/stale/fresh` states over stale `null` values.
- GA4/Search Console auth is durable through the host-only service account `uutistenlukija-analytics-reade@leafy-star-490910-t5.iam.gserviceaccount.com`; do not ask Perttu for OAuth unless host verification fails. Team agents should use the safe snapshot at `/workspace/reports/uutistenlukija-analytics/` (or the same path under their host workspace) and must not copy `.secrets` or service-account keys into sandboxes.
- After meaningful changes, do a DOX pass: update this file or the nearest child `AGENTS.md` only if a durable contract, path ownership, workflow, verification rule, or child index changed. Do not add diary/status notes.

## Verification

Use the checks relevant to the changed area and report real output:

- Hugo/UI/templates: `scripts/verify_hugo.sh OPE-NNN`. To inspect generated output before successful cleanup, append `-- <verification command>` and read `$HUGO_OUTPUT_DIR` in that command. Failed builds/checks remain at `/tmp/opeNNN-hugo-build` for diagnosis.
- Template contract: `bash scripts/validate_templates.sh`
- Portal CSS: `python3 scripts/validate_portal_css_contract.py`
- Frontmatter: `python3 pipeline/validate_frontmatter.py`
- Pipeline health: `python3 pipeline/health_check.py`
- Project cron health: `python3 scripts/cron_health_monitor.py --dry-run`
- Business panel: `python3 scripts/business_control_panel.py --dry-run` plus `python3 -m unittest scripts/test_business_control_panel.py`
- Python edits: `python3 -m py_compile <changed files>` and targeted unit tests.

## Child DOX Index

- `.github/AGENTS.md` — GitHub Actions deploy and alert workflows.
- `docs/AGENTS.md` — durable docs, runbooks, plans, and research notes.
- `layouts/AGENTS.md` — Hugo templates and public UI markup.
- `pipeline/AGENTS.md` — scanners, writers, publishers, queues, logs, metrics, and cron pipeline behavior.
- `scripts/AGENTS.md` — operator scripts, validators, dashboards, reports, and local utilities.
- `themes/uutistenlukija/AGENTS.md` — theme CSS/JS/layout files and design-system implementation.
