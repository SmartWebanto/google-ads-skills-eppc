---
name: skill-040-target-cpa-roas-realism-check
description: "Evaluate target direction and dated achieved outcomes with budget, goal and economic guardrails."
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
# Skill 040: Target CPA and ROAS Realism Check

## Purpose

Separate ambitious efficiency targets from relaxed volume targets: lower tCPA or higher tROAS is more restrictive; higher tCPA or lower tROAS is less restrictive. Gaps to historical outcomes are diagnostics, not causal proof.

Recommendations are review-only; this recipe never changes an account.

## Data Requirements

**Applicability:** Campaign/portfolio strategies with an explicitly configured CPA or ROAS target, including optional targets within Maximize strategies.

**Required inputs:**
- Read `../_resources/DATA_CONTRACT.md`, `../_resources/PARAMETERS.md` and the supplied client profile.
- `export/account`, `export/campaigns`, `export/bidding_strategies`, `export/budgets`, `export/conversion_actions`: explicit goals, strategy/target sources and business CPA/ROAS constraints from client profile.
- `export/custom/target_daily.csv`: one account_id/campaign_id/date/goal_cohort row, strategy_id, budget_id, impressions, clicks, cost, conversions, conversion_value, lag_mature; Ads daily report spanning 90 complete days or available history, declared date basis.
- `export/custom/target_history.csv`: one account_id/entity_type/entity_id/effective_from/to row, campaign_id/strategy_id, strategy_type, target_type, target_value, target_source (standalone/embedded/portfolio), learning_status/reason, source_ref; dated Ads settings/history covering the same period.
- `export/custom/budget_history.csv`: one account_id/budget_id/effective_from/to row, amount, amount_unit, shared_flag, member_campaign_ids, source_ref; dated Ads budget/membership changes covering analysis window.

Use account currency, timezone, export window, snapshot and completeness declarations.
Keep missing values distinct from zero and disabled; join on stable IDs, never names.

**Missing inputs:** Without history compare snapshot target to aggregate mature outcomes only, with no recent-change/learning/trend claims. Missing goals, target basis or business guardrails prevent recommended target sizing.
Skip only the dependent subcheck; report its exact missing file/columns and coverage.
Do not treat absent evidence as a defect or a passed check.

## Analysis Steps

1. Resolve current effective target and its source, including Maximize Conversions CPA and Maximize Value ROAS fields; a zero/absent optional target is not a zero-efficiency requirement.

2. Split daily evidence into stable strategy, target, goal and budget regimes. Never treat today’s target as the historical target for every day; retain date and lag cutoffs.

3. For a stable comparable 30-day mature window calculate achieved CPA=sum(cost)/sum(conversions), ROAS=sum(value)/sum(cost). Describe separate 7/14-day windows only if each sample qualifies; do not average daily ratios or invent recent weighting.

4. Calculate CPA restrictiveness=1−target_CPA/achieved_CPA and ROAS restrictiveness=target_ROAS/achieved_ROAS−1 when denominators are positive. Positive values mean more restrictive targets; negative values mean relaxed targets, not guaranteed waste.

5. A restrictiveness above 0.20 is a review heuristic. Check lower volume alongside budget utilization, tracking, demand, eligibility and dated changes before associating it with the target; correlation does not establish causation.

6. Compute pool utilization from dated daily budgets counted once per budget ID, with historical membership. Treat it as planning utilization, not billing-cap compliance; no campaign gets the full shared pool as an independent budget.

7. Review achievable business constraints: do not raise tCPA beyond approved acquisition economics or lower tROAS below minimum returns just to match past results. Low ROAS targets may trade efficiency for volume; high ROAS targets may restrict volume.

8. Recommend a bounded target test or simulator review through 051 with explicit direction, rationale, owner approval and guardrails. Do not output historical achieved CPA as though it were a proposed target.

## Thresholds

Numerical screens are triage heuristics, not platform requirements or causal proof.
Use resolved `{{min_impressions}}` for CTR/IS, `{{min_clicks}}` for CVR and
`{{min_conversions}}` for CPA/ROAS comparisons; both comparison cohorts must qualify.
Use mature, comparable goals/windows; exclude incomplete days and conversion lag.
A zero denominator yields unavailable, never infinity or an invented zero rate.

| Condition | Severity |
|---|---|
| Restrictiveness >0.20 with mature comparable sample and corroborated delivery/economic concern | Warning |
| Relaxed target outside approved business constraint with evidenced exposure | Warning |
| Target gap alone, target within historical range, insufficient sample or missing history | Info |

Critical requires directly evidenced material delivery, measurement or safety failure.
Historical spend is exposure, not guaranteed savings; any forecast requires an explicit model.

## Output

Use `../_resources/OUTPUT_TEMPLATES.md`; do not create a competing report format.
Include stable entity IDs, condition key, observed evidence/window, sample, resolved
thresholds, recommendation, uncertainty and the responsible owner.
Separate confirmed findings, opportunities, insufficient evidence and not-applicable checks.
- Current target, source, achieved outcomes, signed restrictiveness and stable-regime dates.
- Hypothesis and bounded test proposal with business floor/ceiling; no claim that one target gap proves causal loss.
