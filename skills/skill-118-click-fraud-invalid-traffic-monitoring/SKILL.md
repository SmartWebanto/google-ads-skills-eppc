---
name: skill-118-click-fraud-invalid-traffic-monitoring
description: "Separate filtered invalid traffic from suspected charged traffic and prepare evidence-led review requests."
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
# Skill 118: Invalid Traffic and Billing Evidence Review

## Purpose

Separate filtered invalid traffic from suspected charged traffic and prepare evidence-led review requests.

This is a local evidence review. Recommendations are proposals, not permission to act on an account or disclose client data.

## Data Requirements

**Applicability:** Supported invalid-click reporting; hourly/IP checks require corresponding authorized local evidence.

**Required inputs:**
- Base `export/` tables: account, campaigns, campaign_metrics, using [DATA_CONTRACT](../_resources/DATA_CONTRACT.md).
- Read client objectives, parameter overrides, currency, timezone, snapshot, report completeness, conversion-date basis and lag maturity.
- `export/custom/invalid_click_daily.csv`: account_id/campaign_id/date/network grain; impressions, clicks, cost, conversions, invalid_clicks, invalid_click_rate, denominator_definition; Ads report for 8 complete weeks and incident dates.
- `export/external/invalid_traffic_billing.csv`: account_id/adjustment_or_case_id grain; service_start/end, billed_cost, invalid_activity_credit, currency, case_status, confirmed_charged_invalid_amount, evidence_ref, checked_at; client statements/support outcomes for incident and later credit periods.
- Optional `export/external/traffic_incidents.csv`: incident_id/time_bucket/campaign_id grain; bucket_start/end, timezone, clicks, privacy_safe_source_id, location_basis, suspicious_behavior, charge_link_ref, collection_authorization_ref; approved local hourly server summaries for burst checks, no raw IP/personal data.

Keep original source labels and stable IDs; filenames are suggested local intake paths, not assumed existing files.
Custom/configuration schemas describe UI/export evidence, not a claim of live API field verification.

**Missing inputs:** List exact missing files/columns, source dates and affected subchecks.
Continue independent inventory or arithmetic with available evidence; skip only dependent checks.
Optional evidence gates only its stated deeper comparison, forecast or test-result analysis.
Unknown settings, authorization, coverage or policy applicability are not false/disabled and are not a passed check.

## Analysis Steps

1. Use the native invalid-click denominator; filtered invalid clicks are not billed fraud. Do not calculate invalid rate from paid clicks alone.

2. Compare complete weekday/network baselines; CTR and invalid-rate changes can reflect brand terms, promotions or traffic mix.

3. Hourly bursts require hourly observations; daily rows cannot establish them. Location does not prove bad actors or justify geographic exclusions.

4. Reconcile dated billed charges and later credits; do not allocate account credits to campaigns without evidence. Distinguish filtered counts, suspected paid exposure and authoritative confirmed charged-invalid amounts.

5. Prepare a support-review pack with campaign IDs, dates, evidence and uncertainty. Vendor, IP or geographic control proposals require independent relevance, current supported controls, privacy and owner review; no automatic exclusion or data transmission.

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
| Authoritatively confirmed material charged invalid activity after credits | Critical |
| Unresolved billing-linked suspicious activity | Warning |
| Elevated filtered-invalid rate or CTR alone | Info |

Insufficient evidence or sample is Info. Critical requires directly evidenced material delivery, measurement or safety failure.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a conflicting report format.
Each finding includes skill/entity IDs, condition key, severity, observed values and evidence references, exact window,
sample, resolved threshold, recommendation, uncertainty, responsible owner and dependent skipped subchecks.

- Invalid-click baseline table and exact source definitions; no invented hourly observations or refunds.
- Case-level charged/credited/unresolved reconciliation and request-only support evidence pack.

Separate observations, hypotheses and requested changes. No account writes, rule installation, subscriptions,
notifications, exclusions, feed edits, legal certification or external data transfers occur in this review.
Any implementation request must name exact scope/values, approval owner, monitoring and recovery conditions.
