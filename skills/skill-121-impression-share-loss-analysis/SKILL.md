---
name: skill-121-impression-share-loss-analysis
description: "Separate reported budget/rank visibility constraints from proven economic opportunity. Basic campaign_metrics already supplies impression-share metrics."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: waste
  kind: analyst
  data_source: export
  merged_from: [skill-133-impression-share-loss-analysis]
  related: [skill-135-top-of-page-rate-monitoring]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixOperationsSeasonal | corrected evidence, controls, thresholds and request-only outputs"
---
# Skill 121: Impression Share Loss Review

## Purpose

Separate reported budget/rank visibility constraints from proven economic opportunity. Basic campaign_metrics already supplies impression-share metrics.

This is a local evidence review. Recommendations are proposals, not permission to act on an account or disclose client data.

## Data Requirements

**Applicability:** Search campaigns with supported share metrics, comparable objectives and explicit client targets.

**Required inputs:**
- Base `export/` tables: account, campaigns, budgets, campaign_metrics, keywords, keyword_metrics, using [DATA_CONTRACT](../_resources/DATA_CONTRACT.md).
- Read client objectives, parameter overrides, currency, timezone, snapshot, report completeness, conversion-date basis and lag maturity.
- Optional `export/custom/is_daily.csv`: one row per account_id/campaign_id/date: budget_id, strategy_id, goal_id, impressions, clicks, cost, conversions, conversion_value, conversion_date_basis, maturity; Ads UI daily report, account timezone, complete dates including historical inactive campaigns and coverage/suppression notes; add search_impression_share, budget_lost_is, rank_lost_is and historical_budget_amount for 8 complete weeks when testing daily saturation/trends.
- Optional `export/external/is_scenarios.csv`: scenario_id/campaign_id grain; target_metric, target_value, allowable_spend, marginal_cvr, marginal_cpc, marginal_value, assumptions, approval_owner; client planning assumptions current to forecast dates. Without this, no monetary recovery forecast.

Keep original source labels and stable IDs; filenames are suggested local intake paths, not assumed existing files.
Custom/configuration schemas describe UI/export evidence, not a claim of live API field verification.

**Missing inputs:** List exact missing files/columns, source dates and affected subchecks.
Continue independent inventory or arithmetic with available evidence; skip only dependent checks.
Optional evidence gates only its stated deeper comparison, forecast or test-result analysis.
Unknown settings, authorization, coverage or policy applicability are not false/disabled and are not a passed check.

## Analysis Steps

1. Normalize fraction/percent units and retain censored or unavailable shares; require {{min_impressions}}. Do not average daily IS without eligible-impression weights.

2. Screen budget-lost IS above 20% or rank-lost IS above 30% as triage, allowing both. These indicate reported constraints, not certain lost profitable sales.

3. Assess CPA against target or ROAS against target with mature {{min_conversions}}. Conversion count alone is not profitability; no target means economic suitability unknown.

4. Confirm daily saturation only from historical budgets and complete daily spend, deduplicating shared budgets. Current daily budget times days cannot establish historical saturation.

5. Rank loss has multiple causes. Join keyword diagnostics by campaign/ad-group/criterion IDs only if provided; Quality Score is not an auction input and does not prove the root cause.

6. If uncensored IS permits, estimated eligible impressions = served impressions / IS is a rough diagnostic, not recoverable impressions. Any conversion/value scenario needs explicit marginal assumptions and uncertainty; never multiply historical CTR/CVR into guaranteed gains.

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
| Budget-lost IS >20% with sufficient sample and goal-aligned economics | Warning |
| Rank-lost IS >30% with sufficient sample | Warning |
| No target, censored IS, missing daily history or low sample | Info |

Insufficient evidence or sample is Info. Critical requires directly evidenced material delivery, measurement or safety failure.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a conflicting report format.
Each finding includes skill/entity IDs, condition key, severity, observed values and evidence references, exact window,
sample, resolved threshold, recommendation, uncertainty, responsible owner and dependent skipped subchecks.

- Campaign IDs, dates, share units/censoring, loss types, outcomes and targets.
- Rank/budget investigation ownership; optional assumption-led scenario rather than savings or automatic budget increase.

Separate observations, hypotheses and requested changes. No account writes, rule installation, subscriptions,
notifications, exclusions, feed edits, legal certification or external data transfers occur in this review.
Any implementation request must name exact scope/values, approval owner, monitoring and recovery conditions.
