---
name: skill-045-budget-allocation-optimization
description: "Evaluate constrained reallocation scenarios within comparable goal cohorts using explicit marginal-response evidence."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: bidding
  kind: analyst
  data_source: external
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixCreativeBidding | evidence-led audit correction"
---
# Skill 045: Goal-Matched Budget Allocation Review

## Purpose

Review allocation under real business constraints rather than ranking mixed campaigns by account-wide CPA quartiles or projecting large shifts from average returns.

Recommendations are review-only; this recipe never changes an account.

## Data Requirements

**Applicability:** Budget pools/campaigns with comparable objectives, conversion definitions, value basis and traffic roles; cross-goal allocation needs explicit business value exchange rates.

**Required inputs:**
- Read `../_resources/DATA_CONTRACT.md`, `../_resources/PARAMETERS.md` and the supplied client profile.
- `export/account`, `export/campaigns`, `export/budgets`, `export/bidding_strategies`, `export/campaign_metrics`: goals, IDs, mature outcomes and supported budget-lost IS.
- `export/custom/allocation_daily.csv`: one account_id/campaign_id/date/goal_cohort row, budget_id, cost, clicks, impressions, conversions, value, budget_lost_IS, lag_mature and source_ref; at least 30 complete days plus model baseline, from Ads reports.
- `export/custom/budget_history.csv`: one account_id/budget_id/effective_from/to row, amount, amount_unit, shared_flag, member_campaign_ids, source_ref; same analysis period.
- `export/external/allocation_constraints.csv`: one account_id/cohort_id/scope_id row, objective, goal_action_ids, value_basis, traffic_role, minimum/maximum_spend, protected_commitment, total_cap, approved_CPA_or_ROAS_limit, effective_dates, owner and source_ref; business allocation brief.
- `export/external/allocation_response.csv`: one model_id/scope_id/scenario_id row, baseline_window, forecast_window, baseline_spend/outcome, scenario_spend/outcome, uncertainty_low/high, response_method, assumptions, validity_domain, source_ref and approved_state; supplied simulator, controlled test or documented response model.

Use account currency, timezone, export window, snapshot and completeness declarations.
Keep missing values distinct from zero and disabled; join on stable IDs, never names.

**Missing inputs:** Without comparable goals do not rank cohorts together. Without marginal-response evidence provide a constrained experiment proposal, not quantified uplift or a recommended percentage shift.
Skip only the dependent subcheck; report its exact missing file/columns and coverage.
Do not treat absent evidence as a defect or a passed check.

## Analysis Steps

1. Define cohorts by explicit business goal, included conversion actions, value/currency basis, customer lifecycle and traffic role. Brand capture and acquisition are not exchangeable merely because both report conversions.

2. Reconstruct budget pools and dated member spend; compare efficiency only within mature comparable cohorts. Compute pooled CPA/ROAS from sums, not means of campaign ratios.

3. Inventory minimum commitments, maximum affordable spend and shared-pool restrictions. An unspent daily budget is not incurred spend; reducing it may free no actual spend.

4. Screen recipients using observed constraints and acceptable economics, donors using approved priority and modeled opportunity cost. Low volume or bottom quartile alone does not mean overfunded.

5. For each bounded scenario compare model responses at current and proposed spend. Report incremental outcomes and lost donor outcomes separately; marginal CPA=delta_cost/delta_conversions only when both deltas positive, marginal ROAS=delta_value/delta_cost for positive incremental cost.

6. Keep total proposed budget within the approved cap and respect all pool/commitment constraints. Do not apply independent member changes to an indivisible shared pool; avoid summing overlapping model scope or incompatible periods.

7. Calculate net scenario outcome only when units/goals match and the response model accounts for scope interactions. Label estimates, uncertainty, diminishing returns and model domain; do not extrapolate averages into 40–50% shifts.

8. Select review candidates meeting marginal business limits under uncertainty; propose a controlled holdout or limited-budget test where evidence is weak. Preserve owner approval, rollback guardrails and measurement window; execute nothing.

## Thresholds

Numerical screens are triage heuristics, not platform requirements or causal proof.
Use resolved `{{min_impressions}}` for CTR/IS, `{{min_clicks}}` for CVR and
`{{min_conversions}}` for CPA/ROAS comparisons; both comparison cohorts must qualify.
Use mature, comparable goals/windows; exclude incomplete days and conversion lag.
A zero denominator yields unavailable, never infinity or an invented zero rate.

| Condition | Severity |
|---|---|
| Actual allocation violates a documented business minimum/cap with evidenced exposure | Warning |
| Modeled marginal trade-off meets constraints and warrants controlled evaluation | Info |
| Mixed goals, missing response model or historical average efficiency difference alone | Info |

Critical requires directly evidenced material delivery, measurement or safety failure.
Historical spend is exposure, not guaranteed savings; any forecast requires an explicit model.

## Output

Use `../_resources/OUTPUT_TEMPLATES.md`; do not create a competing report format.
Include stable entity IDs, condition key, observed evidence/window, sample, resolved
thresholds, recommendation, uncertainty and the responsible owner.
Separate confirmed findings, opportunities, insufficient evidence and not-applicable checks.
- Comparable cohort and pool ledger, approved constraints and candidate donor/recipient rationale.
- Explicit current/proposed spend, marginal response, net scenario only where valid, uncertainty and owner review.
