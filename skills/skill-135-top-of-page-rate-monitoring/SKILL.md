---
name: skill-135-top-of-page-rate-monitoring
description: "Distinguish served-impression prominence rates from estimated eligible-impression shares without equating visibility with profitable performance."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: competitive
  kind: analyst
  data_source: custom_query
  related: [skill-121-impression-share-loss-analysis]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixOperationsSeasonal | corrected evidence and controls; gpt-6-astra | openai | 2026-09-06 | s_20260906_fix | native weekly aggregation evidence"
---
# Skill 135: Top and Absolute-Top Metric Review

## Purpose

Distinguish served-impression prominence rates from estimated eligible-impression shares without equating visibility with profitable performance.

This is a local evidence review. Recommendations are proposals, not permission to act on an account or disclose client data.

## Data Requirements

**Applicability:** Google Search reporting with actual native top-rate metrics; exclude unsupported Search partner position data.

**Required inputs:**
- Base `export/` tables: account, campaigns, campaign_metrics, using [DATA_CONTRACT](../_resources/DATA_CONTRACT.md).
- Read client objectives, parameter overrides, currency, timezone, snapshot, report completeness, conversion-date basis and lag maturity.
- `export/custom/search_prominence_daily.csv`: account_id/campaign_id/ad_group_id/date/network grain; impressions, clicks, cost, conversions, conversion_value, top_impression_rate, absolute_top_impression_rate, search_top_impression_share, search_absolute_top_impression_share, rate_counting_basis, share_censoring; Ads native prominence columns for 8 full weeks, with source definitions.
- For weekly comparisons, `export/custom/search_prominence_weekly.csv`: the same account/campaign/
  ad_group/network dimensions and native metric columns, with period_start, period_end, source and
  extracted_at instead of date. Export each exact complete comparison week natively from Ads;
  preserve the source counting conventions/censoring rather than deriving weekly shares from daily rows.
- Optional `export/custom/position_outcomes.csv`: account_id/campaign_id/date/position_segment grain; segment_definition, impressions, clicks, cost, conversions, conversion_value; supported Ads position-segment report for the same window. Campaign rate tiers are NOT position-segment outcomes.

Keep original source labels and stable IDs; filenames are suggested local intake paths, not assumed existing files.
Custom/configuration schemas describe UI/export evidence, not a claim of live API field verification.

**Missing inputs:** List exact missing files/columns, source dates and affected subchecks.
Continue independent inventory or arithmetic with available evidence; skip only dependent checks.
Optional evidence gates only its stated deeper comparison, forecast or test-result analysis.
Absent native weekly values blocks only weekly aggregates unless source-compatible numerator/denominator
weights are explicitly supplied; retain descriptive daily rates and label unsupported weekly cells unavailable.
Unknown settings, authorization, coverage or policy applicability are not false/disabled and are not a passed check.

## Analysis Steps

1. Preserve native Impr. (Top)% and Impr. (Abs. Top)% as served-search prominence rates; shares use estimated eligible top opportunities. Do not relabel top IS as a served-impression rate.

2. Use native rate counting conventions, which may count only the most prominent impression per advertiser/search. Do not reconstruct rates from campaign-table impressions when counting bases differ.

3. Compare native complete-week reports at the same grain with {{min_impressions}} on both sides.
   Daily rates alone cannot produce weekly rates or shares: never average shares or weight prominence
   by ordinary impressions unless source counting bases and actual denominators are compatible.
   Report supported rate differences in percentage points and label relative changes separately.

4. Compare with explicit client visibility objectives, goal CPA/ROAS and budget constraints. Brand terms come from profile, not a universal 80% rule.

5. Only real position-segment outcomes can support descriptive performance by position; even these are not randomized causal effects. Top-rate trends alone do not justify bid increases or diagnose competitors.

6. Route lost-share investigation to skill-121 and strategy review to skill-039. Propose a controlled visibility/economics test only when the business objective requires it.

Use matched IDs and declared grain before joining; never multiply entity metrics across many-to-many associations.
For comparisons, align goals, traffic scope and complete periods; exclude incomplete days and conversion reporting lag.
Use {{min_impressions}} for CTR/share, {{min_clicks}} for CVR and {{min_conversions}} for CPA/ROAS, on both comparison sides.
A zero-conversion spend screen may bypass min_conversions only after maturity, working tracking and relevance review at {{spend_floor}}.
Do not divide by zero; preserve censored, suppressed and unknown values rather than treating them as zero.
Historical non-converting cost is exposure, not guaranteed savings; observational changes are not causal uplift.

## Thresholds

Numerical cutoffs here are triage heuristics unless explicitly tied to a sourced platform requirement.
Resolve parameters through [PARAMETERS](../_resources/PARAMETERS.md); business tolerances require a declared value.

| Condition | Severity |
|---|---|
| Mature prominence decline exceeds client tolerance and conflicts with stated visibility goal | Warning |
| Low top rate/share alone, no goal, or incompatible counting bases | Info |

Insufficient evidence or sample is Info. Critical requires directly evidenced material delivery, measurement or safety failure.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a conflicting report format.
Each finding includes skill/entity IDs, condition key, severity, observed values and evidence references, exact window,
sample, resolved threshold, recommendation, uncertainty, responsible owner and dependent skipped subchecks.

- Daily native rates and shares separately; weekly columns only where the exact native weekly report or valid counting-basis weights support them. Include counting bases and censoring.
- Actual position-segment outcomes only when supplied; evidence-led investigation or test proposal.

Separate observations, hypotheses and requested changes. No account writes, rule installation, subscriptions,
notifications, exclusions, feed edits, legal certification or external data transfers occur in this review.
Any implementation request must name exact scope/values, approval owner, monitoring and recovery conditions.

[Google prominence definitions](https://support.google.com/google-ads/answer/7501826?hl=en).
