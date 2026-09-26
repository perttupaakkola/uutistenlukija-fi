# Uutistenlukija — automated Finnish news site

One Python controller writes one Finnish article per tick from a reviewed official source,
an independent reviewer approves it, and one guarded executor deploys it to
uutistenlukija.fi (GitHub Actions → Cloudflare Pages). Steady state: the pipeline runs on
the VPS timer (`uutistenlukija-mvp.timer`). There are no owner-approval gates — review is
the in-pipeline chain below, and every decision is recorded in the plans docs.

## Sources (news-reviewed-v2)

- NASA MODIS image-of-the-day plus pinned official text sources in
  `sources/finnish-official.json` (Helsinki, Tilastokeskus, Kuntaliitto, ECB, Kuopio,
  Vantaa, Valtioneuvosto). Each provider pins its article-URL pattern, hosts, reuse
  terms (text hash; document hash for Kuopio) and licence — the licence is never
  defaulted.
- Discovery reads each provider's bounded index/RSS with 48-hour freshness, returns at
  most five recipes, admits one new source per tick, rotates providers after the last
  admitted provider, and reports per-provider source errors without suppressing others.
- Related-coverage search may add corroborating sources (B..N): best effort, never
  required, and never the sole basis of a claim.

## Provenance

- Text releases bind packet/source/rights hashes; before release, stored intake bytes
  must reproduce the reviewed source and rights, and live-page readback must match the
  reviewed text (reversible CDN e-mail obfuscation excepted).
- Every new public article needs one relevant reviewed image. Verified licensed real
  imagery is attempted first; otherwise the complete draft grounds a clearly labelled AI
  illustration. Actual pixels are checked independently against the final article and
  bound by hash. Sensitive and named-person stories use safe objects, places or processes;
  generated illustrations contain no people, likenesses or invented documentary events.
  Official text permissions never imply permission to reuse the source's photography.
- Image-provider failures retain the saved draft for a later attempt. An image-only
  editorial rejection preserves the refused candidate and review in `image-rejections/`
  and retries imagery. Public rendering and publication both refuse missing images.
- Archive image corrections preserve old job/publication records in
  `image_backfill_batches`. One guarded batch has one deployment anchor; every corrected
  article and exact image must pass immutable-release and live readback checks before
  the batch completes. Historical nullable image fields remain provenance, not permission
  to publish a new text-only page.
- Headlines target ≤60 characters: the writer is instructed, one bounded repair call
  fits over-long ones, and the reviewer checks the final draft.
- The public bundle includes RSS (`/rss.xml`), sitemap, canonical links, OG/Twitter/
  JSON-LD metadata, and an IndexNow key file; deploys ping IndexNow best-effort.

## Operations

- `python3 -B -m unittest discover -s tests` — full suite.
- `python3 -B -m news_mvp live-tick --config config.json` — one scheduled tick.
- `python3 -B -m news_mvp requeue-failed --config config.json [--job ID]` — reset failed
  publications for retry (fixed-bug recovery); the normal publish path re-validates
  everything before anything reaches the public site.
- Pending-publication priority: each tick reconciles at most one nonterminal publication
  before any new admission; multiple pending rows or unknown commit outcomes stop for
  operator review instead of guessing.
- State lives in `/home/pertt/.local/share/uutistenlukija` (`jobs.sqlite`, `media/`,
  `learning/`).
- Prefer `UUTIS_IMAGE_PROVIDER=codex-oauth` with the existing ChatGPT-authenticated Codex
  CLI. This uses one ephemeral, read-only `gpt-6-astra`/`xhigh` image-only invocation;
  no API key, publishing tools, shell, apps or paid image fallback is passed to it.
  Set `UUTIS_CODEX_BINARY` when the installed executable is outside the normal PATH.
  Exact fresh native image bytes, prompt, invocation events and receipts are retained
  under `codex-image-requests/`; prose success alone is refused. Cached output survives
  reviewer outages, completed interrupted requests reconcile without regeneration,
  and failures back off while publication remains image-pending. The documented
  built-in image model is `gpt-image-2`; receipts distinguish this from returned model
  telemetry. The existing independent pixel reviewer remains separately configured.
  The preserved alternative settings are `UUTIS_IMAGE_PROVIDER=google` and
  `UUTIS_VISION_PROVIDER=google`. These select Google
  `gemini-3.1-flash-image` and the separate `gemini-2.5-flash` pixel reviewer. Selecting
  image provider `kie` uses its `nano-banana-2` task API; the default remains OpenAI when unset.
  Existing host-only project credentials supply `KIE_API_KEY`; Google reads the existing
  `GOOGLE_API_KEY`/`GEMINI_API_KEY` or the host's Hermes environment file. Credentials
  never enter source, public assets, receipts or request diagnostics. The licensed-real
  provider order remains Pexels, Unsplash, Wikimedia Commons, then Google image search.
  `image-provider-requests/` retains task identities and exact cached pixels, so a pending
  task or temporary review outage resumes without another paid generation. Explicitly
  rejected pixels require a fresh task. `image-provider-attempts/` records request hosts,
  HTTP outcomes and the accepted image hash without request queries or response bodies.

## Front-page snapshots

Generated-image accessibility uses `AI-generoitu kuva: ` followed by a useful,
reviewed Finnish description of the actual pixels. The small article-only caption
is `AI-generoitu kuva. Ei valokuva tapahtumasta.` The rights section uses `AI-kuvitus`
and `/ai-kuvat/`; generator details stay in internal provenance. Listing images have
no generated-image badge, overlay or disclosure. The validator checks all current
generated metadata, not only the visible alt. Archive wording corrections retain
the original image record in batch history, preserve image bytes and prompt hashes,
and require exact-image plus unchanged-text archive approval before activation.

Real-image selection still comes first. Commons searches reserve their bounded
window for raster files; an explicit historical HTTP Creative Commons identifier
is canonicalized only to the same official HTTPS grant. Missing or conflicting
rights never become permission. New Commons records retain the work title and a
JPEG reproduction notice in the article's existing rights section. A historical
failed publication can enter image-only archive correction only when a later
successful, locally reconciled release and Pages receipt bind its exact canonical
HTML and image bytes on the live host. Its failed history remains in the batch;
no old dispatch is replayed.

The existing live controller refreshes four MET Norway location forecasts and ECB daily
EUR reference rates when `frontpage_snapshots` is enabled in the local config. Data is
cached in state `frontpage-data.json` (weather: one hour; currencies: six hours), then
embedded in the normal static release. Requests have an identifying User-Agent, an
8-second timeout and a size limit; upstream failures preserve the last snapshot. There
is no client API key, third-party page-load request or additional service. The browser
selects the nearest forecast hour and suppresses forecasts older than 18 hours or rates
older than seven days; source/model timestamps and the forecast/reference-rate labels
stay visible. Provider outages do not stop article publication.

The newest story always occupies the original dark overlaid lead. The layout and CSS
retain baseline `3b55192d7818214090f350fe7a210ddd84a05284`: weather uses the compact header
surface, markets use the existing panel after the newsletter, and RSS uses the existing
newsletter/footer/feed metadata. There is no extra shortcut row or older-story promotion.
The original mobile ordering and visibility rules remain intact. Known image exclusions
and accurate alt corrections preserve the original source records; excluded imagery
requires replacement before a public release can render.
