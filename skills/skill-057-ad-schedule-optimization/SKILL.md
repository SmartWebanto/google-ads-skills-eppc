---
name: skill-057-ad-schedule-optimization
description: "Analyze joint day-hour evidence and supported scheduling controls without inferring excluded-hour performance."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: targeting
  kind: deterministic
  data_source: external
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixTargetingQuality | evidence-led audit corrections"
---
# Skill 057: Ad Schedule Optimization

## Purpose

Find repeatable time-of-week patterns and operational coverage gaps. Produce a genuine
hour-by-day heatmap only from joint observations; separate hourly and daily marginal
reports cannot establish how a particular weekday-hour performs.

## Data Requirements

**Applicability:** Campaigns with time-segmented reporting and supported schedules. Confirm
business availability and lead handling; an unattended hour can still create valuable leads.

**Required inputs:** [DATA_CONTRACT](../_resources/DATA_CONTRACT.md) files `account`,
`campaigns`, `campaign_metrics`, `bid_adjustments` and `bidding_strategies`; load timezone,
conversion date basis/maturity, strategy, current schedule intervals and modifiers.
- `export/custom/day_hour_performance.csv` from a Google Ads report segmented jointly
  by date, day of week and hour, not two marginal reports. Row key: account_id,
  campaign_id, date, day_of_week, hour and any explicit channel/device segments.
  Columns: impressions, clicks, cost, conversions, conversion_value, source, timezone.
  Supply at least four complete comparable weeks when available; declare actual window.
- `export/custom/schedule_history.csv` from Ads settings/change-history exports:
  account_id, campaign_id, schedule_id, effective_start, effective_end, day_of_week,
  start_hour, start_minute, end_hour, end_minute, bid_modifier, timezone, source.
  One row per effective schedule interval; include all-day defaults explicitly.
- Client profile campaign_objectives and supplied `export/external/business_hours.csv`
  are required for availability conclusions: account_id, campaign_id, day_of_week,
  opens_at, closes_at, timezone, after_hours_handling, valid_from, valid_to, owner_source.
  One row per service/lead-handling interval; no staff or customer personal data.

**Missing inputs:** Marginal reports permit marginal diagnostics only; skip joint heatmap.
Absent schedule history makes historical eligibility unknown. Missing business hours blocks
operational exclusions, not performance summaries. Excluded hours are not zero performers.

## Analysis Steps

1. Align dates and hours to account timezone, including daylight-saving boundaries and
   partial days. Attribute conversions consistently; do not mix conversion-hour and click-hour.
2. Join schedule history to create observed-eligible, eligible-no-record, excluded and unknown
   cells. Only a complete report can establish a true zero; never fill all missing cells with zero.
3. Aggregate dates into campaign/day-of-week/hour cells and separately derive marginal totals
   from that SAME joint table. Show observed weeks, eligible hours and metric coverage per cell.
4. Compute CPA, CVR, ROAS and efficiency ratio = conversion share / cost share within
   the same campaign and goal. Require positive campaign conversions/cost and cell cost.
   Compare cell CPA/ROAS with the rest of the campaign only with samples on both sides.
5. Use efficiency <0.75 for adverse review and >1.25 for opportunity, consistently in all
   tables. Inspect complete-week persistence, holidays, promotions and lead-handling lag.
   Combining adjacent hours is permissible only with documented comparable intent/coverage.
6. For supported Manual CPC schedules, raw incremental multiplier = efficiency ratio;
   cap to 0.9–1.1 and multiply the current schedule multiplier within platform limits.
   Treat it as an initial test, not an optimum; do not size from sparse/zero-conversion cells.
7. Smart Bidding does not use ordinary schedule CPC modifiers; do not propose them.
   Eligibility restrictions require supported controls and explicit business rationale.
   For currently excluded hours, propose an owner-reviewed observation test if appropriate;
   there is no measured historical counterfactual for the excluded periods.

## Thresholds

| Condition | Severity |
|-----------|----------|
| Efficiency <0.75 with mature comparable samples | Warning |
| Zero conversions, working tracking, mature cost >= {{spend_floor}} | Warning |
| Schedule contradicts confirmed service/lead-handling requirement | Warning |
| Efficiency >1.25 with mature comparable samples | Info |
| Unobserved/excluded hours, marginal-only data or sparse joint cells | Info |

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
Include joint heatmap with missing/excluded states, observed weeks, timezone, effective
schedule, business-hours exceptions and supported bounded test proposals.
