# Uutistenlukija MVP — revision54 candidate, not installed

One Python controller, SQLite dedupe, sequential Finnish writer/reviewer prompts,
static pages and one existing GitHub/Cloudflare Pages executor. Uses the existing
shared Hermes runtime, news-mvp profile and Codex OAuth. No old pipeline/history,
agent roles, extra runtime or publisher. The installed baseline remains the
previously activated NASA-only release; this isolated candidate has no live authority.

`news-reviewed-v2` discovery preserves NASA MODIS and adds two exact official text
sources: Tilastokeskus Finnish releases and Helsinki news RSS. Relevant terms and
licence links are pinned in sources/finnish-official.json. VN is not approved:
attribution does not override its commercial-reuse restriction. No facts-only
substitution or legal-basis change is implied. Current scope remains two Finnish
institutional sources plus NASA, not comprehensive world/sports/independent news.

Discovery reads three bounded indices, examines at most 50 official index entries
per provider and returns at most five recipes. Terminal URLs are removed before
selection. Provider order rotates after the last admitted provider. Outage/refusal
of one provider is returned as source_errors and does not suppress other providers.
At most one new source is admitted per tick. The full collection budget is at most
18 bounded intake fetch calls (three indices plus up to five three-fetch collections).
Freshness remains 48 hours and the same timer remains 15 minutes. Completed and
uncertain-dispatch records cannot cause duplicate editorial work or redispatch.

The new official-text-v1 contract permits image-less articles ONLY for those exact
providers, rights text/licence, source identity and policy hash. The packet includes
source-byte and parsed-source hashes; the writer preserves null image, and the
reviewer checks the exact Finnish draft against its sources. Before release, actual
stored intake bytes must reproduce the reviewed source and rights. Unknown policy,
missing/changed provenance, fixture/private-only packet or unreviewed draft refuses
publication. No dummy image, fabricated hash, logo or automatic image inference.

The same contract reaches public_bundle, cutover/check_release.py, the actual
ops/deploy.yml deployment-record command and canonical readback. Text-only version2
receipts bind packet/draft/review/provenance and use JSON null for image_sha256.
Public pages say they have no image, show source attribution, CC BY link and change
notice, and do not call accepted public text a draft. Canonical readback checks the
text and licence notices without requesting a JPEG. Mixed home pages retain existing
NASA articles/images. Existing imaged receipts retain image hash/JPEG semantics.

The publications schema permits SQL NULL for new text-only image_sha. The tiny
transactional migration copies existing rows unchanged and refuses unexpected
columns/indexes/triggers. restore_image_required_schema is a pre-activation rollback
only: it refuses if any text-only publication exists. Never delete rows to roll back.
The operator must hold the existing single_tick lock across any install/schema/
policy transition. There is no installation or activation by this candidate.

A proposed steady-state v2 policy is disabled until separately approved by Hermes;
it pins the exact source commit, all three providers, text policy digest, canonical
origin/executor, admission/fetch/freshness limits and 15-minute timer. Existing v1
NASA authorization remains supported. Source config outside the exact policy,
dirty source, disabled controller or missing approval fails closed. Keep production
config/state/profile untouched until a separate reviewed installation boundary.

Private commands:

```
python3 -B -m unittest discover -s tests -v
node tests/test_analytics.cjs
python3 -B -m news_mvp discover --config config.private.json
```

config.private.json is disabled and uses relative private state/output paths.
`collect` and `tick` remain the same intake/controller interfaces; no model fetches
sources. `live-tick` for news-reviewed-v2 additionally requires the exact approved
policy before opening state. A direct publish call is not an operator entrypoint;
normal scheduling holds the controller lock throughout intake, model and release.

Revision54 includes two real private historical-source experiments with unchanged
source dates. Both were rejected and are preserved as rejected reports, not approved
articles. No model retry or self-approval is implied. Current official-source fetches
found no fresh eligible item overnight. A fresh accepted private article and later
natural scheduled same-packet live/no-duplicate proof remain required acceptance.

Pending-publication priority: under the same controller lock, each tick first reads
SQLite for nonterminal publications and reconciles at most one. It does not read
feeds or admit a new provider until the outcome is terminal. Multiple pending rows,
missing job identity or an unknown commit outcome fail closed for operator review.
Prepared records may finish their original promotion/dispatch; dispatched/unknown
records only inspect their existing run and canonical result. A lost external
response remains unknown and cannot cause another push or dispatch. A successful
reconciliation owns that entire tick; fresh discovery waits for the next tick.
