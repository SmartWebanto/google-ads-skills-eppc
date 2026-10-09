---
name: skill-042-budget-limited-campaign-identification
description: "Identify budget-specific constraints with dated delivery evidence and assess economic headroom without deterministic recovery projections."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: bidding
  kind: analyst
  data_source: custom_query
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixCreativeBidding | evidence-led audit correction"
---
# Skill 042: Budget Constraint and Scale Opportunity Review

## Purpose

Screen budget-limited delivery as a potential scale opportunity, not an automatic defect or guaranteed missed revenue. Impression-share metrics already exist in the base contract; additional data supplies dates and actual reasons.

Recommendations are review-only; this recipe never changes an account.

## Data Requirements

**Applicability:** Eligible campaign types with supported budget diagnostics; Search IS checks only where Search impression-share metrics apply.

**Required inputs:**
- Read `../_resources/DATA_CONTRACT.md`, `../_resources/PARAMETERS.md` and the supplied client profile.
- `export/account`, `export/campaigns`, `export/budgets`, `export/campaign_metrics`: budget IDs, strategy, explicit goals, base IS metrics and mature outcomes.
- `export/custom/budget_constraint_daily.csv`: one account_id/campaign_id/date row, budget_id, impressions, clicks, cost, conversions, conversion_value, search_IS, budget_lost_IS, rank_lost_IS, metric_bounds and lag_mature; at least 30 complete days of Ads reports.
- `export/custom/budget_constraint_status.csv`: one account_id/campaign_id/observed_at row, primary_status, raw_reasons, budget_specific_diagnostic, source_ref; dated Ads diagnostics matched to daily periods.
- `export/custom/budget_history.csv`: one account_id/budget_id/effective_from/to row, amount, amount_unit, shared_flag, member_campaign_ids and source_ref; history covering the daily window. Client profile supplies approved spend and CPA/ROAS limits.

Use account currency, timezone, export window, snapshot and completeness declarations.
Keep missing values distinct from zero and disabled; join on stable IDs, never names.

**Missing inputs:** Generic Limited does not identify budget limitation. Without daily budgets/status dates do not claim persistent saturation; without business limits no sized increase.
Skip only the dependent subcheck; report its exact missing file/columns and coverage.
Do not treat absent evidence as a defect or a passed check.

## Analysis Steps

1. Join all relevant campaigns and shared-budget pools, preserving historical membership and paused-period spend. Map constraints by date rather than applying current status to the whole window.

2. Require explicit budget-specific diagnostic or supported positive budget-lost IS for budget constraint evidence. Separate rank, demand, policy and tracking issues; Limited alone is insufficient.

3. Sum pool spend once across members and compare with dated pool budget. Report count/share of complete days near the budget as a heuristic, not proof that any daily excess is a billing violation.

4. Evaluate mature efficiency against explicit business targets within comparable goal cohorts. Low CPA or high ROAS only supports further scale review, not unlimited profitability at higher spend.

5. Report lost IS with actual scope and censored/bounded values. Do not turn it into lost impressions when eligible-impression denominator/scope is unavailable; no linear lost-conversion or revenue extrapolation.

6. Identify possible recipient/donor pools only under matching goals and approved allocation constraints. Unspent budget is not cash already spent and low-volume campaigns can have legitimate roles.

7. Use a supplied simulator or controlled response model for sizing through 051/045. Otherwise propose a guarded budget experiment with an owner-defined cap, not a precise forecast.

8. Prioritize verified constraints by business opportunity and uncertainty. No budget increase or reallocation is executed; retained spend is exposure rather than guaranteed savings.

## Thresholds

Numerical screens are triage heuristics, not platform requirements or causal proof.
Use resolved `{{min_impressions}}` for CTR/IS, `{{min_clicks}}` for CVR and
`{{min_conversions}}` for CPA/ROAS comparisons; both comparison cohorts must qualify.
Use mature, comparable goals/windows; exclude incomplete days and conversion lag.
A zero denominator yields unavailable, never infinity or an invented zero rate.

| Condition | Severity |
|---|---|
| Budget-specific constraint with mature acceptable economics and unmet business demand | Info |
| Persistent documented constraint conflicts with an approved delivery commitment | Warning |
| Generic Limited, missing daily history or unsupported/censored IS denominator | Info |

Critical requires directly evidenced material delivery, measurement or safety failure.
Historical spend is exposure, not guaranteed savings; any forecast requires an explicit model.

## Output

Use `../_resources/OUTPUT_TEMPLATES.md`; do not create a competing report format.
Include stable entity IDs, condition key, observed evidence/window, sample, resolved
thresholds, recommendation, uncertainty and the responsible owner.
Separate confirmed findings, opportunities, insufficient evidence and not-applicable checks.
- Campaign/pool constraint matrix with dated diagnostic, saturation denominator and eligible IS scope.
- Economically guarded experiment candidates and exact additional evidence needed for sizing.
