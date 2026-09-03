---
name: ads
description: >
  Front desk for the Ads engine. Use for ANY Google Ads work — account audit,
  structure/keyword/bidding/budget review, conversion tracking, Quality Score,
  shopping/PMax, audiences/geo/device, compliance/disapprovals, seasonality,
  wasted-spend hunting, "why did CPA/ROAS change", or a campaign launch review —
  including vague requests ("controlla l'account Google Ads", "dove sto sprecando
  budget", "audit ads"). Routes the request into the ads-OS sub-app.
metadata:
  author: smartweb
  version: "1.0"
  category: engine-frontdesk
---

# Ads Engine — front desk

The studio Ads engine is the **`OS/ads-OS/` sub-app**: a deterministic, mock-first
TypeScript pipeline (rules → findings → Ads scoring → band P1/P2/P3/INFO →
human-approval gate) plus a Claude orchestration layer (19 analytic agents +
`ads-strategist`). It is **recommend-only**: it prepares changes and an approval
queue but never executes mutations. It runs fully without credentials.

It is backed by **145 Google Ads audit skills**, harvested into executable rules
under `OS/ads-OS/src/rules/` (the originals are retained read-only under
`.agents/skills/ads/_harvest/`). Nothing from the old skill library was lost — a
rule-coverage test enforces it.

## How to run Ads work

1. **Operate inside `OS/ads-OS/`.** Run a workflow with the dispatcher (mock by
   default; point `--input` at a `/google-ads` export dir with a `snapshot.json`):
   ```
   npm run ads-os -- audit --mock
   npm run ads-os -- audit --input data/google-ads
   npm run ads-os -- waste --input data/google-ads
   npm run ads-os -- tracking --input data/google-ads
   npm run ads-os -- monthly --input data/google-ads --month 2026-06
   npm run ads-os -- launch-review --brief ads/briefs/campaign.md
   ```
   Commands: `audit, waste, search-terms, keyword-hygiene, creative,
   budget-bidding, tracking, pmax-shopping, audience, seasonality, compliance,
   change-history, monthly, launch-review` (each also has an `:mock` npm alias).
2. **Validate the engine:** `npm test` and `npm run typecheck` from `OS/ads-OS/`.

## Output contract (surface in the dashboard)

Each run writes the operator deliverable — diagnosis + Now/Next/Later roadmap
(band · owner · approval) — to **`ads/reports/<YYYY-MM-DD>-<workflow>.md`**, the
machine-readable findings to **`ads/findings/<YYYY-MM-DD>-<workflow>.json`**, and
one action per P1/P2 to **`ads/actions/ads-<NNN>.md`**, so the studio dashboard
surfaces them under the `ads` area. The engine's working store
(`OS/ads-OS/reports/<account-id>/state.json` and `pending_changes.json`) stays local
to the sub-app.

## Rules

- **Recommend-only — never execute.** Every mutating change (budget, bidding,
  target CPA/ROAS, pause/enable, negative keywords, match types, final URL,
  conversion actions, audiences, geo targeting, live ad copy, PMax expansion,
  merchant feed, scripts/automation) is gated for human approval and written to
  `pending_changes.json`. Surface it under "Needs approval"; apply only via the
  operator execute/validate step.
- Never fabricate metrics — when no export/API is connected, run on the mock
  account or a provided `snapshot.json` and say which.
- One strategist pass per workflow; P1 is reserved for high waste, broken
  tracking, grave compliance/disapprovals, and blocked delivery.
