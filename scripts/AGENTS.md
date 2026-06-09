# AGENTS.md — Scripts

## Purpose

`scripts/` contains operator utilities, validators, dashboards, reporting jobs, SEO/business helpers, and maintenance scripts that support the live newspaper business.

## Ownership

- Max owns reliability/ops/security scripts.
- Alex owns implementation and regression-test changes.
- Sara owns design/SEO validators and specs when the script enforces UI/search contracts.
- Iris owns growth/marketing metrics scripts when assigned through Linear.

## Local Contracts

- Prefer deterministic script logic for monitoring and reporting; do not route simple checks through an LLM when a script can decide safely.
- Scripts that may be run by cron should be idempotent, bounded, and explicit about dry-run vs write mode.
- Never print secrets. Redact paths or command strings that could expose token files, webhook URLs, API keys, bearer headers, cookies, or OAuth material.
- Public JSON generators must mark output as safe/public and must not read private token files unless the whole script is explicitly private.
- Keep script output compact and machine-readable where another agent/cron job consumes it.

## Work Guidance

- Add or update unit tests for behavior-changing Python scripts when a test harness exists.
- Preserve existing command-line flags and cron compatibility unless a Linear task explicitly migrates callers.
- For dashboard/control-panel scripts, prefer `status + reason + checked_at` over silent missing fields.
- For shell scripts, quote paths, fail deliberately, and keep logs useful without secrets.

## Verification

- Python edits: `python3 -m py_compile <changed scripts>` and targeted `python3 -m unittest ...`.
- Business panel: `python3 scripts/business_control_panel.py --dry-run` and `python3 -m unittest scripts/test_business_control_panel.py`.
- Cron/report scripts: run the documented `--dry-run` mode when present.
- Template/design validators: run the specific validator listed by the changed script.

## Child DOX Index

No child `AGENTS.md` files are currently required here.
