---
name: skill-052-conversion-value-based-bidding
description: "Review bidding-value meaning and business evidence without requiring dynamic revenue, profit or LTV values for every account."
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
# Skill 052: Business Value and Value-Based Bidding Assessment

## Purpose

Determine whether actual values represent the chosen business objective. Revenue, contribution profit, expected lead value and deliberate equal values can each be valid; tROAS optimizes the supplied value, not inherently profit or revenue.

Recommendations are review-only; this recipe never changes an account.

## Data Requirements

**Applicability:** Conversion actions used in active optimization and optional value-bidding opportunities, with explicit campaign goal membership.

**Required inputs:**
- Read `../_resources/DATA_CONTRACT.md`, `../_resources/PARAMETERS.md` and the supplied client profile.
- `export/account`, `export/campaigns`, `export/bidding_strategies`, `export/conversion_actions`, `export/campaign_metrics`: strategy/goal IDs, primary/custom-goal membership, value/default settings, cost and conversion/value totals.
- `export/custom/conversion_value_action_daily.csv`: one account_id/campaign_id/action_id/date/value_currency row, conversions, conversion_value, count_basis, source_ref and lag_mature; mature Ads action-segmented outcomes matching business reconciliation dates.
- `export/external/business_value_policy.csv`: one account_id/action_id/value_cohort/effective_from/to row, business_objective, value_basis, static_or_dynamic_intent, currency, gross/net/tax/shipping/refund_treatment, close_rate, contribution_per_closed_customer, horizon, discount_assumptions, approved_value, tolerance, owner and source_ref; approved finance/CRM policy, only applicable fields required.
- `export/external/business_value_reconciliation.csv`: one account_id/action_id/value_cohort/period row, business_event_count, comparable_business_value, Ads_count/value, exclusions, expected_lag, source_ref and reconciliation_status; aggregated supplied CRM/order/finance evidence with no PII. Transaction-level accuracy reconciliation remains owned by 071/107.

Use account currency, timezone, export window, snapshot and completeness declarations.
Keep missing values distinct from zero and disabled; join on stable IDs, never names.

**Missing inputs:** Without business records report settings and unknown accuracy, not a value defect. Missing LTV/margin is irrelevant if approved objective is revenue; zero lead values can be valid for count optimization.
Skip only the dependent subcheck; report its exact missing file/columns and coverage.
Do not treat absent evidence as a defect or a passed check.

## Analysis Steps

1. Map active strategy to actual optimizing goal/action set including custom goals; primary/secondary flags alone do not fully establish which actions influence bidding.

2. Inventory default, always-default and actual reported values separately. Static settings do not establish actual transaction values, and declared dynamic values do not prove business accuracy.

3. Identify the approved value basis and event population. Revenue optimization may intentionally differ from profit; do not label that difference an error or impose LTV on every lead campaign.

4. Compare aligned aggregated business and Ads records on the same currency, dates, attribution/count basis and lag maturity; respect tax/refund rules and exclusions. Percent variance is unavailable when business denominator is zero; show absolute differences.

5. Evaluate zero/equal/unit values in goal context. Count-based lead campaigns and homogeneous approved expected values can be valid; material verified corruption of value-optimized signals requires attention.

6. For a proposed lead model, expected contribution per lead=observed qualified close probability×approved contribution per closed customer over an explicit horizon, with uncertainty and cohort maturity. Do not invent a multiplier, double count already qualified stages or mix revenue LTV with profit targets.

7. Assess whether value differentiation would improve alignment with the chosen business goal and whether signals are timely, stable and supported. No forced dynamic values, profit migration or new micro-conversion values.

8. Recommend owner-reviewed value definitions and controlled bidding evaluation only after reconciliation. Changing value units/basis requires coherent target recalibration and risk review; never directly assign new values or forecast uplift.

## Thresholds

Numerical screens are triage heuristics, not platform requirements or causal proof.
Use resolved `{{min_impressions}}` for CTR/IS, `{{min_clicks}}` for CVR and
`{{min_conversions}}` for CPA/ROAS comparisons; both comparison cohorts must qualify.
Use mature, comparable goals/windows; exclude incomplete days and conversion lag.
A zero denominator yields unavailable, never infinity or an invented zero rate.

| Condition | Severity |
|---|---|
| Verified material value corruption in active value-optimized goals on aligned business evidence | Critical |
| Confirmed discrepancy outside approved tolerance requiring reconciliation | Warning |
| Intentional static/zero values, optional value-bidding opportunity or missing business records | Info |

Critical requires directly evidenced material delivery, measurement or safety failure.
Historical spend is exposure, not guaranteed savings; any forecast requires an explicit model.

## Output

Use `../_resources/OUTPUT_TEMPLATES.md`; do not create a competing report format.
Include stable entity IDs, condition key, observed evidence/window, sample, resolved
thresholds, recommendation, uncertainty and the responsible owner.
Separate confirmed findings, opportunities, insufficient evidence and not-applicable checks.
- Action/campaign value-policy ledger with actual goal membership, basis, source, maturity and known accuracy.
- Reconciliation exceptions and bounded value-model proposals with business owner; no unsupported accuracy verdict or mandatory migration.
