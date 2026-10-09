---
name: skill-152-historical-performance-benchmarking-seasonal-planning
description: "Build comparable historical benchmarks and explicit future scenarios without inventing capacity or marginal returns."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: seasonal
  kind: analyst
  data_source: external
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixOperationsSeasonal | corrected evidence, controls, thresholds and request-only outputs"
---
# Skill 152: Historical Seasonal Benchmarking

## Purpose

Build comparable historical benchmarks and explicit future scenarios without inventing capacity or marginal returns.

This is a local evidence review. Recommendations are proposals, not permission to act on an account or disclose client data.

## Data Requirements

**Applicability:** Events with available prior-year history; new accounts receive an evidence-limited planning path, not a defect.

**Required inputs:**
- Base `export/` tables: account, campaigns, budgets, using [DATA_CONTRACT](../_resources/DATA_CONTRACT.md).
- Read client objectives, parameter overrides, currency, timezone, snapshot, report completeness, conversion-date basis and lag maturity.
- `export/custom/seasonal_benchmark_daily.csv`: one row per account_id/campaign_id/date: budget_id, strategy_id, goal_id, impressions, clicks, cost, conversions, conversion_value, conversion_date_basis, maturity; Ads UI daily report, account timezone, complete dates including historical inactive campaigns and coverage/suppression notes; 2-3 prior event/normal periods and adjoining weeks, add active_status and budget_lost_is_if_supported.
- `export/custom/benchmark_budget_history.csv`: account_id/budget_id/effective_from grain; effective_to, amount, member_campaign_ids; historical Ads settings covering each benchmark date.
- `export/external/seasonal_forecast_plan.csv`: one row per event_id/campaign_id: name, start_at, end_at, timezone, objective, offer, expected_cvr_change, rationale, owner, approval_status, normal_baseline_dates; client calendar snapshot covering relevant past events and next 60 days; add historical_campaign_mapping, structural_breaks, tracking_basis_changes, proposed_cap, growth_assumptions, marginal_cpc/cvr/value_ranges, evidence_ref.

Keep original source labels and stable IDs; filenames are suggested local intake paths, not assumed existing files.
Custom/configuration schemas describe UI/export evidence, not a claim of live API field verification.

**Missing inputs:** List exact missing files/columns, source dates and affected subchecks.
Continue independent inventory or arithmetic with available evidence; skip only dependent checks.
Optional evidence gates only its stated deeper comparison, forecast or test-result analysis.
Unknown settings, authorization, coverage or policy applicability are not false/disabled and are not a passed check.

## Analysis Steps

1. Align events by actual moving-holiday dates and comparable weekdays; include historical inactive campaigns and document structural mappings rather than forcing one-to-one continuity.

2. Pool underlying counts to calculate CTR/CVR/CPC/CPA/ROAS with sample/maturity gates; currency/goal changes and tracking breaks can invalidate comparison.

3. Compute YoY changes only on comparable nonzero baselines. Single-year history is a benchmark, not proven recurring seasonality; no history means unknown, never Critical.

4. Budget utilization requires historical budget amounts and shared membership; lost IS requires actual reported fields. Do not produce hourly patterns from daily data.

5. Use >20% adverse YoY efficiency change as review heuristic, not market-shift proof. Higher proposed budgets need explicit marginal-response/capacity assumptions, not automatic rejection against old spend.

6. Present low/base/high scenarios from supplied CPC/CVR/value ranges with assumptions and approved cap. Without assumptions provide historical ranges and prerequisites only, no invented forecast.

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
| Comparable mature YoY efficiency worsens >20% against client goal | Warning |
| Forecast conflicts with explicit approved cap or documented capacity constraint | Warning |
| New account, no comparable prior period or unspecified growth model | Info |

Insufficient evidence or sample is Info. Critical requires directly evidenced material delivery, measurement or safety failure.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a conflicting report format.
Each finding includes skill/entity IDs, condition key, severity, observed values and evidence references, exact window,
sample, resolved threshold, recommendation, uncertainty, responsible owner and dependent skipped subchecks.

- Date/goal-aligned multi-year and normal-baseline tables with comparability exclusions.
- Historical utilization/IS only where supported; assumption-led scenario ranges and request-only planning owner.

Separate observations, hypotheses and requested changes. No account writes, rule installation, subscriptions,
notifications, exclusions, feed edits, legal certification or external data transfers occur in this review.
Any implementation request must name exact scope/values, approval owner, monitoring and recovery conditions.
