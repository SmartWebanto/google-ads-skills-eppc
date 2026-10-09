---
name: skill-058-demographic-performance-analysis
description: "Diagnose demographic performance with channel, market, policy and control applicability gates."
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
# Skill 058: Demographic Performance Analysis

## Purpose

Describe age, gender and household-income performance without assuming inferred traits
are accurate or that exclusion improves results. Retain Unknown rather than asserting it
cannot be excluded; verify actual controls and policy before any targeting proposal.

## Data Requirements

**Applicability:** Age/gender where reported; household income only in supported markets
and channels, not a blanket US-only skill. Restricted products and sensitive categories
require policy/owner review; do not infer that a segment is permitted because it is reported.

**Required inputs:** [DATA_CONTRACT](../_resources/DATA_CONTRACT.md) `account`,
`campaigns`, `ad_groups`, `campaign_metrics`, `bidding_strategies` and `bid_adjustments`:
stable IDs, market/channel, goals, strategy, demographic criteria/modifiers/exclusions.
- Three independent Google Ads Demographics report exports:
  `export/custom/demographic_age.csv`, `export/custom/demographic_gender.csv`,
  `export/custom/demographic_income.csv`. Each row keyed by account_id, campaign_id,
  ad_group_id, criterion_id, date and segment_value, with impressions, clicks, cost,
  conversions, conversion_value, source and reporting_completeness. Common mature window.
  Preserve UNKNOWN and withheld data; unavailable reports are explicitly unavailable.
- `export/custom/demographic_controls.csv` from current demographic settings UI,
  one row per account/campaign/ad-group/dimension/segment: criterion_id, snapshot_date,
  market, control_type, current_value, permitted_min, permitted_max, supported,
  source_url. Include Unknown control eligibility instead of assuming it.
- Client profile business_type, campaign_objectives and any declared targeting constraints.

**Missing inputs:** Missing strategy/support blocks adjustment proposals. Missing one
report blocks only that dimension. No income report does not mean income targeting is off.
Policy uncertainty means no demographic restriction proposal pending specialist review.

## Analysis Steps

1. Establish channel/market and policy eligibility. Keep age, gender and income tables
   separate: these overlapping marginal dimensions cannot be summed into one audience total.
2. Reconcile each dimension independently to its campaign/ad-group totals and document
   hidden/unknown coverage. These reports do not reveal joint age-by-gender performance.
3. Calculate CPA, CVR, ROAS and efficiency = conversion share / cost share within a
   campaign/goal cohort. Use only positive denominators and comparable stable windows.
4. Compare each segment to the rest of the same campaign or ad group where targeting
   differs. Efficiency <0.7 is an adverse review; >1.3 an opportunity hypothesis.
   Apply the same boundaries everywhere and inspect uncertainty/multiple comparisons.
5. Keep Unknown as its own observed segment. It may include valuable users and incomplete
   demographic inference; neither its label nor weak aggregate efficiency warrants exclusion.
6. A Manual CPC modifier test is allowed only for a supported exported control. Use raw
   incremental multiplier = efficiency, capped to 0.9–1.1, multiplied by the existing positive
   multiplier within its permitted range; do not calculate from zero-conversion cells.
7. Under Smart Bidding do not propose ordinary demographic CPC modifiers. Any supported
   eligibility restriction needs owner intent and policy review, not rate-based automation.
   Recommend measurement and creative/landing-page relevance review before restrictions.
   Do not infer protected traits about individuals or export personal demographic data.

## Thresholds

| Condition | Severity |
|-----------|----------|
| Efficiency <0.7 with mature comparable samples | Warning |
| Zero conversions, working tracking, mature cost >= {{spend_floor}} | Warning |
| Efficiency >1.3 with mature comparable samples | Info |
| Unknown segment, unsupported control, policy uncertainty or sparse sample | Info |

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
Include separate dimension tables, criterion IDs, Unknown/withheld shares, eligible
market/channel, policy caveats, supported control and current/proposed values if justified.
