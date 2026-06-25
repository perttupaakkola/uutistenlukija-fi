# OPE-233 source-reject audit, 2026-06-24 19:15 UTC

Scope: current staged publish rejects after the OPE-228 source-confidence guard.
Inputs inspected:

- `pipeline/logs/staged-scan.log`, especially 2026-06-24 12:00-19:05 UTC scan cycles.
- `pipeline/logs/staged-monica-worker.log`, especially 2026-06-24 12:54-18:54 UTC.
- `pipeline/logs/quality_gate_rejects.log`.
- Current staged failed packets under `pipeline/queues/staged/failed/20260624T*.json`.
- Source-confidence implementation and tests: `pipeline/source_confidence_guard.py`,
  `pipeline/test_source_confidence_guard.py`, `pipeline/test_staged_publish.py`,
  and `pipeline/test_monica_writer.py`.

## Summary verdict

The current reject pattern does not show the OPE-228 source-confidence guard
overblocking normal Talous or general packets. The guard is intentionally narrow:
it only adds high-stakes denial/election-context failures for geopolitics or
similar source-risk stories.

The bigger yield pattern is split:

- Correct fail-closed behavior on packets with no usable source text, mismatched
  source/topic, or one very short block.
- Source-backed near-short writer failures where usable source packets produce
  200-249 word articles and repair sometimes adds zero useful words.
- Repeated Talous enqueue drops before Monica when two-source Talous packets have
  only 97-142 selected source words, below the current source floor.

Do not loosen the source-confidence guard or publish thin packets as a shortcut.
The next safe implementation target is narrower: improve the source-backed
near-short repair path so 240-249 word, 3-4 block packets can be expanded from
source material without invented facts. Talous still needs better source yield,
not relaxed public trust gates.

## Current counts

Command used to summarize current Jun 24 failed packets:

```bash
for f in $(find pipeline/queues/staged/failed -maxdepth 1 -type f -name '20260624T*.json' | sort); do
  jq -r --arg f "$f" '[($f|split("/")[-1]), (.packet.category // .payload.category // "?"), (.failure // "?"), (.writer_failure_feedback.selected_source_words // .packet.source_diagnostics.selected_source_words // 0), (.writer_failure_feedback.selected_source_blocks // .packet.source_diagnostics.selected_blocks // 0), (.writer_failure_feedback.final_word_count // 0), (.writer_failure_feedback.source_backed // false), (.writer_failure_feedback.near_miss_short // false)] | @tsv' "$f"
done
```

Result from 78 current Jun 24 failed packets:

- 31 had `content too short` failures.
- 32 were thin/no-source/mismatched-source failures that should fail closed.
- 22 were marked `source_backed=true`.
- 21 were marked `near_miss_short=true`.
- 5 were Talous; 3 of those were source-backed near-short content failures,
  and 2 were `weak_talous_ready_promotional`.
- Current Jun 24 failed packet sample had no new `source_confidence_*` failures.
  The visible source-confidence failures are Jun 23 high-stakes context rejects
  in `quality_gate_rejects.log`, not the main Jun 24 yield problem.

Current ready/outbox state at inspection time: no ready or outbox packets.

## Sample review

| Packet | Category | Evidence | Verdict |
| --- | --- | --- | --- |
| `20260624T183138Z_d1f43223ac.json` | Kotimaa | Yle source packet, 258 selected source words, 3 blocks, story confidence 0.98; final output 246 words; repair added 0 words and failed `content too short: 246 words`. | Needs rule/repair tweak. Source is usable; guard is not the problem. A tested repair pass should expand safely from the selected blocks. |
| `20260624T115124Z_1616e29356.json` | Talous | 319 source words, 3 blocks, source-backed and near-short; failed `content too short: 244 words`. | Needs repair tweak. This is the clearest Talous yield opportunity without lowering source standards. |
| `20260624T133126Z_c02166dd2d.json` | Talous | 281 source words, 4 blocks; failed after repair at 226 words. | Needs repair/writer prompt work, not source-floor relaxation. |
| `20260624T043130Z_bea473180b.json` | Talous | 313 source words, 4 blocks; failed at 241 words. | Needs repair tweak. Safe candidate class if expansion stays source-bound. |
| `20260624T171122Z_116d603d88.json` | Kotimaa | Only 48 source words, 1 block; Monica rejected because the source had only Teollisuusliitto reaction and did not explain the proposal background. | Correct fail closed. Publishing would require invention or external research. |
| `20260624T181120Z_7320a5f5ef.json` | Ulkomaat | 69 source words, 1 block; rejected as too thin for a 250-word article. | Correct fail closed. |
| `20260624T184119Z_2f1b2872ad.json` | Kotimaa | 41 source words, 1 block; missing-child item would require fresh confirmation. | Correct fail closed; also sensitive enough to avoid filler. |
| `20260624T004120Z_41439f9031.json` | Ulkomaat | Writer/selection mismatch: title was about Dutch euthanasia, source text was about a Hanko boating court case. | Correct fail closed. This protects public trust. |
| `20260624T051123Z_6458d0b276.json` and `20260624T124127Z_d678055b68.json` | Talous | Both failed `weak_talous_ready_promotional` despite 364-390 source words. | Correct fail closed unless a separate editorial product/revenue policy says influencer/company promo is desired. |

Public holdback/correction flags: none found for published content in this
sample, because the risky samples stayed out of ready/outbox/published.

## Talous enqueue drops

From 2026-06-24 12:00-19:05 UTC, `staged-scan.log` contains 32
`talous_enqueue_drop` scan events. The repeated drop class is:

- `drop_reason`: `source_floor_not_met`
- `research_bucket`: `research_enriched`
- `source_evidence_basis`: `selected_sources`
- common examples:
  - Finanssiala, 97-142 selected source words, 2 blocks.
  - Arvopaperi, 103 selected source words, 2 blocks.

Verdict: the current floor is doing trust-protection work. These packets are not
good candidates for automatic publication at 250 words unless the research stage
can find more source material or the product accepts shorter, clearly labelled
briefs as a separate tested format. There is no basis here to weaken the
existing article gate.

## Source-confidence guard assessment

`pipeline/source_confidence_guard.py` is narrow by design:

- It activates for `Ulkomaat` or high-stakes keywords.
- It checks whether source denial/contradiction or election uncertainty survives
  into public title, summary/key points, and lead.
- It returns `source_confidence_denial_context_missing` or
  `source_confidence_election_uncertainty_missing`.

The current Jun 24 source-yield failures are not mostly this guard. The guard's
recent visible value is Jun 23 high-stakes rejects such as Iran/Gaza context
loss in `quality_gate_rejects.log`.

Verdict: keep OPE-228 guard intact.

## Recommended follow-up

1. Create a narrow Alex implementation issue for source-backed near-short repair:
   packets with at least 240 output words, at least 250 selected source words,
   at least 3 selected source blocks, and `source_backed=true` should get a
   deterministic second repair instruction that forces 250-320 words from
   existing source facts only. Acceptance tests should cover:
   `20260624T183138Z_d1f43223ac`, `20260624T115124Z_1616e29356`, and a thin
   1-block packet that must still fail closed.
2. Keep Talous `source_floor_not_met` as fail-closed for normal articles until
   research/source acquisition improves. A separate brief-format experiment
   would need explicit template, labelling, and quality tests.
3. Monica/editorial watch should sample `weak_talous_ready_promotional` weekly.
   These rejects are probably healthy unless the business deliberately wants a
   sponsored/company-promotional lane, which would require approval and policy.

