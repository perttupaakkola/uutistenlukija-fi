# Finnish News Aggregation — Legal/Copyright Brief
**Date:** 2026-03-21
**Author:** Monica (research agent)
**Status:** Final — approved by Felix for team distribution

## Executive Summary

**Bottom line:** uutistenlukija.fi should operate as a **link + minimal preview aggregator**, not as a republisher of publisher text.

The biggest legal constraint is that **Finland has implemented EU DSM Directive Art. 15** (press publishers' right). That means commercial online services generally need permission to use press-publication content **beyond hyperlinks, individual words, or "very short extracts."**

The hard part is that **"very short extract" is not numerically defined** in law. So there is no reliable "safe by statute" number like 120 or 160 characters. Because of that uncertainty — and because some Finnish publishers explicitly restrict commercial use of headlines in RSS contexts — the safest build rule is:

- **Headline as outbound link** ✅
- **Very short preview only** ✅  
- **No copied ledes / no first paragraphs** ❌
- **No substantial snippets or article-style rewrites derived from publisher text** ❌ without licensing/permission

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
- Strong signal from Finnish legal commentary + Kopiosto: this is intended to cover **commercial news aggregators** and similar online news-use cases.
- Practical implication: if uutistenlukija displays publisher text in a way that goes beyond **link + minimal preview**, we're in licensing-risk territory.

## 3. Safe Snippet Lengths

### What the law clearly says
- Hyperlinks: always allowed
- Individual words: always allowed
- "Very short extracts": allowed but undefined

### What it doesn't define
- No statutory character/word limit for "very short"
- No Finnish court rulings yet establishing a bright line

### Recommended operational ceiling
- **Headline (as-is from publisher) + max 120 characters of preview text**
- Preview text should be our own summary, not copied lede
- This stays well within what German/Spanish precedent suggests is safe

### Safer fallback mode
- **Headline-only with no preview text** — zero risk
- Use if a publisher sends a takedown notice or objects

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

## 6. Recommended Operating Policy for uutistenlukija.fi

### Default mode (all publishers)
1. **Headline as clickable link** to original article
2. **Max 120 chars of AI-generated summary** (NOT copied from article)
3. **Publisher attribution** clearly visible
4. **Direct link to original** — no interstitial, no content gate
5. **No article images** without explicit permission or compatible license

### Enhanced mode (permissive publishers only — e.g., Yle)
1. Everything in default mode PLUS
2. Up to 200 chars of preview
3. Category-tagged thumbnail if publisher permits

### Takedown protocol
1. Any publisher objection → immediately switch to headline-only mode for that publisher
2. Document the request
3. Assess whether to pursue licensing conversation

### What we must NOT do
- ❌ Copy article ledes or first paragraphs
- ❌ Create "rewritten" versions that are substantially derived from original text
- ❌ Display publisher images without permission
- ❌ Cache or host full article content
- ❌ Use content in AI training pipelines without separate legal basis

---

## Impact on Product

This brief fundamentally shapes what uutistenlukija.fi can be:
- **We are a discovery/navigation layer**, not a content destination
- **Value-add must come from**: categorization, clustering, personalization, speed — NOT from displaying publisher content
- **Our AI summarization** must generate original preview text, not extract/copy from articles
- **Monetization** must not depend on keeping users away from publisher sites

## Next Steps
1. ⚠️ Perttu to review and confirm operating policy
2. Alex to implement snippet length limits in article display pipeline
3. Sara to design article cards within these constraints
4. Monica to research Kopiosto licensing options for potential enhanced partnerships
5. Legal review recommended before public launch
