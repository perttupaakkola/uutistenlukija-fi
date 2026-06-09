# AGENTS.md — Docs

## Purpose

`docs/` contains durable runbooks, research notes, implementation plans, and operator references for `uutistenlukija.fi`.

## Ownership

- Felix owns coordination docs and business-loop operating model.
- Max owns ops/security/reliability runbooks.
- Sara owns design/SEO/a11y docs.
- Monica owns editorial/source-quality docs.
- Iris owns growth, distribution, analytics interpretation, and monetization experiment docs.

## Local Contracts

- Write durable knowledge, not status diaries. Current task progress belongs in Linear OPE comments or workspace mirrors.
- Remove stale instructions instead of adding historical caveats unless history is operationally necessary.
- Do not include secrets, private webhook URLs, token paths beyond non-secret directory shape, or raw private customer/user data.
- Link docs to actual files, commands, tests, dashboards, or Linear issues when they are operational instructions.
- Keep public-action, paid, account, credential, legal, and privacy approval gates explicit.

## Work Guidance

- Prefer concise runbook steps with verification commands and rollback notes.
- If a doc describes a workflow that agents must follow before editing code, consider whether root or child `AGENTS.md` also needs a short contract update.
- When documenting research, separate current facts from recommendations and note evidence age.

## Verification

- Markdown-only docs usually need read-through verification plus link/path sanity checks.
- Run code or command examples when the doc claims they are current and safe.
- For docs that change operating rules, verify the nearest `AGENTS.md` remains consistent.

## Child DOX Index

No child `AGENTS.md` files are currently required here.
