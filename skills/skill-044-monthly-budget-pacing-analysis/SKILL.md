---
name: skill-044-monthly-budget-pacing-analysis
description: "Compare all month-to-date spend with approved dated plans, deduplicated shared budgets and explicit forecast assumptions."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: bidding
  kind: analyst
  data_source: external
  related: [skill-123-budget-pacing-daily-allocation-scripts]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixCreativeBidding | evidence-led audit correction"
---
# Skill 044: Monthly Budget Pacing Analysis

## Purpose

Distinguish client spending commitments, platform average daily budgets and modeled month-end pacing. Current daily budget times calendar days is only a planning proxy, not an approved cap or universal billing limit.

Recommendations are review-only; this recipe never changes an account.

## Data Requirements

**Applicability:** Account, budget-pool or campaign scopes with a declared month, timezone, spend definition and approved plan.

**Required inputs:**
- Read `../_resources/DATA_CONTRACT.md`, `../_resources/PARAMETERS.md` and the supplied client profile.
- `export/account`, `export/campaigns`, `export/budgets`: include paused/removed entities with spend in the month and all shared-budget IDs.
- `export/custom/monthly_spend_daily.csv`: one account_id/campaign_id/date row, budget_id, cost, billed_cost_if_available, currency, source_ref and complete_day; all days from month start through reporting cutoff plus prior complete days for seven-day baseline, no current-status filter.
- `export/custom/budget_history.csv`: one account_id/budget_id/effective_from/to row, amount, amount_unit, shared_flag, member_campaign_ids and source_ref; month-to-date settings/membership history.
- `export/external/monthly_budget_plan.csv`: one account_id/scope_type/scope_id/month/date row, planned_spend, approved_month_total, cap_or_target, spend_basis (cost/billed), currency, timezone, approved_at, owner and source_ref; client-approved daily weights/plan. If only monthly total exists, explicitly assume uniform daily weighting.

Use account currency, timezone, export window, snapshot and completeness declarations.
Keep missing values distinct from zero and disabled; join on stable IDs, never names.

**Missing inputs:** Without approved plan report actual spend and a clearly labeled daily-budget proxy, not cap breach/pacing pass. Missing early-month data prevents MTD claims; missing billed cost prevents billing-limit claims.
Skip only the dependent subcheck; report its exact missing file/columns and coverage.
Do not treat absent evidence as a defect or a passed check.

## Analysis Steps

1. Set reporting month and last fully reported account-timezone day. Exclude partial/current days from pacing/forecasts and disclose their separate provisional spend if supplied.

2. Sum spend from every campaign that incurred it, including now paused/removed entities. Match plan spend_basis; do not mix billed costs, credits and reporting cost without reconciliation.

3. Deduplicate budget amounts by budget ID and effective interval; apply historical membership. Pool-level plans must not be repeated for every member or added to overlapping campaign/account plans.

4. Compute MTD actual A and expected E=sum(planned_spend through cutoff). Pacing=A/E when E>0; uniform fallback E=approved_month_total×elapsed_complete_days/days_in_month must be labeled an assumption.

5. Calculate linear forecast A/elapsed_complete_days×days_in_month only when elapsed days>0. Seven-day forecast=A+mean(cost over last seven complete comparable days)×remaining_days; fewer than seven gives unavailable or explicitly labeled shorter baseline.

6. For planned events/changes prefer A+remaining approved plan and label this a plan scenario, not a predicted outcome. Show different forecasts and assumptions instead of averaging them into false precision.

7. Compute remaining approved amount=month total−A and required average remaining spend=remaining amount/remaining days when positive days remain. This is arithmetic planning, not a safe Google Ads daily-budget setting or demand guarantee.

8. Investigate target pacing outside 0.85–1.15 as a review heuristic using dated budget/status/event changes. Distinguish intentional underspend, forecast risk and already exceeded explicit cap; propose owner-reviewed corrections with shared-pool scope.

## Thresholds

Numerical screens are triage heuristics, not platform requirements or causal proof.
Use resolved `{{min_impressions}}` for CTR/IS, `{{min_clicks}}` for CVR and
`{{min_conversions}}` for CPA/ROAS comparisons; both comparison cohorts must qualify.
Use mature, comparable goals/windows; exclude incomplete days and conversion lag.
A zero denominator yields unavailable, never infinity or an invented zero rate.

| Condition | Severity |
|---|---|
| Verified actual spend exceeds an explicit approved cap by material amount on matched spend basis | Critical |
| Pacing <0.85 or >1.15 against approved plan, not an intentional deviation | Warning |
| Forecast cap risk, unknown plan/history or normal daily overdelivery alone | Info |

Critical requires directly evidenced material delivery, measurement or safety failure.
Historical spend is exposure, not guaranteed savings; any forecast requires an explicit model.

## Output

Use `../_resources/OUTPUT_TEMPLATES.md`; do not create a competing report format.
Include stable entity IDs, condition key, observed evidence/window, sample, resolved
thresholds, recommendation, uncertainty and the responsible owner.
Separate confirmed findings, opportunities, insufficient evidence and not-applicable checks.
- MTD spend, expected plan, pacing denominator, last complete day, forecasts and remaining-spend arithmetic.
- Cap/target/billing distinctions, deduplicated pool IDs and request-only budget review; no automatic changes.
