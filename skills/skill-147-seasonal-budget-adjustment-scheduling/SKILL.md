---
name: skill-147-seasonal-budget-adjustment-scheduling
description: "Review approved temporary budgets, caps and reversion plans without requiring event-driven budget increases."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: seasonal
  kind: operational
  data_source: external
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixOperationsSeasonal | corrected evidence, controls, thresholds and request-only outputs"
---
# Skill 147: Seasonal Budget Schedule Proposals

## Purpose

Review approved temporary budgets, caps and reversion plans without requiring event-driven budget increases.

This is a local evidence review. Recommendations are proposals, not permission to act on an account or disclose client data.

## Data Requirements

**Applicability:** Events with known budget owners, approved envelope and supported budget/rule settings.

**Required inputs:**
- Base `export/` tables: account, campaigns, budgets, bidding_strategies, using [DATA_CONTRACT](../_resources/DATA_CONTRACT.md).
- Read client objectives, parameter overrides, currency, timezone, snapshot, report completeness, conversion-date basis and lag maturity.
- `export/external/seasonal_budget_plan.csv`: one row per event_id/campaign_id: name, start_at, end_at, timezone, objective, offer, expected_cvr_change, rationale, owner, approval_status, normal_baseline_dates; client calendar snapshot covering relevant past events and next 60 days; add budget_id, approved_total_cap, baseline_daily_budget, proposed_event_budget, post_event_budget, economic_target, response_assumptions, approval_ref.
- `export/custom/seasonal_budget_daily.csv`: one row per account_id/campaign_id/date: budget_id, strategy_id, goal_id, impressions, clicks, cost, conversions, conversion_value, conversion_date_basis, maturity; Ads UI daily report, account timezone, complete dates including historical inactive campaigns and coverage/suppression notes; prior event, surrounding normal weeks and full current MTD; add budget_lost_is_if_supported.
- `export/custom/seasonal_budget_rules.csv`: account_id/budget_id/rule_id/snapshot_at grain; current_amount, historical_amounts_and_effective_dates, member_campaign_ids, action, scheduled_at, timezone, enabled, last_result, reversion_amount, manual_override_owner; Ads budget history and rule settings covering event and recovery dates.

Keep original source labels and stable IDs; filenames are suggested local intake paths, not assumed existing files.
Custom/configuration schemas describe UI/export evidence, not a claim of live API field verification.

**Missing inputs:** List exact missing files/columns, source dates and affected subchecks.
Continue independent inventory or arithmetic with available evidence; skip only dependent checks.
Optional evidence gates only its stated deeper comparison, forecast or test-result analysis.
Unknown settings, authorization, coverage or policy applicability are not false/disabled and are not a passed check.

## Analysis Steps

1. Reconcile shared-budget membership, actual MTD spend and approved cap once per budget pool. Current amounts do not establish historical utilization.

2. Compare prior event demand and outcomes to normal periods with mature samples. Lost IS alone cannot prove profitable incremental demand.

3. Evaluate explicit marginal-response scenarios and cash/capacity limits before recommending any change. Keeping a flat or lower budget is a valid decision.

4. For an already approved temporary change, compare rules or documented manual handoff with event dates/timezone and approved post-event amount. Automatic reversion is not mandatory if accountable manual control exists.

5. Draft a bounded budget-ID schedule with start/end, cap, monitoring, override, owner and approval. Do not schedule or apply; month-long planning does not imply a bid seasonality adjustment.

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
| Directly evidenced material breach of approved spending cap | Critical |
| Approved temporary schedule or post-event restoration conflicts with actual configuration | Warning |
| Upcoming event without increase, lost IS alone or missing response model | Info |

Insufficient evidence or sample is Info. Critical requires directly evidenced material delivery, measurement or safety failure.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a conflicting report format.
Each finding includes skill/entity IDs, condition key, severity, observed values and evidence references, exact window,
sample, resolved threshold, recommendation, uncertainty, responsible owner and dependent skipped subchecks.

- Historical/normal/event economics, shared-pool cap reconciliation and scenario assumptions.
- Request-only dated budget schedule, manual/automated restoration responsibility and verification plan.

Separate observations, hypotheses and requested changes. No account writes, rule installation, subscriptions,
notifications, exclusions, feed edits, legal certification or external data transfers occur in this review.
Any implementation request must name exact scope/values, approval owner, monitoring and recovery conditions.
