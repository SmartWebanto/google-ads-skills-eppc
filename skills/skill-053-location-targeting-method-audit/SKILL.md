---
name: skill-053-location-targeting-method-audit
description: "Assess positive and negative geographic targeting against campaign business intent."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: targeting
  kind: deterministic
  data_source: export
  merged_from: [skill-063-locations-of-interest-exclusion]
  related: [skill-054-geographic-performance-analysis]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixTargetingQuality | evidence-led audit corrections; claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | owner_serving_evidence input for Critical"
---
# Skill 053: Location Targeting Method Audit

## Purpose

Own the location-method review, including the former locations-of-interest check (063).
Distinguish a settings mismatch from unproven out-of-area waste. Local businesses can
legitimately acquire future visitors, relocating customers, or purchasers buying for others.
Presence is not universally correct, and presence-or-interest is not universally wasteful.

## Data Requirements

**Applicability:** Campaigns exposing geographic targeting controls; record unsupported channels.

**Required inputs:** [DATA_CONTRACT](../_resources/DATA_CONTRACT.md) files:
- `account`: snapshot, timezone, currency, export window and completeness.
- `campaigns` and `bid_adjustments`: campaign IDs/status/channel, positive and negative
  geo method, included/excluded location criterion IDs, radii and current modifiers.
- `campaign_metrics`: cost and delivery for prioritization in the same window.
- Client profile: business_type, service_area and explicit campaign_objectives, including
  whether distant planners, travelers or remote purchasers are intended customers.
- Optional `keywords`, `ads` and `assets` with inherited entity associations may support
  local-intent review; local words/assets alone cannot establish the owner's intent.
- If base settings are incomplete, request `export/custom/geo_targeting_methods.csv`
  from campaign Location options and Locations UI, one row per account/campaign/criterion
  at snapshot: account_id, campaign_id, criterion_id, criterion_type, location_or_radius,
  excluded, positive_geo_target_type, negative_geo_target_type, source, snapshot_date.
- Optional `export/external/owner_serving_evidence.csv` (evidence_ref, campaign_id, intended_from,
  intended_to, material_basis): owner proof that a campaign was meant to serve; required for any Critical.

**Missing inputs:** No declared service area/intent means fit is unknown; missing settings
block only that method check. Missing metrics block spend priority, not settings inventory.
Do not infer business_type or disabled controls from campaign names or empty fields.

## Analysis Steps

1. Build the full campaign inventory, including paused campaigns separately from serving ones.
   Join by stable IDs, retain explicit unknown settings and note channel applicability.
2. Separate positive targeting (who may qualify) from negative targeting (who is excluded).
   Compare geographic inclusion, radius coverage, exclusions and the two location methods;
   do not confuse physical user location with a matched location of interest.
3. Compare each campaign to the declared service and acquisition intent. A local campaign
   limited to currently present buyers makes interest expansion a review candidate, not
   proof that all non-local impressions are irrelevant. Preserve intentional exceptions.
4. Review supplied copy/keywords/location assets as corroboration. Quote relevant evidence
   and mark semantic interpretation as analyst judgment. Do not use literal location words
   as a deterministic business classifier.
5. Identify exclusions contradicting desired coverage, redundant overlapping geographies,
   or method inconsistencies among campaigns with the SAME objective. Ask the owner to
   resolve contradictions; consistency itself is not a goal across different objectives.
6. Route measured geographic performance and service-area exposure to skill-054.
   Settings alone cannot quantify interest traffic, wasted spend or savings from Presence.
   A location-method proposal includes the exact current/proposed option and trade-off,
   intended visitor exception, owner approval requirement and post-change review window.

## Thresholds

| Condition | Severity |
|-----------|----------|
| Method conflicts with explicit campaign acquisition intent | Warning |
| Exclusion contradicts documented desired geographic coverage | Warning |
| Directly evidenced material delivery failure from contradictory geo settings | Critical |
| Intentional Presence or interest setup consistent with goals | Info |
| Local keywords/assets suggest intent but owner intent is unknown | Info |
| Settings, applicability, or service-area evidence unavailable | Info |

A Critical requires observed material failure, not a business label or optional setting.
Cost is priority context only; report it for the supplied window, not projected annual waste.
Geographic detection is imperfect; no method is a guarantee of a person's precise location.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a separate format.
Include stable account/campaign/ad-group/entity IDs, condition key, observed evidence and window,
sample, resolved thresholds, recommendation, uncertainty, and responsible owner.
List exact missing fields and dependent checks skipped; unknown does not mean passed.
Recommendations are request-only proposals; do not modify accounts or export files.
Historical exposure is not savings; no uplift forecast without an explicit counterfactual model.
Add positive/negative method, target and exclusion IDs, declared intent, fit rationale,
local-intent evidence provenance, exceptions, and measured vs unmeasured impact.
