---
name: skill-146-seasonality-bid-adjustment-deployment
description: "Review expected short future CVR deviations from NORMAL baseline, including exceptional below-normal post-event conditions, without routine compensation after promotions."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: seasonal
  kind: operational
  data_source: external
  merged_from: [skill-150-post-peak-negative-seasonality-adjustment]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixOperationsSeasonal | corrected evidence, controls, thresholds and request-only outputs"
---
# Skill 146: Exceptional Seasonality Adjustment Proposals

## Purpose

Review expected short future CVR deviations from NORMAL baseline, including exceptional below-normal post-event conditions, without routine compensation after promotions.

This is a local evidence review. Recommendations are proposals, not permission to act on an account or disclose client data.

## Data Requirements

**Applicability:** Supported Search/Shopping/Display target CPA or target ROAS configurations and PMax; App beta only with confirmed availability. Travel unsupported; verify actual strategy/control eligibility.

**Required inputs:**
- Base `export/` tables: account, campaigns, bidding_strategies, using [DATA_CONTRACT](../_resources/DATA_CONTRACT.md).
- Read client objectives, parameter overrides, currency, timezone, snapshot, report completeness, conversion-date basis and lag maturity.
- `export/custom/event_cvr_daily.csv`: one row per account_id/campaign_id/date: budget_id, strategy_id, goal_id, impressions, clicks, cost, conversions, conversion_value, conversion_date_basis, maturity; Ads UI daily report, account timezone, complete dates including historical inactive campaigns and coverage/suppression notes; prior comparable event, 4-8 surrounding non-event weeks, mature post-event dates and current normal baseline, separately labeled.
- `export/external/seasonality_events.csv`: one row per event_id/campaign_id: name, start_at, end_at, timezone, objective, offer, expected_cvr_change, rationale, owner, approval_status, normal_baseline_dates; client calendar snapshot covering relevant past events and next 60 days; add exceptional_future_reason, expected_start/end, estimate_range, evidence_ref.
- `export/custom/seasonality_settings.csv`: account_id/adjustment_id/snapshot_at grain; name, scope_type, campaign_ids, strategy_ids, device_scope, start_at, end_at, timezone, cvr_adjustment_percent, status, supported_control_evidence, source_screen; all current/future Ads seasonality settings including overlapping manager-account scope.

Keep original source labels and stable IDs; filenames are suggested local intake paths, not assumed existing files.
Custom/configuration schemas describe UI/export evidence, not a claim of live API field verification.

**Missing inputs:** List exact missing files/columns, source dates and affected subchecks.
Continue independent inventory or arithmetic with available evidence; skip only dependent checks.
Optional evidence gates only its stated deeper comparison, forecast or test-result analysis.
Unknown settings, authorization, coverage or policy applicability are not false/disabled and are not a passed check.

## Analysis Steps

1. Validate campaign strategy and currently supported scope from settings. Omitted settings are unknown; no adjustment is not inherently a defect.

2. Build normal CVR from mature non-event comparable clicks/conversions, matching weekday, goals and mix. Promotional CVR is NOT the post-event baseline.

3. Estimate future adjustment percent = 100*(expected future CVR / normal CVR - 1), only with nonzero normal baseline, sufficient samples and justified comparable forecasts. Historical event differences are evidence, not automatically the future setting.

4. Google says Smart Bidding manages ordinary seasonality; short 1-7 day events with major expected changes are the intended use. Longer than 14 days may work less well; neither timing nor size alone is a Critical failure.

5. After a promotion, return to normal is expected and needs NO negative adjustment. An exceptional independently justified future below-normal period may merit a scoped negative proposal; never apply retrospective compensation or infer overbidding from CPC alone.

6. Check overlap, dates/timezone, device/campaign scope and unsupported settings. Draft only the justified duration/estimate range with uncertainty, owner, approval, monitoring and end verification. Tracking incidents route to skill-111, not seasonality masking.

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
| Confirmed configured scope/date conflicts create material delivery harm | Critical |
| Configured adjustment contradicts documented exceptional event scope or normal-baseline estimate | Warning |
| Routine post-promotion return, no adjustment, sparse history or uncertain forecast | Info |

Insufficient evidence or sample is Info. Critical requires directly evidenced material delivery, measurement or safety failure.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a conflicting report format.
Each finding includes skill/entity IDs, condition key, severity, observed values and evidence references, exact window,
sample, resolved threshold, recommendation, uncertainty, responsible owner and dependent skipped subchecks.

- Normal/event/post-event/future comparison with dates, samples, calculation and forecast evidence.
- Supported configuration/overlap matrix and request-only positive or exceptional negative proposal; no automatic compensation.

Separate observations, hypotheses and requested changes. No account writes, rule installation, subscriptions,
notifications, exclusions, feed edits, legal certification or external data transfers occur in this review.
Any implementation request must name exact scope/values, approval owner, monitoring and recovery conditions.

[Google seasonality guidance: no negative adjustment after a promotion](https://support.google.com/google-ads/answer/10369906?hl=en).
