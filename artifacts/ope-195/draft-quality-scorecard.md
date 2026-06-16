# OPE-195 Buffer Draft Quality Scorecard

Generated: 2026-06-16 14:41 UTC

Scope: internal growth/distribution review only. No Buffer, X, queue, schedule, reply, DM, follow, repost, email, payment, or campaign action was performed.

## Source Artifacts

- `artifacts/ope-189/buffer-draft-examples.json`
- `artifacts/ope-189/buffer-draft-examples.txt`
- `artifacts/ope-195/buffer-draft-sample-20.json`
- `artifacts/ope-195/buffer-draft-sample-20.txt`

## Verification

- `python3 pipeline/buffer_dry_run.py --hours 168 --max-posts 20 --output artifacts/ope-195/buffer-draft-sample-20.json`
- `python3 pipeline/buffer_dry_run.py --hours 168 --max-posts 20 --format text --output artifacts/ope-195/buffer-draft-sample-20.txt`
- `python3 -m py_compile pipeline/buffer_dry_run.py pipeline/x_auto_poster.py`
- JSON inspection confirmed 25 total review drafts across the original 5 and the new 20-draft sample.
- Both JSON payloads have `public_actions_disabled=true`, all drafts have `approval_required=true`, all `scheduled_at=null`, and `BUFFER_PROFILE_ID` is still missing.

## Summary

Drafts scored: 25

Review-ready without manual rewrite: 9/25 = 36%

Held back: 16/25

Decision: do not ask for public Buffer/X approval yet. The 60% review-ready threshold was not met, and the zero category/tag mismatch rule was not met.

Primary failure modes:

- Teaser completeness: 12 drafts end with an ellipsis because the current X-oriented composer clips teaser text near the 280-character boundary.
- Category/tag fit: 7 drafts have category or hashtag mismatch risk, mostly `Kotimaa` / `#suomi #kotimaa` on clearly foreign or non-domestic stories.
- Sensitivity risk: 6 drafts involve war/geopolitics, murder/crime, fire, or other high-care material and should not be early public-distribution examples without editorial review.
- Cadence fit: cadence is usable as a draft-only heuristic, but it is only alternating morning/evening slots and does not yet distinguish sensitive breaking news, evergreen explainers, or entertainment/roundup posts.

## Scoring Rules

Review-ready means all of these are true:

- Category and hashtags fit the story topic.
- Teaser is a complete sentence or complete thought, not visibly clipped.
- Sensitivity is low enough for routine public-distribution review.
- Cadence target is plausible for the item.

Held-back does not mean the article itself is bad. It means the generated distribution draft should not be used as-is.

## Draft-Level Notes

| # | Source | Category | Title | Result | Main reason |
|---|---|---|---|---|---|
| 1 | OPE-189 | Ulkomaat | Trump torjui Iranin vastauksen... | Hold | Sensitive geopolitics and clipped teaser |
| 2 | OPE-189 | Kotimaa | Justin Trudeau puolustautui... | Hold | Canada story labeled Kotimaa / `#suomi #kotimaa` |
| 3 | OPE-189 | Teknologia | Stroopin testi paljasti... | Hold | Strong angle, but teaser is clipped |
| 4 | OPE-189 | Kotimaa | Äiti odottaa uutta oikeudenkäyntiä... | Hold | Sensitive murder case and country/category mismatch |
| 5 | OPE-189 | Teknologia | Viikon peliuutisissa GTA 6... | Ready | Complete teaser and category fit |
| 6 | Sample 20 | Kotimaa | Orimattilan kaupunginjohtajan asemaa... | Hold | Local angle is relevant, but teaser is clipped |
| 7 | Sample 20 | Ulkomaat | Iranissa mahdollinen sopimus... | Hold | Sensitive geopolitics and clipped teaser |
| 8 | Sample 20 | Talous | Tekoäly tuo uusia vakuutuspetoksia... | Hold | Good Talous angle, but teaser is clipped |
| 9 | Sample 20 | Teknologia | SpaceX ostaa Cursorin emoyhtiön... | Ready | Complete teaser and category fit |
| 10 | Sample 20 | Kotimaa | Vuoden pakolainen on näyttelijä... | Ready | Complete teaser and category fit |
| 11 | Sample 20 | Ulkomaat | Kertausharjoitusten määrät nousivat... | Hold | Category/topic ambiguity and clipped teaser |
| 12 | Sample 20 | Kotimaa | Kolin kuuluisa Mäkrän mänty... | Ready | Complete teaser and category fit |
| 13 | Sample 20 | Kotimaa | Nigerian asevoimat vapautti... | Hold | Nigeria story labeled Kotimaa / `#suomi #kotimaa` |
| 14 | Sample 20 | Kotimaa | Vietnam toi Suvi Kokkoselle... | Hold | Sport/foreign-league angle labeled Kotimaa |
| 15 | Sample 20 | Kotimaa | MTV:n ja Elisan kiista... | Ready | Complete teaser and category fit |
| 16 | Sample 20 | Kotimaa | Kemin polttopuuautomaatti... | Ready | Complete teaser and category fit |
| 17 | Sample 20 | Teknologia | Samsung-puhelimiin tulossa... | Ready | Complete teaser and category fit |
| 18 | Sample 20 | Kotimaa | Intialaisen oppikirjan peitelty... | Hold | India story labeled Kotimaa and clipped teaser |
| 19 | Sample 20 | Kotimaa | Kaksi miestä pidätetty... Australiassa | Hold | Australia/crime story labeled Kotimaa and sensitive |
| 20 | Sample 20 | Teknologia | Simpsonit puhuivat suomea... | Hold | Category/tag fit is weak for culture/TV content |
| 21 | Sample 20 | Talous | Joka kolmas päätoiminen yksinyrittäjä... | Hold | Strong Talous angle, but teaser is clipped |
| 22 | Sample 20 | Ulkomaat | Vance: Yhdysvaltain ja Iranin... | Hold | Sensitive geopolitics and clipped teaser |
| 23 | Sample 20 | Kotimaa | Kerrostaloasunnon palo... | Hold | Local category fits, but incident sensitivity needs review |
| 24 | Sample 20 | Urheilu | Thomas Röhler palasi... | Ready | Complete teaser and category fit |
| 25 | Sample 20 | Tiede | Hyttysiä on poikkeuksellisen vähän... | Ready | Complete teaser and category fit |

## Recommendation

Create a composition-quality follow-up before public approval:

- Alex: adjust the Buffer/social draft composer so Buffer drafts are not constrained to the X 280-character clipping behavior, or add a Buffer-specific text template with complete teaser sentences.
- Monica: define a simple editorial holdback rule for sensitive stories and category/tag mismatches before social drafts enter an approval pack.
- Iris: keep growth work moving without posting publicly by building a no-public distribution angle backlog from the 9 review-ready examples plus fresh Talous/technology stories, then use the fixed composer for the next approval pack.

Approval request status: not ready.
