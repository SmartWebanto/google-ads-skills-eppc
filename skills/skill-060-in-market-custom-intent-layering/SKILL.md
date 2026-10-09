---
name: skill-060-in-market-custom-intent-layering
description: "Evaluate current audience segments with explicit comparison coverage and overlap limits."
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
# Skill 060: In-Market and Custom Segment Review

## Purpose

Review in-market and custom segments using current channel-specific mechanics. The legacy
skill identifier is retained, but unsupported custom_intent API fields and mandatory
competitor audiences are not. Absence of optional audience signals is not an account defect.

## Data Requirements

**Applicability:** Only audience types supported by the campaign channel/subtype. Custom
segments may be targeting inputs or signals depending on channel; do not assume Search
Observation support or that input keywords mean exact searches performed by every member.

**Required inputs:** [DATA_CONTRACT](../_resources/DATA_CONTRACT.md) `account`,
`campaigns`, `ad_groups`, `campaign_metrics`, `audiences`, `bidding_strategies` and
`bid_adjustments`; client profile business_type, objectives and competitor_terms if relevant.
- `export/custom/audience_segment_performance.csv`: Google Ads Audiences report,
  one row per account_id/campaign_id/ad_group_id/audience_id/criterion_id/date/mode
  and explicit report segments; impressions, clicks, cost, conversions, conversion_value,
  audience_type, source, reporting_completeness. Common mature reporting window.
- `export/custom/custom_segment_definitions.csv` from Audience manager/current campaign
  settings: one row per account_id/segment_id/input_id/snapshot_date with segment_name,
  input_type (keyword/URL/app), input_value, interpretation, channel_support, source.
  Include campaign/ad-group association IDs in `audiences`, not inferred from names.
- Only for non-audience comparisons, `export/custom/audience_exclusive_cohorts.csv`
  must be a supplied defensible non-overlapping report or experiment aggregation:
  account_id, campaign_id, ad_group_id, cohort_id, definition, date, impressions, clicks,
  cost, conversions, conversion_value, assignment_method, source, overlap_resolved.
  One row per mutually exclusive cohort/date; document exposed and unexposed definitions.
  If Ads cannot provide it, do not manufacture control traffic by subtracting audience rows.

**Missing inputs:** No exclusive cohort evidence means skip audience-versus-non-audience
inference; retain segment inventory/descriptive metrics. No custom definitions means
relevance unknown. Missing support or strategy blocks targeting/bid proposals only.

## Analysis Steps

1. Join all campaign inventory to associations and definitions. Classify in-market,
   affinity, custom segment or first-party list plus Targeting, Observation or signal use.
2. Describe overlap: a user may belong to multiple segments and reports are not additive.
   Never sum segment costs as total audience spend or subtract their sum from campaign cost.
3. Calculate segment CPA/ROAS descriptively. A campaign baseline includes the audience,
   so label it a contextual, non-independent comparison rather than a control.
4. If valid mutually exclusive cohorts are supplied, compare within the same campaign,
   goal and mature window using the assignment/overlap methodology. Observational cohorts
   still differ by intent; incremental lift requires an explicit controlled test design.
5. Review adverse CPA >1.5x a comparable exclusive cohort or ROAS <0.7x only with both
   sample gates; CPA <0.7x is an opportunity hypothesis, not automatic bid scaling.
6. Suggest optional relevant categories or custom inputs from explicit business intent.
   Explain URL/app/keyword input semantics, eligibility, policy and channel support.
   Neither competitor input absence nor no in-market segments is inherently an issue.
7. Ordinary audience modifiers are not a Smart Bidding control. With supported Manual CPC,
   a bounded owner-reviewed test can use baseline CPA / segment CPA as a raw multiplier,
   capped to 0.9–1.1 times current multiplier, only with exclusive comparable evidence.
   Record overlap with other modifiers and platform limits; otherwise propose no bid value.

## Thresholds

| Condition | Severity |
|-----------|----------|
| CPA >1.5x or ROAS <0.7x valid comparison with mature samples | Warning |
| Verified targeting/signal use contradicts documented business intent | Warning |
| CPA <0.7x valid comparison with mature samples | Info |
| Optional relevant segment not used or valid control unavailable | Info |
| Unknown overlap, mechanism, definition, support or sample | Info |

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
Include segment/criterion IDs, mechanism, overlap caveat, definition provenance,
comparison method and separate descriptive metrics from causal test hypotheses.
