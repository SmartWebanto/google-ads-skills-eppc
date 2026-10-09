---
name: skill-117-ad-schedule-waste-analysis
description: "Identify time-of-week performance and service mismatches without fixed bid changes or guaranteed savings."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: waste
  kind: analyst
  data_source: external
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixOperationsSeasonal | corrected evidence, controls, thresholds and request-only outputs"
---
# Skill 117: Ad Schedule Performance Review

## Purpose

Identify time-of-week performance and service mismatches without fixed bid changes or guaranteed savings.

This is a local evidence review. Recommendations are proposals, not permission to act on an account or disclose client data.

## Data Requirements

**Applicability:** Campaigns with complete date/hour reporting and known objectives; midnight is not inherently off-hours.

**Required inputs:**
- Base `export/` tables: account, campaigns, campaign_metrics, bid_adjustments, using [DATA_CONTRACT](../_resources/DATA_CONTRACT.md).
- Read client objectives, parameter overrides, currency, timezone, snapshot, report completeness, conversion-date basis and lag maturity.
- `export/custom/schedule_hourly.csv`: account_id/campaign_id/date/hour/device/network grain; impressions, clicks, cost, conversions, conversion_value, goal_id; Ads hourly report for 8 complete weeks ending before conversion lag, timezone and daylight-saving ambiguity recorded.
- `export/external/business_hours.csv`: campaign_id/weekday/effective_range grain; timezone, open_at, close_at, live_or_asynchronous_handling, holiday_override, approved_schedule, owner; client operations calendar covering historical and proposed dates.

Keep original source labels and stable IDs; filenames are suggested local intake paths, not assumed existing files.
Custom/configuration schemas describe UI/export evidence, not a claim of live API field verification.

**Missing inputs:** List exact missing files/columns, source dates and affected subchecks.
Continue independent inventory or arithmetic with available evidence; skip only dependent checks.
Optional evidence gates only its stated deeper comparison, forecast or test-result analysis.
Unknown settings, authorization, coverage or policy applicability are not false/disabled and are not a passed check.

## Analysis Steps

1. Align business/account timezones, holidays and daylight saving. Keep dates until incomplete or immature hours are removed.

2. Aggregate counts then rates into weekday/hour heatmaps. Off-hours share = off-hours cost / SAME-window campaign cost, not undeclared budget.

3. Compare recurring blocks across weeks and like-for-like goals with sample gates on both sides. Closed-office leads may still be handled asynchronously.

4. Screen zero-conversion blocks above {{spend_floor}} only after tracking and relevance checks. Neither low CVR nor closed hours prove lost revenue.

5. Propose a limited schedule experiment with outcome metric, guardrails and rollback owner. Manual schedule CPC modifiers require an applicable strategy; do not propose fixed modifiers on Smart Bidding. tCPA device-target behavior is not a schedule CPC control.

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
| Observed schedule conflicts with a documented unavailable-service restriction | Warning |
| Mature comparable block misses client efficiency tolerance | Warning |
| Off-hours share alone or sparse cells | Info |

Insufficient evidence or sample is Info. Critical requires directly evidenced material delivery, measurement or safety failure.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a conflicting report format.
Each finding includes skill/entity IDs, condition key, severity, observed values and evidence references, exact window,
sample, resolved threshold, recommendation, uncertainty, responsible owner and dependent skipped subchecks.

- Dated heatmap, sample, goal and cost denominator; business/account-timezone schedule proposals.
- Control applicability, asynchronous exceptions, experiment safeguards and owner.

Separate observations, hypotheses and requested changes. No account writes, rule installation, subscriptions,
notifications, exclusions, feed edits, legal certification or external data transfers occur in this review.
Any implementation request must name exact scope/values, approval owner, monitoring and recovery conditions.
