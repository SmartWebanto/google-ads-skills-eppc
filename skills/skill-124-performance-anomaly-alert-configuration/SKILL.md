---
name: skill-124-performance-anomaly-alert-configuration
description: "Use dated, complete-period baselines to propose alerts; anomalies are not diagnosed failures."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: waste
  kind: operational
  data_source: external
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixOperationsSeasonal | corrected evidence, controls, thresholds and request-only outputs"
---
# Skill 124: Performance Anomaly Alert Proposals

## Purpose

Use dated, complete-period baselines to propose alerts; anomalies are not diagnosed failures.

This is a local evidence review. Recommendations are proposals, not permission to act on an account or disclose client data.

## Data Requirements

**Applicability:** Campaigns or ad groups with daily history at the same stable entity grain.

**Required inputs:**
- Base `export/` tables: account, campaigns, campaign_metrics, using [DATA_CONTRACT](../_resources/DATA_CONTRACT.md).
- Read client objectives, parameter overrides, currency, timezone, snapshot, report completeness, conversion-date basis and lag maturity.
- `export/custom/anomaly_daily.csv`: one row per account_id/campaign_id/date: budget_id, strategy_id, goal_id, impressions, clicks, cost, conversions, conversion_value, conversion_date_basis, maturity; Ads UI daily report, account timezone, complete dates including historical inactive campaigns and coverage/suppression notes; 8 full baseline weeks plus candidate dates. For ad-group alerts additionally supply ad_group_id and do not mix grains.
- `export/custom/anomaly_context.csv`: account_id/entity_id/event_id grain; start_at, end_at, event_type, affected_metrics, incident_confirmed, evidence_ref; Ads change/status history and supplied tracking/seasonal incident log covering baseline/current dates.
- `export/external/alert_policy.csv`: policy_id/entity_scope/metric grain; relative_threshold, absolute_threshold, minimum_baseline_periods, cadence, cooldown, recipient_role, owner, approved_spend_cap, confirmation_required; client monitoring policy at snapshot.

Keep original source labels and stable IDs; filenames are suggested local intake paths, not assumed existing files.
Custom/configuration schemas describe UI/export evidence, not a claim of live API field verification.

**Missing inputs:** List exact missing files/columns, source dates and affected subchecks.
Continue independent inventory or arithmetic with available evidence; skip only dependent checks.
Optional evidence gates only its stated deeper comparison, forecast or test-result analysis.
Unknown settings, authorization, coverage or policy applicability are not false/disabled and are not a passed check.

## Analysis Steps

1. Exclude partial dates and immature conversion periods; baseline each candidate against the same weekday in prior 8 complete weeks, excluding documented incidents/promotions with reasons.

2. For counts use comparable daily observations; for CTR/CVR pool underlying numerator/denominator, not average percentages. CPA/ROAS needs mature sample in candidate and comparator.

3. Calculate relative change and descriptive mean/sample SD from eligible observations. Default screen is BOTH absolute deviation >2 SD AND relative change >30%, with the client absolute-impact floor and baseline minimum. These are triage heuristics, not statistical significance.

4. If baseline mean or SD is zero, relative/Z scores are undefined or degenerate; use client absolute threshold and report that branch. Sparse history yields Info, not an alert-worthy defect.

5. Cross-reference change/lag/demand context; stable clicks and falling conversions do not prove tracking failure. Escalate Critical only with independently confirmed material failure.

6. Draft alert-only configuration with time basis, exclusions, cadence, recipient role, dedupe/cooldown, evidence link, recovery condition and approval owner. Do not configure subscriptions or send alerts.

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
| Independently confirmed material delivery/measurement failure | Critical |
| Complete mature deviation meets BOTH 2-SD and 30% screens plus policy impact floor | Warning |
| Sparse/degenerate baseline or unexplained anomaly below screen | Info |

Insufficient evidence or sample is Info. Critical requires directly evidenced material delivery, measurement or safety failure.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a conflicting report format.
Each finding includes skill/entity IDs, condition key, severity, observed values and evidence references, exact window,
sample, resolved threshold, recommendation, uncertainty, responsible owner and dependent skipped subchecks.

- Per-entity baseline dates, counts, SD, absolute/relative deviations and exact trigger branch.
- Request-only alert configuration plus suspected explanations, owner and dependent skipped checks.

Separate observations, hypotheses and requested changes. No account writes, rule installation, subscriptions,
notifications, exclusions, feed edits, legal certification or external data transfers occur in this review.
Any implementation request must name exact scope/values, approval owner, monitoring and recovery conditions.
