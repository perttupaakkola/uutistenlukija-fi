# Research Brief: Generative Engine Optimization (GEO) for uutistenlukija.fi

**Date:** 2026-03-28
**Author:** Monica
**Status:** Ready for Implementation (Alex)
**Topic:** Optimizing for visibility and citations in AI Answer Engines (ChatGPT, Gemini, Perplexity)

---

## 1. AI Ranking Factors: What Makes News "Citable"?

In 2026, AI models don't just "rank" pages; they "retrieve" facts. To be selected as a source in a Finnish-language AI response, an article must satisfy three primary retrieval signals:

1. **Entity-Centric Authority:** Models like Perplexity and Gemini identify **Entities** (e.g., "Mari-Leena Talvitie", "Kehysriihi 2026", "Liekinheitin"). Articles that clearly define the relationship between these entities (Who did What, When, and Why) are prioritized for "grounding."
2. **Citations & Outbound Verifiability:** AI agents value "source chains." Including outgoing links to high-authority primary sources (valtioneuvosto.fi, thl.fi, tilastokeskus.fi) signals that our news is verified, making the AI more likely to cite *us* as the aggregator of that truth.
3. **Conversational "Lead-First" Structure:** Perplexity and ChatGPT scan for the "Direct Answer." If the first 150 words of an article (the lead) provide a standalone summary of the news development, the AI can "snip" it directly into the response.

---

## 2. Structured Data: The GEO Schema Stack

Traditional SEO focuses on `Article` schema. GEO requires a more granular "Machine-Readable" layer.

### Primary Schema Types for Alex:
- **NewsArticle:** Standard, but must include `datePublished`, `dateModified`, and `author` (with `sameAs` links to LinkedIn/X to prove E-E-A-T).
- **Speakable:** **CRITICAL.** Identifies sections (headline + lead) that are suitable for text-to-speech agents (Gemini/Copilot).
- **FAQPage:** If the article is an explainer (e.g., "What is Kehysriihi?"), use FAQ schema. AI models use this to directly answer "People also ask" style conversational queries.
- **FactCheck / ClaimReview:** If the article debunks or verifies a specific claim, this schema is a massive "Trust Signal" for Gemini.

---

## 3. Industry Benchmarks: Nordic AI Strategies

- **Schibsted (Norway/Sweden):** Has signed a direct licensing deal with OpenAI (VG, Aftenposten). They use a proprietary LLM (NorLLM) specifically to generate headlines that perform well in AI-retrieval contexts.
- **Alma Media (Finland):** Aggressively scaling AI to improve conversion and personalization. Their strategy prioritizes **First-Party Data** (e.g. newsletters) to counter the loss of third-party cookies and maintain audience engagement in AI search environments.
- **Sanoma:** Focuses on high-quality editorial data that acts as a "Gold Standard" for LLM training and retrieval.

### The New Standard: `llms.txt`
By March 2026, `llms.txt` (located at the root) has become the "robots.txt" for AI. It should provide a markdown-formatted directory of the site's most important themes to help LLM crawlers index our topical authority quickly.

---

## 4. Top 5 Actionable Hugo Implementation Steps (for Alex)

1. **Generate `/llms.txt`:** Create a Hugo template that outputs a Markdown file at the root. It should list our 8 categories and the latest 5 high-authority articles in each, acting as a "Fast-Track" for AI crawlers.
2. **Author "Trust-Link" Partial:** Update the author partial to include `schema.org/Person` with `sameAs` links. AI models need to verify that the author is a real entity with expertise.
3. **The "TL;DR" Box (Semantic Lead):** Add a `.tldr` class to the first paragraph of all articles. Wrap this in a specific HTML5 `<aside>` or `<section>` tag that the AI identifies as the "Executive Summary."
4. **Inject `Speakable` JSON-LD:** Use Hugo's internal templates to automatically inject the `Speakable` schema targeting the `.article-title` and `.tldr` selectors.
5. **Markdown Table Optimization:** Ensure all statistics and numbers (mortgage rates, budget deficits) are rendered as clean HTML `<table>` or Markdown tables. LLMs parse tables significantly better than narrative text for data-heavy queries.

---

## Recommendation
GEO is about **clarity over cleverness**. Optimize for "citations" not "clicks." If Perplexity cites uutistenlukija.fi, we win the 2026 search market.
