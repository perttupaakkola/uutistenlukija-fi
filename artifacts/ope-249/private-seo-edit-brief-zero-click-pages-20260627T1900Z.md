# OPE-249 Private SEO Edit Brief

Created: 2026-06-27 19:00 UTC  
Scope: private implementation brief only. No public content changed, posted, emailed, scheduled, advertised, or launched.

## Measurement Baseline

Source: `/home/pertt/.openclaw/workspace/reports/uutistenlukija-analytics/search-console-data.json`  
Generated: `2026-06-27T06:30:01.725423+00:00`  
Freshness reference: `2026-06-27T12:15:05+00:00`

Selected pages:

| URL | Impressions | Clicks | CTR | Avg. position |
| --- | ---: | ---: | ---: | ---: |
| `/posts/2026-05-31-kuhmossa-asuntoja-on-tarjottu-eurolla-ja-ilmaiseksi/` | 131 | 1 | 0.76% | 5.2 |
| `/posts/2026-04-30-mm-kisoissa-voidaan-antaa-punainen-kortti-myos-suun-peittami/` | 123 | 1 | 0.81% | 10.0 |
| `/posts/2026-05-08-isanmaan-toivot-sarjan-toni-wahlstrom-on-jatkanut-uraansa-te/` | 118 | 0 | 0.00% | 11.3 |

Success check: compare page-level Search Console clicks, CTR, impressions, and average position after 7 and 14 days against this baseline. Treat ranking volatility as inconclusive unless impressions stay above 50 in the comparison window.

## Shared Patch Model

Alex's OPE-252 mapping shows these three pages can be patched as content-only changes:

- Add `seo_title:` near the existing `title:` when changing only the search/browser title.
- Edit `description:` for the visible deck, meta description, OG/Twitter description, and JSON-LD description.
- Edit `title:` only if the H1 and internal card anchor should also change. This brief does not require changing H1s.

Avoid template changes unless a later implementation needs a separate internal-anchor override field.

## Page 1: Kuhmo One-Euro Apartments

Canonical file: `projects/uutistenlukija/content/posts/2026-05-31-kuhmossa-asuntoja-on-tarjottu-eurolla-ja-ilmaiseksi.md`

Current title/H1: `Kuhmossa asuntoja on tarjottu eurolla ja ilmaiseksi`

Proposed `seo_title`:

```yaml
seo_title: "Kuhmon euron asunnot: miksi asunto voi olla ilmainen?"
```

Proposed `description`:

```yaml
description: "Kuhmossa asuntoja on tarjottu eurolla ja jopa ilmaiseksi. Artikkeli kertoo, miksi nollahinta ei poista vastikkeita, lainoja ja remonttiriskejä."
```

Internal-anchor guidance:

- Preferred anchor from related housing or economy contexts: `Miksi Kuhmossa asuntoja tarjotaan eurolla?`
- Secondary anchor for category cards if H1 is kept: `Kuhmon euron asunnot ja nollahinnan riskit`

Editorial fit and risk:

- Keeps the existing factual frame: cheap listings plus ownership costs.
- Does not claim a completed sale or a verified individual seller outcome.
- Improves search intent by naming "euron asunnot", "ilmainen asunto", and cost-risk context.

## Page 2: Red Card for Covering Mouth at World Cup

Canonical file: `projects/uutistenlukija/content/posts/2026-04-30-mm-kisoissa-voidaan-antaa-punainen-kortti-myos-suun-peittami.md`

Current title/H1: `MM-kisoissa voidaan antaa punainen kortti myös suun peittämisestä`

Proposed `seo_title`:

```yaml
seo_title: "Punainen kortti suun peittämisestä? Fifan uusi MM-linjaus"
```

Proposed `description`:

```yaml
description: "Fifa ottaa MM-kisoissa käyttöön linjauksen, jossa pelaaja voi saada punaisen kortin suun peittämisestä puhuessaan. Taustalla on Ifabin muutos."
```

Internal-anchor guidance:

- Preferred anchor from football or sports contexts: `Fifan MM-linjaus suun peittämisestä`
- Secondary anchor for broader rules context: `Punainen kortti voi tulla myös suun peittämisestä`

Editorial fit and risk:

- Keeps the conditional wording "voi saada", because available source material does not describe every application scenario.
- Does not overstate that every mouth-covering gesture automatically leads to a red card.
- Makes the search result clearer by naming Fifa, MM-kisat, punainen kortti, and suun peittäminen.

## Page 3: Toni Wahlstrom / Isanmaan Toivot

Canonical file: `projects/uutistenlukija/content/posts/2026-05-08-isanmaan-toivot-sarjan-toni-wahlstrom-on-jatkanut-uraansa-te.md`

Current title/H1: `Isänmaan toivot -sarjan Toni Wahlström on jatkanut uraansa teatterissa ja ohjaajana`

Proposed `seo_title`:

```yaml
seo_title: "Toni Wahlström nyt: Isänmaan toivot -näyttelijän ura jatkui teatterissa"
```

Proposed `description`:

```yaml
description: "Isänmaan toivot -sarjasta tuttu Toni Wahlström on ollut viime vuosina harvemmin televisiossa, mutta ura on jatkunut teatterissa ja ohjaajana."
```

Internal-anchor guidance:

- Preferred anchor from culture or TV contexts: `Mitä Toni Wahlström tekee nykyään?`
- Secondary anchor for series-interest contexts: `Isänmaan toivot -näyttelijän ura jatkui teatterissa`

Editorial fit and risk:

- Uses search-intent wording "nyt" and "mitä tekee nykyään" without adding unsupported new biography claims.
- Keeps the factual emphasis on theatre and directing from the existing article.
- Does not imply Wahlström has left acting or television permanently.

## Implementation Handoff

Smallest safe patch:

1. Add `seo_title` and replace `description` in the three markdown files above.
2. Keep existing `title` values unless Sara/Alex deliberately decide the H1 should also change.
3. Run the normal content/template checks after patching:
   - `python3 -m py_compile` for any touched Python helper only if scripts change.
   - `bash scripts/validate_templates.sh`
   - Hugo render through the repo's existing Hugo binary/path.
4. After deploy, record public URL checks and compare Search Console again after 7 and 14 days.

No public action approval is needed for drafting this brief. Any live content patch should still go through the normal repository verification and deploy path.
