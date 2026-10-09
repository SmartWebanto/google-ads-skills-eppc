---
name: skill-051-bid-simulator-analysis-target-changes
description: "Interpret dated simulator target points and modeled achieved metrics with explicit normalization and business constraints."
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
# Skill 051: Bid Simulator Marginal Target Analysis

## Purpose

Use available simulator response curves as conditional models, not causal forecasts or guaranteed optimum targets. Keep target CPA/ROAS inputs separate from modeled achieved CPA/ROAS outputs.

Recommendations are review-only; this recipe never changes an account.

## Data Requirements

**Applicability:** Strategies and campaign/portfolio resources for which the platform actually supplies comparable simulator points.

**Required inputs:**
- Read `../_resources/DATA_CONTRACT.md`, `../_resources/PARAMETERS.md` and the supplied client profile.
- `export/account`, `export/campaigns`, `export/bidding_strategies`, `export/campaign_metrics`: effective target/source, business CPA/ROAS constraints and mature achieved outcomes.
- `export/custom/bid_simulation_points.csv`: one account_id/scope_type/scope_id/simulation_id/point_id row, campaign_id/strategy_id, simulation_type, modification_method, simulation_start_date/end_date, generated_at, target_type, target_value, modeled_cost, modeled_conversions, modeled_conversion_value, modeled_impressions/clicks_if_available, currency/unit, baseline_point_flag and source_ref; actual Ads simulator export for CPA or ROAS, no fabricated fields.
- `export/custom/bid_simulation_context.csv`: one account_id/simulation_id row, goal_action_ids, value_basis, budget_id/amount, strategy_type, current_target_at_simulation, material_changes_since, source_ref; matching simulator/settings context.

Use account currency, timezone, export window, snapshot and completeness declarations.
Keep missing values distinct from zero and disabled; join on stable IDs, never names.

**Missing inputs:** No simulator data is an explicit unavailable outcome. Missing dates/units prevents period normalization; missing cost/value/conversion fields skips only the relevant metric.
Skip only the dependent subcheck; report its exact missing file/columns and coverage.
Do not treat absent evidence as a defect or a passed check.

## Analysis Steps

1. Inventory available simulations and retain scope/type/modification method, generation timestamp and both dates. Do not infer simulator eligibility or extract hypothetical zero-filled points when absent.

2. Validate matching goals, budget and strategy context between points. Do not compare campaign and portfolio models or simulation periods as if they shared one response curve; record later material changes.

3. For every point show target input separately from modeled cost/conversions/value. Compute modeled achieved CPA=cost/conversions and modeled achieved ROAS=value/cost only for positive denominators.

4. Calculate inclusive simulation days from start/end. Present native-period results first; optional seven-day equivalent=modeled amount×7/days with explicit stationarity assumption, not guaranteed future weekly performance.

5. Order candidate points by modeled spend, then compare adjacent and baseline-to-candidate deltas. Marginal CPA=delta cost/delta conversions only for positive increments; marginal ROAS=delta value/delta cost for positive incremental cost. Nonpositive/nonmonotonic deltas need interpretation, not forced efficiency ratios.

6. Compare marginal returns to approved business limits, not just current average CPA. Higher tCPA or lower tROAS relaxes efficiency targets and may buy volume; lower tROAS alone is not an efficiency gain.

7. Choose feasible review candidates within model domain and business budget/return constraints. Do not call an input target equal to modeled achieved CPA or extrapolate beyond observed points.

8. Report estimated incremental outcomes with simulator caveats, freshness and missing uncertainty. Historical sample gates apply to observed comparisons; simulated conversion counts are not statistical sample sizes. Recommend a bounded approved test rather than automatic target changes.

## Thresholds

Numerical screens are triage heuristics, not platform requirements or causal proof.
Use resolved `{{min_impressions}}` for CTR/IS, `{{min_clicks}}` for CVR and
`{{min_conversions}}` for CPA/ROAS comparisons; both comparison cohorts must qualify.
Use mature, comparable goals/windows; exclude incomplete days and conversion lag.
A zero denominator yields unavailable, never infinity or an invented zero rate.

| Condition | Severity |
|---|---|
| Modeled candidate meets marginal business constraints and warrants evaluation | Info |
| Proposed change exceeds documented budget/return constraint in supplied model | Warning |
| Unavailable/stale/incomparable simulator evidence or missing point fields | Info |

Critical requires directly evidenced material delivery, measurement or safety failure.
Historical spend is exposure, not guaranteed savings; any forecast requires an explicit model.

## Output

Use `../_resources/OUTPUT_TEMPLATES.md`; do not create a competing report format.
Include stable entity IDs, condition key, observed evidence/window, sample, resolved
thresholds, recommendation, uncertainty and the responsible owner.
Separate confirmed findings, opportunities, insufficient evidence and not-applicable checks.
- Per-point target input, native-period modeled outcomes, achieved metrics, deltas and normalized-period assumptions.
- Review candidate target distinguished from modeled achieved CPA/ROAS; availability, freshness and uncertainty retained.
