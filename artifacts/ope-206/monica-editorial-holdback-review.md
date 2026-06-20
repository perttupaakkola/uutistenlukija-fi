# OPE-206 Monica Editorial Holdback Review

Generated: 2026-06-19 20:28 UTC

Scope: private Buffer draft quality-gate evidence only. No Buffer, X, email, campaign, queue, schedule, reply, DM, follow, repost, payment, or other public action was performed.

## Evidence Base

- `projects/uutistenlukija/artifacts/ope-195/buffer-draft-sample-20.json`
- `projects/uutistenlukija/artifacts/ope-195/buffer-draft-sample-20.txt`
- `projects/uutistenlukija/artifacts/ope-195/draft-quality-scorecard.md`

The exact OPE-206 artifact directory was absent at review start, so this packet uses the latest local Buffer draft sample already produced for the same quality-gate line of work.

## Keep/Hold Decisions

| Sample | Draft | Decision | Evidence | Editorial reason |
|---|---:|---|---|---|
| OPE-195 sample 20 | 4 | Keep | "SpaceX ostaa Cursorin emoyhtiön 60 miljardilla dollarilla"; complete teaser sentence; `#teknologia #tekoäly` | Category/tag fit is coherent and the teaser is not visibly clipped. Hold only if source verification flags the acquisition claim itself. |
| OPE-195 sample 20 | 5 | Keep | "Vuoden pakolainen on näyttelijä Youssef Asad Alkhatib"; complete teaser sentence; `#suomi #kotimaa` | Public-interest domestic item with a complete, neutral teaser. The draft is suitable for an approval pack. |
| OPE-195 sample 20 | 8 | Hold | "Nigerian asevoimat vapautti vankeudessa kuolleen kenraalin lesken"; `#suomi #kotimaa` | Clear geography/category mismatch: a Nigeria story is labeled domestic Finland. Also contains abduction/custody sensitivity. |
| OPE-195 sample 20 | 14 | Hold | "Kaksi miestä pidätetty Dezi Freemanin liikkeiden tutkinnassa Australiassa"; `#suomi #kotimaa` | Australia/crime story is labeled domestic Finland and should not enter social approval without manual category and sensitivity review. |
| OPE-195 sample 20 | 16 | Hold | "Joka kolmas päätoiminen yksinyrittäjä jää alle 2 000 euron kuukausituloihin"; teaser ends mid-thought with ellipsis | Strong `Talous` story, but the Buffer draft should hold because the teaser is visibly clipped. Buffer copy needs a complete sentence before approval. |

## Editorial Holdback Rule

Hold a Buffer/social draft before it enters an approval pack if any of these are true:

1. The teaser visibly ends in a generated clipping marker or incomplete thought, especially a trailing ellipsis from X-length composition.
2. The category, emoji, or hashtags do not match the story's actual geography or topic. In particular, do not allow foreign-only stories through with `Kotimaa`, `#suomi`, or `#kotimaa`.
3. The story involves war, active geopolitics, death, murder, sexual violence, serious crime, fire, abduction, missing persons, terrorism, court proceedings, or other high-care material, unless a human/editorial review has explicitly approved the social framing.
4. The social text makes a large factual claim that would be reputationally costly if wrong and the source support is not visible in the article or packet.

Passing the rule does not publish anything. It only means the draft may be included in a private approval pack for human review.

## Alex-Ready Acceptance Criteria

- Buffer-specific composition must not inherit X's 280-character teaser clipping. Generated Buffer teaser text should be a complete sentence or complete thought.
- Distribution gate should emit a machine-readable decision for each draft: `keep` or `hold`, plus one or more reason codes such as `clipped_teaser`, `category_tag_mismatch`, `sensitive_topic`, or `source_claim_risk`.
- A draft with foreign geography and `Kotimaa`/`#suomi`/`#kotimaa` must be held.
- A draft containing sensitive-topic keywords or classified sensitive by existing metadata must be held unless an explicit manual override is present.
- Tests or dry-run evidence should include at least one keep case and one hold case for each of: clipped teaser, category/tag mismatch, and sensitive-topic holdback.

## Summary

From these five representative local examples: 2 keep, 3 hold.

The highest-value editorial rule is simple: no clipped teasers, no mismatched category/tags, and no sensitive stories in the social approval pack without explicit editorial review. This protects trust while still allowing clean, low-risk drafts to move forward.
