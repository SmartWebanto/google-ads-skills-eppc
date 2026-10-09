---
name: skill-066-historical-quality-score-trend
description: "Analyze native daily historical QS and component transitions using stable keyword cohorts."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: quality
  kind: deterministic
  data_source: custom_query
  related: [skill-064-quality-score-distribution-analysis, skill-065-quality-score-component-breakdown, skill-067-expected-ctr-improvement]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixTargetingQuality | evidence-led audit corrections"
---
# Skill 066: Historical Quality Score Trend

## Purpose

Google Ads DOES provide native historical Quality Score and its component columns, with
changes viewable by day. Use them to investigate keyword-level transitions, not to optimize
an account score or infer CPC savings, competitive pressure or causal business deterioration.
Source: [Google Ads: About Quality Score](https://support.google.com/google-ads/answer/6167118?hl=en) (historical columns and daily segmentation).

## Data Requirements

**Applicability:** Search keyword historical QS where available. Native reporting is the
preferred source; externally saved current snapshots are an explicitly labeled alternative,
not a prerequisite invented on the premise that Google stores no history.

**Required inputs:** [DATA_CONTRACT](../_resources/DATA_CONTRACT.md) `account`,
`campaigns`, `ad_groups`, `keywords` and `keyword_metrics` for inventory/current context.
- `export/custom/quality_score_history.csv`: from Google Ads Keywords UI, add Quality
  Score (hist.), Exp. CTR (hist.), Ad Relevance (hist.) and Landing Page Exper. (hist.),
  segment by Day and include account, campaign, ad-group and criterion IDs. Export the
  complete requested 60-day interval (or declared alternative), without an impression filter.
  Row grain/key: account_id, campaign_id, ad_group_id, criterion_id, date.
  Required normalized columns: keyword_text, match_type, keyword_status,
  historical_quality_score, historical_expected_ctr, historical_ad_relevance,
  historical_landing_page_experience, impressions, clicks, cost, conversions,
  conversion_value, source, extracted_at. Preserve unavailable scores/components as null.
  The source must say native_historical; dates use account timezone and metrics share basis.
- Alternative `export/custom/quality_score_snapshots.csv`: same IDs and fields, with
  snapshot_date instead of date, source=current_snapshot, captured_at and original
  metric_window_start/end. The historical_* columns hold captured current values only;
  label this distinction in every comparison. Do not mix native history and snapshots.
- Optional `export/custom/quality_change_history.csv` from Ads change history:
  account_id, campaign_id, ad_group_id, criterion_id_or_ad_id, changed_at, field,
  previous_value, new_value, source; one row per change over the compared interval.

**Missing inputs:** No history means no trend; report current diagnostics through 064/065.
Missing IDs prevents text-only joins. Missing a component blocks that component's transition
only; missing change history prevents causal explanation, not measured QS differences.

## Analysis Steps

1. Validate source type, dates, null conventions and uniqueness of the full entity/date key.
   Deduplicate identical exports; conflicting same-key values require source reconciliation.
   Current quality_info values selected with historical metrics are not historical QS.
2. Choose explicit baseline and comparison dates or equal complete windows. For a window,
   use each keyword's last available native daily rating within that window and disclose
   the actual observation dates; never fill missing dates or carry scores across unobserved gaps.
3. Build a matched cohort by stable account/campaign/ad-group/criterion IDs with non-null
   scores on both sides. Same text in another ad group or a recreated criterion is a new entity.
   Report entrants, exits, paused/removed keywords and null-to-rated transitions separately.
4. Compare per-keyword QS points and categorical components. Record 2+ point declines
   as review candidates, plus Average/Above Average to Below Average component transitions.
   Neither five declining keywords nor a lower aggregate score establishes Critical harm.
5. Report transition counts and matched-cohort coverage by campaign, match type and ad group.
   Compare the SAME matched cohort before/after so new low-QS keywords do not manufacture
   deterioration. Do not use changing impression weights to claim a within-keyword decline.
6. Rank investigation by mature cost exposure, not an aggregate QS target. Review change
   history where supplied; temporal correlation with ad/page changes is a hypothesis.
   Do not infer landing-page grouping without actual URL associations or competition from QS.
7. For business-metric comparisons, align mature goals/windows and use sample gates on both
   sides. A QS decline alone does not prove a CTR, CPA or ROAS decline. Propose owner-reviewed
   diagnostic follow-up via 067/068/069, not automatic bids, pauses or score-uplift forecasts.

## Thresholds

| Condition | Severity |
|-----------|----------|
| Matched keyword declines >=2 QS points with cost >= {{spend_significant}} | Warning |
| Component becomes Below Average with cost >= {{spend_significant}} | Warning |
| Score decline without material exposure or independently evidenced business harm | Info |
| Entrants/exits, unavailable history, missing IDs or unmatched cohort | Info |

Point/spend cutoffs are triage heuristics; no QS-only finding is Critical.
Use {{min_impressions}} for CTR, {{min_clicks}} for CVR and {{min_conversions}} for
CPA/ROAS on both mature sides under [PARAMETERS](../_resources/PARAMETERS.md).

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a separate format.
Include stable account/campaign/ad-group/entity IDs, condition key, observed evidence and window,
sample, resolved thresholds, recommendation, uncertainty, and responsible owner.
List exact missing fields and dependent checks skipped; unknown does not mean passed.
Recommendations are request-only proposals; do not modify accounts or export files.
Historical exposure is not savings; no uplift forecast without an explicit counterfactual model.
Include native-vs-snapshot source, exact paired dates, matched-cohort denominator,
entrants/exits/nulls, point/component transitions and evidence versus causal hypotheses.
