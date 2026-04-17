# Uutistenlukija Finnish Quality Revamp Plan

Date: 2026-04-17
Owner: Felix
Status: Proposed, ready for implementation

## Executive summary

The current pipeline is good enough at keeping articles flowing, but not good enough at protecting publication quality.

The main failure is architectural, not cosmetic:
- raw multi-source research is fed too directly into the writer
- the writer batches multiple articles per model call, which increases cross-article contamination and truncation
- cheap-model fallback paths are allowed to publish
- quality gates are too soft and are compensating for upstream weaknesses instead of blocking them
- low-confidence or degraded articles are still allowed into the publish path

If we want publication-level Finnish, we must change the contract of the pipeline:
- better to publish fewer articles than bad articles
- degraded mode can keep drafts moving, but degraded mode must not publish
- every article must pass both hard deterministic checks and an editorial-quality pass

## What the current code is doing wrong

### 1. The writer is underpowered for the job
Current rewriter architecture in `pipeline/rewriter.py`:
- pass 1 uses `gpt-4o-mini`
- pass 2 audit also uses `gpt-4o-mini`
- escalation to stronger rewrite happens only for very low-scoring articles
- when quota is exhausted, quality scoring returns a synthetic good-enough score and degraded content can continue downstream
- broken Gemini fallback paths still exist in the critical path

Why this fails:
- publication-grade Finnish synthesis is a high-complexity task
- `gpt-4o-mini` is acceptable for support tasks, but not as the primary publication writer for noisy multi-source Finnish journalism
- quota/degraded behavior currently optimizes continuity over quality, which is the wrong tradeoff for a newspaper product

### 2. Batch rewriting is causing contamination and truncation
Current writer behavior:
- multiple articles are generated in one batch call
- code comments already admit article cuts happen in larger batches

Why this fails:
- mixed source context increases story bleed between articles
- one weak article in the batch can destabilize the whole response
- long outputs create title/body mismatch, truncation, and duplicated openings

### 3. Research output is too raw and too loosely structured
Current research behavior in `pipeline/research.py`:
- source blocks are concatenated and passed downstream as semi-clean text blobs
- source labels, thin extraction, and boilerplate still leak into the writer context

Why this fails:
- the model is forced to do extraction, source selection, synthesis, translation, structure, and copyediting in one pass
- source boilerplate and English fragments contaminate the Finnish article
- the model can overfit to whichever source block is most dominant or most recently seen

### 4. The quality gate is too permissive
Current gate behavior in `pipeline/quality_gate.py`:
- `REJECT_THRESHOLD = 30`
- `DEFAULT_NORMALIZED_THRESHOLD = 3.5`
- gate is acting as a soft scoring layer instead of a strict publication blocker
- current live metrics show `rejected = 0` repeatedly, even while bad public articles are visible

Why this fails:
- if the gate never rejects, it is not functioning as a publication safety system
- English titles, source leakage, wrong category, duplication, and truncation are clearly still escaping

### 5. No quarantine lane exists as a first-class product behavior
Current behavior:
- articles tend to move toward publish if anything usable exists

Required behavior:
- low-confidence or degraded articles must go to quarantine, not public site
- “no publish” must be treated as success when quality standards are not met

## Recommended target architecture

This is the recommended architecture for this setup.

### A. Story intake and clustering
Goal: reduce noisy inputs before writing begins.

Changes:
- keep scanner and research discovery cheap
- cluster articles by event/story before writing
- limit each article to 2 to 4 high-value primary sources, not a long loose pile
- rank sources by reliability, specificity, and freshness
- prefer Finnish or high-quality English sources with clean extraction
- drop thin, duplicate, or boilerplate-heavy source blocks earlier

Output of this stage:
- one `story packet` per article candidate
- each packet contains:
  - headline candidate
  - primary category candidate
  - primary facts
  - named entities
  - timeline
  - quotes
  - source URLs
  - confidence score
  - unresolved ambiguities

Important rule:
- the writer should receive a structured story packet, not raw source soup

### B. Structured fact extraction stage
Goal: separate journalism facts from prose generation.

New stage to add:
- `fact_extractor.py`

Responsibilities:
- extract normalized event facts into JSON
- mark unsupported claims and contradictory claims
- identify missing core elements: who, what, where, when, why, consequence
- normalize names, places, dates, and source attributions
- produce a short “editor brief” in English or Finnish for downstream writing

Suggested model tier:
- cheap/medium model is okay here if output is structured and validated
- this stage can use `gpt-4o-mini` or similar cost-efficient model

Reason:
- structured extraction is exactly where cheaper models help without harming final copy quality

### C. Primary Finnish writer
Goal: produce one strong Finnish article per story.

New rule:
- one article per model call
- no multi-article rewrite batches in the publish path

Suggested model strategy:
- recommended default writer: a stronger OpenAI model than `gpt-4o-mini`
- best fit for this setup: `gpt-5.4` or another top-tier OpenAI writing model available in your stack
- if cost needs trimming later, keep strong model for final writer while keeping extraction cheaper

Writer input:
- structured story packet
- editorial style guide
- category-specific expectations
- banned output patterns
- explicit “never publish source labels / untranslated boilerplate / English title / duplicated opener / generic ending” rules

Writer output schema:
- title
- deck/summary
- lead
- section blocks
- category
- tags
- image prompt/query
- source notes (internal only, not for publishing)
- confidence

Hard rules for writer:
- Finnish only for title, summary, and body unless a direct quote must remain in source language
- no source labels in body
- no vague generic ending
- no filler conclusion if facts are thin
- if facts are too thin, writer must return `INSUFFICIENT_CONFIDENCE`, not improvise

### D. Native Finnish editor pass
Goal: make the output sound publishable, not machine-translated.

New stage to add:
- `finnish_editor.py`

Responsibilities:
- improve idiomatic Finnish
- remove literal translation phrasing
- fix rhythm and sentence weight
- ensure title-body coherence
- remove duplication, padding, and awkward subheads
- verify category fit

This is not the same as the writer.
This is an editorial cleanup pass with a different prompt and stricter role.

Suggested model strategy:
- same strong model as writer, or one tier lower if quality remains strong in testing
- if budget allows, keep both writer and editor on the stronger model during rollout

### E. Hard publication gate
Goal: treat publication as a strict pass/fail system.

The gate should combine deterministic blockers and editorial scoring.

#### Deterministic hard blockers
These should reject automatically:
- title contains substantial English
- body contains substantial English outside direct quotes
- duplicated opener or repeated paragraph blocks
- truncated ending or abrupt final sentence
- source leakage such as “Lähde:”, “Alkuperäinen artikkeli”, newsroom boilerplate, promo residue
- article word count below category minimum
- category confidence below threshold
- missing core structure: title, summary, lead, body
- unresolved placeholder text
- story packet confidence below minimum

#### Editorial quality scoring
After deterministic blockers pass, run an editorial scorer.

This scorer should evaluate:
- idiomatic Finnish
- factual clarity
- coherence
- non-repetitiveness
- category fit
- publishability

New threshold recommendation:
- raise the normalized publish threshold substantially
- stop treating 3.5/5 as publishable for the final public lane
- initial rollout threshold should be strict enough that obviously weak articles do not pass

### F. Repair or quarantine, never blind publish
Goal: preserve automation without public embarrassment.

New flow:
- first failure: one repair attempt
- second failure: quarantine
- no article gets more than one automatic repair cycle in the publish lane

Quarantine output should store:
- article slug
- source URLs
- failure reasons
- gate metrics
- model outputs

That creates a usable review queue and a training/evaluation set.

## Recommended model and cost strategy

## Preferred setup

### Cheap where it is safe
Use a cheaper model for:
- clustering
- fact extraction
- metadata normalization
- image query generation
- non-public support tasks

### Expensive where it matters
Use a stronger model for:
- final Finnish article generation
- native Finnish editorial pass
- borderline repair attempts

## Recommended operating mode for current setup

### Option 1, recommended
- research/fact extraction: `gpt-4o-mini`
- primary writer: `gpt-5.4`
- Finnish editor: `gpt-5.4`
- optional repair pass: `gpt-5.4`

Why this is the best fit:
- it keeps the expensive tokens concentrated only on deduped story candidates
- it avoids paying top-tier cost on the noisy feed stage
- it matches the actual problem: writing and editing quality, not scanning quality

### Option 2, lower-cost compromise
- research/fact extraction: `gpt-4o-mini`
- primary writer: `gpt-4.1` or comparable stronger non-mini writer
- Finnish editor: `gpt-4.1`
- escalate only worst borderline cases to `gpt-5.4`

This may be enough, but I would not start here if the current quality is already unacceptable.

### Option 3, full premium
- stronger model for extraction, writing, and editing

I do not recommend starting here. It is expensive and unnecessary before the architecture is fixed.

## What must be removed or disabled immediately

These changes should happen before any deeper rewrite work.

### 1. Remove degraded publication behavior
If quota is exhausted or the strong writer is unavailable:
- do not publish
- quarantine instead

### 2. Remove broken Gemini fallback from the public lane
If Gemini is currently failing or producing unreliable output, it should not sit inside the critical publish path.

### 3. Remove synthetic “good enough” scoring on quota exhaustion
No code path should ever assign a safe score to content that was not truly evaluated.

### 4. Stop batch rewriting in the publish lane
One story, one call.

### 5. Raise gate strictness immediately
Even before the full rebuild:
- reject English title/body
- reject duplicated opener
- reject source leakage
- reject truncation

## Full scope implementation plan

## Phase 0, emergency quality containment, same day
Goal: stop public embarrassment quickly.

Changes:
- disable degraded publishing
- disable Gemini fallback in public pipeline
- remove quota-exhausted “score 4” behavior
- move to single-article rewriting for public lane
- add hard reject rules for English leakage, duplication, truncation, source leakage
- raise publication threshold
- treat “no publish this cycle” as acceptable

Acceptance criteria:
- zero fully-English public articles
- zero duplicated openers in new posts
- zero obvious source-label leakage in new posts
- rejection count becomes non-zero when bad articles are present

## Phase 1, structured story packet refactor, 1 to 2 days
Goal: stop feeding raw source soup into the writer.

Changes:
- add story packet JSON layer
- split extraction from writing
- restrict article source context to best 2 to 4 sources
- normalize facts and unresolved ambiguities

Acceptance criteria:
- story packets are inspectable on disk/logs
- writers no longer receive raw concatenated research blobs as primary input
- cross-story contamination rate drops clearly in sampled outputs

## Phase 2, new Finnish writer + editor path, 2 to 4 days
Goal: get from acceptable facts to publication-level Finnish.

Changes:
- new writer prompt and schema
- dedicated Finnish editorial pass
- one article per call
- explicit category-aware writing rules
- explicit anti-pattern bans

Acceptance criteria:
- sampled titles are consistently idiomatic Finnish
- body no longer reads like translated source notes
- title, summary, and body stay aligned
- category accuracy improves on new batch samples

## Phase 3, real publication gate and quarantine queue, 1 to 2 days
Goal: make quality control reliable, not cosmetic.

Changes:
- deterministic blockers
- editorial score pass
- one repair attempt max
- quarantine queue with reason logging

Acceptance criteria:
- clearly weak articles are rejected before publish
- quarantine folder/log contains actionable reasons
- `rejected` metric reflects reality

## Phase 4, evaluation harness and regression suite, 1 to 2 days
Goal: keep quality from silently regressing.

Changes:
- build a gold set of 50 to 100 real story packets
- save expected traits and failure labels
- create repeatable evaluation runner
- compare pass rate, language leakage, category accuracy, duplication, and truncation over time

Acceptance criteria:
- every prompt/model change is testable before full rollout
- quality improvements are measured, not guessed

## Phase 5, throughput tuning after quality is stable
Goal: scale volume safely.

Changes:
- only after quality is stable, optimize cost and throughput
- consider smaller editor for easy stories
- consider category-based routing by difficulty
- restore higher publish frequency only when quality metrics stay stable

Acceptance criteria:
- quality remains stable while volume rises
- no return to soft degraded-publication shortcuts

## Operational policy changes

These are as important as code changes.

### 1. Change success definition
Old definition:
- success = articles were published

New definition:
- success = only publishable articles were published

### 2. Add a “quality-first fail-safe”
When writer/editor/gate confidence is low:
- skip publish
- keep the pipeline healthy
- log the blocked article for repair or later retry

### 3. Treat quality incidents like production incidents
Quality issues should trigger the same seriousness as publishing outages.

### 4. Use live canary sampling
On every deploy/change:
- sample the first 3 to 5 public articles
- inspect manually or with stricter QA logic
- only widen rollout after those pass

## Files likely to change

Core files:
- `pipeline/research.py`
- `pipeline/rewriter.py`
- `pipeline/quality_gate.py`
- `pipeline/run_pipeline.py`
- `pipeline/publisher.py`

New files likely needed:
- `pipeline/fact_extractor.py`
- `pipeline/story_packet.py`
- `pipeline/finnish_editor.py`
- `pipeline/quarantine.py`
- `pipeline/evaluate_quality.py`
- `tests/test_story_packets.py`
- `tests/test_finnish_quality_gate.py`
- `tests/test_rewriter_regressions.py`

## Concrete recommendation

I recommend we do this as a controlled rebuild of the quality path, not another small patch round.

The most sensible setup for this stack is:
- keep feed scanning and extraction relatively cheap
- move final writing and editing to a stronger OpenAI model
- eliminate degraded publishing
- add quarantine as a normal outcome
- add a strict publication gate
- add an evaluation harness so improvements do not regress

## My recommendation on scope and sequence

If we want the fastest sensible route to publication-grade Finnish, do this in order:

1. same-day containment
   - remove degraded publication behavior
   - remove broken fallback behavior
   - add hard blockers

2. next, rebuild the content path
   - story packet extraction
   - one-article writer
   - Finnish editor pass

3. then harden operations
   - quarantine queue
   - evaluation suite
   - metrics and regression tests

## Non-negotiable principle

A robust publication pipeline does not guarantee that every cycle publishes.
It guarantees that bad articles do not publish.

That is the architectural shift we need.

## Suggested acceptance targets

I would use these rollout targets for the new public lane:
- zero fully-English public articles across 7 days
- zero source-label leakage across 7 days
- zero duplicated opener failures across 7 days
- category accuracy high enough that obvious misclassification becomes rare
- at least 90 percent of sampled public articles judged clearly publishable
- quarantine rate accepted as normal during rollout

## Immediate next step

If approved, implementation should start with Phase 0 and Phase 1 together:
- lock down the current publish lane
- build structured story packets
- then replace the current writer/editor path on top of the new packet format
