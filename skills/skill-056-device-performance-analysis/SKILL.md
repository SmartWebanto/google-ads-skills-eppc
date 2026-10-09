---
name: skill-056-device-performance-analysis
description: "Compare device performance with strategy-specific controls and mature campaign-relative evidence."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: targeting
  kind: deterministic
  data_source: custom_query
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixTargetingQuality | evidence-led audit corrections"
---
# Skill 056: Device Performance Analysis

## Purpose

Diagnose device efficiency and conversion experience without treating device membership
as a cause of poor performance. Separate Manual CPC adjustments, tCPA device target
behavior, and supported device exclusions instead of a blanket Smart Bidding exception.

## Data Requirements

**Applicability:** Campaigns with device metrics. Available devices and controls depend on
channel, campaign subtype and bidding strategy; connected TV is not necessarily comparable.

**Required inputs:** [DATA_CONTRACT](../_resources/DATA_CONTRACT.md) files `account`,
`campaigns`, `campaign_metrics`, `bidding_strategies` and `bid_adjustments`: stable IDs,
goals, targets, strategy type/ID, device exclusions/modifiers, lag maturity and units.
- `export/custom/device_performance.csv` from Google Ads campaign report segmented by
  date and device; key account_id/campaign_id/date/device plus any report segments.
  Columns: impressions, clicks, cost, conversions, conversion_value, source and window.
  Cover the common mature 30 days, preserving all device categories and unknowns.
- For control proposals, `export/custom/device_controls.csv` from current campaign
  Devices/bidding settings UI: account_id, campaign_id, device, snapshot_date,
  control_type (CPC_multiplier, CPA_target_adjustment, exclusion, unsupported),
  current_value, permitted_min, permitted_max, strategy_type, support_source_url.
  One row per campaign/device/control; omitted controls remain unknown.

**Missing inputs:** Missing controls means diagnostic-only output, not assumed applicability.
Missing industry benchmarks does not block within-campaign comparisons; do not invent them.
Missing mature goals/metrics blocks efficiency judgments, not the device inventory.

## Analysis Steps

1. Join settings and metrics by campaign IDs, normalize units and separate strategy changes
   into stable windows. Reconcile device totals to campaign totals before calculating shares.
2. Report cost, impressions, clicks, conversion and value shares. Calculate CPA, CVR and ROAS
   only when denominators are positive; zero-conversion CPA is N/A.
3. Compare each device against other devices within the same campaign/goal/window.
   Efficiency index = baseline CPA / device CPA - 1. Different acquisition mix, tracking,
   landing-page experience and lag can explain differences; no causal device claim.
4. Triage index < -0.2 as adverse review and > +0.2 as an opportunity. Inspect persistence
   across complete weeks before proposing a change; large deviations still need evidence.
   Retain zero-conversion spend as a tracking/relevance investigation, not automatic exclusion.
5. For supported Manual CPC adjustments, set raw incremental multiplier = 1 + index;
   cap to 0.9–1.1, multiply current bid multiplier and respect exported control bounds.
   Do not adjust already excluded devices or calculate a multiplier for N/A metrics.
   This bounded initial test is a heuristic, not estimated optimal bid sizing.
6. Under tCPA, a device adjustment can change the CPA target rather than CPC; verify the
   actual subtype/control and describe that target effect. Do not reuse the CPC formula.
   Under other Smart Bidding strategies, ordinary device modifiers are generally ignored;
   propose no adjustment unless current supported-control evidence establishes behavior.
7. A -100% or other device exclusion is not universally available or advisable. Confirm
   control support and business necessity, incremental conversion risk and owner intent.
   For poor device performance propose tracking/UX review before any eligibility restriction.

## Thresholds

| Condition | Severity |
|-----------|----------|
| Device efficiency index < -0.2 with comparable mature samples | Warning |
| Zero conversions with working tracking and mature cost >= {{spend_floor}} | Warning |
| Device efficiency index > +0.2 with comparable mature samples | Info |
| Unknown control, sparse sample, missing benchmark or unresolved tracking | Info |

Use [PARAMETERS](../_resources/PARAMETERS.md): CTR needs {{min_impressions}}, CVR
needs {{min_clicks}}, and CPA/ROAS needs {{min_conversions}} on BOTH comparison sides.
Exclude incomplete days and immature conversion-lag periods; align goals and date basis.
Undefined denominators produce N/A, not zero or infinity. Zero-conversion screening is
a separate exception: mature tracking-verified data and cost >= {{spend_floor}} permit
a Warning review, not an automatic pause. Numeric cutoffs below are triage heuristics.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a separate format.
Include stable account/campaign/ad-group/entity IDs, condition key, observed evidence and window,
sample, resolved thresholds, recommendation, uncertainty, and responsible owner.
List exact missing fields and dependent checks skipped; unknown does not mean passed.
Recommendations are request-only proposals; do not modify accounts or export files.
Historical exposure is not savings; no uplift forecast without an explicit counterfactual model.
Include device, baseline cohort, current modifier, strategy and control semantics,
raw index, bounded test values only when supported, and excluded/unobserved devices.
