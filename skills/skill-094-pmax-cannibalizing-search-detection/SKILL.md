---
name: skill-094-pmax-cannibalizing-search-detection
description: "Screen observed PMax and Search overlap without causal cannibalization claims from aggregates."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: shopping_pmax
  kind: analyst
  data_source: external
  related: [skill-002-brand-nonbrand-split, skill-018-duplicate-keyword-detection, skill-128-performance-max-channel-performance]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixShoppingAudiences | evidence contracts and contextual decision rules"
---
# Skill 094: PMax and Search Overlap Hypothesis Review

## Purpose

Identify observable query overlap and performance shifts worth investigating. Search deterioration does not establish PMax cannibalization, internal auction competition or incremental loss; a causal conclusion requires a credible controlled comparison.

## Data Requirements

**Applicability:** Accounts running Search and PMax concurrently with comparable goals; aggregate-only evidence supports descriptive screening only.

**Required inputs:**

- Base [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md): `export/account`, `export/campaigns`, `export/campaign_metrics`, `export/search_terms`; profile `brand_terms` and campaign objectives; client objectives and parameter overrides.
- Record export window, account timezone/currency, snapshot time, source, filters, completeness and conversion-date basis.
- `export/custom/search_pmax_daily.csv`: Ads report, one row per account_id, campaign_id, date, goal_set_id and available channel dimension; impressions, clicks, cost, conversions, conversion_value and Search impression-share metrics only where actually reported. Cover at least two equal mature periods around an explicit intervention date, record lag, reporting changes and incomplete/suppressed segments.
- `export/custom/search_pmax_queries.csv`: optional directly reported Search/PMax query evidence for the same dates, at account_id, campaign_id, date, query_text and reported_query_or_category_type; ad_group_id/asset_group_id where available, impressions, clicks, cost, conversions, conversion_value, coverage/suppression note and source_reference. Search-theme or category summaries are not literal PMax queries.
- `export/external/search_pmax_controls.csv`: configuration/history review at campaign_id, effective_from/to and setting_id; channel, brand exclusions with list/brand IDs, negatives, budget_id/amount, strategy/target, geo/language, goal_set, launch/change dates and source_reference. Include approved intended brand/customer mix and other concurrent changes.
- For causal evaluation only: `export/external/pmax_overlap_experiment.csv`, one row per experiment_id, randomized_unit/aggregate arm and date; arm assignment, eligibility, exposure, intervention, spend, qualified outcomes/value, assignment method, preperiod, analysis_window, contamination checks, power/MDE plan, estimator and uncertainty method. Supply aggregate/privacy-safe data and approved experiment plan.

**Missing inputs:** Without direct PMax query rows do not measure query overlap or brand share; without a controlled comparison do not conclude cannibalization. Continue a clearly labeled hypothesis screen. Skip only the dependent subcheck and list exact missing fields; continue supported inventory. Omitted settings are unknown, not enabled or disabled.

These local intake schemas describe evidence, not asserted API field names. No live GAQL verification is claimed.

## Analysis Steps

1. Declare the observational or experimental scope before analysis. Match market, goals, attribution, brand/customer mix and mature dates; use supplied brand terms rather than campaign-name guesses.

2. Plot campaign/day outcomes around the change and compare equal complete periods. Calculate percentage-point changes for impression-share rates and relative CPC/CPA changes only with valid denominators; inspect budgets, bids, eligibility, seasonality, tracking and demand as alternative explanations.

3. If direct comparable query reports exist, normalize text conservatively and map observed overlaps by campaign/date. Keep categories/themes separate; show visible-query coverage and do not infer hidden-query population shares or simultaneous eligibility.

4. Compare total account/comparable-goal outcomes as well as Search and PMax components. A transfer of attributed conversions can coexist with higher, lower or unchanged incrementality; channel CPA differences and Search share declines are descriptive.

5. Classify unexplained shifts as hypotheses, not Critical or proof of internal competition. Missing PMax brand exclusions is not a defect; preserve intentional brand participation. Route existing brand-protection mismatches to 002 and Search duplicate routing to 018.

6. For a credible causal question propose a supported randomized campaign/geo holdout with agreed brand policy, budget constraints, stable goals, predeclared outcome, duration based on power and lag, contamination checks and rollback plan. Analyze a supplied completed test using its assignment/estimator and uncertainty; do not invent savings or prescribe immediate brand exclusions.

## Thresholds

| Condition | Severity |
|---|---|
| Documented intent/control mismatch independently corroborated by actual served-query evidence | Warning |
| Comparable mature Search/PMax shift or directly observed overlap without controlled causal evidence | Info |
| Missing PMax brand exclusions without a conflicting approved objective | Info |
| Incomplete query coverage, missing controls or insufficient sample/power | Info |

Use [PARAMETERS.md](../_resources/PARAMETERS.md) and resolved client overrides.
CTR comparisons require {{min_impressions}}, conversion-rate comparisons {{min_clicks}},
and CPA/ROAS comparisons {{min_conversions}} on **both** comparable sides.
Use mature, equal-length windows with matched goals, currency and attribution basis;
exclude incomplete days and conversion lag, and never divide by zero.
Numerical screens without a cited platform requirement are triage heuristics, not proof of harm.
Critical requires directly evidenced material delivery, measurement or safety failure.
Missing evidence and optional-feature absence are Info, not a failed or passed check.

## Output

Use [OUTPUT_TEMPLATES.md](../_resources/OUTPUT_TEMPLATES.md), not a separate competing template.
Report stable entity IDs, condition key, observed evidence/window, sample denominators,
resolved thresholds, recommendation, uncertainty and the owning skill.

- Separate observed facts, alternative explanations and causal hypotheses with campaign IDs and windows.
- Show exact query versus category coverage and label brand shares as visible-report shares only.
- Provide test design or supported test estimate with uncertainty; never report Search aggregate decline as proven PMax cannibalization.

Recommendations are request-only proposals; do not modify accounts, feeds, tags or audience lists.
Historical spend is exposure, not guaranteed savings. Do not forecast uplift without a stated model or controlled test.
