# Monica Writer Architecture Cutover

Date: 2026-04-17
Owner: Felix
Implementer: Alex
Target role after cutover: Monica = dedicated final Finnish writer/editor worker

## Goal

Replace the current weak public writing lane with a quality-first lane where:
- code handles scanning, research, dedup, queueing, validation, publish, and quarantine
- Monica handles only the final Finnish article writing and editing step
- degraded or fallback content never reaches the public site
- one story becomes one writing job
- every article either passes a hard publication gate or goes to quarantine

This is a one-shot cutover plan, but it is separated day by day for implementation discipline.

---

## Final target architecture

### Responsibilities that stay in code
These remain deterministic Python pipeline responsibilities:
- feed scan
- dedup and event clustering
- source fetch and research cleanup
- story packet creation
- queue creation
- Monica job dispatch
- schema validation
- hard quality gate
- publish
- quarantine
- metrics and logs

### Responsibilities moved to Monica
Monica becomes a dedicated headless article worker for:
- final Finnish article writing
- Finnish editorial cleanup pass
- title and summary quality
- tone normalization into publication-quality Finnish

Monica should not:
- decide what gets published
- do feed scanning
- do broad product work during this role
- bypass schema or gate checks

---

## Hard principle

Bad articles must fail closed.

If Monica is unavailable, malformed, low-confidence, or the gate fails:
- do not publish
- quarantine instead

No public degraded mode.
No Gemini public fallback.
No emergency source-soup article building in the public lane.

---

## Exact queue flow

### Step 1: scan and dedup
Existing pipeline scans feeds and removes duplicates.

### Step 2: research cleanup
Before queueing, code must clean and rank sources.

Required source cleanup rules:
- max 2 to 4 source blocks per story packet
- drop thin blocks
- strip boilerplate, source labels, promo residue, excerpt junk, “continue reading”, and repeated nav/footer text
- keep source URLs and source names as internal metadata only

### Step 3: story packet creation
For each candidate article, create one structured packet.

Suggested file location:
- `pipeline/queues/monica/inbox/`

Suggested schema:
```json
{
  "packet_id": "2026-04-17T12-30-00Z_xxx",
  "created_at": "2026-04-17T12:30:00Z",
  "source_urls": ["..."],
  "source_names": ["Yle", "BBC"],
  "category_hint": "Kotimaa",
  "story_confidence": 0.92,
  "headline_seed": "...",
  "description_seed": "...",
  "language_mix": ["fi", "en"],
  "facts": {
    "who": ["..."],
    "what": ["..."],
    "where": ["..."],
    "when": ["..."],
    "why": ["..."],
    "consequences": ["..."]
  },
  "clean_source_blocks": [
    {"source": "Yle", "url": "...", "text": "..."},
    {"source": "BBC", "url": "...", "text": "..."}
  ],
  "editor_brief": "Write a clean Finnish news article from these facts."
}
```

### Step 4: Monica job dispatch
Dispatcher gives Monica one packet at a time.

Suggested runtime behavior:
- one article per Monica call
- no batch generation in the public lane
- strict JSON response contract

Suggested output location:
- `pipeline/queues/monica/outbox/`

### Step 5: Monica response schema
Monica must return strict JSON.

Suggested schema:
```json
{
  "packet_id": "...",
  "title": "...",
  "summary": "...",
  "content": "...",
  "category": "Kotimaa",
  "tags": ["...", "..."],
  "summary_bullets": ["...", "...", "..."],
  "content_type": "article",
  "editorial_reviewed": true,
  "confidence": 0.0,
  "notes": "internal only"
}
```

### Step 6: schema validation
Code validates:
- valid JSON
- required keys present
- strings non-empty where required
- allowed category only
- tags are list of strings
- content length above minimum

If invalid:
- move to quarantine
- log reason `schema_invalid`

### Step 7: hard publication gate
Only validated Monica output reaches the hard gate.

### Step 8: publish or quarantine
- pass = publish
- fail = quarantine

---

## Hard gate rules

These are mandatory blockers.

### Language blockers
Reject if:
- title contains substantial English
- summary contains substantial English
- body contains substantial English outside direct quotes
- title is still source-language when Finnish output is expected

### Structural blockers
Reject if:
- duplicated opener
- repeated paragraph block
- abrupt/truncated ending
- article has obvious section-template residue
- malformed H2 structure
- article is below minimum word count

### Source leakage blockers
Reject if body contains public-facing junk like:
- `Lähde:`
- `Alkuperäinen artikkeli`
- `Continue reading`
- excerpt residue
- promo residue
- source-site boilerplate

### Content coherence blockers
Reject if:
- title/body mismatch
- cross-story contamination
- category is obviously wrong
- lead does not state the actual news event clearly

### Confidence blockers
Reject if:
- Monica confidence below configured threshold
- story packet confidence too low
- source material too thin for trustworthy article generation

---

## What gets disabled immediately

These items must be removed from the public lane as part of the cutover.

### Disable immediately
- `gpt-4o-mini` as the primary final public writer
- batch multi-article rewrite generation in public path
- Gemini public fallback
- quota-exhausted “good enough” scoring behavior
- emergency quota fallback article builder for public publishing
- any degraded-mode article that can still pass into publish
- soft publish behavior when quality checks are inconclusive

### Keep only for non-public use if needed
These can exist only for drafts, experiments, or quarantine inspection:
- degraded article builders
- fallback content synthesis
- weak-model rescue flows

---

## Monica operating contract

Monica should be repurposed into a narrow production role.

### Monica prompt contract
Monica receives only:
- one story packet
- one strict output schema
- one role: publication-quality Finnish journalist/editor

Monica must not:
- invent facts
- preserve English unless it is a direct quote or required proper noun
- expose source labels in public copy
- improvise around thin evidence
- return prose outside schema

If evidence is too weak, Monica should return a structured failure, not a weak article.

Suggested failure response:
```json
{
  "packet_id": "...",
  "status": "INSUFFICIENT_CONFIDENCE",
  "reason": "source too thin / conflicting facts / unclear lead"
}
```

---

## File and module changes

### New modules likely needed
- `pipeline/story_packet.py`
- `pipeline/monica_queue.py`
- `pipeline/monica_dispatch.py`
- `pipeline/monica_schema.py`
- `pipeline/quarantine.py`
- `pipeline/validate_public_article.py`

### Existing modules to modify
- `pipeline/research.py`
- `pipeline/rewriter.py`
- `pipeline/quality_gate.py`
- `pipeline/run_pipeline.py`
- possibly `pipeline/publisher.py`

### Important implementation note
Do not just bolt Monica onto the current raw `rewriter.py` batch flow.
The public lane must be rerouted so Monica receives structured story packets, not giant mixed source blobs.

---

## Day-by-day implementation plan

## Day 1: cut the unsafe public lane and build the Monica job path

### Required Day 1 outcomes
- current unsafe public writer path disabled
- no degraded publish path remains
- story packet generation exists
- Monica dispatch path exists
- Monica output is validated through strict schema

### Day 1 tasks
1. add story packet builder
2. add Monica inbox/outbox queue structure
3. implement Monica dispatcher contract
4. switch public lane from current rewriter path to Monica job path
5. disable Gemini public fallback
6. disable degraded public publishing
7. force one-article-per-job
8. save all failures to quarantine instead of publishing

### Day 1 acceptance criteria
- pipeline can generate packets
- Monica can process at least one packet into valid JSON
- no invalid or fallback output can slip to publish

## Day 2: hard gate and quarantine discipline

### Required Day 2 outcomes
- hard blockers fully active
- quarantine becomes first-class behavior
- source leakage and English leakage are blocked automatically

### Day 2 tasks
1. add English leakage detection for title, summary, body
2. add source leakage detection
3. add duplicate opener / repeat block detection
4. add truncation detector
5. add category sanity check
6. add confidence threshold enforcement
7. store quarantine artifacts and reasons cleanly

### Day 2 acceptance criteria
- a known bad English article fails
- a known duplicated-opener article fails
- a known source-leakage article fails
- quarantine output contains exact failure reasons

## Day 3: stabilization and pipeline proof

### Required Day 3 outcomes
- sample production lane works end to end
- first clean publishable outputs appear
- automated proof/testing exists

### Day 3 tasks
1. run canary packets through Monica lane
2. compare pass/fail against known bad samples
3. tighten thresholds if weak samples still pass
4. ensure publish path only accepts gate-passed Monica output
5. run dry-run pipeline test
6. run live limited test if dry-run is clean

### Day 3 acceptance criteria
- no English-only public article from new lane
- no source-label leakage from new lane
- no duplicated opener from new lane
- at least one clearly publishable clean sample produced

---

## Alex implementation checklist

Alex should implement in this exact order:

1. create queue + packet scaffolding
2. cut out degraded public publishing
3. disable Gemini public fallback
4. reroute public lane to Monica dispatch
5. enforce one-packet one-article flow
6. add schema validation
7. add hard gate blockers
8. wire quarantine
9. dry-run pipeline
10. produce one proof bundle:
   - changed files
   - one passing clean sample
   - one blocked bad sample
   - exact remaining blocker if not complete

---

## Testing plan

### Unit-level tests
Add tests for:
- story packet generation
- Monica JSON schema validation
- English leakage rejection
- source leakage rejection
- repeated opener rejection
- truncation rejection

### Dry-run pipeline test
Test path:
- scan -> packet -> Monica -> schema -> gate -> quarantine/publish

Dry-run must prove:
- invalid Monica outputs do not publish
- known bad packets fail cleanly
- known decent packet passes

### Live limited test
After dry-run passes:
- run with max 1 to 2 articles
- inspect final outputs manually
- publish only if they pass gate and read cleanly

---

## Success definition

Cutover is successful when:
- public writing no longer depends on the old weak writer lane
- Monica handles final Finnish writing and editing
- bad outputs fail closed
- quarantine works normally
- first clean public output from the new lane is verified

---

## Proof bundle Alex must return

Alex’s completion update must contain all of this:
- files changed
- exact cutover point in code
- what was disabled
- one valid packet sample
- one valid Monica output sample
- one blocked bad sample with rejection reason
- dry-run result
- full pipeline test status

Anything less is not “done”.
