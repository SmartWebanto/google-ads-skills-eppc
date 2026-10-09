---
name: skill-054-geographic-performance-analysis
description: "Review geographic efficiency and service-area exposure without unsupported exclusion savings."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: targeting
  kind: deterministic
  data_source: custom_query
  merged_from: [skill-055-underperforming-location-exclusion]
  related: [skill-053-location-targeting-method-audit]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixTargetingQuality | evidence-led audit corrections"
---
# Skill 054: Geographic Performance Analysis

## Purpose

Compare geographic segments within comparable campaigns and identify defensible review
candidates for service-area alignment and performance. Retain former skill-055 exclusion
coverage, but do not equate non-converting spend with recoverable savings.

## Data Requirements

**Applicability:** Campaigns with geographic reporting; adjustment proposals require a
supported channel, strategy and geographic control. Presence and matched geography differ.

**Required inputs:** [DATA_CONTRACT](../_resources/DATA_CONTRACT.md) base files
`account`, `campaigns`, `campaign_metrics`, `bid_adjustments` and `bidding_strategies`.
Load campaign goals, lag maturity, location methods, current targets, exclusions and modifiers.
Client profile must supply service_area and campaign_objectives with intended remote buyers.
- `export/custom/geographic_performance.csv`: supplied Google Ads Locations report,
  one row per account_id, campaign_id, date, geo_level, geo_criterion_id, location_type,
  report_basis (user_location or matched_location), and any additional report segments.
  Columns: location_name, country_criterion_id, impressions, clicks, cost, conversions,
  conversion_value, source, currency, reporting_completeness; preserve unknown locations.
  Use the common mature 30-day window or declared longer window for sparse locations.
- Supplied geographic criterion lookup must be in `export/custom/geo_lookup.csv`:
  one row per geo_criterion_id, with name, parent_id, country_code, geo_level, source,
  snapshot_date from Google Ads geo-target data/UI. Radius targets retain center/radius.

**Missing inputs:** Without service area, skip relevance/exclusion claims. Missing location
basis or hierarchy prevents geographic rollups. Missing strategy blocks modifier proposals.
Metrics can still be summarized; unknown/withheld geography is not out-of-area traffic.

## Analysis Steps

1. Reconcile each campaign's geographic reporting coverage to campaign totals. Separate
   user-location from matched-location reports; never sum the two or parent/child levels.
2. Map one mutually exclusive level at a time to the service area. Check intended travelers,
   shipping coverage and existing exclusions before labeling apparently outside traffic.
3. Calculate CPA = cost/conversions, CVR = conversions/clicks and ROAS = value/cost.
   Compare each location with the rest of the SAME campaign and eligible goal cohort;
   account averages are descriptive only. Do not blend incompatible conversion goals.
4. Review CPA >1.5x or CVR <0.5x comparable baseline as adverse signals; CPA <0.7x is
   an opportunity hypothesis. Require corresponding sample gates on both sides.
   For zero conversions use the separate spend-floor review rule, never divide by zero.
5. Prioritize confirmed service mismatch and adverse efficiency by historical cost exposed.
   A small location sample, modeled location or conversion lag can explain apparent issues.
   Neither CPA differences nor out-of-area matched locations prove exclusion benefits.
6. For Manual CPC only, a supported modifier test may use raw multiplier = baseline CPA /
   location CPA; cap the incremental multiplier to 0.9–1.1 and multiply the existing positive
   bid multiplier. Record current/proposed values and verify platform range/interactions.
   This is a cautious test heuristic, not an optimum; no formula at zero CPA/conversions.
7. Smart Bidding already uses location signals: do not propose ordinary CPC adjustments.
   Consider geographic eligibility changes only for confirmed business coverage reasons,
   with owner review and measured trade-offs; do not auto-exclude expensive segments.
   Route positive/negative location-method conflicts to skill-053.

## Thresholds

| Condition | Severity |
|-----------|----------|
| Confirmed non-serviceable traffic with mature spend >= {{spend_floor}} | Warning |
| CPA >1.5x or CVR <0.5x comparable baseline with required samples | Warning |
| Zero conversions, verified tracking, mature spend >= {{spend_floor}} | Warning |
| CPA <0.7x comparable baseline with required samples | Info |
| Missing basis, intent, strategy, geography or sufficient sample | Info |

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
Include geography level/basis, criterion IDs, service-area decision, within-campaign
baseline, sample on both sides, current exclusions, and supported control/test proposal.
