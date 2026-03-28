# Finnish News Publishing — Legal/Copyright Brief
**Date:** 2026-03-21 (päivitetty 2026-03-23)
**Author:** Monica (research agent)
**Status:** Final — päivitetty vastaamaan nykyistä sisältömallia (alkuperäinen AI-journalismi)

## Executive Summary

**Bottom line:** uutistenlukija.fi toimii **verkkolehtenä, joka tuottaa alkuperäistä AI-avusteista journalismia** useiden lähteiden pohjalta. Emme ole uutisaggregaattori — emme kopioi tai välitä muiden artikkeleja.

Koska kirjoitamme alkuperäistä sisältöä, EU DSM Directive Art. 15 (press publishers' right) ei ole suoraan sovellettavissa samalla tavalla kuin aggregaattoreille. Silti toimituksellisena standardina:

- **Alkuperäiset artikkelit useiden lähteiden pohjalta** ✅
- **Ei sanatarkkaa kopiointia lähdemateriaaleista** ✅
- **Käytetyt lähteet listataan** ✅
- **AI-sisältö merkitään läpinäkyvästi** ✅

---

## 1. Finnish / EU Copyright Baseline

- Finland **implemented the EU DSM Copyright Directive** into national law; amendments approved **27 Feb 2023**, effective **3 Apr 2023**.
- **Article 15** creates a press publishers' related right: commercial online services generally need permission to use press-publication content beyond links / very short extracts.
- The directive/Finnish implementation excludes:
  - Plain hyperlinking
  - Individual words
  - "Very short extracts"
- **"Very short extract" is not clearly defined** in a hard numeric way. The boundary is ultimately for courts/practice to define.

## 2. Finland Status of Article 15

- **Art. 15 is in force in Finland now.**
- Art. 15 is primarily intended to cover **commercial news aggregators** that republish or display publisher content directly.
- **Uutistenlukija's model** — producing original articles inspired by multiple sources — is fundamentally different from aggregation. We don't republish or display publisher text. However, editorial standards still require that we don't copy verbatim from sources.

## 3. Safe Snippet Lengths

### What the law clearly says
- Hyperlinks: always allowed
- Individual words: always allowed
- "Very short extracts": allowed but undefined

### What it doesn't define
- No statutory character/word limit for "very short"
- No Finnish court rulings yet establishing a bright line

### Our model: original journalism
Since we write original articles based on research across multiple sources (not snippets or previews of individual articles), the "safe snippet length" question is less relevant. Our editorial standard is:
- **No verbatim copying** from any single source
- **Original synthesis** — our articles are new works, not extracts
- **Source attribution** — list sources used at the end of each article

## 4. Publisher Policies

| Publisher | RSS Available | Commercial Aggregation | Notes |
|-----------|--------------|----------------------|-------|
| Yle | Yes (multiple feeds) | Generally permissive for linking | Public broadcaster; content partly CC-licensed |
| HS (Helsingin Sanomat) | Limited | Restrictive — explicit ToS against commercial reuse | Sanoma group; likely to enforce Art. 15 |
| Iltalehti | Yes | No explicit aggregation policy found | Alma Media group |
| IS (Ilta-Sanomat) | Yes | Restrictive — Sanoma ToS applies | Same group as HS |
| MTV Uutiset | Yes | No explicit policy found | |
| Kauppalehti | Yes | Restrictive — Alma Media ToS | Business-focused |
| Tekniikka&Talous | Yes | Same as Kauppalehti (Alma) | |
| Taloussanomat | Limited | Sanoma group restrictions | |

### Key risk publishers
- **Sanoma group** (HS, IS, Taloussanomat): Most likely to assert Art. 15 rights. Explicit ToS restrictions on commercial content reuse.
- **Alma Media** (Kauppalehti, Iltalehti, Tekniikka&Talous): Less explicit but corporate policy likely protective.

## 5. What Ampparit / Google News Do

### Ampparit
- Displays headline + very short preview (typically <100 chars)
- Links directly to publisher article
- Has been operating for years without known legal challenges
- Likely has informal arrangements with some publishers

### Google News Finland
- Headline + snippet (auto-generated, typically 1-2 sentences)
- Google has **licensing agreements** with major Finnish publishers via Google News Showcase
- Not a valid precedent for us — Google has legal resources and licensing deals we don't have

## 6. Editorial Policy for uutistenlukija.fi

### Original journalism model
1. **AI researches multiple sources** for each topic/event
2. **Writes an original article** that synthesizes information from these sources
3. **Lists sources used** at the end of each article
4. **Byline: "Uutistenlukija · AI-toimitus"** — transparent about AI involvement
5. **`<meta name="ai-generated" content="true">`** on all article pages

### Editorial standards (legal caution)
- ✅ Synthesize facts from multiple sources into original articles
- ✅ Attribute sources used
- ✅ Use our own language, structure, and framing
- ❌ Do NOT copy verbatim text from any source
- ❌ Do NOT closely paraphrase a single source's unique expression
- ❌ Do NOT use publisher images without explicit permission or compatible license

### Takedown protocol
1. Any publisher objection → review the specific article immediately
2. If verbatim copying found → fix immediately
3. Document the request and assess
4. If pattern of issues → review pipeline quality controls

---

## Impact on Product

As a verkkolehti producing original AI-journalism:
- **We are a content destination** — readers come for our original articles
- **Value-add comes from**: original synthesis, categorization, speed, accessibility, and AI-powered journalism
- **Our AI writes original articles** based on research across multiple sources — not extracts or rewrites
- **Monetization** is based on our own content and audience — standard media model

## Next Steps
1. ✅ Sisältömalli päätetty: alkuperäinen AI-journalismi
2. Alex to implement byline fix + source attribution in pipeline
3. Sara to design article layout with source section
4. Legal review recommended before public launch (focus: AI disclosure compliance, EU AI Act Art. 50)
