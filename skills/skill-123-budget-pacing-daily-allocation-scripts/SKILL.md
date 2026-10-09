---
name: skill-123-budget-pacing-daily-allocation-scripts
description: "Combine dated pacing with weekday efficiency to propose bounded allocation experiments, not deterministic multipliers."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: waste
  kind: operational
  data_source: external
  related: [skill-044-monthly-budget-pacing-analysis]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixOperationsSeasonal | corrected evidence, controls, thresholds and request-only outputs"
---
# Skill 123: Budget Pacing and Daily Allocation Proposals

## Purpose

Combine dated pacing with weekday efficiency to propose bounded allocation experiments, not deterministic multipliers.

This is a local evidence review. Recommendations are proposals, not permission to act on an account or disclose client data.

## Data Requirements

**Applicability:** Accounts with client-approved monthly envelopes and date-level spend, including historical inactive campaigns.

**Required inputs:**
- Base `export/` tables: account, campaigns, budgets, bidding_strategies, using [DATA_CONTRACT](../_resources/DATA_CONTRACT.md).
- Read client objectives, parameter overrides, currency, timezone, snapshot, report completeness, conversion-date basis and lag maturity.
- `export/custom/allocation_daily.csv`: one row per account_id/campaign_id/date: budget_id, strategy_id, goal_id, impressions, clicks, cost, conversions, conversion_value, conversion_date_basis, maturity; Ads UI daily report, account timezone, complete dates including historical inactive campaigns and coverage/suppression notes; 90 complete days through the last completed account-local date, including full current MTD.
- `export/custom/budget_history.csv`: account_id/budget_id/effective_from grain; effective_to, amount, currency, campaign_ids, change_ref; Ads budget history covering those dates.
- `export/external/allocation_plan.csv`: plan_id/budget_id/date grain; monthly_cap_id, approved_monthly_cap, planned_daily_spend, goal_group, maximum_change, minimum_roas_or_maximum_cpa, marginal_response_assumptions, owner; approved current-month plan including remaining days.

Keep original source labels and stable IDs; filenames are suggested local intake paths, not assumed existing files.
Custom/configuration schemas describe UI/export evidence, not a claim of live API field verification.

**Missing inputs:** List exact missing files/columns, source dates and affected subchecks.
Continue independent inventory or arithmetic with available evidence; skip only dependent checks.
Optional evidence gates only its stated deeper comparison, forecast or test-result analysis.
Unknown settings, authorization, coverage or policy applicability are not false/disabled and are not a passed check.

## Analysis Steps

1. Join dates and budget memberships as of each day; sum all historical campaign spend and deduplicate shared budgets/caps. Exclude incomplete current day.

2. MTD pacing ratio = actual MTD cost / approved planned-to-date spend. Remaining budget = approved cap minus actual spend; required remaining-day average uses only planned active remaining days. Zero denominators yield unknown.

3. Calculate weekly and weekday efficiency from dated counts; use mature conversions for efficiency but current complete cost for pacing. Compare only same goal groups across multiple weeks.

4. Use >10% overplan or >20% underplan as consistent triage heuristics, not billing-limit breaches. Daily platform overdelivery and client cap are distinct.

5. Historical weekday averages do not establish marginal returns. Propose a bounded allocation experiment only with approved envelope, shared-pool constraints, response assumptions, monitoring/rollback and business priority; no fixed multiplier from CPA rankings.

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
| Directly evidenced material breach of approved client spending cap | Critical |
| Complete MTD cost >110% or <80% of approved planned-to-date spend | Warning |
| Weekday pattern without approved marginal-response assumptions | Info |

Insufficient evidence or sample is Info. Critical requires directly evidenced material delivery, measurement or safety failure.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a conflicting report format.
Each finding includes skill/entity IDs, condition key, severity, observed values and evidence references, exact window,
sample, resolved threshold, recommendation, uncertainty, responsible owner and dependent skipped subchecks.

- MTD/weekly actual-versus-plan, cap IDs, shared-budget reconciliation and remaining-day arithmetic.
- Weekday cohorts and request-only allocation scenario with assumptions, owner and guardrails.

Separate observations, hypotheses and requested changes. No account writes, rule installation, subscriptions,
notifications, exclusions, feed edits, legal certification or external data transfers occur in this review.
Any implementation request must name exact scope/values, approval owner, monitoring and recovery conditions.
