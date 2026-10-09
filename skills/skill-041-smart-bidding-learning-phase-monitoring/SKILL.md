---
name: skill-041-smart-bidding-learning-phase-monitoring
description: "Monitor learning using dated status transitions, complete change histories and comparable pre-learning outcomes."
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
# Skill 041: Smart Bidding Learning Phase Monitoring

## Purpose

Distinguish currently reported learning from known learning duration and explore instability without attributing every change to a restart or imposing a blanket freeze.

Recommendations are review-only; this recipe never changes an account.

## Data Requirements

**Applicability:** Supported Smart Bidding campaigns and portfolios with actual platform status/reason evidence.

**Required inputs:**
- Read `../_resources/DATA_CONTRACT.md`, `../_resources/PARAMETERS.md` and the supplied client profile.
- `export/account`, `export/campaigns`, `export/bidding_strategies`, `export/conversion_actions`, `export/budgets`: IDs and optimization context.
- `export/custom/learning_status_history.csv`: one account_id/campaign_id/strategy_id/observed_at row, raw_status, raw_reason, documented_learning_state, status_source, source_ref; continuous snapshots/history for 60 days or since creation, with gaps declared.
- `export/custom/learning_changes.csv`: one account_id/change_id row, changed_at, campaign_id/strategy_id/budget_id, entity_type/id, field, old/new_value, reason, source_ref; all relevant target/budget/goal/status changes for at least 30 days plus baseline.
- `export/custom/learning_daily.csv`: one account_id/campaign_id/date/goal_cohort row, impressions, clicks, cost, conversions, conversion_value, budget_id, lag_mature; daily Ads data covering the learning interval and a prior stable comparable baseline, normally at least 60 days.

Use account currency, timezone, export window, snapshot and completeness declarations.
Keep missing values distinct from zero and disabled; join on stable IDs, never names.

**Missing inputs:** Current status cannot establish start date; first-observed learning gives a lower bound. Missing baseline/value/change history skips respective duration/ROAS/change-count comparisons.
Skip only the dependent subcheck; report its exact missing file/columns and coverage.
Do not treat absent evidence as a defect or a passed check.

## Analysis Steps

1. Map raw supplied status/reason to learning only when documented for that resource. Do not guess a campaign primary-status enum or confuse generic Limited with Learning.

2. Identify last confirmed non-learning and first confirmed learning observations and any intervening gaps. Report exact transition only from an event; otherwise give an interval or minimum observed duration.

3. Build a dated timeline of target, budget, strategy, conversion-goal and pause/resume changes. Count unique change IDs within the stated 30-day window; do not extrapolate fourteen days to thirty.

4. Separate necessary incident repairs and planned tests from discretionary churn. A change during learning does not prove it restarted the learning process; mark associations as hypotheses.

5. Construct a pre-learning baseline with the same goals, attribution and comparable weekdays/season. Aggregate cost/conversions/value before CPA/ROAS; both baseline and learning sample need maturity.

6. For volatility use non-overlapping complete weekly CPA/ROAS aggregates with qualifying samples; report number of valid weeks and range or coefficient of variation with positive mean. Do not compute daily CPA variance on zero-conversion days.

7. A continuous observed learning interval over 21 days or repeated discretionary changes is a review heuristic, not Critical. Check lag, tracking, traffic, eligibility and business constraints; no universal conversion-volume gate.

8. Propose an observation window based on actual conversion cycles and unresolved risks, with owner and next review date. Urgent tracking, safety, budget-cap and policy repairs override elective-change deferral; never promise an exit date.

## Thresholds

Numerical screens are triage heuristics, not platform requirements or causal proof.
Use resolved `{{min_impressions}}` for CTR/IS, `{{min_clicks}}` for CVR and
`{{min_conversions}}` for CPA/ROAS comparisons; both comparison cohorts must qualify.
Use mature, comparable goals/windows; exclude incomplete days and conversion lag.
A zero denominator yields unavailable, never infinity or an invented zero rate.

| Condition | Severity |
|---|---|
| Observed learning >21 days with corroborated sustained business-performance concern | Warning |
| Repeated discretionary changes with documented instability needing review | Warning |
| Learning alone, low volume, incomplete history or unqualified baseline | Info |

Critical requires directly evidenced material delivery, measurement or safety failure.
Historical spend is exposure, not guaranteed savings; any forecast requires an explicit model.

## Output

Use `../_resources/OUTPUT_TEMPLATES.md`; do not create a competing report format.
Include stable entity IDs, condition key, observed evidence/window, sample, resolved
thresholds, recommendation, uncertainty and the responsible owner.
Separate confirmed findings, opportunities, insufficient evidence and not-applicable checks.
- Status/change timeline with exact, bounded or unknown duration and coverage gaps.
- Matched baseline outcomes, instability evidence and review-only monitoring plan with urgent-fix exceptions.
