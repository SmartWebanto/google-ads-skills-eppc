---
name: skill-050-shared-budget-appropriateness-check
description: "Measure shared-pool concentration against its member-count baseline and assess unmet demand before any separation proposal."
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
# Skill 050: Shared Budget Compatibility and Concentration Review

## Purpose

Describe allocation concentration without equating low spend share with starvation. Equal two-campaign sharing has HHI 0.50 and is not a defect; compatibility and business constraints determine whether allocation warrants review.

Recommendations are review-only; this recipe never changes an account.

## Data Requirements

**Applicability:** Explicit shared budgets with complete actual membership and comparable observation windows.

**Required inputs:**
- Read `../_resources/DATA_CONTRACT.md`, `../_resources/PARAMETERS.md` and the supplied client profile.
- `export/account`, `export/campaigns`, `export/budgets`, `export/bidding_strategies`, `export/campaign_metrics`: pool IDs, all member IDs/statuses, daily amount, explicit goals and mature outcomes.
- `export/custom/shared_budget_daily.csv`: one account_id/budget_id/campaign_id/date row, cost, impressions, clicks, conversions, value, budget_lost_IS, budget_specific_reason, eligibility_status, goal_cohort, lag_mature and source_ref; complete Ads daily window, normally thirty days.
- `export/custom/budget_history.csv`: one account_id/budget_id/effective_from/to row, amount, amount_unit, shared_flag, member_campaign_ids and source_ref; matching settings/membership history.
- Client profile: campaign objective/traffic role, economic limits, approved allocation commitments and total spend constraint. A quantified split additionally needs `export/custom/shared_budget_response.csv`: one model_id/budget_id/scenario_id row, source_type, baseline/scenario_member_allocations, modeled_cost/conversions/value, period_start/end, assumptions, uncertainty_low/high, source_ref; supplied simulator or experiment model with comparable goal units.

Use account currency, timezone, export window, snapshot and completeness declarations.
Keep missing values distinct from zero and disabled; join on stable IDs, never names.

**Missing inputs:** Incomplete membership/history prevents concentration claims for that regime. Missing unmet-demand evidence means no starvation conclusion; missing response model means no projected split gains.
Skip only the dependent subcheck; report its exact missing file/columns and coverage.
Do not treat absent evidence as a defect or a passed check.

## Analysis Steps

1. Inventory true budget pools by budget ID, not portfolio names. Segment dates at membership or budget changes; include zero-spend eligible members so the denominator is not performance-filtered.

2. Within each stable membership regime define n as complete eligible member count and S=sum(member spend). For S>0 compute p_i=spend_i/S and HHI=sum(p_i²); if S=0 concentration is unavailable.

3. Report equal-share baseline 1/n. For n>1 normalized concentration=(HHI−1/n)/(1−1/n); for n=1 mark normalized concentration not applicable. Equal two-member spend yields HHI=0.50 and normalized=0, not a warning.

4. Describe spend and conversion/value shares without calling a member below 5% starved or above 60% harmful. A normalized concentration above 0.50 is an Info review heuristic only.

5. Evaluate explicit business compatibility, traffic roles and goal/value definitions; pooling can intentionally favor some members. Different goals require contextual review, not automatic Critical or compulsory separation.

6. For a starvation hypothesis require dated pool saturation/budget-specific limitation plus an eligible low-share member with independently evidenced unmet demand and acceptable economics. Low impressions/spend can reflect low demand or ineligibility instead.

7. Compare matched mature CPA/ROAS within goal cohorts; do not average ratios across incomparable members. Preserve legitimate asymmetric allocation when goals and constraints are satisfied.

8. Propose separation only for a documented business conflict or tested response advantage under approved constraints. Use the supplied response model for net/marginal scenarios, not current average CPA extrapolation; otherwise propose a bounded experiment and retain pooling.

## Thresholds

Numerical screens are triage heuristics, not platform requirements or causal proof.
Use resolved `{{min_impressions}}` for CTR/IS, `{{min_clicks}}` for CVR and
`{{min_conversions}}` for CPA/ROAS comparisons; both comparison cohorts must qualify.
Use mature, comparable goals/windows; exclude incomplete days and conversion lag.
A zero denominator yields unavailable, never infinity or an invented zero rate.

| Condition | Severity |
|---|---|
| Documented allocation commitment conflict plus corroborated budget constraint/unmet demand | Warning |
| Concentration, high/low member share, or differing roles alone | Info |
| Missing membership, demand evidence, maturity or separation-response model | Info |

Critical requires directly evidenced material delivery, measurement or safety failure.
Historical spend is exposure, not guaranteed savings; any forecast requires an explicit model.

## Output

Use `../_resources/OUTPUT_TEMPLATES.md`; do not create a competing report format.
Include stable entity IDs, condition key, observed evidence/window, sample, resolved
thresholds, recommendation, uncertainty and the responsible owner.
Separate confirmed findings, opportunities, insufficient evidence and not-applicable checks.
- Pool/regime membership, spend shares, raw HHI, 1/n baseline and normalized concentration with edge cases.
- Compatibility/unmet-demand evidence and review-only retain/test/split proposal; no deterministic separation uplift.
