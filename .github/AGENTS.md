# AGENTS.md — GitHub Workflows

## Purpose

`.github/` owns CI/deploy/alert workflows for `uutistenlukija.fi`.

## Ownership

- Max owns deploy reliability and alerting.
- Alex owns code/test workflow changes when implementation tasks require them.
- Felix verifies production deploy evidence and coordinates follow-up.

## Local Contracts

- Never print or hardcode GitHub, Cloudflare, Discord, or other secrets. Use GitHub Actions secrets and keep logs redacted.
- Keep the Cloudflare Pages deploy path aligned with the repository build: checkout, Hugo setup, validators, `hugo --minify`, deploy `public`.
- Keep deterministic staged pipeline workflows independently marker-gated. Scanner canaries use authenticated `workflow_dispatch` from exact `refs/heads/main` only; `pipeline/actions-scan.enabled` is reserved for final scheduled cutover. Until the historically exposed Firehose credential is rotated and separately reviewed, the scanner is intentionally RSS/public-research only and must not inject `FIREHOSE_TOKEN`. Publisher control uses `pipeline/actions-publish.enabled`. Changing or rolling back one must not toggle the other.
- Staged scanner runs may commit only `pipeline/queues/staged/**`, must validate the bounded queue delta, then rebase and push fail closed. Queue/control-only pushes must stay excluded from `deploy.yml`.
- Alert workflows should be actionable and low-noise; include failing workflow/run URLs and first failing step when feasible.
- Do not disable validation steps to make deploys pass unless a Linear issue explicitly tracks the risk and replacement check.

## Work Guidance

- For workflow edits, inspect the current workflow run state before and after pushing.
- Prefer pinning action major versions already used here unless there is a security/reliability reason to change.
- Keep `continue-on-error` intentional and limited to non-blocking diagnostics.

## Verification

- YAML parse/lint if a local checker is available.
- Staged Actions contracts: `python3 -m unittest -v scripts.test_actions_pipeline_workflows`.
- For deploy-impacting changes, push only after local checks pass and then verify the GitHub Actions run through the GitHub API or `gh` if available.
- Confirm `https://uutistenlukija.fi/` or the relevant `/api/...` endpoint after deploy when public behavior changes.

## Child DOX Index

No child `AGENTS.md` files are currently required here.
