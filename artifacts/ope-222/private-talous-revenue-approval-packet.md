# OPE-222 Private Talous Revenue Approval Packet

Generated: 2026-06-22 18:17 UTC

Status: private approval artifact only. No public post, schedule, Buffer/X/social API call, outbound email, spend, payment, credential, provider, or account change was performed.

## Recommendation

Ask Perttu to approve one restrained owned-channel utility test using the existing pörssisähkön varttihinnat packet.

Recommended first test: newsletter utility block, because the copy is practical, low-risk, and does not require account changes or public social posting.

Fallback if newsletter placement is not available: LinkedIn post using the same copy and UTM after explicit approval.

## Approval Gate Wording

Perttu, approve or reject one private-to-public Talous distribution test:

```text
Approve publishing the OPE-219 pörssisähkön varttihinnat utility copy as a newsletter utility block with the UTM link in that packet. Scope is one placement only, no paid boosting, no automated reposting, no DMs, no account/provider changes, and no social posting unless separately approved.
```

## Target Audience And Offer

Audience: Finnish readers with household electricity costs, especially readers who can shift flexible consumption such as laundry, dishwasher use, heating support, or EV charging.

Offer: a short practical reminder that pörssisähkö timing can vary by quarter-hour, with a clear warning that the article's prices are historical examples and readers must check current prices before acting.

## Source Packet

Use this existing private packet as the approved copy source:

```text
projects/uutistenlukija/artifacts/ope-219/private-utility-packet-spot-price-timing.md
```

The article URL and UTM template are already defined there. Re-check the live URL and headline before any approved placement.

Secondary inventory, do not use first unless Perttu rejects the electricity angle:

```text
projects/uutistenlukija/artifacts/ope-216/private-approval-packet-card-fraud.md
```

## Expected Learning Metric

Primary metric: sessions to the article from `utm_campaign=spot_price_timing` during the first 72 hours after approved placement.

Secondary metric: engagement or click-through from the article to `/categories/talous/` or other household-money/Talous content if available in analytics/referrer logs.

Decision rule: if sessions are meaningful with acceptable engagement, prepare one more household-money utility draft; if sessions are near zero, keep the angle but test a narrower audience or placement; if freshness/advice concerns appear, pause reuse and route copy to Monica/editorial review.

## Risk Controls

- Keep the timestamp and historical-price caveat in the copy.
- Do not promise savings or give financial advice.
- Do not imply the old prices are current.
- Do not broaden beyond one approved placement.
- Stop variants if readers challenge freshness, advice framing, or source trust.

## Blocker / Fallback Note

Iris has not posted the requested OPE-222 artifact in Linear by the 18:17 UTC Felix check, and direct agent-to-agent messaging returned `forbidden` for `agent:iris:main` with `tools.agentToAgent.allow`. This packet is Felix's narrow fallback artifact so the cycle produces business-progress evidence without public action.
