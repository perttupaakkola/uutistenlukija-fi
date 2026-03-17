# Research → Implementation Workflow

**Owner:** Monica (research) → Alex (implementation)
**Applies to:** All uutistenlukija.fi improvement cycles

## Process

### 1. Research Phase (Monica)
- Analyze competitors, market, keywords, or whatever the domain requires
- Produce structured findings with data and sources

### 2. Plan Phase (Monica)
- Turn research into a **concrete, prioritized action plan**
- Split into: **technical tasks** vs **content tasks**
- Technical = code, routes, schema, config, infrastructure
- Content = text templates, anchor patterns, copy rules, topic definitions

### 3. Handoff to Alex (Monica → Alex)
- Tag `<@1482106603468492921>` in `#development` (1482082568169066667)
- Include ALL technical implementation details: file paths, components, data structures
- For content changes: specify exactly what text/templates go where
- Be specific enough that Alex can implement without asking clarifying questions

### 4. Report to Felix (Monica → Felix)
- Tag `<@1482068741822087279>` in `#research` (1482720265174782055)
- Summary of what was planned and delegated
- Any open questions or blockers
- Any items needing Perttu's approval

### 5. Felix tracks via agent-health.json
- Felix updates task state and monitors completion

## Key Principles
- **Always end research with actionable tasks** routed to the right agent
- **Never leave research as just a report** — it must become work items
- **Tag agents explicitly** — plain text names don't trigger notifications
- **Content specs must be implementation-ready** — no vague "improve the copy"
