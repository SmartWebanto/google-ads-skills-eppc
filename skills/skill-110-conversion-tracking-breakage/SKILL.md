---
name: skill-110-conversion-tracking-breakage
description: "Screen lag-aware conversion anomalies and distinguish suspected measurement failures from confirmed incidents."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: remarketing
  kind: analyst
  data_source: external
  related: [skill-070-conversion-tracking-completeness, skill-071-conversion-tracking-accuracy, skill-075-consent-mode-v2, skill-080-offline-conversion-import, skill-107-conversion-value-accuracy, skill-111-data-exclusion-tracking-incidents]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixTracking | evidence-led audit correction"
---
# Skill 110: Tracking Incident Detection

## Purpose

Screen lag-aware conversion anomalies and distinguish suspected measurement failures from confirmed incidents.
Recommendations are review requests only; do not change accounts, tags, uploads, or configuration.

## Data Requirements

**Applicability:** Campaign/action series with comparable mature history; confirmed incident severity requires independent implementation evidence.

**Required inputs:**
- Base files in `export/`, following [DATA_CONTRACT](../_resources/DATA_CONTRACT.md): `account`, `campaigns`, `conversion_actions`, `campaign_metrics`, `bidding_strategies`.
- Use account timezone, currency, window, snapshot, completeness/filters, and conversion date basis.
- Client profile supplies business objectives, campaign objectives, sales cycle, and conversion/reporting lag where relevant.
- `export/custom/tracking_daily.csv`: account_id/campaign_id/action_id/date/date_basis/device/channel grain, from Ads action reports over at least the chosen comparison cycles plus lag tail.
  Columns: conversions, conversion_value, all_conversions, reporting_mature, currency; record whether action metrics include modeled conversions.
- `export/custom/tracking_traffic_daily.csv`: account_id/campaign_id/date/device/channel grain, from Ads reports for the same window.
  Columns: impressions, clicks, cost, currency; join without summing repeated traffic across action rows.
- `export/external/tracking_context.csv`: account_id/campaign_id/action_id/date grain, from aggregate CRM/site and operations records.
  Columns: business_outcomes, eligible_sessions, expected_weekday_pattern, promotion_status, site_availability, deployment_id, budget_or_goal_change, consent_change, expected_reporting_lag_hours, source_reference; unavailable controls stay null.
- `export/external/tracking_incidents.csv`: incident_id/account_id/campaign_id/action_id/device/channel grain, from incident owner and sanitized tag/upload QA.
  Columns: status_suspected_or_confirmed, detected_at, fault_start, fault_end, timezone, timestamp_precision, fault_type, expected_behavior, observed_behavior, evidence_reference, recovery_verified_at, backfill_status, material_impact_evidence, owner.
  Needed only to confirm incidents; anomaly screening still runs without incident evidence. Exact hourly silence requires timestamped telemetry, not daily rows.
- Supplemental files must record source, extraction timestamp, window start/end, timezone, filters, and completeness.
- Use sanitized settings and aggregate diagnostics; no emails, phones, addresses, cookies, click IDs, credentials, or user-level browsing histories.
- Business-event tokens must be synthetic or locally pseudonymized; never supply reversible mappings or hashed personal identifiers.

**Missing inputs:** Omitted fields are unknown, never false or disabled. Name missing files/columns and skip only dependent checks.
Do not call missing evidence a defect or full pass. An empty table proves absence only when its completeness is attested.

## Analysis Steps

1. Establish per-action campaign/device/channel series with explicit date basis. Preserve missing rows as unknown unless complete reports establish true zeros.
2. Exclude incomplete days and immature interaction-date cohorts or apply an explicitly justified lag model with uncertainty; never compare today's partial conversions to a mature day.
3. Compare mature like weekdays and business cycles, controlling for campaign/goal changes, traffic mix, demand, consent, promotions, and site availability where supplied.
4. Screen drops against a documented baseline and resolved samples. A 50% drop can be a triage heuristic, not proof; use longer aggregation for sparse actions.
5. Stable clicks plus fewer conversions is an anomaly, not a causal diagnosis. Cross-check business outcomes, tag traces, upload errors, and deployment history.
6. Distinguish business downturn, attribution/reporting delay, consent-related changes, and true measurement faults. Missing contextual controls lower confidence rather than imply stable demand.
7. Confirm incidents only with independent reproducible evidence and scope/timestamps. Daily data supports affected dates, not an exact 24-hour silence duration.
8. Verify recovery using restored event flow and mature reporting; late backfill can change the apparent incident. Do not promise a fixed Smart Bidding recovery timeline.
9. Send confirmed measurement incidents to 111 for applicability and exclusion review; do not automatically propose exclusions for every anomaly.

## Thresholds

Use [PARAMETERS](../_resources/PARAMETERS.md); resolve overrides before classifying findings.
Numerical cutoffs are triage heuristics unless explicitly sourced as platform guidance, not causal-loss estimates.
| Condition | Severity |
|---|---|
| Independent evidence confirms material tracking failure in the affected scope | Critical |
| Mature comparable anomaly or reproducible nonmaterial tracking fault warrants investigation | Warning |
| >50% mature conversion drop without confirmation is a screening heuristic, not a fault verdict | Warning |
| Sparse/immature data, incomplete days, missing controls, or timestamp precision limits | Info |

Apply `{{min_impressions}}` to CTR, `{{min_clicks}}` to conversion rates, and `{{min_conversions}}` to CPA/ROAS comparisons on both sides.
Compare mature, complete, like-for-like windows and goals; exclude incomplete days/reporting lag. Never divide by zero.
Direct trace/configuration evidence needs no rate comparison, but Critical additionally needs evidenced material impact.
Historical spend is exposure, not savings; do not invent recovery, revenue, match-rate, or conversion uplift.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md); do not duplicate its format.
Include stable account/campaign/action or other entity IDs, condition key, evidence/window, sample, resolved thresholds, recommendation, uncertainty, and owner.
- Include baseline selection, date basis, lag cutoff, traffic/action samples, contextual controls, and suspected versus confirmed classification.
- Confirmed incidents include owner, evidence, actual time precision, affected scope, and recovery/backfill state; no automatic exclusion.
Separate confirmed defects, contextual risks, optional opportunities, and unassessed checks.
No account writes, legal certification, or automatic remediation are authorized.
