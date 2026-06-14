# OPE-189 Buffer Draft Approval Pack

Generated: 2026-06-14 16:39 UTC

Scope: non-public review examples only. No Buffer, X, queue, schedule, reply, DM, follow, repost, payment, or campaign action was performed.

## Artifacts

- JSON payload: `artifacts/ope-189/buffer-draft-examples.json`
- Human review text: `artifacts/ope-189/buffer-draft-examples.txt`

## Verification

- `python3 pipeline/buffer_dry_run.py --hours 24 --max-posts 5 --output artifacts/ope-189/buffer-draft-examples.json`
- `python3 pipeline/buffer_dry_run.py --hours 24 --max-posts 5 --format text --output artifacts/ope-189/buffer-draft-examples.txt`
- `python3 -m py_compile pipeline/buffer_dry_run.py pipeline/x_auto_poster.py`
- `python3 pipeline/x_auto_poster.py --dry-run --max-posts 1`
- `jq` inspection confirmed 5 drafts, `public_actions_disabled=true`, `approval_required=true`, `scheduled_at=null`, and missing `BUFFER_PROFILE_ID`.

## Draft Summary

All examples are generated from recent Uutistenlukija articles through the same local text composition path used by the X dry-run. Each draft is review-only and uses a placeholder Buffer profile id because Buffer is not connected.

1. Trump torjui Iranin vastauksen Lähi-idän sopimusesitykseen, Israelin iskut Libanonissa kiristävät tilannetta
   - Category: Ulkomaat
   - Cadence target: draft-only morning slot, 07:00-08:30 Europe/Helsinki
   - Text length: 280

2. Justin Trudeau puolustautui Kanadan ottelun väliin jättämisestä Katy Perryn esiintymisen vuoksi
   - Category: Kotimaa
   - Cadence target: draft-only evening slot, 17:00-18:30 Europe/Helsinki
   - Text length: 280

3. Stroopin testi paljasti suurten kielimallien heikkouden pitkissä tehtävissä
   - Category: Teknologia
   - Cadence target: draft-only morning slot, 07:00-08:30 Europe/Helsinki
   - Text length: 280

4. Äiti odottaa uutta oikeudenkäyntiä tyttärensä murhasta Dominikaanisessa tasavallassa
   - Category: Kotimaa
   - Cadence target: draft-only evening slot, 17:00-18:30 Europe/Helsinki
   - Text length: 280

5. Viikon peliuutisissa GTA 6 -huolia, ilmaispelejä ja Destiny 2:n päätöksen tunnelmia
   - Category: Teknologia
   - Cadence target: draft-only morning slot, 07:00-08:30 Europe/Helsinki
   - Text length: 274

## Approval Gate

These drafts are suitable for internal review of tone, cadence, and article selection. They are not approved for public use until Perttu approves the public-distribution gate and Buffer/X runtime is connected with a non-secret profile id.
