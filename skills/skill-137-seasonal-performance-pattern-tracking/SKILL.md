---
name: skill-137-seasonal-performance-pattern-tracking
description: "Separate recurring multi-year patterns from single-cycle observations and business-driven serving changes."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: competitive
  kind: analyst
  data_source: external
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixOperationsSeasonal | corrected evidence, controls, thresholds and request-only outputs"
---
# Skill 137: Seasonal Pattern Description

## Purpose

Separate recurring multi-year patterns from single-cycle observations and business-driven serving changes.

This is a local evidence review. Recommendations are proposals, not permission to act on an account or disclose client data.

## Data Requirements

**Applicability:** Campaigns with monthly history; repeated seasonality requires at least two comparable annual cycles, not one year alone.

**Required inputs:**
- Base `export/` tables: account, campaigns, using [DATA_CONTRACT](../_resources/DATA_CONTRACT.md).
- Read client objectives, parameter overrides, currency, timezone, snapshot, report completeness, conversion-date basis and lag maturity.
- `export/custom/seasonal_monthly.csv`: account_id/campaign_id/year_month grain; goal_id, impressions, clicks, cost, conversions, conversion_value, active_days, tracking_basis, search_is_if_available, is_censoring; Ads monthly report for 24-36 complete months, or all available history explicitly labeled.
- `export/custom/seasonal_budget_history.csv`: account_id/budget_id/effective_from grain; effective_to, amount, member_campaign_ids; Ads historical budgets throughout comparison.
- `export/external/seasonal_context.csv`: campaign_id/event_id/date_range grain; event_type, promotion_dates, inventory_constraint, tracking_change, structural_change, market_calendar, evidence_ref; client history covering each cycle.

Keep original source labels and stable IDs; filenames are suggested local intake paths, not assumed existing files.
Custom/configuration schemas describe UI/export evidence, not a claim of live API field verification.

**Missing inputs:** List exact missing files/columns, source dates and affected subchecks.
Continue independent inventory or arithmetic with available evidence; skip only dependent checks.
Optional evidence gates only its stated deeper comparison, forecast or test-result analysis.
Unknown settings, authorization, coverage or policy applicability are not false/disabled and are not a passed check.

## Analysis Steps

1. Align moving holidays, active days, maturity and goal definitions; mark structurally incomparable campaigns rather than treating renames/new structures as growth.

2. Calculate monthly totals and pooled rates within each year. One annual cycle is descriptive; repeated similar patterns across comparable cycles are seasonality hypotheses, not causal proof.

3. Compare same-season months against non-event normal periods and prior cycles; account for historical budget/capacity changes.

4. Use >30% recurring CVR decline as a triage heuristic only with {{min_clicks}} on both cohorts; spend/volume may reflect budgets rather than demand.

5. IS changes cannot establish increased competition. Flat budgets are legitimate when constraints or margins require them.

6. Propose planning scenarios through skill-152/147. Routine month-long seasonality should not receive bid seasonality adjustments; skill-146 owns exceptional short future deviations from NORMAL baseline.

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
| Repeated comparable >30% CVR decline with material client goal risk | Warning |
| One cycle, structural break or routine seasonal pattern | Info |

Insufficient evidence or sample is Info. Critical requires directly evidenced material delivery, measurement or safety failure.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a conflicting report format.
Each finding includes skill/entity IDs, condition key, severity, observed values and evidence references, exact window,
sample, resolved threshold, recommendation, uncertainty, responsible owner and dependent skipped subchecks.

- Year-month/goal table with complete-cycle count, normal baseline, budget context and comparability exclusions.
- Descriptive patterns and assumption-led planning handoffs, no automatic monthly bid/budget changes.

Separate observations, hypotheses and requested changes. No account writes, rule installation, subscriptions,
notifications, exclusions, feed edits, legal certification or external data transfers occur in this review.
Any implementation request must name exact scope/values, approval owner, monitoring and recovery conditions.
